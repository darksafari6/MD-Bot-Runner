import { describe, expect, it } from 'vitest';
import {
  decideReply,
  formatUptime,
  renderResponse,
  type IncomingMessageContext,
} from '../server/commands.js';
import { friendlyConnectionError } from '../server/runtime.js';
import { DEFAULT_COMMANDS, DEFAULT_CONFIG, DEFAULT_STATS, type Instance } from '../shared/types.js';

function makeInstance(overrides: Partial<Instance> = {}): Instance {
  return {
    id: 'test-bot',
    name: 'Test Bot',
    status: 'connected',
    createdAt: new Date().toISOString(),
    identity: null,
    config: { ...DEFAULT_CONFIG },
    commands: structuredClone(DEFAULT_COMMANDS),
    stats: { ...DEFAULT_STATS },
    lastError: null,
    ...overrides,
  };
}

function msg(partial: Partial<IncomingMessageContext> = {}): IncomingMessageContext {
  return {
    senderNumber: '923001234567',
    senderJid: '923001234567@s.whatsapp.net',
    isGroup: false,
    chatJid: '923001234567@s.whatsapp.net',
    text: '!ping',
    ...partial,
  };
}

describe('decideReply', () => {
  it('matches a known command by prefix', () => {
    const result = decideReply(makeInstance(), msg());
    expect(result.allowed).toBe(true);
    expect(result.match?.rule.name).toBe('ping');
  });

  it('passes arguments through', () => {
    const result = decideReply(makeInstance(), msg({ text: '!ping hello world' }));
    expect(result.match?.args).toBe('hello world');
  });

  it('ignores plain chatter without a prefix', () => {
    const result = decideReply(makeInstance(), msg({ text: 'good morning' }));
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/no command matched/);
  });

  it('rejects unknown commands', () => {
    const result = decideReply(makeInstance(), msg({ text: '!nope' }));
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/unknown command/);
  });

  it('respects a custom prefix', () => {
    const instance = makeInstance({ config: { ...DEFAULT_CONFIG, commandPrefix: '.' } });
    expect(decideReply(instance, msg({ text: '.ping' })).allowed).toBe(true);
    expect(decideReply(instance, msg({ text: '!ping' })).allowed).toBe(false);
  });

  it('honours the group toggle', () => {
    const instance = makeInstance({ config: { ...DEFAULT_CONFIG, respondToGroups: false } });
    const result = decideReply(instance, msg({ isGroup: true, chatJid: '123@g.us' }));
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/group/);
  });

  it('honours the DM toggle', () => {
    const instance = makeInstance({ config: { ...DEFAULT_CONFIG, respondToDms: false } });
    expect(decideReply(instance, msg()).allowed).toBe(false);
  });

  it('blocks blocklisted numbers', () => {
    const instance = makeInstance({
      config: { ...DEFAULT_CONFIG, blockedNumbers: ['923001234567'] },
    });
    expect(decideReply(instance, msg()).allowed).toBe(false);
  });

  it('enforces a non-empty allowlist', () => {
    const instance = makeInstance({
      config: { ...DEFAULT_CONFIG, allowedNumbers: ['447700900123'] },
    });
    expect(decideReply(instance, msg()).allowed).toBe(false);
    expect(decideReply(instance, msg({ senderNumber: '447700900123' })).allowed).toBe(true);
  });

  it('skips disabled commands', () => {
    const instance = makeInstance({
      commands: [{ name: 'ping', response: 'pong', enabled: false }],
    });
    expect(decideReply(instance, msg()).allowed).toBe(false);
  });

  it('supports exact matches without a prefix', () => {
    const instance = makeInstance({
      commands: [{ name: 'hello', response: 'hi', enabled: true, exact: true }],
    });
    expect(decideReply(instance, msg({ text: 'Hello' })).allowed).toBe(true);
    expect(decideReply(instance, msg({ text: 'hello there' })).allowed).toBe(false);
  });

  it('rejects empty messages', () => {
    expect(decideReply(makeInstance(), msg({ text: '   ' })).allowed).toBe(false);
  });
});

describe('renderResponse', () => {
  const context = {
    senderName: 'Ali',
    instanceName: 'Support Bot',
    status: 'connected',
    uptimeSeconds: 3725,
    received: 12,
    prefix: '!',
  };

  it('substitutes placeholders', () => {
    const out = renderResponse(
      'Hi {{sender}}, this is {{instance}} ({{uptime}}, {{received}} msgs)',
      '',
      { name: 'x', response: '', enabled: true },
      context,
    );
    expect(out).toBe('Hi Ali, this is Support Bot (1h 2m, 12 msgs)');
  });

  it('leaves unknown placeholders untouched', () => {
    const out = renderResponse(
      '{{unknown}}',
      '',
      { name: 'x', response: '', enabled: true },
      context,
    );
    expect(out).toBe('{{unknown}}');
  });

  it('reports missing args', () => {
    const out = renderResponse(
      'args: {{args}}',
      '',
      { name: 'x', response: '', enabled: true },
      context,
    );
    expect(out).toBe('args: (none)');
  });
});

describe('formatUptime', () => {
  it.each([
    [0, '0s'],
    [45, '45s'],
    [90, '1m 30s'],
    [3725, '1h 2m'],
    [90000, '1d 1h'],
  ])('formats %i seconds as %s', (input, expected) => {
    expect(formatUptime(input)).toBe(expected);
  });
});

describe('friendlyConnectionError', () => {
  it('explains blocked HTTPS egress clearly', () => {
    const message = friendlyConnectionError('WebSocket Error (TLS handshake failed)', 1, 2000);
    expect(message).toMatch(/Cannot reach WhatsApp servers/);
    expect(message).toMatch(/outbound HTTPS/);
  });

  it('reports unlinked devices', () => {
    expect(friendlyConnectionError('logged out', 1)).toMatch(/unlinked/i);
  });

  it('falls back to retry information for other errors', () => {
    expect(friendlyConnectionError('boom', 2, 4000)).toContain('retry 2/8 in 4s');
  });
});
