"""
Module: security

Password hashing and JWT access token issuance/verification for the native
authentication backend (C-U-17). Kept independent of any specific auth
backend implementation so it can be reused by future backends that still
need to issue a session token after delegating identity verification
elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

settings = get_settings()


def hash_password(password: str) -> str:
    """Hashes a plaintext password with bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt password hash.
    """
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifies a plaintext password against a bcrypt hash.

    Args:
        password: The plaintext password supplied by the caller.
        password_hash: The stored bcrypt hash to compare against.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    return _pwd_context.verify(password, password_hash)


def create_access_token(subject: str, token_version: int = 0, expires_minutes: int | None = None) -> str:
    """Creates a signed JWT access token.

    Args:
        subject: The value to place in the token's `sub` claim (the user id).
        token_version: The issuing user's current `User.token_version`,
            embedded as the `tv` claim. `deps._resolve_user_from_token`
            rejects any token whose `tv` doesn't match the user's *current*
            `token_version` — password change / 2FA disable increment it,
            deterministically invalidating every previously issued token
            (see `User.token_version`'s docstring for why this is a version
            counter and not a timestamp comparison).
        expires_minutes: Optional override for token lifetime in minutes.

    Returns:
        An encoded JWT string.
    """
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "tv": token_version, "purpose": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_2fa_challenge_token(subject: str) -> str:
    """Creates a short-lived token proving password verification succeeded,
    used as the second leg of a two-factor login (C-U-14).

    This token alone does not grant API access — `get_current_user`
    (app/deps.py) only accepts tokens with `purpose == "access"` — it only
    proves the holder passed the first login step and may attempt the TOTP
    code exchange.
    """
    expire = datetime.now(UTC) + timedelta(minutes=5)
    payload = {"sub": subject, "exp": expire, "purpose": "2fa_challenge"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_oidc_state_token(organization_id: str, client_nonce: str) -> str:
    """Creates a short-lived signed token carrying the organisation id
    (and the browser-generated client nonce, see below) through an OIDC
    authorization-code round trip (E-U-01), used as the `state` parameter.

    Avoids needing server-side session storage for `state`: the org id is
    embedded directly in a signed token rather than looked up from a
    session, so the callback handler can recover it (and be sure it wasn't
    tampered with) without any shared server-side state between the
    redirect and the callback.

    `client_nonce`: a random value the *frontend* generates and stores in
    `sessionStorage` before it ever navigates to the login-start endpoint,
    echoed back through this token and the eventual callback redirect. This
    is what proves the browser landing on `/oidc-complete` with a token is
    the same browser that actually initiated this specific login attempt —
    without it, `state` alone only proves the org wasn't tampered with, not
    who's holding the resulting session. See `routers/auth_oidc.py` and
    `OidcCompletePage.tsx` for the two ends of this check; without it, an
    attacker could complete their own legitimate login (native or SSO,
    unrelated to any particular org's flow) and hand a victim a crafted
    `/oidc-complete?token=...` link, silently logging the victim's browser
    into the attacker's account (a login-CSRF / session-fixation pattern).
    """
    expire = datetime.now(UTC) + timedelta(minutes=10)
    payload = {"org_id": organization_id, "client_nonce": client_nonce, "exp": expire, "purpose": "oidc_state"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decodes and validates a JWT access token.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded claims dict, or None if the token is invalid or expired.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
