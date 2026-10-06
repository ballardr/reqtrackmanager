"""
Module: routers.artefact_links

Read-only link graph for any artefact (`GET /projects/{id}/artefacts/{type}/
{id}/link-graph`): the records linked to it out to a few hops, with edge
direction resolved against the organisation's link-type settings.

This router is the authorisation point for the traversal: project membership
is checked here, and `services.link_graph` then authorises every record it
returns (same project or visible org record, module enabled, `view`
permission), so a hidden record is counted but never revealed or traversed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.link_graph import LinkGraphDirection, LinkGraphOut
from app.services.link_graph import MAX_DEPTH, build_link_graph
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
