"""
Module: modules.architecture.reports_drawing

The reports that carry a drawing a custom report layout can embed: AR5 Diagram (one architecture diagram) and AR7 State
machines (the states and transitions of each element's state machine diagrams, and one diagram's drawing).

Design decisions (Decided by: Agent):
- **The drawing is the server SVG, not a second drawing.** `diagram_svg.render_diagram` and
  `state_machine_svg.render_state_machine` are the functions the SVG endpoints call, on the same resolved view or model
  (`diagram_view.build_view`, `state_machines.model_of`), so a report shows what the screen and the export show. It is
  a `ReportSection.drawing`: the document and a layout widget print it as a picture.
- **A drawing needs a name.** Without the `diagram` / `state_machine` parameter (a code or a name) the report has no
  drawing and says so in a note, rather than guessing which of many diagrams is meant.
- **Beside every drawing, a table of what it shows,** because the screen, CSV and JSON carry no picture and a picture
  alone is not readable by assistive technology.
- **Visibility is the reader's.** The view is built for the person the report runs for (`report_support.viewer_for`), so
  an element they cannot read is a locked placeholder and appears in the tables only as "Shared element". A diagram or
  state machine diagram whose element they cannot read is not found.
- Default toggle states and no retired connections, as the SVG endpoint does with no query.

Dependencies: `diagram_view`, `diagram_svg`, `state_machines`, `state_machine_svg`, `report_support`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.architecture import diagrams, state_machines
from app.modules.architecture.diagram_svg import render_diagram
from app.modules.architecture.diagram_view import build_view
from app.modules.architecture.labels import STATE_KIND_LABEL, record_status_label
from app.modules.architecture.models import ArchitectureState
from app.modules.architecture.report_support import SHARED, element_text, project_elements, viewer_for
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    STATE_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_SUBCOMPONENT_KEY,
)
from app.modules.architecture.state_machine_svg import render_state_machine
from app.modules.architecture.visibility import Viewer
from app.modules.registry import ReportDefinition, ReportParamDefinition, ReportPartDefinition
from app.services.report_framework import ReportContext, ReportMetric, ReportResult, ReportSection

MODULE_KEY = ARCHITECTURE_MODULE_KEY
ELEMENT_COLUMNS = ["Element", "Type", "Status", "Project"]
LINE_COLUMNS = ["From", "To", "Type", "Connections", "Project"]
MACHINE_COLUMNS = ["State machine diagram", "Element", "Status", "States", "Transitions", "Project"]
STATE_COLUMNS = ["State machine diagram", "State", "Kind", "Parent", "Entry action", "Exit action", "Activity", "Project"]
TRANSITION_COLUMNS = ["State machine diagram", "From", "To", "Event", "Guard", "Action", "Project"]
_CLIP = 200


def _matches(wanted: str, code: str, name: str) -> bool:
    """Whether a code or a name equals `wanted` (case-insensitive)."""
    return wanted.casefold() in (code.casefold(), name.casefold())


def collect_diagram(db: Session, req: ReportContext) -> ReportResult:
    """AR5 — one diagram as a drawing, with the elements and lines it shows.

    Args:
        db: Database session.
        req: The request; `diagram` (a code, such as `DGM-002`, or a name) picks the diagram.

    Returns:
        The report; `data` is `{"nodes": int, "lines": int, "drawn": bool}`.
    """
    projects = req.eligible(db, DIAGRAM_SUBCOMPONENT_KEY)
    wanted = (req.params.get("diagram") or "").strip()
    element_rows: list[list[str]] = []
    line_rows: list[list[str]] = []
    drawing: str | None = None
    for project in projects:
        found = next((d for d in diagrams.list_diagrams(db, project.id) if wanted and _matches(wanted, d.unique_code, d.name)), None)
        if found is None:
            continue
        view = build_view(db, project.id, viewer_for(db, req, project), found)
        drawing = drawing or render_diagram(db, view)
        owned = project_elements(db, project.id)
        node_text: dict[uuid.UUID, str] = {}
        for node in view.nodes:
            own = node.element_id in owned and not node.locked and not node.shared
            node_text[node.element_id] = element_text(req, project.id, owned, node.element_id) if own else SHARED
            if not node.hidden:
                element_rows.append([
                    node_text[node.element_id], node.element_type_name if own else "", record_status_label(node.status) if own else "", project.name,
                ])
        for edge in view.edges:
            line_rows.append([
                node_text.get(edge.source_element_id, SHARED), node_text.get(edge.target_element_id, SHARED),
                ", ".join(sorted({c.connection_type_name for c in edge.connections})),
                ", ".join(req.code(c.unique_code, project.id) for c in edge.connections), project.name,
            ])
    notes = [req.scope_note]
    if drawing is None:
        notes.append(
            "No diagram was drawn: set the diagram parameter to the code or name of a diagram you can read."
            if not wanted else f'No diagram called "{wanted}" was found.'
        )
    result = ReportResult(
        key="ar5", title="Diagram", scope_label=req.scope_label, generated_at=datetime.now(UTC), notes=notes,
        sections=[
            ReportSection("drawing", "Diagram", [], [], screen=False, drawing=drawing),
            ReportSection("elements", "Elements shown", ELEMENT_COLUMNS, element_rows),
            ReportSection("lines", "Lines shown", LINE_COLUMNS, line_rows),
        ],
        eligible_projects=len(projects),
    )
    result.metrics = [ReportMetric("Elements shown", len(element_rows)), ReportMetric("Lines shown", len(line_rows))]
    result.data = {"nodes": len(element_rows), "lines": len(line_rows), "drawn": drawing is not None}
    return result


def collect_state_machines(db: Session, req: ReportContext) -> ReportResult:
    """AR7 — the state machine diagrams, their states and transitions, and one diagram's drawing.

    Args:
        db: Database session.
        req: The request; `element` (a code or name) keeps the diagrams of that element, `state_machine` (a code or a name)
            picks the diagram to draw.

    Returns:
        The report; `data` is `{"diagrams": int, "states": int, "transitions": int, "drawn": bool}`.
    """
    projects = req.eligible(db, STATE_MACHINE_SUBCOMPONENT_KEY)
    only_element = (req.params.get("element") or "").strip()
    drawn_name = (req.params.get("state_machine") or "").strip()
    machine_rows: list[list[str]] = []
    state_rows: list[list[str]] = []
    transition_rows: list[list[str]] = []
    drawing: str | None = None
    for project in projects:
        viewer: Viewer = viewer_for(db, req, project)
        owned = project_elements(db, project.id)
        for machine in state_machines.list_state_machines(db, viewer, project.id):
            element = owned.get(machine.element_id)
            if only_element and (element is None or not _matches(only_element, element.unique_code, element.name)):
                continue
            states = state_machines.states_of(db, machine.id)
            transitions = state_machines.transitions_of(db, machine.id)
            label = f"{req.code(machine.unique_code, project.id)} {machine.name}".strip()
            machine_rows.append([
                label, element_text(req, project.id, owned, machine.element_id), record_status_label(machine.status),
                str(len(states)), str(len(transitions)), project.name,
            ])
            by_id: dict[uuid.UUID, ArchitectureState] = {s.id: s for s in states}

            def state_text(state_id: uuid.UUID, by_id=by_id, project_id=project.id) -> str:
                state = by_id.get(state_id)
                return f"{req.code(state.unique_code, project_id)} {state.name}".strip() if state is not None else ""

            for s in states:
                state_rows.append([
                    label, f"{req.code(s.unique_code, project.id)} {s.name}".strip(), STATE_KIND_LABEL.get(s.kind, s.kind),
                    state_text(s.parent_state_id) if s.parent_state_id else "", s.entry_action[:_CLIP], s.exit_action[:_CLIP],
                    s.activity[:_CLIP], project.name,
                ])
            for t in transitions:
                transition_rows.append([
                    label, state_text(t.source_state_id), state_text(t.target_state_id), t.event[:_CLIP], t.guard[:_CLIP],
                    t.action[:_CLIP], project.name,
                ])
            if drawing is None and drawn_name and _matches(drawn_name, machine.unique_code, machine.name):
                drawing = render_state_machine(state_machines.model_of(db, machine, viewer))
    notes = [req.scope_note]
    if drawn_name and drawing is None:
        notes.append(f'No state machine diagram called "{drawn_name}" was found.')
    elif not drawn_name:
        notes.append("To draw one diagram, set the state machine parameter to its code or name.")
    result = ReportResult(
        key="ar7", title="State machines", scope_label=req.scope_label, generated_at=datetime.now(UTC), notes=notes,
        sections=[
            ReportSection("machines", "State machine diagrams", MACHINE_COLUMNS, machine_rows),
            ReportSection("states", "States", STATE_COLUMNS, state_rows),
            ReportSection("transitions", "Transitions", TRANSITION_COLUMNS, transition_rows),
            ReportSection("drawing", "State machine diagram", [], [], screen=False, drawing=drawing),
        ],
        eligible_projects=len(projects),
    )
    result.metrics = [
        ReportMetric("State machine diagrams", len(machine_rows)), ReportMetric("States", len(state_rows)),
        ReportMetric("Transitions", len(transition_rows)),
    ]
    result.data = {
        "diagrams": len(machine_rows), "states": len(state_rows), "transitions": len(transition_rows), "drawn": drawing is not None,
    }
    return result


DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "ar5", "diagram", "Diagram", "One diagram drawn as the screen shows it, with the elements and lines it contains.",
        collect_diagram, subcomponent=DIAGRAM_SUBCOMPONENT_KEY,
        params=(
            ReportParamDefinition("diagram", "string", label="Diagram", description="The code (for example DGM-002) or name of the diagram to draw."),
        ),
        parts=(
            ReportPartDefinition("drawing", "Diagram drawing", "The diagram as a picture."),
            ReportPartDefinition("elements", "Elements shown"), ReportPartDefinition("lines", "Lines shown"),
        ),
        record_types=(DIAGRAM_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE),
    ),
    ReportDefinition(
        "ar7", "state-machines", "State machines",
        "The state machine diagrams of the elements, their states and transitions, and one diagram's drawing.",
        collect_state_machines, subcomponent=STATE_MACHINE_SUBCOMPONENT_KEY,
        params=(
            ReportParamDefinition("element", "string", label="Element", description="Only the diagrams of the element with this code or name."),
            ReportParamDefinition(
                "state_machine", "string", label="State machine diagram",
                description="The code (for example SMD-001) or name of the diagram to draw.",
            ),
        ),
        parts=(
            ReportPartDefinition("machines", "State machine diagrams"), ReportPartDefinition("states", "States"),
            ReportPartDefinition("transitions", "Transitions"),
            ReportPartDefinition("drawing", "State machine diagram drawing", "One diagram as a picture."),
        ),
        record_types=(STATE_MACHINE_ARTEFACT_TYPE, STATE_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE),
    ),
)
