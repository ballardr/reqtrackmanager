"""
Module: modules.stakeholders.relationship_project_router

Project-scoped API for the §10.5 relationships a Stakeholder or Persona has with
other artefacts (Phase 3), mounted at
`/api/v1/projects/{project_id}/modules/stakeholders`: the declared kinds, a
target picker, a holder's relationships (list/add/remove) and the reverse view
from a target.

RBAC: viewing needs the holder's sub-component (`stakeholder`/`persona`);
changing a holder's relationships needs the same manage gate as editing that
holder (`stakeholder_owner`/`persona_owner` or the FGAC `manage` grant). A
target is only ever shown to a caller who may view its artefact type
(`(target_type, view)` FGAC atom) in an enabled module. Tenancy: a target must
belong to the request's project; anything else 404s so another tenant's ids look
absent. Targets come from `relationships.resolve_target`, never from a direct
import of the owning module.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import PermissionLevel
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _shared as psh
from app.modules.stakeholders import _stakeholder_shared as sh
from app.modules.stakeholders import relationships as rel
from app.modules.stakeholders._shared import apply_value_error_as_conflict, get_visible_holder, holder_name
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope
from app.modules.stakeholders.schemas import (
    IncomingRelationshipOut,
    RelationshipCreate,
    RelationshipKindOut,
    RelationshipOut,
    RelationshipTargetOut,
)
from app.modules.stakeholders.service import PERSONA_ARTEFACT_TYPE, STAKEHOLDER_ARTEFACT_TYPE
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.rbac import (
    get_effective_permissions,
    permission_satisfied,
    require_project_module_enabled,
    require_project_subcomponent_enabled,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/stakeholders", tags=["stakeholder-relationships-project"])

_require_module = require_project_module_enabled("stakeholders")
_require_stakeholder_view = require_project_subcomponent_enabled("stakeholders", "stakeholder")
_require_persona_view = require_project_subcomponent_enabled("stakeholders", "persona")


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _require_manage(db: Session, user: User, project: Project, holder_type: str) -> None:
    """The manage gate for the holder's artefact type (project scope)."""
    if holder_type == STAKEHOLDER_ARTEFACT_TYPE:
        sh.require_stakeholder_manage(
            db, user, StakeholderScope.PROJECT, organization_id=project.organization_id, project_id=project.id
        )
    else:
        psh.require_persona_manage(
            db, user, PersonaScope.PROJECT, organization_id=project.organization_id, project_id=project.id
        )


def _viewable_types(db: Session, user: User, project: Project) -> set[str]:
    """The target artefact types `user` may view in `project` (the FGAC
    `(type, view)` atom), so a relationship never leaks a title the caller could
    not read on the owning module's own screens."""
    held = get_effective_permissions(db, user.id, organization_id=project.organization_id, project_id=project.id)
    types = {t for kind in rel.RELATIONSHIP_KINDS for t in kind.target_types}
    return {t for t in types if permission_satisfied(held, encode_permission(t, PermissionLevel.VIEW.value))}


def _to_out(link, kind: rel.RelationshipKind, summary) -> RelationshipOut:
    return RelationshipOut(
        link_id=link.id, kind=kind.key, forward=kind.forward, target_type=link.target_type, target_id=summary.id,
        label=summary.label, status=summary.status, is_archived=summary.is_archived,
    )


# --- Kinds and the target picker ---------------------------------------------


@router.get("/relationship-kinds", response_model=list[RelationshipKindOut])
def list_relationship_kinds(project_id: UUID, current_user: User = Depends(_require_module), db: Session = Depends(get_db)):
    """The declared relationship kinds, with which target types are linkable now."""
    _project(db, project_id)
    return [
        RelationshipKindOut(
            key=k.key, forward=k.forward, reverse=k.reverse, holder_types=list(k.holder_types),
            target_types=list(k.target_types), available_target_types=list(rel.available_target_types(k)),
        )
        for k in rel.RELATIONSHIP_KINDS
    ]


@router.get("/relationship-targets", response_model=list[RelationshipTargetOut])
def list_relationship_targets(
    project_id: UUID, target_type: str, current_user: User = Depends(_require_module), db: Session = Depends(get_db),
):
    """The project's records of `target_type` a relationship can point at
    (404 for a type no kind targets, or one the caller may not view)."""
    project = _project(db, project_id)
    if target_type not in _viewable_types(db, current_user, project) or not rel.target_type_available(target_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such relationship target type.")
    return [
        RelationshipTargetOut(id=s.id, label=s.label, status=s.status)
        for s in rel.list_targets(db, project, target_type)
    ]


# --- A holder's relationships ------------------------------------------------


def _list(db: Session, user: User, project: Project, holder_type: str, holder_id: UUID) -> list[RelationshipOut]:
    holder = get_visible_holder(db, project, holder_type, holder_id)
    viewable = _viewable_types(db, user, project)
    return [
        _to_out(link, kind, summary)
        for link, kind, summary in rel.list_relationships(db, project, holder_type, holder.id)
        if link.target_type in viewable
    ]


def _add(
    db: Session, user: User, project: Project, holder_type: str, holder_id: UUID, payload: RelationshipCreate
) -> RelationshipOut:
    holder = get_visible_holder(db, project, holder_type, holder_id)
    _require_manage(db, user, project, holder_type)
    kind = rel.get_kind(payload.kind)
    if kind is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown relationship kind.")
    # An unavailable (reserved) target type has no provider, so reject it as a
    # conflict with the kind rather than as a missing record.
    if payload.target_type in kind.target_types and not rel.target_type_available(payload.target_type):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"\"{kind.forward}\" a {payload.target_type} is not available until that module is installed.",
        )
    if payload.target_type not in _viewable_types(db, user, project):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship target not found.")
    summary = rel.resolve_target(db, project, payload.target_type, payload.target_id)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship target not found.")
    link = apply_value_error_as_conflict(
        rel.add_relationship, db, holder_type, holder.id, kind, summary, payload.target_type, user,
        organization_id=project.organization_id, project_id=project.id,
    )
    log_event(db, entity_type=holder_type, entity_id=holder.id, action="relationship_added", actor_id=user.id,
              project_id=project.id, detail={"kind": kind.key, "target_type": payload.target_type, "target_id": str(summary.id)})
    db.commit()
    return _to_out(link, kind, summary)


def _remove(db: Session, user: User, project: Project, holder_type: str, holder_id: UUID, link_id: UUID) -> None:
    holder = get_visible_holder(db, project, holder_type, holder_id)
    _require_manage(db, user, project, holder_type)
    link = rel.find_link(db, project, holder_type, holder.id, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship not found.")
    detail = {"target_type": link.target_type, "target_id": str(link.target_id)}
    rel.remove_relationship(db, link)
    log_event(db, entity_type=holder_type, entity_id=holder.id, action="relationship_removed", actor_id=user.id,
              project_id=project.id, detail=detail)
    db.commit()


@router.get("/stakeholders/{stakeholder_id}/relationships", response_model=list[RelationshipOut])
def list_stakeholder_relationships(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_stakeholder_view),
    db: Session = Depends(get_db),
):
    """The Stakeholder's relationships to records of this project."""
    return _list(db, current_user, _project(db, project_id), STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id)


@router.post("/stakeholders/{stakeholder_id}/relationships", response_model=RelationshipOut, status_code=status.HTTP_201_CREATED)
def add_stakeholder_relationship(
    project_id: UUID, stakeholder_id: UUID, payload: RelationshipCreate,
    current_user: User = Depends(_require_stakeholder_view), db: Session = Depends(get_db),
):
    """Adds a relationship from the Stakeholder to a record of this project (409 on a duplicate or an unavailable target)."""
    return _add(db, current_user, _project(db, project_id), STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id, payload)


@router.delete("/stakeholders/{stakeholder_id}/relationships/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_stakeholder_relationship(
    project_id: UUID, stakeholder_id: UUID, link_id: UUID,
    current_user: User = Depends(_require_stakeholder_view), db: Session = Depends(get_db),
):
    _remove(db, current_user, _project(db, project_id), STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id, link_id)


@router.get("/personas/{persona_id}/relationships", response_model=list[RelationshipOut])
def list_persona_relationships(
    project_id: UUID, persona_id: UUID, current_user: User = Depends(_require_persona_view), db: Session = Depends(get_db),
):
    """The Persona's relationships to records of this project."""
    return _list(db, current_user, _project(db, project_id), PERSONA_ARTEFACT_TYPE, persona_id)


@router.post("/personas/{persona_id}/relationships", response_model=RelationshipOut, status_code=status.HTTP_201_CREATED)
def add_persona_relationship(
    project_id: UUID, persona_id: UUID, payload: RelationshipCreate,
    current_user: User = Depends(_require_persona_view), db: Session = Depends(get_db),
):
    """Adds a relationship from the Persona to a record of this project (409 on a duplicate or an unavailable target)."""
    return _add(db, current_user, _project(db, project_id), PERSONA_ARTEFACT_TYPE, persona_id, payload)


@router.delete("/personas/{persona_id}/relationships/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_persona_relationship(
    project_id: UUID, persona_id: UUID, link_id: UUID,
    current_user: User = Depends(_require_persona_view), db: Session = Depends(get_db),
):
    _remove(db, current_user, _project(db, project_id), PERSONA_ARTEFACT_TYPE, persona_id, link_id)


# --- The reverse view --------------------------------------------------------


@router.get("/relationships/incoming", response_model=list[IncomingRelationshipOut])
def list_incoming_relationships(
    project_id: UUID, target_type: str, target_id: UUID,
    current_user: User = Depends(_require_module), db: Session = Depends(get_db),
):
    """The Stakeholders and Personas (visible to this project) that have a
    relationship to one record of this project — "who experiences this Pain
    Point / provides this Requirement / was consulted on this Decision"."""
    project = _project(db, project_id)
    if target_type not in _viewable_types(db, current_user, project):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship target not found.")
    if rel.resolve_target(db, project, target_type, target_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship target not found.")
    out = []
    for link, kind, holder_type, holder in rel.list_incoming(db, project, target_type, target_id):
        try:
            get_visible_holder(db, project, holder_type, holder.id)
        except HTTPException:
            continue
        out.append(IncomingRelationshipOut(
            link_id=link.id, kind=kind.key, reverse=kind.reverse, holder_type=holder_type, holder_id=holder.id,
            holder_name=holder_name(db, holder_type, holder), scope=holder.scope.value,
        ))
    return out
