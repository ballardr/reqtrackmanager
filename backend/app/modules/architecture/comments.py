"""
Module: modules.architecture.comments

Opts the three architecture types into the generic record comments (`services.record_comments`) and gives each its
`/comments` route under the module's own path.

Responsibilities:
- `RECORD_COMMENTS`: the `RecordCommentProvider` of each type. A diagram's threads may be pinned to a free spot, a box
  (an element placed on it) or a line (a connection of its project); an element or connection takes ordinary
  comments only.
- `add_comment_routes`: `GET` and `POST <kind>/{id}/comments` for a type, behind the type's sub-component gate, so a
  project with the module or sub-component off answers 404. They return the same thread as the generic API
  (`routers.record_comments`); editing, resolving and moving go through the generic routes.

Design decisions:
- A `node` key is an element id and an `edge` key a connection id, never a canvas-local id: a drawn line may be a
  rolled-up or bridged one, and the browser anchors a comment to one of its underlying connections, so the key stays
  true when the drawing changes.

External dependencies: `services.record_comments`, `routers.record_comments`, `modules.registry`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture.models import ArchitectureConnection, ArchitectureDiagramPlacement
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
)
from app.modules.registry import RecordCommentProvider
from app.routers import record_comments as generic
from app.schemas.record_comments import CommentCreate, RecordThreadOut
from app.services.rbac import require_project_subcomponent_enabled


def _as_uuid(key: str) -> uuid.UUID | None:
    """The key as a UUID, or `None` when it is not one."""
    try:
        return uuid.UUID(key)
    except ValueError:
        return None


def validate_diagram_anchor(db: Session, project_id: uuid.UUID, diagram_id: uuid.UUID, kind: str, key: str) -> bool:
    """Whether a diagram's pin may anchor to `key`: an element placed on the diagram (`node`) or a connection of the
    diagram's project (`edge`)."""
    target = _as_uuid(key)
    if target is None:
        return False
    if kind == "node":
        return db.scalar(
            select(ArchitectureDiagramPlacement.id).where(
                ArchitectureDiagramPlacement.diagram_id == diagram_id, ArchitectureDiagramPlacement.element_id == target
            )
        ) is not None
    if kind == "edge":
        return db.scalar(
            select(ArchitectureConnection.id).where(
                ArchitectureConnection.id == target, ArchitectureConnection.project_id == project_id
            )
        ) is not None
    return False


RECORD_COMMENTS: dict[str, RecordCommentProvider] = {
    ELEMENT_ARTEFACT_TYPE: RecordCommentProvider(),
    CONNECTION_ARTEFACT_TYPE: RecordCommentProvider(),
    DIAGRAM_ARTEFACT_TYPE: RecordCommentProvider(
        anchor_kinds=("node", "edge"), validate_anchor=validate_diagram_anchor
    ),
}


def add_comment_routes(router: APIRouter) -> None:
    """Adds `GET`/`POST` `{elements,connections,diagrams}/{id}/comments` to the module's project router."""
    for path, artefact_type, subcomponent in (
        ("elements", ELEMENT_ARTEFACT_TYPE, ELEMENT_SUBCOMPONENT_KEY),
        ("connections", CONNECTION_ARTEFACT_TYPE, CONNECTION_SUBCOMPONENT_KEY),
        ("diagrams", DIAGRAM_ARTEFACT_TYPE, DIAGRAM_SUBCOMPONENT_KEY),
    ):
        gate = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, subcomponent)
        _add(router, path, artefact_type, gate)


def _add(router: APIRouter, path: str, artefact_type: str, gate) -> None:
    """Adds the two routes of one type (a function, so each closure keeps its own type and gate)."""

    @router.get(f"/{path}/{{record_id}}/comments", response_model=RecordThreadOut, name=f"list_{path}_comments")
    def list_comments(
        project_id: uuid.UUID, record_id: uuid.UUID, current_user: User = Depends(gate), db: Session = Depends(get_db),
    ) -> RecordThreadOut:
        """The record's comments, pinned threads and pins (as the generic API returns them)."""
        return generic.get_record_comments(project_id, artefact_type, record_id, current_user, db)

    @router.post(
        f"/{path}/{{record_id}}/comments", response_model=RecordThreadOut, status_code=status.HTTP_201_CREATED,
        name=f"add_{path}_comment",
    )
    def add_comment(
        project_id: uuid.UUID, record_id: uuid.UUID, payload: CommentCreate, current_user: User = Depends(gate),
        db: Session = Depends(get_db),
    ) -> RecordThreadOut:
        """Adds a comment to the record (as the generic API does)."""
        return generic.add_record_comment(project_id, artefact_type, record_id, payload, current_user, db)
