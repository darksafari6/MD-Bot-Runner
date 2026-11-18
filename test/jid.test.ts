import { describe, expect, it } from 'vitest';
import {
  describeJid,
  isGroupJid,
  isIgnorableJid,
  normalizeNumber,
  numberFromJid,
  parseTarget,
} from '../server/jid.js';

describe('parseTarget', () => {
  it('accepts human-formatted phone numbers', () => {
    expect(parseTarget('+92 300-1234567')).toEqual({
      jid: '923001234567@s.whatsapp.net',
      number: '923001234567',
      kind: 'user',
    });
  });

  it('accepts a bare jid unchanged', () => {
    expect(parseTarget('923001234567@s.whatsapp.net')?.kind).toBe('user');
  });

  it('recognises group jids', () => {
    const target = parseTarget('120363000000000000@g.us');
    expect(target?.kind).toBe('group');
    expect(target?.number).toBeNull();
  });

  it('rejects junk and too-short numbers', () => {
    expect(parseTarget('')).toBeNull();
    expect(parseTarget('123')).toBeNull();
    expect(parseTarget('not a number')).toBeNull();
    expect(parseTarget('!!!')).toBeNull();
  });

  it('rejects jids without a known domain', () => {
    expect(parseTarget('abc@evil.example.com')).toBeNull();
  });

  it('rejects path traversal attempts', () => {
    expect(parseTarget('../../etc/passwd')).toBeNull();
  });
});

describe('normalizeNumber', () => {
  it('strips formatting but keeps digits', () => {
    expect(normalizeNumber('+44 (7700) 900-123')).toBe('447700900123');
  });

  it('enforces E.164 bounds', () => {
    expect(normalizeNumber('1234567')).toBeNull();
    expect(normalizeNumber('1'.repeat(16))).toBeNull();
  });
});

describe('numberFromJid', () => {
  it('drops the device suffix on user jids', () => {
    expect(numberFromJid('923001234567:12@s.whatsapp.net')).toBe('923001234567');
  });

  it('handles group participant jids', () => {
    expect(numberFromJid('447700900123@s.whatsapp.net')).toBe('447700900123');
  });
});

describe('isIgnorableJid', () => {
  it('ignores status, newsletters and empty jids', () => {
    expect(isIgnorableJid('status@broadcast')).toBe(true);
    expect(isIgnorableJid('123@newsletter')).toBe(true);
    expect(isIgnorableJid('')).toBe(true);
    expect(isIgnorableJid('923001234567@s.whatsapp.net')).toBe(false);
  });
});

describe('describeJid / isGroupJid', () => {
  it('labels groups and users readably', () => {
    expect(describeJid('120363000000000000@g.us')).toContain('Group');
    expect(describeJid('923001234567@s.whatsapp.net')).toBe('+923001234567');
    expect(isGroupJid('a@g.us')).toBe(true);
    expect(isGroupJid('a@s.whatsapp.net')).toBe(false);
  });
});
