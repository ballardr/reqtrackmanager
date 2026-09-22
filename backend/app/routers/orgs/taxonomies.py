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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.project import Project
from app.models.project_status import ProjectStatusDefinition
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.schemas.link_type import LinkTypeCreate, LinkTypeOut, LinkTypeUpdate
from app.schemas.project import MoveDirection
from app.schemas.project_status import ProjectStatusCreate, ProjectStatusOut, ProjectStatusUpdate
from app.services.audit import log_event
from app.services.definitions import delete_definition_with_reassignment
from app.services.ordering import move_ordered
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
    """Creates a new requirement link type for this organisation (C-G-09)."""
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    count = len(
        db.scalars(
            select(RequirementLinkTypeDefinition.id).where(RequirementLinkTypeDefinition.organization_id == organization_id)
        ).all()
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=payload.forward_name, reverse_name=payload.reverse_name,
        sort_order=count,
    )
    db.add(link_type)
    db.flush()
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"forward_name": link_type.forward_name, "reverse_name": link_type.reverse_name})
    db.commit()
    db.refresh(link_type)
    return link_type


@router.get("/{organization_id}/link-types", response_model=list[LinkTypeOut])
def list_link_types(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's requirement link types — any org member may
    need this to populate a requirement's "add link" form, so listing isn't
    admin-only (only create/rename/move/delete are)."""
    return db.scalars(
        select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.organization_id == organization_id)
        .order_by(RequirementLinkTypeDefinition.sort_order)
    ).all()


@router.post("/{organization_id}/link-types/{link_type_id}/move", response_model=LinkTypeOut)
def move_link_type(
    organization_id: UUID, link_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Moves a link type up/down in display order."""
    result = move_ordered(
        db, RequirementLinkTypeDefinition, [RequirementLinkTypeDefinition.organization_id == organization_id],
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
    """Renames both directional names of a link type at once. Every
    `ArtefactLink.link_type_id` reference points at this row's id,
    never its names, so renaming has zero effect on any existing link
    using this type — see `services.definitions`' module docstring."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
            RequirementLinkTypeDefinition.id != link_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    link_type.forward_name = payload.forward_name
    link_type.reverse_name = payload.reverse_name
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(link_type)
    return link_type


@router.delete("/{organization_id}/link-types/{link_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link_type(
    organization_id: UUID, link_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes a link type, applying the shared rename/delete/reassign
    rules (§4.0): refuses to leave the organisation with zero link types
    (409), and requires an explicit `reassign_to_id` to delete a type
    that's currently in use by any `ArtefactLink` (409 naming the count
    if omitted; bulk-reassigns then deletes if provided). Reassignment here
    changes each affected link's asserted meaning, which is exactly why
    it's the admin's explicit choice rather than an automatic cascade or
    silent delete — see `services.definitions.delete_definition_with_reassignment`'s
    docstring for the exact behaviour.

    Filtering by `referencing_fk_column` alone (no `source_type`/
    `target_type` filter) is still correct here: in this phase, only
    requirement-to-requirement links ever have a non-null `link_type_id`
    (untyped action links always have `link_type_id IS NULL`), so every
    `ArtefactLink` row this reassigns/counts is, in practice, a
    requirement-to-requirement traceability link — the same set the old
    `RequirementLink`-scoped query returned.
    """
    delete_definition_with_reassignment(
        db, definition_model=RequirementLinkTypeDefinition, scope_column=RequirementLinkTypeDefinition.organization_id,
        scope_id=organization_id, item_id=link_type_id, reassign_to_id=reassign_to_id,
        referencing_model=ArtefactLink, referencing_fk_column=ArtefactLink.link_type_id,
        referencing_fk_name="link_type_id", entity_type="requirement_link_type_definition", noun="link type",
        plural_noun="link(s)", reassign_verb="convert",
        min_count_message="An organisation must always have at least one requirement link type.",
        actor_id=current_user.id, organization_id=organization_id, project_id=None, name_attr="forward_name",
    )
    db.commit()

