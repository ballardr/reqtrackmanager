"""
Module: security

Password hashing and JWT access token issuance/verification for the native
authentication backend (C-U-17). Kept independent of any specific auth
backend implementation so it can be reused by future backends that still
need to issue a session token after delegating identity verification
elsewhere.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

settings = get_settings()

PAT_PREFIX = "rtm_pat_"
SCIM_TOKEN_PREFIX = "rtm_scim_"


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


def create_oidc_state_token(organization_id: str, client_nonce: str, client: str = "app") -> str:
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

    `client`: which caller started this login attempt — `"app"` (the
    frontend, default) or `"mcp"` (`mcp-server`'s own `/login` page). Only
    ever one of these two literal, server-defined values, embedded in this
    *signed* token rather than trusted from any redirect-target string
    supplied by the caller — `routers/auth_oidc.py`'s callback uses it only
    to pick between two fixed, server-configured redirect base URLs, never
    to redirect somewhere client-controlled (which would be an open
    redirect / token-theft vector).
    """
    expire = datetime.now(UTC) + timedelta(minutes=10)
    payload = {
        "org_id": organization_id, "client_nonce": client_nonce, "client": client,
        "exp": expire, "purpose": "oidc_state",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_email_unsubscribe_token(user_id: str) -> str:
    """Creates a long-lived signed token embedded in the footer "manage
    your email preferences" link of every outgoing email
    (`services/notifications.py`), letting a recipient disable email
    notifications with a single click, without logging in first.

    Deliberately long-lived (2 years) rather than short-lived like
    `create_access_token`/`create_oidc_state_token`: unlike those, this
    token grants no session and no privileged action — the one thing it
    can ever do, via `routers/notifications.py::unsubscribe`, is set
    `User.email_digest_mode = DigestMode.NONE`, the exact same field a
    logged-in user can already set themselves from the Preferences page
    (`PUT /auth/me`). A stolen or forwarded link's worst case is someone
    else turning off a user's email notifications — an availability/
    annoyance issue, not a confidentiality or integrity breach — so the
    usual "keep it short-lived" session-token reasoning doesn't apply, and
    a working link that expires after a few weeks would be a worse
    experience for no real security benefit. Every use (successful or
    rejected) is still written to the audit trail — see the endpoint.
    """
    expire = datetime.now(UTC) + timedelta(days=730)
    payload = {"sub": user_id, "exp": expire, "purpose": "email_unsubscribe"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_email_unsubscribe_token(token: str) -> str | None:
    """Decodes an unsubscribe token created by `create_email_unsubscribe_token`.

    Returns:
        The embedded user id, or `None` if the token is invalid, expired,
        or wasn't issued for this purpose (e.g. an access token replayed
        here, which must not be accepted).
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("purpose") != "email_unsubscribe":
        return None
    return payload.get("sub")


def create_module_frame_token(
    module_key: str, organization_id: str, user_id: str, project_id: str | None = None
) -> str:
    """Creates a short-lived signed JWT scoping a Tier B `<ModuleFrame>`
    iframe's own backend calls to exactly one module, organisation,
    (optionally) project, and user (compliance-module-plan.md Phase 3).

    Minted by `POST /orgs/{id}/modules/{module_key}/frame-token` or
    `POST /projects/{id}/modules/{module_key}/frame-token` for a caller who
    already holds a normal session (those endpoints depend on
    `require_org_module_enabled_dynamic`/`require_project_module_enabled_
    dynamic`, which only accept a real `get_current_user` session — a
    module-frame token can never be used to mint another one, since
    `deps.get_current_user` rejects any token whose `purpose` isn't
    `"access"`). The minted token itself is deliberately narrower than the
    caller's real session: `app.deps.get_current_user_or_module_frame` only
    accepts it for the one `module_key` it was minted for, and `app.
    services.rbac._enforce_module_frame_scope` additionally requires the
    request's own `organization_id`/`project_id` path parameter to match
    the token's — so the remote module's own code, which receives this
    token (not the user's real session token) via the Host UI Bridge's
    `init` message, can only ever reach that one module's own endpoints for
    that one org/project, regardless of what else the underlying user could
    otherwise do.

    Args:
        module_key: The module this token is scoped to.
        organization_id: The organisation this token is scoped to.
        user_id: The real user this token was minted for.
        project_id: The project this token is scoped to, for a
            project-mounted `<ModuleFrame>` — `None` for an org-mounted one.

    Returns:
        An encoded JWT string, expiring in 15 minutes.
    """
    expire = datetime.now(UTC) + timedelta(minutes=15)
    payload = {
        "module_key": module_key, "organization_id": organization_id,
        "project_id": project_id, "user_id": user_id,
        "exp": expire, "purpose": "module_frame",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_module_frame_token(token: str) -> dict[str, Any] | None:
    """Decodes a token created by `create_module_frame_token`.

    Returns:
        The decoded claims dict, or `None` if the token is invalid, expired,
        or wasn't issued for this purpose (e.g. a normal access token
        replayed here, which must not be accepted).
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("purpose") != "module_frame":
        return None
    return payload


def generate_pat() -> tuple[str, str, str]:
    """Generates a new Personal Access Token secret.

    Deliberately an opaque random secret, not a JWT: unlike a session
    token, a PAT needs instant, per-token revocation (an org/server admin
    "revoke now" action must take effect immediately, not wait for a
    signature-only check to naturally expire), which is a simple hash
    lookup against a DB row rather than a second revocation-list mechanism
    bolted onto a supposedly-stateless token. Mirrors how this codebase
    already treats passwords: only a hash is ever persisted.

    Returns:
        A 3-tuple of `(raw_token, token_hash, token_prefix)`:
        - `raw_token`: the full secret, e.g. `rtm_pat_<43 url-safe chars>`.
          Shown to the caller exactly once, at creation, and never
          recoverable afterward — only its hash is stored.
        - `token_hash`: the SHA-256 hex digest to persist and look up by.
        - `token_prefix`: the first ~14 characters of `raw_token`, safe to
          store and display in plaintext so a user's token list can help
          them recognise which token is which without exposing the secret.
    """
    raw_token = f"{PAT_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_token, hash_pat(raw_token), raw_token[: len(PAT_PREFIX) + 6]


def hash_pat(raw_token: str) -> str:
    """Hashes a raw PAT secret for storage/lookup.

    Args:
        raw_token: The full, plaintext token secret.

    Returns:
        The SHA-256 hex digest. Unlike password hashing, this is a plain
        fast hash rather than bcrypt — the input is already a
        cryptographically random 32-byte secret (not a human-memorable,
        low-entropy password), so there's no offline brute-force risk a
        slow hash would need to defend against; a fast hash keeps every
        authenticated request's lookup cheap.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_scim_token() -> tuple[str, str, str]:
    """Generates a new per-organisation SCIM 2.0 bearer token
    (`routers/scim.py`). Same shape and hashing rationale as `generate_pat`
    — an opaque, instantly-revocable random secret, not a JWT — just a
    different, recognisable prefix so a token pasted into the wrong config
    field is obviously not a PAT (or vice versa).

    Returns:
        A 3-tuple of `(raw_token, token_hash, token_prefix)`, same meaning
        as `generate_pat`'s return value.
    """
    raw_token = f"{SCIM_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_token, hash_pat(raw_token), raw_token[: len(SCIM_TOKEN_PREFIX) + 6]


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
