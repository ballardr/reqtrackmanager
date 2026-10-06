"""
Module: routers.project_link_types

The project level of the link-type vocabulary:
- `GET/POST/PATCH/DELETE .../link-types`: the link types a project can reach
  (organisation-wide, its own, and its ancestors'), and create/rename/re-order/delete
  its own, with the same delete-in-use dialog contract the organisation's types use.
- `PUT .../link-types/{id}/visibility`: hide or re-show a type for the project.
- `GET/PUT/DELETE .../artefact-link-rules`: the project's artefact-type link rules.

Reading needs project membership (or project-management capability); every write
needs `require_project_manage` and is refused with 403 while the organisation locks
link-type customisation (`Organization.project_customisation_locks`). Types are
resolved through `services.link_type_scope`, never queried directly, so isolation
between projects is decided in one place.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.registry import get_artefact_type_label
from app.schemas.link_type import (
    ArtefactLinkRuleSet,
    ArtefactTypeOut,
    LinkTypeCandidateOut,
    LinkTypeCreate,
    LinkTypeDeleteOutcomeOut,
    LinkTypeOut,
    LinkTypeUpdate,
    LinkTypeUsageOut,
    LinkTypeVisibilitySet,
    ProjectArtefactLinkRuleOut,
    ProjectLinkTypeOut,
    ProjectLinkTypesOut,
)
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.link_authoring import linkable_types_for_project
from app.services.link_type_scope import (
    ScopedLinkType,
    is_customisation_locked,
    resolve_artefact_rule_rows,
    resolve_link_type_scope,
)
from app.services.link_type_usage import compute_usage
from app.services.link_type_usage import delete_link_type as delete_link_type_in_use
from app.services.link_types import clear_artefact_rule, ensure_org_seeds, set_artefact_rule
from app.services.ordering import move_ordered
from app.services.project_link_types import (
    assert_not_locked,
    create_project_link_type,
    get_own_link_type,
    set_visibility,
    update_project_link_type,
)
from app.services.rbac import can_manage_project_settings, get_effective_project_roles, require_project_manage, require_project_view_or_manage

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["project-link-types"])


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, or 404 (access is checked by the route dependency)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _visible_project_name(db: Session, user: User, project_id: UUID | None) -> str | None:
    """The project's name, only when `user` could already see that project (a member,
    or able to manage it); never the name of one they cannot open."""
    if project_id is None:
        return None
    other = db.get(Project, project_id)
    if other is None:
        return None
    if get_effective_project_roles(db, user.id, project_id) or can_manage_project_settings(db, user, other):
        return other.name
    return None


def _scope_of(scoped: ScopedLinkType, project: Project) -> Literal["organization", "project", "inherited"]:
    """Where a scoped type comes from, relative to `project`."""
    if scoped.owner_project_id is None:
        return "organization"
    return "project" if scoped.owner_project_id == project.id else "inherited"


def _to_out(db: Session, user: User, project: Project, scoped: ScopedLinkType) -> ProjectLinkTypeOut:
    """The panel row for one scoped link type."""
    link_type = scoped.link_type
    shadow = scoped.shadowed_by
    return ProjectLinkTypeOut(
        id=link_type.id, organization_id=link_type.organization_id, project_id=link_type.project_id,
        forward_name=link_type.forward_name, reverse_name=link_type.reverse_name, sort_order=link_type.sort_order,
        flow=link_type.flow, allowed_source_types=link_type.allowed_source_types,
        allowed_target_types=link_type.allowed_target_types, dedicated_endpoint=link_type.dedicated_endpoint,
        scope=_scope_of(scoped, project), owner_project_id=scoped.owner_project_id,
        owner_project_name=_visible_project_name(db, user, scoped.owner_project_id)
        if scoped.owner_project_id != project.id else None,
        hidden=scoped.hidden, hidden_here=scoped.own_visibility,
        hidden_by_inherited=scoped.hidden and scoped.hidden_by_project_id not in (None, project.id),
        shadowed_by_scope=None if shadow is None else (
            "organization" if shadow.project_id is None else ("project" if shadow.project_id == project.id else "inherited")
        ),
        shadowed_by_name=None if shadow is None else shadow.forward_name,
        editable=scoped.owner_project_id == project.id,
    )


@router.get("/link-types", response_model=ProjectLinkTypesOut)
def list_project_link_types(
    project_id: UUID,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
) -> ProjectLinkTypesOut:
    """The link types this project can reach, annotated with where each comes from,
    whether it is hidden or shadowed, and whether the project may edit it.

    Hidden and shadowed types are included (so the panel can show and re-enable
    them); pickers use the artefact `link-types` endpoint instead, which lists only
    what is offered. Missing module-seeded types are created first. While the
    organisation locks customisation only the organisation-wide types appear.
    """
    project = _project_or_404(db, project_id)
    ensure_org_seeds(db, project.organization_id)
    db.commit()
    return ProjectLinkTypesOut(
        locked=is_customisation_locked(db, project.organization_id),
        items=[_to_out(db, current_user, project, s) for s in resolve_link_type_scope(db, project)],
    )


@router.post("/link-types", response_model=ProjectLinkTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_link_type_endpoint(
    payload: LinkTypeCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectLinkTypeOut:
    """Creates a link type local to this project (usable here and in every
    descendant project).

    Raises:
        HTTPException: 403 the organisation locks customisation; 400 the name is
            already provided here, by the organisation or by a parent project; 422 a
            restriction names an unknown artefact type.
    """
    link_type = create_project_link_type(
        db, project, forward_name=payload.forward_name, reverse_name=payload.reverse_name, flow=payload.flow,
        allowed_source_types=payload.allowed_source_types, allowed_target_types=payload.allowed_target_types,
        actor=current_user,
    )
    db.commit()
    return _to_out(db, current_user, project, next(s for s in resolve_link_type_scope(db, project) if s.link_type.id == link_type.id))


@router.patch("/link-types/{link_type_id}", response_model=ProjectLinkTypeOut)
def update_project_link_type_endpoint(
    link_type_id: UUID,
    payload: LinkTypeUpdate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectLinkTypeOut:
    """Renames one of this project's own link types (and optionally changes its
    flow or restrictions). Every link keeps pointing at the row's id, so existing
    links are untouched.

    Raises:
        HTTPException: 403 locked; 404 not this project's own type; 400 name clash;
            422 unknown artefact type.
    """
    update_project_link_type(
        db, project, link_type_id, forward_name=payload.forward_name, reverse_name=payload.reverse_name,
        flow=payload.flow,
        restrictions={
            k: getattr(payload, k) for k in ("allowed_source_types", "allowed_target_types") if k in payload.model_fields_set
        },
        actor=current_user,
    )
    db.commit()
    return _to_out(db, current_user, project, next(s for s in resolve_link_type_scope(db, project) if s.link_type.id == link_type_id))


@router.post("/link-types/{link_type_id}/move", response_model=LinkTypeOut)
def move_project_link_type(
    link_type_id: UUID,
    payload: MoveDirection,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Moves one of this project's own link types up or down among its own types."""
    assert_not_locked(db, project)
    get_own_link_type(db, project, link_type_id)
    result = move_ordered(
        db, RequirementLinkTypeDefinition, [RequirementLinkTypeDefinition.project_id == project.id],
        link_type_id, payload.direction,
    )
    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type_id, action="reordered",
        actor_id=current_user.id, organization_id=project.organization_id, project_id=project.id,
        detail={"direction": payload.direction, "scope": "project"},
    )
    db.commit()
    return result


@router.put("/link-types/{link_type_id}/visibility", response_model=ProjectLinkTypeOut)
def set_project_link_type_visibility(
    link_type_id: UUID,
    payload: LinkTypeVisibilitySet,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectLinkTypeOut:
    """Hides or re-shows a link type for this project (and its descendants, unless
    one overrides). Hidden means "not offered for new links": existing links keep
    showing. `hidden: null` removes this project's own choice.

    Raises:
        HTTPException: 403 locked; 404 the type is not reachable from this project.
    """
    set_visibility(db, project, link_type_id, payload.hidden, current_user)
    db.commit()
    return _to_out(db, current_user, project, next(s for s in resolve_link_type_scope(db, project) if s.link_type.id == link_type_id))


@router.get("/link-types/{link_type_id}/usage", response_model=LinkTypeUsageOut)
def get_project_link_type_usage(
    link_type_id: UUID,
    keep_in_projects: bool = Query(False, description="Assess as if other projects keep the type by copy."),
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LinkTypeUsageOut:
    """What depends on one of this project's own link types, for the delete dialog."""
    usage = compute_usage(
        db, project.organization_id, link_type_id, project=project, actor=current_user, keep_in_projects=keep_in_projects
    )
    return LinkTypeUsageOut(
        link_count=usage.link_count, project_count=usage.project_count,
        pending_change_requests=usage.pending_change_requests,
        approved_requirement_links=usage.approved_requirement_links,
        rule_artefact_types=[ArtefactTypeOut(type=t, label=get_artefact_type_label(t)) for t in usage.rule_artefact_types],
        emptied_rule_artefact_types=[
            ArtefactTypeOut(type=t, label=get_artefact_type_label(t)) for t in usage.emptied_rule_artefact_types
        ],
        is_dedicated=usage.is_dedicated, is_last=usage.is_last,
        candidates=[
            LinkTypeCandidateOut(
                id=c.link_type.id, forward_name=c.link_type.forward_name, reverse_name=c.link_type.reverse_name,
                flow=c.link_type.flow, compatible=c.compatible, reason=c.reason, flow_differs=c.flow_differs,
            )
            for c in usage.candidates
        ],
        moved_link_count=usage.moved_link_count, keep_available=usage.keep_available,
        keep_project_count=usage.keep_project_count, unmanageable_project_count=usage.unmanageable_project_count,
    )


@router.delete("/link-types/{link_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_link_type(
    link_type_id: UUID,
    reassign_to_id: UUID | None = Query(None),
    mode: Literal["reassign", "remove_links"] | None = Query(None),
    keep_in_projects: bool = Query(False),
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes one of this project's own link types (`services.link_type_usage.delete_link_type`).

    Same contract as the organisation's delete: an unused type goes outright; one
    in use needs `reassign_to_id`/`mode=reassign` or `mode=remove_links`. With
    `keep_in_projects`, descendant projects that use the type keep it by copy
    instead. Passing `mode` or `keep_in_projects` returns 200 with what happened;
    the legacy forms return 204.

    Raises:
        HTTPException: 403 locked; 404 not this project's own type; 409 see the
            service (in use with no mode, pending change requests, a rule would be
            emptied, links held by projects the caller cannot manage).
    """
    assert_not_locked(db, project)
    outcome = delete_link_type_in_use(
        db, organization_id=project.organization_id, link_type_id=link_type_id, mode=mode,
        reassign_to_id=reassign_to_id, actor=current_user, project=project, keep_in_projects=keep_in_projects,
    )
    db.commit()
    if mode is not None or keep_in_projects:
        return JSONResponse(
            LinkTypeDeleteOutcomeOut(
                moved=outcome.moved, merged=outcome.merged, removed=outcome.removed,
                copies_created=outcome.copies_created, copies_renamed=outcome.copies_renamed,
            ).model_dump(),
            status_code=status.HTTP_200_OK,
        )


@router.get("/artefact-link-rules", response_model=list[ProjectArtefactLinkRuleOut])
def list_project_artefact_link_rules(
    project_id: UUID,
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
) -> list[ProjectArtefactLinkRuleOut]:
    """Every artefact type available in the project with the link types it may use as
    this project resolves them (`null` = any), and which scope the rule comes from."""
    project = _project_or_404(db, project_id)
    rows = resolve_artefact_rule_rows(db, project.organization_id, project.id)
    result: list[ProjectArtefactLinkRuleOut] = []
    for artefact_type in sorted(linkable_types_for_project(db, project), key=lambda t: get_artefact_type_label(t).lower()):
        rule = rows.get(artefact_type)
        result.append(
            ProjectArtefactLinkRuleOut(
                artefact_type=artefact_type, label=get_artefact_type_label(artefact_type),
                link_type_ids=None if rule is None else sorted((e.link_type_id for e in rule.allowed_link_types), key=str),
                source=None if rule is None else (
                    "organization" if rule.project_id is None else ("project" if rule.project_id == project.id else "inherited")
                ),
                source_project_name=(
                    None if rule is None or rule.project_id in (None, project.id)
                    else _visible_project_name(db, current_user, rule.project_id)
                ),
                own=rule is not None and rule.project_id == project.id,
            )
        )
    return result


@router.put("/artefact-link-rules/{artefact_type}", response_model=ProjectArtefactLinkRuleOut)
def set_project_artefact_link_rule(
    artefact_type: str,
    payload: ArtefactLinkRuleSet,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectArtefactLinkRuleOut:
    """Sets this project's rule for an artefact type: a closed, non-empty list of link
    types it may use here and in descendants, replacing any inherited rule entirely.
    Existing links are never changed.

    Raises:
        HTTPException: 403 locked; 422 unknown artefact type, empty list, or a link
            type the project cannot use.
    """
    assert_not_locked(db, project)
    try:
        rule = set_artefact_rule(db, project.organization_id, artefact_type, payload.link_type_ids, project)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    log_event(
        db, entity_type="artefact_type_link_rule", entity_id=rule.id, action="updated", actor_id=current_user.id,
        organization_id=project.organization_id, project_id=project.id,
        detail={"artefact_type": artefact_type, "link_type_ids": [str(i) for i in payload.link_type_ids], "scope": "project"},
    )
    db.commit()
    return ProjectArtefactLinkRuleOut(
        artefact_type=artefact_type, label=get_artefact_type_label(artefact_type),
        link_type_ids=sorted((e.link_type_id for e in rule.allowed_link_types), key=str), source="project", own=True,
    )


@router.delete("/artefact-link-rules/{artefact_type}", status_code=status.HTTP_204_NO_CONTENT)
def clear_project_artefact_link_rule(
    artefact_type: str,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Removes this project's own rule for an artefact type, so the inherited rule
    (an ancestor's, else the organisation's, else none) applies again."""
    assert_not_locked(db, project)
    if clear_artefact_rule(db, project.organization_id, artefact_type, project):
        log_event(
            db, entity_type="artefact_type_link_rule", entity_id=project.id, action="deleted",
            actor_id=current_user.id, organization_id=project.organization_id, project_id=project.id,
            detail={"artefact_type": artefact_type, "scope": "project"},
        )
    db.commit()
