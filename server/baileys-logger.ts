import type { LogHub } from './logger.js';

type Level = 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal';

/**
 * Baileys expects a pino-compatible logger. Wiring pino straight into our log
 * hub would either spam the UI or leak QR/credential material, so we expose a
 * minimal, level-aware adapter instead.
 */
export function createBaileysLogger(hub: LogHub, instanceId: string, level: Level = 'warn') {
  const order: Level[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal'];

  const make = (currentLevel: Level): Record<string, unknown> => {
    const log = (entryLevel: Level) => (context: unknown, message?: unknown) => {
      if (order.indexOf(entryLevel) < order.indexOf(currentLevel)) return;
      if (entryLevel === 'trace' || entryLevel === 'debug') return;
      const text =
        typeof message === 'string'
          ? message
          : typeof context === 'string'
            ? context
            : JSON.stringify(context);
      // Credentials and QR payloads must never reach the browser.
      if (/cred|qr|noise|signal/i.test(String(text))) return;
      hub.push(
        entryLevel === 'fatal' ? 'error' : (entryLevel as 'info' | 'warn' | 'error'),
        'whatsapp',
        String(text).slice(0, 500),
        instanceId,
      );
    };

    const instance: Record<string, unknown> = {
      level: currentLevel,
      child: () => make(currentLevel),
    };
    for (const entryLevel of order) instance[entryLevel] = log(entryLevel);
    return instance;
  };

  return make(level);
}
