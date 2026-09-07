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

Phase 11 (Cross-Standard Mapping + Version Impact, §27) adds one mutating
action to the "Project compliance assignments" section below: `POST
.../project-compliance/{id}/migrate-version`, the explicit, user-triggered
action a project uses to adopt a newer, published version of the standard
it's already assigned to. It creates a **new** `ProjectCompliance` row
(the existing one stays pinned to its original version forever, per §27
and this module's own Phase 7 design) and archives the old one — never a
silent, in-place version swap. See `service.py::migrate_project_compliance`'s
own docstring for exactly which requirements' assessments are carried
forward vs. left to reassess, and why. No MCP tool is declared for this
action (`module.py`'s own Phase 11 notes) — it is a significant mutation
with wide side effects across many rows, and nothing in this phase's spec
asks for one; the read-only version-diff endpoint on the org router
(`router.py::get_standard_version_diff`) is this action's natural "preview
before you commit" companion and *is* an MCP tool.

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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApprovalState,
    ComplianceReviewStatus,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceEvidenceActionLink,
    ComplianceEvidenceFile,
    ComplianceEvidenceRequirementLink,
    ComplianceEvidenceRevalidation,
    ComplianceRequiredActionAssessment,
    ComplianceReview,
    ComplianceReviewEvidenceLink,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.reports import (
    collect_project_compliance_report,
    generate_project_compliance_csv,
    generate_project_compliance_pdf,
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
    ComplianceReviewCompleteRequest,
    ComplianceReviewCreate,
    ComplianceReviewEvidenceLinkCreate,
    ComplianceReviewOut,
    ComplianceReviewUpdate,
    NonCompliantRequirementOut,
    OutstandingRequiredActionOut,
    PendingApprovalOut,
    ProjectComplianceApplicabilityUpdate,
    ProjectComplianceAssessmentUpdate,
    ProjectComplianceMigrationRequest,
    ProjectComplianceMigrationResultOut,
    ProjectComplianceOut,
    ProjectComplianceRequirementOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import (
    advance_approval_state_on_assessment,
    build_evidence_out,
    build_migration_result_out,
    build_requirement_out,
    build_review_out,
    build_status_out,
    complete_review,
    diff_standard_versions,
    find_pcrs_linked_to_evidence,
    get_effective_compliance_officers,
    invalidate_approval_if_in_flight,
    list_expiring_or_expired_evidence,
    list_non_compliant_requirements_for_project,
    list_outstanding_required_actions_for_project,
    list_pending_approvals_for_project,
    list_reviews_due_for_project,
    load_pcrs_and_applicability,
    migrate_project_compliance,
)
from app.modules.registry import APPROVAL_ACTION_ROUTE_EXTRA
from app.schemas.audit import AuditEventOut
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.services import notifications
from app.services.audit import log_event
from app.services.downloads import filename_safe
from app.services.files import delete_file, upload_file
from app.services.rbac import get_effective_org_roles, require_module_role, require_project_module_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/compliance", tags=["compliance"])

# Same "factory called once, at router-definition time" convention as
# `router.py` — see that file's own comment.
_require_officer = require_module_role("compliance", "compliance_officer")
_require_view = require_project_module_enabled("compliance")


# --- Cross-scope ownership-chain lookups (404, not 403, on a mismatch) ---------


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
        _notify_approval_invalidated(db, project_id, pcr, actor_id=actor_id)


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


@router.post(
    "/project-compliance/{project_compliance_id}/migrate-version",
    response_model=ProjectComplianceMigrationResultOut, status_code=status.HTTP_201_CREATED,
)
def migrate_project_compliance_version(
    project_id: UUID, project_compliance_id: UUID, payload: ProjectComplianceMigrationRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """§27's explicit, user-triggered version-migration action — adopts a
    newer, published version of the standard this assignment already
    tracks. Gated the same as every other mutating endpoint on this router
    (`compliance_officer` or `PROJECT_MANAGER`), *not* `compliance_manager`
    like the org router's own initial-assignment endpoint
    (`router.py::create_project_compliance`) — a deliberate distinction:
    choosing *which standard* a project tracks is a Compliance Manager
    decision (§26), but rolling an *already-tracked* standard forward to a
    newer version is project-level maintenance of an existing assignment,
    the same class of action as everything else this router already gates
    at the officer/PROJECT_MANAGER level.

    Never mutates the existing assignment's own `standard_version_id`
    (§27's "Existing Project Compliance assignments must remain associated
    with their original version" — Phase 7's own pinned-forever design) —
    creates a new `ProjectCompliance` row instead (`service.migrate_
    project_compliance`) and archives the old one here, so the old row's
    own `ProjectComplianceRequirement` history is retained completely
    untouched. See that function's own docstring for exactly which
    requirements' assessments are carried forward vs. left to reassess,
    and why.

    `payload.confirmed_replacement_requirement_ids` is the officer's own
    per-migration opt-in to carry an assessment forward across a
    `replaced` version-diff pair (§27; `models.py`'s own Phase 11 notes on
    `ComplianceMappingRelationshipTypeDefinition.implies_equivalence`).
    Validated against a freshly computed diff *before* calling `service.
    migrate_project_compliance` — every id must name a new-version
    requirement that is actually part of this migration's `replaced` set
    *and* whose mapping's relationship type has `implies_equivalence=True`,
    or this 400s outright rather than silently ignoring a stale/invalid
    confirmation (this module's usual "never silent" convention, applied
    here to a client-supplied id list rather than a single path parameter)."""
    old_project_compliance = _get_project_compliance_or_404(db, project_id, project_compliance_id)
    if old_project_compliance.is_archived:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This assignment is archived; unarchive it first, or assign the new version directly instead of migrating.",
        )
    old_version = db.get(ComplianceStandardVersion, old_project_compliance.standard_version_id)
    new_version = db.get(ComplianceStandardVersion, payload.new_standard_version_id)
    if new_version is None or new_version.standard_id != old_version.standard_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "new_standard_version_id must be another version of the same standard."
        )
    if new_version.status != ComplianceStandardVersionStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a published standard version can be migrated to.")
    if new_version.version_number <= old_version.version_number:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Migration must move to a newer version (a higher version_number) than the current assignment.",
        )
    existing = db.scalar(
        select(ProjectCompliance.id).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.standard_version_id == new_version.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project is already assigned to this standard version.")

    confirmed_ids = frozenset(payload.confirmed_replacement_requirement_ids)
    if confirmed_ids:
        diff_preview = diff_standard_versions(
            db, standard_id=new_version.standard_id, old_version=old_version, new_version=new_version
        )
        eligible_ids = {
            new.id for _old, new, _mapping, relationship_type in diff_preview.replaced
            if relationship_type.implies_equivalence
        }
        invalid_ids = confirmed_ids - eligible_ids
        if invalid_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "confirmed_replacement_requirement_ids must each name a new-version requirement that is part of "
                "this migration's 'replaced' set and whose mapping's relationship type has "
                f"implies_equivalence=true: {sorted(str(i) for i in invalid_ids)}",
            )

    outcome = migrate_project_compliance(
        db, old_project_compliance=old_project_compliance, new_version=new_version, actor_id=current_user.id,
        confirmed_replacement_requirement_ids=confirmed_ids,
    )

    old_project_compliance.is_archived = True
    old_project_compliance.archived_at = datetime.now(UTC)
    old_project_compliance.archived_by = current_user.id
    log_event(
        db, entity_type="project_compliance", entity_id=old_project_compliance.id, action="archived",
        actor_id=current_user.id, project_id=project_id,
        detail={"reason": "version_migration", "migrated_to_project_compliance_id": str(outcome.new_project_compliance.id)},
    )
    log_event(
        db, entity_type="project_compliance", entity_id=outcome.new_project_compliance.id, action="migrated",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_project_compliance_id": str(old_project_compliance.id),
            "previous_standard_version_id": str(old_version.id),
            "new_standard_version_id": str(new_version.id),
            "carried_forward_count": sum(1 for impact in outcome.impacts if impact.carried_forward),
            "requires_reassessment_count": sum(1 for impact in outcome.impacts if impact.requires_reassessment),
            "confirmed_replaced_carry_forward_count": sum(
                1 for impact in outcome.impacts if impact.change == "replaced" and impact.carried_forward
            ),
        },
    )
    for new_pcr, previous_approval_state in outcome.invalidated:
        log_event(
            db, entity_type="project_compliance_requirement", entity_id=new_pcr.id, action="approval_invalidated",
            actor_id=current_user.id, project_id=project_id,
            detail={
                "reason": "standard_version_migration",
                "previous_approval_state": previous_approval_state.value,
                "new_approval_state": new_pcr.approval_state.value,
            },
        )
        _notify_approval_invalidated(db, project_id, new_pcr, actor_id=current_user.id)

    for recipient_id in get_effective_compliance_officers(db, project_id):
        recipient = db.get(User, recipient_id)
        if recipient is None:
            continue
        notifications.notify(
            db, recipient, notification_type=NotificationType.COMPLIANCE_ASSIGNMENT_CREATED,
            title="Compliance assignment migrated to a new standard version",
            body=f'This project\'s assignment to "{old_version.version_label}" was migrated to version '
                 f'"{new_version.version_label}"; some requirements need (re-)assessment.',
            project_id=project_id, entity_type="project_compliance", entity_id=str(outcome.new_project_compliance.id),
            actor_id=current_user.id,
        )

    db.commit()
    db.refresh(outcome.new_project_compliance)
    for impact in outcome.impacts:
        db.refresh(impact.new_pcr)

    return build_migration_result_out(
        outcome, previous_project_compliance_id=old_project_compliance.id, previous_standard_version_id=old_version.id
    )


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
    requirements` MCP tool. Delegates to `service.py::list_non_compliant_
    requirements_for_project`, shared verbatim with `router.py`'s Phase 14
    org-wide aggregation (moved there in Phase 14; behaviour unchanged)."""
    return list_non_compliant_requirements_for_project(db, project_id=project_id)


@router.get("/pending-approvals", response_model=list[PendingApprovalOut])
def list_pending_approvals(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every requirement currently `PENDING_APPROVAL` across this project's
    active standard assignments (§12's "Pending Approval" as its own
    drillable list) — the `compliance_list_pending_approvals` MCP tool.
    Delegates to `service.py::list_pending_approvals_for_project`, shared
    verbatim with `router.py`'s Phase 14 org-wide aggregation (moved there
    in Phase 14; behaviour unchanged)."""
    return list_pending_approvals_for_project(db, project_id=project_id)


@router.get("/outstanding-required-actions", response_model=list[OutstandingRequiredActionOut])
def list_outstanding_required_actions(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every incomplete required-action assessment whose owning requirement
    is currently applicable, across this project's active standard
    assignments (Phase 14, §22's "outstanding Required Actions" as its own
    drillable list — added alongside the org-wide aggregation of the same
    name in `router.py` since no flattened listing existed for this at
    either scope before Phase 14, only the per-requirement nested
    `.../required-action-assessments` endpoint from Phase 7). Delegates to
    `service.py::list_outstanding_required_actions_for_project`, shared
    verbatim with the org-wide version."""
    return list_outstanding_required_actions_for_project(db, project_id=project_id)


# --- Reports (Phase 15, §29) -----------------------------------------------------


@router.get("/reports/pdf")
def get_project_compliance_report_pdf(
    project_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Generates a PDF compliance report for this project (§29) — every
    requirement's assessment across its assigned standards, plus evidence/
    review/cross-standard-mapping appendices. View-gated like every other
    read endpoint on this router (§26: "Other Project Users: Read access
    according to existing project permissions") — a report never surfaces
    anything this same caller couldn't already read via the JSON endpoints
    it's built from (see `app.modules.compliance.reports`'s own module
    docstring)."""
    project = db.get(Project, project_id)
    data = collect_project_compliance_report(db, project, include_archived=include_archived)
    pdf_bytes = generate_project_compliance_pdf(project.name, data)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-compliance-report.pdf"'},
    )


@router.get("/reports/csv")
def get_project_compliance_report_csv(
    project_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Generates a flat CSV export of this project's compliance assessments
    (§29) — one row per requirement per assigned standard."""
    project = db.get(Project, project_id)
    data = collect_project_compliance_report(db, project, include_archived=include_archived)
    csv_bytes = generate_project_compliance_csv(data)
    return Response(
        content=csv_bytes, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-compliance-report.csv"'},
    )


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
    evidence.expiry_reminder_sent_at = None
    evidence.expiry_notified_at = None
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


# --- Phase 10: Scheduled reviews (project-level; §17, §18, §28) -----------------


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


@router.post("/reviews/{review_id}/complete", response_model=ComplianceReviewOut)
def complete_project_review(
    project_id: UUID, review_id: UUID, payload: ComplianceReviewCompleteRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Completes a `SCHEDULED` review (§17's "Review outcome"), 409 if
    already completed. Schedules the next cycle automatically when this
    review recurs — see `service.py::complete_review`'s own docstring."""
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
