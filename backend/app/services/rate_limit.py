"""
Module: services.rate_limit

A small per-key token-bucket rate limiter for endpoints a single person can drive hard.

Responsibilities:
- Decide whether a caller (any hashable key, normally a user id) may make another request now
  (`RateLimiter.acquire`), and if not, how long until they may.
- Keep memory bounded: a bucket idle long enough to have refilled completely is dropped.

Design decisions:
- A token bucket, not a fixed window: a burst up to `capacity` is allowed (typing in a live search box
  is bursty), and the sustained rate is `refill_per_second`; there is no window edge to game.
- In-process state. The backend runs several worker processes, each with its own limiter, so the
  effective ceiling for one person is the limit times the number of workers. That is a deliberate
  trade for no shared store and no per-request write; the limit bounds abuse by a factor, it is not a
  hard quota. A shared limiter would replace `RateLimiter` behind the same two calls.
- The clock is injectable so tests do not sleep.
- A limit of zero or less disables the limiter (`enabled` is false and `acquire` always allows).

Dependencies: standard library only.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable

#: Most buckets kept before idle ones are swept, so a flood of distinct keys cannot grow memory without bound.
_SWEEP_THRESHOLD = 10_000


class RateLimiter:
    """A token-bucket limiter keyed by caller.

    Args:
        capacity: Most requests allowed in a burst (the bucket size); `<= 0` disables the limiter.
        refill_per_second: Sustained requests per second (tokens added per second).
        clock: Monotonic time source in seconds (injectable for tests).
    """

    def __init__(self, capacity: int, refill_per_second: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._clock = clock
        self._buckets: dict[Hashable, tuple[float, float]] = {}  # key -> (tokens, last refill time)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether the limiter enforces anything."""
        return self.capacity > 0 and self.refill_per_second > 0

    def acquire(self, key: Hashable) -> float | None:
        """Takes one token for `key` if there is one.

        Args:
            key: Who is asking (a user id).

        Returns:
            `None` when the request may go ahead, else the seconds to wait before one token is available.
        """
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            if len(self._buckets) > _SWEEP_THRESHOLD:
                self._sweep(now)
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.refill_per_second)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return None
            self._buckets[key] = (tokens, now)
            return (1.0 - tokens) / self.refill_per_second

    def _sweep(self, now: float) -> None:
        """Drops buckets that have been idle long enough to be full again (call with the lock held)."""
        full_after = self.capacity / self.refill_per_second
        for key in [k for k, (_tokens, last) in self._buckets.items() if now - last >= full_after]:
            del self._buckets[key]
