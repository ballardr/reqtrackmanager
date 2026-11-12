"""
Module: modules.architecture.diagram_routes

The project-scoped endpoints for diagrams, added to the module's project router by `add_diagram_routes`: the diagram
record and its lifecycle, saving its layout and toggles, placing and unplacing one element, and reading it resolved
(JSON for the editor, SVG for documents).

Responsibilities:
- Declare the routes and translate `records.RuleError` to its HTTP status.
- Read the toggle overrides from the address (`toggle_on` / `toggle_off`), which the page keeps so a flipped toggle is
  not saved.
- Apply the list filters (`filter_diagrams`) the list and the record-table export share.

RBAC: reading needs project membership and the `architecture_diagram` sub-component to be enabled; every change needs
`_shared.require_architect` with the diagram manage atom. Every lookup is scoped to the project in the URL, so another
project's ids look absent, and the resolved view applies the visibility rules of the person reading.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import diagrams
from app.modules.architecture._shared import DIAGRAM_MANAGE_PERMISSION, require_architect
from app.modules.architecture.diagram_model import build_model
from app.modules.architecture.diagram_svg import render_diagram
from app.modules.architecture.diagram_view import ToggleState, build_view
from app.modules.architecture.enums import RecordStatus
from app.modules.architecture.models import ArchitectureDiagram
from app.modules.architecture.record_routes import _matches, as_http
from app.modules.architecture.schemas import (
    DiagramCreate,
    DiagramModel,
    DiagramOut,
    DiagramUpdate,
    DiagramView,
    LayoutSave,
    PlacementAdd,
    PlacementIn,
    StatusChange,
    TogglesSave,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_SUBCOMPONENT_KEY,
)
from app.modules.architecture.symbol_routes import SVG_HEADERS
from app.modules.architecture.visibility import Viewer
from app.services import report_images
from app.services.lookups import project_or_404
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_subcomponent_enabled
from app.services.tags import TagFilter


def filter_diagrams(
    rows: list[ArchitectureDiagram], *, status_: str | None = None, open_only: bool = False, search: str | None = None,
) -> list[ArchitectureDiagram]:
    """The diagrams the list's filters keep. `open_only` leaves out retired diagrams."""
    return [
        d for d in rows
        if (status_ is None or d.status == status_)
        and (not open_only or d.status != RecordStatus.RETIRED.value)
        and _matches(search, d.unique_code, d.name, d.purpose)
    ]


def add_diagram_routes(router: APIRouter) -> None:
    """Adds the diagram routes to `router` (the project router)."""
    view_diagrams = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, DIAGRAM_SUBCOMPONENT_KEY)

    def out(db: Session, diagram: ArchitectureDiagram, user: User, project_id: uuid.UUID) -> DiagramOut:
        return diagrams.diagram_outs(db, [diagram], Viewer.of_user(user, project_or_404(db, project_id)))[0]

    def resolved(
        db: Session, user: User, project_id: uuid.UUID, diagram_id: uuid.UUID, toggle_on: list[uuid.UUID],
        toggle_off: list[uuid.UUID], include_retired: bool,
    ) -> DiagramView:
        project = project_or_404(db, project_id)
        diagram = as_http(lambda: diagrams.get_diagram(db, project_id, diagram_id))
        return build_view(
            db, project_id, Viewer.of_user(user, project), diagram,
            state=ToggleState(frozenset(toggle_on), frozenset(toggle_off)), include_retired=include_retired,
        )

    @router.post("/diagrams", response_model=DiagramOut, status_code=status.HTTP_201_CREATED)
    def create_diagram(
        project_id: uuid.UUID, payload: DiagramCreate,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Creates a diagram (`draft`, or `active` with `activate`); `populate` places the scope's children. Needs the
        Architect role."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.create_diagram(db, project, current_user, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.get("/diagrams", response_model=list[DiagramOut])
    def list_diagrams(
        project_id: uuid.UUID, include_archived: bool = False, status_filter: RecordStatus | None = Query(None, alias="status"),
        open_only: bool = False, search: str | None = None, tag_filter: TagFilter = Depends(),
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
        project_scope: ProjectScope = Depends(),
    ):
        """The project's diagrams; archived ones only with `include_archived`."""
        request_project = project_or_404(db, project_id)

        def rows_for(pid: uuid.UUID) -> list[DiagramOut]:
            found = filter_diagrams(
                diagrams.list_diagrams(db, pid, include_archived=include_archived),
                status_=status_filter.value if status_filter else None, open_only=open_only, search=search,
            )
            return diagrams.diagram_outs(
                db, tag_filter.keep(db, pid, DIAGRAM_ARTEFACT_TYPE, found), Viewer.of_user(current_user, request_project),
            )

        return project_scope.collect(
            db, request_project, current_user.id, DIAGRAM_ARTEFACT_TYPE, rows_for,
            gate=(ARCHITECTURE_MODULE_KEY, DIAGRAM_SUBCOMPONENT_KEY),
        )

    @router.get("/diagrams/{diagram_id}", response_model=DiagramOut)
    def get_diagram(
        project_id: uuid.UUID, diagram_id: uuid.UUID,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """One diagram's record and counts."""
        return out(db, as_http(lambda: diagrams.get_diagram(db, project_id, diagram_id)), current_user, project_id)

    @router.get("/diagrams/{diagram_id}/view", response_model=DiagramView)
    def get_diagram_view(
        project_id: uuid.UUID, diagram_id: uuid.UUID, toggle_on: list[uuid.UUID] = Query(default=[]),
        toggle_off: list[uuid.UUID] = Query(default=[]), include_retired: bool = False,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """The diagram resolved for the caller: its nodes, lines (after toggles, bridging, roll-up and merging), notes
        and toggles. `toggle_on` / `toggle_off` override the saved default of a toggle for this read only."""
        return resolved(db, current_user, project_id, diagram_id, toggle_on, toggle_off, include_retired)

    @router.get("/diagrams/{diagram_id}/model", response_model=DiagramModel)
    def get_diagram_model(
        project_id: uuid.UUID, diagram_id: uuid.UUID,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """The data the diagram's lines are resolved from (elements, parents, connections, what each view switch hides),
        as the caller may read it, so the editor redraws lines while a layout is edited. Nothing is stored."""
        project = project_or_404(db, project_id)
        diagram = as_http(lambda: diagrams.get_diagram(db, project_id, diagram_id))
        return build_model(db, project_id, Viewer.of_user(current_user, project), diagram)

    @router.get("/diagrams/{diagram_id}/svg")
    def get_diagram_svg(
        project_id: uuid.UUID, diagram_id: uuid.UUID, toggle_on: list[uuid.UUID] = Query(default=[]),
        toggle_off: list[uuid.UUID] = Query(default=[]), include_retired: bool = False,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """The same resolved diagram as an SVG document, the drawing a report shows."""
        view = resolved(db, current_user, project_id, diagram_id, toggle_on, toggle_off, include_retired)
        return Response(
            content=render_diagram(db, view), media_type=report_images.SVG_TYPE,
            headers={**SVG_HEADERS, "Cache-Control": "private, no-store"},
        )

    @router.put("/diagrams/{diagram_id}", response_model=DiagramOut)
    def update_diagram(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: DiagramUpdate,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Edits a diagram's own fields; the body quotes the `version` it was based on (409 if stale)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.update_diagram(db, project, current_user, diagram_id, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.put("/diagrams/{diagram_id}/layout", response_model=DiagramOut)
    def save_layout(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: LayoutSave,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Replaces the diagram's placements and notes (the editor's save); an element left out is unplaced, never
        deleted. 409 if the `version` is stale."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.save_layout(db, project, current_user, diagram_id, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.put("/diagrams/{diagram_id}/toggles", response_model=DiagramOut)
    def save_toggles(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: TogglesSave,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Replaces the diagram's view toggles (name, default state, rule and manual members). 409 if the `version` is
        stale."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.save_toggles(db, project, current_user, diagram_id, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/diagrams/{diagram_id}/placements", response_model=DiagramOut, status_code=status.HTTP_201_CREATED)
    def add_placement(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: PlacementAdd,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Places one more element on the diagram (400 if it is already there or not available)."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        box = PlacementIn(**payload.model_dump(exclude={"version"}))
        diagram = as_http(lambda: diagrams.add_placement(db, project, current_user, diagram_id, payload.version, box))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.delete("/diagrams/{diagram_id}/placements/{element_id}", response_model=DiagramOut)
    def remove_placement(
        project_id: uuid.UUID, diagram_id: uuid.UUID, element_id: uuid.UUID, version: int,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Takes an element off the diagram. The element itself is never deleted."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.remove_placement(db, project_id, current_user, diagram_id, version, element_id))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/diagrams/{diagram_id}/status", response_model=DiagramOut)
    def change_diagram_status(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: StatusChange,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Moves a diagram to another status."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.change_diagram_status(
            db, project_id, current_user, diagram_id, payload.version, payload.status,
        ))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/diagrams/{diagram_id}/archive", response_model=DiagramOut)
    def archive_diagram(
        project_id: uuid.UUID, diagram_id: uuid.UUID,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Archives a diagram."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.set_diagram_archived(db, project_id, current_user, diagram_id, True))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/diagrams/{diagram_id}/unarchive", response_model=DiagramOut)
    def unarchive_diagram(
        project_id: uuid.UUID, diagram_id: uuid.UUID,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Restores an archived diagram."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        diagram = as_http(lambda: diagrams.set_diagram_archived(db, project_id, current_user, diagram_id, False))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.delete("/diagrams/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_diagram(
        project_id: uuid.UUID, diagram_id: uuid.UUID,
        current_user: User = Depends(view_diagrams), db: Session = Depends(get_db),
    ):
        """Deletes a diagram with its placements, notes and toggles; the model's elements and connections are untouched."""
        project = project_or_404(db, project_id)
        require_architect(db, current_user, project, DIAGRAM_MANAGE_PERMISSION)
        as_http(lambda: diagrams.delete_diagram(db, project_id, current_user, diagram_id))
        db.commit()

