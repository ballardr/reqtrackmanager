"""Tests for `app.concurrency_limit`: the per-worker ceiling on requests in flight.

Covers the ceiling, the queue and its timeout, that health/metrics/WebSocket traffic is never held, that a slot is freed
when a handler fails, and that the default equals the database pool's capacity (the number that cannot exhaust it).
"""

from __future__ import annotations

import asyncio

import pytest

from app.concurrency_limit import ConcurrencyLimitMiddleware, effective_limit
from app.config import get_settings


class _Probe:
    """An ASGI app that records how many requests are inside it at once and holds each until released."""

    def __init__(self) -> None:
        self.inside = 0
        self.peak = 0
        self.gate = asyncio.Event()
        self.fail = False

    async def __call__(self, scope, receive, send) -> None:
        self.inside += 1
        self.peak = max(self.peak, self.inside)
        try:
            await self.gate.wait()
            if self.fail:
                raise RuntimeError("handler failed")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        finally:
            self.inside -= 1


async def _request(app, path="/api/v1/thing", scope_type="http"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    try:
        await app({"type": scope_type, "path": path, "headers": []}, receive, send)
    except RuntimeError:
        return "raised"
    return sent[0]["status"] if sent else None


def test_at_most_the_limit_run_at_once_and_the_rest_wait_for_a_slot():
    async def scenario():
        probe = _Probe()
        app = ConcurrencyLimitMiddleware(probe, limit=3, queue_timeout=5)
        tasks = [asyncio.create_task(_request(app)) for _ in range(8)]
        await asyncio.sleep(0.05)
        assert probe.inside == 3, "three admitted, five waiting in the event loop"
        probe.gate.set()
        results = await asyncio.gather(*tasks)
        assert results == [200] * 8 and probe.peak == 3

    asyncio.run(scenario())


def test_a_request_that_waits_past_the_timeout_gets_503_with_retry_after():
    async def scenario():
        probe = _Probe()
        app = ConcurrencyLimitMiddleware(probe, limit=1, queue_timeout=0.05)
        sent = []

        async def send(message):
            sent.append(message)

        holder = asyncio.create_task(_request(app))
        await asyncio.sleep(0.02)
        await app({"type": "http", "path": "/api/v1/thing", "headers": []}, lambda: None, send)
        assert sent[0]["status"] == 503 and (b"retry-after", b"2") in sent[0]["headers"]
        probe.gate.set()
        assert await holder == 200

    asyncio.run(scenario())


def test_health_metrics_and_websockets_are_never_held():
    async def scenario():
        probe = _Probe()
        app = ConcurrencyLimitMiddleware(probe, limit=1, queue_timeout=5)
        holder = asyncio.create_task(_request(app))
        await asyncio.sleep(0.02)
        others = [asyncio.create_task(_request(app, "/health")), asyncio.create_task(_request(app, "/metrics")),
                  asyncio.create_task(_request(app, "/ws/stream", scope_type="websocket"))]
        await asyncio.sleep(0.05)
        assert probe.inside == 4, "the three exempt requests are inside while the one slot is taken"
        probe.gate.set()
        await asyncio.gather(holder, *others)

    asyncio.run(scenario())


def test_a_failing_handler_frees_its_slot():
    async def scenario():
        probe = _Probe()
        probe.fail = True
        probe.gate.set()
        app = ConcurrencyLimitMiddleware(probe, limit=1, queue_timeout=1)
        assert await _request(app) == "raised"
        probe.fail = False
        assert await _request(app) == 200, "the next request is not left waiting for the failed one's slot"

    asyncio.run(scenario())


def test_default_limit_is_the_database_pools_capacity(monkeypatch):
    settings = get_settings()
    assert settings.max_concurrent_requests == 0
    assert effective_limit() == settings.db_pool_size + settings.db_max_overflow
    monkeypatch.setattr(settings, "max_concurrent_requests", 7)
    assert effective_limit() == 7


def test_the_application_installs_the_limit(client):
    from app.main import app

    assert any(m.cls is ConcurrencyLimitMiddleware for m in app.user_middleware)
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("name", ["max_concurrent_requests", "request_queue_timeout_seconds"])
def test_the_settings_are_documented_in_the_configuration_reference(name):
    from pathlib import Path

    reference = Path(__file__).resolve().parents[2] / "docs/website/docs/installation-deployment/configuration-reference.md"
    if not reference.is_file():
        pytest.skip("docs are not mounted")
    assert name.upper() in reference.read_text()
