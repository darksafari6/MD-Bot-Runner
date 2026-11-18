from __future__ import annotations

from wamanager.throttle import Policy, Throttle, typing_delay_ms


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, ms: float) -> None:
        self.t += ms / 1000.0


def make(limit=3, gap=1_000, window=10_000):
    clock = Clock()
    return Throttle(Policy(limit=limit, window_ms=window, min_gap_ms=gap), clock), clock


def test_first_message_is_immediate():
    throttle, _ = make()
    assert throttle.reserve().delay_ms == 0


def test_minimum_gap_is_enforced():
    throttle, _ = make()
    throttle.reserve()
    assert throttle.reserve().delay_ms == 1_000


def test_no_wait_after_gap_elapsed():
    throttle, clock = make()
    throttle.reserve()
    clock.advance(1_000)
    assert throttle.reserve().delay_ms == 0


def test_window_limit_defers():
    throttle, _ = make()
    throttle.reserve()  # t+0
    throttle.reserve()  # t+1000
    throttle.reserve()  # t+2000
    # Fourth must wait for the first booking to leave the 10s window.
    assert throttle.reserve().delay_ms == 10_000


def test_remaining_refills_over_time():
    throttle, clock = make()
    assert throttle.remaining() == 3
    throttle.reserve()
    throttle.reserve()
    assert throttle.remaining() == 1
    clock.advance(11_000)
    assert throttle.remaining() == 3


def test_never_exceeds_limit_in_any_window():
    clock = Clock()
    throttle = Throttle(Policy(limit=5, window_ms=60_000, min_gap_ms=0), clock)
    booked = []
    for _ in range(40):
        reservation = throttle.reserve()
        booked.append(reservation.at)
        clock.advance(reservation.delay_ms)
    for at in booked:
        in_window = [t for t in booked if at <= t < at + 60]
        assert len(in_window) <= 5


def test_reservations_are_kept_if_send_fails():
    throttle, _ = make()
    throttle.reserve()
    # A crashed caller still consumed capacity: fail safe, not fail open.
    assert throttle.remaining() == 2


def test_policy_clamps_dangerous_values():
    policy = Policy.clamp(limit=9999, min_gap_ms=1)
    assert policy.limit == 60
    assert policy.min_gap_ms == 250
    policy = Policy.clamp(limit=0, min_gap_ms=99_999)
    assert policy.limit == 1
    assert policy.min_gap_ms == 30_000


def test_typing_delay_is_bounded_and_positive():
    assert typing_delay_ms("hi", lambda: 0.5) >= 600
    assert typing_delay_ms("x" * 5000, lambda: 0.5) <= 4_000
    assert typing_delay_ms("hello", lambda: 0.99) > 0
