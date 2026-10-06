"""
Module: routers.orgs.taxonomies

Organisation-definable taxonomies: project statuses and requirement link
types (bidirectional, C-G-09) — create/list/move/rename/delete, sharing
the rename/reorder/delete-with-reassignment rules described in
`services.definitions`' module docstring.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.project import Project
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.registry import get_artefact_type_label
from app.schemas.link_type import (
    ArtefactLinkRuleOut,
    ArtefactLinkRuleSet,
    ArtefactTypeOut,
    LinkTypeCandidateOut,
    LinkTypeCreate,
    LinkTypeDeleteOutcomeOut,
    LinkTypeOut,
    LinkTypeUpdate,
    LinkTypeUsageOut,
    ProjectCustomisationOut,
    ProjectCustomisationSet,
)
from app.schemas.project import MoveDirection
from app.schemas.project_status import ProjectStatusCreate, ProjectStatusOut, ProjectStatusUpdate
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.link_type_usage import compute_usage
from app.services.link_type_usage import delete_link_type as delete_link_type_in_use
from app.services.link_types import (
    clear_artefact_rule,
    ensure_org_seeds,
    get_artefact_rules,
    list_org_artefact_types,
    set_artefact_rule,
)
from app.services.ordering import move_ordered
from app.services.project_link_types import get_lock_summary, set_customisation_locks, validated_restrictions
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-taxonomies"])


@router.post("/{organization_id}/project-statuses", response_model=ProjectStatusOut, status_code=status.HTTP_201_CREATED)
def create_project_status(
    organization_id: UUID, payload: ProjectStatusCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a new project status for this organisation."""
    existing = db.scalar(
        select(ProjectStatusDefinition.id).where(
            ProjectStatusDefinition.organization_id == organization_id, ProjectStatusDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project status with this name already exists.")
    count = len(
        db.scalars(select(ProjectStatusDefinition.id).where(ProjectStatusDefinition.organization_id == organization_id)).all()
    )
    project_status = ProjectStatusDefinition(organization_id=organization_id, name=payload.name, sort_order=count)
    db.add(project_status)
    db.flush()
    log_event(db, entity_type="project_status_definition", entity_id=project_status.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": project_status.name})
    db.commit()
    db.refresh(project_status)
    return project_status


@router.get("/{organization_id}/project-statuses", response_model=list[ProjectStatusOut])
def list_project_statuses(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's project statuses — any org member may need
    this to populate a project's status picker, so listing isn't admin-only
    (only create/rename/move/delete are), mirroring `list_report_templates`."""
    return db.scalars(
        select(ProjectStatusDefinition).where(ProjectStatusDefinition.organization_id == organization_id)
        .order_by(ProjectStatusDefinition.sort_order)
    ).all()


@router.post("/{organization_id}/project-statuses/{status_id}/move", response_model=ProjectStatusOut)
def move_project_status(
    organization_id: UUID, status_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Moves a project status up/down in display order."""
    result = move_ordered(
        db, ProjectStatusDefinition, [ProjectStatusDefinition.organization_id == organization_id], status_id, payload.direction
    )
    log_event(db, entity_type="project_status_definition", entity_id=status_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{organization_id}/project-statuses/{status_id}", response_model=ProjectStatusOut)
def rename_project_status(
    organization_id: UUID, status_id: UUID, payload: ProjectStatusUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Renames a project status. Every `Project.status_id` reference points
    at this row's id, never its name, so renaming has zero effect on any
    project currently on this status — see `services.definitions`' module
    docstring."""
    project_status = db.get(ProjectStatusDefinition, status_id)
    if project_status is None or project_status.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project status not found.")
    existing = db.scalar(
        select(ProjectStatusDefinition.id).where(
            ProjectStatusDefinition.organization_id == organization_id, ProjectStatusDefinition.name == payload.name,
            ProjectStatusDefinition.id != status_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project status with this name already exists.")
    project_status.name = payload.name
    log_event(db, entity_type="project_status_definition", entity_id=project_status.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(project_status)
    return project_status


@router.delete("/{organization_id}/project-statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_status(
    organization_id: UUID, status_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes a project status, applying the shared rename/delete/reassign
    rules (§4.0): refuses to leave the organisation with zero statuses
    (409), and requires an explicit `reassign_to_id` to delete a status
    that's currently in use by any `Project` (409 naming the count if
    omitted; bulk-reassigns then deletes if provided) — see
    `services.definitions.delete_definition_with_reassignment`'s docstring
    for the exact behaviour.
    """
    delete_definition_with_reassignment(
        db, definition_model=ProjectStatusDefinition, scope_column=ProjectStatusDefinition.organization_id,
        scope_id=organization_id, item_id=status_id, reassign_to_id=reassign_to_id,
        referencing_model=Project, referencing_fk_column=Project.status_id, referencing_fk_name="status_id",
        entity_type="project_status_definition", noun="status", plural_noun="project(s)", reassign_verb="move",
        min_count_message="An organisation must always have at least one project status.",
        actor_id=current_user.id, organization_id=organization_id, project_id=None,
    )
    db.commit()


@router.post("/{organization_id}/link-types", response_model=LinkTypeOut, status_code=status.HTTP_201_CREATED)
def create_link_type(
    organization_id: UUID, payload: LinkTypeCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a new requirement link type for this organisation (C-G-09).

    Raises:
        HTTPException: 400 on a duplicate forward name, or 422 when a restriction
            names an unknown artefact type.
    """
    allowed_source_types, allowed_target_types = validated_restrictions(
        payload.allowed_source_types, payload.allowed_target_types
    )
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.project_id.is_(None),
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    count = len(
        db.scalars(
            select(RequirementLinkTypeDefinition.id).where(
                RequirementLinkTypeDefinition.organization_id == organization_id,
                RequirementLinkTypeDefinition.project_id.is_(None),
            )
        ).all()
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=payload.forward_name, reverse_name=payload.reverse_name,
        sort_order=count, flow=payload.flow, allowed_source_types=allowed_source_types,
        allowed_target_types=allowed_target_types,
    )
    db.add(link_type)
    db.flush()
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"forward_name": link_type.forward_name, "reverse_name": link_type.reverse_name,
                      "flow": link_type.flow.value, "allowed_source_types": allowed_source_types,
                      "allowed_target_types": allowed_target_types})
    db.commit()
    db.refresh(link_type)
    return link_type


@router.get("/{organization_id}/link-types", response_model=list[LinkTypeOut])
def list_link_types(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's organisation-wide requirement link types — any org
    member may need this, so listing isn't admin-only (only create/rename/move/
    delete are). Project-local types are never returned here (they could belong
    to projects the caller cannot see); a project's own and inherited types come
    from `GET /projects/{id}/link-types`. Module-seeded link types
    the organisation lacks are created first (`services.link_types.ensure_org_seeds`),
    so the list is complete before anything has used them."""
    ensure_org_seeds(db, organization_id)
    db.commit()
    return db.scalars(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.project_id.is_(None),
        ).order_by(RequirementLinkTypeDefinition.sort_order)
    ).all()


@router.post("/{organization_id}/link-types/{link_type_id}/move", response_model=LinkTypeOut)
def move_link_type(
    organization_id: UUID, link_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Moves a link type up/down in display order."""
    result = move_ordered(
        db, RequirementLinkTypeDefinition,
        [RequirementLinkTypeDefinition.organization_id == organization_id, RequirementLinkTypeDefinition.project_id.is_(None)],
        link_type_id, payload.direction,
    )
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{organization_id}/link-types/{link_type_id}", response_model=LinkTypeOut)
def rename_link_type(
    organization_id: UUID, link_type_id: UUID, payload: LinkTypeUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Renames both directional names of a link type at once, and (when
    `flow` is given) changes its direction. Every
    `ArtefactLink.link_type_id` reference points at this row's id,
    never its names, so renaming has zero effect on any existing link
    using this type — see `services.definitions`' module docstring."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.organization_id != organization_id or link_type.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.project_id.is_(None),
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
            RequirementLinkTypeDefinition.id != link_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    link_type.forward_name = payload.forward_name
    link_type.reverse_name = payload.reverse_name
    if payload.flow is not None:
        link_type.flow = payload.flow
    if "allowed_source_types" in payload.model_fields_set or "allowed_target_types" in payload.model_fields_set:
        source_types, target_types = validated_restrictions(
            payload.allowed_source_types if "allowed_source_types" in payload.model_fields_set else link_type.allowed_source_types,
            payload.allowed_target_types if "allowed_target_types" in payload.model_fields_set else link_type.allowed_target_types,
        )
        link_type.allowed_source_types = source_types
        link_type.allowed_target_types = target_types
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"flow": link_type.flow.value, "allowed_source_types": link_type.allowed_source_types,
                      "allowed_target_types": link_type.allowed_target_types})
    db.commit()
    db.refresh(link_type)
    return link_type


@router.get("/{organization_id}/link-types/{link_type_id}/usage", response_model=LinkTypeUsageOut)
def get_link_type_usage(
    organization_id: UUID, link_type_id: UUID,
    keep_in_projects: bool = Query(False, description="Assess as if projects using the type keep it by copy."),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """What depends on an organisation-wide link type, for the delete-in-use dialog:
    link, project, pending change request and approved-requirement counts, the
    artefact-type rules naming it, whether projects could keep it by copy, and every
    other organisation-wide link type assessed as a replacement."""
    usage = compute_usage(db, organization_id, link_type_id, keep_in_projects=keep_in_projects)
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


@router.delete("/{organization_id}/link-types/{link_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link_type(
    organization_id: UUID, link_type_id: UUID,
    reassign_to_id: UUID | None = Query(None),
    mode: Literal["reassign", "remove_links"] | None = Query(None),
    keep_in_projects: bool = Query(False),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes an organisation-wide link type (`services.link_type_usage.delete_link_type`).

    Refuses to leave the organisation with zero link types (409). An unused type
    is deleted outright. A type in use needs `reassign_to_id` (convert the links
    to another type, merging duplicates) or `mode=remove_links` (delete them too,
    refused while pending change requests propose the type or when it would
    empty an artefact-type rule); without either, 409 naming the count. Passing
    `mode` or `keep_in_projects` explicitly returns 200 with what happened
    (`moved`/`merged`/`removed`/`copies_created`/`copies_renamed`); the legacy forms
    return 204. With `keep_in_projects`, each project that uses the type keeps it as
    a local copy (the top-most using project of each branch; descendants inherit it)
    and its links are repointed, so nothing they see changes.
    """
    outcome = delete_link_type_in_use(
        db, organization_id=organization_id, link_type_id=link_type_id, mode=mode,
        reassign_to_id=reassign_to_id, actor=current_user, keep_in_projects=keep_in_projects,
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


@router.get("/{organization_id}/artefact-types", response_model=list[ArtefactTypeOut])
def list_artefact_types(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """The artefact types that exist in this organisation (core types plus those
    of its enabled modules) with display labels, for link-type restriction and
    rule pickers."""
    return [ArtefactTypeOut(type=t, label=get_artefact_type_label(t)) for t in list_org_artefact_types(db, organization_id)]


@router.get("/{organization_id}/artefact-link-rules", response_model=list[ArtefactLinkRuleOut])
def list_artefact_link_rules(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Every artefact type of the organisation with the link types it may use
    (`null` = any link type), for the link-type admin's "By artefact type" view."""
    rules = get_artefact_rules(db, organization_id)
    return [
        ArtefactLinkRuleOut(
            artefact_type=t, label=get_artefact_type_label(t),
            link_type_ids=sorted(rules[t], key=str) if t in rules else None,
        )
        for t in list_org_artefact_types(db, organization_id)
    ]


@router.put("/{organization_id}/artefact-link-rules/{artefact_type}", response_model=ArtefactLinkRuleOut)
def set_artefact_link_rule(
    organization_id: UUID, artefact_type: str, payload: ArtefactLinkRuleSet,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Limits an artefact type to the given link types (a closed, non-empty list;
    existing links are never changed). Enforced when links are created."""
    try:
        rule = set_artefact_rule(db, organization_id, artefact_type, payload.link_type_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    log_event(db, entity_type="artefact_type_link_rule", entity_id=rule.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"artefact_type": artefact_type, "link_type_ids": [str(i) for i in payload.link_type_ids]})
    db.commit()
    return ArtefactLinkRuleOut(
        artefact_type=artefact_type, label=get_artefact_type_label(artefact_type),
        link_type_ids=sorted((e.link_type_id for e in rule.allowed_link_types), key=str),
    )


@router.delete("/{organization_id}/artefact-link-rules/{artefact_type}", status_code=status.HTTP_204_NO_CONTENT)
def clear_artefact_link_rule(
    organization_id: UUID, artefact_type: str,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Removes an artefact type's rule, so it may use any link type again."""
    if clear_artefact_rule(db, organization_id, artefact_type):
        log_event(db, entity_type="artefact_type_link_rule", entity_id=organization_id, action="deleted",
                  actor_id=current_user.id, organization_id=organization_id, detail={"artefact_type": artefact_type})
    db.commit()


@router.get("/{organization_id}/project-customisation", response_model=ProjectCustomisationOut)
def get_project_customisation(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
) -> ProjectCustomisationOut:
    """Which vocabularies projects may not customise in this organisation, with the
    number of project-local link types (and projects owning them) that locking would
    leave dormant. Readable by any org member, since project admins need to know
    whether their own link-type controls are available."""
    summary = get_lock_summary(db, organization_id)
    return ProjectCustomisationOut(
        locks=summary.locks, local_link_type_count=summary.local_link_type_count,
        local_link_type_project_count=summary.local_link_type_project_count,
    )


@router.put("/{organization_id}/project-customisation", response_model=ProjectCustomisationOut)
def set_project_customisation(
    organization_id: UUID, payload: ProjectCustomisationSet,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> ProjectCustomisationOut:
    """Replaces the organisation's project-customisation locks (`link_types` forbids
    project-level link types, hiding and rules). Nothing is deleted: project-level rows
    go dormant and come back when the lock is removed.

    Raises:
        HTTPException: 422 for an unknown lock key.
    """
    summary = set_customisation_locks(db, organization_id, payload.locks, current_user)
    db.commit()
    return ProjectCustomisationOut(
        locks=summary.locks, local_link_type_count=summary.local_link_type_count,
        local_link_type_project_count=summary.local_link_type_project_count,
    )
