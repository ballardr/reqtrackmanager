"""
Module: services.process_coordination

Coordinates several backend worker processes (uvicorn `--workers`,
`BACKEND_WORKERS`) through PostgreSQL advisory locks, so the API can use
more than one CPU core without duplicating process-wide work:

- `startup_lock()` serialises each worker's startup (migrations, bootstrap,
  registry syncs). The first worker does the work; later ones find it done.
- `run_leadership_loop()` elects one *leader* worker to run the singleton
  background work (scheduled jobs, the digest emailer, the disk monitor),
  so emails and sweeps never run once per worker. Non-leaders retry
  periodically, so leadership moves on if the leader dies; the leader
  re-checks its lock connection and steps down if it is lost, so two
  workers never believe they lead at once for longer than one interval.

Design decisions (2026-10-04, Decided by: User — "do 1": multi-worker
backend after e2e profiling showed a single process saturating one core):
- Advisory locks need no extra infrastructure and are released by Postgres
  automatically when a holder's connection closes (including a crash).
- Locks are taken on dedicated DBAPI connections *detached* from the
  SQLAlchemy pool, so closing one really ends its session (releasing the
  lock) and request traffic can never reuse a lock-holding session.
- Advisory-lock keys are scoped to the current database, so the pytest
  database and the live database never contend.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.database import engine

logger = logging.getLogger(__name__)


def _dedicated_connection():
    """A DBAPI connection detached from the SQLAlchemy pool, so `close()`
    really ends the database session — and with it any session-level
    advisory lock. (A pooled connection's `close()` only returns it to the
    pool, leaving the lock held by a session request traffic then reuses.)"""
    connection = engine.raw_connection()
    connection.detach()
    return connection

# Arbitrary, fixed 64-bit keys ("ReqT" + purpose), unique within this app.
STARTUP_LOCK_KEY = 0x5265715401
LEADER_LOCK_KEY = 0x5265715402
LEADERSHIP_CHECK_INTERVAL_SECONDS = 30.0


@contextmanager
def startup_lock() -> Iterator[None]:
    """Blocks until this process holds the startup lock, then holds it for
    the duration of the block. Released on exit, or by Postgres if the
    process dies."""
    connection = _dedicated_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT pg_advisory_lock(%s)", (STARTUP_LOCK_KEY,))
        connection.commit()
        try:
            yield
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (STARTUP_LOCK_KEY,))
            connection.commit()
    finally:
        connection.close()


class LeaderLock:
    """Holds (or tries to hold) the leader advisory lock on a dedicated
    connection for as long as this process leads.

    Args:
        key: The advisory-lock key; `LEADER_LOCK_KEY` by default. Tests pass
            their own key so they never contend with an app instance (e.g.
            the pytest session's lifespan) holding the real one.
    """

    def __init__(self, key: int = LEADER_LOCK_KEY) -> None:
        self.key = key
        self._connection = None

    @property
    def held(self) -> bool:
        """Whether this process currently believes it holds the lock."""
        return self._connection is not None

    def try_acquire(self) -> bool:
        """Attempts to take the lock without blocking.

        Returns:
            True if this process now holds it.
        """
        connection = _dedicated_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
            acquired = bool(cursor.fetchone()[0])
            connection.commit()
        except Exception:
            connection.close()
            raise
        if acquired:
            self._connection = connection
        else:
            connection.close()
        return acquired

    def still_held(self) -> bool:
        """Verifies the lock's connection is alive and still holds the lock.
        Drops the connection (stepping down) if not.

        Returns:
            True if the lock is still held.
        """
        if self._connection is None:
            return False
        try:
            cursor = self._connection.cursor()
            cursor.execute(
                # A bigint advisory key is stored as classid (high 32 bits),
                # objid (low 32 bits), objsubid = 1.
                "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
                "AND classid = %s AND objid = %s AND objsubid = 1 AND granted",
                (self.key >> 32, self.key & 0xFFFFFFFF),
            )
            held = cursor.fetchone() is not None
            self._connection.commit()
        except Exception:
            held = False
        if not held:
            self.release()
        return held

    def release(self) -> None:
        """Releases the lock by closing its connection (idempotent)."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                logger.warning("Error closing leader-lock connection", exc_info=True)
            self._connection = None


async def run_leadership_loop(
    on_elected: Callable[[], None], on_deposed: Callable[[], None],
    interval: float = LEADERSHIP_CHECK_INTERVAL_SECONDS, lock: LeaderLock | None = None,
) -> None:
    """Runs forever: becomes leader when the lock is free (calling
    `on_elected`), and steps down (calling `on_deposed`) if the lock is lost.
    Cancel the task to stop; the caller is responsible for its own shutdown
    of whatever `on_elected` started.

    Args:
        on_elected: Starts the singleton background work.
        on_deposed: Stops it.
        interval: Seconds between checks.
        lock: Injected for tests; a fresh `LeaderLock` by default.
    """
    lock = lock or LeaderLock()
    try:
        while True:
            try:
                if not lock.held:
                    if await asyncio.to_thread(lock.try_acquire):
                        logger.info("This worker is now the background-job leader.")
                        on_elected()
                elif not await asyncio.to_thread(lock.still_held):
                    logger.warning("Lost the background-job leader lock; stepping down.")
                    on_deposed()
            except Exception:
                logger.exception("Leader election check failed; retrying.")
            await asyncio.sleep(interval)
    finally:
        lock.release()
