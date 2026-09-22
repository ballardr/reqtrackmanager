"""
Module: modules.compliance.project_router.applicability

A project's own per-requirement compliance rows (Phase 8/9): list/
get, and updating a requirement's applicability or assessment value.
The approval *workflow* actions on the same rows (submit/approve/
reject) are `assessment_workflow.py`'s own sibling bucket, split out
separately since the two are logically distinct concerns (editing an
assessment's value vs. deciding on it).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import NotificationType
from app.models.user import User
from app.modules.compliance.enums import ComplianceApplicability, ComplianceStatus
from app.modules.compliance.project_router._shared import (
    _get_pcr_or_404,
    _get_project_compliance_or_404,
    _notify_approval_invalidated,
    _require_officer,
    _require_view,
)
from app.modules.compliance.schemas import ProjectComplianceApplicabilityUpdate, ProjectComplianceAssessmentUpdate, ProjectComplianceRequirementOut
from app.modules.compliance.service import (
    advance_approval_state_on_assessment,
    build_requirement_out,
    get_effective_compliance_officers,
    invalidate_approval_if_in_flight,
    load_pcrs_and_applicability,
)
from app.services import notifications
from app.services.audit import log_event

router = APIRouter(tags=["compliance-project-applicability"])


@router.get(
    "/project-compliance/{project_compliance_id}/requirements",
    response_model=list[ProjectComplianceRequirementOut],
)
def list_project_compliance_requirements(
    project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every requirement's project-specific assessment for this
    assignment (§8), each with its resolved effective applicability/source
    (§9)."""
    project_compliance = _get_project_compliance_or_404(db, project_id, project_compliance_id)
    pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return [build_requirement_out(pcr, applicability) for pcr in pcrs]


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}",
    response_model=ProjectComplianceRequirementOut,
)
def get_project_compliance_requirement(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single requirement's project-specific assessment."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


@router.patch(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/applicability",
    response_model=ProjectComplianceRequirementOut,
)
def update_requirement_applicability(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ProjectComplianceApplicabilityUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Sets a requirement's own explicit applicability decision (§9).
    `justification` is mandatory (400) when `applicability ==
    NOT_APPLICABLE` — "The Not Applicable state must not simply mean that
    the requirement is ignored... It represents an explicit compliance
    decision" (§9). Records `applicability_set_at`/`applicability_set_by`
    automatically and logs the previous/new value (§16: "who changed
    applicability, previous applicability, new applicability")."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if payload.applicability == ComplianceApplicability.NOT_APPLICABLE and not payload.justification.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A justification is required to mark a requirement Not Applicable.")

    previous_applicability = pcr.explicit_applicability
    pcr.explicit_applicability = payload.applicability
    pcr.justification = payload.justification
    pcr.applicability_set_at = datetime.now(UTC)
    pcr.applicability_set_by = current_user.id

    previous_approval_state = None
    if previous_applicability != payload.applicability:
        previous_approval_state = invalidate_approval_if_in_flight(pcr)
        if previous_approval_state is not None:
            _notify_approval_invalidated(db, project_id, pcr, actor_id=current_user.id)

    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="applicability_changed",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_applicability": previous_applicability.value if previous_applicability else None,
            "new_applicability": payload.applicability.value,
            "justification": payload.justification,
            "previous_approval_state": previous_approval_state.value if previous_approval_state else None,
            "new_approval_state": pcr.approval_state.value if previous_approval_state else None,
        },
    )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


@router.patch(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/assessment",
    response_model=ProjectComplianceRequirementOut,
)
def update_requirement_assessment(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ProjectComplianceAssessmentUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Sets a requirement's project-specific compliance status (§10).
    `justification` is mandatory (400) when `compliance_status ==
    NON_COMPLIANT` (§16: "A rationale should also be required for
    Non-Compliant decisions"). Records `assessed_at`/`assessed_by`
    automatically and logs the previous/new value (§16: "who changed the
    compliance state... previous state... new state")."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if payload.compliance_status == ComplianceStatus.NON_COMPLIANT and not payload.justification.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A justification is required to mark a requirement Non-Compliant."
        )

    previous_status = pcr.compliance_status
    pcr.compliance_status = payload.compliance_status
    pcr.justification = payload.justification
    pcr.notes = payload.notes
    pcr.assessed_at = datetime.now(UTC)
    pcr.assessed_by = current_user.id
    previous_approval_state = advance_approval_state_on_assessment(pcr)
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="assessed",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_status": previous_status.value, "new_status": payload.compliance_status.value,
            "justification": payload.justification,
            "previous_approval_state": previous_approval_state.value,
            "new_approval_state": pcr.approval_state.value,
        },
    )
    if payload.compliance_status == ComplianceStatus.NON_COMPLIANT and previous_status != ComplianceStatus.NON_COMPLIANT:
        for recipient_id in get_effective_compliance_officers(db, project_id):
            recipient = db.get(User, recipient_id)
            if recipient is None:
                continue
            notifications.notify(
                db, recipient, notification_type=NotificationType.COMPLIANCE_REQUIREMENT_NON_COMPLIANT,
                title="Compliance requirement is Non-Compliant",
                body=f"A requirement was assessed Non-Compliant: {payload.justification}",
                project_id=project_id, entity_type="project_compliance_requirement", entity_id=str(pcr.id),
                actor_id=current_user.id,
            )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)
