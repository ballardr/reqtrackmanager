"""
Module: modules.architecture.perf_dataset

Dataset generators for the `architecture_element`, `architecture_connection`, `architecture_diagram`,
`architecture_state_machine_diagram` and `architecture_state` types: elements in a tree with ports, connections,
diagrams (placements, notes, toggles), state machine diagrams with states and transitions, plus tags, places, links to
earlier types, "created" audit events and the project's sequence counters.

Design decisions:
- Elements form a tree at most four levels deep (a share are roots); a connection joins two elements, on a port each when
  both have one. `order` generates elements, then connections, then diagrams.
- The first diagram of a project is the large one (up to `_LARGE_DIAGRAM` elements, a toggle and a note) so the view and
  SVG are measured on a big drawing; a share of lines carry anchors; toggle rules name a domain row, never a record. The
  first and a few other diagrams are scoped to an element with outer connections and carry boundary boxes (the cap
  keeps the connection scan bounded).
- Each kind has its own folder tree (about one folder per twenty records, up to four deep) with about two thirds of its
  records filed, so folder-path reads are measured.
- State machine diagrams follow the diagrams, each describing one element; states come from a second generator (the
  state is its own type with its own codes), each diagram getting an initial and a final state, some nesting and a few
  transitions.
- Only project-owned records are generated (a profile's unit is the project); the visibility resolver's cost is covered
  by the scaling-shape guard.

Dependencies: `perf_dataset.records`, this module's models and service constants.
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from sqlalchemy import select

from app.models.record_comment import RecordComment, RecordCommentPin
from app.modules.architecture.diagram_resolver import outer_side
from app.modules.architecture.enums import (
    DISPLAY_NOTE_MAX,
    AttachPoint,
    LineShape,
    NoteAlign,
    NoteSizeMode,
    NoteTone,
    PortDirection,
    RecordStatus,
)
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionRealisation,
    ArchitectureConnectionType,
    ArchitectureDiagram,
    ArchitectureDiagramAnchor,
    ArchitectureDiagramBoundary,
    ArchitectureDiagramNote,
    ArchitectureDiagramPlacement,
    ArchitectureDiagramToggle,
    ArchitectureDiagramToggleMember,
    ArchitectureDomain,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitectureFolder,
    ArchitectureNoteLeader,
    ArchitecturePort,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_CODE_PREFIX,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_CODE_PREFIX,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
    STATE_ARTEFACT_TYPE,
    STATE_CODE_PREFIX,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_CODE_PREFIX,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import ANCHOR, PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.records import (
    RecordBatch,
    add_comments,
    add_tags,
    at_between,
    created_at,
    link_to_earlier,
    pick_weighted,
)

#: Deepest generated tree level (a root is 1); the application allows more.
_GENERATED_DEPTH = 4
_STATUS_MIX = (
    (RecordStatus.ACTIVE, 0.5), (RecordStatus.DRAFT, 0.15), (RecordStatus.PROPOSED, 0.15), (RecordStatus.RETIRED, 0.1),
    (RecordStatus.REJECTED, 0.1),
)
_PORT_NAMES = ("Main", "Control", "Data", "Power", "Debug", "Status")
#: Most elements the first (large) diagram of a project places, and the range for the others.
_LARGE_DIAGRAM = 200
_SMALL_DIAGRAM = (3, 12)
_ATTACH_POINTS = [point.value for point in AttachPoint]
#: The share of drawn lines that carry vertices, and the most vertices a generated line gets.
_ROUTED_LINES = 0.2
_MAX_VERTICES = 3
#: The most folders a kind gets and how deep they go.
_MAX_FOLDERS = 60
_FOLDER_DEPTH = 4
#: How many diagrams besides the first are given boundary boxes, and the most boxes one diagram gets.
_SCOPED_DIAGRAMS = 5
_MAX_BOUNDARIES = 20
_NOTE_TONES = [tone.value for tone in NoteTone]
_NOTE_ALIGNS = [align.value for align in NoteAlign]
_NOTE_SIZE_MODES = [mode.value for mode in NoteSizeMode]
_SHAPES = [shape.value for shape in LineShape]


def _line_shape(rng: random.Random) -> str | None:
    """A drawn line's own shape: half of the lines follow their diagram's default (none), the rest name one."""
    return None if rng.random() < 0.5 else rng.choice(_SHAPES)


def _route(rng: random.Random, seed: int) -> list[dict[str, float]]:
    """One to `_MAX_VERTICES` vertices near the diagram's grid, as a drawn line stores them."""
    return [
        {"x": float(seed % 7 * 200 + 100 * (vertex + 1)), "y": float(rng.randint(-60, 400))}
        for vertex in range(rng.randint(1, _MAX_VERTICES))
    ]


def _note_leaders(
    rng: random.Random, placed: list[uuid.UUID], connections: list[uuid.UUID], order: int, *, forced: bool,
) -> list[dict[str, Any]]:
    """The leaders of a generated note, as rows without their id and note: none, or up to two lines to a box of the diagram,
    a connection of the project (drawn only when a line of the diagram stands for it) or a free point, with a start point,
    vertices and styles on some. With `forced` the kind follows `order` (a box, a connection, a point), so the project's
    first diagram always has one of each, the first of them routed and starting at a chosen point."""
    blank: dict[str, Any] = {"element_id": None, "connection_id": None, "state_id": None, "transition_id": None, "x": None, "y": None}
    roll = (order + 0.5) / 3 * 0.75 if forced else rng.random()
    kinds: list[str] = []
    if roll < 0.3 and placed:
        kinds.append("element")
    elif roll < 0.55 and connections:
        kinds.append("connection")
    elif roll < 0.75:
        kinds.append("point")
    if kinds and not forced and rng.random() < 0.15:
        kinds.append("point")
    rows: list[dict[str, Any]] = []
    for slot, kind in enumerate(kinds):
        target = (
            {"element_id": rng.choice(placed)} if kind == "element"
            else {"connection_id": rng.choice(connections)} if kind == "connection"
            else {"x": float(order * 180 + 80 + slot * 40), "y": -200.0}
        )
        routed = (forced and order == 0) or rng.random() < _ROUTED_LINES
        rows.append({
            **blank, **target, "sort_order": slot, "kind": kind,
            "start_point": rng.choice(_ATTACH_POINTS) if (forced and order == 0) or rng.random() < 0.3 else None,
            "points": _route(rng, order) if routed else [], "line_shape": _line_shape(rng),
            "start_style": rng.choice(("none", "none", "dot")), "end_style": rng.choice(("arrow", "arrow", "dot", "none")),
        })
    return rows


def _type_ids(
    ctx: PerfProjectContext, model: type[ArchitectureElementType] | type[ArchitectureConnectionType],
) -> list[uuid.UUID]:
    """The ids of the organisation's default rows of a vocabulary (every generated project offers them)."""
    return list(ctx.db.scalars(
        select(model.id).where(model.organization_id == ctx.organization_uuid).order_by(model.sort_order, model.name)
    ))


def _write_folders(ctx: PerfProjectContext, kind: str, records: int) -> list[uuid.UUID]:
    """Writes a folder tree for one kind of record (about one folder per twenty records, at most `_FOLDER_DEPTH` deep)
    and returns the folder ids, so the records can be spread over them (some stay at the top level).

    Args:
        ctx: The project's context.
        kind: The `FolderKind` value.
        records: How many records of the kind are generated.
    """
    rng = ctx.rng
    wanted = min(_MAX_FOLDERS, max(3, records // 20))
    rows: list[dict] = []
    depths: dict[uuid.UUID, int] = {}
    for index in range(wanted):
        folder_id = uuid_from(rng)
        parent = None
        if rows and rng.random() < 0.6:
            candidate = rng.choice(list(depths))
            if depths[candidate] < _FOLDER_DEPTH:
                parent = candidate
        depths[folder_id] = depths[parent] + 1 if parent else 1
        rows.append({
            "id": folder_id, "project_id": ctx.project_uuid, "organization_id": None, "kind": kind, "name": f"Folder {index + 1}",
            "parent_id": parent, "sort_order": index, "creator_id": rng.choice(ctx.user_ids), "created_at": ANCHOR, "updated_at": ANCHOR,
        })
    # A folder's parent is always an earlier row, so the rows insert in order.
    ctx.add_count(ArchitectureFolder.__tablename__, insert_rows(ctx.db, ArchitectureFolder, rows))
    return list(depths)


def _pick_folder(rng: random.Random, folder_ids: list[uuid.UUID]) -> uuid.UUID | None:
    """A folder for a record, or `None` (the top level) for about a third of them."""
    return rng.choice(folder_ids) if folder_ids and rng.random() < 0.7 else None


def generate_elements(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's elements, their ports and everything hanging off them.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(ELEMENT_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    types = _type_ids(ctx, ArchitectureElementType)
    connection_types = _type_ids(ctx, ArchitectureConnectionType)
    if count == 0 or not types:
        return {}
    start = dict(ctx.counts)
    folder_ids = _write_folders(ctx, "element", count)
    batch = RecordBatch.start(ctx, ELEMENT_ARTEFACT_TYPE, ELEMENT_CODE_PREFIX, ArchitectureElement)
    depths: dict[uuid.UUID, int] = {}
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        parent = None
        if batch.ids and rng.random() < 0.7:
            candidate = rng.choice(batch.ids)
            if depths[candidate] < _GENERATED_DEPTH:
                parent = candidate
        record_id = batch.new_id()
        depths[record_id] = depths[parent] + 1 if parent else 1
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.5 else None
        name = textgen.title(rng)
        batch.add(
            {
                "id": record_id, "name": name, "description": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
                "display_note": textgen.paragraphs(rng, empty_chance=0.6, short_max=1, long_chance=0)[:DISPLAY_NOTE_MAX],
                "element_type_id": rng.choice(types), "parent_id": parent, "folder_id": _pick_folder(rng, folder_ids),
                "owner_type": "user" if owner else None, "owner_id": owner, "status": status.value, "version": 1,
                "is_archived": archived, "archived_at": created if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=name, detail={"status": status.value},
        )
        for order in range(rng.choice((0, 1, 1, 2, 3))):
            batch.satellite(ArchitecturePort, {
                "id": batch.new_id(), "element_id": record_id, "name": _PORT_NAMES[order],
                "direction": rng.choice(list(PortDirection)).value,
                "connection_type_id": rng.choice(connection_types) if connection_types and rng.random() < 0.8 else None,
                "sort_order": order, "created_at": created, "updated_at": created,
            })
    batch.write()
    add_tags(ctx, batch)
    _add_record_comments(ctx, batch, ELEMENT_ARTEFACT_TYPE)
    link_to_earlier(ctx, batch, [("requirement", 0.4), ("risk", 0.1), ("decision", 0.1)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def generate_connections(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's connections between the elements `generate_elements` wrote.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(CONNECTION_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    elements = ctx.shared.get(ELEMENT_ARTEFACT_TYPE, [])
    types = _type_ids(ctx, ArchitectureConnectionType)
    if count == 0 or len(elements) < 2 or not types:
        return {}
    start = dict(ctx.counts)
    ports: dict[uuid.UUID, list[uuid.UUID]] = {}
    for port_id, element_id in ctx.db.execute(
        select(ArchitecturePort.id, ArchitecturePort.element_id).where(ArchitecturePort.element_id.in_(elements))
        .order_by(ArchitecturePort.element_id, ArchitecturePort.sort_order, ArchitecturePort.name)
    ):
        ports.setdefault(element_id, []).append(port_id)
    folder_ids = _write_folders(ctx, "connection", count)
    batch = RecordBatch.start(ctx, CONNECTION_ARTEFACT_TYPE, CONNECTION_CODE_PREFIX, ArchitectureConnection)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        source, target = rng.sample(elements, 2)
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        batch.add(
            {
                "name": textgen.title(rng) if rng.random() < 0.7 else "", "connection_type_id": rng.choice(types),
                "source_element_id": source, "source_port_id": rng.choice(ports[source]) if ports.get(source) else None,
                "target_element_id": target, "target_port_id": rng.choice(ports[target]) if ports.get(target) else None,
                "protocol": rng.choice(("v1", "v2", "9600 baud", "TLS 1.3", "")), "folder_id": _pick_folder(rng, folder_ids),
                "description": textgen.paragraphs(rng, empty_chance=0.3, short_max=2), "status": status.value,
                "version": 1, "is_archived": archived, "archived_at": created if archived else None,
                "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title="connection", detail={"status": status.value},
        )
    batch.write()
    add_tags(ctx, batch)
    _add_record_comments(ctx, batch, CONNECTION_ARTEFACT_TYPE)
    link_to_earlier(ctx, batch, [("requirement", 0.3), ("risk", 0.05)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def _chain_ids(parents: dict[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID) -> set[uuid.UUID]:
    """The element and its ancestors."""
    found: set[uuid.UUID] = set()
    current: uuid.UUID | None = element_id
    while current is not None and current not in found:
        found.add(current)
        current = parents.get(current)
    return found


def _scoped_boundaries(
    ctx: PerfProjectContext, elements: list[uuid.UUID], taken: set[uuid.UUID],
) -> tuple[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]]] | None:
    """A scope element with outer connections and the boxes to draw for them.

    Returns:
        `(scope, [(outer connection, scope-side end, a connection inside that end that realises it or None)])`, or
        `None` when no element in a bounded sample has an outer connection.
    """
    parents = dict(ctx.db.execute(
        select(ArchitectureElement.id, ArchitectureElement.parent_id).where(ArchitectureElement.id.in_(elements))
    ).tuples().all())
    ends = ctx.db.execute(
        select(ArchitectureConnection.id, ArchitectureConnection.source_element_id, ArchitectureConnection.target_element_id)
        .where(ArchitectureConnection.source_element_id.in_(elements)).order_by(ArchitectureConnection.id).limit(5000)
    ).tuples().all()
    for scope in ctx.rng.sample([e for e in elements if e not in taken], min(len(elements) - len(taken), 25)):
        sides = [(c, outer_side(scope, parents, a, b)) for c, a, b in ends]
        outer = [(c, side) for c, side in sides if side is not None][:_MAX_BOUNDARIES]
        if not outer:
            continue
        inside = [
            (c, a, b) for c, a, b in ends if scope in _chain_ids(parents, a) and scope in _chain_ids(parents, b)
        ]
        rows: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]] = []
        for connection_id, side in outer:
            realising = next(
                (c for c, a, b in inside if c != connection_id and side in _chain_ids(parents, a) and side in _chain_ids(parents, b)),
                None,
            ) if ctx.rng.random() < 0.5 else None
            rows.append((connection_id, side, realising))
        return scope, rows
    return None


def _add_pinned_threads(
    rng: random.Random, ctx: PerfProjectContext, batch: RecordBatch, record_id: uuid.UUID, created: Any,
    placed: list[uuid.UUID], connections: list[uuid.UUID], *, first: bool,
) -> None:
    """Writes a diagram's pinned comment threads: free spots, boxes it places and lines of the project, some resolved,
    each with one to three comments. The first diagram always has one of each kind and a resolved thread."""
    wanted = ["none", "node", "edge", "node", "none", "edge", "node", "none"] if first else [
        rng.choice(("none", "node", "edge")) for _ in range(rng.choice((0, 0, 1, 2)))
    ]
    for slot, kind in enumerate(wanted):
        key = None
        if kind == "node" and placed:
            key = str(rng.choice(placed))
        elif kind == "edge" and connections:
            key = str(rng.choice(connections))
        else:
            kind = "none"
        pinned_at = at_between(rng, created)
        resolved = first and slot == 4 or rng.random() < 0.2
        author = rng.choice(ctx.user_ids)
        pin_id = batch.new_id()
        batch.satellite(RecordCommentPin, {
            "id": pin_id, "project_id": ctx.project_uuid, "organization_id": None, "artefact_type": DIAGRAM_ARTEFACT_TYPE,
            "record_id": record_id, "anchor_kind": kind, "anchor_key": key, "x": float(rng.randint(-200, 800)),
            "y": float(rng.randint(-200, 600)), "resolved_at": pinned_at if resolved else None,
            "resolved_by": rng.choice(ctx.user_ids) if resolved else None, "created_by": author, "created_at": pinned_at,
        })
        for position in range(rng.randint(1, 3) if not first else 3):
            at = at_between(rng, pinned_at)
            batch.satellite(RecordComment, {
                "id": batch.new_id(), "project_id": ctx.project_uuid, "organization_id": None,
                "artefact_type": DIAGRAM_ARTEFACT_TYPE, "record_id": record_id, "pin_id": pin_id,
                "author_id": author if position == 0 else rng.choice(ctx.user_ids),
                "body": textgen.sentences(rng, rng.randint(1, 3)), "edited_at": None, "created_at": at, "updated_at": at,
            })


def _add_record_comments(ctx: PerfProjectContext, batch: RecordBatch, artefact_type: str) -> None:
    """Writes ordinary (unpinned) comments on a batch's records at the requirements' comment ratio."""
    add_comments(
        ctx, batch, RecordComment, "record_id",
        extra={
            "project_id": ctx.project_uuid, "organization_id": None, "artefact_type": artefact_type, "pin_id": None,
        },
    )


def generate_diagrams(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's diagrams placing the elements `generate_elements` wrote.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(DIAGRAM_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    elements = ctx.shared.get(ELEMENT_ARTEFACT_TYPE, [])
    project_connections = ctx.shared.get(CONNECTION_ARTEFACT_TYPE, [])
    if count == 0 or not elements:
        return {}
    start = dict(ctx.counts)
    folder_ids = _write_folders(ctx, "diagram", count)
    # The organisation's seeded Hardware domain, which a toggle rule names (never a record).
    hardware_domain = ctx.db.scalar(select(ArchitectureDomain.id).where(
        ArchitectureDomain.organization_id == ctx.organization_uuid, ArchitectureDomain.name == "Hardware",
    ))
    batch = RecordBatch.start(ctx, DIAGRAM_ARTEFACT_TYPE, DIAGRAM_CODE_PREFIX, ArchitectureDiagram)
    scoped_left = _SCOPED_DIAGRAMS + 1
    used_scopes: set[uuid.UUID] = set()
    realised: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for index in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        name = textgen.title(rng)
        scoped = _scoped_boundaries(ctx, elements, used_scopes) if scoped_left and (index == 0 or rng.random() < 0.3) else None
        if scoped is not None:
            scoped_left -= 1
            used_scopes.add(scoped[0])
        record_id = batch.add(
            {
                "name": name, "purpose": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
                "scope_element_id": scoped[0] if scoped else (rng.choice(elements) if rng.random() < 0.3 else None),
                "connection_detail": rng.random() < 0.5, "line_hops": rng.random() < 0.5, "line_shape": rng.choice(_SHAPES),
                "show_connection_names": rng.random() < 0.5, "folder_id": _pick_folder(rng, folder_ids), "status": status.value,
                "version": 1, "is_archived": archived,
                "archived_at": created if archived else None, "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=name, detail={"status": status.value},
        )
        size = min(len(elements), _LARGE_DIAGRAM if index == 0 else rng.randint(*_SMALL_DIAGRAM))
        columns = max(int(math.sqrt(size)), 1)
        placed = rng.sample(elements, size)
        for slot, element_id in enumerate(placed):
            batch.satellite(ArchitectureDiagramPlacement, {
                "id": batch.new_id(), "diagram_id": record_id, "element_id": element_id,
                "x": float(slot % columns * 200), "y": float(slot // columns * 120), "width": 160.0, "height": 80.0,
                "collapsed": rng.random() < 0.1, "created_at": created, "updated_at": created,
            })
        for slot, (first, second) in enumerate(zip(placed, placed[1:], strict=False)):
            if rng.random() < 0.15:
                points = rng.sample(_ATTACH_POINTS, 2)
                batch.satellite(ArchitectureDiagramAnchor, {
                    "id": batch.new_id(), "diagram_id": record_id, "source_element_id": first, "target_element_id": second,
                    "source_point": points[0], "target_point": points[1] if rng.random() < 0.7 else None,
                    "points": _route(rng, slot) if rng.random() < _ROUTED_LINES else [], "line_shape": _line_shape(rng),
                    "created_at": created, "updated_at": created,
                })
        for slot, (connection_id, _side, realising) in enumerate(scoped[1] if scoped else ()):
            batch.satellite(ArchitectureDiagramBoundary, {
                "id": batch.new_id(), "diagram_id": record_id, "connection_id": connection_id,
                "x": float(-260 - slot % 2 * 140), "y": float(slot * 70), "width": 120.0, "height": 48.0,
                "created_at": created, "updated_at": created,
            })
            if realising is not None and (realising, connection_id) not in realised:
                realised.add((realising, connection_id))
                batch.satellite(ArchitectureConnectionRealisation, {
                    "id": batch.new_id(), "inner_connection_id": realising, "outer_connection_id": connection_id,
                    "created_at": created, "updated_at": created,
                })
        for order in range(3 if index == 0 else rng.choice((0, 1, 1, 2))):
            note_id = batch.new_id()
            batch.satellite(ArchitectureDiagramNote, {
                "id": note_id, "diagram_id": record_id, "state_machine_diagram_id": None, "text": textgen.title(rng), "x": float(order * 180),
                "y": -100.0, "width": 160.0, "height": 60.0, "sort_order": order, "tone": rng.choice(_NOTE_TONES),
                "title": textgen.title(rng), "text_align": rng.choice(_NOTE_ALIGNS), "size_mode": rng.choice(_NOTE_SIZE_MODES),
                "created_at": created, "updated_at": created,
            })
            for leader in _note_leaders(rng, placed, project_connections, order, forced=index == 0):
                batch.satellite(ArchitectureNoteLeader, {
                    "id": batch.new_id(), "note_id": note_id, "created_at": created, "updated_at": created, **leader,
                })
        _add_pinned_threads(rng, ctx, batch, record_id, created, placed, project_connections, first=index == 0)
        if index == 0 or rng.random() < 0.4:
            toggle_id = batch.new_id()
            batch.satellite(ArchitectureDiagramToggle, {
                "id": toggle_id, "diagram_id": record_id, "name": "Hardware", "default_on": rng.random() < 0.8,
                "rule": {"domain_ids": [str(hardware_domain)]} if hardware_domain else {}, "sort_order": 0,
                "created_at": created, "updated_at": created,
            })
            batch.satellite(ArchitectureDiagramToggleMember, {
                "id": batch.new_id(), "toggle_id": toggle_id, "element_id": rng.choice(elements), "connection_id": None,
                "created_at": created, "updated_at": created,
            })
    batch.write()
    add_tags(ctx, batch)
    _add_record_comments(ctx, batch, DIAGRAM_ARTEFACT_TYPE)
    link_to_earlier(ctx, batch, [("requirement", 0.2)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def generate_state_machines(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's state machine diagrams, each describing one element `generate_elements` wrote (the states and
    transitions come from `generate_states`).

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(STATE_MACHINE_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    elements = ctx.shared.get(ELEMENT_ARTEFACT_TYPE, [])
    if count == 0 or not elements:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, STATE_MACHINE_ARTEFACT_TYPE, STATE_MACHINE_CODE_PREFIX, ArchitectureStateMachineDiagram)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        status = pick_weighted(rng, _STATUS_MIX)
        archived = rng.random() < 0.03
        name = textgen.title(rng)
        batch.add(
            {
                "name": name, "description": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
                "element_id": rng.choice(elements), "line_hops": rng.random() < 0.5, "line_shape": rng.choice(_SHAPES),
                "status": status.value, "version": 1,
                "is_archived": archived,
                "archived_at": created if archived else None, "archived_by": creator if archived else None,
            },
            creator=creator, at=created, title=name, detail={"status": status.value},
        )
    batch.write()
    add_tags(ctx, batch)
    _add_record_comments(ctx, batch, STATE_MACHINE_ARTEFACT_TYPE)
    link_to_earlier(ctx, batch, [("requirement", 0.3), ("risk", 0.05)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def _state_note_leaders(
    rng: random.Random, states: list[uuid.UUID], transitions: list[uuid.UUID], order: int, *, forced: bool,
) -> list[dict[str, Any]]:
    """The leaders of a generated state machine note, as rows without their id and note: none, or up to two lines to a state, a
    transition of the diagram or a free point, with a start point, vertices and styles on some. With `forced` the kind follows
    `order` (a state, a transition, a point), so the project's first state machine diagram always has one of each."""
    blank: dict[str, Any] = {"state_id": None, "transition_id": None, "element_id": None, "connection_id": None, "x": None, "y": None}
    roll = (order + 0.5) / 3 * 0.75 if forced else rng.random()
    kinds: list[str] = []
    if roll < 0.3 and states:
        kinds.append("state")
    elif roll < 0.55 and transitions:
        kinds.append("transition")
    elif roll < 0.75:
        kinds.append("point")
    if kinds and not forced and rng.random() < 0.15:
        kinds.append("point")
    rows: list[dict[str, Any]] = []
    for slot, kind in enumerate(kinds):
        target = (
            {"state_id": rng.choice(states)} if kind == "state"
            else {"transition_id": rng.choice(transitions)} if kind == "transition"
            else {"x": float(order * 180 + 80 + slot * 40), "y": -200.0}
        )
        routed = (forced and order == 0) or rng.random() < _ROUTED_LINES
        rows.append({
            **blank, **target, "sort_order": slot, "kind": kind,
            "start_point": rng.choice(_ATTACH_POINTS) if (forced and order == 0) or rng.random() < 0.3 else None,
            "points": _route(rng, order) if routed else [], "line_shape": _line_shape(rng),
            "start_style": rng.choice(("none", "none", "dot")), "end_style": rng.choice(("arrow", "arrow", "dot", "none")),
        })
    return rows


_STATE_NAMES = ("Idle", "Starting", "Running", "Degraded", "Stopping", "Fault", "Updating", "Standby", "Calibrating", "Recovering")
_EVENTS = ("start", "stop", "timeout", "fault", "reset", "ready", "")
#: The most states one generated state machine diagram gets (the first diagram is the largest).
_MAX_STATES = 60


def generate_states(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the states and transitions of the state machine diagrams `generate_state_machines` wrote, sharing the
    type's count out over them: each diagram gets an initial state, a final state and ordinary states (some nested in an
    earlier one, a share with entry, exit and activity text, an occasional choice), chained by transitions plus a few
    extra, a self transition among them, so the checks have sound and unsound diagrams to read.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng = ctx.rng
    machines = ctx.shared.get(STATE_MACHINE_ARTEFACT_TYPE, [])
    total = ctx.spec.ratios.count_for(STATE_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    if total == 0 or not machines:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, STATE_ARTEFACT_TYPE, STATE_CODE_PREFIX, ArchitectureState)
    per_machine = max(3, min(_MAX_STATES, total // len(machines)))
    for index, machine_id in enumerate(machines):
        size = min(_MAX_STATES, per_machine * 3 if index == 0 else per_machine)
        stamp = ctx.created_times[STATE_MACHINE_ARTEFACT_TYPE][index]
        made: list[tuple[uuid.UUID, str]] = []
        for slot in range(size):
            kind = "initial" if slot == 0 else "final" if slot == size - 1 else "choice" if rng.random() < 0.05 else "state"
            parent = None
            ordinary = [state_id for state_id, state_kind in made if state_kind == "state"]
            if kind != "initial" and ordinary and rng.random() < 0.25:
                parent = rng.choice(ordinary)
            record_id = batch.new_id()
            name = "Start" if kind == "initial" else "End" if kind == "final" else f"{rng.choice(_STATE_NAMES)} {slot}"
            detail = kind == "state" and rng.random() < 0.5
            batch.add(
                {
                    "id": record_id, "state_machine_diagram_id": machine_id, "name": name,
                    "description": textgen.paragraphs(rng, empty_chance=0.5, short_max=1), "kind": kind,
                    "parent_state_id": parent, "entry_action": f"enter_{slot}()" if detail else "",
                    "exit_action": f"leave_{slot}()" if detail and rng.random() < 0.5 else "",
                    "activity": "monitor()" if detail and rng.random() < 0.4 else "",
                    "label": "OK?" if kind == "choice" else "Go" if kind == "initial" else "",
                    "label_position": "right" if kind == "choice" else "inside",
                    "x": float(slot % 6 * 220), "y": float(slot // 6 * 120), "width": 160.0, "height": 64.0,
                    "collapsed": rng.random() < 0.05,
                },
                creator=rng.choice(ctx.user_ids), at=at_between(rng, stamp), title=name, detail={"kind": kind},
            )
            made.append((record_id, kind))
        transition_ids: list[uuid.UUID] = []
        for order, ((source, _source_kind), (target, _target_kind)) in enumerate(zip(made, made[1:], strict=False)):
            if made[order][1] == "final":
                continue
            transition_id = batch.new_id()
            transition_ids.append(transition_id)
            batch.satellite(ArchitectureTransition, {
                "id": transition_id, "state_machine_diagram_id": machine_id, "source_state_id": source,
                "target_state_id": target, "event": rng.choice(_EVENTS), "guard": "ready" if rng.random() < 0.2 else "",
                "action": f"do_{order}()" if rng.random() < 0.3 else "", "description": "", "sort_order": order,
                "source_point": rng.choice(_ATTACH_POINTS) if rng.random() < 0.1 else None,
                "target_point": None, "points": _route(rng, order) if rng.random() < _ROUTED_LINES else [], "line_shape": _line_shape(rng),
                "created_at": stamp, "updated_at": stamp,
            })
        ordinary_ids = [state_id for state_id, state_kind in made if state_kind == "state"]
        for order in range(3 if index == 0 else rng.choice((0, 1, 1, 2))):
            note_id = batch.new_id()
            batch.satellite(ArchitectureDiagramNote, {
                "id": note_id, "diagram_id": None, "state_machine_diagram_id": machine_id, "text": textgen.title(rng), "x": float(order * 180),
                "y": -100.0, "width": 160.0, "height": 60.0, "sort_order": order, "tone": rng.choice(_NOTE_TONES),
                "title": textgen.title(rng), "text_align": rng.choice(_NOTE_ALIGNS), "size_mode": rng.choice(_NOTE_SIZE_MODES),
                "created_at": stamp, "updated_at": stamp,
            })
            for leader in _state_note_leaders(rng, ordinary_ids, transition_ids, order, forced=index == 0):
                batch.satellite(ArchitectureNoteLeader, {
                    "id": batch.new_id(), "note_id": note_id, "created_at": stamp, "updated_at": stamp, **leader,
                })
        for extra in range(min(len(ordinary_ids), 3)):
            batch.satellite(ArchitectureTransition, {
                "id": batch.new_id(), "state_machine_diagram_id": machine_id, "source_state_id": ordinary_ids[extra],
                "target_state_id": ordinary_ids[extra] if extra == 0 else rng.choice(ordinary_ids), "event": rng.choice(_EVENTS),
                "guard": "", "action": "", "description": "", "sort_order": size + extra, "source_point": None,
                "target_point": None, "points": [], "line_shape": None, "created_at": stamp, "updated_at": stamp,
            })
    batch.write()
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.1)])
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}
