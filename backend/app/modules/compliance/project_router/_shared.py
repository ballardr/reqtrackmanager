"""
Module: modules.compliance.project_router._shared

Internal helpers shared by several bucket modules of the compliance
module's project-scoped router package (docs/decisions.md's "Split
compliance/router.py and project_router.py into packages" entry) —
the module-role/module-enabled dependency factories
(`_require_officer`/`_require_view`), the project-membership-or-none
validator, the project-compliance/requirement/evidence ownership-
chain lookups, the required-action-assessment resolver, and the
approval-invalidation notifier. Not a router itself — no `@router`
routes live here. Every name here is used by two or more sibling
bucket modules (verified by call-site grep before this split); a
helper used by only one bucket instead stayed local to that bucket,
per this package's own split convention.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.models import ComplianceEvidence, ComplianceRequiredActionAssessment, ProjectCompliance, ProjectComplianceRequirement
from app.modules.compliance.service import get_effective_compliance_officers
from app.schemas.principal import PrincipalRef
from app.services import notifications
from app.services.principals import validate_principal
from app.services.rbac import require_module_role, require_project_module_enabled

_require_officer = require_module_role("compliance", "compliance_officer")
_require_view = require_project_module_enabled("compliance")


def _validate_project_principal(db: Session, project_id: UUID, ref: PrincipalRef | None, field: str) -> None:
    """400s unless `ref` is `None` or a principal that may be named on a record of this project: a member
    of the project's organisation, a group of that organisation, or a group of this project
    (`services.principals.validate_principal`). Guards every `assignee`/`owner` field this router
    accepts so a scheduled reminder (`scheduler.py`'s daily sweeps) can never be pointed at someone with
    no relationship to this project at all. Deliberately organisation-scoped rather than
    project-role-scoped: an assignee/owner (e.g. a Compliance Manager overseeing several projects) is not
    required to hold a formal `ProjectRole` on this specific project."""
    if ref is None:
        return
    project = db.get(Project, project_id)
    if project is not None:
        validate_principal(db, ref, organization_id=project.organization_id, project_id=project_id, field=field)


def _get_project_compliance_or_404(db: Session, project_id: UUID, project_compliance_id: UUID) -> ProjectCompliance:
    project_compliance = db.get(ProjectCompliance, project_compliance_id)
    if project_compliance is None or project_compliance.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project compliance assignment not found.")
    return project_compliance


def _get_pcr_or_404(
    db: Session, project_id: UUID, project_compliance_id: UUID, pcr_id: UUID
) -> tuple[ProjectCompliance, ProjectComplianceRequirement]:
    project_compliance = _get_project_compliance_or_404(db, project_id, project_compliance_id)
    pcr = db.get(ProjectComplianceRequirement, pcr_id)
    if pcr is None or pcr.project_compliance_id != project_compliance.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project compliance requirement not found.")
    return project_compliance, pcr


def _get_evidence_or_404(db: Session, project_id: UUID, evidence_id: UUID) -> ComplianceEvidence:
    evidence = db.get(ComplianceEvidence, evidence_id)
    if evidence is None or evidence.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence not found.")
    return evidence


def _get_pcr_for_project_or_404(db: Session, project_id: UUID, pcr_id: UUID) -> ProjectComplianceRequirement:
    """Like `_get_pcr_or_404`, but for the Evidence endpoints below, which
    take a bare `project_compliance_requirement_id` (evidence can link to
    a requirement under any of this project's standard assignments, so
    there is no single `project_compliance_id` in these paths to check
    against first)."""
    pcr = db.get(ProjectComplianceRequirement, pcr_id)
    if pcr is not None:
        project_compliance = db.get(ProjectCompliance, pcr.project_compliance_id)
        if project_compliance is not None and project_compliance.project_id == project_id:
            return pcr
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Project compliance requirement not found.")


def _notify_approval_invalidated(
    db: Session, project_id: UUID, pcr: ProjectComplianceRequirement, *, actor_id: UUID
) -> None:
    """Notifies this project's compliance officers that a material change
    invalidated an in-flight or decided approval (§18's "Compliance
    approval becoming invalid due to a change") — shared by `update_
    requirement_applicability` and `_invalidate_approvals_supported_by_
    evidence` below, the two call sites `invalidate_approval_if_in_flight`
    already has. Caller has already confirmed a real transition happened
    (a non-`None` previous state) before calling this."""
    for recipient_id in get_effective_compliance_officers(db, project_id):
        recipient = db.get(User, recipient_id)
        if recipient is None:
            continue
        notifications.notify(
            db, recipient, notification_type=NotificationType.COMPLIANCE_APPROVAL_INVALIDATED,
            title="Compliance approval invalidated",
            body="A material change means this compliance assessment must be re-assessed/re-approved.",
            project_id=project_id, entity_type="project_compliance_requirement", entity_id=str(pcr.id),
            actor_id=actor_id,
        )


def _get_assessment_for_project_or_404(
    db: Session, project_id: UUID, assessment_id: UUID
) -> ComplianceRequiredActionAssessment:
    """The Evidence-endpoint equivalent of `_get_pcr_for_project_or_404`,
    for a bare `required_action_assessment_id`."""
    assessment = db.get(ComplianceRequiredActionAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Required action assessment not found.")
    _get_pcr_for_project_or_404(db, project_id, assessment.project_compliance_requirement_id)
    return assessment
