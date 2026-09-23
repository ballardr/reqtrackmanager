"""
Module: modules.compliance.project_router.reviews

A project's own scheduled compliance reviews (Phase 10, §17/§18):
create/list/get/update/delete/complete, its due-review listing, and
evidence link/unlink. `_get_project_review_or_404` is local to this
file only (verified by call-site grep before this split).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.enums import ComplianceReviewStatus
from app.modules.compliance.models import ComplianceReview, ComplianceReviewEvidenceLink, ProjectCompliance
from app.modules.compliance.project_router._shared import (
    _get_evidence_or_404,
    _get_project_compliance_or_404,
    _require_officer,
    _require_project_member_or_none,
    _require_view,
)
from app.modules.compliance.schemas import (
    ComplianceReviewCompleteRequest,
    ComplianceReviewCreate,
    ComplianceReviewEvidenceLinkCreate,
    ComplianceReviewOut,
    ComplianceReviewUpdate,
)
from app.modules.compliance.service import build_review_out, complete_review, list_reviews_due_for_project
from app.modules.registry import APPROVAL_ACTION_ROUTE_EXTRA
from app.services.audit import log_event

router = APIRouter(tags=["compliance-project-reviews"])


def _get_project_review_or_404(db: Session, project_id: UUID, review_id: UUID) -> ComplianceReview:
    """404s unless `review_id` is a *project*-level review (`project_
    compliance_id` set, not `standard_id`) transitively owned by
    `project_id` — a standard-level review is only ever reachable through
    `router.py`'s org-scoped endpoints, mirroring every other cross-scope
    ownership check on this router."""
    review = db.get(ComplianceReview, review_id)
    if review is None or review.project_compliance_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance review not found.")
    project_compliance = db.get(ProjectCompliance, review.project_compliance_id)
    if project_compliance is None or project_compliance.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance review not found.")
    return review


@router.post(
    "/project-compliance/{project_compliance_id}/reviews", response_model=ComplianceReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_review(
    project_id: UUID, project_compliance_id: UUID, payload: ComplianceReviewCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Schedules a new review of a project's compliance assignment (§17)."""
    project_compliance = _get_project_compliance_or_404(db, project_id, project_compliance_id)
    _require_project_member_or_none(db, project_id, payload.owner_id)
    review = ComplianceReview(
        project_compliance_id=project_compliance.id, frequency_label=payload.frequency_label,
        recurrence_days=payload.recurrence_days, next_due_date=payload.next_due_date, owner_id=payload.owner_id,
        notes=payload.notes, created_by=current_user.id,
    )
    db.add(review)
    db.flush()
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"project_compliance_id": str(project_compliance.id)})
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.get("/project-compliance/{project_compliance_id}/reviews", response_model=list[ComplianceReviewOut])
def list_project_reviews(
    project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every review — `SCHEDULED` and `COMPLETED` — ever scheduled
    against this assignment, in creation order; §17's "Review history" is
    exactly this listing (see `models.py`'s own Phase 10 notes)."""
    project_compliance = _get_project_compliance_or_404(db, project_id, project_compliance_id)
    reviews = db.scalars(
        select(ComplianceReview)
        .where(ComplianceReview.project_compliance_id == project_compliance.id)
        .order_by(ComplianceReview.created_at)
    ).all()
    return [build_review_out(db, review) for review in reviews]


@router.get("/reviews-due", response_model=list[ComplianceReviewOut])
def list_reviews_due(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Unified `DUE`/`OVERDUE` listing (§17/§28's "identify upcoming and
    overdue compliance reviews") across every review relevant to this
    project: its own project-level reviews, plus every review of a
    standard this project is currently (non-archived-ly) assigned to — a
    standard-level review (e.g. "annual audit of this standard itself")
    affects every project assigned to it, so a project's own dashboard
    should surface both. The `compliance_list_reviews_due` MCP tool.
    Delegates to `service.py::list_reviews_due_for_project` (`include_
    upcoming=False`, this endpoint's pre-existing behaviour), shared with
    `router.py`'s Phase 14 org-wide aggregation — moved there in Phase 14;
    behaviour unchanged."""
    reviews = list_reviews_due_for_project(db, project_id=project_id, include_upcoming=False)
    return [build_review_out(db, review) for review in reviews]


@router.get("/reviews/{review_id}", response_model=ComplianceReviewOut)
def get_project_review(
    project_id: UUID, review_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    review = _get_project_review_or_404(db, project_id, review_id)
    return build_review_out(db, review)


@router.patch("/reviews/{review_id}", response_model=ComplianceReviewOut)
def update_project_review(
    project_id: UUID, review_id: UUID, payload: ComplianceReviewUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Edits a still-`SCHEDULED` review's schedule/owner/notes (409 for an
    already-`COMPLETED` one — §17's retained history must not be edited in
    place). Resets `due_reminder_sent_at`/`overdue_notified_at` whenever
    `next_due_date` actually changes, the same reschedule convention
    `update_required_action_assessment` above already established."""
    review = _get_project_review_or_404(db, project_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This review is already completed and cannot be edited.")
    _require_project_member_or_none(db, project_id, payload.owner_id)
    if review.next_due_date != payload.next_due_date:
        review.due_reminder_sent_at = None
        review.overdue_notified_at = None
    review.frequency_label = payload.frequency_label
    review.recurrence_days = payload.recurrence_days
    review.next_due_date = payload.next_due_date
    review.owner_id = payload.owner_id
    review.notes = payload.notes
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_review(
    project_id: UUID, review_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Deletes a still-`SCHEDULED` review scheduled by mistake (409 for an
    already-`COMPLETED` one — §17's retained history must never be
    deleted)."""
    review = _get_project_review_or_404(db, project_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "A completed review is retained history and cannot be deleted.")
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="deleted",
              actor_id=current_user.id, project_id=project_id)
    db.delete(review)
    db.commit()


@router.post(
    "/reviews/{review_id}/complete", response_model=ComplianceReviewOut, openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA,
)
def complete_project_review(
    project_id: UUID, review_id: UUID, payload: ComplianceReviewCompleteRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Completes a `SCHEDULED` review (§17's "Review outcome"), 409 if
    already completed. Schedules the next cycle automatically when this
    review recurs — see `service.py::complete_review`'s own docstring.

    Marked `APPROVAL_ACTION_ROUTE_EXTRA` (2026-09-23 hardening pass):
    recording a review outcome is core's one categorically MCP-excluded
    action (`mcp-server/server.py`'s own instructions: "Voting and
    recording a review outcome remain entirely unavailable through this
    server, in every configuration") — a stricter posture than the
    `require_ai_approvals_enabled` opt-in gate applied to approve/reject/
    complete elsewhere, since a review outcome is a judgment call this
    project treats as needing real human accountability under any
    configuration. This endpoint was declared as a plain MCP write tool
    with no exclusion or gate at all; found and corrected in that pass."""
    review = _get_project_review_or_404(db, project_id, review_id)
    if review.status != ComplianceReviewStatus.SCHEDULED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This review is already completed.")
    next_review = complete_review(db, review, outcome=payload.outcome, notes=payload.notes, actor_id=current_user.id)
    log_event(
        db, entity_type="compliance_review", entity_id=review.id, action="completed",
        actor_id=current_user.id, project_id=project_id,
        detail={"outcome": payload.outcome.value, "next_review_id": str(next_review.id) if next_review else None},
    )
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.post(
    "/reviews/{review_id}/evidence-links", response_model=ComplianceReviewOut, status_code=status.HTTP_201_CREATED
)
def link_review_evidence(
    project_id: UUID, review_id: UUID, payload: ComplianceReviewEvidenceLinkCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Links a piece of this project's own evidence to a review (§17's
    "Notes/evidence associated with the review") — `_get_evidence_or_404`
    already confines `evidence_id` to this same `project_id`, which is what
    enforces "a review's evidence must belong to the same project" (see
    `models.py`'s own docstring)."""
    review = _get_project_review_or_404(db, project_id, review_id)
    evidence = _get_evidence_or_404(db, project_id, payload.evidence_id)
    existing = db.scalar(
        select(ComplianceReviewEvidenceLink).where(
            ComplianceReviewEvidenceLink.review_id == review.id,
            ComplianceReviewEvidenceLink.evidence_id == evidence.id,
        )
    )
    if existing is None:
        db.add(ComplianceReviewEvidenceLink(
            review_id=review.id, evidence_id=evidence.id, linked_by=current_user.id, created_at=datetime.now(UTC)
        ))
        log_event(db, entity_type="compliance_review", entity_id=review.id, action="evidence_linked",
                  actor_id=current_user.id, project_id=project_id, detail={"evidence_id": str(evidence.id)})
    db.commit()
    db.refresh(review)
    return build_review_out(db, review)


@router.delete("/reviews/{review_id}/evidence-links/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_review_evidence(
    project_id: UUID, review_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    review = _get_project_review_or_404(db, project_id, review_id)
    link = db.scalar(
        select(ComplianceReviewEvidenceLink).where(
            ComplianceReviewEvidenceLink.review_id == review.id,
            ComplianceReviewEvidenceLink.evidence_id == evidence_id,
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This evidence is not linked to that review.")
    db.delete(link)
    log_event(db, entity_type="compliance_review", entity_id=review.id, action="evidence_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"evidence_id": str(evidence_id)})
    db.commit()
