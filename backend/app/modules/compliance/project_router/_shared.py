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
from app.services import notifications
from app.services.rbac import get_effective_org_roles, require_module_role, require_project_module_enabled

_require_officer = require_module_role("compliance", "compliance_officer")
_require_view = require_project_module_enabled("compliance")


def _require_project_member_or_none(db: Session, project_id: UUID, user_id: UUID | None) -> None:
    """400s unless `user_id` is `None` or an effective member of the
    project's own organisation — guards every `assignee_id`/`owner_id`
    field this router accepts so a scheduled reminder (`scheduler.py`'s
    daily sweeps) can never be pointed at an arbitrary user with no
    relationship to this project at all, mirroring the codebase-wide "the
    user must be a member of this project's organisation first" convention
    (`routers/projects.py::add_member_source`'s identical check). Deliberately
    org-scoped rather than project-role-scoped: an assignee/owner (e.g. a
    Compliance Manager overseeing several projects) is not required to hold
    a formal `ProjectRole` on this specific project."""
    if user_id is None:
        return
    project = db.get(Project, project_id)
    if project is not None and not get_effective_org_roles(db, user_id, project.organization_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assignee/owner must be a member of this project's organisation.")


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
