"""
Module: modules.compliance.project_router.assignment

A project's own compliance-standard assignments (Phase 7/9/11): list/
get, self-service assignment (§20), version migration (§27, with its
optional `confirmed_replacement_requirement_ids` carry-forward), plus
this project's overall status/non-compliant-requirements/pending-
approvals/outstanding-required-actions rollups and its downloadable
compliance report.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import NotificationType
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import ComplianceStandard, ComplianceStandardVersion, ProjectCompliance
from app.modules.compliance.project_router._shared import (
    _get_project_compliance_or_404,
    _notify_approval_invalidated,
    _require_officer,
    _require_view,
)
from app.modules.compliance.reports import collect_project_compliance_report, generate_project_compliance_csv, generate_project_compliance_pdf
from app.modules.compliance.schemas import (
    NonCompliantRequirementOut,
    OutstandingRequiredActionOut,
    PendingApprovalOut,
    ProjectComplianceCreate,
    ProjectComplianceMigrationRequest,
    ProjectComplianceMigrationResultOut,
    ProjectComplianceOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import (
    build_migration_result_out,
    build_status_out,
    diff_standard_versions,
    get_effective_compliance_officers,
    list_non_compliant_requirements_for_project,
    list_outstanding_required_actions_for_project,
    list_pending_approvals_for_project,
    materialize_assessment_rows,
    migrate_project_compliance,
)
from app.services import notifications
from app.services.audit import log_event
from app.services.downloads import filename_safe

router = APIRouter(tags=["compliance-project-assignment"])


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
    "/project-compliance", response_model=ProjectComplianceOut, status_code=status.HTTP_201_CREATED,
)
def create_project_compliance_self_service(
    project_id: UUID, payload: ProjectComplianceCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Phase 20's **default, primary** way a project acquires a standard:
    a `compliance_officer` grant or `ProjectRole.PROJECT_MANAGER` (this
    router's own established `_require_officer` composition, unchanged) may
    assign any `PUBLISHED` version of any non-archived standard in their
    project's own organisation, without needing a Compliance Manager to act
    on their behalf first. Payload/response shape is identical to the org
    router's own `create_project_compliance` (`router.py:1485` before this
    phase) — the two endpoints differ only in *who* may call them and
    *which router* they live on, matching this repo's existing "assignment
    lives wherever the RBAC boundary for that action already lives" split
    (`project_router.py`'s own module docstring).

    A Project Manager may **not** use this endpoint to change a standard's
    own `applicability_default`/exclusion-list setting (§3) — that stays
    Compliance-Manager/org-admin territory on `router.py`. This endpoint
    only ever creates a `ProjectCompliance` row for *this* project, the
    exact same boundary Phase 7 already drew between "who curates the
    org-wide catalogue" and "who runs day-to-day assessment" — making PM-
    initiated assignment the default path shifts *which project links
    exist*, not *who governs the standard itself*."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    standard = db.get(ComplianceStandard, payload.standard_id)
    if standard is None or standard.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard not found.")
    if standard.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This standard is archived and can no longer be assigned.")
    version = db.get(ComplianceStandardVersion, payload.standard_version_id)
    if version is None or version.standard_id != standard.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard version not found.")
    if version.status != ComplianceStandardVersionStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a published standard version can be assigned to a project."
        )
    existing = db.scalar(
        select(ProjectCompliance.id).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.standard_version_id == version.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project is already assigned to this standard version.")

    project_compliance = ProjectCompliance(
        project_id=project_id, standard_version_id=version.id,
        assigned_at=datetime.now(UTC), assigned_by=current_user.id,
        target_compliance_date=payload.target_compliance_date,
    )
    db.add(project_compliance)
    db.flush()
    materialize_assessment_rows(db, project_compliance_id=project_compliance.id, standard_version_id=version.id)
    log_event(
        db, entity_type="project_compliance", entity_id=project_compliance.id, action="created",
        actor_id=current_user.id, project_id=project_id,
        detail={"standard_version_id": str(version.id), "assigned_via": "project_manager_self_service"},
    )
    for recipient_id in get_effective_compliance_officers(db, project_id):
        recipient = db.get(User, recipient_id)
        if recipient is None:
            continue
        notifications.notify(
            db, recipient, notification_type=NotificationType.COMPLIANCE_ASSIGNMENT_CREATED,
            title="New compliance assignment",
            body="This project was assigned to a compliance standard and needs assessment to begin.",
            project_id=project_id, entity_type="project_compliance", entity_id=str(project_compliance.id),
            actor_id=current_user.id,
        )
    db.commit()
    db.refresh(project_compliance)
    return project_compliance


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


@router.get("/reports")
def get_project_compliance_report(
    project_id: UUID, format: Literal["pdf", "csv"] = Query(...), include_archived: bool = Query(False),
    standard_id: UUID | None = Query(None), standard_version_id: UUID | None = Query(None),
    requirement_id: UUID | None = Query(None),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Generates this project's compliance report in `format` — PDF or CSV
    (§29) — merged from two separate `/reports/pdf`/`/reports/csv` GETs on
    2026-09-22 (see docs/decisions.md) since they only differed in output
    format, not the data collected. PDF: every requirement's assessment
    across its assigned standards, plus evidence/review/cross-standard-
    mapping appendices. CSV: a flat export, one row per requirement per
    assigned standard. View-gated like every other read endpoint on this
    router (§26: "Other Project Users: Read access according to existing
    project permissions") — a report never surfaces anything this same
    caller couldn't already read via the JSON endpoints it's built from
    (see `app.modules.compliance.reports`'s own module docstring).

    `standard_id`/`standard_version_id`/`requirement_id` (Phase 43) are
    optional scoping filters — see `collect_project_compliance_report`'s own
    docstring — passed by `OutstandingPanel.tsx`'s Export trigger to match
    whatever that panel's own Standard/Standard version/Sub-section filters
    currently show."""
    project = db.get(Project, project_id)
    data = collect_project_compliance_report(
        db, project, include_archived=include_archived,
        standard_id=standard_id, standard_version_id=standard_version_id, requirement_id=requirement_id,
    )
    if format == "csv":
        csv_bytes = generate_project_compliance_csv(data)
        return Response(
            content=csv_bytes, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-compliance-report.csv"'},
        )
    pdf_bytes = generate_project_compliance_pdf(project.name, data)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-compliance-report.pdf"'},
    )
