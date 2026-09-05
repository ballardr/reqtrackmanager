"""
Module: modules.compliance.router

The Compliance Module's Phase 6 "Standards Management API"
(docs/compliance-module-plan.md Phase 6; docs/Compliance_Module_Requirements.md
§2, §3, §4, §26) — full CRUD for compliance standards, their versions,
hierarchical requirements, and required actions, plus an organisation-scoped
required-action-type vocabulary, and the publish/retire version lifecycle.

Responsibilities:
- Mount every endpoint under `/api/v1/orgs/{organization_id}/modules/
  compliance` — the exact prefix `app.modules.registry.McpToolDefinition`'s
  own docstring already names as the intended shape for this module's
  eventual router, so this file doesn't deviate from it.
- Enforce the org-admin/compliance-manager split §3/§26 require: every
  mutating endpoint is gated by `require_module_role("compliance",
  "compliance_manager")`, which (per `services.rbac.require_module_role`'s
  own composition, already built and covered by Phase 2's own tests) also
  passes for `is_server_admin` and `OrgRole.ORG_ADMIN` on the named
  organisation — Phase 6 does not reimplement that override, it only needs
  to prove it applies here too (see `backend/tests/
  test_compliance_standards_api.py`'s RBAC-composition tests). Every read
  endpoint is gated by the weaker `require_org_module_enabled("compliance")`
  — any org member with the module enabled may view standards, since §26
  doesn't restrict *viewing* standards to Compliance Manager (only
  managing them), and Phase 7's project members will eventually need to
  browse/assign standards too.
- Enforce §4's versioning/publish/retire lifecycle: a `DRAFT` version's
  requirements and required actions may be freely created/edited/deleted/
  reordered; once a version is `PUBLISHED` (or `RETIRED`), all four of
  those operations 409 — "a published version's requirements become
  immutable... changes require a new version" (§4). No endpoint here lets
  a version go backwards (published -> draft) or deletes a version at all
  — every version, published or retired, stays permanently addressable
  (Phase 5's own design decision; see `models.py`'s module docstring).
- Log every mutation via `services.audit.log_event`, before the single
  `db.commit()` each endpoint makes — never a second, separate commit.
- Verify, on every endpoint that names a standard/version/requirement/
  required-action by id in the path, that the referenced row actually
  belongs to the `organization_id` in the path (transitively, through its
  parent chain) — returning **404, not 403**, on a cross-org reference,
  mirroring `routers.action_types`' own "wrong scope -> 404" precedent
  (`action_type.project_id != project.id` -> `404 "Action type not
  found."`) rather than confirming a resource's existence to a caller with
  no access to its owning organisation at all.

Design decisions recorded in full in docs/compliance-module-plan.md's
"Phase 6 notes" (exact path segments, the version-cloning mechanism, the
flat-with-parent-id requirement listing shape, the reference-immutability
call, and every audit action-name string chosen) — this docstring gives the
short version; that document is authoritative for the reasoning.

External dependencies: `app.services.rbac` (module-role/module-enabled
gating), `app.services.audit` (mutation logging), `app.services.ordering`
(sibling reordering), `app.services.definitions` (action-type delete-with-
reassignment) — every one of these is reused, not reimplemented, per this
repo's CLAUDE.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import (
    ComplianceActionTypeDefinition,
    ComplianceRequiredAction,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
)
from app.modules.compliance.schemas import (
    ComplianceActionTypeCreate,
    ComplianceActionTypeOut,
    ComplianceActionTypeUpdate,
    ComplianceRequiredActionCreate,
    ComplianceRequiredActionOut,
    ComplianceRequiredActionUpdate,
    ComplianceRequirementCreate,
    ComplianceRequirementOut,
    ComplianceRequirementUpdate,
    ComplianceStandardCreate,
    ComplianceStandardOut,
    ComplianceStandardUpdate,
    ComplianceStandardVersionCreate,
    ComplianceStandardVersionOut,
    ProjectComplianceCreate,
    ProjectComplianceOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import build_status_out, materialize_assessment_rows
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered
from app.services.rbac import require_module_role, require_org_module_enabled

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/compliance", tags=["compliance"])

# Dependency factories are called once, at router-definition time, per this
# codebase's established convention (`orgs.py`'s `require_org_role(...)`
# calls, `action_types.py`'s `require_project_manage`/`require_project_view`)
# — not re-constructed per request.
_require_manage = require_module_role("compliance", "compliance_manager")
_require_view = require_org_module_enabled("compliance")


# --- Cross-org ownership-chain lookups (404, not 403, on a mismatch) --------
#
# Every helper below mirrors `routers.action_types`' own precedent exactly:
# `action_type is None or action_type.project_id != project.id` -> 404. A
# wrong-org reference must be indistinguishable from a nonexistent one to a
# caller with no access to the owning organisation at all.


def _get_standard_or_404(db: Session, organization_id: UUID, standard_id: UUID) -> ComplianceStandard:
    standard = db.get(ComplianceStandard, standard_id)
    if standard is None or standard.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard not found.")
    return standard


def _get_version_or_404(
    db: Session, organization_id: UUID, standard_id: UUID, version_id: UUID
) -> tuple[ComplianceStandard, ComplianceStandardVersion]:
    standard = _get_standard_or_404(db, organization_id, standard_id)
    version = db.get(ComplianceStandardVersion, version_id)
    if version is None or version.standard_id != standard.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard version not found.")
    return standard, version


def _get_requirement_or_404(
    db: Session, organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID
) -> tuple[ComplianceStandard, ComplianceStandardVersion, ComplianceRequirement]:
    standard, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    requirement = db.get(ComplianceRequirement, requirement_id)
    if requirement is None or requirement.standard_version_id != version.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    return standard, version, requirement


def _get_required_action_or_404(
    db: Session,
    organization_id: UUID,
    standard_id: UUID,
    version_id: UUID,
    requirement_id: UUID,
    action_id: UUID,
) -> tuple[ComplianceStandard, ComplianceStandardVersion, ComplianceRequirement, ComplianceRequiredAction]:
    standard, version, requirement = _get_requirement_or_404(
        db, organization_id, standard_id, version_id, requirement_id
    )
    action = db.get(ComplianceRequiredAction, action_id)
    if action is None or action.requirement_id != requirement.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance required action not found.")
    return standard, version, requirement, action


def _require_draft_version(version: ComplianceStandardVersion) -> None:
    """Enforces §4's "a published version's requirements become immutable":
    creating, editing, deleting, or reordering a requirement or required
    action under a non-draft version 409s. Applied uniformly to *every*
    content mutation under a version (create/update/delete/move alike) —
    see docs/compliance-module-plan.md's Phase 6 notes for why `move` is
    included even though the spec text only explicitly names create/
    update/delete: reordering is still a mutation of the version's content,
    and letting it slip through would silently alter what a published
    version presents even though no single requirement's own fields
    changed."""
    if version.status != ComplianceStandardVersionStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This standard version is no longer a draft; its requirements and required actions are immutable. "
            "Create a new version to make changes.",
        )


# --- Standards ---------------------------------------------------------------


@router.post("/standards", response_model=ComplianceStandardOut, status_code=status.HTTP_201_CREATED)
def create_standard(
    organization_id: UUID, payload: ComplianceStandardCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new organisation-level compliance standard (§2). `owner_id`
    defaults to the creating user when omitted."""
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


@router.patch("/standards/{standard_id}", response_model=ComplianceStandardOut)
def update_standard(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
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
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
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
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
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


# --- Standard versions ---------------------------------------------------------


def _clone_requirement_tree(
    db: Session, *, source_version_id: UUID, new_version_id: UUID, creator_id: UUID
) -> None:
    """Deep-copies `source_version_id`'s full `ComplianceRequirement` tree
    (preserving parent/child structure via an old-id -> new-id remap) and
    each requirement's `ComplianceRequiredAction`s into `new_version_id`.

    Used by `create_standard_version` when `clone_from_version_id` is given
    — see that endpoint's docstring for why this exists. Processes
    requirements breadth-first from the roots down (`_clone_level`,
    recursive), so a child is never cloned before its own remapped parent
    id exists to point at."""
    source_requirements = db.scalars(
        select(ComplianceRequirement)
        .where(ComplianceRequirement.standard_version_id == source_version_id)
        .order_by(ComplianceRequirement.sort_order)
    ).all()
    children_by_parent: dict[uuid.UUID | None, list[ComplianceRequirement]] = {}
    for req in source_requirements:
        children_by_parent.setdefault(req.parent_requirement_id, []).append(req)

    def _clone_level(parent_old_id: uuid.UUID | None, parent_new_id: uuid.UUID | None) -> None:
        for old_req in children_by_parent.get(parent_old_id, []):
            new_req = ComplianceRequirement(
                standard_version_id=new_version_id,
                parent_requirement_id=parent_new_id,
                reference=old_req.reference,
                name=old_req.name,
                description=old_req.description,
                reasoning=old_req.reasoning,
                sort_order=old_req.sort_order,
                created_by=creator_id,
            )
            db.add(new_req)
            db.flush()

            old_actions = db.scalars(
                select(ComplianceRequiredAction)
                .where(ComplianceRequiredAction.requirement_id == old_req.id)
                .order_by(ComplianceRequiredAction.sort_order)
            ).all()
            for old_action in old_actions:
                db.add(
                    ComplianceRequiredAction(
                        requirement_id=new_req.id,
                        action_type_id=old_action.action_type_id,
                        name=old_action.name,
                        description=old_action.description,
                        is_mandatory=old_action.is_mandatory,
                        sort_order=old_action.sort_order,
                        created_by=creator_id,
                    )
                )

            _clone_level(old_req.id, new_req.id)

    _clone_level(None, None)


@router.post(
    "/standards/{standard_id}/versions", response_model=ComplianceStandardVersionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_standard_version(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardVersionCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new (always `DRAFT`) version of a standard (§4).
    `version_number` is always the next sequential number for this
    standard — never caller-supplied.

    `clone_from_version_id`, when given, deep-copies that version's full
    requirement tree and required actions into the new draft version. This
    is a deliberate Phase 6 design decision beyond what the plan's own spec
    text spells out: §4 requires that "changes to a standard should result
    in a new version rather than modifying requirements historical
    assessments depend upon," but without a way to version existing content
    forward, every new version would have to be rebuilt from scratch,
    defeating the point of versioning an evolving standard rather than
    starting over each time."""
    standard = _get_standard_or_404(db, organization_id, standard_id)

    last_version_number = db.scalar(
        select(ComplianceStandardVersion.version_number)
        .where(ComplianceStandardVersion.standard_id == standard.id)
        .order_by(ComplianceStandardVersion.version_number.desc())
        .limit(1)
    )
    next_version_number = (last_version_number or 0) + 1

    version = ComplianceStandardVersion(
        standard_id=standard.id,
        version_number=next_version_number,
        version_label=payload.version_label,
        effective_date=payload.effective_date,
        change_note=payload.change_note,
        created_by=current_user.id,
    )
    db.add(version)
    db.flush()

    if payload.clone_from_version_id is not None:
        _, source_version = _get_version_or_404(db, organization_id, standard_id, payload.clone_from_version_id)
        _clone_requirement_tree(
            db, source_version_id=source_version.id, new_version_id=version.id, creator_id=current_user.id
        )

    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"version_label": version.version_label, "cloned_from": str(payload.clone_from_version_id)
                      if payload.clone_from_version_id else None})
    db.commit()
    db.refresh(version)
    return version


@router.get("/standards/{standard_id}/versions", response_model=list[ComplianceStandardVersionOut])
def list_standard_versions(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a standard's versions, ordered by `version_number` — every
    version, published or retired, remains listed (Phase 5's "never
    superseded/deleted" design)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    return db.scalars(
        select(ComplianceStandardVersion)
        .where(ComplianceStandardVersion.standard_id == standard.id)
        .order_by(ComplianceStandardVersion.version_number)
    ).all()


@router.get("/standards/{standard_id}/versions/{version_id}", response_model=ComplianceStandardVersionOut)
def get_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single standard version."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    return version


@router.post(
    "/standards/{standard_id}/versions/{version_id}/publish", response_model=ComplianceStandardVersionOut
)
def publish_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Publishes a `DRAFT` version (§4) — after this, its requirements and
    required actions become immutable (`_require_draft_version`). 409 if
    the version isn't currently `DRAFT` (already published or retired)."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    if version.status != ComplianceStandardVersionStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft version can be published.")
    version.status = ComplianceStandardVersionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    version.published_by = current_user.id
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="published",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(version)
    return version


@router.post(
    "/standards/{standard_id}/versions/{version_id}/retire", response_model=ComplianceStandardVersionOut
)
def retire_standard_version(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Retires a version — from either `DRAFT` or `PUBLISHED` (§4). 409 if
    already retired. A retired version is never deleted and stays
    addressable indefinitely (Phase 5's own design)."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    if version.status == ComplianceStandardVersionStatus.RETIRED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This version is already retired.")
    version.status = ComplianceStandardVersionStatus.RETIRED
    version.retired_at = datetime.now(UTC)
    version.retired_by = current_user.id
    log_event(db, entity_type="compliance_standard_version", entity_id=version.id, action="retired",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(version)
    return version


# --- Requirements ----------------------------------------------------------------


def _flatten_requirements_dfs(requirements: list[ComplianceRequirement]) -> list[ComplianceRequirement]:
    """Orders a version's requirements as a flat list in depth-first,
    parent-before-children order (each sibling group internally ordered by
    its own `sort_order`) — a flat list with `parent_requirement_id`
    populated, matching how this codebase already returns other
    parent-referencing hierarchies flatly rather than pre-nesting them
    server-side, while still presenting them in a sensible reading order
    rather than an arbitrary one."""
    children_by_parent: dict[uuid.UUID | None, list[ComplianceRequirement]] = {}
    for req in requirements:
        children_by_parent.setdefault(req.parent_requirement_id, []).append(req)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda r: r.sort_order)

    ordered: list[ComplianceRequirement] = []

    def _visit(parent_id: uuid.UUID | None) -> None:
        for req in children_by_parent.get(parent_id, []):
            ordered.append(req)
            _visit(req.id)

    _visit(None)
    return ordered


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements",
    response_model=ComplianceRequirementOut, status_code=status.HTTP_201_CREATED,
)
def create_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, payload: ComplianceRequirementCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a requirement under a version (§5). 409 if the version is no
    longer a draft. `sort_order` is always append-to-end within the
    requirement's sibling group (same `standard_version_id` AND same
    `parent_requirement_id` — top-level requirements and each parent's own
    children are each their own separately-ordered sibling group)."""
    standard, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    _require_draft_version(version)

    parent_id = payload.parent_requirement_id
    if parent_id is not None:
        parent = db.get(ComplianceRequirement, parent_id)
        if parent is None or parent.standard_version_id != version.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_requirement_id must be a requirement in this version.")

    count = len(
        db.scalars(
            select(ComplianceRequirement.id).where(
                ComplianceRequirement.standard_version_id == version.id,
                ComplianceRequirement.parent_requirement_id == parent_id,
            )
        ).all()
    )
    requirement = ComplianceRequirement(
        standard_version_id=version.id,
        parent_requirement_id=parent_id,
        reference=payload.reference,
        name=payload.name,
        description=payload.description,
        reasoning=payload.reasoning,
        sort_order=count,
        created_by=current_user.id,
    )
    db.add(requirement)
    db.flush()
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"name": requirement.name})
    db.commit()
    db.refresh(requirement)
    return requirement


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements", response_model=list[ComplianceRequirementOut]
)
def list_requirements(
    organization_id: UUID, standard_id: UUID, version_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a version's requirements as a flat, depth-first-ordered list
    with `parent_requirement_id` populated (§5's hierarchy) — see
    `_flatten_requirements_dfs`."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    requirements = db.scalars(
        select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
    ).all()
    return _flatten_requirements_dfs(list(requirements))


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    response_model=ComplianceRequirementOut,
)
def get_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single requirement."""
    _, _, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    return requirement


@router.patch(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    response_model=ComplianceRequirementOut,
)
def update_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    payload: ComplianceRequirementUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Updates a requirement's reference/name/description/reasoning. 409 if
    the owning version is no longer a draft. Does not support reparenting
    — see `schemas.py`'s module docstring."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    requirement.reference = payload.reference
    requirement.name = payload.name
    requirement.description = payload.description
    requirement.reasoning = payload.reasoning
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": requirement.name})
    db.commit()
    db.refresh(requirement)
    return requirement


@router.delete(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Deletes a requirement (and, via the database's own `ON DELETE
    CASCADE`, its child requirements and their required actions — no
    manual cascade code needed, per Phase 5's schema). 409 if the owning
    version is no longer a draft."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    log_event(db, entity_type="compliance_requirement", entity_id=requirement.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": requirement.name})
    db.delete(requirement)
    db.commit()


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/move",
    response_model=ComplianceRequirementOut,
)
def move_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Moves a requirement up/down among its siblings — same
    `standard_version_id` AND same `parent_requirement_id`. 409 if the
    owning version is no longer a draft (see `_require_draft_version`'s
    docstring for why reordering is treated as a content mutation too)."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)
    result = move_ordered(
        db, ComplianceRequirement,
        [
            ComplianceRequirement.standard_version_id == version.id,
            ComplianceRequirement.parent_requirement_id == requirement.parent_requirement_id,
        ],
        requirement_id, payload.direction,
    )
    log_event(db, entity_type="compliance_requirement", entity_id=requirement_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


# --- Required actions --------------------------------------------------------------


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions",
    response_model=ComplianceRequiredActionOut, status_code=status.HTTP_201_CREATED,
)
def create_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    payload: ComplianceRequiredActionCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a required action under a requirement (§6). 409 if the
    owning version is no longer a draft. `action_type_id` must be an
    organisation-scoped `ComplianceActionTypeDefinition` belonging to this
    same organisation."""
    _, version, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    _require_draft_version(version)

    action_type = db.get(ComplianceActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type in this organisation.")

    count = len(
        db.scalars(
            select(ComplianceRequiredAction.id).where(ComplianceRequiredAction.requirement_id == requirement.id)
        ).all()
    )
    action = ComplianceRequiredAction(
        requirement_id=requirement.id,
        action_type_id=payload.action_type_id,
        name=payload.name,
        description=payload.description,
        is_mandatory=payload.is_mandatory,
        sort_order=count,
        created_by=current_user.id,
    )
    db.add(action)
    db.flush()
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.commit()
    db.refresh(action)
    return action


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions",
    response_model=list[ComplianceRequiredActionOut],
)
def list_required_actions(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a requirement's required actions, ordered by `sort_order`."""
    _, _, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    return db.scalars(
        select(ComplianceRequiredAction)
        .where(ComplianceRequiredAction.requirement_id == requirement.id)
        .order_by(ComplianceRequiredAction.sort_order)
    ).all()


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    response_model=ComplianceRequiredActionOut,
)
def get_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single required action."""
    _, _, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    return action


@router.patch(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    response_model=ComplianceRequiredActionOut,
)
def update_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    payload: ComplianceRequiredActionUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Updates a required action's action type/name/description/
    is_mandatory. 409 if the owning version is no longer a draft."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)

    action_type = db.get(ComplianceActionTypeDefinition, payload.action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_type_id must be an action type in this organisation.")

    action.action_type_id = payload.action_type_id
    action.name = payload.name
    action.description = payload.description
    action.is_mandatory = payload.is_mandatory
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.commit()
    db.refresh(action)
    return action


@router.delete(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Deletes a required action. 409 if the owning version is no longer a
    draft. No manual cascade needed for its `action_type_id` FK (implicit
    RESTRICT, not CASCADE, per Phase 5's schema) — deleting the required
    action itself is unaffected by that."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)
    log_event(db, entity_type="compliance_required_action", entity_id=action.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action.name})
    db.delete(action)
    db.commit()


@router.post(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions/{action_id}/move",
    response_model=ComplianceRequiredActionOut,
)
def move_required_action(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID, action_id: UUID,
    payload: MoveDirection,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Moves a required action up/down among its siblings (same
    `requirement_id`). 409 if the owning version is no longer a draft."""
    _, version, _, action = _get_required_action_or_404(
        db, organization_id, standard_id, version_id, requirement_id, action_id
    )
    _require_draft_version(version)
    result = move_ordered(
        db, ComplianceRequiredAction, [ComplianceRequiredAction.requirement_id == requirement_id],
        action_id, payload.direction,
    )
    log_event(db, entity_type="compliance_required_action", entity_id=action_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


# --- Action types (organisation-scoped vocabulary) ------------------------------


@router.post("/action-types", response_model=ComplianceActionTypeOut, status_code=status.HTTP_201_CREATED)
def create_action_type(
    organization_id: UUID, payload: ComplianceActionTypeCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a new organisation-scoped required-action type (§6)."""
    existing = db.scalar(
        select(ComplianceActionTypeDefinition.id).where(
            ComplianceActionTypeDefinition.organization_id == organization_id,
            ComplianceActionTypeDefinition.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    count = len(
        db.scalars(
            select(ComplianceActionTypeDefinition.id).where(
                ComplianceActionTypeDefinition.organization_id == organization_id
            )
        ).all()
    )
    action_type = ComplianceActionTypeDefinition(organization_id=organization_id, name=payload.name, sort_order=count)
    db.add(action_type)
    db.flush()
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": action_type.name})
    db.commit()
    db.refresh(action_type)
    return action_type


@router.get("/action-types", response_model=list[ComplianceActionTypeOut])
def list_action_types(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this organisation's required-action types — any org member
    with the module enabled may select one when authoring a required
    action, so listing isn't manage-only."""
    return db.scalars(
        select(ComplianceActionTypeDefinition)
        .where(ComplianceActionTypeDefinition.organization_id == organization_id)
        .order_by(ComplianceActionTypeDefinition.sort_order)
    ).all()


@router.post("/action-types/{action_type_id}/move", response_model=ComplianceActionTypeOut)
def move_action_type(
    organization_id: UUID, action_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Moves an action type up/down in display order."""
    result = move_ordered(
        db, ComplianceActionTypeDefinition,
        [ComplianceActionTypeDefinition.organization_id == organization_id], action_type_id, payload.direction,
    )
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/action-types/{action_type_id}", response_model=ComplianceActionTypeOut)
def rename_action_type(
    organization_id: UUID, action_type_id: UUID, payload: ComplianceActionTypeUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Renames an action type. Every `ComplianceRequiredAction.
    action_type_id` reference points at this row's id, never its name, so
    renaming has zero effect on existing required actions."""
    action_type = db.get(ComplianceActionTypeDefinition, action_type_id)
    if action_type is None or action_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action type not found.")
    existing = db.scalar(
        select(ComplianceActionTypeDefinition.id).where(
            ComplianceActionTypeDefinition.organization_id == organization_id,
            ComplianceActionTypeDefinition.name == payload.name,
            ComplianceActionTypeDefinition.id != action_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An action type with this name already exists.")
    action_type.name = payload.name
    log_event(db, entity_type="compliance_action_type_definition", entity_id=action_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(action_type)
    return action_type


@router.delete("/action-types/{action_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_type(
    organization_id: UUID, action_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Deletes an organisation-scoped action type, applying the shared
    rename/delete/reassign rules (`services.definitions`). Unlike project-
    scoped `ActionTypeDefinition`, there is no "must always retain at least
    one" floor here — an organisation's compliance action-type vocabulary
    may be emptied to zero (§6 doesn't require a non-empty minimum the way
    a project's requirement-action-type picker does), so `allow_empty=True`
    unconditionally. Requires an explicit `reassign_to_id` to delete a type
    currently in use by any `ComplianceRequiredAction` (409 naming the
    count if omitted; bulk-reassigns then deletes if provided)."""
    delete_definition_with_reassignment(
        db, definition_model=ComplianceActionTypeDefinition,
        scope_column=ComplianceActionTypeDefinition.organization_id, scope_id=organization_id,
        item_id=action_type_id, reassign_to_id=reassign_to_id,
        referencing_model=ComplianceRequiredAction, referencing_fk_column=ComplianceRequiredAction.action_type_id,
        referencing_fk_name="action_type_id", entity_type="compliance_action_type_definition", noun="action type",
        plural_noun="required action(s)", reassign_verb="move",
        min_count_message="",  # unreachable: allow_empty=True skips the floor check that would use this
        actor_id=current_user.id, organization_id=organization_id, project_id=None,
        allow_empty=True,
    )
    db.commit()


# --- Project compliance assignment (org-scoped: assigning IS a Compliance -------
# Manager decision, §26; day-to-day assessment lives on `project_router.py`
# instead, since Phase 4's MCP tool scoping rule requires `project_id` as
# the *only* path placeholder for `compliance_get_project_status`/
# `compliance_list_non_compliant_requirements` — impossible on a route that
# also carries `{organization_id}`. See docs/compliance-module-plan.md's
# Phase 7 notes for the full reasoning behind this split.)


def _get_project_or_404(db: Session, organization_id: UUID, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get_project_compliance_or_404(
    db: Session, organization_id: UUID, project_id: UUID, project_compliance_id: UUID
) -> ProjectCompliance:
    _get_project_or_404(db, organization_id, project_id)
    project_compliance = db.get(ProjectCompliance, project_compliance_id)
    if project_compliance is None or project_compliance.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project compliance assignment not found.")
    return project_compliance


@router.post(
    "/projects/{project_id}/project-compliance", response_model=ProjectComplianceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_compliance(
    organization_id: UUID, project_id: UUID, payload: ProjectComplianceCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Assigns a compliance standard version to a project (§7) — a
    Compliance Manager decision (module.py's own role description; §26
    doesn't list this as a Project Manager/Compliance Officer capability).
    Only a `PUBLISHED` version may be assigned (409 otherwise) — see
    `models.py`'s own docstring for why. Materialises the full per-
    requirement/per-required-action assessment row set for this
    assignment in the same transaction (`service.materialize_assessment_
    rows`) — see that function's own docstring for why this happens once,
    upfront, rather than lazily."""
    _get_project_or_404(db, organization_id, project_id)
    _, version = _get_version_or_404(db, organization_id, payload.standard_id, payload.standard_version_id)
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
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id,
              detail={"standard_version_id": str(version.id)})
    db.commit()
    db.refresh(project_compliance)
    return project_compliance


@router.get("/project-compliance", response_model=list[ProjectComplianceStatusOut])
def list_all_project_compliance(
    organization_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Lists every `ProjectCompliance` assignment across this
    organisation's projects, each with its computed §20 overall status —
    the Compliance Manager's "View compliance across projects" capability
    (§26). Manage-gated, not view-gated: §26 lists this specifically under
    Compliance Manager, not under any project role or general org
    membership."""
    query = (
        select(ProjectCompliance)
        .join(Project, Project.id == ProjectCompliance.project_id)
        .where(Project.organization_id == organization_id)
    )
    if not include_archived:
        query = query.where(ProjectCompliance.is_archived.is_(False))
    assignments = db.scalars(query).all()
    return [build_status_out(db, pc) for pc in assignments]


@router.post(
    "/projects/{project_id}/project-compliance/{project_compliance_id}/archive",
    response_model=ProjectComplianceOut,
)
def archive_project_compliance(
    organization_id: UUID, project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Soft-archives a project's assignment to a standard — used when a
    project no longer needs to track compliance against it. Never a hard
    delete: the `ProjectComplianceRequirement` rows underneath carry real
    assessment/audit history (§16) that must survive this."""
    project_compliance = _get_project_compliance_or_404(db, organization_id, project_id, project_compliance_id)
    project_compliance.is_archived = True
    project_compliance.archived_at = datetime.now(UTC)
    project_compliance.archived_by = current_user.id
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id)
    db.commit()
    db.refresh(project_compliance)
    return project_compliance


@router.post(
    "/projects/{project_id}/project-compliance/{project_compliance_id}/unarchive",
    response_model=ProjectComplianceOut,
)
def unarchive_project_compliance(
    organization_id: UUID, project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Restores an archived project compliance assignment. Idempotent."""
    project_compliance = _get_project_compliance_or_404(db, organization_id, project_id, project_compliance_id)
    project_compliance.is_archived = False
    project_compliance.archived_at = None
    project_compliance.archived_by = None
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id)
    db.commit()
    db.refresh(project_compliance)
    return project_compliance
