"""
Module: routers.search

The global search endpoints.

- `POST /api/v1/search`: find records by code, title, tags and chosen fields across one project,
  every project the caller can open, or a module-defined scope.
- `GET /api/v1/search/fields`: the fields the caller can choose to match (for the field picker and
  the Preferences search section). Returns labels only, so it discloses nothing about records.

Access: any signed-in user. What a search covers is decided per project and record type by
`services.search`; nothing is returned the caller could not open.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.search import (
    SearchFieldOut,
    SearchHitOut,
    SearchNamedOut,
    SearchOrganizationOut,
    SearchRequestIn,
    SearchResultOut,
    SearchSnippetOut,
    SearchTypeCountOut,
)
from app.services.rate_limit import RateLimiter
from app.services.search import COMMENTS_FIELD, SearchParams, SearchTimeout, available_fields, run_search

router = APIRouter(prefix="/api/v1/search", tags=["search"])

_limiters: dict[tuple[int, int], RateLimiter] = {}


def _enforce_rate_limit(user: User) -> None:
    """Spends one of the caller's search tokens (per user, per worker process).

    Raises:
        HTTPException: 429 with `Retry-After` when the caller has searched too fast.
    """
    settings = get_settings()
    key = (settings.search_rate_limit_burst, settings.search_rate_limit_per_minute)
    limiter = _limiters.setdefault(key, RateLimiter(key[0], key[1] / 60))
    wait = limiter.acquire(user.id)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"You are searching too fast. Wait {seconds} second{'s' if seconds != 1 else ''} and try again.",
            headers={"Retry-After": str(seconds)},
        )


@router.post("", response_model=SearchResultOut)
def search(body: SearchRequestIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SearchResultOut:
    """Runs a search for the caller.

    The text is in the body so it never reaches an access log, and the application never logs it
    either (only the scope, fields, match mode, result count and duration).

    Raises:
        HTTPException: 404 the scope or project is not found or not allowed; 408 the search took too
            long; 422 the text is too short or long, or the page is past the depth limit; 429 the caller
            has searched too fast (`Retry-After` says how long to wait).
    """
    _enforce_rate_limit(current_user)
    params = SearchParams(**body.model_dump())
    try:
        result = run_search(db, current_user, params)
    except SearchTimeout:
        raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, "The search took too long. Narrow the search and try again.") from None
    return SearchResultOut(
        hits=[
            SearchHitOut(
                **{k: v for k, v in vars(h).items() if k not in ("snippet", "tier")},
                snippet=SearchSnippetOut(**vars(h.snippet)) if h.snippet else None,
            )
            for h in result.hits
        ],
        total=result.total,
        total_capped=result.total_capped,
        type_counts=[SearchTypeCountOut(**vars(c)) for c in result.type_counts],
        fields_used=result.fields_used,
        not_searched=[SearchNamedOut(key=k, label=label) for k, label in result.not_searched],
        statuses=[SearchNamedOut(key=k, label=label) for k, label in result.statuses],
        organizations=[SearchOrganizationOut(id=i, name=n, code=c) for i, n, c in result.organizations],
        projects_truncated=result.projects_truncated,
    )


@router.get("/fields", response_model=list[SearchFieldOut])
def list_search_fields(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SearchFieldOut]:
    """The fields the caller can choose to match, merged across the record types they can view: ID,
    Title and Tags first, then the type-specific ones by label, each with the types that carry it.

    Counts against the same rate limit as a search (it authorises every project the same way)."""
    _enforce_rate_limit(current_user)
    return [
        SearchFieldOut(key=k, label=label, types=types, default_allowed=k != COMMENTS_FIELD)
        for k, label, types in available_fields(db, current_user)
    ]
