"""Tests for the token-bucket rate limiter (`services.rate_limit`) and its use on the global search."""

from __future__ import annotations

import uuid

from app.config import get_settings
from app.services.rate_limit import RateLimiter
from tests.conftest import auth_headers, create_org_admin_in


class _Clock:
    """A settable monotonic clock, so no test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_burst_is_allowed_then_refused_with_the_wait_until_the_next_token():
    clock = _Clock()
    limiter = RateLimiter(capacity=3, refill_per_second=1.0, clock=clock)
    assert [limiter.acquire("a") for _ in range(3)] == [None, None, None]
    wait = limiter.acquire("a")
    assert wait is not None and 0.99 <= wait <= 1.0
    clock.now += 0.5
    assert 0.49 <= limiter.acquire("a") <= 0.5  # half a token so far
    clock.now += 0.5
    assert limiter.acquire("a") is None


def test_tokens_refill_up_to_the_capacity_and_no_further():
    clock = _Clock()
    limiter = RateLimiter(capacity=2, refill_per_second=1.0, clock=clock)
    assert limiter.acquire("a") is None and limiter.acquire("a") is None
    clock.now += 3600
    assert limiter.acquire("a") is None and limiter.acquire("a") is None
    assert limiter.acquire("a") is not None  # an hour idle gave two tokens, not 3,600


def test_callers_are_limited_independently():
    limiter = RateLimiter(capacity=1, refill_per_second=0.1, clock=_Clock())
    assert limiter.acquire("a") is None
    assert limiter.acquire("a") is not None
    assert limiter.acquire("b") is None


def test_a_non_positive_limit_disables_the_limiter():
    limiter = RateLimiter(capacity=0, refill_per_second=1.0, clock=_Clock())
    assert not limiter.enabled
    assert all(limiter.acquire("a") is None for _ in range(100))


def test_idle_buckets_are_swept_so_memory_stays_bounded(monkeypatch):
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "_SWEEP_THRESHOLD", 5)
    clock = _Clock()
    limiter = RateLimiter(capacity=1, refill_per_second=1.0, clock=clock)
    for i in range(6):
        limiter.acquire(i)
    clock.now += 10
    limiter.acquire("fresh")
    assert len(limiter._buckets) == 1


def test_the_search_endpoints_answer_429_with_retry_after_and_limit_each_person_alone(client, admin_token, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "search_rate_limit_burst", 3)
    monkeypatch.setattr(settings, "search_rate_limit_per_minute", 60)
    _, first = create_org_admin_in(client, admin_token, f"Rate Limit One {uuid.uuid4().hex[:6]}")
    _, second = create_org_admin_in(client, admin_token, f"Rate Limit Two {uuid.uuid4().hex[:6]}")

    def search(token):
        return client.post("/api/v1/search", json={"q": "anything", "scope": "all"}, headers=auth_headers(token))

    assert [search(first).status_code for _ in range(3)] == [200, 200, 200]
    refused = search(first)
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1 and "searching too fast" in refused.json()["detail"]
    # The field list spends from the same bucket.
    assert client.get("/api/v1/search/fields", headers=auth_headers(first)).status_code == 429
    # Another person is unaffected.
    assert search(second).status_code == 200


def test_a_zero_limit_turns_the_search_limiter_off(client, admin_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "search_rate_limit_burst", 0)
    _, token = create_org_admin_in(client, admin_token, f"Rate Limit Off {uuid.uuid4().hex[:6]}")
    codes = {client.post("/api/v1/search", json={"q": "anything", "scope": "all"}, headers=auth_headers(token)).status_code for _ in range(8)}
    assert codes == {200}
