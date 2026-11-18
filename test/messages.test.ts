import { describe, expect, it } from 'vitest';
import type { WAMessage } from '@whiskeysockets/baileys';
import { classifyDisconnect, extractMessage } from '../server/messages.js';
import { parseTarget } from '../server/jid.js';

/** Build a minimal WAMessage fixture — only the fields we read. */
function fixture(overrides: Record<string, unknown> = {}, content?: Record<string, unknown>) {
  return {
    key: {
      remoteJid: '923001234567@s.whatsapp.net',
      fromMe: false,
      id: 'ABC123',
      ...(overrides.key as object),
    },
    pushName: 'Ali',
    messageTimestamp: 1_700_000_000,
    message: content ?? { conversation: 'hello' },
    ...Object.fromEntries(Object.entries(overrides).filter(([key]) => key !== 'key')),
  } as unknown as WAMessage;
}

describe('extractMessage', () => {
  it('reads plain conversation text', () => {
    const result = extractMessage(fixture());
    expect(result).toMatchObject({
      chatJid: '923001234567@s.whatsapp.net',
      senderNumber: '923001234567',
      senderName: 'Ali',
      isGroup: false,
      text: 'hello',
      kind: 'text',
      mediaOnly: false,
      messageId: 'ABC123',
      timestamp: 1_700_000_000_000,
    });
  });

  it('prefers extendedText over conversation', () => {
    const result = extractMessage(
      fixture({}, { conversation: 'ignored', extendedTextMessage: { text: 'extended' } }),
    );
    expect(result?.text).toBe('extended');
  });

  it('uses an image caption as text', () => {
    const result = extractMessage(fixture({}, { imageMessage: { caption: 'my photo' } }));
    expect(result).toMatchObject({ kind: 'image', text: 'my photo', mediaOnly: false });
  });

  it('flags caption-less media as media-only', () => {
    const result = extractMessage(fixture({}, { imageMessage: {} }));
    expect(result).toMatchObject({ kind: 'image', text: '', mediaOnly: true });
  });

  it('detects audio, document and sticker kinds', () => {
    expect(extractMessage(fixture({}, { audioMessage: {} }))?.kind).toBe('audio');
    expect(extractMessage(fixture({}, { documentMessage: { caption: 'doc' } }))?.kind).toBe(
      'document',
    );
    expect(extractMessage(fixture({}, { stickerMessage: {} }))?.kind).toBe('sticker');
  });

  it('attributes group messages to the participant', () => {
    const result = extractMessage(
      fixture({
        key: { remoteJid: '120363000000000000@g.us', participant: '447700900123@s.whatsapp.net' },
      }),
    );
    expect(result).toMatchObject({
      isGroup: true,
      senderJid: '447700900123@s.whatsapp.net',
      senderNumber: '447700900123',
    });
  });

  it('ignores our own messages, status updates and newsletters', () => {
    expect(extractMessage(fixture({ key: { fromMe: true } }))).toBeNull();
    expect(extractMessage(fixture({ key: { remoteJid: 'status@broadcast' } }))).toBeNull();
    expect(extractMessage(fixture({ key: { remoteJid: '123@newsletter' } }))).toBeNull();
  });

  it('ignores uninterpretable payloads (reactions, protocol stubs)', () => {
    expect(extractMessage(fixture({}, { protocolMessage: {} }))).toBeNull();
    expect(extractMessage(fixture({}, {}))).toBeNull();
  });

  it('falls back to the phone number when pushName is missing', () => {
    const result = extractMessage(fixture({ pushName: undefined }));
    expect(result?.senderName).toBe('+923001234567');
  });
});

describe('classifyDisconnect', () => {
  it('never reconnects after an explicit stop', () => {
    expect(classifyDisconnect({ explicitStop: true, attempt: 1 })).toEqual({ type: 'ignore' });
  });

  it('treats 401 and 403 as logged out', () => {
    expect(classifyDisconnect({ explicitStop: false, attempt: 1, statusCode: 401 })).toEqual({
      type: 'logged_out',
    });
    expect(classifyDisconnect({ explicitStop: false, attempt: 1, statusCode: 403 })).toEqual({
      type: 'logged_out',
    });
  });

  it('reconnects immediately on restart-required (515)', () => {
    expect(classifyDisconnect({ explicitStop: false, attempt: 3, statusCode: 515 })).toEqual({
      type: 'restart_now',
    });
  });

  it('backs off exponentially and caps the delay', () => {
    const delays = [1, 2, 3, 4, 5, 6, 7, 8].map((attempt) => {
      const action = classifyDisconnect({ explicitStop: false, attempt });
      return action.type === 'retry' ? action.delayMs : -1;
    });
    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  });

  it('gives up after the attempt budget', () => {
    expect(classifyDisconnect({ explicitStop: false, attempt: 9 })).toEqual({ type: 'give_up' });
  });
});

describe('send target validation order', () => {
  it('rejects a bad recipient independently of connection state', () => {
    // sendMessage validates the target before checking the socket, so a typo
    // returns 400 even when the bot is stopped. This mirrors that ordering.
    expect(parseTarget('nope')).toBeNull();
    expect(parseTarget('+92 300 1234567')).not.toBeNull();
  });
});
