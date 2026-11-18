"""
Module: modules.architecture.diagram_resolver

The one rule that turns the model's connections into the lines a diagram draws. The API's diagram view, the server
SVG, and (later) the report part and the Mermaid and Structurizr exports all call `resolve`, so a screen and a
document cannot differ.

Responsibilities:
- Apply, in this order: (1) hide the elements and connections of switched-off toggles; (2) join across hidden
  elements (a hidden transit element is bridged); (3) roll every end up to its nearest placed ancestor; (4) merge
  parallel lines when connection detail is off. A connection a person routed on its own is never merged: it is drawn as a
  line of its own.
- Report which underlying connections each line stands for, which hidden elements a bridged line passes through,
  and which connections are wholly inside a placed element (and so drawn on no line).
- Join a scoped diagram's boundary boxes: an inner connection that realises an outer connection and ends at the outer
  connection's scope-side element is drawn to that connection's box (`Boundary`), and `outer_side` says which end of a
  connection lies inside a scope, which is what makes it an outer connection.

Design decisions:
- **Pure.** The function reads only the plain data it is given (ids, parents, ends); the loader that builds that data
  from the database, and applies visibility, is in `diagram_view`. An element the viewer may not read is never passed
  in `hidden_elements`, so it is never bridged through and never matched by a toggle.
- **Hidden means the element or an ancestor is switched off:** a switched-off element takes its subtree with it.
- **Bridging follows directions.** A one-way connection is an arc from source to target; a two-way connection is an arc
  each way. A hidden element joins every in-neighbour to every out-neighbour its arcs allow, and a chain of hidden
  elements is followed to `MAX_HOPS`; one shortest path is kept per pair of visible ends, so a dense hidden region
  cannot make the work explode. A hidden element with a single neighbour joins nothing and just disappears.
- **A line is dashed ("indirect") only when every connection behind it is rolled up or bridged.** A merged line that
  includes a direct connection stays solid.
- **A boundary box is a placed element with no parent.** `resolve` swaps the end of each realising connection that meets
  the box (the outer connection's scope-side element, or an element inside the one outside the scope) for the box (one
  candidate per box, so a connection realising two outer connections is drawn to both) and drops the original, which
  would otherwise be drawn to nothing. A scope-side element that is itself placed keeps its own lines there: the box is
  then a coverage marker, or a line to the element outside.
- **A routed connection is its own line.** A connection with a route of its own (`routed`: the connection and the two boxes
  its route joins) that resolves to one direct or rolled-up line between exactly those boxes is taken out of the merge, so
  the route moves it alone. A route whose boxes no longer match is ignored and the connection merges as before; a bridged
  line (several connections behind it) and a line to a boundary box are never routed, so they are not offered
  (`Line.routable`).
- **Order is deterministic** (lines sorted by their ends and first connection), so equal inputs draw equal diagrams.

Dependencies: none beyond the standard library.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

#: The longest chain of hidden elements a bridged line passes through, and the deepest ancestor walk.
MAX_HOPS = 12

_WALK_CAP = 13


@dataclass(frozen=True)
class ModelConnection:
    """A connection as the resolver sees it.

    Attributes:
        id: The connection.
        source_id / target_id: Its two end elements.
        directional: Whether it is one-way (source to target); false is two-way.
    """

    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    directional: bool


@dataclass(frozen=True)
class Boundary:
    """A boundary box of a scoped diagram, as the resolver sees it.

    Attributes:
        id: The box (its own id, never an element's); lines to it use this id as their end.
        element_id: The outer connection's scope-side end element: the element inside the scope that the outer
            connection attaches to (the scope itself or a descendant).
        outside_id: The outer connection's other end, the element outside the scope.
        connection_ids: The inner connections that realise the outer connection.
    """

    id: uuid.UUID
    element_id: uuid.UUID
    outside_id: uuid.UUID
    connection_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class Line:
    """One line to draw between two placed elements.

    Attributes:
        source_id / target_id: The placed elements at its ends (never equal).
        two_way: True when the line has no single direction (a two-way connection, or members that disagree).
        connection_ids: The model connections it stands for, in input order.
        rolled_up: Some end was rolled up to a placed ancestor.
        bridged: Some connection reaches its end through hidden elements.
        indirect: Every connection behind it is rolled up or bridged (drawn dashed).
        hops: The hidden elements bridged through, in the order met, without repeats.
        routable: The connections behind it that can have a route of their own: each stands alone behind one candidate
            line between two boxes (not bridged, not to a boundary box).
        own_route: The connection this line is drawn for with its own route (the only connection behind it), or `None`.
    """

    source_id: uuid.UUID
    target_id: uuid.UUID
    two_way: bool
    connection_ids: tuple[uuid.UUID, ...]
    rolled_up: bool
    bridged: bool
    indirect: bool
    hops: tuple[uuid.UUID, ...]
    routable: tuple[uuid.UUID, ...] = ()
    own_route: uuid.UUID | None = None


@dataclass(frozen=True)
class Resolution:
    """What `resolve` decides.

    Attributes:
        hidden_placed: The placed elements that are switched off (drawn on no diagram, kept in the placements).
        lines: The lines to draw.
        internal: `{placed element id: connection ids wholly inside it}`: connections whose two ends roll up to the
            same placed element, drawn on no line.
    """

    hidden_placed: frozenset[uuid.UUID]
    lines: tuple[Line, ...]
    internal: Mapping[uuid.UUID, tuple[uuid.UUID, ...]]


@dataclass
class _Candidate:
    """A line before roll-up and merging: two visible ends and what lies behind them."""

    a: uuid.UUID
    b: uuid.UUID
    connection_ids: list[uuid.UUID]
    one_way: bool
    bridged: bool
    hops: list[uuid.UUID]


def _chain(parents: Mapping[uuid.UUID, uuid.UUID | None], element_id: uuid.UUID):
    """The element and its ancestors, nearest first (cycle-safe)."""
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = element_id
    while current is not None and current not in seen and len(seen) < _WALK_CAP:
        seen.add(current)
        yield current
        current = parents.get(current)


def outer_side(
    scope_id: uuid.UUID, parents: Mapping[uuid.UUID, uuid.UUID | None], source_id: uuid.UUID, target_id: uuid.UUID,
) -> uuid.UUID | None:
    """The end of a connection that lies inside `scope_id`, when the other end lies outside it; otherwise `None`.

    A connection with exactly one end in the scope's subtree (the scope itself or a descendant) is an *outer*
    connection of that scope: it crosses the scope's boundary.

    Args:
        scope_id: The element whose inside a diagram shows.
        parents: `{element id: parent id}` covering both ends and their ancestors.
        source_id / target_id: The connection's two end elements.

    Returns:
        The end element inside the scope, or `None` for a connection wholly inside or wholly outside.
    """
    source_in = scope_id in _chain(parents, source_id)
    target_in = scope_id in _chain(parents, target_id)
    if source_in == target_in:
        return None
    return source_id if source_in else target_id


def _attach_boundaries(
    live: Sequence[ModelConnection], boundaries: Sequence[Boundary], placed: Collection[uuid.UUID],
    parents: Mapping[uuid.UUID, uuid.UUID | None],
) -> list[ModelConnection]:
    """The connections with the end that meets a boundary swapped for its box.

    A realising connection meets the box at its end that is the outer connection's scope-side element (when that element
    is not itself placed) or that lies inside the element outside the scope. It becomes one connection per box it
    realises, the end swapped; the original is dropped. A connection whose two ends would both meet the box, and every
    other connection, is unchanged.
    """
    by_connection: dict[uuid.UUID, list[Boundary]] = {}
    for boundary in boundaries:
        for connection_id in boundary.connection_ids:
            by_connection.setdefault(connection_id, []).append(boundary)

    def meets(boundary: Boundary, end: uuid.UUID) -> bool:
        return (end == boundary.element_id and end not in placed) or boundary.outside_id in _chain(parents, end)

    out: list[ModelConnection] = []
    for c in live:
        swaps = [
            (b, meets(b, c.source_id), meets(b, c.target_id)) for b in by_connection.get(c.id, ())
        ]
        swaps = [(b, s_, t_) for b, s_, t_ in swaps if s_ != t_]
        if not swaps:
            out.append(c)
            continue
        for b, source_meets, _target_meets in swaps:
            out.append(ModelConnection(
                c.id, b.id if source_meets else c.source_id, c.target_id if source_meets else b.id, c.directional,
            ))
    return out


def resolve(
    *, placed: Collection[uuid.UUID], parents: Mapping[uuid.UUID, uuid.UUID | None],
    connections: Sequence[ModelConnection], hidden_elements: Collection[uuid.UUID] = (),
    hidden_connections: Collection[uuid.UUID] = (), merge_parallel: bool, boundaries: Sequence[Boundary] = (),
    routed: Mapping[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] | None = None,
) -> Resolution:
    """Resolves the lines of a diagram.

    Args:
        placed: The elements placed on the diagram.
        parents: `{element id: parent id}` for every element that appears as a connection end or placement, and every
            ancestor of one (a root maps to `None`).
        connections: The connections to consider, in a stable order.
        hidden_elements: The elements switched off (their descendants are hidden with them).
        hidden_connections: The connections switched off.
        merge_parallel: True when connection detail is off: every line between the same two placed elements becomes one.
        boundaries: The boundary boxes of a scoped diagram; a realising connection is drawn to its box (see `Boundary`).
        routed: `{connection id: the two boxes its own route joins}` for the connections a person routed on their own; such
            a connection is drawn as its own line while it still resolves to a line between those two boxes.

    Returns:
        The decision; see `Resolution`.
    """
    switched_off = set(hidden_elements)
    hidden_cache: dict[uuid.UUID, bool] = {}

    def is_hidden(element_id: uuid.UUID) -> bool:
        if element_id not in hidden_cache:
            hidden_cache[element_id] = bool(switched_off) and any(a in switched_off for a in _chain(parents, element_id))
        return hidden_cache[element_id]

    placed_set = set(placed) | {b.id for b in boundaries}
    anchors: dict[uuid.UUID, uuid.UUID | None] = {}

    def anchor(element_id: uuid.UUID) -> uuid.UUID | None:
        if element_id not in anchors:
            anchors[element_id] = next((a for a in _chain(parents, element_id) if a in placed_set), None)
        return anchors[element_id]

    switched_off_connections = set(hidden_connections)
    live = [c for c in connections if c.id not in switched_off_connections]
    if boundaries:
        live = _attach_boundaries(live, boundaries, placed_set, parents)
    candidates: list[_Candidate] = []
    arcs: dict[uuid.UUID, list[tuple[uuid.UUID, ModelConnection]]] = {}
    for c in live:
        source_hidden, target_hidden = is_hidden(c.source_id), is_hidden(c.target_id)
        if not source_hidden and not target_hidden:
            candidates.append(_Candidate(c.source_id, c.target_id, [c.id], c.directional, False, []))
            continue
        arcs.setdefault(c.source_id, []).append((c.target_id, c))
        if not c.directional:
            arcs.setdefault(c.target_id, []).append((c.source_id, c))
    if arcs:
        candidates.extend(_bridge(arcs, is_hidden, live))

    internal: dict[uuid.UUID, list[uuid.UUID]] = {}
    rolled: list[tuple[uuid.UUID, uuid.UUID, _Candidate, bool]] = []
    for candidate in candidates:
        pa, pb = anchor(candidate.a), anchor(candidate.b)
        if pa is None or pb is None:
            continue
        if pa == pb:
            internal.setdefault(pa, []).extend(candidate.connection_ids)
            continue
        rolled.append((pa, pb, candidate, pa != candidate.a or pb != candidate.b))

    lines = _merge(rolled, merge_parallel, routed or {}, {b.id for b in boundaries})
    return Resolution(
        hidden_placed=frozenset(p for p in placed_set if is_hidden(p)),
        lines=tuple(sorted(lines, key=lambda ln: (str(ln.source_id), str(ln.target_id), str(ln.connection_ids[0])))),
        internal={k: tuple(dict.fromkeys(v)) for k, v in internal.items()},
    )


def _bridge(
    arcs: Mapping[uuid.UUID, Sequence[tuple[uuid.UUID, ModelConnection]]], is_hidden, live: Sequence[ModelConnection],
) -> list[_Candidate]:
    """The lines that join a visible element to another through a chain of hidden ones.

    Starting from each visible element with an arc into a hidden one, a breadth-first walk through hidden elements
    (to `MAX_HOPS`) keeps the shortest path to each visible element reached. A pair reached in both directions is
    one two-way candidate, emitted once.
    """
    starts = sorted({
        end for c in live for end in (c.source_id, c.target_id) if not is_hidden(end) and end in arcs
    }, key=str)
    found: dict[tuple[uuid.UUID, uuid.UUID], _Candidate] = {}
    for start in starts:
        queue: deque[tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]] = deque()
        reached: set[uuid.UUID] = set()
        for nxt, c in arcs.get(start, ()):
            if is_hidden(nxt) and nxt not in reached:
                reached.add(nxt)
                queue.append((nxt, [nxt], [c.id]))
        done: set[uuid.UUID] = set()
        while queue:
            node, hops, ids = queue.popleft()
            for nxt, c in arcs.get(node, ()):
                if is_hidden(nxt):
                    if nxt not in reached and len(hops) < MAX_HOPS:
                        reached.add(nxt)
                        queue.append((nxt, [*hops, nxt], [*ids, c.id]))
                elif nxt != start and nxt not in done:
                    done.add(nxt)
                    key = (start, nxt)
                    found[key] = _Candidate(start, nxt, [*ids, c.id], True, True, list(hops))
    merged: list[_Candidate] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for (a, b), candidate in sorted(found.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if (a, b) in seen:
            continue
        seen.add((a, b))
        reverse = found.get((b, a))
        if reverse is not None:
            seen.add((b, a))
            candidate.one_way = False
            candidate.connection_ids = list(dict.fromkeys([*candidate.connection_ids, *reverse.connection_ids]))
            candidate.hops = list(dict.fromkeys([*candidate.hops, *reverse.hops]))
        merged.append(candidate)
    return merged


def _merge(
    rolled: Sequence[tuple[uuid.UUID, uuid.UUID, _Candidate, bool]], merge_parallel: bool,
    routed: Mapping[uuid.UUID, tuple[uuid.UUID, uuid.UUID]], boundary_ids: Collection[uuid.UUID],
) -> list[Line]:
    """Groups rolled candidates into lines: all between one unordered pair when `merge_parallel`, otherwise only the
    indirect ones (rolled up or bridged) while a direct connection keeps its own line. A connection with a route of its
    own (`routed`) that stands alone between exactly its route's two boxes is a line by itself either way."""
    groups: dict[object, list[tuple[uuid.UUID, uuid.UUID, _Candidate, bool]]] = {}
    for pa, pb, candidate, rolled_up in rolled:
        indirect = rolled_up or candidate.bridged
        own = _routable_id(candidate, pa, pb, boundary_ids)
        if own is not None and own in routed and frozenset(routed[own]) == frozenset((pa, pb)):
            key: object = ("own", own, pa, pb)
        elif merge_parallel:
            key = frozenset((pa, pb))
        elif indirect:
            key = ("indirect", frozenset((pa, pb)))
        else:
            key = ("direct", candidate.connection_ids[0], pa, pb)
        groups.setdefault(key, []).append((pa, pb, candidate, rolled_up))
    lines: list[Line] = []
    for key, members in groups.items():
        first_a, first_b = members[0][0], members[0][1]
        # The line is drawn from the first member's orientation; members drawn the other way make it two-way.
        agree = all((m[0], m[1]) == (first_a, first_b) for m in members)
        two_way = any(not m[2].one_way for m in members) or not agree
        ids: list[uuid.UUID] = []
        hops: list[uuid.UUID] = []
        for _pa, _pb, candidate, _rolled in members:
            ids.extend(candidate.connection_ids)
            hops.extend(candidate.hops)
        flags = [(rolled_up, candidate.bridged) for _pa, _pb, candidate, rolled_up in members]
        routable = [i for pa, pb, candidate, _r in members if (i := _routable_id(candidate, pa, pb, boundary_ids)) is not None]
        lines.append(Line(
            source_id=first_a, target_id=first_b, two_way=two_way, connection_ids=tuple(dict.fromkeys(ids)),
            rolled_up=any(r for r, _b in flags), bridged=any(b for _r, b in flags),
            indirect=all(r or b for r, b in flags), hops=tuple(dict.fromkeys(hops)),
            routable=tuple(dict.fromkeys(routable)),
            own_route=key[1] if isinstance(key, tuple) and key[0] == "own" else None,
        ))
    return lines


def _routable_id(
    candidate: _Candidate, pa: uuid.UUID, pb: uuid.UUID, boundary_ids: Collection[uuid.UUID],
) -> uuid.UUID | None:
    """The one connection behind a candidate line when it can have a route of its own: a candidate with several
    connections is a bridged chain, and a line to a boundary box has no element pair to keep a route on."""
    if len(candidate.connection_ids) != 1 or pa in boundary_ids or pb in boundary_ids:
        return None
    return candidate.connection_ids[0]
