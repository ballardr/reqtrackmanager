"""
Module: modules.architecture.state_machine_routes

The project-scoped endpoints for state machine diagrams, added to the module's project router by
`add_state_machine_routes`: the diagram record and its lifecycle, its states and transitions, saving its layout, and
reading it whole (the editor's model) or one state at a time (the project-wide States list).

Responsibilities:
- Declare the routes and translate `records.RuleError` to its HTTP status.
- Apply the list filters (`filter_state_machines`, `filter_states`) the lists and the record-table export share.
- Serve the diagram as SVG and as Mermaid text (`state_machine_svg`, `state_machine_mermaid`), read through the same gate
  as the model.

RBAC: reading needs project membership and the `architecture_state_machine` sub-component to be enabled; every change
needs `_shared.require_architect` with the state machine diagram manage atom. Every lookup is scoped to the project in
the URL, so another project's ids look absent, and every read applies the visibility rules of the person reading (a
diagram of an element the person cannot read answers 404).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import state_machines as machines
from app.modules.architecture._shared import STATE_MACHINE_MANAGE_PERMISSION, require_architect
from app.modules.architecture.enums import RecordStatus, StateKind
from app.modules.architecture.models import ArchitectureState, ArchitectureStateMachineDiagram
from app.modules.architecture.record_routes import _matches, as_http
from app.modules.architecture.schemas import (
    StateCreate,
    StateMachineDiagramCreate,
    StateMachineDiagramOut,
    StateMachineDiagramUpdate,
    StateMachineLayoutSave,
    StateMachineModel,
    StateOut,
    StateUpdate,
    StatusChange,
    TransitionIn,
    TransitionOut,
)
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    STATE_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_SUBCOMPONENT_KEY,
)
from app.modules.architecture.state_machine_mermaid import render_state_machine_mermaid
from app.modules.architecture.state_machine_svg import render_state_machine
from app.modules.architecture.symbol_routes import SVG_HEADERS
from app.modules.architecture.visibility import Viewer
from app.services import report_images
from app.services.lookups import project_or_404
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_subcomponent_enabled
from app.services.tags import TagFilter


def filter_states(
    rows: list[ArchitectureState], codes: dict[uuid.UUID, str], *, kind: str | None = None, search: str | None = None,
    state_machine_diagram_id: uuid.UUID | None = None,
) -> list[ArchitectureState]:
    """The states the list's filters keep; `codes` maps a diagram id to its code, which the search also matches."""
    return [
        s for s in rows
        if (kind is None or s.kind == kind)
        and (state_machine_diagram_id is None or s.state_machine_diagram_id == state_machine_diagram_id)
        and _matches(
            search, s.unique_code, s.name, s.description, s.entry_action, s.exit_action, s.activity,
            codes.get(s.state_machine_diagram_id, ""),
        )
    ]


def add_state_machine_routes(router: APIRouter) -> None:
    """Adds the state machine diagram, state and transition routes to `router` (the project router)."""
    view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, STATE_MACHINE_SUBCOMPONENT_KEY)

    def viewer_of(db: Session, user: User, project_id: uuid.UUID) -> Viewer:
        return Viewer.of_user(user, project_or_404(db, project_id))

    def out(db: Session, diagram, user: User, project_id: uuid.UUID) -> StateMachineDiagramOut:
        return machines.state_machine_outs(db, [diagram], viewer_of(db, user, project_id))[0]

    def _version_of(db: Session, diagram_id: uuid.UUID) -> int:
        row = db.get(ArchitectureStateMachineDiagram, diagram_id)
        assert row is not None
        return row.version

    def manage(db: Session, user: User, project_id: uuid.UUID):
        project = project_or_404(db, project_id)
        require_architect(db, user, project, STATE_MACHINE_MANAGE_PERMISSION)
        return project

    # --- Diagrams ----------------------------------------------------------

    @router.post("/state-machine-diagrams", response_model=StateMachineDiagramOut, status_code=status.HTTP_201_CREATED)
    def create_state_machine(
        project_id: uuid.UUID, payload: StateMachineDiagramCreate, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Creates a state machine diagram (`draft`, or `active` with `activate`, refused while the checks find an error).
        Needs the Architect role."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.create_state_machine(db, project, current_user, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.get("/state-machine-diagrams", response_model=list[StateMachineDiagramOut])
    def list_state_machines(
        project_id: uuid.UUID, include_archived: bool = False, status_filter: RecordStatus | None = Query(None, alias="status"),
        open_only: bool = False, search: str | None = None, element_id: uuid.UUID | None = None,
        tag_filter: TagFilter = Depends(), current_user: User = Depends(view), db: Session = Depends(get_db),
        project_scope: ProjectScope = Depends(),
    ):
        """The project's state machine diagrams (whose element the caller may read); archived ones only with
        `include_archived`."""
        request_project = project_or_404(db, project_id)
        viewer = Viewer.of_user(current_user, request_project)

        def rows_for(pid: uuid.UUID) -> list[StateMachineDiagramOut]:
            found = machines.filter_state_machines(
                machines.list_state_machines(db, viewer, pid, include_archived=include_archived),
                status_=status_filter.value if status_filter else None, open_only=open_only, search=search, element_id=element_id,
            )
            return machines.state_machine_outs(db, tag_filter.keep(db, pid, STATE_MACHINE_ARTEFACT_TYPE, found), viewer)

        return project_scope.collect(
            db, request_project, current_user.id, STATE_MACHINE_ARTEFACT_TYPE, rows_for,
            gate=(ARCHITECTURE_MODULE_KEY, STATE_MACHINE_SUBCOMPONENT_KEY),
        )

    @router.get("/state-machine-diagrams/{diagram_id}", response_model=StateMachineDiagramOut)
    def get_state_machine(
        project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """One state machine diagram's record, counts and finding counts."""
        viewer = viewer_of(db, current_user, project_id)
        return out(db, as_http(lambda: machines.get_state_machine(db, viewer, project_id, diagram_id)), current_user, project_id)

    @router.get("/state-machine-diagrams/{diagram_id}/model", response_model=StateMachineModel)
    def get_model(
        project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The diagram with its states, transitions and modelling findings, as the caller may read it."""
        viewer = viewer_of(db, current_user, project_id)
        diagram = as_http(lambda: machines.get_state_machine(db, viewer, project_id, diagram_id))
        return machines.model_of(db, diagram, viewer)

    @router.get("/state-machine-diagrams/{diagram_id}/svg")
    def get_svg(
        project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The diagram as an SVG document (UML state machine notation), the file the editor's Export downloads."""
        viewer = viewer_of(db, current_user, project_id)
        diagram = as_http(lambda: machines.get_state_machine(db, viewer, project_id, diagram_id))
        return Response(
            content=render_state_machine(machines.model_of(db, diagram, viewer)), media_type=report_images.SVG_TYPE,
            headers={**SVG_HEADERS, "Cache-Control": "private, no-store"},
        )

    @router.get("/state-machine-diagrams/{diagram_id}/mermaid")
    def get_mermaid(
        project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The diagram as Mermaid `stateDiagram-v2` text (plain text, for pasting into documentation)."""
        viewer = viewer_of(db, current_user, project_id)
        diagram = as_http(lambda: machines.get_state_machine(db, viewer, project_id, diagram_id))
        return Response(
            content=render_state_machine_mermaid(machines.model_of(db, diagram, viewer)), media_type="text/plain; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )

    @router.put("/state-machine-diagrams/{diagram_id}", response_model=StateMachineDiagramOut)
    def update_state_machine(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: StateMachineDiagramUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Edits a diagram's own fields; the body quotes the `version` it was based on (409 if stale)."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.update_state_machine(db, project, current_user, diagram_id, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.put("/state-machine-diagrams/{diagram_id}/layout", response_model=StateMachineDiagramOut)
    def save_layout(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: StateMachineLayoutSave,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Saves the boxes and nesting of the states named and the attach points of the transitions named. 409 if the
        `version` is stale."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.save_layout(db, project, current_user, diagram_id, payload))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/state-machine-diagrams/{diagram_id}/status", response_model=StateMachineDiagramOut)
    def change_status(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: StatusChange,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Moves a diagram to another status; the move to `active` is refused (409) while the checks find an error."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.change_state_machine_status(
            db, project, current_user, diagram_id, payload.version, payload.status,
        ))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/state-machine-diagrams/{diagram_id}/archive", response_model=StateMachineDiagramOut)
    def archive(project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """Archives a state machine diagram."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.set_state_machine_archived(db, project, current_user, diagram_id, True))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.post("/state-machine-diagrams/{diagram_id}/unarchive", response_model=StateMachineDiagramOut)
    def unarchive(project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """Restores an archived state machine diagram."""
        project = manage(db, current_user, project_id)
        diagram = as_http(lambda: machines.set_state_machine_archived(db, project, current_user, diagram_id, False))
        db.commit()
        return out(db, diagram, current_user, project_id)

    @router.delete("/state-machine-diagrams/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_state_machine(project_id: uuid.UUID, diagram_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """Deletes a diagram with its states and transitions; the element it describes is untouched."""
        project = manage(db, current_user, project_id)
        as_http(lambda: machines.delete_state_machine(db, project, current_user, diagram_id))
        db.commit()

    # --- States ------------------------------------------------------------

    @router.post(
        "/state-machine-diagrams/{diagram_id}/states", response_model=StateOut, status_code=status.HTTP_201_CREATED,
    )
    def add_state(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: StateCreate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Adds a state (or an initial, final or choice marker); the body quotes the diagram's `version`."""
        project = manage(db, current_user, project_id)
        state = as_http(lambda: machines.add_state(db, project, current_user, diagram_id, payload))
        db.commit()
        return machines.state_outs(db, [state], viewer_of(db, current_user, project_id))[0]

    @router.get("/states", response_model=list[StateOut])
    def list_states(
        project_id: uuid.UUID, include_archived: bool = False, kind: StateKind | None = None, search: str | None = None,
        state_machine_diagram_id: uuid.UUID | None = None, tag_filter: TagFilter = Depends(),
        current_user: User = Depends(view), db: Session = Depends(get_db), project_scope: ProjectScope = Depends(),
    ):
        """The states of the project's state machine diagrams (those whose element the caller may read)."""
        request_project = project_or_404(db, project_id)
        viewer = Viewer.of_user(current_user, request_project)

        def rows_for(pid: uuid.UUID) -> list[StateOut]:
            diagrams = machines.list_state_machines(db, viewer, pid, include_archived=include_archived)
            codes = {d.id: d.unique_code for d in diagrams}
            states = machines.states_of_many(db, codes)
            found = filter_states(
                states, codes, kind=kind.value if kind else None, search=search, state_machine_diagram_id=state_machine_diagram_id,
            )
            return machines.state_outs(db, tag_filter.keep(db, pid, STATE_ARTEFACT_TYPE, found), viewer)

        return project_scope.collect(
            db, request_project, current_user.id, STATE_ARTEFACT_TYPE, rows_for,
            gate=(ARCHITECTURE_MODULE_KEY, STATE_MACHINE_SUBCOMPONENT_KEY),
        )

    @router.get("/states/{state_id}", response_model=StateOut)
    def get_state(project_id: uuid.UUID, state_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """One state."""
        viewer = viewer_of(db, current_user, project_id)
        state, _diagram = as_http(lambda: machines.get_state(db, viewer, project_id, state_id))
        return machines.state_outs(db, [state], viewer)[0]

    @router.get("/states/{state_id}/impact")
    def state_impact(project_id: uuid.UUID, state_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)) -> dict[str, int]:
        """How many transitions and links deleting the state would remove, for the confirmation."""
        state, _diagram = as_http(lambda: machines.get_state(db, viewer_of(db, current_user, project_id), project_id, state_id))
        return machines.impact_of_state(db, state)

    @router.put("/states/{state_id}", response_model=StateOut)
    def update_state(
        project_id: uuid.UUID, state_id: uuid.UUID, payload: StateUpdate,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Edits a state; the body quotes the diagram's `version` (409 if stale)."""
        project = manage(db, current_user, project_id)
        state = as_http(lambda: machines.update_state(db, project, current_user, state_id, payload))
        db.commit()
        return machines.state_outs(db, [state], viewer_of(db, current_user, project_id))[0]

    @router.delete("/states/{state_id}")
    def delete_state(
        project_id: uuid.UUID, state_id: uuid.UUID, version: int,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ) -> dict[str, int]:
        """Deletes a state with its transitions and links; 409 while it contains other states or the `version` is stale.
        Answers what went with it and the diagram's new `version`."""
        project = manage(db, current_user, project_id)
        impact = as_http(lambda: machines.delete_state(db, project, current_user, state_id, version))
        db.commit()
        return impact

    # --- Transitions -------------------------------------------------------

    @router.post(
        "/state-machine-diagrams/{diagram_id}/transitions", response_model=TransitionOut, status_code=status.HTTP_201_CREATED,
    )
    def add_transition(
        project_id: uuid.UUID, diagram_id: uuid.UUID, payload: TransitionIn,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Adds a transition between two states of the diagram."""
        project = manage(db, current_user, project_id)
        transition = as_http(lambda: machines.add_transition(db, project, current_user, diagram_id, payload))
        db.commit()
        return machines.transition_outs([transition], machines.states_of(db, diagram_id), _version_of(db, diagram_id))[0]

    @router.put("/state-machine-diagrams/{diagram_id}/transitions/{transition_id}", response_model=TransitionOut)
    def update_transition(
        project_id: uuid.UUID, diagram_id: uuid.UUID, transition_id: uuid.UUID, payload: TransitionIn,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Edits a transition; the body quotes the diagram's `version` (409 if stale)."""
        project = manage(db, current_user, project_id)
        transition = as_http(lambda: machines.update_transition(db, project, current_user, diagram_id, transition_id, payload))
        db.commit()
        return machines.transition_outs([transition], machines.states_of(db, diagram_id), _version_of(db, diagram_id))[0]

    @router.delete("/state-machine-diagrams/{diagram_id}/transitions/{transition_id}")
    def delete_transition(
        project_id: uuid.UUID, diagram_id: uuid.UUID, transition_id: uuid.UUID, version: int,
        current_user: User = Depends(view), db: Session = Depends(get_db),
    ) -> dict[str, int]:
        """Deletes a transition; answers the diagram's new `version`."""
        project = manage(db, current_user, project_id)
        new_version = as_http(lambda: machines.delete_transition(db, project, current_user, diagram_id, transition_id, version))
        db.commit()
        return {"version": new_version}
