"""
Module: modules.compliance.project_router.required_action_assessments

A project compliance requirement's required-action assessments (Phase
8): list/get/update, complete/uncomplete, and linked-evidence listing.
`_get_required_action_assessment_or_404` is local to this file only
(verified by call-site grep before this split).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.models import (
    ARTEFACT_TYPE_EVIDENCE,
    ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT,
    ComplianceEvidence,
    ComplianceRequiredActionAssessment,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.project_router._shared import _get_pcr_or_404, _require_officer, _require_project_member_or_none, _require_view
from app.modules.compliance.schemas import ComplianceEvidenceOut, ComplianceRequiredActionAssessmentOut, ComplianceRequiredActionAssessmentUpdate
from app.modules.compliance.service import build_evidence_out
from app.services import relationships
from app.services.audit import log_event

router = APIRouter(tags=["compliance-project-required-action-assessments"])


def _get_required_action_assessment_or_404(
    db: Session, project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID
) -> tuple[ProjectCompliance, ProjectComplianceRequirement, ComplianceRequiredActionAssessment]:
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    assessment = db.get(ComplianceRequiredActionAssessment, assessment_id)
    if assessment is None or assessment.project_compliance_requirement_id != pcr.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Required action assessment not found.")
    return project_compliance, pcr, assessment


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments",
    response_model=list[ComplianceRequiredActionAssessmentOut],
)
def list_required_action_assessments(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this requirement's required-action assessments (§6/§25)."""
    _project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    return db.scalars(
        select(ComplianceRequiredActionAssessment).where(
            ComplianceRequiredActionAssessment.project_compliance_requirement_id == pcr.id
        )
    ).all()


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments/{assessment_id}",
    response_model=ComplianceRequiredActionAssessmentOut,
)
def get_required_action_assessment(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single required action assessment."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
    return assessment


@router.patch(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments/{assessment_id}",
    response_model=ComplianceRequiredActionAssessmentOut,
)
def update_required_action_assessment(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID,
    payload: ComplianceRequiredActionAssessmentUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Updates a required action assessment's assignee/due date/notes
    (§6's "Assignee," "Due date"). Completion is a separate action
    endpoint below, mirroring `Requirement`'s own completion-overlay
    shape — never set here. Resetting `due_reminder_sent_at`/`overdue_
    notified_at` whenever `due_date` actually changes (Phase 10, §18) gives
    a rescheduled due date its own fresh reminder cycle rather than
    silently inheriting the old date's "already reminded" state."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
    _require_project_member_or_none(db, project_id, payload.assignee_id)
    if assessment.due_date != payload.due_date:
        assessment.due_reminder_sent_at = None
        assessment.overdue_notified_at = None
    assessment.assignee_id = payload.assignee_id
    assessment.due_date = payload.due_date
    assessment.notes = payload.notes
    log_event(db, entity_type="compliance_required_action_assessment", entity_id=assessment.id, action="updated",
              actor_id=current_user.id, project_id=project_id,
              detail={"assignee_id": str(payload.assignee_id) if payload.assignee_id else None})
    db.commit()
    db.refresh(assessment)
    return assessment


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments/"
    "{assessment_id}/complete",
    response_model=ComplianceRequiredActionAssessmentOut,
)
def complete_required_action_assessment(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Marks a required action assessment completed — mirrors
    `complete_requirement`'s own shape (`is_completed`/`completed_at`/
    `completed_by`, 409 if already completed)."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
    if assessment.is_completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This required action is already marked completed.")
    assessment.is_completed = True
    assessment.completed_at = datetime.now(UTC)
    assessment.completed_by = current_user.id
    log_event(db, entity_type="compliance_required_action_assessment", entity_id=assessment.id, action="completed",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments/"
    "{assessment_id}/uncomplete",
    response_model=ComplianceRequiredActionAssessmentOut,
)
def uncomplete_required_action_assessment(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Reverts a required action assessment's completion, to correct a
    mistake — mirrors `uncomplete_requirement`'s own shape."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
    if not assessment.is_completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This required action is not marked completed.")
    assessment.is_completed = False
    assessment.completed_at = None
    assessment.completed_by = None
    log_event(db, entity_type="compliance_required_action_assessment", entity_id=assessment.id, action="uncompleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/required-action-assessments/"
    "{assessment_id}/evidence",
    response_model=list[ComplianceEvidenceOut],
)
def list_required_action_assessment_evidence(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Evidence linked to this required action's own assessment (§6/§13),
    viewed from the assessment side — the required-action equivalent of
    `list_requirement_evidence` above; see that endpoint's own docstring
    for why the canonical evidence CRUD lives elsewhere."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
    links = relationships.get_links_to(db, ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, assessment.id)
    evidence_ids = [link.source_id for link in links if link.source_type == ARTEFACT_TYPE_EVIDENCE]
    if not evidence_ids:
        return []
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(evidence_ids))).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]
