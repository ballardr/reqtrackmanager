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

Phase 8 (Evidence, §13-§15) adds this module's evidence CRUD, revalidation
history, requirement/required-action multi-linkage, and file attachments
(reusing `services.files.upload_file` per §13's own "reuse ReqTrackManager's
existing attachment/file mechanisms") to this same router, at the bottom of
this file — evidence is project-scoped (like everything else here), not
nested under one specific `ProjectCompliance` assignment, since a single
piece of evidence may support requirements across more than one of a
project's standard assignments at once.

Phase 9 (Approval/Sign-off, §12, §16, §27) adds the `submit-for-approval`/
`approve`/`reject` state-machine actions and the `pending-approvals`
cross-assignment listing to the per-requirement assessment section below.
`approve`/`reject` are marked with `app.modules.registry.
APPROVAL_ACTION_ROUTE_EXTRA` (`openapi_extra`) — Phase 4's manifest-builder
exclusion reads this directly off the route, so these two can never be
exposed as an MCP tool regardless of what a future session's `module.py`
might declare; `submit-for-approval` is marked the same way as belt-and-
braces, even though it only queues a decision rather than making one, since
§11 describes the whole flow ("Request/perform assessment... Approve/sign
off compliance") as one accountable-human action set. No new MCP tool is
declared for any of the three — only the read-only `pending-approvals`
listing (`compliance_list_pending_approvals`, `module.py`) is, mirroring
the existing `compliance_get_project_status`/`list_non_compliant_
requirements` read-only shape. `update_requirement_assessment` and
`update_requirement_applicability` (Phase 7) are extended to trigger the
two automatic transitions `service.py`'s `advance_approval_state_on_
assessment`/`invalidate_approval_if_in_flight` define; `archive_evidence`/
`revalidate_evidence` (Phase 8) are extended to invalidate any in-flight or
decided approval the changed evidence supports, via `service.py`'s `find_
pcrs_linked_to_evidence`.

Responsibilities:
- Every mutating endpoint (applicability, assessment, required-action
  assessment updates/completion, and Phase 8's evidence CRUD/linkage/file
  endpoints) is gated by `require_module_role("compliance",
  "compliance_officer")`, which (Phase 2's own composition) also passes
  for `is_server_admin` and `ProjectRole.PROJECT_MANAGER` on this project —
  matching §11/§26's "Project Managers and assigned Compliance Officers
  may... Other users should have read-only access."
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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceApplicability, ComplianceApprovalState, ComplianceStatus
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceEvidenceActionLink,
    ComplianceEvidenceFile,
    ComplianceEvidenceRequirementLink,
    ComplianceEvidenceRevalidation,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.schemas import (
    ComplianceApprovalDecisionRequest,
    ComplianceEvidenceActionLinkCreate,
    ComplianceEvidenceCreate,
    ComplianceEvidenceOut,
    ComplianceEvidenceRequirementLinkCreate,
    ComplianceEvidenceRevalidateRequest,
    ComplianceEvidenceRevalidationOut,
    ComplianceEvidenceUpdate,
    ComplianceRequiredActionAssessmentOut,
    ComplianceRequiredActionAssessmentUpdate,
    NonCompliantRequirementOut,
    PendingApprovalOut,
    ProjectComplianceApplicabilityUpdate,
    ProjectComplianceAssessmentUpdate,
    ProjectComplianceOut,
    ProjectComplianceRequirementOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import (
    advance_approval_state_on_assessment,
    build_evidence_out,
    build_requirement_out,
    build_status_out,
    find_pcrs_linked_to_evidence,
    invalidate_approval_if_in_flight,
    list_expiring_or_expired_evidence,
    load_pcrs_and_applicability,
)
from app.modules.registry import APPROVAL_ACTION_ROUTE_EXTRA
from app.schemas.audit import AuditEventOut
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
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


def _invalidate_approvals_supported_by_evidence(
    db: Session, project_id: UUID, evidence: ComplianceEvidence, actor_id: UUID, *, reason: str
) -> None:
    """Applies §12/§16/§27's evidence-side auto-invalidation: for every
    `ProjectComplianceRequirement` this evidence supports (directly or via
    a required-action assessment — `service.py::find_pcrs_linked_to_evidence`),
    downgrades an in-flight or decided approval to `REQUIRES_REASSESSMENT`
    (`service.py::invalidate_approval_if_in_flight`) and logs the
    transition against that requirement's own history, exactly like every
    other approval-state change on this router. Called by `archive_evidence`
    (evidence marked no longer applicable) and `revalidate_evidence`
    (evidence's expiry information changed) — see each of those endpoints'
    own docstrings; a no-op for a piece of evidence that supports nothing,
    or whose linked rows aren't currently `PENDING_APPROVAL`/`APPROVED`.
    `actor_id` is the user who performed the evidence mutation that
    triggered this — a real human action, unlike a future Phase 10
    passive-expiry sweep, which would log with `actor_id=None` instead.

    Does not commit — callers commit as part of their own single
    transaction, same convention as every other mutation on this router.
    """
    for pcr in find_pcrs_linked_to_evidence(db, evidence_id=evidence.id):
        previous_approval_state = invalidate_approval_if_in_flight(pcr)
        if previous_approval_state is None:
            continue
        log_event(
            db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="approval_invalidated",
            actor_id=actor_id, project_id=project_id,
            detail={
                "reason": reason, "evidence_id": str(evidence.id),
                "previous_approval_state": previous_approval_state.value,
                "new_approval_state": pcr.approval_state.value,
            },
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


@router.get("/pending-approvals", response_model=list[PendingApprovalOut])
def list_pending_approvals(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every requirement currently `PENDING_APPROVAL` across this project's
    active standard assignments (§12's "Pending Approval" as its own
    drillable list) — the `compliance_list_pending_approvals` MCP tool.
    Mirrors `list_non_compliant_requirements`'s exact loop shape above."""
    assignments = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.is_archived.is_(False)
        )
    ).all()

    results: list[PendingApprovalOut] = []
    for project_compliance in assignments:
        version = db.get(ComplianceStandardVersion, project_compliance.standard_version_id)
        standard = db.get(ComplianceStandard, version.standard_id)
        pcrs, _applicability = load_pcrs_and_applicability(
            db, project_compliance_id=project_compliance.id, standard_version_id=version.id
        )
        requirements_by_id = {
            r.id: r
            for r in db.scalars(
                select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
            ).all()
        }
        for pcr in pcrs:
            if pcr.approval_state != ComplianceApprovalState.PENDING_APPROVAL:
                continue
            requirement = requirements_by_id[pcr.requirement_id]
            results.append(
                PendingApprovalOut(
                    project_compliance_id=project_compliance.id,
                    standard_reference=standard.reference,
                    standard_name=standard.name,
                    version_label=version.version_label,
                    project_compliance_requirement_id=pcr.id,
                    requirement_id=requirement.id,
                    requirement_reference=requirement.reference,
                    requirement_name=requirement.name,
                    compliance_status=pcr.compliance_status,
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

    previous_approval_state = None
    if previous_applicability != payload.applicability:
        previous_approval_state = invalidate_approval_if_in_flight(pcr)

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
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/submit-for-approval",
    response_model=ProjectComplianceRequirementOut,
    openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA,
)
def submit_requirement_for_approval(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Requests formal approval/sign-off for this requirement's current
    assessment (§12) — `ASSESSED` -> `PENDING_APPROVAL`. 409 from any other
    `approval_state`, enforcing §12's own minimum ordering ("Not Assessed ->
    Assessed -> Pending Approval -> ...") rather than allowing e.g. a
    `NOT_ASSESSED` row to be submitted with nothing yet assessed."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if pcr.approval_state != ComplianceApprovalState.ASSESSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot submit for approval from state '{pcr.approval_state.value}'; the requirement must be "
            "'assessed' first.",
        )
    pcr.approval_state = ComplianceApprovalState.PENDING_APPROVAL
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="submitted_for_approval",
        actor_id=current_user.id, project_id=project_id,
        detail={"previous_approval_state": "assessed", "new_approval_state": "pending_approval"},
    )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/approve",
    response_model=ProjectComplianceRequirementOut,
    openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA,
)
def approve_requirement(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ComplianceApprovalDecisionRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Formally approves/signs off this requirement's assessment (§12) —
    `PENDING_APPROVAL` -> `APPROVED`. Gated the same as every other
    mutating endpoint on this router (`compliance_officer` or
    `PROJECT_MANAGER`) — §11/§26 describe "Approve/sign off compliance
    where authorised" as one of the same Project Manager/Compliance
    Officer actions as assessing, with no separate approver role named.
    Marked `APPROVAL_ACTION_ROUTE_EXTRA` so Phase 4's manifest-builder can
    never expose this as an MCP tool, regardless of what a future
    `module.py` declares."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if pcr.approval_state != ComplianceApprovalState.PENDING_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot approve from state '{pcr.approval_state.value}'; the requirement must be "
            "'pending_approval' first.",
        )
    pcr.approval_state = ComplianceApprovalState.APPROVED
    pcr.approval_decided_at = datetime.now(UTC)
    pcr.approval_decided_by = current_user.id
    pcr.decision_note = payload.decision_note
    log_event(
        db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="approved",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_approval_state": "pending_approval", "new_approval_state": "approved",
            "decision_note": payload.decision_note,
        },
    )
    db.commit()
    db.refresh(pcr)
    _pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=project_compliance.standard_version_id
    )
    return build_requirement_out(pcr, applicability)


@router.post(
    "/project-compliance/{project_compliance_id}/requirements/{pcr_id}/reject",
    response_model=ProjectComplianceRequirementOut,
    openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA,
)
def reject_requirement(
    project_id: UUID, project_compliance_id: UUID, pcr_id: UUID, payload: ComplianceApprovalDecisionRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Formally rejects this requirement's assessment (§12) —
    `PENDING_APPROVAL` -> `REJECTED`. `decision_note` is mandatory (400) —
    mirrors §16's existing mandatory-rationale rule for Non-Compliant/Not-
    Applicable decisions, applied to a rejection for the same reason: a
    rejection must never appear with no indication of why."""
    project_compliance, pcr = _get_pcr_or_404(db, project_id, project_compliance_id, pcr_id)
    if pcr.approval_state != ComplianceApprovalState.PENDING_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot reject from state '{pcr.approval_state.value}'; the requirement must be "
            "'pending_approval' first.",
        )
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
            "previous_approval_state": "pending_approval", "new_approval_state": "rejected",
            "decision_note": payload.decision_note,
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
    evidence_ids = db.scalars(
        select(ComplianceEvidenceRequirementLink.evidence_id).where(
            ComplianceEvidenceRequirementLink.project_compliance_requirement_id == pcr.id
        )
    ).all()
    if not evidence_ids:
        return []
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(evidence_ids))).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]


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
    evidence_ids = db.scalars(
        select(ComplianceEvidenceActionLink.evidence_id).where(
            ComplianceEvidenceActionLink.required_action_assessment_id == assessment.id
        )
    ).all()
    if not evidence_ids:
        return []
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(evidence_ids))).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]


# --- Evidence (§13-§15) -----------------------------------------------------------


@router.post("/evidence", response_model=ComplianceEvidenceOut, status_code=status.HTTP_201_CREATED)
def create_evidence(
    project_id: UUID, payload: ComplianceEvidenceCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Creates a piece of supporting evidence for this project (§13),
    optionally linked to one or more requirement/required-action
    assessments at creation time — each id is verified to belong to this
    project before the row or any link is created (404 on a mismatch,
    mirroring this router's own established "wrong scope -> 404"
    convention for every other cross-reference check). `provided_by`/
    `provided_at` are never caller-supplied."""
    for pcr_id in payload.project_compliance_requirement_ids:
        _get_pcr_for_project_or_404(db, project_id, pcr_id)
    for assessment_id in payload.required_action_assessment_ids:
        _get_assessment_for_project_or_404(db, project_id, assessment_id)

    now = datetime.now(UTC)
    evidence = ComplianceEvidence(
        project_id=project_id, title=payload.title, description=payload.description,
        issuing_organisation=payload.issuing_organisation, issued_date=payload.issued_date,
        expiry_date=payload.expiry_date, provided_by=current_user.id, provided_at=now, notes=payload.notes,
    )
    db.add(evidence)
    db.flush()
    for pcr_id in payload.project_compliance_requirement_ids:
        db.add(ComplianceEvidenceRequirementLink(
            evidence_id=evidence.id, project_compliance_requirement_id=pcr_id, linked_by=current_user.id,
            created_at=now,
        ))
    for assessment_id in payload.required_action_assessment_ids:
        db.add(ComplianceEvidenceActionLink(
            evidence_id=evidence.id, required_action_assessment_id=assessment_id, linked_by=current_user.id,
            created_at=now,
        ))
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"title": evidence.title})
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.get("/evidence", response_model=list[ComplianceEvidenceOut])
def list_evidence(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every piece of evidence for this project, including archived
    rows — a caller wanting only active evidence filters client-side,
    mirroring `list_project_compliance`'s own identical judgment call."""
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.project_id == project_id)).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]


@router.get("/expiring-evidence", response_model=list[ComplianceEvidenceOut])
def get_expiring_evidence(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every non-archived piece of evidence approaching or past its
    expiry (§14) — the `compliance_list_expiring_evidence` MCP tool
    (`module.py`)."""
    return [build_evidence_out(db, evidence) for evidence in list_expiring_or_expired_evidence(db, project_id=project_id)]


@router.get("/evidence/{evidence_id}", response_model=ComplianceEvidenceOut)
def get_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single piece of evidence."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return build_evidence_out(db, evidence)


@router.patch("/evidence/{evidence_id}", response_model=ComplianceEvidenceOut)
def update_evidence(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Updates evidence metadata — deliberately excludes `expiry_date`;
    see `ComplianceEvidenceUpdate`'s own docstring for §15's
    revalidation-only rule."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    evidence.title = payload.title
    evidence.description = payload.description
    evidence.issuing_organisation = payload.issuing_organisation
    evidence.issued_date = payload.issued_date
    evidence.notes = payload.notes
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/archive", response_model=ComplianceEvidenceOut)
def archive_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Marks evidence as no longer applicable (§13's "Whether it remains
    applicable"), retained (not deleted) since other assessments' own
    audit trail (§16) may still reference it via a link row."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    if evidence.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This evidence is already archived.")
    evidence.is_archived = True
    evidence.archived_at = datetime.now(UTC)
    evidence.archived_by = current_user.id
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    _invalidate_approvals_supported_by_evidence(db, project_id, evidence, current_user.id, reason="evidence_archived")
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/unarchive", response_model=ComplianceEvidenceOut)
def unarchive_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Reverts `archive_evidence`, to correct a mistake."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    if not evidence.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This evidence is not archived.")
    evidence.is_archived = False
    evidence.archived_at = None
    evidence.archived_by = None
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/revalidate", response_model=ComplianceEvidenceOut)
def revalidate_evidence(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceRevalidateRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Revalidates a piece of evidence (§15) — records the *previous*
    expiry in an append-only `ComplianceEvidenceRevalidation` row before
    updating `expiry_date` in place, so revalidating a second time never
    loses the first revalidation's own "previous" value (§15: "must not
    overwrite the historical record")."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    previous_expiry_date = evidence.expiry_date
    now = datetime.now(UTC)
    evidence.expiry_date = payload.new_expiry_date
    db.add(ComplianceEvidenceRevalidation(
        evidence_id=evidence.id, revalidated_by=current_user.id, revalidated_at=now,
        previous_expiry_date=previous_expiry_date, new_expiry_date=payload.new_expiry_date,
        justification=payload.justification, created_at=now,
    ))
    log_event(
        db, entity_type="compliance_evidence", entity_id=evidence.id, action="revalidated",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_expiry_date": previous_expiry_date.isoformat() if previous_expiry_date else None,
            "new_expiry_date": payload.new_expiry_date.isoformat() if payload.new_expiry_date else None,
            "justification": payload.justification,
        },
    )
    _invalidate_approvals_supported_by_evidence(db, project_id, evidence, current_user.id, reason="evidence_revalidated")
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.get("/evidence/{evidence_id}/revalidations", response_model=list[ComplianceEvidenceRevalidationOut])
def list_evidence_revalidations(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This evidence's full revalidation history (§15), oldest first —
    never overwritten, only ever appended to."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return db.scalars(
        select(ComplianceEvidenceRevalidation)
        .where(ComplianceEvidenceRevalidation.evidence_id == evidence.id)
        .order_by(ComplianceEvidenceRevalidation.created_at)
    ).all()


# --- Evidence linkage (§13's multi-requirement/multi-action support) -------------


@router.post(
    "/evidence/{evidence_id}/requirement-links", response_model=ComplianceEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def link_evidence_to_requirement(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceRequirementLinkCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Links existing evidence to an additional requirement's assessment
    (§13's "a single piece of evidence should be capable of supporting
    multiple compliance requirements") — idempotent (re-linking an
    already-linked pair is a no-op, not a 409/duplicate error)."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    pcr = _get_pcr_for_project_or_404(db, project_id, payload.project_compliance_requirement_id)
    existing = db.scalar(
        select(ComplianceEvidenceRequirementLink).where(
            ComplianceEvidenceRequirementLink.evidence_id == evidence.id,
            ComplianceEvidenceRequirementLink.project_compliance_requirement_id == pcr.id,
        )
    )
    if existing is None:
        db.add(ComplianceEvidenceRequirementLink(
            evidence_id=evidence.id, project_compliance_requirement_id=pcr.id, linked_by=current_user.id,
            created_at=datetime.now(UTC),
        ))
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="requirement_linked",
                  actor_id=current_user.id, project_id=project_id,
                  detail={"project_compliance_requirement_id": str(pcr.id)})
        db.commit()
    return build_evidence_out(db, evidence)


@router.delete("/evidence/{evidence_id}/requirement-links/{pcr_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_from_requirement(
    project_id: UUID, evidence_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = db.scalar(
        select(ComplianceEvidenceRequirementLink).where(
            ComplianceEvidenceRequirementLink.evidence_id == evidence.id,
            ComplianceEvidenceRequirementLink.project_compliance_requirement_id == pcr_id,
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This evidence is not linked to that requirement.")
    db.delete(link)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="requirement_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"project_compliance_requirement_id": str(pcr_id)})
    db.commit()


@router.post(
    "/evidence/{evidence_id}/action-links", response_model=ComplianceEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def link_evidence_to_action_assessment(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceActionLinkCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """The required-action equivalent of `link_evidence_to_requirement`."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    assessment = _get_assessment_for_project_or_404(db, project_id, payload.required_action_assessment_id)
    existing = db.scalar(
        select(ComplianceEvidenceActionLink).where(
            ComplianceEvidenceActionLink.evidence_id == evidence.id,
            ComplianceEvidenceActionLink.required_action_assessment_id == assessment.id,
        )
    )
    if existing is None:
        db.add(ComplianceEvidenceActionLink(
            evidence_id=evidence.id, required_action_assessment_id=assessment.id, linked_by=current_user.id,
            created_at=datetime.now(UTC),
        ))
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="action_linked",
                  actor_id=current_user.id, project_id=project_id,
                  detail={"required_action_assessment_id": str(assessment.id)})
        db.commit()
    return build_evidence_out(db, evidence)


@router.delete("/evidence/{evidence_id}/action-links/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_from_action_assessment(
    project_id: UUID, evidence_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = db.scalar(
        select(ComplianceEvidenceActionLink).where(
            ComplianceEvidenceActionLink.evidence_id == evidence.id,
            ComplianceEvidenceActionLink.required_action_assessment_id == assessment_id,
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This evidence is not linked to that required action assessment.")
    db.delete(link)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="action_unlinked",
              actor_id=current_user.id, project_id=project_id,
              detail={"required_action_assessment_id": str(assessment_id)})
    db.commit()


# --- Evidence file attachments (§13's "reuse existing attachment mechanisms") ---


@router.post("/evidence/{evidence_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_evidence_attachment(
    project_id: UUID, evidence_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Uploads and attaches a new file to a piece of evidence — mirrors
    `routers.requirements.upload_requirement_attachment`'s shape exactly,
    reusing `services.files.upload_file` per §13's "reuse ReqTrackManager's
    existing attachment/file mechanisms where possible" rather than a
    second, independent file storage mechanism."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(ComplianceEvidenceFile(
        evidence_id=evidence.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at
    ))
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/evidence/{evidence_id}/files/link", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
def link_evidence_org_resource(
    project_id: UUID, evidence_id: UUID, payload: LinkResourceRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Links an organisation shared resource file to a piece of evidence —
    mirrors `routers.requirements.link_org_resource`'s shape exactly."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    project = db.get(Project, project_id)
    asset = db.get(FileAsset, payload.file_id)
    if asset is None or not asset.is_org_resource or asset.organization_id != project.organization_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "file_id must be a shared resource in this project's organisation."
        )
    existing = db.scalar(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.evidence_id == evidence.id, ComplianceEvidenceFile.file_id == asset.id
        )
    )
    if existing is None:
        db.add(ComplianceEvidenceFile(
            evidence_id=evidence.id, file_id=asset.id, linked_by=current_user.id, created_at=datetime.now(UTC)
        ))
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_linked",
                  actor_id=current_user.id, project_id=project_id, detail={"file_id": str(asset.id)})
        db.commit()
    return asset


@router.get("/evidence/{evidence_id}/files", response_model=list[FileAssetOut])
def list_evidence_files(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return db.scalars(
        select(FileAsset)
        .join(ComplianceEvidenceFile, ComplianceEvidenceFile.file_id == FileAsset.id)
        .where(ComplianceEvidenceFile.evidence_id == evidence.id)
    ).all()


@router.delete("/evidence/{evidence_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_file(
    project_id: UUID, evidence_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Removes a file from a piece of evidence. Direct (non-shared)
    uploads are deleted outright; shared org resources are only unlinked —
    mirrors `routers.requirements.unlink_requirement_file`'s shape."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = db.scalar(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.evidence_id == evidence.id, ComplianceEvidenceFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this evidence.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None and not asset.is_org_resource:
        delete_file(db, asset)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
