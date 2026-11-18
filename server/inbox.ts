import { randomUUID } from 'node:crypto';
import type { MessageKind } from './messages.js';

export type MessageDirection = 'in' | 'out';

export interface InboxMessage {
  id: string;
  instanceId: string;
  chatJid: string;
  /** Phone number of the peer, digits only, when known. */
  number: string | null;
  chatName: string;
  senderJid: string;
  senderName: string;
  direction: MessageDirection;
  /** Where the outgoing message came from: a command reply or the panel. */
  origin: 'command' | 'manual' | 'system';
  text: string;
  kind: MessageKind;
  ts: number;
  /** Set when the send failed, so the UI can show it as unsent. */
  error?: string;
}

export interface Conversation {
  chatJid: string;
  chatName: string;
  number: string | null;
  isGroup: boolean;
  lastMessage: string;
  lastTs: number;
  /** Messages exchanged in this conversation (capped by the buffer). */
  count: number;
  unread: number;
  lastDirection: MessageDirection;
}

export interface InboxQuery {
  instanceId?: string;
  chatJid?: string;
  direction?: MessageDirection;
  limit?: number;
}

const MAX_PER_INSTANCE = 500;
const MAX_CONVERSATIONS = 200;

/**
 * In-memory message log. Deliberately not persisted: message bodies are the
 * most sensitive data this app touches, and a self-hosted manager should not
 * quietly accumulate a transcript on disk. Operators who want history can
 * attach a database later — the interface is small on purpose.
 */
export class Inbox {
  private messages: InboxMessage[] = [];
  private unread = new Map<string, number>();
  private listeners = new Set<(message: InboxMessage) => void>();

  add(entry: Omit<InboxMessage, 'id'> & { id?: string }): InboxMessage {
    const message: InboxMessage = { ...entry, id: entry.id ?? randomUUID() };
    this.messages.push(message);
    this.enforceLimits(entry.instanceId);

    if (message.direction === 'in') {
      const key = `${message.instanceId}:${message.chatJid}`;
      this.unread.set(key, (this.unread.get(key) ?? 0) + 1);
    }

    for (const listener of this.listeners) {
      try {
        listener(message);
      } catch {
        this.listeners.delete(listener);
      }
    }
    return message;
  }

  /** Mark a conversation read (called when the operator opens it). */
  markRead(instanceId: string, chatJid: string): void {
    this.unread.delete(`${instanceId}:${chatJid}`);
  }

  totalUnread(instanceId: string): number {
    let total = 0;
    for (const [key, count] of this.unread) {
      if (key.startsWith(`${instanceId}:`)) total += count;
    }
    return total;
  }

  query({ instanceId, chatJid, direction, limit = 100 }: InboxQuery = {}): InboxMessage[] {
    const filtered = this.messages.filter((message) => {
      if (instanceId && message.instanceId !== instanceId) return false;
      if (chatJid && message.chatJid !== chatJid) return false;
      if (direction && message.direction !== direction) return false;
      return true;
    });
    return filtered.slice(-Math.min(Math.max(limit, 1), 500));
  }

  /** Most recent conversation per chat, newest first. */
  conversations(instanceId: string): Conversation[] {
    const byChat = new Map<string, Conversation>();
    for (const message of this.messages) {
      if (message.instanceId !== instanceId) continue;
      const key = message.chatJid;
      const existing = byChat.get(key);
      if (!existing) {
        byChat.set(key, {
          chatJid: message.chatJid,
          chatName: message.chatName,
          number: message.number,
          isGroup: message.chatJid.endsWith('@g.us'),
          lastMessage: message.text || `[${message.kind}]`,
          lastTs: message.ts,
          count: 1,
          unread: this.unread.get(`${instanceId}:${message.chatJid}`) ?? 0,
          lastDirection: message.direction,
        });
        continue;
      }
      existing.count += 1;
      if (message.ts >= existing.lastTs) {
        existing.lastTs = message.ts;
        existing.lastMessage = message.text || `[${message.kind}]`;
        existing.lastDirection = message.direction;
        if (message.chatName) existing.chatName = message.chatName;
      }
    }
    return [...byChat.values()].sort((a, b) => b.lastTs - a.lastTs).slice(0, MAX_CONVERSATIONS);
  }

  subscribe(listener: (message: InboxMessage) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  clear(instanceId?: string): void {
    this.messages = instanceId
      ? this.messages.filter((message) => message.instanceId !== instanceId)
      : [];
    if (instanceId) {
      for (const key of [...this.unread.keys()]) {
        if (key.startsWith(`${instanceId}:`)) this.unread.delete(key);
      }
    } else {
      this.unread.clear();
    }
  }

  /** Bound memory: keep the newest N per instance, not per whole process. */
  private enforceLimits(instanceId: string): void {
    const forInstance = this.messages.filter((message) => message.instanceId === instanceId);
    if (forInstance.length <= MAX_PER_INSTANCE) return;
    const drop = new Set(
      forInstance.slice(0, forInstance.length - MAX_PER_INSTANCE).map((message) => message.id),
    );
    this.messages = this.messages.filter((message) => !drop.has(message.id));
  }
}

/** Preview text for a log line — keeps tokens/PII out of the console. */
export function previewText(text: string, max = 60): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max)}…` : clean;
}
