"""
Module: modules.compliance.router.standards

A compliance standard's own CRUD/lifecycle (Phase 6): create, list,
get, update, archive/unarchive, plus its audit history and export/
import as a portable JSON document (Phase 21), its Overview
project-summary stat tiles (Phase 23), and its applicability-default/
per-project-exclusion configuration (Phase 20). Standard membership/
role grants are a deliberately separate bucket (`standard_access.py`)
even though they also key off `standard_id` — see that module's own
docstring for why.
"""

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditEvent
from app.models.module_role import UserModuleRole
from app.models.notification import NotificationType
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardApplicabilityDefault
from app.modules.compliance.export import export_standard_data, import_standard_data
from app.modules.compliance.models import ComplianceStandard, ComplianceStandardDefaultExclusion, ComplianceStandardVersion, ProjectCompliance
from app.modules.compliance.router._shared import _get_standard_or_404, _require_manage, _require_standard_manage, _require_view
from app.modules.compliance.schemas import (
    ComplianceStandardApplicabilityDefaultUpdate,
    ComplianceStandardCreate,
    ComplianceStandardDefaultExclusionCreate,
    ComplianceStandardDefaultExclusionOut,
    ComplianceStandardOut,
    ComplianceStandardUpdate,
    ProjectComplianceStatusOut,
    StandardImportResult,
)
from app.modules.compliance.service import (
    _reconcile_one_project,
    build_status_out,
    get_effective_compliance_officers,
    reconcile_standard_applicability,
)
from app.schemas.audit import AuditEventOut
from app.services import notifications
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.downloads import filename_safe

router = APIRouter(tags=["compliance-org-standards"])


@router.post("/standards", response_model=ComplianceStandardOut, status_code=status.HTTP_201_CREATED)
def create_standard(
    organization_id: UUID, payload: ComplianceStandardCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new organisation-level compliance standard (§2), together
    with its mandatory first version (version 1), in a single transaction —
    a standard is never left with zero versions. `owner_id` defaults to the
    creating user when omitted.

    The creator is also granted a direct `standards_manager` role on this
    standard (Phase 22) — mirrors `create_project`'s own already-established
    "on creation, the creator is granted a direct PROJECT_MANAGER" precedent
    (`routers/projects.py:403`) exactly, applied one level down, so a
    standard's manager floor (§3: "a standard must always have at least one
    standards_manager") is satisfied from the moment it exists, not left to
    a separate follow-up grant."""
    existing = db.scalar(
        select(ComplianceStandard.id).where(
            ComplianceStandard.organization_id == organization_id,
            ComplianceStandard.reference == payload.reference,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A standard with this reference already exists.")
    standard = ComplianceStandard(
        organization_id=organization_id,
        reference=payload.reference,
        name=payload.name,
        description=payload.description,
        issuing_organisation=payload.issuing_organisation,
        owner_id=payload.owner_id or current_user.id,
        creator_id=current_user.id,
    )
    db.add(standard)
    db.flush()
    log_event(db, entity_type="compliance_standard", entity_id=standard.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"reference": standard.reference, "name": standard.name})

    db.add(
        UserModuleRole(
            user_id=current_user.id, module_key="compliance", role_key="standards_manager",
            organization_id=organization_id, scope_entity_id=standard.id, granted_by=current_user.id,
        )
    )
    log_event(
        db, entity_type="user_module_role", entity_id=current_user.id, action="granted",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"module_key": "compliance", "role_key": "standards_manager", "standard_id": str(standard.id)},
    )

    version = ComplianceStandardVersion(
        standard_id=standard.id,
        version_number=1,
        version_label=payload.initial_version_label,
        effective_date=payload.initial_version_effective_date,
        change_note=payload.initial_version_change_note,
        created_by=current_user.id,
    )
    db.add(version)
    db.flush()
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"version_label": version.version_label, "cloned_from": None})

    db.commit()
    db.refresh(standard)
    return standard


@router.get("/standards", response_model=list[ComplianceStandardOut])
def list_standards(
    organization_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this organisation's compliance standards (§2). Any org member
    with the module enabled may list — see this module's own docstring for
    why viewing isn't manage-gated."""
    query = select(ComplianceStandard).where(ComplianceStandard.organization_id == organization_id)
    if not include_archived:
        query = query.where(ComplianceStandard.is_archived.is_(False))
    return db.scalars(query.order_by(ComplianceStandard.reference)).all()


@router.get("/standards/{standard_id}", response_model=ComplianceStandardOut)
def get_standard(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single compliance standard."""
    return _get_standard_or_404(db, organization_id, standard_id)


@router.get("/standards/{standard_id}/history", response_model=list[AuditEventOut])
def get_standard_history(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This standard's own audit history (compliance-module-plan.md Phase
    18's "Standard" nav-rail workspace, "History" section) — every
    `compliance_standard`-entity audit event logged against this row
    (created/updated/archived/unarchived, see this router's own create/
    update/archive/unarchive handlers above), oldest first. Mirrors
    `project_router.py::get_requirement_history`'s identical shape/query
    exactly, just against `compliance_standard` instead of
    `project_compliance_requirement` — view-gated, not manage-gated, same
    as every other read on this standard."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "compliance_standard", AuditEvent.entity_id == str(standard.id))
        .order_by(AuditEvent.created_at)
    ).all()


@router.get("/standards/{standard_id}/project-summary", response_model=list[ProjectComplianceStatusOut])
def get_standard_project_summary(
    organization_id: UUID, standard_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This standard's own slice of §20's per-assignment status (Phase 23's
    Overview "projects this standard applies to" / "compliant" stat tiles)
    — the exact same per-project computation `list_all_project_compliance`
    already runs across every standard in the org (`build_status_out`),
    narrowed to just the assignments whose version belongs to this one
    standard. No new counting logic: this is a narrower query plus the same
    `build_status_out` call, not a reimplementation of §20's percentage/
    state calculation.

    View-gated like every other read on this standard (`get_standard`,
    `list_standards`) rather than manage-gated like `list_all_project_
    compliance` itself — this is this standard's own Overview stats,
    visible to anyone who can already view the standard, not the
    Compliance Manager's cross-standard reporting §26 restricts."""
    _get_standard_or_404(db, organization_id, standard_id)
    query = (
        select(ProjectCompliance)
        .join(ComplianceStandardVersion, ComplianceStandardVersion.id == ProjectCompliance.standard_version_id)
        .join(Project, Project.id == ProjectCompliance.project_id)
        .where(Project.organization_id == organization_id, ComplianceStandardVersion.standard_id == standard_id)
    )
    if not include_archived:
        query = query.where(ProjectCompliance.is_archived.is_(False))
    assignments = db.scalars(query).all()
    return [build_status_out(db, pc) for pc in assignments]


@router.patch("/standards/{standard_id}", response_model=ComplianceStandardOut)
def update_standard(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardUpdate,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Updates a standard's name/description/issuing_organisation/owner_id.
    `reference` is immutable after creation — see `schemas.py`'s module
    docstring for why."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    standard.name = payload.name
    standard.description = payload.description
    standard.issuing_organisation = payload.issuing_organisation
    standard.owner_id = payload.owner_id
    log_event(db, entity_type="compliance_standard", entity_id=standard.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": standard.name})
    db.commit()
    db.refresh(standard)
    return standard


@router.post("/standards/{standard_id}/archive", response_model=ComplianceStandardOut)
def archive_standard(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Soft-archives a standard (§2's "Status" attribute), mirroring
    `Requirement`/`Project`'s own `is_archived`/`archived_at`/`archived_by`
    convention exactly."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    standard.is_archived = True
    standard.archived_at = datetime.now(UTC)
    standard.archived_by = current_user.id
    log_event(db, entity_type="compliance_standard", entity_id=standard.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(standard)
    return standard


@router.post("/standards/{standard_id}/unarchive", response_model=ComplianceStandardOut)
def unarchive_standard(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Restores an archived standard. Idempotent, like `unarchive_project`/
    `restore_requirement` — calling this on an already-active standard is a
    harmless no-op."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    standard.is_archived = False
    standard.archived_at = None
    standard.archived_by = None
    log_event(db, entity_type="compliance_standard", entity_id=standard.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(standard)
    return standard


@router.get("/standards/{standard_id}/export")
def export_standard(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Exports a single compliance standard (Phase 21, §29) as a portable,
    self-contained JSON document — every version's full requirement/
    required-action tree, plus the vocabulary/mapping subset it actually
    references — for backup or transfer into a different organisation/
    deployment via `POST .../standards/import`. Manage-gated like every
    other standards-curation action on this router; unlike the whole-org
    bundle (`GET /orgs/{id}/export`), this is a narrower, standard-scoped
    document — see `export.py::export_standard_data`'s own docstring."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    data = export_standard_data(db, standard)
    return Response(
        content=json.dumps(data, indent=2), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(standard.reference, fallback="standard")}-export.json"'},
    )


@router.post("/standards/import", response_model=StandardImportResult, status_code=status.HTTP_201_CREATED)
async def import_standard(
    organization_id: UUID, file: UploadFile = File(...), resolution: str | None = Form(None),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Imports a single compliance standard from a `GET .../standards/{id}/
    export` document (Phase 21, §29) into this organisation, always as a
    brand-new `ComplianceStandard` with every version forced to `DRAFT`
    regardless of its exported status (§4/§31) — see `export.py::import_
    standard_data`'s own docstring for the full reference-collision and
    cross-standard-mapping-resolution behaviour.

    `resolution` is only needed when this document's `reference` collides
    with a standard this organisation already has — omit it on the first
    attempt; a 409 response means the caller should ask the user to choose
    `"skip"` or `"import_as_copy"` and retry with that value."""
    raw_bytes = await file.read()
    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This file is not valid JSON.") from None

    warnings = BundleImportWarnings()
    users = UserResolver(db, current_user, warnings)
    org = db.get(Organization, organization_id)
    standard, skipped = import_standard_data(db, org, data, users, warnings, resolution=resolution)
    if skipped:
        return StandardImportResult(
            standard=None, skipped=True,
            warnings=["Import skipped: a standard with this reference already exists in this organisation."],
        )

    log_event(
        db, entity_type="compliance_standard", entity_id=standard.id, action="imported",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"reference": standard.reference, "warning_count": len(warnings.messages)},
    )
    db.commit()
    db.refresh(standard)
    return StandardImportResult(standard=standard, skipped=False, warnings=warnings.messages)


def _get_exclusion_target_project_or_400(db: Session, organization_id: UUID, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id must be a project in this organisation.")
    return project


def _get_exclusion_or_404(
    db: Session, organization_id: UUID, standard_id: UUID, project_id: UUID
) -> ComplianceStandardDefaultExclusion:
    standard = _get_standard_or_404(db, organization_id, standard_id)
    exclusion = db.scalar(
        select(ComplianceStandardDefaultExclusion).where(
            ComplianceStandardDefaultExclusion.standard_id == standard.id,
            ComplianceStandardDefaultExclusion.project_id == project_id,
        )
    )
    if exclusion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This project is not excluded from this standard's default.")
    return exclusion


@router.patch("/standards/{standard_id}/applicability-default", response_model=ComplianceStandardOut)
def update_standard_applicability_default(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardApplicabilityDefaultUpdate,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Switches a standard's default project-assignment mode (Phase 20,
    §3) — Compliance-Manager-only (or org admin/server admin, via
    `require_module_role`'s existing composition), never a Project
    Manager, who may only act on their own project's own assignment row.

    Switching to `APPLIES_TO_ALL_PROJECTS` immediately reconciles a real
    `ProjectCompliance` row into existence for every current, non-archived,
    non-excluded project in this organisation (`service.py::reconcile_
    standard_applicability`) — never a virtual/computed default, since a
    real row is what carries the per-requirement assessment/audit trail
    every other part of this module depends on (§8, §16). Switching back to
    `OPT_IN` reconciles nothing and never retroactively archives rows a
    prior reconciliation created (see `models.py`'s own Phase 20 design-
    decisions section) — idempotent either way (setting the same mode
    twice is a harmless no-op, though re-setting `APPLIES_TO_ALL_PROJECTS`
    still re-runs reconciliation, picking up e.g. a project that was
    created between the two calls without going through the `on_project_
    created` hook for some other reason)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    previous = standard.applicability_default
    standard.applicability_default = payload.applicability_default
    log_event(
        db, entity_type="compliance_standard", entity_id=standard.id, action="applicability_default_changed",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"previous": previous.value, "new": standard.applicability_default.value},
    )
    reconciled: list[ProjectCompliance] = []
    if standard.applicability_default == ComplianceStandardApplicabilityDefault.APPLIES_TO_ALL_PROJECTS:
        reconciled = reconcile_standard_applicability(db, standard=standard, actor_id=current_user.id)
        for project_compliance in reconciled:
            log_event(
                db, entity_type="project_compliance", entity_id=project_compliance.id, action="reconciled",
                actor_id=current_user.id, organization_id=organization_id, project_id=project_compliance.project_id,
                detail={"standard_id": str(standard.id), "reason": "applicability_default_changed"},
            )
            for recipient_id in get_effective_compliance_officers(db, project_compliance.project_id):
                recipient = db.get(User, recipient_id)
                if recipient is None:
                    continue
                notifications.notify(
                    db, recipient, notification_type=NotificationType.COMPLIANCE_ASSIGNMENT_CREATED,
                    title="New compliance assignment",
                    body="This project was automatically assigned to a compliance standard that now applies to "
                         "all projects, and needs assessment to begin.",
                    project_id=project_compliance.project_id, entity_type="project_compliance",
                    entity_id=str(project_compliance.id), actor_id=current_user.id,
                )
    db.commit()
    db.refresh(standard)
    return standard


@router.get("/standards/{standard_id}/exclusions", response_model=list[ComplianceStandardDefaultExclusionOut])
def list_standard_default_exclusions(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists the projects excepted out of this standard's
    `applies_to_all_projects` default (view-gated, same as every other read
    on a standard)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    return db.scalars(
        select(ComplianceStandardDefaultExclusion)
        .where(ComplianceStandardDefaultExclusion.standard_id == standard.id)
        .order_by(ComplianceStandardDefaultExclusion.excluded_at)
    ).all()


@router.post(
    "/standards/{standard_id}/exclusions", response_model=ComplianceStandardDefaultExclusionOut,
    status_code=status.HTTP_201_CREATED,
)
def exclude_project_from_standard_default(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardDefaultExclusionCreate,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Excepts `payload.project_id` out of this standard's
    `applies_to_all_projects` default — `reason` is mandatory (400 if
    blank), mirroring this module's established Not-Applicable/Non-
    Compliant/Rejection mandatory-justification convention (§9, §12, §16).

    If this project currently has a non-archived `ProjectCompliance` row
    against any version of this standard, that row is **archived, not
    deleted** (`models.py:730-735`'s existing soft-delete convention) — the
    assessment history a project may already have recorded against this
    standard must survive being excepted out."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    _get_exclusion_target_project_or_400(db, organization_id, payload.project_id)
    if not payload.reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A reason is required to exclude a project.")
    existing = db.scalar(
        select(ComplianceStandardDefaultExclusion).where(
            ComplianceStandardDefaultExclusion.standard_id == standard.id,
            ComplianceStandardDefaultExclusion.project_id == payload.project_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project is already excluded from this standard's default.")

    exclusion = ComplianceStandardDefaultExclusion(
        standard_id=standard.id, project_id=payload.project_id,
        excluded_by=current_user.id, excluded_at=datetime.now(UTC), reason=payload.reason,
    )
    db.add(exclusion)
    db.flush()
    log_event(
        db, entity_type="compliance_standard_default_exclusion", entity_id=exclusion.id, action="created",
        actor_id=current_user.id, organization_id=organization_id, project_id=payload.project_id,
        detail={"standard_id": str(standard.id), "reason": payload.reason},
    )

    version_ids = db.scalars(
        select(ComplianceStandardVersion.id).where(ComplianceStandardVersion.standard_id == standard.id)
    ).all()
    active_assignments = db.scalars(
        select(ProjectCompliance).where(
            ProjectCompliance.project_id == payload.project_id,
            ProjectCompliance.standard_version_id.in_(version_ids),
            ProjectCompliance.is_archived.is_(False),
        )
    ).all()
    for assignment in active_assignments:
        assignment.is_archived = True
        assignment.archived_at = datetime.now(UTC)
        assignment.archived_by = current_user.id
        log_event(
            db, entity_type="project_compliance", entity_id=assignment.id, action="archived",
            actor_id=current_user.id, organization_id=organization_id, project_id=payload.project_id,
            detail={"reason": "excluded_from_standard_default"},
        )

    db.commit()
    db.refresh(exclusion)
    return exclusion


@router.delete("/standards/{standard_id}/exclusions/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_standard_default_exclusion(
    organization_id: UUID, standard_id: UUID, project_id: UUID,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Removes a project from a standard's exclusion list — if the standard
    is currently `APPLIES_TO_ALL_PROJECTS`, the project is immediately
    reconciled (the same "gets the same treatment at that moment" rule a
    newly-created project gets, `service.py::_reconcile_one_project`).
    Un-excluding a project that isn't excluded 404s (nothing to remove)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    exclusion = _get_exclusion_or_404(db, organization_id, standard_id, project_id)
    db.delete(exclusion)
    log_event(
        db, entity_type="compliance_standard_default_exclusion", entity_id=exclusion.id, action="deleted",
        actor_id=current_user.id, organization_id=organization_id, project_id=project_id,
        detail={"standard_id": str(standard.id)},
    )
    if standard.applicability_default == ComplianceStandardApplicabilityDefault.APPLIES_TO_ALL_PROJECTS:
        project = db.get(Project, project_id)
        if project is not None and not project.is_archived:
            reconciled = _reconcile_one_project(db, project=project, standard=standard, actor_id=current_user.id)
            if reconciled is not None:
                log_event(
                    db, entity_type="project_compliance", entity_id=reconciled.id, action="reconciled",
                    actor_id=current_user.id, organization_id=organization_id, project_id=project_id,
                    detail={"standard_id": str(standard.id), "reason": "exclusion_removed"},
                )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
