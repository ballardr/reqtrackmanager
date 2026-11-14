"""
Module: modules.architecture.structurizr

Structurizr DSL export: a project's elements, relationships and diagrams as one `workspace`, for the Structurizr tools.
Export only; the module does not read the format (JSON interchange is the round trip, see `interchange`).

Responsibilities:
- `render_workspace`: the DSL text for a project as the caller may read it, optionally for one diagram and with toggle
  states named in the request.

Design decisions (all Decided by: Agent, the format being fixed by Decided by: User):
- **Levels follow the element tree.** An element with no parent is a `softwareSystem`, its children are `container`s and
  everything deeper a `component` (the model has three levels; a deeper
  element is attached to the second-level element it sits under and keeps its own code, so nothing is dropped).
- **A relationship is one connection.** Its description is the connection's name (else its type), its technology the
  protocol; the code, type, direction and ports are properties. A two-way connection is one relationship with a
  `direction` property, because the format has no two-way relationship. A connection between an element and one of its
  own descendants is not written (Structurizr forbids it) and is counted in the header comment.
- **One view per diagram, drawn from the resolved view** (`diagram_view.build_view`, so toggles, bridging and roll-up are
  the screen's). The view type follows the elements shown: all top-level gives a `systemLandscape`; all siblings under
  one system a `container` view; all siblings under one container a `component` view; a mixed diagram a
  `systemLandscape` of the systems that contain its elements, with a comment saying so. Layout is automatic: box
  positions are not carried.
- **Nothing the caller cannot read, and no hidden element, is named.** Only elements the project owns that are not
  archived, retired or rejected are written; a connection to another owner's element is counted, not written, and a
  box a toggle hides is left out of its view.
- **Text is quoted and cleaned.** Every string is one line, with quotes and backslashes escaped and control characters
  removed, so a name cannot start a new statement. Identifiers are derived from codes, never from names.
- Deterministic: records are written in code order.

Dependencies: `diagram_view`, `report_support`, this module's models and labels.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.architecture import diagrams
from app.modules.architecture.diagram_view import ToggleState, build_view
from app.modules.architecture.labels import INACTIVE_STATUSES, record_status_label
from app.modules.architecture.models import (
    ArchitectureConnectionType,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitecturePort,
)
from app.modules.architecture.report_support import chain_of, live_connections, project_elements
from app.modules.architecture.visibility import Viewer

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_TEXT_LIMIT = 500
_LEVEL_KIND = ("softwareSystem", "container", "component")


def _q(value: str | None, limit: int = _TEXT_LIMIT) -> str:
    """A DSL string literal: one line, control characters removed, quotes and backslashes escaped, clipped to `limit`."""
    text = _CONTROL.sub(" ", value or "").strip()[:limit]
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ident(code: str) -> str:
    """The identifier of a record: derived from its code (`ELM-003` gives `e_elm003`), never from a name."""
    return "e_" + re.sub(r"[^a-z0-9]", "", code.lower())


def _levels(elements: dict[uuid.UUID, ArchitectureElement]) -> dict[uuid.UUID, int]:
    """Depth of each element within `elements` (0 for one with no parent among them)."""
    parents = {i: (e.parent_id if e.parent_id in elements else None) for i, e in elements.items()}
    return {i: len(chain_of(parents, i)) - 1 for i in elements}


def render_workspace(
    db: Session, project: Project, viewer: Viewer, *, diagram_id: uuid.UUID | None = None,
    toggle_on: frozenset[uuid.UUID] = frozenset(), toggle_off: frozenset[uuid.UUID] = frozenset(),
) -> str:
    """The project as a Structurizr DSL workspace.

    Args:
        db: Database session (read only).
        project: The project exported.
        viewer: Who exports (applies the diagram view's visibility rules).
        diagram_id: Only this diagram's view; `None` writes a view for every diagram that is neither archived nor retired.
        toggle_on: Diagram toggle ids forced on for the views.
        toggle_off: Diagram toggle ids forced off (wins over `toggle_on`); with neither, each toggle's saved state applies.

    Returns:
        The DSL text, ending in a newline.
    """
    owned = {i: e for i, e in project_elements(db, project.id).items() if e.status not in INACTIVE_STATUSES}
    levels = _levels(owned)
    parents = {i: (e.parent_id if e.parent_id in owned else None) for i, e in owned.items()}
    types = {t.id: t.name for t in db.scalars(select(ArchitectureElementType).where(
        ArchitectureElementType.id.in_({e.element_type_id for e in owned.values()})
    ))} if owned else {}
    ports: dict[uuid.UUID, list[ArchitecturePort]] = defaultdict(list)
    if owned:
        for port in db.scalars(
            select(ArchitecturePort).where(ArchitecturePort.element_id.in_(owned))
            .order_by(ArchitecturePort.sort_order, ArchitecturePort.name)
        ):
            ports[port.element_id].append(port)
    connections = live_connections(db, project.id)
    connection_types = {t.id: t for t in db.scalars(select(ArchitectureConnectionType).where(
        ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
    ))} if connections else {}

    # A component deeper than the third level is written under its second-level ancestor, so the model keeps three levels.
    def home(element_id: uuid.UUID) -> uuid.UUID | None:
        if levels[element_id] <= 2:
            return parents[element_id]
        return chain_of(parents, element_id)[levels[element_id] - 1]

    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for element_id in owned:
        children[home(element_id)].append(element_id)
    for kids in children.values():
        kids.sort(key=lambda i: owned[i].unique_code)

    pairs = []
    skipped_foreign = skipped_nested = 0
    for c in connections:
        if c.source_element_id not in owned or c.target_element_id not in owned:
            skipped_foreign += 1
        elif c.source_element_id in chain_of(parents, c.target_element_id) or c.target_element_id in chain_of(parents, c.source_element_id):
            skipped_nested += 1
        else:
            pairs.append(c)

    lines: list[str] = [
        f"// System Architecture export of {project.name} ({project.code}). Generated; positions are not carried.",
    ]
    if skipped_foreign or skipped_nested:
        lines.append(
            f"// Not written: {skipped_foreign} connection(s) with an end this project does not own or that is retired, "
            f"and {skipped_nested} connection(s) between an element and one inside it."
        )
    lines += [f"workspace {_q(project.name, 200)} {_q('Exported from System Architecture.', 200)} {{", "", "    model {"]

    def write(element_id: uuid.UUID, indent: int) -> None:
        e = owned[element_id]
        pad = "    " * indent
        kind = _LEVEL_KIND[min(levels[element_id], 2)]
        lines.append(f"{pad}{_ident(e.unique_code)} = {kind} {_q(e.name, 200)} {_q(e.description)} {_q(types.get(e.element_type_id, ''), 100)} {{")
        props = [("code", e.unique_code), ("status", record_status_label(e.status))]
        if levels[element_id] > 2:
            props.append(("level", str(levels[element_id] + 1)))
        props += [(f"port {p.name}", p.direction) for p in ports.get(element_id, [])]
        lines.append(f"{pad}    properties {{")
        lines.extend(f"{pad}        {_q(k, 100)} {_q(v, 200)}" for k, v in props)
        lines.append(f"{pad}    }}")
        for child in children.get(element_id, []):
            write(child, indent + 1)
        lines.append(f"{pad}}}")

    for root in children.get(None, []):
        write(root, 2)
    lines.append("")
    for c in pairs:
        kind = connection_types.get(c.connection_type_id)
        lines.append(
            f"        {_ident(owned[c.source_element_id].unique_code)} -> {_ident(owned[c.target_element_id].unique_code)} "
            f"{_q(c.name or (kind.name if kind else ''), 200)} {_q(c.protocol, 100)} {{"
        )
        props = [("code", c.unique_code), ("type", kind.name if kind else ""), ("direction", "one-way" if kind and kind.directional else "two-way")]
        lines.append("            properties {")
        lines += [f"                {_q(k, 100)} {_q(v, 200)}" for k, v in props]
        lines += ["            }", "        }"]
    lines += ["    }", "", "    views {"]

    state = ToggleState(toggle_on, toggle_off)
    for diagram in diagrams.list_diagrams(db, project.id):
        if diagram.status in INACTIVE_STATUSES or (diagram_id is not None and diagram.id != diagram_id):
            continue
        view = build_view(db, project.id, viewer, diagram, state=state)
        shown = sorted(
            (n.element_id for n in view.nodes if not n.hidden and not n.locked and not n.shared and n.element_id in owned),
            key=lambda i: owned[i].unique_code,
        )
        title = _q(f"{diagram.unique_code} {diagram.name}", 200)
        key = _q(diagram.unique_code, 64)
        kinds = {levels[i] for i in shown}
        shared_parent = {parents[i] for i in shown}
        only_parent = next(iter(shared_parent)) if len(shared_parent) == 1 else None
        if not shown:
            lines.append(f"        // {diagram.unique_code} shows no element this export may name.")
            continue
        if kinds == {0}:
            header, members = f"systemLandscape {key} {title}", shown
        elif kinds == {1} and only_parent is not None:
            header, members = f"container {_ident(owned[only_parent].unique_code)} {key} {title}", shown
        elif kinds == {2} and only_parent is not None:
            header, members = f"component {_ident(owned[only_parent].unique_code)} {key} {title}", shown
        else:
            roots = sorted({chain_of(parents, i)[-1] for i in shown}, key=lambda i: owned[i].unique_code)
            lines.append(f"        // {diagram.unique_code} mixes levels, so its view shows the systems that contain its elements.")
            header, members = f"systemLandscape {key} {title}", roots
        lines.append(f"        {header} {{")
        lines += [f"            include {_ident(owned[i].unique_code)}" for i in members]
        lines += ["            autolayout lr", "        }"]
    lines += ["    }", "}", ""]
    return "\n".join(lines)
