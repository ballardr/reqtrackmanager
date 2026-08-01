"""Tests for authentication: login success/failure and the current-user endpoint."""

from tests.conftest import auth_headers, login


def test_login_success_returns_token_and_user(client):
    token = login(client, "admin@example.com", "ChangeMe123!")
    assert token

    resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@example.com"
    assert resp.json()["is_server_admin"] is True


def test_login_wrong_password_returns_401(client):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_login_is_audited(client, admin_token):
    """Every login attempt, successful or not, is recorded (C-A-07)."""
    client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    from app.database import SessionLocal
    from app.models.audit import LoginEvent

    db = SessionLocal()
    try:
        events = db.query(LoginEvent).filter(LoginEvent.email_attempted == "admin@example.com").all()
        assert any(e.success for e in events)
        assert any(not e.success for e in events)
    finally:
        db.close()
