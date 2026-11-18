import path from 'node:path';
import dotenv from 'dotenv';

dotenv.config();

function int(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const dataDir = path.resolve(process.env.WAMANAGER_DATA_DIR ?? path.join(process.cwd(), 'data'));

export const config = {
  port: int(process.env.PORT, 3001),
  host: process.env.HOST ?? '0.0.0.0',
  logLevel: process.env.LOG_LEVEL ?? 'info',
  upgraderLogLevel: process.env.BAILEYS_LOG_LEVEL ?? 'silent',
  dataDir,
  sessionsDir: path.join(dataDir, 'sessions'),
  staticDir: path.resolve(process.env.WAMANAGER_STATIC_DIR ?? path.join(process.cwd(), 'dist')),
  /** When false the API is reachable without a token (single-user local use). */
  get apiToken() {
    return process.env.API_TOKEN?.trim() || null;
  },
  get authRequired() {
    return Boolean(process.env.API_TOKEN?.trim());
  },
  /** Max number of live Baileys sockets this process will run. */
  maxInstances: int(process.env.MAX_INSTANCES, 10),
  /** How many log lines to keep in memory per process. */
  logBuffer: int(process.env.LOG_BUFFER, 2000),
  get corsOrigins() {
    return (process.env.CORS_ORIGINS ?? '')
      .split(',')
      .map((origin) => origin.trim())
      .filter(Boolean);
  },
} as const;

export const isProduction = process.env.NODE_ENV === 'production';
