"""
Module: modules.compliance.router.standard_reviews

A compliance standard's own scheduled reviews (Phase 10, §17/§18):
create/list/get/update/delete/complete.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.enums import ComplianceReviewStatus
from app.modules.compliance.models import ComplianceReview
from app.modules.compliance.router._shared import _get_standard_or_404, _require_manage, _require_view
from app.modules.compliance.schemas import ComplianceReviewCompleteRequest, ComplianceReviewCreate, ComplianceReviewOut, ComplianceReviewUpdate
from app.modules.compliance.service import build_review_out, complete_review
from app.services.audit import log_event
from app.services.rbac import get_effective_org_roles

router = APIRouter(tags=["compliance-org-standard-reviews"])


def _require_org_member_or_none(db: Session, organization_id: UUID, user_id: UUID | None) -> None:
    """400s unless `user_id` is `None` or an effective member of
    `organization_id` — org-scoped sibling of `project_router.py`'s
    `_require_project_member_or_none`; see that function's own docstring
    for why this guards every review `owner_id`."""
    if user_id is None:
        return
    if not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "owner must be a member of this organisation.")


def _get_standard_review_or_404(db: Session, organization_id: UUID, standard_id: UUID, review_id: UUID) -> ComplianceReview:
    """404s unless `review_id` is a *standard*-level review (`standard_id`
    set, not `project_compliance_id`) owned by `standard_id`/`organization_id`
    — a project-level review is only ever reachable through `project_
    router.py`'s project-scoped endpoints."""
    _get_standard_or_404(db, organization_id, standard_id)
    review = db.get(ComplianceReview, review_id)
    if review is None or review.standard_id != standard_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance review not found.")
    return review


@router.post(
    "/standards/{standard_id}/reviews", response_model=ComplianceReviewOut, status_code=status.HTTP_201_CREATED
)
def create_standard_review(
    organization_id: UUID, standard_id: UUID, payload: ComplianceReviewCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Schedules a new review of a compliance standard itself (§17) — e.g.
    "Annual audit of this standard.\""""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    _require_org_member_or_none(db, organization_id, payload.owner_id)
    review = ComplianceReview(
        standard_id=standard.id, frequency_label=payload.frequency_label, recurrence_days=payload.recurrence_days,
        next_due_date=payload.next_due_date, owner_id=payload.owner_id, notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(review)
    db.flush()
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"standard_id": str(standard.id)})
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.get("/standards/{standard_id}/reviews", response_model=list[ComplianceReviewOut])
def list_standard_reviews(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every review — `SCHEDULED` and `COMPLETED` — ever scheduled
    against this standard, in creation order (§17's "Review history")."""
    _get_standard_or_404(db, organization_id, standard_id)
    reviews = db.scalars(
        select(ComplianceReview).where(ComplianceReview.standard_id == standard_id).order_by(ComplianceReview.created_at)
    ).all()
    return [build_review_out(db, review) for review in reviews]


@router.get("/standards/{standard_id}/reviews/{review_id}", response_model=ComplianceReviewOut)
def get_standard_review(
    organization_id: UUID, standard_id: UUID, review_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    review = _get_standard_review_or_404(db, organization_id, standard_id, review_id)
    return build_review_out(db, review)


@router.patch("/standards/{standard_id}/reviews/{review_id}", response_model=ComplianceReviewOut)
def update_standard_review(
    organization_id: UUID, standard_id: UUID, review_id: UUID, payload: ComplianceReviewUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Mirrors `project_router.py::update_project_review`'s exact shape,
    for a standard-level review."""
    review = _get_standard_review_or_404(db, organization_id, standard_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This review is already completed and cannot be edited.")
    _require_org_member_or_none(db, organization_id, payload.owner_id)
    if review.next_due_date != payload.next_due_date:
        review.due_reminder_sent_at = None
        review.overdue_notified_at = None
    review.frequency_label = payload.frequency_label
    review.recurrence_days = payload.recurrence_days
    review.next_due_date = payload.next_due_date
    review.owner_id = payload.owner_id
    review.notes = payload.notes
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.delete("/standards/{standard_id}/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_standard_review(
    organization_id: UUID, standard_id: UUID, review_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    review = _get_standard_review_or_404(db, organization_id, standard_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "A completed review is retained history and cannot be deleted.")
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.delete(review)
    db.commit()


@router.post("/standards/{standard_id}/reviews/{review_id}/complete", response_model=ComplianceReviewOut)
def complete_standard_review(
    organization_id: UUID, standard_id: UUID, review_id: UUID, payload: ComplianceReviewCompleteRequest,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    review = _get_standard_review_or_404(db, organization_id, standard_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This review is already completed.")
    next_review = complete_review(db, review, outcome=payload.outcome, notes=payload.notes, actor_id=current_user.id)
    log_event(
        db, entity_type="compliance_review", entity_id=review.id, action="completed",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"outcome": payload.outcome.value, "next_review_id": str(next_review.id) if next_review else None},
    )
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)
