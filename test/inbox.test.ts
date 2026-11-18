import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Inbox, previewText } from '../server/inbox.js';

function message(overrides: Partial<Parameters<Inbox['add']>[0]> = {}) {
  return {
    instanceId: 'bot-a',
    chatJid: '923001234567@s.whatsapp.net',
    number: '923001234567',
    chatName: 'Ali',
    senderJid: '923001234567@s.whatsapp.net',
    senderName: 'Ali',
    direction: 'in' as const,
    origin: 'command' as const,
    text: 'hello',
    kind: 'text' as const,
    ts: 1_700_000_000_000,
    ...overrides,
  };
}

let inbox: Inbox;
beforeEach(() => {
  inbox = new Inbox();
});

describe('Inbox', () => {
  it('stores messages with generated ids', () => {
    const stored = inbox.add(message());
    expect(stored.id).toBeTruthy();
    expect(inbox.query({ instanceId: 'bot-a' })).toHaveLength(1);
  });

  it('isolates instances', () => {
    inbox.add(message());
    inbox.add(message({ instanceId: 'bot-b' }));
    expect(inbox.query({ instanceId: 'bot-a' })).toHaveLength(1);
    expect(inbox.query({ instanceId: 'bot-b' })).toHaveLength(1);
  });

  it('filters by chat and direction', () => {
    inbox.add(message());
    inbox.add(message({ direction: 'out', text: 'pong', chatJid: 'other@s.whatsapp.net' }));
    expect(
      inbox.query({ instanceId: 'bot-a', chatJid: '923001234567@s.whatsapp.net' }),
    ).toHaveLength(1);
    expect(inbox.query({ instanceId: 'bot-a', direction: 'out' })).toHaveLength(1);
  });

  it('counts unread inbound messages and clears them on read', () => {
    inbox.add(message());
    inbox.add(message());
    inbox.add(message({ direction: 'out', text: 'reply' }));
    expect(inbox.totalUnread('bot-a')).toBe(2);
    inbox.markRead('bot-a', '923001234567@s.whatsapp.net');
    expect(inbox.totalUnread('bot-a')).toBe(0);
  });

  it('builds conversations newest-first with last message', () => {
    inbox.add(message({ ts: 1_000, text: 'first' }));
    inbox.add(message({ ts: 2_000, text: 'second' }));
    inbox.add(message({ ts: 3_000, chatJid: '447700900123@s.whatsapp.net', text: 'other chat' }));

    const conversations = inbox.conversations('bot-a');
    expect(conversations).toHaveLength(2);
    expect(conversations[0].lastMessage).toBe('other chat');
    expect(conversations[1]).toMatchObject({ lastMessage: 'second', count: 2 });
  });

  it('shows a placeholder for caption-less media in previews', () => {
    inbox.add(message({ kind: 'image', text: '' }));
    expect(inbox.conversations('bot-a')[0].lastMessage).toBe('[image]');
  });

  it('caps stored messages per instance', () => {
    for (let index = 0; index < 620; index += 1) {
      inbox.add(message({ ts: 1_000 + index, text: `m${index}` }));
    }
    const stored = inbox.query({ instanceId: 'bot-a', limit: 500 });
    expect(stored.length).toBeLessThanOrEqual(500);
    // The newest message must survive trimming.
    expect(stored[stored.length - 1].text).toBe('m619');
  });

  it('limits query results', () => {
    for (let index = 0; index < 20; index += 1) inbox.add(message({ ts: index }));
    expect(inbox.query({ instanceId: 'bot-a', limit: 5 })).toHaveLength(5);
  });

  it('notifies subscribers and stops after unsubscribe', () => {
    const listener = vi.fn();
    const unsubscribe = inbox.subscribe(listener);
    inbox.add(message());
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    inbox.add(message());
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('clears by instance or entirely', () => {
    inbox.add(message());
    inbox.add(message({ instanceId: 'bot-b' }));
    inbox.clear('bot-a');
    expect(inbox.query({ instanceId: 'bot-a' })).toHaveLength(0);
    expect(inbox.query({ instanceId: 'bot-b' })).toHaveLength(1);
    inbox.clear();
    expect(inbox.query()).toHaveLength(0);
  });
});

describe('previewText', () => {
  it('collapses whitespace and truncates', () => {
    expect(previewText('hello   world')).toBe('hello world');
    expect(previewText('x'.repeat(100), 10)).toBe(`${'x'.repeat(10)}…`);
  });
});
