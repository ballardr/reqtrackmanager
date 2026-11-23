"""
Module: modules.product_feedback.merge

Merging a duplicate request into a canonical one, and reversing it.
`merge_requests` records an `EnhancementRequestMerge` and marks the duplicate
`DUPLICATE`; `unmerge_request` restores its previous status. Nothing is copied:
demand is derived from the active merges, so unmerging ends the row.
- Same tier and owner only; no chains; only an open request can be merged away.
- Nothing commits or checks the role; the caller owns both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.product_feedback.enums import EnhancementRequestStatus
from app.modules.product_feedback.labels import request_status_label
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestMerge
from app.modules.product_feedback.service import apply_new_version, get_current_version

_S = EnhancementRequestStatus

#: Statuses a request can be merged away from.
MERGEABLE_STATUSES = frozenset({_S.NEW, _S.UNDER_REVIEW, _S.ACCEPTED})


def active_merge_of(db: Session, duplicate_id: uuid.UUID) -> EnhancementRequestMerge | None:
    """The active merge that made `duplicate_id` a duplicate, if any."""
    return db.scalar(select(EnhancementRequestMerge).where(
        EnhancementRequestMerge.duplicate_id == duplicate_id, EnhancementRequestMerge.unmerged_at.is_(None),
    ))


def has_active_merge(db: Session, request_id: uuid.UUID) -> bool:
    """Whether `request_id` is in an active merge, as the duplicate or as the canonical."""
    return db.scalar(select(EnhancementRequestMerge.id).where(
        EnhancementRequestMerge.unmerged_at.is_(None),
        (EnhancementRequestMerge.duplicate_id == request_id) | (EnhancementRequestMerge.canonical_id == request_id),
    ).limit(1)) is not None


def merge_requests(
    db: Session, canonical: EnhancementRequest, duplicate: EnhancementRequest, actor: User, note: str = "",
) -> EnhancementRequestMerge:
    """Merges `duplicate` into `canonical`.

    Args:
        db: Active session; the caller has locked both rows, checked the actor may and commits.
        canonical: The request that stays.
        duplicate: The request to mark as a duplicate of it.
        actor: The acting user.
        note: Why they are the same ask; kept on the merge row and in the duplicate's version history.

    Returns:
        The new active merge row (flushed).

    Raises:
        ValueError: If they are the same request, belong to different owners, either is archived, the
            canonical is itself a duplicate, the duplicate already heads a merge, or the duplicate's status
            is not open.
    """
    if canonical.id == duplicate.id:
        raise ValueError("A request cannot be merged into itself.")
    if (canonical.scope, canonical.project_id, canonical.organization_id) != (
        duplicate.scope, duplicate.project_id, duplicate.organization_id,
    ):
        raise ValueError("Only requests of the same project (or the same organisation inbox) can be merged.")
    if canonical.is_archived or duplicate.is_archived:
        raise ValueError("An archived request cannot be merged; unarchive it first.")
    canonical_version = get_current_version(db, canonical.id)
    duplicate_version = get_current_version(db, duplicate.id)
    if canonical_version.status == _S.DUPLICATE:
        raise ValueError(f"{canonical.unique_code} is itself a duplicate; merge into the request it duplicates.")
    if db.scalar(select(EnhancementRequestMerge.id).where(
        EnhancementRequestMerge.canonical_id == duplicate.id, EnhancementRequestMerge.unmerged_at.is_(None),
    ).limit(1)) is not None:
        raise ValueError(f"{duplicate.unique_code} has duplicates merged into it; unmerge them first.")
    if duplicate_version.status not in MERGEABLE_STATUSES:
        raise ValueError(
            f"A request that is {request_status_label(duplicate_version.status.value).lower()} cannot be merged "
            "into another."
        )
    now = datetime.now(UTC)
    note = note.strip()
    merge = EnhancementRequestMerge(
        canonical_id=canonical.id, duplicate_id=duplicate.id, prior_status=duplicate_version.status,
        merged_by=actor.id, merged_at=now, note=note,
    )
    db.add(merge)
    apply_new_version(
        db, duplicate, duplicate_version, actor, changes={"status": _S.DUPLICATE},
        change_note=f"Merged into {canonical.unique_code} as a duplicate." + (f" {note}" if note else ""),
    )
    db.flush()
    return merge


def unmerge_request(db: Session, duplicate: EnhancementRequest, actor: User) -> EnhancementRequestMerge:
    """Reverses the active merge of `duplicate`: it returns to the status it had and stops adding to the
    canonical request's demand.

    Args:
        db: Active session; the caller has locked the row, checked the actor may and commits.
        duplicate: A request that is currently a duplicate.
        actor: The acting user.

    Returns:
        The merge row, now ended.

    Raises:
        ValueError: If the request is not a duplicate by an active merge.
    """
    merge = active_merge_of(db, duplicate.id)
    if merge is None:
        raise ValueError("This request is not merged into another.")
    merge.unmerged_by = actor.id
    merge.unmerged_at = datetime.now(UTC)
    canonical = db.get(EnhancementRequest, merge.canonical_id)
    apply_new_version(
        db, duplicate, get_current_version(db, duplicate.id), actor, changes={"status": merge.prior_status},
        change_note=f"Unmerged from {canonical.unique_code if canonical else 'its canonical request'}.",
    )
    db.flush()
    return merge
