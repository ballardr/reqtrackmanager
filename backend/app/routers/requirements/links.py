"""
Module: routers.requirements.links

Requirement-to-requirement traceability links (C-G-09): create/list/delete,
each subject to the project's opt-in "approved requirements need a change
request to add/remove a link" rule.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.routers.requirements.core import _get_requirement_in_project, _require_edit_role
from app.schemas.requirement import RequirementLinkCreate, RequirementLinkOut
from app.services.audit import log_event
from app.services.link_type_scope import UNAVAILABLE_MESSAGE, assert_link_type_usable
from app.services.link_types import LinkRuleError
from app.services.rbac import require_project_view
from app.services.relationships import create_link as create_artefact_link
from app.services.relationships import delete_link as delete_artefact_link
from app.services.relationships import get_all_links as get_all_artefact_links
from app.services.requirements import get_current_version, is_locked, requires_change_request_for_links

router = APIRouter(tags=["requirements-links"])


def _links_to_out(db: Session, links: list[ArtefactLink], viewpoint_requirement_id: UUID) -> list[RequirementLinkOut]:
    """Resolves `ArtefactLink`s (requirement-to-requirement, per this
    endpoint's own scope) into the API shape from the perspective of
    `viewpoint_requirement_id` — whichever requirement `GET
    /{requirement_id}/links` was called for. Direction and the
    other-requirement's display fields can only be resolved server-side
    (per-request), since a link row alone doesn't say which end the caller
    is looking from (see `schemas.requirement.RequirementLinkOut`'s
    docstring).

    `source_id`/`target_id` here are read as requirement ids — this
    endpoint only ever creates/lists links where both
    `source_type`/`target_type` are `ArtefactType.REQUIREMENT` (see
    `create_link` below), so that's a safe assumption for any row this
    function is handed.

    The link types, the other requirements and their current versions are
    each loaded in one statement for the whole list, so a hub requirement
    with hundreds of links costs the same number of statements as one with two.
    """
    other_ids = {
        link.target_id if link.source_id == viewpoint_requirement_id else link.source_id for link in links
    }
    link_types = {
        t.id: t for t in db.scalars(select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.id.in_({link.link_type_id for link in links})))
    } if links else {}
    others = {
        r.id: r for r in db.scalars(select(Requirement).where(Requirement.id.in_(other_ids)))
    } if other_ids else {}
    names = {
        v.requirement_id: v.name for v in db.scalars(select(RequirementVersion).where(
            RequirementVersion.requirement_id.in_(other_ids), RequirementVersion.valid_to.is_(None)))
    } if other_ids else {}
    out = []
    for link in links:
        link_type = link_types.get(link.link_type_id)
        if link.source_id == viewpoint_requirement_id:
            direction = "outgoing"
            display_name = link_type.forward_name if link_type is not None else ""
            other_id = link.target_id
        else:
            direction = "incoming"
            display_name = link_type.reverse_name if link_type is not None else ""
            other_id = link.source_id
        other = others.get(other_id)
        out.append(RequirementLinkOut(
            id=link.id, source_requirement_id=link.source_id, target_requirement_id=link.target_id,
            link_type_id=link.link_type_id, direction=direction, display_name=display_name,
            other_requirement_id=other_id,
            other_requirement_unique_code=other.unique_code if other is not None else "",
            other_requirement_name=names.get(other_id, ""),
        ))
    return out


@router.post("/{requirement_id}/links", response_model=RequirementLinkOut, status_code=status.HTTP_201_CREATED)
def create_link(
    project_id: UUID, requirement_id: UUID, payload: RequirementLinkCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Creates a traceability link between two requirements (C-G-09).

    Not gated by either requirement's lock state by default — see
    `models.relationship.ArtefactLink`'s docstring for why traceability
    metadata sits outside C-G-12's change-log boundary. Platform review
    2026-09
    deliberately supersedes that default for a project (or org) that opts
    in: once `requirement_id`'s current version is locked (approved) *and*
    `services.requirements.requires_change_request_for_links` is true for
    this project, adding a link must go through an `ADD_LINK` change
    request instead — see `routers.change_requests.create_change_request`.
    """
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)) and requires_change_request_for_links(db, project):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved and this project requires links to be added via a change request.",
        )
    target = _get_requirement_in_project(db, project_id, payload.target_requirement_id)
    link_type = db.get(RequirementLinkTypeDefinition, payload.link_type_id)
    if link_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, UNAVAILABLE_MESSAGE)
    try:
        assert_link_type_usable(db, project, link_type, enforce_offered=True)
        link = create_artefact_link(
            db, source_type=ArtefactType.REQUIREMENT, source_id=requirement_id,
            target_type=ArtefactType.REQUIREMENT, target_id=target.id,
            link_type_id=payload.link_type_id, created_by=current_user.id,
            project_id=project_id, enforce_offered=True,
        )
    except LinkRuleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="requirement_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"source_requirement_id": str(requirement_id), "target_requirement_id": str(target.id),
                      "link_type_id": str(payload.link_type_id)})
    db.commit()
    db.refresh(link)
    return _links_to_out(db, [link], requirement_id)[0]


@router.get("/{requirement_id}/links", response_model=list[RequirementLinkOut])
def list_links(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    _get_requirement_in_project(db, project_id, requirement_id)
    # `get_all_artefact_links` returns every link touching this requirement
    # in either direction, which also includes untyped `ArtefactLink` rows
    # where a `RequirementAction` links to this requirement (`link_action`,
    # in `routers.requirements.actions`) — those aren't requirement-to-
    # requirement traceability links, so they're filtered out here rather
    # than by `link_type_id is not None` alone, to stay correct even if a
    # future artefact type ever adds its own typed link to a requirement.
    links = [
        link for link in get_all_artefact_links(db, ArtefactType.REQUIREMENT, requirement_id)
        if link.source_type == ArtefactType.REQUIREMENT and link.target_type == ArtefactType.REQUIREMENT
    ]
    return _links_to_out(db, links, requirement_id)


@router.delete("/{requirement_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(
    project_id: UUID, requirement_id: UUID, link_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Removes a traceability link. 404s unless `link_id`'s source or
    target is `requirement_id` — deletable from either end, not just the
    end it was created from.

    Same opt-in gate as `create_link`,
    above — checked against `requirement_id` (the endpoint's own scoped
    requirement), not whichever end the link's other requirement happens to
    be in.
    """
    _require_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    requirement = _get_requirement_in_project(db, project_id, requirement_id)
    if is_locked(get_current_version(db, requirement.id)) and requires_change_request_for_links(db, project):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This requirement is approved and this project requires links to be removed via a change request.",
        )
    link = db.get(ArtefactLink, link_id)
    if (
        link is None
        or link.source_type != ArtefactType.REQUIREMENT
        or link.target_type != ArtefactType.REQUIREMENT
        or requirement_id not in (link.source_id, link.target_id)
        or link.source_project_id is not None  # a cross-level link is removed through the generic endpoint
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    log_event(db, entity_type="requirement_link", entity_id=link.id, action="deleted",
              actor_id=current_user.id, project_id=project_id,
              detail={"source_requirement_id": str(link.source_id),
                      "target_requirement_id": str(link.target_id)})
    delete_artefact_link(db, link)
    db.commit()
