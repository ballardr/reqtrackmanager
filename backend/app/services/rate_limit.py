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
- Two kinds of state behind the same two calls. By default the buckets are in this process, so a limit holds per
  worker (the ceiling for one person is the limit times the number of workers). A limiter given a `shared` name
  keeps its buckets in PostgreSQL (`rate_limit_buckets`), so one limit holds across every worker and replica;
  that costs one short transaction per call, so it is used for the unauthenticated and the expensive routes, not
  for every request. If the database cannot be reached the call falls back to the in-process bucket rather than
  refusing everyone.
- The clock is injectable so tests do not sleep.
- A limit of zero or less disables the limiter (`enabled` is false and `acquire` always allows).

Dependencies: standard library only.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Hashable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

#: The chance, per shared call, of deleting buckets idle for a day.
_SWEEP_CHANCE = 0.01

#: Most buckets kept before idle ones are swept, so a flood of distinct keys cannot grow memory without bound.
_SWEEP_THRESHOLD = 10_000


class RateLimiter:
    """A token-bucket limiter keyed by caller.

    Args:
        capacity: Most requests allowed in a burst (the bucket size); `<= 0` disables the limiter.
        refill_per_second: Sustained requests per second (tokens added per second).
        clock: Monotonic time source in seconds (injectable for tests).
        shared: A name that puts this limiter's buckets in the database, shared by every worker (the bucket key is
            `<shared>:<key>`). The clock is then the database's, and `clock` is not used.
    """

    def __init__(
        self, capacity: int, refill_per_second: float, clock: Callable[[], float] = time.monotonic,
        shared: str | None = None,
    ) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.shared = shared
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
        if self.shared is not None:
            try:
                return self._acquire_shared(f"{self.shared}:{key}")
            except SQLAlchemyError:
                logger.warning("The shared rate limit store is unavailable; limiting in this process only.")
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

    def _acquire_shared(self, bucket: str) -> float | None:
        """`acquire` against the database: one transaction that locks the bucket's row, refills it and takes a token."""
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(
                text("INSERT INTO rate_limit_buckets (bucket, tokens, updated_at) VALUES (:b, :cap, clock_timestamp()) ON CONFLICT DO NOTHING"),
                {"b": bucket, "cap": float(self.capacity)},
            )
            tokens, idle = db.execute(
                text(
                    "SELECT tokens, EXTRACT(EPOCH FROM clock_timestamp() - updated_at) FROM rate_limit_buckets "
                    "WHERE bucket = :b FOR UPDATE"
                ),
                {"b": bucket},
            ).one()
            tokens = min(float(self.capacity), float(tokens) + max(0.0, float(idle)) * self.refill_per_second)
            allowed = tokens >= 1.0
            db.execute(
                text("UPDATE rate_limit_buckets SET tokens = :t, updated_at = clock_timestamp() WHERE bucket = :b"),
                {"b": bucket, "t": tokens - 1.0 if allowed else tokens},
            )
            if random.random() < _SWEEP_CHANCE:
                db.execute(text("DELETE FROM rate_limit_buckets WHERE updated_at < now() - interval '1 day'"))
            db.commit()
            return None if allowed else (1.0 - tokens) / self.refill_per_second
        finally:
            db.close()

    def _sweep(self, now: float) -> None:
        """Drops buckets that have been idle long enough to be full again (call with the lock held)."""
        full_after = self.capacity / self.refill_per_second
        for key in [k for k, (_tokens, last) in self._buckets.items() if now - last >= full_after]:
            del self._buckets[key]
