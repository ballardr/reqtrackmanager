"""Tests for the client address (forged headers ignored), the progressive login delay and the sign-up limit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import LoginEvent
from app.services import login_throttle
from app.services.audit import log_login
from tests.conftest import login

ADMIN = "admin@example.com"


def _bad(client, email=ADMIN, headers=None):
    return client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"}, headers=headers or {})


def test_a_forged_forwarded_header_does_not_choose_the_recorded_address(client):
    _bad(client, headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    db = SessionLocal()
    try:
        event = db.query(LoginEvent).filter(LoginEvent.email_attempted == ADMIN).one()
        assert event.ip_address != "203.0.113.9"
    finally:
        db.close()


def test_a_very_long_forwarded_header_cannot_break_the_login(client):
    resp = _bad(client, headers={"X-Forwarded-For": "9" * 500})
    assert resp.status_code == 401


def test_failures_within_the_allowance_are_not_delayed(client):
    free = get_settings().login_delay_free_attempts_account
    assert [_bad(client).status_code for _ in range(free)] == [401] * free


def test_the_attempt_after_the_allowance_waits_and_a_correct_password_is_not_checked(client):
    free = get_settings().login_delay_free_attempts_account
    for _ in range(free):
        _bad(client)
    resp = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": "ChangeMe123!"})
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    assert "Too many sign-in attempts" in resp.json()["detail"]


def test_an_unknown_address_is_delayed_in_the_same_way(client):
    free = get_settings().login_delay_free_attempts_account
    for _ in range(free):
        _bad(client, "nobody@example.com")
    assert _bad(client, "nobody@example.com").status_code == 429


def test_refused_attempts_do_not_extend_the_wait(client):
    free = get_settings().login_delay_free_attempts_account
    for _ in range(free):
        _bad(client)
    waits = {int(_bad(client).headers["Retry-After"]) for _ in range(5)}
    assert max(waits) <= get_settings().login_delay_base_seconds
    db = SessionLocal()
    try:
        assert db.query(LoginEvent).filter(LoginEvent.kind == "throttled").count() == 5
    finally:
        db.close()


def test_the_wait_doubles_and_is_capped():
    assert [login_throttle._delay_seconds(n, 5, 5, 300) for n in (4, 5, 6, 7, 20)] == [0, 5, 10, 20, 300]


def test_the_delay_ends_by_itself_and_a_success_resets_the_account(client):
    free = get_settings().login_delay_free_attempts_account
    db = SessionLocal()
    try:
        long_ago = datetime.now(UTC) - timedelta(seconds=get_settings().login_delay_base_seconds + 5)
        for _ in range(free):
            event = log_login(db, user_id=None, email_attempted=ADMIN, ip_address="198.51.100.1", success=False)
            event.created_at = long_ago
        db.commit()
        assert login_throttle.seconds_to_wait(db, ADMIN, "198.51.100.2") == 0
        db.rollback()
        for _ in range(free):
            event = log_login(db, user_id=None, email_attempted=ADMIN, ip_address="198.51.100.1", success=False)
        db.commit()
        assert login_throttle.seconds_to_wait(db, ADMIN, "198.51.100.2") > 0
        db.rollback()
        log_login(db, user_id=None, email_attempted=ADMIN, ip_address="198.51.100.1", success=True)
        db.commit()
        assert login_throttle.seconds_to_wait(db, ADMIN, "198.51.100.2") == 0
    finally:
        db.close()


def test_the_wait_is_in_utc_and_does_not_depend_on_the_viewer_zone():
    """A past instant: the same stored UTC times give the same wait at any offset; the boundary is the exact second."""
    db = SessionLocal()
    try:
        cfg = get_settings()
        free = cfg.login_delay_free_attempts_account
        base = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)  # 23:00 UTC is 09:00 the next day at UTC+10
        for _ in range(free):
            event = log_login(db, user_id=None, email_attempted=ADMIN, ip_address="198.51.100.1", success=False)
            event.created_at = base
        db.commit()
        base_s = cfg.login_delay_base_seconds
        assert login_throttle.seconds_to_wait(db, ADMIN, "x", now=base + timedelta(seconds=base_s - 1)) == 1
        db.rollback()
        assert login_throttle.seconds_to_wait(db, ADMIN, "x", now=base + timedelta(seconds=base_s)) == 0
    finally:
        db.close()


def test_one_account_failing_does_not_delay_another_from_another_address(client):
    free = get_settings().login_delay_free_attempts_account
    for _ in range(free):
        _bad(client)
    db = SessionLocal()
    try:
        assert login_throttle.seconds_to_wait(db, "someone-else@example.com", "198.51.100.77") == 0
    finally:
        db.close()


def test_a_normal_login_still_works(client):
    assert login(client, ADMIN, "ChangeMe123!")


def test_sign_up_is_limited_per_address(client):
    cfg = get_settings()
    codes = [
        client.post("/api/v1/auth/signup", json={"email": f"p{i}@example.com", "password": "Sufficient-Passw0rd!", "display_name": "P"}).status_code
        for i in range(cfg.public_auth_rate_limit_burst + 2)
    ]
    assert 429 in codes


def test_the_password_rule_applies_where_a_password_is_chosen_not_where_it_is_used(client):
    from app.services.password_policy import MAX_PASSWORD_BYTES, password_problem

    assert password_problem("short") is not None
    assert password_problem("Password123") is not None  # on the built-in list (case-insensitive)
    assert password_problem("aaaaaaaaaaaa") is not None
    assert password_problem("person@example.com", "person@example.com") is not None
    assert password_problem("x" * (MAX_PASSWORD_BYTES + 1) + "!") is not None
    assert password_problem("é" * 37) is not None  # 74 bytes: bytes, not characters, are what bcrypt reads
    assert password_problem("Correct-Horse-Battery-9") is None

    refused = client.post(
        "/api/v1/auth/signup", json={"email": "weak@example.com", "password": "password123", "display_name": "Weak"}
    )
    assert refused.status_code == 422
    assert login(client, ADMIN, "ChangeMe123!")  # an existing password that would not pass today still signs in
