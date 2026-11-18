import { describe, expect, it } from 'vitest';
import { Throttle, typingDelayMs, type ThrottlePolicy } from '../server/throttle.js';

/** Controllable clock so pacing assertions are deterministic. */
function clock(start = 1_000_000) {
  let now = start;
  return {
    now: () => now,
    advance: (ms: number) => {
      now += ms;
    },
  };
}

const policy: ThrottlePolicy = { limit: 3, windowMs: 10_000, minGapMs: 1_000 };

describe('Throttle', () => {
  it('allows the first message immediately', () => {
    const throttle = new Throttle(policy, clock().now);
    expect(throttle.reserve()).toEqual({ delayMs: 0, at: 1_000_000 });
  });

  it('enforces the minimum gap between consecutive sends', () => {
    const c = clock();
    const throttle = new Throttle(policy, c.now);
    throttle.reserve();
    const second = throttle.reserve();
    expect(second.delayMs).toBe(1_000);
  });

  it('accepts a send with no wait once the gap has elapsed', () => {
    const c = clock();
    const throttle = new Throttle(policy, c.now);
    throttle.reserve();
    c.advance(1_000);
    expect(throttle.reserve().delayMs).toBe(0);
  });

  it('defers the message that exceeds the window limit', () => {
    const c = clock();
    const throttle = new Throttle(policy, c.now);
    // Three reservations land at t+0, t+1000 and t+2000 because of minGap.
    throttle.reserve();
    throttle.reserve();
    throttle.reserve();
    const fourth = throttle.reserve();
    // The 4th must wait until the first booking leaves the 10s window.
    expect(fourth.delayMs).toBe(10_000);
  });

  it('reports remaining capacity and refills over time', () => {
    const c = clock();
    const throttle = new Throttle(policy, c.now);
    expect(throttle.remaining()).toBe(3);
    throttle.reserve(); // at t+0
    throttle.reserve(); // booked at t+1000
    expect(throttle.remaining()).toBe(1);
    // Move far enough that both bookings fall out of the window.
    c.advance(11_001);
    expect(throttle.remaining()).toBe(3);
  });

  it('never exceeds the limit in any rolling window', () => {
    const c = clock();
    const throttle = new Throttle({ limit: 5, windowMs: 60_000, minGapMs: 0 }, c.now);
    const scheduled: number[] = [];
    for (let i = 0; i < 50; i += 1) {
      const reservation = throttle.reserve();
      scheduled.push(reservation.at);
      c.advance(reservation.delayMs);
    }
    // Every 60s window may hold at most 5 reservations.
    for (const at of scheduled) {
      const inWindow = scheduled.filter((other) => other >= at && other < at + 60_000);
      expect(inWindow.length).toBeLessThanOrEqual(5);
    }
  });

  it('keeps reservations even if the caller fails to send (fails safe)', () => {
    const c = clock();
    const throttle = new Throttle(policy, c.now);
    throttle.reserve();
    // Caller "crashes" without sending — capacity is still consumed.
    expect(throttle.remaining()).toBe(2);
  });

  it('honours a one-message-per-second policy', () => {
    const c = clock();
    const throttle = new Throttle({ limit: 1, windowMs: 1_000, minGapMs: 0 }, c.now);
    expect(throttle.reserve().delayMs).toBe(0);
    // Second message waits for the first to leave the window.
    expect(throttle.reserve().delayMs).toBe(1_000);
    // Having actually waited that long, the next slot is free again.
    c.advance(2_000);
    expect(throttle.reserve().delayMs).toBe(0);
  });
});

describe('typingDelayMs', () => {
  it('is bounded for tiny and huge messages', () => {
    const noJitter = () => 0.5;
    expect(typingDelayMs('hi', noJitter)).toBeGreaterThanOrEqual(600);
    expect(typingDelayMs('x'.repeat(5000), noJitter)).toBeLessThanOrEqual(4_000);
  });

  it('scales with message length', () => {
    const noJitter = () => 0.5;
    expect(typingDelayMs('x'.repeat(120), noJitter)).toBeGreaterThan(
      typingDelayMs('x'.repeat(20), noJitter),
    );
  });

  it('always returns a positive integer', () => {
    const value = typingDelayMs('hello', () => 0.99);
    expect(Number.isInteger(value)).toBe(true);
    expect(value).toBeGreaterThan(0);
  });
});
