"""Tests for `GET /api/v1/system/version` (`app/version.py`, `routers/system.py`)
— the backend's own build identity, surfaced for the nav rail's version
footer (2026-08 UX audit follow-up: "a way to see the version and date of
the frontend and backend in the UI")."""

from app.version import APP_VERSION
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


def test_openapi_metadata_version_matches_app_version(client):
    """Pins `app/main.py`'s `FastAPI(version=...)` to `app.version.APP_VERSION`
    rather than the previously-hardcoded, permanently-stale "1.0.0" (2026-08
    UX audit roadmap, "Fix the hardcoded FastAPI(version="1.0.0") OpenAPI
    metadata constant") — asserted two ways so a regression back to a
    literal constant is caught regardless of which surface someone checks:
    the live `FastAPI` app instance's own `.version` attribute, and the
    `/openapi.json` schema's `info.version` field it feeds into `/docs`."""
    assert client.app.version == APP_VERSION
    resp = client.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    assert resp.json()["info"]["version"] == APP_VERSION
