"""
Module: body_limit

A request-body size ceiling, enforced before a handler reads the body.

Responsibilities:
- Refuse a request whose declared `Content-Length` exceeds its limit with 413, before any of the body is read.
- Count the bytes of a body that arrives without a length (chunked) and stop reading it at the limit.

Design decisions:
- Pure ASGI, not `BaseHTTPMiddleware`: it must see the raw `receive` stream and cannot buffer the body.
- Two ceilings. A bundle or spreadsheet import (a path with an `/import` segment) may be as large as
  `services.bundle_common.MAX_IMPORT_UPLOAD_BYTES`; everything else (JSON, attachments, avatars) is held to
  `Settings.max_request_body_bytes`, which is above `Settings.max_upload_bytes` by the multipart overhead.
  Every upload handler reads its whole file into memory, so this ceiling is what bounds a worker's memory
  against a signed-in user with the lowest upload right.
- A reverse proxy's own limit (`client_max_body_size`) is still the first line in production; this is the
  one that holds when the backend is reached directly.

Dependencies: `config`, `services.bundle_common`.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.services.bundle_common import MAX_IMPORT_UPLOAD_BYTES

#: Headroom over the import ceiling for multipart framing and form fields.
_IMPORT_OVERHEAD_BYTES = 1024 * 1024


def limit_for(path: str) -> int:
    """The largest request body, in bytes, the path accepts.

    Args:
        path: The request path.

    Returns:
        The import ceiling for a path with an `/import` segment, else `Settings.max_request_body_bytes`.
    """
    if "/import" in path:
        return MAX_IMPORT_UPLOAD_BYTES + _IMPORT_OVERHEAD_BYTES
    return get_settings().max_request_body_bytes


class RequestBodyTooLarge(Exception):
    """Raised inside `receive` once a streamed body passes its limit."""


class BodySizeLimitMiddleware:
    """Rejects an oversized request body with 413.

    Args:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Applies the limit to an HTTP request; passes anything else (WebSocket, lifespan) straight through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = False
            if too_big:
                await self._reject(send, limit)
                return

        received = 0
        responded = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal responded
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except RequestBodyTooLarge:
            if not responded:
                await self._reject(send, limit)

    @staticmethod
    async def _reject(send: Send, limit: int) -> None:
        """Sends the 413 response."""
        body = json.dumps({"detail": f"The request is too large (limit {limit // (1024 * 1024)} MB)."}).encode()
        await send({
            "type": "http.response.start", "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")],
        })
        await send({"type": "http.response.body", "body": body})
