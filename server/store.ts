import { randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  DEFAULT_COMMANDS,
  DEFAULT_CONFIG,
  DEFAULT_STATS,
  THROTTLE_LIMITS,
  type Instance,
  type InstanceConfig,
  type ManagerSettings,
} from '../shared/types.js';

interface PersistedState {
  version: 1;
  settings: ManagerSettings;
  instances: Instance[];
}

const DEFAULT_SETTINGS: ManagerSettings = {
  autostartConnectedInstances: true,
  logRetention: 500,
  commandPrefixDefault: '!',
};

const INSTANCE_ID_RE = /^[a-z0-9-]{3,40}$/;

export function isValidInstanceId(id: string): boolean {
  return INSTANCE_ID_RE.test(id);
}

export function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .normalize('NFKD')
    // Strip combining accents so "Böt" becomes "bot", not "bo-t".
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 24);
  return base || 'bot';
}

/**
 * Tiny file-backed store. The previous version of this project described a
 * full database that never existed; a single atomically-written JSON file is
 * plenty for the dozens of instances this manager is designed for and keeps
 * deployment to "npm start".
 */
export class Store {
  private state: PersistedState = { version: 1, settings: DEFAULT_SETTINGS, instances: [] };
  private readonly file: string;
  private writeChain: Promise<void> = Promise.resolve();

  constructor(private readonly dataDir: string) {
    this.file = path.join(dataDir, 'state.json');
  }

  async init(): Promise<void> {
    await fs.mkdir(this.dataDir, { recursive: true });
    try {
      const raw = await fs.readFile(this.file, 'utf8');
      const parsed = JSON.parse(raw) as Partial<PersistedState>;
      this.state = {
        version: 1,
        settings: { ...DEFAULT_SETTINGS, ...(parsed.settings ?? {}) },
        instances: (parsed.instances ?? []).map(normalizeInstance),
      };
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== 'ENOENT') {
        // Corrupt state should not brick the manager: back it up and start clean.
        await fs.rename(this.file, `${this.file}.corrupt-${Date.now()}`).catch(() => {});
      }
      await this.persist();
    }
  }

  private persist(): Promise<void> {
    // Serialise writes so concurrent API calls cannot interleave partial JSON.
    this.writeChain = this.writeChain.then(async () => {
      const tmp = `${this.file}.${randomUUID()}.tmp`;
      await fs.writeFile(tmp, JSON.stringify(this.state, null, 2), 'utf8');
      await fs.rename(tmp, this.file);
    });
    return this.writeChain;
  }

  get settings(): ManagerSettings {
    return this.state.settings;
  }

  list(): Instance[] {
    return this.state.instances.map((instance) => structuredClone(instance));
  }

  get(id: string): Instance | undefined {
    const found = this.state.instances.find((instance) => instance.id === id);
    return found ? structuredClone(found) : undefined;
  }

  async create(name: string, overrides: Partial<Instance> = {}): Promise<Instance> {
    const cleanName = name.trim().slice(0, 60) || 'Untitled bot';
    let id = slugify(cleanName);
    if (this.state.instances.some((instance) => instance.id === id)) {
      id = `${id}-${Math.random().toString(36).slice(2, 6)}`;
    }
    const instance = normalizeInstance({
      ...overrides,
      id,
      name: cleanName,
      status: 'stopped',
      createdAt: new Date().toISOString(),
    });
    this.state.instances.push(instance);
    await this.persist();
    return structuredClone(instance);
  }

  async update(id: string, patch: Partial<Instance>): Promise<Instance | undefined> {
    const index = this.state.instances.findIndex((instance) => instance.id === id);
    if (index === -1) return undefined;
    const merged = normalizeInstance({ ...this.state.instances[index], ...patch, id });
    this.state.instances[index] = merged;
    await this.persist();
    return structuredClone(merged);
  }

  async patchConfig(id: string, patch: Partial<InstanceConfig>): Promise<Instance | undefined> {
    const current = this.get(id);
    if (!current) return undefined;
    return this.update(id, { config: { ...current.config, ...patch } });
  }

  async updateSettings(patch: Partial<ManagerSettings>): Promise<ManagerSettings> {
    this.state.settings = { ...this.state.settings, ...patch };
    await this.persist();
    return { ...this.state.settings };
  }

  async remove(id: string): Promise<boolean> {
    const before = this.state.instances.length;
    this.state.instances = this.state.instances.filter((instance) => instance.id !== id);
    if (this.state.instances.length === before) return false;
    await this.persist();
    return true;
  }

  async flush(): Promise<void> {
    await this.writeChain;
  }
}

/** Repair/normalise anything loaded from disk or sent by clients. */
export function normalizeInstance(input: Partial<Instance> & { id?: string }): Instance {
  const id = (input.id ?? '').trim() || 'bot';
  const config: InstanceConfig = {
    ...DEFAULT_CONFIG,
    ...(input.config ?? {}),
    allowedNumbers: sanitizeNumbers(input.config?.allowedNumbers),
    blockedNumbers: sanitizeNumbers(input.config?.blockedNumbers),
    commandPrefix: (input.config?.commandPrefix ?? DEFAULT_CONFIG.commandPrefix).trim().slice(0, 3),
    outboundLimitPerMinute: clampInt(
      input.config?.outboundLimitPerMinute,
      THROTTLE_LIMITS.minPerMinute,
      THROTTLE_LIMITS.maxPerMinute,
      DEFAULT_CONFIG.outboundLimitPerMinute,
    ),
    outboundMinGapMs: clampInt(
      input.config?.outboundMinGapMs,
      THROTTLE_LIMITS.minGapMs,
      THROTTLE_LIMITS.maxGapMs,
      DEFAULT_CONFIG.outboundMinGapMs,
    ),
    sendTypingIndicator: input.config?.sendTypingIndicator !== false,
  };
  if (!config.commandPrefix) config.commandPrefix = DEFAULT_CONFIG.commandPrefix;

  const commands =
    Array.isArray(input.commands) && input.commands.length
      ? input.commands
          .map((rule) => ({
            name: String(rule?.name ?? '')
              .toLowerCase()
              .replace(/\s+/g, '')
              .slice(0, 32),
            response: String(rule?.response ?? '').slice(0, 4000),
            enabled: rule?.enabled !== false,
            exact: Boolean(rule?.exact),
          }))
          .filter((rule) => rule.name && rule.response)
      : structuredClone(DEFAULT_COMMANDS);

  return {
    id,
    name: String(input.name ?? 'Untitled bot').slice(0, 60),
    status: input.status ?? 'stopped',
    createdAt: input.createdAt ?? new Date().toISOString(),
    identity: input.identity ?? null,
    config,
    commands,
    stats: { ...DEFAULT_STATS, ...(input.stats ?? {}) },
    lastError: input.lastError ?? null,
  };
}

/** Clamp untrusted numeric input into an allowed range. */
export function clampInt(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.trunc(parsed), min), max);
}

function sanitizeNumbers(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value
        .map((entry) => String(entry).replace(/\D/g, ''))
        .filter((entry) => entry.length >= 8 && entry.length <= 15),
    ),
  );
}
