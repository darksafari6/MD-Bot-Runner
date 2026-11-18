/**
 * WhatsApp JID helpers. Pure functions: no socket, no I/O — so they can be
 * unit tested without a network connection.
 */

export interface ParsedTarget {
  /** Canonical jid, e.g. "923001234567@s.whatsapp.net" or "123-456@g.us". */
  jid: string;
  /** Digits only for phone targets; null for groups and other jids. */
  number: string | null;
  kind: 'user' | 'group' | 'other';
}

const JID_RE = /^[0-9a-zA-Z._:-]{3,80}@(s\.whatsapp\.net|g\.us|broadcast|newsletter)$/;

/**
 * Accepts what a human would type (a phone number with spaces, dashes or a
 * leading +) as well as a fully-formed jid, and returns a canonical target.
 * Returns null when the input cannot be understood, so callers can 400 it.
 */
export function parseTarget(input: string): ParsedTarget | null {
  const raw = input.trim();
  if (!raw) return null;

  // Already a jid (group links, usernames, etc.).
  if (raw.includes('@')) {
    const jid = raw.toLowerCase();
    if (!JID_RE.test(jid)) return null;
    const kind = jid.endsWith('@g.us')
      ? 'group'
      : jid.endsWith('@s.whatsapp.net')
        ? 'user'
        : 'other';
    const local = jid.split('@')[0];
    const number = kind === 'user' ? normalizeNumber(local) : null;
    return { jid, number, kind };
  }

  const number = normalizeNumber(raw);
  if (!number) return null;
  return { jid: `${number}@s.whatsapp.net`, number, kind: 'user' };
}

/** Digits only, validated to be a plausible E.164 length. Null when invalid. */
export function normalizeNumber(input: string): string | null {
  const digits = input.replace(/\D/g, '');
  if (digits.length < 8 || digits.length > 15) return null;
  return digits;
}

/** Extract the phone number from a jid such as "92300…:12@s.whatsapp.net". */
export function numberFromJid(jid: string): string {
  return jid.split('@')[0].split(':')[0].replace(/\D/g, '');
}

export function isGroupJid(jid: string): boolean {
  return jid.endsWith('@g.us');
}

/** Chats we never reply to or list. */
export function isIgnorableJid(jid: string): boolean {
  if (!jid) return true;
  return jid === 'status@broadcast' || jid.endsWith('@newsletter') || jid.endsWith('@broadcast');
}

/** Short human label for a jid, used when we have no contact name. */
export function describeJid(jid: string): string {
  if (isGroupJid(jid)) return `Group ${jid.split('@')[0]}`;
  const number = numberFromJid(jid);
  return number ? `+${number}` : jid;
}
