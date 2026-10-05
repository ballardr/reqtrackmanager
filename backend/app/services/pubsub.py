"""
Module: services.pubsub

A minimal in-process publish/subscribe hub backing the optional WebSocket
interface (I-A-04). Broadcasts requirement/change-request state transitions
to connected clients of the relevant project.

Cross-process (2026-10-04): the backend now runs several worker processes
(`BACKEND_WORKERS`), and a WebSocket is held by whichever worker accepted
it, so a publish must reach every worker. When `start_listener()` has run
(the app lifespan does this when WebSockets are enabled), `notify()`
publishes through PostgreSQL `NOTIFY` and each worker's listener thread
re-broadcasts to its own sockets — no extra broker needed. Without a
listener (unit tests, no lifespan) it broadcasts in-process as before.

FastAPI route handlers may be plain (sync) functions that FastAPI runs in a
worker thread, so `notify` schedules the broadcast onto the event loop
captured at startup rather than assuming it's already running on the
calling thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import select
import threading
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)
CHANNEL = "reqtrack_pubsub"

_connections: dict[UUID, set[WebSocket]] = defaultdict(set)
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Captures the running event loop at application startup."""
    global _loop
    _loop = loop


async def connect(project_id: UUID, websocket: WebSocket) -> None:
    await websocket.accept()
    _connections[project_id].add(websocket)


def disconnect(project_id: UUID, websocket: WebSocket) -> None:
    _connections[project_id].discard(websocket)


async def _broadcast(project_id: UUID, message: dict[str, Any]) -> None:
    """Sends `message` to every live WebSocket connected to `project_id`,
    dropping any connection that fails to send (I-A-04)."""
    dead = []
    for ws in _connections[project_id]:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[project_id].discard(ws)


_listener_thread: threading.Thread | None = None
_listener_stop = threading.Event()


def _dispatch(payload: str) -> None:
    """Re-broadcasts one NOTIFY payload to this worker's own sockets."""
    if _loop is None:
        return
    try:
        data = json.loads(payload)
        project_id = UUID(data["project_id"])
    except (ValueError, KeyError, TypeError):
        logger.warning("Ignoring malformed pub/sub payload")
        return
    asyncio.run_coroutine_threadsafe(_broadcast(project_id, data["message"]), _loop)


def _listen_forever() -> None:
    """Listener thread: LISTENs on `CHANNEL` over a dedicated connection and
    dispatches each notification, reconnecting after errors."""
    while not _listener_stop.is_set():
        connection = None
        try:
            connection = engine.raw_connection()
            # Detached from the pool: a LISTENing session must never be
            # handed back to request traffic.
            connection.detach()
            raw = connection.dbapi_connection  # the psycopg2 connection itself
            raw.set_isolation_level(0)  # autocommit, required for LISTEN
            raw.cursor().execute(f"LISTEN {CHANNEL}")
            while not _listener_stop.is_set():
                if select.select([raw], [], [], 1.0) == ([], [], []):
                    continue
                raw.poll()
                while raw.notifies:
                    _dispatch(raw.notifies.pop(0).payload)
        except Exception:
            logger.warning("Pub/sub listener error; reconnecting", exc_info=True)
            _listener_stop.wait(2.0)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def start_listener() -> None:
    """Starts this worker's NOTIFY listener thread (idempotent)."""
    global _listener_thread
    if _listener_thread is not None:
        return
    _listener_stop.clear()
    _listener_thread = threading.Thread(target=_listen_forever, name="pubsub-listener", daemon=True)
    _listener_thread.start()


def stop_listener() -> None:
    """Stops the listener thread (idempotent)."""
    global _listener_thread
    if _listener_thread is None:
        return
    _listener_stop.set()
    _listener_thread.join(timeout=5)
    _listener_thread = None


def notify(project_id: UUID, message: dict[str, Any]) -> None:
    """Broadcasts `message` to every client subscribed to a project, on
    every worker process.

    Safe to call from a synchronous route handler running in a worker
    thread. With a listener running, publishes via PostgreSQL NOTIFY (on
    its own autocommitted connection, so it is delivered immediately — the
    same timing as the previous in-process broadcast). Otherwise broadcasts
    in-process, and no-ops if no event loop has been captured yet (e.g. in
    unit tests that don't run the full ASGI lifespan).
    """
    if _listener_thread is not None:
        payload = json.dumps({"project_id": str(project_id), "message": message}, default=str)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT pg_notify(:channel, :payload)"),
                                   {"channel": CHANNEL, "payload": payload})
                connection.commit()
        except Exception:
            logger.warning("Pub/sub publish failed", exc_info=True)
        return
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(project_id, message), _loop)
