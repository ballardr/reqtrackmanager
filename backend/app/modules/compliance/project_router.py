"""
Module: modules.compliance.project_router

The Compliance Module's Phase 7 project-scoped endpoints
(docs/compliance-module-plan.md Phase 7; docs/Compliance_Module_
Requirements.md §7-§11, §16, §20, §21, §26) — day-to-day compliance
assessment for one specific project: viewing assigned standards and their
computed §20 overall status, changing a requirement's applicability or
compliance status (with §9/§16's mandatory-justification rules), managing
required action assessments, and viewing a requirement's own assessment
history.

Mounted at `/api/v1/projects/{project_id}/modules/compliance` — a genuinely
separate router from `router.py`'s org-scoped `/api/v1/orgs/
{organization_id}/modules/compliance`, registered as this module's
`get_project_router()` (`app.modules.registry.ModuleDefinition`, a Phase 7
addition to the registry — see that module's own docstring). This split
exists because Phase 4's MCP tool scoping rule requires `compliance_get_
project_status`/`compliance_list_non_compliant_requirements` to declare
`project_id` as their *only* path parameter (mirroring hand-written tools
like `get_project(project_id)`), which is impossible for a route that also
carries an `{organization_id}` placeholder — seeing this doc, plus §7's
"assigning a standard is a Compliance Manager decision" (`router.py`'s own
docstring), together explain why *assignment* lives on the org router while
*assessment* lives here.

Responsibilities:
- Every mutating endpoint (applicability, assessment, required-action
  assessment updates/completion) is gated by `require_module_role
  ("compliance", "compliance_officer")`, which (Phase 2's own composition)
  also passes for `is_server_admin` and `ProjectRole.PROJECT_MANAGER` on
  this project — matching §11/§26's "Project Managers and assigned
  Compliance Officers may... Other users should have read-only access."
- Every read endpoint is gated by the weaker `require_project_module_
  enabled("compliance")` — any project member may view (§26: "Other
  Project Users: Read access according to existing project permissions").
- §9's mandatory-justification rule (Not Applicable) and §16's (Non-
  Compliant) are enforced here, not in the schema layer — see
  `update_requirement_applicability`/`update_requirement_assessment`.
- Applicability resolution (§9's hierarchical inheritance/override) and
  the §20 overall-status calculation are never reimplemented here — every
  endpoint that needs either calls into `service.py`.
- Every mutation logged via `services.audit.log_event`, before the single
  `db.commit()` each endpoint makes.
- Verifies, on every endpoint naming a `project_compliance_id`/
  `project_compliance_requirement_id`/required-action-assessment id in the
  path, that the row actually belongs to this `project_id` (transitively) —
  404, not 403, on a mismatch, mirroring `router.py`'s own established
  cross-scope-isolation convention.

External dependencies: `app.services.rbac` (module-role/module-enabled
gating), `app.services.audit` (mutation logging), `app.modules.compliance.
service` (applicability resolution, §20 status calculation) — reused, not
reimplemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditEvent
from app.models.user import User
from app.modules.compliance.enums import ComplianceApplicability, ComplianceStatus
from app.modules.compliance.models import (
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.schemas import (
    ComplianceRequiredActionAssessmentOut,
    ComplianceRequiredActionAssessmentUpdate,
    NonCompliantRequirementOut,
    ProjectComplianceApplicabilityUpdate,
    ProjectComplianceAssessmentUpdate,
    ProjectComplianceOut,
    ProjectComplianceRequirementOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import build_requirement_out, build_status_out, load_pcrs_and_applicability
from app.schemas.audit import AuditEventOut
from app.services.audit import log_event
from app.services.rbac import require_module_role, require_project_module_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/compliance", tags=["compliance"])

# Same "factory called once, at router-definition time" convention as
# `router.py` — see that file's own comment.
_require_officer = require_module_role("compliance", "compliance_officer")
_require_view = require_project_module_enabled("compliance")


# --- Cross-scope ownership-chain lookups (404, not 403, on a mismatch) ---------


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


def _get_required_action_assessment_or_404(
    db: Session, project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, assessment_id: UUID
) -> tuple[ProjectCompliance, ProjectComplianceRequirement, ComplianceRequiredActionAssessment]:
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    assessment = db.get(ComplianceRequiredActionAssessment, assessment_id)
    if assessment is None or assessment.project_compliance_requirement_id != pcr.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Required action assessment not found.")
    return project_compliance, pcr, assessment


# --- Project compliance assignments (read-only here; created on the org router) -


@router.get("/project-compliance", response_model=list[ProjectComplianceOut])
def list_project_compliance(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every standard assigned to this project (§21's "All compliance
    standards assigned to the project"), including archived ones — a
    caller wanting only active assignments can filter client-side; unlike
    Phase 6's standards listing, this project-scoped list is small enough
    that a query flag isn't worth adding yet."""
    return db.scalars(
        select(ProjectCompliance).where(ProjectCompliance.project_id == project_id)
    ).all()


@router.get("/project-compliance/{project_compliance_id}", response_model=ProjectComplianceOut)
def get_project_compliance(
    project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single assignment."""
    return _get_project_compliance_or_404(db, project_id, project_compliance_id)


@router.get("/status", response_model=list[ProjectComplianceStatusOut])
def get_project_status(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """§20's overall status summary, one entry per active (non-archived)
    standard assigned to this project — the `compliance_get_project_status`
    MCP tool (Phase 4/6's module.py). A project may have several standards
    assigned at once (§7's own worked example), so this returns a list
    rather than inventing a single cross-standard aggregate nothing in the
    requirements asks for."""
    assignments = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.is_archived.is_(False)
        )
    ).all()
    return [build_status_out(db, pc) for pc in assignments]


@router.get("/non-compliant-requirements", response_model=list[NonCompliantRequirementOut])
def list_non_compliant_requirements(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every applicable, Non-Compliant requirement across this project's
    active standard assignments (§20/§21's "Non-Compliant requirements" as
    its own drillable list) — the `compliance_list_non_compliant_
    requirements` MCP tool."""
    assignments = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.is_archived.is_(False)
        )
    ).all()

    results: list[NonCompliantRequirementOut] = []
    for project_compliance in assignments:
        version = db.get(ComplianceStandardVersion, project_compliance.standard_version_id)
        standard = db.get(ComplianceStandard, version.standard_id)
        pcrs, applicability = load_pcrs_and_applicability(
            db, project_compliance_id=project_compliance.id, standard_version_id=version.id
        )
        requirements_by_id = {
            r.id: r
            for r in db.scalars(
                select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
            ).all()
        }
        for pcr in pcrs:
            effective, _source = applicability[pcr.requirement_id]
            if effective != ComplianceApplicability.APPLICABLE or pcr.compliance_status != ComplianceStatus.NON_COMPLIANT:
                continue
            requirement = requirements_by_id[pcr.requirement_id]
            results.append(
                NonCompliantRequirementOut(
                    project_compliance_id=project_compliance.id,
                    standard_reference=standard.reference,
                    standard_name=standard.name,
                    version_label=version.version_label,
                    project_compliance_requirement_id=pcr.id,
                    requirement_id=requirement.id,
                    requirement_reference=requirement.reference,
                    requirement_name=requirement.name,
                    justification=pcr.justification,
                    notes=pcr.notes,
                    assessed_at=pcr.assessed_at,
                    assessed_by=pcr.assessed_by,
                )
            )
    return results


# --- Per-requirement assessment -------------------------------------------------


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
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="applicability_changed",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_applicability": previous_applicability.value if previous_applicability else None,
            "new_applicability": payload.applicability.value,
            "justification": payload.justification,
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
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="assessed",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_status": previous_status.value, "new_status": payload.compliance_status.value,
            "justification": payload.justification,
        },
    )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


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


# --- Required action assessments -------------------------------------------------


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
    shape — never set here."""
    _pc, _pcr, assessment = _get_required_action_assessment_or_404(
        db, project_id, project_compliance_id, pcr_id, assessment_id
    )
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
