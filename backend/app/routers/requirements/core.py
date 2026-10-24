"""
Module: routers.requirements.core

Base CRUD for requirements (create/list/import/export/get/update/delete/
restore), version history, activity, and scoping-stage reordering (C-E-03).

Also home for the shared private helpers used across the `requirements`
package's other bucket files: `_get_requirement_in_project`,
`_require_edit_role`, `_to_out`, and `_has_open_change_request` (the last
used only from inside `_to_out`'s own body). Every other sub-file that needs
one of the first three imports it directly from here rather than
duplicating it.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.metrics import (
    requirements_archived_total,
    requirements_created_total,
    requirements_updated_total,
)
from app.models.change_request import ChangeRequest
from app.models.custom_field import CustomFieldEntityKind
from app.models.enums import (
    ProjectRole,
    RequirementStatus,
    ReviewTargetType,
    StageStatus,
)
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.schemas.changes import ChangeEntryOut
from app.schemas.project import MoveDirection
from app.schemas.requirement import (
    RequirementCreate,
    RequirementOut,
    RequirementUpdate,
    RequirementVersionOut,
)
from app.services import engagement, pubsub
from app.services.audit import log_event
from app.services.changes import get_project_changes
from app.services.custom_fields import validate_custom_field_values
from app.services.principals import validate_principal
from app.services.project_scope import ProjectScope
from app.services.rbac import get_effective_project_roles, require_project_view
from app.services.requirements import (
    OPEN_CR_STATUSES,
    ListPrefetch,
    RequirementFilters,
    archive_requirement,
    create_requirement,
    edit_requirement,
    filter_requirements,
    get_current_version,
    get_keywords,
    is_locked,
    unarchive_requirement,
    version_people,
)

router = APIRouter(tags=["requirements-core"])

CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_edit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds a requirement-editing role on the project.

    No server-admin bypass (I-M-05): requirement content is "data within
    organisations".
    """
    if not get_effective_project_roles(db, user.id, project_id) & set(CAN_EDIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


REQUIRES_APPROVAL_STATUSES = {RequirementStatus.DRAFT, RequirementStatus.REVIEWED}


def _has_open_change_request(db: Session, requirement_id: UUID) -> bool:
    return (
        db.scalar(
            select(ChangeRequest.id).where(
                ChangeRequest.requirement_id == requirement_id, ChangeRequest.status.in_(OPEN_CR_STATUSES)
            )
        )
        is not None
    )


def _to_out(
    db: Session, requirement: Requirement, version: RequirementVersion, current_user_id: UUID,
    prefetch: ListPrefetch | None = None,
) -> RequirementOut:
    """Builds the API response shape for a requirement from its identity row
    plus one version snapshot, including `current_user_id`'s subscription
    state (C-N-01) and derived list-view badge indicators. Pass `prefetch`
    (from `prefetch_for_list`) when serialising many rows, so these come
    from batched lookups instead of per-row queries."""
    if prefetch is not None:
        people = prefetch.people
        keywords = prefetch.keywords.get(requirement.id, [])
        subscribed = requirement.id in prefetch.subscribed
        comment_count = prefetch.comment_counts.get(requirement.id, 0)
        open_cr = requirement.id in prefetch.open_change_request
    else:
        people = version_people(db, [version])
        keywords = get_keywords(db, requirement.id)
        subscribed = engagement.is_subscribed(db, current_user_id, "requirement", requirement.id)
        comment_count = engagement.get_comment_count(db, ReviewTargetType.REQUIREMENT, requirement.id)
        open_cr = _has_open_change_request(db, requirement.id)
    return RequirementOut(
        id=requirement.id, project_id=requirement.project_id, unique_code=requirement.unique_code,
        name=version.name, reasoning=version.reasoning, clarification=version.clarification,
        description=version.description,
        status=version.status, owner=people[(version.owner_type, version.owner_id)], component_id=requirement.component_id,
        category_id=requirement.category_id, target_stage_id=version.target_stage_id, level=version.level,
        sort_order=version.sort_order, creator_id=requirement.creator_id,
        is_archived=requirement.is_archived, is_locked=is_locked(version),
        is_completed=requirement.is_completed, completed_at=requirement.completed_at,
        completed_by=requirement.completed_by,
        keywords=keywords, custom_fields=version.custom_fields,
        created_at=requirement.created_at, updated_at=version.created_at,
        is_subscribed=subscribed,
        comment_count=comment_count,
        has_open_change_request=open_cr,
        requires_approval=version.status in REQUIRES_APPROVAL_STATUSES,
        review_date=version.review_date, review_lead_days=version.review_lead_days,
        reviewer=people[(version.reviewer_type, version.reviewer_id)] if version.reviewer_id else None,
    )


@router.post("", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
def create_requirement_endpoint(
    project_id: UUID, payload: RequirementCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a requirement (C-G-02). Requires stakeholder/administrator/manager."""
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    component = db.get(ProjectComponent, payload.component_id)
    category = db.get(ProjectCategory, payload.category_id)
    if project is None or component is None or component.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid component.")
    if category is None or category.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid category.")
    if category.component_id != component.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category does not belong to the selected component.")

    target_stage_id = payload.target_stage_id
    if target_stage_id is None:
        # Not left unset: default to the project's own earliest stage (by
        # sort_order), the same backfill convention migration 0004 and CSV
        # import use — see RequirementCreate.target_stage_id's docstring.
        default_stage = db.scalar(
            select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order.asc())
        )
        if default_stage is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project has no stages; target_stage_id is required.")
        target_stage_id = default_stage.id
    else:
        stage = db.get(ProjectStage, target_stage_id)
        if stage is None or stage.project_id != project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid target_stage_id.")

    custom_fields = validate_custom_field_values(db, project_id, CustomFieldEntityKind.REQUIREMENT, payload.custom_fields)
    for person_field in ("owner", "reviewer"):
        validate_principal(
            db, getattr(payload, person_field), organization_id=project.organization_id, project_id=project_id,
            field=person_field,
        )

    creator_override_id = None
    if payload.creator_id is not None:
        # PM re-attributing authorship at creation time (C-A-11).
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can assign the creator.")
        creator_override_id = payload.creator_id

    count = len(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    requirement = create_requirement(
        db, project, component, category, current_user,
        name=payload.name, reasoning=payload.reasoning, clarification=payload.clarification,
        description=payload.description,
        owner=payload.owner, keywords=payload.keywords, sort_order=count,
        target_stage_id=target_stage_id, level=payload.level,
        custom_fields=custom_fields, creator_override_id=creator_override_id,
        review_date=payload.review_date, review_lead_days=payload.review_lead_days, reviewer=payload.reviewer,
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="created",
              actor_id=current_user.id, project_id=project_id)
    requirements_created_total.inc()
    db.commit()
    db.refresh(requirement)
    version = get_current_version(db, requirement.id)
    pubsub.notify(project_id, {"type": "requirement", "action": "created", "id": str(requirement.id)})
    return _to_out(db, requirement, version, current_user.id)


@router.get("", response_model=list[RequirementOut])
def list_requirements(
    project_id: UUID,
    response: Response,
    component_id: UUID | None = None,
    category_id: UUID | None = None,
    keyword: str | None = None,
    tag: list[str] = Query([], description="Only requirements carrying these tags (case-insensitive)."),
    tag_mode: Literal["any", "all"] = Query("any", description="Whether a requirement needs any or all of the `tag`s."),
    search: str | None = None,
    status_filter: RequirementStatus | None = Query(None, alias="status"),
    is_completed: bool | None = None,
    target_stage_id: UUID | None = None,
    has_comments: bool | None = None,
    only_watched: bool | None = None,
    include_archived: bool = False,
    sort: str | None = Query(None, pattern="^(unique_code|name|status|created_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists requirements, sorted by component/category (C-G-04) with search (U-E-01)
    and filter-panel query params (status/completed/target version/comments/watched).

    `is_completed` filters on the `Requirement.is_completed` overlay marker
    (C-G-11) independently of `status` — completion is no longer a
    `RequirementStatus` value, so it's its own boolean query param rather
    than a `status` option, matching the frontend's separate "Completed"
    `FilterCheckbox` alongside the status `<select>`.

    `limit`/`offset` (U-P-06) are optional: omitting both returns every
    matching requirement, unchanged from before pagination existed (C-G-05:
    no artificial limit is ever imposed unless the caller asks for a page).
    When `limit` is given, the total match count (before slicing) is
    returned in the `X-Total-Count` response header so a client can tell
    whether more pages remain.

    `sort` optionally overrides the default component/category/manual-
    order sort below with a single-column sort by `unique_code`, `name`,
    `status`, or `created_at`; `order` picks `asc` (default) or `desc`.
    Omitting `sort` leaves the existing default ordering completely
    unchanged, so this is additive, not a breaking change to callers that
    don't ask for it.

    `X-Total-Unfiltered-Count` is a second response header reporting the
    count within only the mandatory project + default archived-visibility
    scope, before component/category/search/status/completed/stage/comments/
    watched filters below narrow it further — unlike `X-Total-Count`, it does not
    change when the caller adds a filter or search term, so the frontend
    can show "12 matching · 57 total" instead of just a bare filtered count.

    `project_scope` (`parents`/`children`/`both`) adds the requirements of the related projects
    the caller can open (`services.project_scope`); rows from another project carry
    `from_project_*`, the counts above cover every project listed, and project-local filters
    (component, category, target stage) only match rows of the project they belong to.
    """
    unfiltered = 0

    filters = RequirementFilters(
        include_archived=include_archived, is_completed=is_completed, component_id=component_id, category_id=category_id,
        tag_names=tuple(tag), tag_match_all=tag_mode == "all", keyword=keyword, search=search, status=status_filter,
        target_stage_id=target_stage_id, has_comments=has_comments, only_watched=only_watched,
    )

    def rows_for(pid: UUID) -> list[RequirementOut]:
        nonlocal unfiltered
        found = filter_requirements(db, pid, current_user.id, filters, structural_order=not sort)
        unfiltered += found.unfiltered
        prefetch = found.prefetch
        return [_to_out(db, req, prefetch.versions[req.id], current_user.id, prefetch) for req in found.requirements]

    out = project_scope.collect(db, db.get(Project, project_id), current_user.id, "requirement", rows_for)
    response.headers["X-Total-Unfiltered-Count"] = str(unfiltered)

    if sort:
        def _sort_value(item: RequirementOut):
            value = getattr(item, sort)
            return value.lower() if isinstance(value, str) else value
        out.sort(key=_sort_value, reverse=(order == "desc"))

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    version = get_current_version(db, requirement.id)
    return _to_out(db, requirement, version, current_user.id)


@router.put("/{requirement_id}", response_model=RequirementOut)
def update_requirement(
    project_id: UUID, requirement_id: UUID, payload: RequirementUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Direct requirement edit. Rejected once the requirement is locked (C-G-12) —
    at that point, changes must go through a change request instead."""
    _require_edit_role(db, current_user, project_id)
    if payload.status == RequirementStatus.APPROVED:
        # C-U-03's clarification is explicit that approving a requirement is
        # a *Project Manager* capability layered on top of, not shared
        # with, what administrators/stakeholders can do ("Project Managers
        # can also provide approvals for change requests and approval of
        # project requirements") — the same distinction
        # decide_change_request already enforces for CR approval
        # specifically ("C-U-03: project manager only"), which this direct-
        # edit path had not mirrored: any of the three CAN_EDIT_ROLES
        # (including a plain Stakeholder) could otherwise set
        # status="approved" here and become the requirement's own
        # approval_authority, self-approving and locking it.
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a requirement.")
    # The previous reject-COMPLETED-in-payload guard that lived here is now
    # moot: `COMPLETED` isn't a valid `RequirementStatus` value at all
    # (C-G-11 — completion is `Requirement.is_completed`, an overlay marker,
    # not a lifecycle status), so Pydantic/enum validation rejects it on the
    # way in before this handler ever runs, with no special case needed.
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    project = db.get(Project, project_id)
    new_version = edit_requirement(
        db, project, requirement, current_user,
        name=payload.name, reasoning=payload.reasoning, clarification=payload.clarification,
        description=payload.description,
        status_value=payload.status, owner=payload.owner,
        target_stage_id=payload.target_stage_id,
        level=payload.level,
        change_note=payload.change_note or "Direct edit during scoping.",
        custom_fields=payload.custom_fields,
        review_date=payload.review_date, review_date_explicitly_set=True,
        review_lead_days=payload.review_lead_days, review_lead_days_explicitly_set=True,
        reviewer=payload.reviewer, reviewer_explicitly_set=True,
        component_id=payload.component_id, category_id=payload.category_id,
        keywords=payload.keywords,
    )
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="updated",
              actor_id=current_user.id, project_id=project_id, detail={"change_note": payload.change_note})
    requirements_updated_total.inc()
    db.commit()
    db.refresh(requirement)
    pubsub.notify(project_id, {"type": "requirement", "action": "updated", "id": str(requirement.id)})
    return _to_out(db, requirement, new_version, current_user.id)


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Archives (soft-deletes) a requirement, preserving its history (C-A-06)."""
    if not get_effective_project_roles(db, current_user.id, project_id) & {
        ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR,
    }:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators or managers may archive requirements.")
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    archive_requirement(db, requirement, current_user)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    requirements_archived_total.inc()
    db.commit()
    pubsub.notify(project_id, {"type": "requirement", "action": "archived", "id": str(requirement.id)})


@router.post("/{requirement_id}/unarchive", response_model=RequirementOut)
def restore_requirement(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Restores an archived requirement to the active list, undoing
    `delete_requirement` — same permission gate (managers/administrators),
    same audit-log shape, mirroring `routers.projects::unarchive_project`
. Unlike `delete_requirement`, calling
    this on a requirement that isn't archived is a harmless no-op rather
    than an error, matching `unarchive_project`'s own idempotent shape.
    """
    if not get_effective_project_roles(db, current_user.id, project_id) & {
        ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR,
    }:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators or managers may restore requirements.")
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    unarchive_requirement(db, requirement, current_user)
    log_event(db, entity_type="requirement", entity_id=requirement.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(requirement)
    version = get_current_version(db, requirement.id)
    pubsub.notify(project_id, {"type": "requirement", "action": "unarchived", "id": str(requirement.id)})
    return _to_out(db, requirement, version, current_user.id)


@router.get("/{requirement_id}/history", response_model=list[RequirementVersionOut])
def requirement_history(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Change log for a requirement, excluding discussion comments (C-A-09)."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    versions = db.scalars(
        select(RequirementVersion)
        .where(RequirementVersion.requirement_id == requirement_id)
        .order_by(RequirementVersion.version_number)
    ).all()
    people = version_people(db, versions)
    return [
        RequirementVersionOut(
            version_number=v.version_number, name=v.name, reasoning=v.reasoning,
            clarification=v.clarification, description=v.description, status=v.status,
            owner=people[(v.owner_type, v.owner_id)],
            target_stage_id=v.target_stage_id, level=v.level,
            change_note=v.change_note, change_request_id=v.change_request_id,
            custom_fields=v.custom_fields,
            created_by=v.created_by, created_at=v.created_at, valid_to=v.valid_to,
        )
        for v in versions
    ]


@router.get("/{requirement_id}/activity", response_model=list[ChangeEntryOut])
def requirement_activity(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Per-entity activity timeline for the requirement detail view's side
    panel (mock's "Subscribed" activity log): audit events plus version
    history, filtered to this requirement. Excludes discussion comments,
    which are shown separately (C-A-09 clarification)."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    return get_project_changes(
        db, project_id, since=None, until=None, include_comments=False,
        entity_type="requirement", entity_id=requirement_id,
    )


@router.post("/{requirement_id}/move", response_model=RequirementOut)
def move_requirement(
    project_id: UUID, requirement_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Reorders a requirement within its list. Scoping-stage only (C-E-03)."""
    _require_edit_role(db, current_user, project_id)
    current_stage = db.scalar(
        select(ProjectStage).where(ProjectStage.project_id == project_id, ProjectStage.is_current.is_(True))
    )
    if current_stage is None or current_stage.status != StageStatus.SCOPING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Requirements can only be reordered during scoping.")

    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")

    siblings = db.scalars(
        select(Requirement).where(
            Requirement.project_id == project_id, Requirement.component_id == requirement.component_id,
            Requirement.category_id == requirement.category_id, Requirement.is_archived.is_(False),
        )
    ).all()
    versions = {r.id: get_current_version(db, r.id) for r in siblings}
    siblings.sort(key=lambda r: versions[r.id].sort_order)
    idx = next(i for i, r in enumerate(siblings) if r.id == requirement.id)
    swap_idx = idx - 1 if payload.direction == "up" else idx + 1
    if 0 <= swap_idx < len(siblings):
        a, b = siblings[idx], siblings[swap_idx]
        versions[a.id].sort_order, versions[b.id].sort_order = versions[b.id].sort_order, versions[a.id].sort_order
        log_event(
            db, entity_type="requirement", entity_id=requirement.id, action="moved", actor_id=current_user.id,
            project_id=project_id, detail={"direction": payload.direction},
        )
        db.commit()
    version = get_current_version(db, requirement.id)
    return _to_out(db, requirement, version, current_user.id)


def _get_requirement_in_project(db: Session, project_id: UUID, requirement_id: UUID) -> Requirement:
    """Loads a requirement and 404s unless it belongs to `project_id`.

    Without this check, an endpoint that only verifies the caller's role on
    `project_id` (via `require_project_view`/`_require_edit_role`) would let
    any project member read or write links/comments on a requirement
    belonging to a different, inaccessible project by supplying its id —
    an IDOR. Every handler taking both a `project_id` and a `requirement_id`
    must load through this helper rather than trusting `requirement_id` alone.
    """
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    return requirement
