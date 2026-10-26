"""
Module: concurrency_limit

A per-worker ceiling on the HTTP requests being served at once, so the request threads and the database connections
can never be exhausted by each other.

Responsibilities:
- Admit at most `limit` requests into the application at a time; hold the rest in the event loop (no thread, no
  connection) until a slot frees or `queue_timeout` passes, then answer 503 with `Retry-After`.
- Leave health, metrics and WebSocket traffic alone.

Design decisions:
- Why a limit exists: a request takes a database connection in its first dependency and keeps it until the handler
  and the session cleanup have run, and each of those steps needs a thread from a fixed pool. With more requests in
  flight than connections, every thread ends up waiting for a connection that is held by a request waiting for a
  thread; nothing moves until the pool's 30-second timeout, and new arrivals refill it. The load test showed a single
  worker serving nothing at 96 simulated users. Admitting no more requests than there are connections means an
  admitted request never waits for one.
- The default limit is the pool's capacity (`db_pool_size + db_max_overflow`). It is below the thread limit, so a
  thread is always available as well. Raising it above the pool only makes sense together with the pool.
- Pure ASGI (not `BaseHTTPMiddleware`) so the wait costs a coroutine, not a thread, and the slot is released when the
  response finishes or the client goes away.
- A slot is held while a request body is still arriving; the reverse proxy in front buffers bodies, which is one more
  reason not to expose the backend directly.

Dependencies: `config`, `metrics`.
"""

from __future__ import annotations

import asyncio
import json

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.metrics import requests_shed_total

#: Paths a probe or a scraper uses; they must answer even when the application is saturated.
EXEMPT_PATHS = frozenset({"/health", "/metrics"})


def effective_limit() -> int:
    """The number of requests one worker admits at once: `MAX_CONCURRENT_REQUESTS`, or the database pool's capacity."""
    settings = get_settings()
    return settings.max_concurrent_requests or settings.db_pool_size + settings.db_max_overflow


class ConcurrencyLimitMiddleware:
    """Limits the HTTP requests in flight in this worker.

    Args:
        app: The wrapped ASGI application.
        limit: Requests admitted at once, or None for `effective_limit()`.
        queue_timeout: Seconds a request may wait for a slot before it is refused, or None for
            `Settings.request_queue_timeout_seconds`.
    """

    def __init__(self, app: ASGIApp, limit: int | None = None, queue_timeout: float | None = None) -> None:
        self.app = app
        self._limit = limit
        self._queue_timeout = queue_timeout
        self._slots: asyncio.Semaphore | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        """The slot counter, created on first use so the limit is read after the settings are final."""
        if self._slots is None:
            self._slots = asyncio.Semaphore(self._limit or effective_limit())
        return self._slots

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Waits for a slot for an HTTP request; passes anything else (WebSocket, lifespan, exempt paths) through."""
        if scope["type"] != "http" or scope["path"] in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        slots = self._semaphore()
        timeout = self._queue_timeout if self._queue_timeout is not None else get_settings().request_queue_timeout_seconds
        try:
            await asyncio.wait_for(slots.acquire(), timeout)
        except TimeoutError:
            requests_shed_total.inc()
            await self._busy(send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            slots.release()

    @staticmethod
    async def _busy(send: Send) -> None:
        """Sends the 503 response."""
        body = json.dumps({"detail": "The server is busy. Try again in a moment."}).encode()
        await send({
            "type": "http.response.start", "status": 503,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"retry-after", b"2")],
        })
        await send({"type": "http.response.body", "body": body})
