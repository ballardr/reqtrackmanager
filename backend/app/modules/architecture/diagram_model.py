"""
Module: modules.architecture.diagram_model

The model data a diagram's lines are resolved from, handed to the editor so it can redraw lines instantly while a layout
is being edited (a box added, a view switch flipped) without a round trip.

Responsibilities:
- Load, in bulk, the elements a diagram could draw (those placed, the project's own, those shared with it, and every
  connection end), their parents, the project's live connections and the connection types.
- Resolve each toggle to the elements and connections it switches off, by the same rule matching `build_view` uses, so
  the browser only combines plain ids and never evaluates a rule.
- Apply visibility: an element the viewer cannot read is a locked entry carrying its code only, and a connection to it
  comes from `records.connection_outs`, which blanks the locked end.

Design decisions:
- **The server still decides what a person may see; the browser only decides which lines to draw.** Nothing here is
  stored, and the layout the browser saves is validated by `diagrams.save_layout`, so a wrong line drawn in the browser can
  never change stored data. `diagram_view.build_view` stays the authority for the first load, the SVG and documents.
- **Parent ids of an element the viewer cannot read are included.** The resolver rolls a connection up through an
  ancestor, as the server does, so the chain has to be whole; the ids are the ones the connection the viewer may read
  already names, and no name or type comes with them.
- **Realisations are listed whole** (both connections live), so the browser can join a realising connection to its
  boundary box the way `diagram_resolver.resolve` does; the stored boxes themselves come with the view.
- **Retired connections are left out and retired or archived elements stay**, as in the view: a diagram is a view of
  what was placed.

Dependencies: `diagram_view`, `diagrams`, `records`, `visibility`, `symbols`; core `services.tags`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture import diagrams, records
from app.modules.architecture.diagram_view import matched_by_rules, rule_type_closure, toggle_rule
from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionType,
    ArchitectureDiagram,
    ArchitectureDiagramToggle,
    ArchitectureDiagramToggleMember,
    ArchitectureElement,
    ArchitectureElementType,
)
from app.modules.architecture.realisations import project_realisations
from app.modules.architecture.schemas import (
    DiagramModel,
    ModelConnectionType,
    ModelElement,
    ModelRealisation,
    ModelToggleMembers,
)
from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.architecture.symbols import visible_symbol_ids
from app.modules.architecture.visibility import Viewer, ancestor_parents, granted_element_ids, visible_element_ids
from app.services import tags as tag_service


def build_model(db: Session, project_id: uuid.UUID, viewer: Viewer, diagram: ArchitectureDiagram) -> DiagramModel:
    """The data the diagram's lines are resolved from, as `viewer` may read it.

    Args:
        db: Session.
        project_id: The diagram's project.
        viewer: Who is reading (applies the visibility rules).
        diagram: The diagram (its toggles are resolved).

    Returns:
        The elements, parents, connections, connection types and each toggle's switched-off members.
    """
    placed = {p.element_id for p in diagrams.placements_of(db, diagram.id)}
    toggles = diagrams.toggles_of(db, diagram.id)
    members = diagrams.toggle_members(db, [t.id for t in toggles])
    connections = [c for c in records.list_connections(db, project_id) if c.status not in INACTIVE_STATUSES]
    live_ids = {c.id for c in connections}
    ends = {c.source_element_id for c in connections} | {c.target_element_id for c in connections}

    # The project's own elements and those shared with it are listed so the editor can place any of them; an archived
    # one is listed only when it is already on the diagram or an end of a connection.
    candidates = {e.id for e in records.list_elements(db, project_id)} | granted_element_ids(db, viewer)
    involved = placed | ends | candidates
    elements = {
        e.id: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.id.in_(involved)))
    } if involved else {}
    elements = {i: e for i, e in elements.items() if not e.is_archived or i in placed or i in ends}
    readable = visible_element_ids(db, viewer, elements)
    parents = ancestor_parents(db, elements)

    element_types = {
        t.id: t for t in db.scalars(select(ArchitectureElementType).where(
            ArchitectureElementType.id.in_({elements[i].element_type_id for i in readable})
        ))
    } if readable else {}
    connection_types = {
        t.id: t for t in db.scalars(select(ArchitectureConnectionType).where(
            ArchitectureConnectionType.id.in_({c.connection_type_id for c in connections})
        ))
    } if connections else {}
    symbols = visible_symbol_ids(db, viewer, {
        symbol for i in readable if (symbol := _drawn_symbol(elements[i], element_types)) is not None
    })

    return DiagramModel(
        elements=[
            _model_element(e, i in readable, element_types, symbols, viewer) for i, e in sorted(
                elements.items(), key=lambda item: item[1].unique_code,
            )
        ],
        parents=parents,
        connections=records.connection_outs(db, connections, viewer),
        connection_types=[
            ModelConnectionType(
                id=t.id, name=t.name, directional=t.directional, line_style=t.line_style,
                color_light=t.color_light, color_dark=t.color_dark,
            )
            for t in connection_types.values()
        ],
        toggle_members=_toggle_members(
            db, toggles, members, {i: elements[i] for i in readable}, connections, element_types, connection_types,
        ),
        realisations=[
            ModelRealisation(inner_connection_id=r.inner_connection_id, outer_connection_id=r.outer_connection_id)
            for r in project_realisations(db, project_id)
            if r.inner_connection_id in live_ids and r.outer_connection_id in live_ids
        ],
    )


def _drawn_symbol(element: ArchitectureElement, element_types: dict[uuid.UUID, ArchitectureElementType]) -> uuid.UUID | None:
    """The symbol an element is drawn with: its own, else its type's."""
    kind = element_types.get(element.element_type_id)
    return element.symbol_id or (kind.symbol_id if kind is not None else None)


def _model_element(
    element: ArchitectureElement, is_readable: bool, element_types: dict[uuid.UUID, ArchitectureElementType],
    symbols: set[uuid.UUID], viewer: Viewer,
) -> ModelElement:
    """One element as the editor needs it.

    Args:
        element: The element.
        is_readable: False when the viewer cannot read it; the entry then carries its code only.
        element_types: The element types of the readable elements.
        symbols: The symbol ids the viewer may read.
        viewer: Who is reading, to tell an element shared from another owner.

    Returns:
        The editor's entry for the element.
    """
    if not is_readable:
        return ModelElement(
            id=element.id, unique_code=element.unique_code, name="", locked=True, shared=False, status="",
            element_type_id=None, element_type_name="", color_light=None, color_dark=None, symbol_id=None,
        )
    kind = element_types.get(element.element_type_id)
    symbol_id = _drawn_symbol(element, element_types)
    return ModelElement(
        id=element.id, unique_code=element.unique_code, name=element.name, locked=False,
        shared=element.project_id != viewer.project_id, status=element.status, element_type_id=element.element_type_id,
        element_type_name=kind.name if kind is not None else "",
        color_light=kind.color_light if kind is not None else None,
        color_dark=kind.color_dark if kind is not None else None,
        symbol_id=symbol_id if symbol_id in symbols else None,
    )


def _toggle_members(
    db: Session, toggles: list[ArchitectureDiagramToggle],
    members: dict[uuid.UUID, list[ArchitectureDiagramToggleMember]],
    readable_elements: dict[uuid.UUID, ArchitectureElement], connections: list[ArchitectureConnection],
    element_types: dict[uuid.UUID, ArchitectureElementType], connection_types: dict[uuid.UUID, ArchitectureConnectionType],
) -> list[ModelToggleMembers]:
    """For each toggle, the elements and connections it switches off: what its rule matches plus its manual members.

    Args:
        db: Session.
        toggles: The diagram's toggles.
        members: Each toggle's manual members.
        readable_elements: The elements the viewer can read (a rule never matches an unreadable one).
        connections: The live connections.
        element_types: Element types by id.
        connection_types: Connection types by id.

    Returns:
        One entry per toggle, in the toggles' order.
    """
    rules = {t.id: toggle_rule(t) for t in toggles}
    element_tags: dict[uuid.UUID, list[str]] = {}
    connection_tags: dict[uuid.UUID, list[str]] = {}
    if any(rule.tags for rule in rules.values()):
        if readable_elements:
            element_tags = tag_service.tag_names_for_records(db, ELEMENT_ARTEFACT_TYPE, readable_elements)
        if connections:
            connection_tags = tag_service.tag_names_for_records(db, CONNECTION_ARTEFACT_TYPE, [c.id for c in connections])
    connection_ids = {c.id for c in connections}
    type_closure = rule_type_closure(db, rules.values())
    out: list[ModelToggleMembers] = []
    for toggle in toggles:
        hidden_elements, hidden_connections = matched_by_rules(
            rules, [toggle.id], readable_elements, connections, element_types, connection_types, element_tags,
            connection_tags, type_closure,
        )
        for member in members.get(toggle.id, ()):
            if member.element_id is not None and member.element_id in readable_elements:
                hidden_elements.add(member.element_id)
            if member.connection_id is not None and member.connection_id in connection_ids:
                hidden_connections.add(member.connection_id)
        out.append(ModelToggleMembers(
            toggle_id=toggle.id, element_ids=sorted(hidden_elements, key=str), connection_ids=sorted(hidden_connections, key=str),
        ))
    return out
