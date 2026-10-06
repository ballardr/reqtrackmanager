"""
Module: routers.artefact_links

Links on any artefact of a project:
- `GET .../{type}/{id}/link-graph`: the records linked to it out to a few hops,
  with edge direction resolved against the organisation's link-type settings.
- `GET .../{type}/{id}/link-types`: the link types usable from it.
- `POST .../{type}/{id}/links` and `DELETE .../{type}/{id}/links/{link_id}`:
  generic link authoring from either end, whatever the artefact types.

This router is the authorisation point: project membership is checked here, and
the services then authorise every record (same project or visible org record,
module enabled, `view` permission; `manage` on the page artefact's type for
writes), so a hidden record is counted but never revealed or traversed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_artefact_type_label
from app.schemas.artefact_links import (
    ArtefactLinkCreate,
    ArtefactLinkOtherEnd,
    ArtefactLinkOut,
    ArtefactLinkTypeOption,
    LinkOrientation,
)
from app.schemas.link_graph import LinkGraphDirection, LinkGraphOut
from app.schemas.link_type import ArtefactTypeOut
from app.services.link_authoring import (
    create_link_for_artefact,
    delete_link_for_artefact,
    require_visible_artefact,
    usable_options,
)
from app.services.link_graph import MAX_DEPTH, build_link_graph
from app.services.link_types import ensure_org_seeds
from app.services.rbac import require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefacts", tags=["artefact-links"])


@router.get("/{artefact_type}/{artefact_id}/link-graph", response_model=LinkGraphOut)
def get_artefact_link_graph(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    depth: int = Query(2, ge=1, le=MAX_DEPTH, description="Hops to follow from the artefact."),
    direction: LinkGraphDirection = Query(LinkGraphDirection.BOTH, description="Which stored link orientations to follow."),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> LinkGraphOut:
    """Returns the link graph around one artefact of the project.

    Args:
        project_id: The project; the caller must be a member.
        artefact_type: A registered artefact type (`requirement`, `decision`, ...).
        artefact_id: The artefact's id.
        depth: Hops to follow (1-3).
        direction: `outgoing`, `incoming` or `both`.

    Returns:
        The root, the visible nodes and edges, whether the node cap truncated
        the result, and how many linked records were not shown.

    Raises:
        HTTPException: 404 if the type is unregistered or the artefact is not a
            visible record of this project (indistinguishable by design).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    graph = build_link_graph(
        db, project=project, user_id=current_user.id, root_type=artefact_type, root_id=artefact_id,
        depth=depth, direction=direction,
    )
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    return graph


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, or 404 (membership is checked separately by the route dependency)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


@router.get("/{artefact_type}/{artefact_id}/link-types", response_model=list[ArtefactLinkTypeOption])
def list_artefact_link_types(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    other_type: str | None = Query(None, description="Only options that can reach this artefact type."),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> list[ArtefactLinkTypeOption]:
    """The link types usable from this artefact, with orientation, the phrase to
    show and the artefact types reachable at the other end.

    Types a link-type restriction or either end's artefact-type rule rules out
    are left out, as are dedicated types (made with their own action). Missing
    module-seeded types are created first.

    Raises:
        HTTPException: 404 if the artefact is not a visible record of the project.
    """
    project = _project_or_404(db, project_id)
    require_visible_artefact(db, project, current_user.id, artefact_type, artefact_id)
    ensure_org_seeds(db, project.organization_id)
    db.commit()
    return [
        ArtefactLinkTypeOption(
            link_type_id=option.link_type.id, forward_name=option.link_type.forward_name,
            reverse_name=option.link_type.reverse_name, flow=option.link_type.flow,
            direction=LinkOrientation.OUTGOING if option.outgoing else LinkOrientation.INCOMING,
            phrase=option.phrase,
            other_types=[ArtefactTypeOut(type=t, label=get_artefact_type_label(t)) for t in option.other_types],
        )
        for option in usable_options(db, project, artefact_type, other_type)
    ]


@router.post("/{artefact_type}/{artefact_id}/links", response_model=ArtefactLinkOut, status_code=status.HTTP_201_CREATED)
def create_artefact_link(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    payload: ArtefactLinkCreate,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ArtefactLinkOut:
    """Links this artefact to another record of the project, from either end.

    Raises:
        HTTPException: 404 an end is not a visible record of the project; 403
            `manage` on this artefact type not held; 400 the link type is unusable
            here (other organisation, dedicated, or a link-type restriction or
            artefact-type rule forbids the pair) or a self-link; 409 duplicate or
            a change request is required for an approved requirement.
    """
    project = _project_or_404(db, project_id)
    created = create_link_for_artefact(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        link_type_id=payload.link_type_id, outgoing=payload.direction is LinkOrientation.OUTGOING,
        other_type=payload.other_type, other_id=payload.other_id,
    )
    db.commit()
    return ArtefactLinkOut(
        id=created.link.id, link_type_id=created.link_type.id,
        phrase=created.link_type.forward_name if created.outgoing else created.link_type.reverse_name,
        direction=LinkOrientation.OUTGOING if created.outgoing else LinkOrientation.INCOMING,
        other=ArtefactLinkOtherEnd(
            type=created.other_type, id=created.other.id, type_label=get_artefact_type_label(created.other_type),
            label=created.other.label, status=created.other.status, is_archived=created.other.is_archived,
        ),
    )


@router.delete("/{artefact_type}/{artefact_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artefact_link(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    link_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Removes a link touching this artefact.

    Raises:
        HTTPException: 404 the artefact is not visible or the link does not touch
            it; 403 `manage` not held; 400 the link belongs to a dedicated action;
            409 a change request is required for an approved requirement.
    """
    project = _project_or_404(db, project_id)
    delete_link_for_artefact(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        link_id=link_id,
    )
    db.commit()
