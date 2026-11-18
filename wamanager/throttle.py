"""Outbound pacing. Sending as fast as messages arrive is how numbers get banned.

The clock is injectable so the policy is deterministic under test.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

MIN_PER_MINUTE, MAX_PER_MINUTE = 1, 60
MIN_GAP_MS, MAX_GAP_MS = 250, 30_000


@dataclass(frozen=True)
class Policy:
    limit: int = 20
    window_ms: int = 60_000
    min_gap_ms: int = 1_200

    @classmethod
    def clamp(cls, limit: int, min_gap_ms: int, window_ms: int = 60_000) -> Policy:
        return cls(
            limit=max(MIN_PER_MINUTE, min(int(limit), MAX_PER_MINUTE)),
            window_ms=window_ms,
            min_gap_ms=max(MIN_GAP_MS, min(int(min_gap_ms), MAX_GAP_MS)),
        )


@dataclass(frozen=True)
class Reservation:
    delay_ms: int
    at: float


class Throttle:
    """Sliding window plus a minimum gap.

    Reservations are booked at their projected send time, so a caller that
    waits `delay_ms` before sending is always within the policy.
    """

    def __init__(self, policy: Policy | None = None, now: Callable[[], float] = time.monotonic):
        self.policy = policy or Policy()
        self._now = now
        self._booked: list[float] = []

    def _prune(self, reference: float) -> None:
        cutoff = reference - self.policy.window_ms / 1000.0
        self._booked = [t for t in self._booked if t > cutoff]

    def remaining(self) -> int:
        self._prune(self._now())
        return max(0, self.policy.limit - len(self._booked))

    def reserve(self) -> Reservation:
        now = self._now()
        self._prune(now)
        at = now

        if self._booked:
            last = self._booked[-1]
            gap = self.policy.min_gap_ms / 1000.0
            if now - last < gap:
                at = last + gap

        if len(self._booked) >= self.policy.limit:
            window = self.policy.window_ms / 1000.0
            at = max(at, self._booked[0] + window)

        self._prune(at)
        while len(self._booked) >= self.policy.limit:
            self._booked.pop(0)

        self._booked.append(at)
        return Reservation(delay_ms=max(0, round((at - now) * 1000)), at=at)


def typing_delay_ms(text: str, jitter: Callable[[], float] = random.random) -> int:
    """A human pause proportional to length, clamped so queues never stall."""
    base = min(4_000, max(600, len(text) * 45))
    return round(base * (0.85 + jitter() * 0.3))
