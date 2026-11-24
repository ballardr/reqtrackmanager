"""
Module: deps

Shared FastAPI dependencies: current-user resolution from a bearer token
(a session JWT or a Personal Access Token), and a client-IP extractor used
for login auditing (C-A-07).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.user import User
from app.security import PAT_PREFIX, decode_access_token, decode_module_frame_token, hash_pat

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)
settings = get_settings()

INVALID_TOKEN_CODE = "invalid_token"


class InvalidTokenError(HTTPException):
    """A 401 for a credential that is missing, malformed, expired, revoked or superseded: the session is over.

    The response body is `{"detail": <text>, "code": "invalid_token"}` (see `app.main`'s handler) and carries
    `WWW-Authenticate: Bearer`. The client treats either signal as the end of the session, because a browser on
    another origin cannot read a response header the server has not exposed, and a proxy may strip one. Every
    cause answers identically, so the response never says whether a token expired, was revoked or never existed.
    A 401 for a wrong password or a bad second-factor code is an ordinary `HTTPException` and carries neither.
    """


_UNAUTHORIZED = InvalidTokenError(
    status.HTTP_401_UNAUTHORIZED,
    "Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _pat_effective_expiry(pat: PersonalAccessToken, db: Session) -> datetime:
    """Computes a PAT's actual, currently-enforced expiry.

    This is `min(pat.expires_at_ceiling, *cap)`, where `cap` is one entry
    per currently-scoped org: `pat.created_at + that org's *current*
    pat_max_lifetime_days (or the system default)`. Recomputing from live
    org settings on every check — rather than only reading the stored
    `expires_at_ceiling` — is what makes an org admin tightening their cap
    apply retroactively to already-issued tokens: this can only ever push
    the effective expiry earlier than `expires_at_ceiling`, never later.
    """
    caps = [pat.expires_at_ceiling]
    for org_id in pat.allowed_organization_ids:
        org = db.get(Organization, UUID(org_id))
        if org is None:
            continue
        max_days = org.pat_max_lifetime_days or settings.pat_default_max_lifetime_days
        caps.append(pat.created_at + timedelta(days=max_days))
    return min(caps)


def _resolve_user_from_pat(token: str, db: Session, request: Request) -> User:
    """Resolves a Personal Access Token to the user it belongs to.

    Raises:
        HTTPException: 401 if the token does not exist, is revoked, is past its effective expiry, or
            names an inactive or archived user.

    Side effects:
        Sets `request.state.pat_allowed_org_ids` (the token's scoped org ids) and
        `request.state.pat_allowed_project_ids` (its optional project restriction, `None` if unset), which
        `services/rbac.py` reads to restrict access on top of the user's RBAC roles. Stamps `last_used_at`
        at most once per hour to avoid a write on every request.
    """
    pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.token_hash == hash_pat(token)))
    if pat is None or pat.revoked_at is not None:
        raise _UNAUTHORIZED
    if datetime.now(UTC) >= _pat_effective_expiry(pat, db):
        raise _UNAUTHORIZED
    user = db.get(User, pat.user_id)
    if user is None or not user.is_active or user.is_archived:
        raise _UNAUTHORIZED

    if pat.last_used_at is None or datetime.now(UTC) - pat.last_used_at > timedelta(hours=1):
        pat.last_used_at = datetime.now(UTC)
        db.commit()

    request.state.pat_allowed_org_ids = {UUID(org_id) for org_id in pat.allowed_organization_ids}
    # None (not an empty set) means no project restriction: an empty list is the unrestricted default,
    # not "scoped to zero projects".
    request.state.pat_allowed_project_ids = (
        {UUID(project_id) for project_id in pat.allowed_project_ids} if pat.allowed_project_ids else None
    )
    # The same scope on the session, for code that reads other projects on the caller's behalf
    # (`rbac.session_may_reach_project`) and has no request to look at.
    db.info["pat_allowed_org_ids"] = request.state.pat_allowed_org_ids
    db.info["pat_allowed_project_ids"] = request.state.pat_allowed_project_ids
    return user


def _require_policies_accepted(user: User, db: Session, request: Request) -> User:
    """Refuses a request that changes data while the user has an unaccepted required policy.

    See `services.policy_acknowledgements`: reading, searching, the policies, sign-in and sign-out stay open.

    Raises:
        HTTPException: 403 (`policy_acknowledgement_required`) for a blocked request.
    """
    from app.services import password_change_gate
    from app.services.policy_acknowledgements import enforce_accepted

    password_change_gate.enforce(user, request.method, request.url.path)
    enforce_accepted(db, user, request.method, request.url.path)
    return user


def _resolve_user_from_token(token: str | None, db: Session, request: Request) -> User:
    """Decodes and validates a bearer token, returning the active user it names.

    Dispatches to `_resolve_user_from_pat` for Personal Access Tokens (`rtm_pat_` prefix, see
    `security.PAT_PREFIX`) and otherwise validates a session JWT. A session JWT never sets
    `request.state.pat_allowed_org_ids`, which lets `services/rbac.py` tell "not a PAT, no restriction"
    from "a PAT scoped to these orgs".

    Args:
        token: The raw bearer token, or None if the request had none.
        db: Active database session.
        request: The incoming request, which carries PAT scope to the RBAC dependencies.

    Returns:
        The authenticated, active, non-archived user.

    Raises:
        HTTPException: 401 if the token is missing, invalid, not an access token (for example a 2FA
            challenge token), or names an inactive or archived user.
    """
    if not token:
        raise _UNAUTHORIZED
    if token.startswith(PAT_PREFIX):
        return _require_policies_accepted(_resolve_user_from_pat(token, db, request), db, request)
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "access":
        # Rejects 2FA challenge tokens (services/totp.py / routers/auth.py):
        # those only prove password verification succeeded and must not be
        # usable as a real access token before the TOTP step completes.
        raise _UNAUTHORIZED
    user = db.get(User, UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_archived:
        raise _UNAUTHORIZED
    if claims.get("tv", 0) != user.token_version:
        # Token was issued before the user's most recent password change /
        # 2FA disable (see User.token_version) — reject even though the
        # signature/expiry are otherwise valid.
        raise _UNAUTHORIZED
    return _require_policies_accepted(user, db, request)


def get_current_user(
    request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolves the current authenticated user from a bearer token (a
    session JWT or a Personal Access Token).

    Args:
        request: The incoming request (see `_resolve_user_from_token`).
        token: The bearer token extracted from the Authorization header.
        db: An active database session.

    Returns:
        The authenticated, active User.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or the user is
            inactive/archived.
    """
    return _resolve_user_from_token(token, db, request)


LIFECYCLE_SKIP_HEADER = "X-Lifecycle-Skip-Reason"


def capture_lifecycle_skip(
    request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> None:
    """Route dependency that reads a request to skip steps of a record's lifecycle.

    A move endpoint is asked to skip steps with the percent-encoded reason in `X-Lifecycle-Skip-Reason`; the request
    is recorded on the session for `services.lifecycles.check_move`. A request without the header is untouched, and
    the header never authenticates by itself: the caller must hold a normal session or personal access token.

    Raises:
        HTTPException: 400 for an empty or over-long reason, 401 for no valid credential.
    """
    raw = request.headers.get(LIFECYCLE_SKIP_HEADER)
    if raw is None or request.method != "POST":
        return
    from app.services.lifecycles import request_skip

    request_skip(db, _resolve_user_from_token(token, db, request), unquote(raw))


_PAT_REFUSED = "Personal access tokens cannot manage account security or other access tokens; sign in to do this."


def refuse_personal_access_token(token: str | None = Depends(oauth2_scheme)) -> None:
    """Route dependency (`dependencies=[Depends(...)]`) refusing a Personal Access Token.

    For an action whose effect outlives or widens the token: granting or revoking a role, creating an account
    with a chosen password, issuing the SCIM token, changing single sign-on. A PAT is a scoped, long-lived,
    headless credential; if it could do these, its scope and expiry would only be a suggestion to its holder.

    Raises:
        HTTPException: 403 when the bearer token is a Personal Access Token.
    """
    if token and token.startswith(PAT_PREFIX):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _PAT_REFUSED)


def get_current_session_user(
    request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Like `get_current_user`, but accepts only an interactive session token, never a Personal Access Token.

    For the endpoints that manage the account's own credentials (password, second factor, access tokens), and
    for leaving an organisation. See `refuse_personal_access_token` for why.

    Args:
        request: The incoming request.
        token: The bearer token from the Authorization header.
        db: An active database session.

    Returns:
        The authenticated, active User.

    Raises:
        HTTPException: 401 as `get_current_user`; 403 when the credential is a Personal Access Token.
    """
    refuse_personal_access_token(token)
    return _resolve_user_from_token(token, db, request)


def get_current_user_or_module_frame(module_key: str):
    """FastAPI dependency factory accepting a normal session/PAT bearer token (resolved as
    `get_current_user` does) or a short-lived Tier B `<ModuleFrame>` JWT
    (`app.security.create_module_frame_token`) scoped to exactly `module_key`.

    Used only by `app.services.rbac`'s module-gating dependencies (`require_org_module_enabled`,
    `require_project_module_enabled`, `require_module_role`). Every other endpoint uses
    `get_current_user`, which rejects a module-frame token (wrong `purpose`, as for a 2FA challenge token),
    so such a token is unusable outside its own module.

    Resolving a module-frame token here confirms only that its `module_key` matches and that it names an
    active user, not that the request's `organization_id`/`project_id` matches the token's scope. The
    calling `rbac.py` dependency checks that through `request.state.module_frame_scope` and
    `rbac._enforce_module_frame_scope`; the two steps stay separate so a bug in one dependency's scope
    check cannot widen scope enforcement for every other module-gated endpoint.

    Args:
        module_key: The module this dependency accepts a module-frame token for; a token for another
            module is rejected.

    Returns:
        A dependency resolving to the authenticated, active `User`.

    Raises:
        HTTPException: 401 for no token, a module-frame token for another module, or an invalid or
            expired token.
    """

    def _dependency(
        request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
    ) -> User:
        if token and not token.startswith(PAT_PREFIX):
            frame_claims = decode_module_frame_token(token)
            if frame_claims is not None:
                if frame_claims.get("module_key") != module_key:
                    raise _UNAUTHORIZED
                user = db.get(User, UUID(frame_claims["user_id"]))
                if user is None or not user.is_active or user.is_archived:
                    raise _UNAUTHORIZED
                request.state.module_frame_scope = {
                    "organization_id": frame_claims.get("organization_id"),
                    "project_id": frame_claims.get("project_id"),
                }
                db.info["module_frame_project_id"] = frame_claims.get("project_id")
                return _require_policies_accepted(user, db, request)
        return _resolve_user_from_token(token, db, request)

    return _dependency


def resolve_user_from_media_token(token: str, db: Session) -> User:
    """Resolves a short-lived media token (`security.create_media_token`) to the active user it names.

    Args:
        token: The token from a `?token=` query parameter.
        db: Active database session.

    Returns:
        The authenticated, active, non-archived user.

    Raises:
        HTTPException: 401 if the token is invalid, expired, not a media token (a session token or a PAT in
            a URL is refused on purpose) or the user's `token_version` has moved on.
    """
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "media":
        raise _UNAUTHORIZED
    user = db.get(User, UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_archived or claims.get("tv", 0) != user.token_version:
        raise _UNAUTHORIZED
    return user


def get_current_user_header_or_query(
    request: Request,
    query_token: str | None = Query(default=None, alias="token"),
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Like `get_current_user`, but also accepts a short-lived media token as a `?token=` query parameter
    when no Authorization header is present.

    Only used for endpoints whose responses are rendered via HTML tags that
    cannot set custom headers (e.g. `<img src>` for avatars/logos/file
    downloads) — everywhere else, the Authorization header path should be
    preferred. The query form accepts only `security.create_media_token` tokens, never a session token or a
    PAT: a URL is logged and remembered, so what it carries must be worthless for anything but loading files.
    """
    if token:
        return _resolve_user_from_token(token, db, request)
    if query_token:
        return resolve_user_from_media_token(query_token, db)
    raise _UNAUTHORIZED


def get_current_user_header_or_query_optional(
    request: Request,
    query_token: str | None = Query(default=None, alias="token"),
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Like `get_current_user_header_or_query`, but returns `None` when no token is presented.

    Used by `routers/files.py::download_file`, which also serves anonymous visitors (for example the
    pre-login page's branding images). A present but invalid or expired token still raises 401, so a
    broken session is never treated as anonymous.
    """
    if token:
        return _resolve_user_from_token(token, db, request)
    if query_token:
        return resolve_user_from_media_token(query_token, db)
    return None


def get_client_ip(request: Request) -> str:
    """Returns the address of the connecting client, as the server itself determined it.

    Uses `request.client.host` only. uvicorn replaces it with the forwarded address when, and only when, the
    peer is listed in `FORWARDED_ALLOW_IPS`, so a caller cannot choose the address by sending an
    `X-Forwarded-For` header of its own. Behind a reverse proxy that is not on that list the proxy's own
    address is returned; `docs/deployment.md` explains the setting.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client address, at most 64 characters (the width of `LoginEvent.ip_address`), or `"unknown"`.
    """
    return (request.client.host if request.client else "unknown")[:64]


def get_request_channel(request: Request) -> str:
    """Identifies the channel a request arrived through: `"mcp"` when it carries the
    `X-Reqtrack-Client: mcp-server` header that `mcp-server/server.py`'s `_call_backend` adds, else `"ui"`.

    The header is a self-declared marker, not authentication or authorisation (docs/decisions.md, "AI
    approval via MCP"): it gates only an `allow_ai_approvals` check that can restrict an action the caller
    could already take, so spoofing it in either direction escalates nothing. It applies that gate to
    MCP-originated calls only and marks the audit event and change note "via MCP", so an AI-made approval
    is distinguishable from a human one.

    Args:
        request: The incoming FastAPI request.

    Returns:
        `"mcp"` or `"ui"`.
    """
    return "mcp" if request.headers.get("x-reqtrack-client") == "mcp-server" else "ui"
