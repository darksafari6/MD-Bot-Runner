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
  /** Character(s) that introduce a command, e.g. "!" or ".". */
  commandPrefix: string;
  respondToGroups: boolean;
  respondToDms: boolean;
  /** Only reply to these numbers (empty = everyone). Stored digit-only. */
  allowedNumbers: string[];
  /** Never reply to these numbers. */
  blockedNumbers: string[];
  autoReadMessages: boolean;
  /**
   * Messages per minute allowed outbound. Applies to command replies and
   * messages sent from the panel, protecting the number from rate-limit bans.
   */
  outboundLimitPerMinute: number;
  /** Minimum spacing between two outbound messages, in milliseconds. */
  outboundMinGapMs: number;
  /** Show "typing…" before replying, which looks far less robotic. */
  sendTypingIndicator: boolean;
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

export type MessageDirection = 'in' | 'out';
export type MessageKind = 'text' | 'image' | 'video' | 'audio' | 'document' | 'sticker' | 'other';

export interface InboxMessage {
  id: string;
  instanceId: string;
  chatJid: string;
  number: string | null;
  chatName: string;
  senderJid: string;
  senderName: string;
  direction: MessageDirection;
  origin: 'command' | 'manual' | 'system';
  text: string;
  kind: MessageKind;
  ts: number;
  error?: string;
}

export interface Conversation {
  chatJid: string;
  chatName: string;
  number: string | null;
  isGroup: boolean;
  lastMessage: string;
  lastTs: number;
  count: number;
  unread: number;
  lastDirection: MessageDirection;
}

export interface SendMessageRequest {
  /** Phone number ("+92 300 1234567") or jid ("…@g.us"). */
  to: string;
  text: string;
}

export interface SendMessageResult {
  queued: boolean;
  message: InboxMessage;
  /** Milliseconds the message waited for the throttle. */
  waitedMs: number;
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
  outboundLimitPerMinute: 20,
  outboundMinGapMs: 1200,
  sendTypingIndicator: true,
};

/** Bounds enforced by the API so a typo cannot disable pacing entirely. */
export const THROTTLE_LIMITS = {
  minPerMinute: 1,
  maxPerMinute: 60,
  minGapMs: 250,
  maxGapMs: 30_000,
} as const;

export const DEFAULT_STATS: InstanceStats = {
  messagesReceived: 0,
  messagesSent: 0,
  commandsHandled: 0,
  errors: 0,
  startedAt: null,
  lastActivityAt: null,
};
