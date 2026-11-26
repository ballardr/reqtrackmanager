"""
Module: modules.compliance.project_router.assessment_workflow

A project compliance requirement's approval/sign-off workflow
(§12/§16/§27): submit-for-approval, approve, reject, each move checked through the assessment's lifecycle — the latter two
reachable through MCP only when both the project's and its
organisation's `allow_ai_approvals` are enabled (see each function's
own docstring) — plus its audit history and linked-evidence listing.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.audit import AuditEvent
from app.models.notification import NotificationType
from app.models.user import User
from app.modules.compliance.approval import require_assessment_approver
from app.modules.compliance.enums import ComplianceApprovalState
from app.modules.compliance.models import (
    ARTEFACT_TYPE_EVIDENCE,
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT,
    ComplianceEvidence,
    ProjectComplianceRequirement,
)
from app.modules.compliance.project_router._shared import _get_pcr_or_404, _require_officer, _require_view
from app.modules.compliance.schemas import ComplianceApprovalDecisionRequest, ComplianceEvidenceOut, ProjectComplianceRequirementOut
from app.modules.compliance.service import (
    approval_moves,
    build_evidence_out,
    build_requirement_out,
    get_effective_compliance_officers,
    load_pcrs_and_applicability,
)
from app.schemas.audit import AuditEventOut
from app.services import approval_separation, notifications, relationships
from app.services.audit import log_event
from app.services.lifecycles import check_move
from app.services.lookups import project_or_404
from app.services.rbac import require_ai_approvals_enabled

router = APIRouter(tags=["compliance-project-assessment-workflow"])


def _check_approval_move(db: Session, project_id: UUID, pcr: ProjectComplianceRequirement, target: ComplianceApprovalState) -> None:
    """Enforces the move of an assessment's approval state through its lifecycle (`modules.compliance.lifecycles`), which
    steps over a state the project turned off.

    Raises:
        HTTPException: 409 naming the states the assessment may move to when the move is not legal here.
    """
    try:
        check_move(
            db, project_id, ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, pcr.approval_state.value, target.value,
            record_id=pcr.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/submit-for-approval",
    response_model=ProjectComplianceRequirementOut,
)
def submit_requirement_for_approval(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Requests formal approval for this requirement's current assessment (§12): `ASSESSED` -> `PENDING_APPROVAL`; 409
    from any other `approval_state` or when the project turned the step off, enforcing §12's ordering through the
    assessment's lifecycle. It only queues a decision for a person to make, so it is
    not `APPROVAL_ACTION_ROUTE_EXTRA` and needs no `allow_ai_approvals` gate, as core's `submit_change_request`; it is a
    normal MCP write tool gated by the caller's `compliance_officer` or `PROJECT_MANAGER` role."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    previous = pcr.approval_state.value
    _check_approval_move(db, project_id, pcr, ComplianceApprovalState.PENDING_APPROVAL)
    pcr.approval_state = ComplianceApprovalState.PENDING_APPROVAL
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="submitted_for_approval",
        actor_id=current_user.id, project_id=project_id,
        detail={"previous_approval_state": previous, "new_approval_state": "pending_approval"},
    )
    for recipient_id in get_effective_compliance_officers(db, project_id):
        recipient = db.get(User, recipient_id)
        if recipient is None:
            continue
        notifications.notify(
            db, recipient, notification_type=NotificationType.COMPLIANCE_APPROVAL_REQUESTED,
            title="Compliance approval requested",
            body="A compliance assessment is awaiting approval/sign-off.",
            project_id=project_id, entity_type="project_compliance_requirement", entity_id=str(pcr.id),
            actor_id=current_user.id,
        )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability, approval_moves(db, project_id)(pcr))


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/approve",
    response_model=ProjectComplianceRequirementOut,
)
def approve_requirement(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ComplianceApprovalDecisionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves and signs off this requirement's assessment (§12): `PENDING_APPROVAL` -> `APPROVED` (from
    `ASSESSED` where the project turned the submit step off). Gated
    through `services.approval_policy` (`compliance.approval.require_assessment_approver`): a `compliance_officer` or
    `PROJECT_MANAGER` as for every mutating endpoint on this router (§11 and §26 name no separate approver role), plus a
    role the project's approval policy names or a holder of the type's `approve_baseline` permission. The person who
    assessed it may approve it unless approval separation requires another approver. Reached through the MCP server
    (`channel == "mcp"`) it also requires the project and its organisation to have enabled AI approval
    (`require_ai_approvals_enabled`), as core's `requirements.approve_requirement` and
    `change_requests.decide_change_request` do; a UI or API call is unaffected."""
    require_assessment_approver(db, current_user, project_id)
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project_or_404(db, project_id))
    previous = pcr.approval_state.value
    _check_approval_move(db, project_id, pcr, ComplianceApprovalState.APPROVED)
    if pcr.assessed_by is not None:
        approval_separation.enforce_approval(
            db, user=current_user, artefact_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, record_id=pcr.id,
            creator_id=pcr.assessed_by, organization_id=project_or_404(db, project_id).organization_id,
            project_id=project_id, comment=payload.decision_note,
        )
    pcr.approval_state = ComplianceApprovalState.APPROVED
    pcr.approval_decided_at = datetime.now(UTC)
    pcr.approval_decided_by = current_user.id
    pcr.decision_note = payload.decision_note
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="approved",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_approval_state": previous, "new_approval_state": "approved",
            "decision_note": payload.decision_note,
            **({"via": "mcp"} if channel == "mcp" else {}),
        },
    )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability, approval_moves(db, project_id)(pcr))


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/reject",
    response_model=ProjectComplianceRequirementOut,
)
def reject_requirement(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ComplianceApprovalDecisionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally rejects this requirement's assessment (§12): `PENDING_APPROVAL` -> `REJECTED` (from `ASSESSED` where the
    project turned the submit step off). `decision_note` is
    mandatory (400), as for Non-Compliant and Not Applicable decisions (§16), so a rejection always says why. Gated like
    `approve_requirement`, including the MCP gate; approval separation does not apply to a rejection."""
    require_assessment_approver(db, current_user, project_id)
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project_or_404(db, project_id))
    previous = pcr.approval_state.value
    _check_approval_move(db, project_id, pcr, ComplianceApprovalState.REJECTED)
    if not payload.decision_note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A decision note is required to reject an approval.")
    pcr.approval_state = ComplianceApprovalState.REJECTED
    pcr.approval_decided_at = datetime.now(UTC)
    pcr.approval_decided_by = current_user.id
    pcr.decision_note = payload.decision_note
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="rejected",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_approval_state": previous, "new_approval_state": "rejected",
            "decision_note": payload.decision_note,
            **({"via": "mcp"} if channel == "mcp" else {}),
        },
    )
    if pcr.assessed_by is not None:
        assessor = db.get(User, pcr.assessed_by)
        if assessor is not None:
            notifications.notify(
                db, assessor, notification_type=NotificationType.COMPLIANCE_ASSESSMENT_REJECTED,
                title="Compliance assessment rejected",
                body=payload.decision_note, project_id=project_id,
                entity_type="project_compliance_requirement", entity_id=str(pcr.id), actor_id=current_user.id,
            )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability, approval_moves(db, project_id)(pcr))


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/history",
    response_model=list[AuditEventOut],
)
def get_requirement_history(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This requirement's own compliance history (§8's "Assessment
    history", §11's "View compliance history", §16's "sufficient history
    to determine how a project reached its current compliance state") —
    every `project_compliance_requirement`-entity audit event logged
    against this row, oldest first."""
    _project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "project_compliance_requirement", AuditEvent.entity_id == str(pcr.id))
        .order_by(AuditEvent.created_at)
    ).all()


@router.get(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/evidence",
    response_model=list[ComplianceEvidenceOut],
)
def list_requirement_evidence(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Evidence linked to this requirement's own assessment (§13), viewed
    from the requirement side. The canonical evidence CRUD lives at the
    project-level `/evidence` resource below, since a single piece of
    evidence may support requirements across more than one of this
    project's standard assignments (§13's "multiple compliance
    requirements and/or standards") — this is a read-only, filtered view
    onto that same data."""
    _project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    links = relationships.get_links_to(db, ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, pcr.id)
    evidence_ids = [link.source_id for link in links if link.source_type == ARTEFACT_TYPE_EVIDENCE]
    if not evidence_ids:
        return []
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(evidence_ids))).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]
