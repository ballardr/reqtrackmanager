"""Tests for multi-worker coordination (2026-10-04): the advisory-lock leader
election and startup lock in `services.process_coordination`, and the
Postgres LISTEN/NOTIFY fan-out in `services.pubsub` — what lets the backend
run several uvicorn workers without duplicating scheduled jobs/emails or
losing WebSocket broadcasts published by another worker.

Each lock is exercised from two separate connections, standing in for two
worker processes (advisory locks are per-session, so a second connection
behaves exactly like a second process).
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
import uuid

from app.database import engine
from app.services import pubsub
from app.services.process_coordination import (
    LeaderLock,
    run_leadership_loop,
    startup_lock,
)


def _test_key() -> int:
    """A random advisory key per test, so these never contend with the
    session-scoped app client's lifespan, which holds the real
    `LEADER_LOCK_KEY` for the whole pytest run."""
    return 0x52657100_00000000 + random.randrange(1 << 32)


def test_leader_lock_is_exclusive_and_released():
    key = _test_key()
    first, second = LeaderLock(key), LeaderLock(key)
    try:
        assert first.try_acquire() is True
        assert second.try_acquire() is False  # another "worker" holds it
        assert first.still_held() is True
        first.release()
        assert second.try_acquire() is True  # leadership moves on
    finally:
        first.release()
        second.release()


def test_leader_steps_down_when_its_lock_is_lost():
    lock = LeaderLock(_test_key())
    try:
        assert lock.try_acquire()
        # Simulate losing the lock (e.g. the connection was reset).
        lock._connection.cursor().execute("SELECT pg_advisory_unlock(%s)", (lock.key,))
        lock._connection.commit()
        assert lock.still_held() is False
        assert lock.held is False
    finally:
        lock.release()


def test_leadership_loop_elects_and_deposes():
    events: list[str] = []
    key = _test_key()
    rival = LeaderLock(key)

    async def scenario():
        lock = LeaderLock(key)
        task = asyncio.create_task(run_leadership_loop(
            lambda: events.append("elected"), lambda: events.append("deposed"), interval=0.05, lock=lock,
        ))
        await asyncio.sleep(0.3)
        assert events == ["elected"]
        # Lose the lock behind the loop's back; it must step down.
        lock._connection.cursor().execute("SELECT pg_advisory_unlock(%s)", (lock.key,))
        lock._connection.commit()
        assert await asyncio.to_thread(rival.try_acquire)  # someone else takes over
        await asyncio.sleep(0.3)
        assert events == ["elected", "deposed"]
        task.cancel()

    try:
        asyncio.run(scenario())
    finally:
        rival.release()


def test_startup_lock_serialises_holders():
    order: list[str] = []

    def second_worker():
        with startup_lock():
            order.append("second")

    with startup_lock():
        thread = threading.Thread(target=second_worker)
        thread.start()
        time.sleep(0.3)
        order.append("first-done")  # the second must still be waiting
    thread.join(timeout=5)
    assert order == ["first-done", "second"]


def test_notify_reaches_local_sockets_via_listen_notify():
    received: list[tuple[uuid.UUID, dict]] = []
    project_id = uuid.uuid4()

    async def fake_broadcast(pid, message):
        received.append((pid, message))

    async def scenario():
        original = pubsub._broadcast
        pubsub._broadcast = fake_broadcast
        pubsub.set_event_loop(asyncio.get_running_loop())
        pubsub.start_listener()
        try:
            await asyncio.sleep(0.5)  # let the listener LISTEN
            await asyncio.to_thread(pubsub.notify, project_id, {"event": "requirement.updated", "id": "x"})
            for _ in range(40):
                if received:
                    break
                await asyncio.sleep(0.05)
        finally:
            pubsub.stop_listener()
            pubsub._broadcast = original
            pubsub.set_event_loop(None)

    asyncio.run(scenario())
    assert received == [(project_id, {"event": "requirement.updated", "id": "x"})]
    # Sanity: the dedicated connections are released afterwards.
    with engine.connect():
        pass
