import fs from 'node:fs/promises';
import path from 'node:path';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
  type WASocket,
  type WAMessage,
  type ConnectionState,
} from '@whiskeysockets/baileys';
import { DEFAULT_STATS, type Instance, type InstanceStats } from '../shared/types.js';
import { config } from './config.js';
import { createBaileysLogger } from './baileys-logger.js';
import { decideReply, renderResponse } from './commands.js';
import type { LogHub } from './logger.js';
import type { Store } from './store.js';

interface RuntimeEvents {
  onChange: (instance: Instance) => void;
}

interface LiveSocket {
  socket: WASocket;
  qr: string | null;
  pairingCode: string | null;
  explicitStop: boolean;
}

const MAX_RECONNECT_ATTEMPTS = 8;
const MAX_BACKOFF_MS = 30_000;

/**
 * Owns every live WhatsApp socket: one Baileys connection per instance.
 * Nothing here is simulated — failures are surfaced through instance status.
 */
export class BotRuntime {
  private live = new Map<string, LiveSocket>();
  private reconnectTimers = new Map<string, NodeJS.Timeout>();
  /** Reconnect attempts for the *current* session, reset on a successful open. */
  private attempts = new Map<string, number>();
  private starting = new Set<string>();

  constructor(
    private readonly store: Store,
    private readonly hub: LogHub,
    private readonly events: RuntimeEvents,
  ) {}

  isLive(id: string): boolean {
    return this.live.has(id);
  }

  liveCount(): number {
    return this.live.size;
  }

  getQr(id: string): { qr: string | null; pairingCode: string | null } {
    const entry = this.live.get(id);
    return { qr: entry?.qr ?? null, pairingCode: entry?.pairingCode ?? null };
  }

  /** Cancel a scheduled reconnect so a manual stop wins the race. */
  private clearReconnect(id: string): void {
    const timer = this.reconnectTimers.get(id);
    if (timer) {
      clearTimeout(timer);
      this.reconnectTimers.delete(id);
    }
  }

  private scheduleReconnect(id: string, delayMs: number): void {
    if (this.reconnectTimers.has(id)) return;
    const timer = setTimeout(() => {
      this.reconnectTimers.delete(id);
      if (this.live.has(id)) return;
      this.hub.info('Reconnecting…', id);
      void this.start(id).catch((err: unknown) => {
        this.hub.error(`Reconnect failed: ${err instanceof Error ? err.message : String(err)}`, id);
      });
    }, delayMs);
    timer.unref?.();
    this.reconnectTimers.set(id, timer);
  }

  async start(id: string): Promise<Instance> {
    const existing = this.store.get(id);
    if (!existing) throw new Error(`Instance "${id}" not found`);
    if (this.live.has(id) || this.starting.has(id)) {
      this.hub.warn(`Instance "${id}" is already running`, id);
      return this.store.get(id)!;
    }
    if (this.live.size + this.starting.size >= config.maxInstances) {
      throw new Error(
        `Instance limit reached (MAX_INSTANCES=${config.maxInstances}). Stop another bot first.`,
      );
    }

    this.clearReconnect(id);
    this.starting.add(id);
    try {
      await this.patch(id, {
        status: 'starting',
        lastError: null,
        identity: null,
        qr: null,
        pairingCode: null,
      });
      this.hub.info(`Starting instance "${existing.name}"`, id);

      const sessionDir = path.join(config.sessionsDir, id);
      await fs.mkdir(sessionDir, { recursive: true });
      const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
      const { version } = await fetchLatestBaileysVersion().catch(() => ({
        version: [2, 3000, 1015901307] as [number, number, number],
      }));

      const logger = createBaileysLogger(this.hub, id);
      const socket = makeWASocket({
        version,
        auth: {
          creds: state.creds,
          keys: makeCacheableSignalKeyStore(state.keys, logger as never),
        },
        logger: logger as never,
        browser: Browsers.ubuntu('Chrome'),
        markOnlineOnConnect: false,
        syncFullHistory: false,
        connectTimeoutMs: 30_000,
        keepAliveIntervalMs: 20_000,
        defaultQueryTimeoutMs: 30_000,
        generateHighQualityLinkPreview: false,
      });

      this.live.set(id, {
        socket,
        qr: null,
        pairingCode: null,
        explicitStop: false,
      });

      socket.ev.on('creds.update', saveCreds);
      socket.ev.on('connection.update', (update: Partial<ConnectionState>) => {
        void this.handleConnectionUpdate(id, update);
      });
      socket.ev.on('messages.upsert', ({ messages, type }) => {
        if (type !== 'notify') return;
        for (const message of messages) {
          void this.handleMessage(id, message);
        }
      });

      this.hub.info(
        state.creds.registered
          ? 'Saved credentials found — restoring session'
          : 'Not linked yet — QR code incoming',
        id,
      );

      return this.store.get(id)!;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.hub.error(`Failed to start "${id}": ${message}`, id);
      await this.patch(id, { status: 'error', lastError: message });
      throw err;
    } finally {
      this.starting.delete(id);
    }
  }

  async stop(id: string, { logout = false } = {}): Promise<Instance> {
    const existing = this.store.get(id);
    if (!existing) throw new Error(`Instance "${id}" not found`);
    this.clearReconnect(id);
    this.attempts.delete(id);

    const entry = this.live.get(id);
    if (!entry) {
      await this.patch(id, {
        status: logout ? 'logged_out' : 'stopped',
        identity: logout ? null : existing.identity,
        qr: null,
        pairingCode: null,
      });
      return this.store.get(id)!;
    }

    entry.explicitStop = true;
    this.live.delete(id);

    try {
      if (logout) {
        await entry.socket.logout().catch(() => {});
        await fs.rm(path.join(config.sessionsDir, id), { recursive: true, force: true });
      } else {
        entry.socket.end(undefined);
      }
    } catch (err) {
      this.hub.warn(
        `Shutdown for "${id}" raised: ${err instanceof Error ? err.message : String(err)}`,
        id,
      );
    }

    await this.patch(id, {
      status: logout ? 'logged_out' : 'stopped',
      identity: logout ? null : existing.identity,
      qr: null,
      pairingCode: null,
      stats: { ...existing.stats, startedAt: null },
    });
    this.hub.info(
      logout ? `Instance "${existing.name}" logged out` : `Instance "${existing.name}" stopped`,
      id,
    );
    return this.store.get(id)!;
  }

  async requestPairingCode(id: string, phoneNumber: string): Promise<string> {
    const entry = this.live.get(id);
    if (!entry) throw new Error('Start the instance before requesting a pairing code');
    const digits = phoneNumber.replace(/\D/g, '');
    if (digits.length < 8 || digits.length > 15) {
      throw new Error('Enter a full international phone number (country code + number)');
    }
    const code = await entry.socket.requestPairingCode(digits);
    entry.pairingCode = code;
    entry.qr = null;
    await this.patch(id, { status: 'pairing', pairingCode: code, qr: null });
    this.hub.info('Pairing code generated — enter it on your phone', id);
    return code;
  }

  async stopAll(): Promise<void> {
    for (const id of this.reconnectTimers.keys()) this.clearReconnect(id);
    await Promise.all([...this.live.keys()].map((id) => this.stop(id).catch(() => {})));
  }

  private async handleConnectionUpdate(
    id: string,
    update: Partial<ConnectionState>,
  ): Promise<void> {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      const entry = this.live.get(id);
      if (entry) {
        entry.qr = qr;
        entry.pairingCode = null;
      }
      await this.patch(id, { status: 'qr', qr });
      this.hub.warn('QR ready — scan with WhatsApp → Linked devices', id);
      return;
    }

    if (connection === 'open') {
      this.attempts.delete(id);
      const entry = this.live.get(id);
      if (entry) {
        entry.qr = null;
        entry.pairingCode = null;
      }
      const user = entry?.socket.user;
      const stats: InstanceStats = this.store.get(id)?.stats ?? { ...DEFAULT_STATS };
      await this.patch(id, {
        status: 'connected',
        qr: null,
        pairingCode: null,
        lastError: null,
        identity: {
          id: user?.id ?? '',
          name: user?.name ?? undefined,
          number: user?.id ? user.id.split(':')[0].split('@')[0] : undefined,
        },
        stats: { ...stats, startedAt: Date.now(), lastActivityAt: Date.now() },
      });
      this.hub.success(
        `Connected as ${user?.name ?? user?.id?.split('@')[0] ?? 'unknown device'}`,
        id,
      );
      return;
    }

    if (connection === 'close') {
      const entry = this.live.get(id);
      if (entry?.explicitStop) return;

      const error = lastDisconnect?.error as
        (Error & { output?: { statusCode?: number } }) | undefined;
      const statusCode = error?.output?.statusCode;
      const detail = error?.message ?? 'connection closed';
      this.live.delete(id);
      const stats: InstanceStats = this.store.get(id)?.stats ?? { ...DEFAULT_STATS };

      if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
        await fs.rm(path.join(config.sessionsDir, id), { recursive: true, force: true });
        await this.patch(id, {
          status: 'logged_out',
          identity: null,
          qr: null,
          lastError: 'Device was unlinked. Re-link to continue.',
          stats: { ...stats, startedAt: null },
        });
        this.hub.error('Device unlinked on the phone — session cleared', id);
        return;
      }

      if (statusCode === DisconnectReason.restartRequired || statusCode === 515) {
        this.hub.info('WhatsApp requested a restart — reconnecting', id);
        await this.patch(id, { status: 'reconnecting', lastError: null });
        this.scheduleReconnect(id, 750);
        return;
      }

      const attempts = (this.attempts.get(id) ?? 0) + 1;
      this.attempts.set(id, attempts);
      if (attempts > MAX_RECONNECT_ATTEMPTS) {
        await this.patch(id, {
          status: 'error',
          qr: null,
          lastError: friendlyConnectionError(detail, attempts),
          stats: { ...stats, startedAt: null },
        });
        this.hub.error('Gave up reconnecting — start the instance manually', id);
        return;
      }

      const delay = Math.min(1000 * 2 ** attempts, MAX_BACKOFF_MS);
      await this.patch(id, {
        status: 'reconnecting',
        qr: null,
        lastError: `${friendlyConnectionError(detail, attempts, delay)}`,
        stats: { ...stats, startedAt: null, errors: stats.errors + 1 },
      });
      this.hub.warn(`Disconnected: ${detail} — retrying in ${Math.round(delay / 1000)}s`, id);
      this.scheduleReconnect(id, delay);
    }
  }

  private async handleMessage(id: string, message: WAMessage): Promise<void> {
    const instance = this.store.get(id);
    if (!instance || !message.message || message.key.fromMe) return;
    const remoteJid = message.key.remoteJid ?? '';
    if (!remoteJid || remoteJid === 'status@broadcast' || remoteJid.endsWith('@newsletter')) {
      return;
    }

    const text =
      message.message.conversation ??
      message.message.extendedTextMessage?.text ??
      message.message.imageMessage?.caption ??
      message.message.videoMessage?.caption ??
      '';

    const isGroup = remoteJid.endsWith('@g.us');
    const senderJid = isGroup ? (message.key.participant ?? remoteJid) : remoteJid;
    const senderNumber = senderJid.split('@')[0].split(':')[0].replace(/\D/g, '');

    const stats = {
      ...instance.stats,
      messagesReceived: instance.stats.messagesReceived + 1,
      lastActivityAt: Date.now(),
    };

    if (instance.config.autoReadMessages) {
      const entry = this.live.get(id);
      await entry?.socket.readMessages([message.key]).catch(() => {});
    }

    const decision = decideReply(instance, {
      senderNumber,
      senderJid,
      isGroup,
      chatJid: remoteJid,
      text,
    });

    if (!decision.allowed || !decision.match) {
      await this.patch(id, { stats });
      return;
    }

    const { rule, args } = decision.match;
    const entry = this.live.get(id);
    if (!entry) return;

    try {
      const uptimeSeconds = instance.stats.startedAt
        ? (Date.now() - instance.stats.startedAt) / 1000
        : 0;
      const commandsList = instance.commands
        .filter((candidate) => candidate.enabled)
        .map((candidate) => `${instance.config.commandPrefix}${candidate.name}`)
        .join(', ');
      const body = renderResponse(rule.response, args, rule, {
        senderName: message.pushName ?? senderNumber,
        instanceName: instance.name,
        status: instance.status,
        uptimeSeconds,
        received: stats.messagesReceived,
        prefix: instance.config.commandPrefix,
      }).replace(/\{\{\s*commands\s*\}\}/g, commandsList);

      await entry.socket.sendMessage(remoteJid, { text: body }, { quoted: message });
      await this.patch(id, {
        stats: {
          ...stats,
          messagesSent: stats.messagesSent + 1,
          commandsHandled: stats.commandsHandled + 1,
        },
      });
      this.hub.push('success', 'command', `«${rule.name}» replied to ${senderNumber}`, id);
    } catch (err) {
      await this.patch(id, { stats: { ...stats, errors: stats.errors + 1 } });
      this.hub.push(
        'error',
        'command',
        `Reply failed: ${err instanceof Error ? err.message : String(err)}`,
        id,
      );
    }
  }

  private async patch(id: string, patch: Partial<Instance>): Promise<void> {
    const updated = await this.store.update(id, patch);
    if (updated) this.events.onChange(updated);
  }
}

/**
 * Turn raw socket noise into something a human can act on. The most common
 * self-hosted failure is simply "this box cannot reach WhatsApp".
 */
export function friendlyConnectionError(detail: string, attempt: number, delayMs = 0): string {
  if (
    /TLS|certificate|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|network socket|ECONNREFUSED|socket hang up/i.test(
      detail,
    )
  ) {
    return `Cannot reach WhatsApp servers (${detail}). Check outbound HTTPS access, DNS, firewall or proxy settings.`;
  }
  if (/logged out|401/i.test(detail)) {
    return 'Device was unlinked. Scan a new QR code to reconnect.';
  }
  if (/connection failure|405/i.test(detail)) {
    return `WhatsApp rejected the connection (${detail}). Retry later or update dependencies.`;
  }
  return delayMs > 0
    ? `${detail} — retry ${attempt}/${MAX_RECONNECT_ATTEMPTS} in ${Math.round(delayMs / 1000)}s`
    : `${detail} — gave up after ${MAX_RECONNECT_ATTEMPTS} attempts`;
}
