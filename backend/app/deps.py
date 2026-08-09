"""
Module: deps

Shared FastAPI dependencies: current-user resolution from a bearer token
(a session JWT or a Personal Access Token), and a client-IP extractor used
for login auditing (C-A-07).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from app.security import PAT_PREFIX, decode_access_token, hash_pat

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)
settings = get_settings()

_UNAUTHORIZED = HTTPException(
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
        HTTPException: 401 if the token doesn't exist, is revoked, has
            passed its effective expiry, or names an inactive/archived user.

    Side effects:
        Stamps `request.state.pat_allowed_org_ids` with the token's scoped
        org ids, and `request.state.pat_allowed_project_ids` with its
        optional further project restriction (`None` if unset) —
        `services/rbac.py`'s dependencies read both to restrict org/project
        access to that scope, on top of the user's real RBAC roles. Also
        stamps `last_used_at` on the token row, throttled to at most once
        per hour so a busy integration doesn't cause a DB write on every
        single request.
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
    # None (not an empty set) means "no extra project restriction" — an
    # empty list is this token's default, unrestricted-within-its-orgs
    # state, not "scoped to zero projects."
    request.state.pat_allowed_project_ids = (
        {UUID(project_id) for project_id in pat.allowed_project_ids} if pat.allowed_project_ids else None
    )
    return user


def _resolve_user_from_token(token: str | None, db: Session, request: Request) -> User:
    """Decodes and validates a bearer token, returning the active user it names.

    Dispatches to `_resolve_user_from_pat` for Personal Access Tokens
    (recognised by their `rtm_pat_` prefix — see `security.PAT_PREFIX`) and
    otherwise validates it as a session JWT, unchanged from before PATs
    existed. A session JWT never sets `request.state.pat_allowed_org_ids`,
    which is exactly what lets `services/rbac.py` tell "not a PAT, no
    restriction" apart from "a PAT scoped to these orgs."

    Args:
        token: The raw bearer token, or None if the request had none.
        db: Active database session.
        request: The incoming request, used to carry PAT scope forward to
            the RBAC dependencies (see `_resolve_user_from_pat`).

    Returns:
        The authenticated, active, non-archived user.

    Raises:
        HTTPException: 401 if the token is missing, invalid, not an access
            token (e.g. a 2FA challenge token), or names a user who is
            inactive/archived.
    """
    if not token:
        raise _UNAUTHORIZED
    if token.startswith(PAT_PREFIX):
        return _resolve_user_from_pat(token, db, request)
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
    return user


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


def get_current_user_header_or_query(
    request: Request,
    query_token: str | None = Query(default=None, alias="token"),
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Like `get_current_user`, but also accepts the token as a `?token=`
    query parameter when no Authorization header is present.

    Only used for endpoints whose responses are rendered via HTML tags that
    cannot set custom headers (e.g. `<img src>` for avatars/logos/file
    downloads) — everywhere else, the Authorization header path should be
    preferred.
    """
    return _resolve_user_from_token(token or query_token, db, request)


def get_client_ip(request: Request) -> str:
    """Extracts the originating client IP, honouring a proxy-set header.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The client IP address as a string.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
