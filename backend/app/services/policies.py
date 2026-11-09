"""
Module: services.policies

Policies: written documents published by a server administrator (server policies) or, later, by an
organisation's administrators, read on the Policies page.

Responsibilities:
- Create, edit, publish, unpublish and delete a policy in one scope, audited.
- Keep the two built-in slots (`privacy`, `data`) fixed: a slot cannot be renamed, duplicated or deleted.
- Write an append-only version on every publication and resolve what a reader sees (the current version).
- Serve the unauthenticated read of published server policies, throttled per client address.

Design decisions:
- Scope is enforced here: every lookup takes the owning `organization_id` (NULL for a server policy), so a
  policy of another scope is a 404, not a 403, and its id is not confirmed.
- Editing writes the working copy only; readers see `current_version`, so a text people may already have read
  changes only when it is published again, as a new version with its date.
- Unpublishing hides the policy from readers and keeps every version for audit.
- Audit events carry the key, version, state and text length, never the title or body.
- `effective_from` is a calendar date shown as chosen; `published_at` is a UTC instant; nothing is scheduled.

External dependencies: `services.policy_body`, `services.audit`, `services.rate_limit`.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.policy import PolicyDocument, PolicyDocumentVersion, PolicyState
from app.models.user import User
from app.services.audit import log_event
from app.services.policy_body import plain_text, validate_body
from app.services.rate_limit import RateLimiter

MAX_TITLE_LENGTH = 120
MAX_NOTE_LENGTH = 1_000
#: Most policies one scope can hold, slots included.
MAX_PER_SCOPE = 50
#: Built-in slots in display order, with the fixed title each one carries.
SLOT_TITLES: dict[str, str] = {"privacy": "Privacy policy", "data": "Data policy"}


def get_in_scope(db: Session, policy_id: uuid.UUID, organization_id: uuid.UUID | None, *, lock: bool = False) -> PolicyDocument:
    """Loads a policy of exactly this scope.

    Raises:
        HTTPException: 404 when it does not exist or belongs to another scope.
    """
    stmt = select(PolicyDocument).where(PolicyDocument.id == policy_id)
    if organization_id is None:
        stmt = stmt.where(PolicyDocument.organization_id.is_(None))
    else:
        stmt = stmt.where(PolicyDocument.organization_id == organization_id)
    row = db.scalars(stmt.with_for_update() if lock else stmt).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found.")
    return row


def list_scope(db: Session, organization_id: uuid.UUID | None) -> list[PolicyDocument]:
    """The policies of one scope: slots first in their fixed order, then the others by title."""
    stmt = select(PolicyDocument)
    if organization_id is None:
        stmt = stmt.where(PolicyDocument.organization_id.is_(None))
    else:
        stmt = stmt.where(PolicyDocument.organization_id == organization_id)
    rows = list(db.scalars(stmt))
    slot_order = list(SLOT_TITLES)
    return sorted(rows, key=lambda r: (0, slot_order.index(r.key)) if r.key in SLOT_TITLES else (1, r.title.lower()))


def clean_title(title: str) -> str:
    """A one-line title with surrounding space removed.

    Raises:
        HTTPException: 422 when it is empty or has control characters.
    """
    clean = " ".join(title.split())
    if not clean or any(ord(c) < 32 for c in clean):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A policy needs a title.")
    return clean[:MAX_TITLE_LENGTH]


def _detail(row: PolicyDocument, body: dict[str, Any]) -> dict[str, object]:
    """Fields safe to record: never the title or body."""
    return {
        "key": row.key, "state": row.state.value, "current_version": row.current_version,
        "text_length": len(plain_text(body)),
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
    }


def create(
    db: Session, *, organization_id: uuid.UUID | None, actor: User, key: str | None, title: str, body: object,
    effective_from: date | None, allow_links: bool = True,
) -> PolicyDocument:
    """Creates a draft policy; audited, not committed.

    A slot (`key`) takes its fixed title and is unique in its scope; only a server policy has slots.

    Raises:
        HTTPException: 422 for an unknown slot, invalid title or body; 409 when the slot exists or the scope is full.
    """
    if key is not None and (key not in SLOT_TITLES or organization_id is not None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown policy slot.")
    held = list_scope(db, organization_id)
    if key is not None and any(r.key == key for r in held):
        raise HTTPException(status.HTTP_409_CONFLICT, f"The {SLOT_TITLES[key]} already exists; edit it instead.")
    if len(held) >= MAX_PER_SCOPE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"At most {MAX_PER_SCOPE} policies can be stored; delete one first.")
    clean_body = validate_body(body, allow_links=allow_links)
    row = PolicyDocument(
        organization_id=organization_id, key=key, title=SLOT_TITLES[key] if key else clean_title(title), body=clean_body,
        state=PolicyState.DRAFT, effective_from=effective_from, current_version=0, created_by=actor.id,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # Two requests creating the same slot at once: the unique index lets one through.
        raise HTTPException(status.HTTP_409_CONFLICT, "That policy already exists; edit it instead.") from None
    log_event(
        db, entity_type="policy", entity_id=row.id, action="created", actor_id=actor.id, organization_id=organization_id,
        detail=_detail(row, clean_body),
    )
    return row


def update(
    db: Session, row: PolicyDocument, *, actor: User, title: str, body: object, effective_from: date | None,
    allow_links: bool = True,
) -> PolicyDocument:
    """Replaces the working copy of a policy; readers keep seeing the published version. Audited, not committed.

    Raises:
        HTTPException: 422 for an invalid title or body.
    """
    clean_body = validate_body(body, allow_links=allow_links)
    row.title = SLOT_TITLES[row.key] if row.key in SLOT_TITLES else clean_title(title)
    row.body, row.effective_from = clean_body, effective_from
    db.flush()
    log_event(
        db, entity_type="policy", entity_id=row.id, action="updated", actor_id=actor.id,
        organization_id=row.organization_id, detail=_detail(row, clean_body),
    )
    return row


def publish(db: Session, row: PolicyDocument, *, actor: User, change_note: str) -> PolicyDocumentVersion:
    """Publishes the working copy as the next version; audited, not committed.

    Raises:
        HTTPException: 422 when the body is empty or the note is too long.
    """
    note = change_note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The change note is longer than {MAX_NOTE_LENGTH} characters.")
    if not plain_text(row.body):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Write the policy text before publishing.")
    version = PolicyDocumentVersion(
        policy_id=row.id, version=row.current_version + 1, title=row.title, body=row.body,
        effective_from=row.effective_from, published_at=datetime.now(UTC), published_by=actor.id, change_note=note,
    )
    db.add(version)
    row.current_version = version.version
    row.state = PolicyState.PUBLISHED
    db.flush()
    log_event(
        db, entity_type="policy", entity_id=row.id, action="published", actor_id=actor.id,
        organization_id=row.organization_id, detail=_detail(row, row.body),
    )
    return version


def unpublish(db: Session, row: PolicyDocument, actor: User) -> PolicyDocument:
    """Takes a policy off the readers' page, keeping every version; audited, not committed."""
    row.state = PolicyState.DRAFT
    db.flush()
    log_event(
        db, entity_type="policy", entity_id=row.id, action="unpublished", actor_id=actor.id,
        organization_id=row.organization_id, detail=_detail(row, row.body),
    )
    return row


def delete(db: Session, row: PolicyDocument, actor: User) -> None:
    """Deletes a policy and its versions; audited, not committed.

    Raises:
        HTTPException: 409 for a built-in slot (unpublish it instead).
    """
    if row.key in SLOT_TITLES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The {SLOT_TITLES[row.key]} cannot be deleted; unpublish it instead.")
    log_event(
        db, entity_type="policy", entity_id=row.id, action="deleted", actor_id=actor.id,
        organization_id=row.organization_id, detail=_detail(row, row.body),
    )
    db.delete(row)


def versions(db: Session, row: PolicyDocument) -> list[PolicyDocumentVersion]:
    """Every published version of a policy, newest first."""
    return list(db.scalars(
        select(PolicyDocumentVersion).where(PolicyDocumentVersion.policy_id == row.id).order_by(PolicyDocumentVersion.version.desc())
    ))


def get_version(db: Session, row: PolicyDocument, number: int) -> PolicyDocumentVersion:
    """One published version of a policy.

    Raises:
        HTTPException: 404 when the version does not exist.
    """
    version = db.scalars(select(PolicyDocumentVersion).where(
        PolicyDocumentVersion.policy_id == row.id, PolicyDocumentVersion.version == number,
    )).first()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
    return version


def current_versions(db: Session, rows: list[PolicyDocument]) -> dict[uuid.UUID, PolicyDocumentVersion]:
    """The latest published version of each policy that has one, read in one query."""
    if not rows:
        return {}
    found = db.scalars(select(PolicyDocumentVersion).where(PolicyDocumentVersion.policy_id.in_([r.id for r in rows])))
    latest: dict[uuid.UUID, PolicyDocumentVersion] = {}
    wanted = {r.id: r.current_version for r in rows}
    for v in found:
        if v.version == wanted.get(v.policy_id):
            latest[v.policy_id] = v
    return latest


def has_unpublished_changes(row: PolicyDocument, current: PolicyDocumentVersion | None) -> bool:
    """Whether the working copy differs from the current published version (or nothing is published yet)."""
    if current is None:
        return True
    return (row.title, row.body, row.effective_from) != (current.title, current.body, current.effective_from)


def published_server_policies(db: Session) -> list[tuple[PolicyDocument, PolicyDocumentVersion]]:
    """The published server policies with their current versions, slots first."""
    rows = [r for r in list_scope(db, None) if r.state == PolicyState.PUBLISHED]
    current = current_versions(db, rows)
    return [(r, current[r.id]) for r in rows if r.id in current]


def published_server_policy(db: Session, policy_id: uuid.UUID) -> tuple[PolicyDocument, PolicyDocumentVersion]:
    """One published server policy with its current version.

    Raises:
        HTTPException: 404 for an unknown, unpublished or organisation policy (the same answer for each).
    """
    for row, version in published_server_policies(db):
        if row.id == policy_id:
            return row, version
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found.")


# --- public read throttle -------------------------------------------------------------------------------

_limiters: dict[tuple[int, int], RateLimiter] = {}


def enforce_public_rate_limit(client_ip: str) -> None:
    """Throttles the unauthenticated policy read per client address (in-process, per worker).

    Raises:
        HTTPException: 429 with `Retry-After` when the bucket is empty.
    """
    cfg = get_settings()
    burst, per_minute = cfg.public_announcement_rate_limit_burst, cfg.public_announcement_rate_limit_per_minute
    limiter = _limiters.setdefault((burst, per_minute), RateLimiter(burst, per_minute / 60))
    wait = limiter.acquire(client_ip)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"Too many requests. Wait {seconds} second{'s' if seconds != 1 else ''} and try again.",
            headers={"Retry-After": str(seconds)},
        )
