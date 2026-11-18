/**
 * Types shared between the server and the browser client.
 * Keep this file dependency-free so it can be imported from both.
 */

export type InstanceStatus =
  'stopped' | 'starting' | 'qr' | 'pairing' | 'connected' | 'reconnecting' | 'logged_out' | 'error';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'success';

export interface LogEntry {
  id: string;
  instanceId: string | null;
  ts: number;
  level: LogLevel;
  source: 'manager' | 'whatsapp' | 'command' | 'system';
  message: string;
}

export interface WhatsAppIdentity {
  id: string;
  name?: string;
  number?: string;
}

export interface CommandRule {
  /** Trigger without the prefix, e.g. "ping". Lowercase, no spaces. */
  name: string;
  /** Reply text. Supports {{sender}}, {{command}}, {{args}}, {{instance}}, {{uptime}}. */
  response: string;
  /** If true, the whole message (not just a command) is matched. */
  exact?: boolean;
  enabled: boolean;
}

export interface InstanceConfig {
  /** Workspace policy (chat jid or "groups"/"dms") where commands are allowed. */
  commandPrefix: string;
  respondToGroups: boolean;
  respondToDms: boolean;
  /** Only reply to these numbers (empty = everyone). Stored digit-only. */
  allowedNumbers: string[];
  /** Never reply to these numbers. */
  blockedNumbers: string[];
  autoReadMessages: boolean;
}

export interface InstanceStats {
  messagesReceived: number;
  messagesSent: number;
  commandsHandled: number;
  errors: number;
  startedAt: number | null;
  lastActivityAt: number | null;
}

export interface Instance {
  id: string;
  name: string;
  status: InstanceStatus;
  /** ISO timestamp of creation. */
  createdAt: string;
  identity: WhatsAppIdentity | null;
  config: InstanceConfig;
  commands: CommandRule[];
  stats: InstanceStats;
  lastError: string | null;
  /** Populated for GET /api/instances/:id/qr only. */
  qr?: string | null;
  pairingCode?: string | null;
}

export interface ManagerSettings {
  autostartConnectedInstances: boolean;
  logRetention: number;
  commandPrefixDefault: string;
}

export interface HealthPayload {
  status: 'ok';
  version: string;
  uptimeSeconds: number;
  node: string;
  library: string;
  /** True when the server expects an API token. */
  authRequired: boolean;
  instances: { total: number; connected: number };
}

export interface ApiErrorBody {
  error: string;
  details?: string;
}

export const DEFAULT_COMMANDS: CommandRule[] = [
  { name: 'ping', response: 'pong 🏓', enabled: true },
  {
    name: 'help',
    response: 'Available commands: {{commands}}\n\nPrefix: {{prefix}}',
    enabled: true,
  },
  {
    name: 'info',
    response:
      '🤖 {{instance}}\nStatus: {{status}}\nUptime: {{uptime}}\nMessages seen: {{received}}',
    enabled: true,
  },
];

export const DEFAULT_CONFIG: InstanceConfig = {
  commandPrefix: '!',
  respondToGroups: true,
  respondToDms: true,
  allowedNumbers: [],
  blockedNumbers: [],
  autoReadMessages: false,
};

export const DEFAULT_STATS: InstanceStats = {
  messagesReceived: 0,
  messagesSent: 0,
  commandsHandled: 0,
  errors: 0,
  startedAt: null,
  lastActivityAt: null,
};
