import { timingSafeEqual } from 'node:crypto';
import type { NextFunction, Request, Response } from 'express';
import { config } from './config.js';

/**
 * Optional shared-secret auth. When API_TOKEN is unset the panel is open —
 * that is the right default for a loopback-only self-hosted tool, and the
 * manager logs a warning at boot so the exposure is never silent.
 */
export function authMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (!config.authRequired) return next();

  const expected = config.apiToken!;
  // Accept either a bearer header or ?token= for EventSource, which cannot
  // send custom headers.
  const header = req.get('authorization');
  const bearer = header?.toLowerCase().startsWith('bearer ') ? header.slice(7).trim() : null;
  const provided = bearer ?? (typeof req.query.token === 'string' ? req.query.token : null);

  if (!provided || !safeEqual(provided, expected)) {
    res.status(401).json({ error: 'Unauthorized', details: 'A valid API token is required.' });
    return;
  }
  next();
}

function safeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

/** Very small fixed-window limiter to keep brute-force + runaway loops cheap. */
export function rateLimit(limit: number, windowMs: number) {
  const hits = new Map<string, { count: number; resetAt: number }>();
  return (req: Request, res: Response, next: NextFunction): void => {
    const key = req.ip ?? 'unknown';
    const now = Date.now();
    const entry = hits.get(key);
    if (!entry || entry.resetAt < now) {
      hits.set(key, { count: 1, resetAt: now + windowMs });
      return next();
    }
    entry.count += 1;
    if (entry.count > limit) {
      res.status(429).json({ error: 'Too many requests', details: 'Slow down and retry.' });
      return;
    }
    next();
  };
}
