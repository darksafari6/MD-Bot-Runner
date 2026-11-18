import type { CommandRule, Instance } from '../shared/types.js';

export interface IncomingMessageContext {
  /** Digits only, e.g. "923001234567". */
  senderNumber: string;
  senderJid: string;
  isGroup: boolean;
  chatJid: string;
  text: string;
}

export interface CommandMatch {
  rule: CommandRule;
  args: string;
}

export interface CommandDecision {
  /** Whether the message should be answered at all. */
  allowed: boolean;
  /** Reason the message was ignored, for the instance log. */
  reason?: string;
  match?: CommandMatch;
}

/**
 * Pure decision function: given an instance configuration and an inbound
 * message, decide if we answer and with which rule. No I/O, so it is fully
 * unit-testable — see test/commands.test.ts.
 */
export function decideReply(instance: Instance, message: IncomingMessageContext): CommandDecision {
  const { config } = instance;

  if (message.isGroup && !config.respondToGroups) {
    return { allowed: false, reason: 'group replies disabled' };
  }
  if (!message.isGroup && !config.respondToDms) {
    return { allowed: false, reason: 'DM replies disabled' };
  }
  if (config.blockedNumbers.includes(message.senderNumber)) {
    return { allowed: false, reason: 'sender is blocked' };
  }
  if (config.allowedNumbers.length > 0 && !config.allowedNumbers.includes(message.senderNumber)) {
    return { allowed: false, reason: 'sender is not on the allowlist' };
  }

  const text = message.text.trim();
  if (!text) return { allowed: false, reason: 'empty message' };

  const prefix = config.commandPrefix;
  const enabledRules = instance.commands.filter((rule) => rule.enabled);

  if (text.startsWith(prefix)) {
    const withoutPrefix = text.slice(prefix.length).trim();
    const [rawName, ...rest] = withoutPrefix.split(/\s+/);
    const name = (rawName ?? '').toLowerCase();
    const rule = enabledRules.find((candidate) => candidate.name === name);
    if (!rule) return { allowed: false, reason: `unknown command "${name}"` };
    return { allowed: true, match: { rule, args: rest.join(' ') } };
  }

  const exact = enabledRules.find((rule) => rule.exact && rule.name === text.toLowerCase());
  if (exact) return { allowed: true, match: { rule: exact, args: '' } };

  return { allowed: false, reason: 'no command matched' };
}

export interface RenderContext {
  senderName: string;
  instanceName: string;
  status: string;
  uptimeSeconds: number;
  received: number;
  prefix: string;
}

/** Replace {{placeholders}} in a command response. Unknown keys stay literal. */
export function renderResponse(
  template: string,
  args: string,
  rule: CommandRule,
  context: RenderContext,
): string {
  const values: Record<string, string> = {
    sender: context.senderName,
    args: args || '(none)',
    command: rule.name,
    instance: context.instanceName,
    status: context.status,
    uptime: formatUptime(context.uptimeSeconds),
    received: String(context.received),
    prefix: context.prefix,
    commands: '',
  };
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (whole, key: string) =>
    key in values ? values[key] : whole,
  );
}

export function formatUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0s';
  const units: Array<[string, number]> = [
    ['d', 86400],
    ['h', 3600],
    ['m', 60],
    ['s', 1],
  ];
  const parts: string[] = [];
  let remaining = Math.floor(seconds);
  for (const [suffix, size] of units) {
    const value = Math.floor(remaining / size);
    if (value > 0) {
      parts.push(`${value}${suffix}`);
      remaining -= value * size;
    }
    if (parts.length === 2) break;
  }
  return parts.join(' ') || '0s';
}
