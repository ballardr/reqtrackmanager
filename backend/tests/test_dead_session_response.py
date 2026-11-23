"""A refused credential is answered so the browser can end the session, and no other 401 is.

The interface and the API are on different origins in the default stack, so a browser reads only the response headers the
CORS middleware exposes. `WWW-Authenticate` marks a dead token in a header; the body carries `code: invalid_token` as well,
so a proxy that removes a header cannot hide it. A wrong password or a bad second-factor code carries neither, because
signing the person out for a typing mistake would be a defect. See `app.deps.InvalidTokenError`.
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.security import create_2fa_challenge_token, create_access_token, create_media_token
from tests.conftest import auth_headers

ORIGIN = {"Origin": "http://localhost:3000"}
DEAD_BODY = {"detail": "Could not validate credentials.", "code": "invalid_token"}


def _admin() -> User:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert user is not None
        db.expunge(user)
        return user


def _expect_dead_session(resp) -> None:
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    assert resp.json() == DEAD_BODY


def test_a_cross_origin_page_may_read_the_dead_session_header(client):
    """Without this a browser reads `null` for `WWW-Authenticate` and never learns the session is over."""
    resp = client.get("/health", headers=ORIGIN)

    exposed = {name.strip().lower() for name in resp.headers["access-control-expose-headers"].split(",")}
    assert {"www-authenticate", "x-projects-truncated"} <= exposed


def test_a_dead_token_response_is_readable_cross_origin(client):
    resp = client.get("/api/v1/auth/me", headers={**ORIGIN, **auth_headers("not-a-token")})

    _expect_dead_session(resp)
    assert "www-authenticate" in resp.headers["access-control-expose-headers"].lower()


def test_every_cause_of_a_dead_token_answers_identically(client, admin_token):
    """Expired, malformed, superseded, wrong kind, revoked and absent look the same, so the answer tells an
    unauthenticated caller nothing about which tokens exist."""
    admin = _admin()
    subject = str(admin.id)
    cases = {
        "malformed": "not-a-token",
        "expired": create_access_token(subject, admin.token_version, expires_minutes=-5),
        "superseded": create_access_token(subject, admin.token_version + 1),
        "second-factor challenge": create_2fa_challenge_token(subject),
        "media token in the header": create_media_token(subject, admin.token_version),
        "unknown personal access token": "rtm_pat_" + "x" * 40,
    }
    for name, token in cases.items():
        resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
        assert resp.status_code == 401, name
        assert resp.headers["www-authenticate"] == "Bearer", name
        assert resp.json() == DEAD_BODY, name

    _expect_dead_session(client.get("/api/v1/auth/me"))


def test_a_deactivated_account_ends_its_session(client):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert user is not None
        token = create_access_token(str(user.id), user.token_version)
        user.is_active = False
        db.commit()
    try:
        _expect_dead_session(client.get("/api/v1/auth/me", headers=auth_headers(token)))
    finally:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "admin@example.com"))
            assert user is not None
            user.is_active = True
            db.commit()


def test_a_password_change_elsewhere_ends_the_session(client, admin_token):
    """Raising `token_version` (what a password change does) refuses the token already held."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert user is not None
        user.token_version += 1
        db.commit()
    try:
        _expect_dead_session(client.get("/api/v1/auth/me", headers=auth_headers(admin_token)))
    finally:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "admin@example.com"))
            assert user is not None
            user.token_version -= 1
            db.commit()


def test_a_business_401_does_not_end_the_session(client, admin_token):
    """A wrong password, a wrong current password and a bad second-factor challenge are mistakes, not a dead session."""
    wrong_login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password"})
    wrong_current = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "AnotherPassw0rd!"},
        headers=auth_headers(admin_token),
    )
    bad_challenge = client.post("/api/v1/auth/2fa/verify", json={"challenge_token": "garbage", "code": "123456"})

    for resp in (wrong_login, wrong_current, bad_challenge):
        assert resp.status_code == 401
        assert "www-authenticate" not in resp.headers
        assert "code" not in resp.json()


def test_only_the_reviewed_modules_raise_their_own_401():
    """A new route that raises its own 401 for a bad token would miss the marker; it must use the shared exception.

    The listed files raise a 401 for something other than the session token: sign-in and challenge mistakes, the SCIM
    credential, the single-sign-on callback, and a file download that carried no credential at all.
    """
    reviewed = {"routers/auth.py", "routers/auth_oidc.py", "routers/scim.py", "routers/files.py"}
    app_dir = Path(__file__).resolve().parent.parent / "app"
    raising = {
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if "HTTP_401_UNAUTHORIZED" in path.read_text() and path.name != "deps.py"
    }

    assert raising <= reviewed, f"raise InvalidTokenError (deps._UNAUTHORIZED) for a dead token: {sorted(raising - reviewed)}"


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/projects"])
def test_the_marker_is_on_ordinary_routes(client, path):
    _expect_dead_session(client.get(path, headers=auth_headers("not-a-token")))
