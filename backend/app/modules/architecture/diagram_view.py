"""
Module: modules.architecture.diagram_view

Builds the resolved view of a diagram: the nodes, lines, toggles and notes a client draws and the server SVG renders.

Responsibilities:
- Load a diagram's placements, notes, toggles, the project's connections and every element involved in bulk, so the
  number of statements does not grow with the size of the diagram.
- Apply visibility: an element the viewer cannot read becomes a locked node (its code only) and is never matched by a
  toggle or bridged through.
- Evaluate each toggle's state (the saved default unless the request overrides it), find its members (manual members
  plus what its rule matches) and hand the plain ids to `diagram_resolver.resolve`.
- Shape the answer for the API (`DiagramView`).

Design decisions:
- **The viewer's project's connections only.** A connection belongs to the project that created it, so a diagram draws
  that project's connections, even where an end is an element another owner shares.
- **Retired and archived connections are left out** (retired only unless `include_retired`), as the lists' "Open only".
  A retired or archived *element* stays drawn, flagged by its status, since a diagram is a view of what was placed.
- **Rules are evaluated over every element the diagram involves** (placed elements and connection ends), so a transit
  element that is not itself placed can still be switched off and bridged through.
- **Nothing here reads a name the viewer may not see:** a locked node carries its code only, a connection to it comes
  from `records.connection_outs`, which blanks the locked end, and a symbol is offered only if `visible_symbol_ids`
  allows it.

Dependencies: `diagram_resolver`, `diagrams`, `records`, `visibility`, `symbols`; core `services.tags`.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture import diagrams, records
from app.modules.architecture.diagram_resolver import ModelConnection, Resolution, resolve
from app.modules.architecture.enums import ElementShape
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionType,
    ArchitectureDiagram,
    ArchitectureDiagramToggle,
    ArchitectureElement,
    ArchitectureElementType,
)
from app.modules.architecture.schemas import (
    DiagramView,
    NoteOut,
    ToggleOut,
    ToggleRule,
    ViewEdge,
    ViewHop,
    ViewNode,
    ViewPort,
)
from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.architecture.symbols import visible_symbol_ids
from app.modules.architecture.visibility import Viewer, ancestor_parents, visible_element_ids
from app.services import tags as tag_service


@dataclass(frozen=True)
class ToggleState:
    """Which toggles the request switches on or off, overriding each toggle's saved default.

    Attributes:
        on: Toggle ids forced on.
        off: Toggle ids forced off (wins over `on`).
    """

    on: frozenset[uuid.UUID] = frozenset()
    off: frozenset[uuid.UUID] = frozenset()

    def is_on(self, toggle: ArchitectureDiagramToggle) -> bool:
        """Whether the toggle is on: forced off, forced on, else its saved default."""
        if toggle.id in self.off:
            return False
        return toggle.id in self.on or toggle.default_on


def toggle_rule(toggle: ArchitectureDiagramToggle) -> ToggleRule:
    """The stored rule as the API shape (an unreadable stored value reads as an empty rule)."""
    try:
        return ToggleRule.model_validate(toggle.rule or {})
    except ValueError:
        return ToggleRule()


def matched_by_rules(
    rules: dict[uuid.UUID, ToggleRule], toggles_off: Collection[uuid.UUID], elements: dict[uuid.UUID, ArchitectureElement],
    connections: list[ArchitectureConnection], element_types: dict[uuid.UUID, ArchitectureElementType],
    connection_types: dict[uuid.UUID, ArchitectureConnectionType], element_tags: dict[uuid.UUID, list[str]],
    connection_tags: dict[uuid.UUID, list[str]],
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The elements and connections the switched-off toggles' rules match."""
    hidden_elements: set[uuid.UUID] = set()
    hidden_connections: set[uuid.UUID] = set()
    for toggle_id in toggles_off:
        rule = rules[toggle_id]
        type_ids, domains, tag_names = set(rule.element_type_ids), {d.value for d in rule.domains}, set(rule.tags)
        for element in elements.values():
            kind = element_types.get(element.element_type_id)
            if (
                element.element_type_id in type_ids or (kind is not None and kind.domain in domains)
                or tag_names.intersection(element_tags.get(element.id, ()))
            ):
                hidden_elements.add(element.id)
        connection_type_ids = set(rule.connection_type_ids)
        for connection in connections:
            connection_kind = connection_types.get(connection.connection_type_id)
            if (
                connection.connection_type_id in connection_type_ids
                or (connection_kind is not None and connection_kind.domain in domains)
                or tag_names.intersection(connection_tags.get(connection.id, ()))
            ):
                hidden_connections.add(connection.id)
    return hidden_elements, hidden_connections


def build_view(
    db: Session, project_id: uuid.UUID, viewer: Viewer, diagram: ArchitectureDiagram, *,
    state: ToggleState | None = None, include_retired: bool = False,
) -> DiagramView:
    """The diagram resolved for `viewer`.

    Args:
        db: Session.
        project_id: The diagram's project.
        viewer: Who is reading (applies the visibility rules).
        diagram: The diagram.
        state: Toggle overrides; none uses every toggle's saved default.
        include_retired: Also draw retired connections.

    Returns:
        The diagram's record, toggles with their state, nodes, lines and notes.
    """
    state = state or ToggleState()
    placements = diagrams.placements_of(db, diagram.id)
    notes = diagrams.notes_of(db, diagram.id)
    toggles = diagrams.toggles_of(db, diagram.id)
    members = diagrams.toggle_members(db, [t.id for t in toggles])

    connections = [
        c for c in records.list_connections(db, project_id)
        if include_retired or c.status != "retired"
    ]
    placed_ids = [p.element_id for p in placements]
    involved = set(placed_ids) | {c.source_element_id for c in connections} | {c.target_element_id for c in connections}
    elements = {
        e.id: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(involved)))
    } if involved else {}
    readable = visible_element_ids(db, viewer, involved)
    parents = ancestor_parents(db, involved)

    types = {
        t.id: t for t in db.scalars(select(ArchitectureElementType).where(
            ArchitectureElementType.id.in_({elements[i].element_type_id for i in readable if i in elements})
        ))
    } if readable else {}
    connection_types = {
        t.id: t for t in db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
        ))
    } if connections else {}

    rules = {t.id: toggle_rule(t) for t in toggles}
    off = [t.id for t in toggles if not state.is_on(t)]
    uses_tags = any(rules[t].tags for t in off)
    readable_elements = {i: elements[i] for i in readable if i in elements}
    element_tags: dict[uuid.UUID, list[str]] = {}
    connection_tags: dict[uuid.UUID, list[str]] = {}
    if uses_tags:
        if readable_elements:
            element_tags = tag_service.tag_names_for_records(db, ELEMENT_ARTEFACT_TYPE, readable_elements)
        if connections:
            connection_tags = tag_service.tag_names_for_records(db, CONNECTION_ARTEFACT_TYPE, [c.id for c in connections])
    hidden_elements, hidden_connections = matched_by_rules(
        rules, off, readable_elements, connections, types, connection_types, element_tags, connection_tags,
    )
    connection_ids = {c.id for c in connections}
    for toggle_id in off:
        for member in members.get(toggle_id, ()):
            if member.element_id is not None and member.element_id in readable_elements:
                hidden_elements.add(member.element_id)
            if member.connection_id is not None and member.connection_id in connection_ids:
                hidden_connections.add(member.connection_id)

    resolution = resolve(
        placed=placed_ids, parents=parents,
        connections=[
            ModelConnection(
                c.id, c.source_element_id, c.target_element_id, connection_types[c.connection_type_id].directional,
            )
            for c in connections if c.source_element_id in elements and c.target_element_id in elements
        ],
        hidden_elements=hidden_elements, hidden_connections=hidden_connections,
        merge_parallel=not diagram.connection_detail,
    )

    return DiagramView(
        diagram=diagrams.diagram_outs(db, [diagram], viewer)[0],
        toggles=_toggle_outs(toggles, members, rules, state),
        nodes=_nodes(db, viewer, placements, elements, readable, types, resolution, hidden_elements, parents),
        edges=_edges(db, viewer, diagram, connections, connection_types, elements, readable, resolution),
        notes=[NoteOut(id=n.id, text=n.text, x=n.x, y=n.y, width=n.width, height=n.height) for n in notes],
    )


def _toggle_outs(toggles, members, rules, state: ToggleState) -> list[ToggleOut]:
    """The toggles with their state in this view and their manual members."""
    return [
        ToggleOut(
            id=t.id, name=t.name, default_on=t.default_on, on=state.is_on(t), rule=rules[t.id],
            element_ids=[m.element_id for m in members.get(t.id, ()) if m.element_id is not None],
            connection_ids=[m.connection_id for m in members.get(t.id, ()) if m.connection_id is not None],
            sort_order=t.sort_order,
        )
        for t in toggles
    ]


def _nodes(
    db: Session, viewer: Viewer, placements, elements, readable, types, resolution: Resolution, hidden_elements,
    parents,
) -> list[ViewNode]:
    """The placed elements as drawn: locked ones carry a code only."""
    readable_placed = [elements[p.element_id] for p in placements if p.element_id in readable and p.element_id in elements]
    ports = records.ports_for(db, [e.id for e in readable_placed])
    port_type_ids = {p.connection_type_id for ps in ports.values() for p in ps if p.connection_type_id}
    port_types = {
        t.id: t.name for t in db.scalars(select(ArchitectureConnectionType).where(ArchitectureConnectionType.id.in_(port_type_ids)))
    } if port_type_ids else {}
    wanted_symbols: set[uuid.UUID] = set()
    for e in readable_placed:
        drawn = e.symbol_id or (types[e.element_type_id].symbol_id if e.element_type_id in types else None)
        if drawn is not None:
            wanted_symbols.add(drawn)
    symbol_ok = visible_symbol_ids(db, viewer, wanted_symbols)

    nodes: list[ViewNode] = []
    for p in placements:
        element = elements.get(p.element_id)
        if element is None:
            continue
        internal = list(resolution.internal.get(element.id, ()))
        box = {"x": p.x, "y": p.y, "width": p.width, "height": p.height, "collapsed": p.collapsed}
        if element.id not in readable:
            nodes.append(ViewNode(
                placement_id=p.id, element_id=element.id, unique_code=element.unique_code, name="", locked=True, shared=False,
                hidden=False, status="", parent_id=None, element_type_id=None, element_type_name="",
                shape=ElementShape.RECTANGLE.value, color_light=None, color_dark=None, symbol_id=None, ports=[],
                internal_connection_ids=internal, **box,
            ))
            continue
        kind = types.get(element.element_type_id)
        symbol_id = element.symbol_id or (kind.symbol_id if kind is not None else None)
        nodes.append(ViewNode(
            placement_id=p.id, element_id=element.id, unique_code=element.unique_code, name=element.name, locked=False,
            shared=element.project_id != viewer.project_id, hidden=element.id in resolution.hidden_placed,
            status=element.status, parent_id=element.parent_id, element_type_id=element.element_type_id,
            element_type_name=kind.name if kind is not None else "",
            shape=kind.shape if kind is not None else ElementShape.RECTANGLE.value,
            color_light=kind.color_light if kind is not None else None, color_dark=kind.color_dark if kind is not None else None,
            symbol_id=symbol_id if symbol_id in symbol_ok else None,
            ports=[
                ViewPort(
                    id=port.id, name=port.name, direction=port.direction,
                    connection_type_name=port_types.get(port.connection_type_id) if port.connection_type_id else None,
                )
                for port in ports.get(element.id, ())
            ],
            internal_connection_ids=internal, **box,
        ))
    return nodes


def _edge_label(count: int, type_name: str | None, protocol: str) -> str | None:
    """The text on a line when connection detail is on."""
    if count == 1:
        return f"{type_name} · {protocol}" if type_name and protocol else (type_name or protocol or None)
    return f"{type_name} ×{count}" if type_name else f"{count} connections"


def _edges(
    db: Session, viewer: Viewer, diagram: ArchitectureDiagram, connections, connection_types, elements, readable,
    resolution: Resolution,
) -> list[ViewEdge]:
    """The lines to draw, each with the connections behind it (as the viewer may read them)."""
    by_id = {c.id: c for c in connections}
    used = [by_id[i] for line in resolution.lines for i in line.connection_ids if i in by_id]
    outs = {o.id: o for o in records.connection_outs(db, list({c.id: c for c in used}.values()), viewer)} if used else {}
    hop_ids = {h for line in resolution.lines for h in line.hops}
    edges: list[ViewEdge] = []
    for line in resolution.lines:
        members = [outs[i] for i in line.connection_ids if i in outs]
        type_ids = {m.connection_type_id for m in members}
        kind = connection_types.get(next(iter(type_ids))) if len(type_ids) == 1 else None
        detail = diagram.connection_detail
        protocols = {m.protocol for m in members}
        edges.append(ViewEdge(
            id=f"{line.source_id}-{line.target_id}-{line.connection_ids[0]}", source_element_id=line.source_id,
            target_element_id=line.target_id, two_way=line.two_way, indirect=line.indirect, rolled_up=line.rolled_up,
            bridged=line.bridged, count=len(members),
            type_name=kind.name if detail and kind is not None else None,
            line_style=kind.line_style if detail and kind is not None else None,
            color_light=kind.color_light if detail and kind is not None else None,
            color_dark=kind.color_dark if detail and kind is not None else None,
            label=_edge_label(len(members), kind.name if kind is not None else None, next(iter(protocols)) if len(protocols) == 1 else "")
            if detail else None,
            connections=members,
            hops=[
                ViewHop(element_id=h, unique_code=elements[h].unique_code, name=elements[h].name)
                for h in line.hops if h in hop_ids and h in elements and h in readable
            ],
        ))
    return edges
