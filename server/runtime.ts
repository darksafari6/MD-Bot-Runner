import fs from 'node:fs/promises';
import path from 'node:path';
import makeWASocket, {
  Browsers,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
  type WASocket,
  type WAMessage,
  type ConnectionState,
} from '@whiskeysockets/baileys';
import {
  DEFAULT_STATS,
  type Instance,
  type InstanceStats,
  type SendMessageResult,
} from '../shared/types.js';
import { config } from './config.js';
import { createBaileysLogger } from './baileys-logger.js';
import { decideReply, renderResponse } from './commands.js';
import { describeJid, isGroupJid, parseTarget } from './jid.js';
import { previewText, type Inbox } from './inbox.js';
import type { LogHub } from './logger.js';
import { MAX_RECONNECT_ATTEMPTS, classifyDisconnect, extractMessage } from './messages.js';
import type { Store } from './store.js';
import { Throttle, typingDelayMs } from './throttle.js';

/** Error with an HTTP status, so the API can answer with the right code. */
export class RuntimeError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'RuntimeError';
  }
}

interface RuntimeEvents {
  onChange: (instance: Instance) => void;
  /** Called after a message is recorded, so the API can push it to the UI. */
  onMessage?: (instanceId: string) => void;
}

interface LiveSocket {
  socket: WASocket;
  qr: string | null;
  pairingCode: string | null;
  explicitStop: boolean;
}

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
  /** Per-instance outbound pacing, rebuilt when the config changes. */
  private throttles = new Map<string, Throttle>();

  constructor(
    private readonly store: Store,
    private readonly hub: LogHub,
    private readonly events: RuntimeEvents,
    private readonly inbox: Inbox,
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

  /** Outbound capacity left in this instance's window (for the UI). */
  throttleStatus(id: string): { remaining: number; limit: number; minGapMs: number } {
    const instance = this.store.get(id);
    const throttle = this.throttleFor(instance);
    return {
      remaining: throttle.remaining(),
      limit: instance?.config.outboundLimitPerMinute ?? 0,
      minGapMs: instance?.config.outboundMinGapMs ?? 0,
    };
  }

  private throttleFor(instance: Instance | undefined): Throttle {
    if (!instance) return new Throttle();
    const cached = this.throttles.get(instance.id);
    const policy = {
      limit: instance.config.outboundLimitPerMinute,
      windowMs: 60_000,
      minGapMs: instance.config.outboundMinGapMs,
    };
    if (cached) {
      const current = cached.policySnapshot;
      const same =
        current.limit === policy.limit &&
        current.windowMs === policy.windowMs &&
        current.minGapMs === policy.minGapMs;
      if (same) return cached;
    }
    const fresh = new Throttle(policy);
    this.throttles.set(instance.id, fresh);
    return fresh;
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
    this.throttles.delete(id);

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
      const error = lastDisconnect?.error as
        (Error & { output?: { statusCode?: number } }) | undefined;
      const statusCode = error?.output?.statusCode;
      const detail = error?.message ?? 'connection closed';

      if (entry?.explicitStop) return;
      this.live.delete(id);

      const attempt = (this.attempts.get(id) ?? 0) + 1;
      this.attempts.set(id, attempt);
      // The whole reconnect policy lives in classifyDisconnect so it can be
      // unit tested without a socket — see test/messages.test.ts.
      const action = classifyDisconnect({
        statusCode,
        explicitStop: Boolean(entry?.explicitStop),
        attempt,
      });
      const stats: InstanceStats = this.store.get(id)?.stats ?? { ...DEFAULT_STATS };

      switch (action.type) {
        case 'ignore':
          return;

        case 'logged_out': {
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

        case 'restart_now':
          this.hub.info('WhatsApp requested a restart — reconnecting', id);
          await this.patch(id, { status: 'reconnecting', lastError: null });
          this.scheduleReconnect(id, 750);
          return;

        case 'give_up':
          await this.patch(id, {
            status: 'error',
            qr: null,
            lastError: friendlyConnectionError(detail, attempt),
            stats: { ...stats, startedAt: null },
          });
          this.hub.error('Gave up reconnecting — start the instance manually', id);
          return;

        case 'retry':
          await this.patch(id, {
            status: 'reconnecting',
            qr: null,
            lastError: friendlyConnectionError(detail, attempt, action.delayMs),
            stats: { ...stats, startedAt: null, errors: stats.errors + 1 },
          });
          this.hub.warn(
            `Disconnected: ${detail} — retrying in ${Math.round(action.delayMs / 1000)}s`,
            id,
          );
          this.scheduleReconnect(id, action.delayMs);
          return;
      }
    }
  }

  /**
   * Central outbound path. Every message the bot sends — command replies and
   * manual sends — goes through here so throttling and inbox recording can
   * never be bypassed.
   */
  private async deliver(
    instance: Instance,
    entry: LiveSocket,
    chatJid: string,
    text: string,
    origin: 'command' | 'manual',
    options: { quoted?: WAMessage; record?: boolean } = {},
  ): Promise<{ waitedMs: number }> {
    const throttle = this.throttleFor(instance);
    const reservation = throttle.reserve();
    if (reservation.delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, reservation.delayMs));
    }

    if (instance.config.sendTypingIndicator) {
      // Best effort: presence failures must never block a send.
      await entry.socket.sendPresenceUpdate('composing', chatJid).catch(() => {});
      const pause = typingDelayMs(text);
      await new Promise((resolve) => setTimeout(resolve, Math.min(pause, 2_500)));
      await entry.socket.sendPresenceUpdate('paused', chatJid).catch(() => {});
    }

    const sent = await entry.socket.sendMessage(
      chatJid,
      { text },
      options.quoted ? { quoted: options.quoted } : undefined,
    );

    if (options.record !== false) {
      const target = describeJid(chatJid);
      this.inbox.add({
        instanceId: instance.id,
        chatJid,
        number: isGroupJid(chatJid) ? null : chatJid.split('@')[0].split(':')[0],
        chatName: target,
        senderJid: entry.socket.user?.id ?? '',
        senderName: 'Bot',
        direction: 'out',
        origin,
        text,
        kind: 'text',
        ts: Date.now(),
      });
      this.events.onMessage?.(instance.id);
    }
    void sent;
    return { waitedMs: reservation.delayMs };
  }

  /**
   * Send a message from the panel. Returns once WhatsApp accepts it, which may
   * be after a throttle wait — the delay is reported so the UI can explain it.
   */
  async sendMessage(id: string, to: string, text: string): Promise<SendMessageResult> {
    const instance = this.store.get(id);
    if (!instance) throw new RuntimeError(404, `Instance "${id}" not found`);

    // Validate the input first: a bad recipient is a 400 regardless of state.
    const target = parseTarget(to);
    if (!target) {
      throw new RuntimeError(
        400,
        'Enter a valid phone number (country code included) or chat jid.',
      );
    }
    const body = text.trim();
    if (!body) throw new RuntimeError(400, 'Message text cannot be empty');
    if (body.length > 4096)
      throw new RuntimeError(400, 'Message is too long (max 4096 characters)');

    if (instance.status !== 'connected') {
      throw new RuntimeError(409, 'This bot is not connected. Start it and link a device first.');
    }
    const entry = this.live.get(id);
    if (!entry) throw new RuntimeError(409, 'This bot has no live connection.');

    const { waitedMs } = await this.deliver(instance, entry, target.jid, body, 'manual', {
      record: false,
    });

    const message = this.inbox.add({
      instanceId: id,
      chatJid: target.jid,
      number: target.number,
      chatName: describeJid(target.jid),
      senderJid: entry.socket.user?.id ?? '',
      senderName: 'Bot',
      direction: 'out',
      origin: 'manual',
      text: body,
      kind: 'text',
      ts: Date.now(),
    });
    this.events.onMessage?.(id);

    const stats = this.store.get(id)?.stats ?? { ...DEFAULT_STATS };
    await this.patch(id, {
      stats: { ...stats, messagesSent: stats.messagesSent + 1, lastActivityAt: Date.now() },
    });
    this.hub.success(`Sent to ${target.jid.split('@')[0]}: ${previewText(body)}`, id);

    return { queued: waitedMs > 0, message, waitedMs };
  }

  private async handleMessage(id: string, message: WAMessage): Promise<void> {
    const instance = this.store.get(id);
    if (!instance) return;

    const extracted = extractMessage(message);
    if (!extracted) return;

    const stats = {
      ...instance.stats,
      messagesReceived: instance.stats.messagesReceived + 1,
      lastActivityAt: Date.now(),
    };

    // Record inbound traffic for the inbox regardless of command matching.
    this.inbox.add({
      instanceId: id,
      chatJid: extracted.chatJid,
      number: isGroupJid(extracted.chatJid) ? null : extracted.senderNumber,
      chatName: describeJid(extracted.chatJid),
      senderJid: extracted.senderJid,
      senderName: extracted.senderName,
      direction: 'in',
      origin: 'system',
      text: extracted.text,
      kind: extracted.kind,
      ts: extracted.timestamp,
    });
    this.events.onMessage?.(id);

    if (instance.config.autoReadMessages) {
      const live = this.live.get(id);
      await live?.socket.readMessages([message.key]).catch(() => {});
    }

    // Media without a caption cannot match a text command.
    if (extracted.mediaOnly) {
      await this.patch(id, { stats });
      return;
    }

    const decision = decideReply(instance, {
      senderNumber: extracted.senderNumber,
      senderJid: extracted.senderJid,
      isGroup: extracted.isGroup,
      chatJid: extracted.chatJid,
      text: extracted.text,
    });

    const entry = this.live.get(id);
    if (!decision.allowed || !decision.match || !entry) {
      await this.patch(id, { stats });
      return;
    }

    const { rule, args } = decision.match;
    try {
      const uptimeSeconds = instance.stats.startedAt
        ? (Date.now() - instance.stats.startedAt) / 1000
        : 0;
      const commandsList = instance.commands
        .filter((candidate) => candidate.enabled)
        .map((candidate) => `${instance.config.commandPrefix}${candidate.name}`)
        .join(', ');
      const body = renderResponse(rule.response, args, rule, {
        senderName: extracted.senderName,
        instanceName: instance.name,
        status: instance.status,
        uptimeSeconds,
        received: stats.messagesReceived,
        prefix: instance.config.commandPrefix,
      }).replace(/\{\{\s*commands\s*\}\}/g, commandsList);

      await this.deliver(instance, entry, extracted.chatJid, body, 'command', {
        quoted: message,
        record: false,
      });

      await this.patch(id, {
        stats: {
          ...stats,
          messagesSent: stats.messagesSent + 1,
          commandsHandled: stats.commandsHandled + 1,
        },
      });
      this.hub.push(
        'success',
        'command',
        `«${rule.name}» replied to ${extracted.senderNumber || extracted.chatJid}`,
        id,
      );
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
