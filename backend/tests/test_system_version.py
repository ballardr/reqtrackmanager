"""Tests for `GET /api/v1/system/version` (`app/version.py`, `routers/system.py`)
— the backend's own build identity, surfaced for the nav rail's version
footer (2026-08 UX audit follow-up: "a way to see the version and date of
the frontend and backend in the UI")."""

from tests.conftest import auth_headers


def test_version_reachable_by_any_authenticated_user(client, admin_token):
    resp = client.get("/api/v1/system/version", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"version", "git_sha", "build_date"}
    # No build ARGs are set in the test environment, so app/version.py's
    # own documented fallbacks apply — pinning that behaviour rather than
    # a specific value, since the real value varies by build.
    assert body == {"version": "dev", "git_sha": "unknown", "build_date": "unknown"}


def test_version_requires_authentication(client):
    resp = client.get("/api/v1/system/version")
    assert resp.status_code == 401
