import type { Response } from 'express';

/**
 * Fan-out hub for live inbox updates (SSE). Kept separate from LogHub so the
 * console and the inbox can be subscribed independently, and so message
 * payloads never end up in the log ring buffer.
 */
export class MessageStream {
  private subscribers = new Map<string, Set<Response>>();

  attach(res: Response, instanceId: string): () => void {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.write(': connected\n\n');

    let set = this.subscribers.get(instanceId);
    if (!set) {
      set = new Set();
      this.subscribers.set(instanceId, set);
    }
    set.add(res);

    const heartbeat = setInterval(() => res.write(': ping\n\n'), 20_000);
    const detach = () => {
      clearInterval(heartbeat);
      const current = this.subscribers.get(instanceId);
      current?.delete(res);
      if (current && current.size === 0) this.subscribers.delete(instanceId);
    };
    res.on('close', detach);
    return detach;
  }

  /** Tell every subscriber of this instance that its inbox changed. */
  broadcast(instanceId: string): void {
    const set = this.subscribers.get(instanceId);
    if (!set) return;
    for (const res of set) {
      try {
        res.write(`data: ${JSON.stringify({ type: 'inbox', instanceId })}\n\n`);
      } catch {
        set.delete(res);
      }
    }
  }

  subscriberCount(): number {
    let total = 0;
    for (const set of this.subscribers.values()) total += set.size;
    return total;
  }
}
