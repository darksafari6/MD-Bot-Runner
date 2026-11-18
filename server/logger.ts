import { randomUUID } from 'node:crypto';
import type { Response } from 'express';
import type { LogEntry, LogLevel } from '../shared/types.js';

type LogListener = (entry: LogEntry) => void;

/**
 * In-memory ring buffer + fan-out to Server-Sent-Events subscribers.
 * Logs are deliberately not persisted: they contain message metadata and
 * would grow unbounded on a long-running self-hosted box.
 */
export class LogHub {
  private buffer: LogEntry[] = [];
  private listeners = new Set<LogListener>();

  constructor(private readonly capacity: number) {}

  push(
    level: LogLevel,
    source: LogEntry['source'],
    message: string,
    instanceId: string | null = null,
  ): LogEntry {
    const entry: LogEntry = {
      id: randomUUID(),
      instanceId,
      ts: Date.now(),
      level,
      source,
      message: message.slice(0, 2000),
    };
    this.buffer.push(entry);
    if (this.buffer.length > this.capacity) {
      this.buffer.splice(0, this.buffer.length - this.capacity);
    }
    for (const listener of this.listeners) {
      try {
        listener(entry);
      } catch {
        this.listeners.delete(listener);
      }
    }
    return entry;
  }

  info(message: string, instanceId?: string | null) {
    return this.push('info', 'manager', message, instanceId ?? null);
  }

  warn(message: string, instanceId?: string | null) {
    return this.push('warn', 'manager', message, instanceId ?? null);
  }

  error(message: string, instanceId?: string | null) {
    return this.push('error', 'manager', message, instanceId ?? null);
  }

  success(message: string, instanceId?: string | null) {
    return this.push('success', 'manager', message, instanceId ?? null);
  }

  recent(limit = 200, instanceId?: string): LogEntry[] {
    const filtered = instanceId
      ? this.buffer.filter((entry) => entry.instanceId === instanceId)
      : this.buffer;
    return filtered.slice(-limit);
  }

  clear(): void {
    this.buffer = [];
  }

  attach(res: Response, instanceId?: string): () => void {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.write(': connected\n\n');

    for (const entry of this.recent(100, instanceId)) {
      res.write(`data: ${JSON.stringify(entry)}\n\n`);
    }

    const listener: LogListener = (entry) => {
      if (instanceId && entry.instanceId !== instanceId) return;
      res.write(`data: ${JSON.stringify(entry)}\n\n`);
    };
    this.listeners.add(listener);

    const heartbeat = setInterval(() => res.write(': ping\n\n'), 20_000);
    const detach = () => {
      clearInterval(heartbeat);
      this.listeners.delete(listener);
    };
    res.on('close', detach);
    return detach;
  }
}
