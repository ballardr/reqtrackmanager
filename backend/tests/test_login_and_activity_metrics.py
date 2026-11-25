"""Tests for `login_attempts_total` (outcome and method, counted where a sign-in attempt is recorded) and the
`active_users` gauge (distinct authenticated users in the last five minutes, exported as a count only)."""

from __future__ import annotations

import uuid

import pytest
from prometheus_client.parser import text_string_to_metric_families

from app import metrics
from app.database import SessionLocal, engine
from app.services.audit import log_login
from tests.conftest import auth_headers

ADMIN = "admin@example.com"


def _scrape(client) -> str:
    return client.get("/metrics").text


def _login_count(client, result: str, auth_method: str) -> float:
    for family in text_string_to_metric_families(_scrape(client)):
        for sample in family.samples:
            if sample.name == "login_attempts_total" and sample.labels == {"result": result, "auth_method": auth_method}:
                return sample.value
    raise AssertionError(f"no login_attempts_total series for {result}/{auth_method}")


def _active_users(client) -> float:
    metrics.update_worker_gauges(engine)
    for family in text_string_to_metric_families(_scrape(client)):
        for sample in family.samples:
            if sample.name == "active_users":
                return sample.value
    raise AssertionError("no active_users series")


@pytest.fixture(autouse=True)
def _forget_activity():
    metrics._last_seen.clear()
    yield
    metrics._last_seen.clear()


def test_every_outcome_and_method_series_exists_before_the_first_attempt(client):
    text = _scrape(client)
    for result, method in [("success", "password"), ("failure", "password"), ("throttled", "password"), ("success", "sso"), ("failure", "sso")]:
        assert f'login_attempts_total{{auth_method="{method}",result="{result}"}}' in text or (
            f'login_attempts_total{{result="{result}",auth_method="{method}"}}' in text
        )
    assert "throttled" not in "".join(line for line in text.splitlines() if 'auth_method="sso"' in line)


def test_a_password_sign_in_is_counted_as_a_success_and_a_wrong_password_as_a_failure(client):
    ok, bad = _login_count(client, "success", "password"), _login_count(client, "failure", "password")
    assert client.post("/api/v1/auth/login", json={"email": ADMIN, "password": "ChangeMe123!"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": ADMIN, "password": "wrong-password"}).status_code == 401
    assert _login_count(client, "success", "password") == ok + 1
    assert _login_count(client, "failure", "password") == bad + 1


@pytest.mark.parametrize(
    ("kind", "success", "result", "auth_method"),
    [
        ("sso", True, "success", "sso"),
        ("sso", False, "failure", "sso"),
        ("second_factor", False, "failure", "password"),
        ("second_factor", True, "success", "password"),
        ("throttled", False, "throttled", "password"),
    ],
)
def test_each_recorded_attempt_kind_is_counted_once_under_its_method(client, kind, success, result, auth_method):
    before = _login_count(client, result, auth_method)
    db = SessionLocal()
    try:
        log_login(db, user_id=None, email_attempted="nobody@example.com", ip_address="203.0.113.5", success=success, kind=kind)
        db.rollback()
    finally:
        db.close()
    assert _login_count(client, result, auth_method) == before + 1


def test_a_user_seen_twice_is_one_active_user_and_a_stale_one_is_forgotten(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(metrics.time, "monotonic", lambda: clock[0])
    first, second = uuid.uuid4(), uuid.uuid4()
    metrics.record_user_activity(first)
    metrics.record_user_activity(first)
    clock[0] += 200
    metrics.record_user_activity(second)
    assert metrics.count_active_users() == 2
    clock[0] += 150  # the first user's last request is 350 s old, the second's 150 s
    assert metrics.count_active_users() == 1
    assert first not in metrics._last_seen, "an expired entry is dropped, so the map cannot grow without bound"
    clock[0] += 400
    assert metrics.count_active_users() == 0


def test_an_authenticated_request_makes_the_user_active_and_an_anonymous_one_does_not(client, admin_token):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert _active_users(client) == 0
    token = admin_token
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 200
    assert _active_users(client) == 1
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).status_code == 200
    assert _active_users(client) == 1, "the same user is counted once"


def test_a_request_with_a_bad_token_is_not_activity(client):
    assert client.get("/api/v1/auth/me", headers=auth_headers("not-a-token")).status_code == 401
    assert _active_users(client) == 0


def test_the_scrape_carries_the_count_and_never_a_user_identifier(client, admin_token):
    token = admin_token
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()
    metrics.update_worker_gauges(engine)
    text = _scrape(client)
    assert "active_users" in text
    assert me["id"] not in text and ADMIN not in text
