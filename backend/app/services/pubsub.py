"""
Module: services.pubsub

A minimal in-process publish/subscribe hub backing the optional WebSocket
interface (I-A-04). Broadcasts requirement/change-request state transitions
to connected clients of the relevant project. This is intentionally simple
(single-process, in-memory) — adequate for a single-backend-instance Ossa
(v1) deployment; a multi-instance deployment would need a shared broker
(e.g. Redis pub/sub) instead, which is a natural extension point rather than
something Ossa (v1) requires.

FastAPI route handlers may be plain (sync) functions that FastAPI runs in a
worker thread, so `notify` schedules the broadcast onto the event loop
captured at startup rather than assuming it's already running on the
calling thread.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket

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
    dead = []
    for ws in _connections[project_id]:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[project_id].discard(ws)


def notify(project_id: UUID, message: dict[str, Any]) -> None:
    """Schedules a broadcast to all clients subscribed to a project.

    Safe to call from a synchronous route handler running in a worker
    thread. No-ops if no event loop has been captured yet (e.g. in unit
    tests that don't run the full ASGI lifespan).
    """
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(project_id, message), _loop)
