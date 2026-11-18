import express, { type NextFunction, type Request, type Response } from 'express';
import type { CommandRule, Instance, InstanceConfig } from '../shared/types.js';
import { authMiddleware, rateLimit } from './auth.js';
import { config } from './config.js';
import type { LogHub } from './logger.js';
import { isValidInstanceId, type Store } from './store.js';
import type { BotRuntime } from './runtime.js';

const VERSION = '2.0.0';

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function asyncRoute(
  handler: (req: Request, res: Response) => Promise<unknown>,
): (req: Request, res: Response, next: NextFunction) => void {
  return (req, res, next) => {
    handler(req, res).catch(next);
  };
}

export function createApi(store: Store, runtime: BotRuntime, hub: LogHub) {
  const api = express.Router();

  api.use(express.json({ limit: '256kb' }));

  // /health is intentionally unauthenticated: container/orchestrator health
  // checks must work without secrets, and the payload is non-sensitive.
  api.get('/health', (_req, res) => {
    const instances = store.list();
    res.json({
      status: 'ok',
      version: VERSION,
      uptimeSeconds: Math.round(process.uptime()),
      node: process.version,
      library: 'Baileys 6.7.24',
      authRequired: config.authRequired,
      instances: {
        total: instances.length,
        connected: instances.filter((instance) => instance.status === 'connected').length,
      },
    });
  });

  api.use(authMiddleware);
  api.use('/instances', rateLimit(600, 60_000));

  api.get('/instances', (_req, res) => {
    res.json({ instances: store.list().map(withQr(runtime)) });
  });

  api.post(
    '/instances',
    asyncRoute(async (req, res) => {
      const name = typeof req.body?.name === 'string' ? req.body.name : '';
      if (!name.trim()) throw new HttpError(400, 'A bot name is required');
      if (store.list().length >= config.maxInstances) {
        throw new HttpError(400, `Instance limit reached (MAX_INSTANCES=${config.maxInstances})`);
      }
      const instance = await store.create(name);
      hub.info(`Created instance "${instance.name}" (${instance.id})`, instance.id);
      res.status(201).json({ instance });
    }),
  );

  api.get('/instances/:id', (req, res) => {
    const instance = requireInstance(store, req.params.id);
    res.json({ instance: withQr(runtime)(instance) });
  });

  api.patch(
    '/instances/:id',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      const patch: Partial<Instance> = {};
      if (typeof req.body?.name === 'string') {
        const name = req.body.name.trim().slice(0, 60);
        if (!name) throw new HttpError(400, 'Name cannot be empty');
        patch.name = name;
      }
      if (req.body?.config !== undefined) {
        patch.config = validateConfig(req.body.config, instance.config);
      }
      if (req.body?.commands !== undefined) {
        patch.commands = validateCommands(req.body.commands);
      }
      const updated = await store.update(instance.id, patch);
      res.json({ instance: updated });
    }),
  );

  api.delete(
    '/instances/:id',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      await runtime.stop(instance.id).catch(() => {});
      const removed = await store.remove(instance.id);
      hub.info(`Deleted instance "${instance.name}"`, instance.id);
      res.json({ removed });
    }),
  );

  api.post(
    '/instances/:id/start',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      const updated = await runtime.start(instance.id);
      res.json({ instance: updated });
    }),
  );

  api.post(
    '/instances/:id/stop',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      const updated = await runtime.stop(instance.id);
      res.json({ instance: updated });
    }),
  );

  api.post(
    '/instances/:id/restart',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      await runtime.stop(instance.id).catch(() => {});
      const updated = await runtime.start(instance.id);
      hub.info(`Restarted "${instance.name}"`, instance.id);
      res.json({ instance: updated });
    }),
  );

  api.post(
    '/instances/:id/logout',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      const updated = await runtime.stop(instance.id, { logout: true });
      res.json({ instance: updated });
    }),
  );

  api.get('/instances/:id/qr', (req, res) => {
    const instance = requireInstance(store, req.params.id);
    const { qr, pairingCode } = runtime.getQr(instance.id);
    res.json({ qr, pairingCode, status: instance.status });
  });

  api.post(
    '/instances/:id/pairing-code',
    asyncRoute(async (req, res) => {
      const instance = requireInstance(store, req.params.id);
      const phone = String(req.body?.phoneNumber ?? '');
      const code = await runtime.requestPairingCode(instance.id, phone);
      res.json({ pairingCode: code });
    }),
  );

  api.get('/settings', (_req, res) => {
    res.json({ settings: store.settings });
  });

  api.patch(
    '/settings',
    asyncRoute(async (req, res) => {
      const autostart = req.body?.autostartConnectedInstances;
      const logRetention = Number(req.body?.logRetention);
      const settings = await store.updateSettings({
        ...(typeof autostart === 'boolean' && { autostartConnectedInstances: autostart }),
        ...(Number.isFinite(logRetention) && {
          logRetention: Math.min(Math.max(Math.trunc(logRetention), 50), 5000),
        }),
      });
      res.json({ settings });
    }),
  );

  api.get('/logs', (req, res) => {
    const limit = Math.min(Number(req.query.limit) || 200, 1000);
    const instanceId = typeof req.query.instanceId === 'string' ? req.query.instanceId : undefined;
    res.json({ logs: hub.recent(limit, instanceId) });
  });

  api.get('/logs/stream', (req, res) => {
    const instanceId = typeof req.query.instanceId === 'string' ? req.query.instanceId : undefined;
    hub.attach(res, instanceId);
  });

  api.post('/logs/clear', (_req, res) => {
    hub.clear();
    res.json({ cleared: true });
  });

  api.use((_req, _res, next) => next(new HttpError(404, 'Endpoint not found')));

  api.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
    const status = err instanceof HttpError ? err.status : 500;
    const message = err instanceof Error ? err.message : 'Unexpected server error';
    if (status >= 500) hub.error(`API error: ${message}`);
    res.status(status).json({ error: message });
  });

  return api;
}

function requireInstance(store: Store, rawId: string): Instance {
  const id = String(rawId);
  if (!isValidInstanceId(id)) throw new HttpError(400, 'Invalid instance id');
  const instance = store.get(id);
  if (!instance) throw new HttpError(404, `Instance "${id}" not found`);
  return instance;
}

function withQr(runtime: BotRuntime) {
  return (instance: Instance): Instance => {
    const { qr, pairingCode } = runtime.getQr(instance.id);
    return { ...instance, qr, pairingCode };
  };
}

function validateConfig(input: unknown, current: InstanceConfig): InstanceConfig {
  if (typeof input !== 'object' || input === null) {
    throw new HttpError(400, 'config must be an object');
  }
  const value = input as Record<string, unknown>;
  const next: InstanceConfig = { ...current };

  if (typeof value.commandPrefix === 'string') {
    const prefix = value.commandPrefix.trim().slice(0, 3);
    if (!prefix) throw new HttpError(400, 'Command prefix cannot be empty');
    next.commandPrefix = prefix;
  }
  for (const key of ['respondToGroups', 'respondToDms', 'autoReadMessages'] as const) {
    if (typeof value[key] === 'boolean') next[key] = value[key] as boolean;
  }
  if (Array.isArray(value.allowedNumbers)) {
    next.allowedNumbers = parseNumbers(value.allowedNumbers);
  }
  if (Array.isArray(value.blockedNumbers)) {
    next.blockedNumbers = parseNumbers(value.blockedNumbers);
  }
  return next;
}

function parseNumbers(input: unknown[]): string[] {
  const numbers = input
    .map((entry) => String(entry).replace(/\D/g, ''))
    .filter((entry) => entry.length >= 8 && entry.length <= 15);
  return Array.from(new Set(numbers));
}

function validateCommands(input: unknown): CommandRule[] {
  if (!Array.isArray(input)) throw new HttpError(400, 'commands must be an array');
  if (input.length > 100) throw new HttpError(400, 'Too many commands (max 100)');
  const seen = new Set<string>();
  const commands: CommandRule[] = [];
  for (const raw of input) {
    if (typeof raw !== 'object' || raw === null) continue;
    const candidate = raw as Record<string, unknown>;
    const name = String(candidate.name ?? '')
      .toLowerCase()
      .replace(/\s+/g, '');
    if (!name) throw new HttpError(400, 'Every command needs a name');
    if (!/^[a-z0-9_-]{1,32}$/.test(name)) {
      throw new HttpError(400, `Invalid command name "${name}" — use letters, numbers, - or _`);
    }
    if (seen.has(name)) throw new HttpError(400, `Duplicate command "${name}"`);
    seen.add(name);
    const response = String(candidate.response ?? '').trim();
    if (!response) throw new HttpError(400, `Command "${name}" needs a response`);
    commands.push({
      name,
      response: response.slice(0, 4000),
      enabled: candidate.enabled !== false,
      exact: Boolean(candidate.exact),
    });
  }
  return commands;
}
