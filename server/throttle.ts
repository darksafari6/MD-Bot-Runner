/**
 * Outbound pacing. Sending replies as fast as they arrive is the quickest way
 * to get a number restricted, so every outbound message goes through this.
 *
 * Implemented as a sliding window plus a minimum gap, with the clock injected
 * so the behaviour is deterministic in tests.
 */

export interface ThrottlePolicy {
  /** Messages allowed per window. */
  limit: number;
  /** Window length in milliseconds. */
  windowMs: number;
  /** Minimum spacing between two sends, even when the window has room. */
  minGapMs: number;
}

export const DEFAULT_THROTTLE: ThrottlePolicy = {
  limit: 20,
  windowMs: 60_000,
  minGapMs: 1_200,
};

export interface ThrottleReservation {
  /** How long the caller must wait before sending. 0 means "send now". */
  delayMs: number;
  /** Send time this reservation occupies. */
  at: number;
}

/**
 * Sliding-window limiter. `reserve()` books a slot; the caller awaits
 * `delayMs` before actually sending. Reservations are kept even if the caller
 * later fails, which errs on the side of sending *less*.
 */
export class Throttle {
  private sent: number[] = [];

  constructor(
    private readonly policy: ThrottlePolicy = DEFAULT_THROTTLE,
    private readonly now: () => number = Date.now,
  ) {}

  get policySnapshot(): ThrottlePolicy {
    return { ...this.policy };
  }

  /** Number of sends still permitted inside the current window. */
  remaining(): number {
    this.prune(this.now());
    return Math.max(0, this.policy.limit - this.sent.length);
  }

  reserve(): ThrottleReservation {
    const now = this.now();
    this.prune(now);

    let at = now;

    // Respect the minimum gap after the most recent send.
    const last = this.sent[this.sent.length - 1];
    if (last !== undefined && now - last < this.policy.minGapMs) {
      at = last + this.policy.minGapMs;
    }

    // If the window is full, wait for the oldest entry to expire.
    if (this.sent.length >= this.policy.limit) {
      const oldest = this.sent[0];
      const windowSlot = oldest + this.policy.windowMs;
      at = Math.max(at, windowSlot);
    }

    this.prune(at);
    if (this.sent.length >= this.policy.limit) {
      // Still full at the projected time: drop the ones that expire by then so
      // the reservation cannot overshoot the limit.
      const cutoff = at - this.policy.windowMs;
      this.sent = this.sent.filter((ts) => ts > cutoff);
    }
    this.sent.push(at);

    return { delayMs: Math.max(0, at - now), at };
  }

  /** Drop timestamps that fell out of the window. */
  private prune(reference: number): void {
    const cutoff = reference - this.policy.windowMs;
    while (this.sent.length > 0 && this.sent[0] <= cutoff) {
      this.sent.shift();
    }
  }
}

/**
 * Humans need a moment to type. Delay the reply proportionally to its length,
 * clamped so a long message never stalls the queue for minutes.
 */
export function typingDelayMs(text: string, jitter = Math.random): number {
  const base = Math.min(4_000, Math.max(600, text.length * 45));
  return Math.round(base * (0.85 + jitter() * 0.3));
}
