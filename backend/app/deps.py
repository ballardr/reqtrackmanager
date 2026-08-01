"""
Module: deps

Shared FastAPI dependencies: current-user resolution from a bearer JWT, and
a client-IP extractor used for login auditing (C-A-07).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


def _resolve_user_from_token(token: str | None, db: Session) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized
    claims = decode_access_token(token)
    if not claims or "sub" not in claims or claims.get("purpose") != "access":
        # Rejects 2FA challenge tokens (services/totp.py / routers/auth.py):
        # those only prove password verification succeeded and must not be
        # usable as a real access token before the TOTP step completes.
        raise unauthorized
    user = db.get(User, UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_archived:
        raise unauthorized
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolves the current authenticated user from a bearer JWT.

    Args:
        token: The bearer token extracted from the Authorization header.
        db: An active database session.

    Returns:
        The authenticated, active User.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or the user is
            inactive/archived.
    """
    return _resolve_user_from_token(token, db)


def get_current_user_header_or_query(
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
    return _resolve_user_from_token(token or query_token, db)


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
