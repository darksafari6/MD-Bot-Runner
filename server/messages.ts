import type { WAMessage } from '@whiskeysockets/baileys';
import { isGroupJid, isIgnorableJid, numberFromJid } from './jid.js';

export type MessageKind = 'text' | 'image' | 'video' | 'audio' | 'document' | 'sticker' | 'other';

export interface ExtractedMessage {
  chatJid: string;
  senderJid: string;
  senderNumber: string;
  senderName: string;
  isGroup: boolean;
  /** Caption for media, conversation text otherwise (may be empty). */
  text: string;
  kind: MessageKind;
  /** True when there is no usable text — media with no caption. */
  mediaOnly: boolean;
  messageId: string;
  timestamp: number;
}

/**
 * Turn a raw Baileys message into the fields the bot needs. Pure apart from
 * reading the message object, which makes it unit testable with fixtures.
 * Returns null for messages we should ignore (own messages, status updates,
 * newsletters, empty stubs).
 */
export function extractMessage(message: WAMessage): ExtractedMessage | null {
  if (!message?.message) return null;
  if (message.key?.fromMe) return null;

  const chatJid = message.key?.remoteJid ?? '';
  if (isIgnorableJid(chatJid)) return null;

  const content = message.message;
  const isGroup = isGroupJid(chatJid);
  const senderJid = isGroup ? (message.key?.participant ?? chatJid) : chatJid;
  const senderNumber = numberFromJid(senderJid);

  // extendedTextMessage carries context (replies, links) so prefer it when
  // both legacy and modern text fields are present.
  const text =
    content.extendedTextMessage?.text ??
    content.conversation ??
    content.imageMessage?.caption ??
    content.videoMessage?.caption ??
    content.documentMessage?.caption ??
    '';

  const kind: MessageKind = content.imageMessage
    ? 'image'
    : content.videoMessage
      ? 'video'
      : content.audioMessage
        ? 'audio'
        : content.documentMessage
          ? 'document'
          : content.stickerMessage
            ? 'sticker'
            : text
              ? 'text'
              : 'other';

  const mediaOnly = kind !== 'text' && !text;
  // A message we cannot interpret (reactions, protocol stubs, polls) is not
  // worth counting as activity.
  if (kind === 'other' && !text) return null;

  const timestamp = Number(message.messageTimestamp ?? 0) * 1000 || Date.now();

  return {
    chatJid,
    senderJid,
    senderNumber,
    senderName: message.pushName?.trim() || (senderNumber ? `+${senderNumber}` : 'Unknown'),
    isGroup,
    text,
    kind,
    mediaOnly,
    messageId: message.key?.id ?? '',
    timestamp,
  };
}

/**
 * Classify a disconnect so the runtime can decide what to do next. Keeping
 * this pure is what lets us test the reconnect policy without a socket.
 */
export type DisconnectAction =
  | { type: 'ignore' }
  | { type: 'logged_out' }
  | { type: 'restart_now' }
  | { type: 'retry'; delayMs: number }
  | { type: 'give_up' };

export const MAX_RECONNECT_ATTEMPTS = 8;
export const MAX_BACKOFF_MS = 30_000;

export interface DisconnectInput {
  /** Numeric status code from Baileys, when present. */
  statusCode?: number;
  /** True when the user pressed Stop — never reconnect in that case. */
  explicitStop: boolean;
  /** Attempts already made for this session (1-based on first failure). */
  attempt: number;
}

export function classifyDisconnect({
  statusCode,
  explicitStop,
  attempt,
}: DisconnectInput): DisconnectAction {
  if (explicitStop) return { type: 'ignore' };

  // 401 = loggedOut. Baileys also reports this as DisconnectReason.loggedOut.
  if (statusCode === 401 || statusCode === 403) return { type: 'logged_out' };

  // 515 = restartRequired: WhatsApp wants an immediate, clean reconnect.
  if (statusCode === 515) return { type: 'restart_now' };

  if (attempt > MAX_RECONNECT_ATTEMPTS) return { type: 'give_up' };

  const delayMs = Math.min(1000 * 2 ** Math.max(0, attempt - 1), MAX_BACKOFF_MS);
  return { type: 'retry', delayMs };
}
