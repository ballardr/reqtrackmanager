"""
Module: modules.architecture.state_machine_svg

Renders a state machine diagram (`schemas.StateMachineModel`) as one SVG document in UML state machine notation, for the
server's SVG endpoint (the PNG download is this document drawn in the browser).

Responsibilities: draw ordinary states as rounded rectangles (name, code, `entry /`, `exit /`, `do /` lines), composite
states as frames with a header strip, and initial, final and choice states as the `state_shapes` markers (label inside
or beside, included in the drawing's extent); transitions as arrows between attach points (a person's choice, else the
nearest; a self transition as the `state_shapes` loop) with an `event [guard] / action` label; notes and leaders with the
block diagram's drawing (`diagram_svg`); small arcs where lines cross when `line_hops` is on (`diagram_line_hops`).

Design decisions:
- Everything user-supplied is text: XML-escaped and stripped of control characters (`diagram_svg` helpers); the only
  markup embedded is the fixed marker table of `state_shapes`.
- Same geometry as the screen: stored absolute box coordinates, the shared attach rule (`diagram_points`), loop and
  marker shapes, and `transition_label`, so the file shows what the editor shows.
- Light-theme colours on a transparent background, as the block diagram's file; the editor's issue tints are not drawn.
- A composite state shows its name and code only; its inside holds its child states.
- Deterministic: boxes and lines are drawn in model order, parents first, so equal models give equal bytes.

Dependencies: `schemas`, `state_shapes`, `diagram_points`, `diagram_svg` (text safety and wrapping), `labels`.
"""

from __future__ import annotations

import uuid

from app.modules.architecture.diagram_line_anchors import AnchorBox, AnchorLine, assign_line_anchors
from app.modules.architecture.diagram_line_hops import HopLine, line_hops
from app.modules.architecture.diagram_line_path import NO_DIRECTIONS, Directions, Point, effective_shape, line_middle, line_path
from app.modules.architecture.diagram_points import ATTACH_POINTS, line_directions, point_xy
from app.modules.architecture.diagram_svg import (
    _ROOT,
    _drawn_notes,
    _framed_notes,
    _leader_runs,
    _note_lines,
    _notes,
    _text,
    _wrap,
    leader_shape,
)
from app.modules.architecture.diagram_symbol_label import LABEL_FONT_SIZE, LABEL_LINE_HEIGHT, LABEL_PADDING, BesideLayout, beside_label, fit_label
from app.modules.architecture.enums import LabelPosition, StateKind
from app.modules.architecture.labels import STATE_KIND_LABEL
from app.modules.architecture.schemas import NoteOut, StateMachineModel, StateOut, TransitionOut
from app.modules.architecture.state_shapes import (
    COMPOSITE_HEADER_HEIGHT,
    LABEL_ON_FILL,
    LABEL_ON_FILL_KINDS,
    SELF_LOOP_REACH,
    STATE_CORNER_RADIUS,
    STATE_MARKERS,
    action_lines,
    labelled_svg,
    marker_attach_points,
    marker_frame,
    self_loop,
    self_loop_path,
    transition_label,
)

_INK = "#475569"
_TEXT_COLOR = "#1E293B"
_MUTED = "#64748B"
_MARGIN = 32.0
_LINE_HEIGHT = 12.0
#: Characters that fit across a state's width at the 10 and 13 point sizes (a rough average glyph width).
_CHARS_PER_UNIT = {"name": 1 / 7.5, "small": 1 / 5.6}

Box = tuple[float, float, float, float]


def _box(state: StateOut) -> Box:
    """The state's frame as drawn: its stored box, or the larger frame of a symbol that carries a label inside it (a label
    outside the symbol leaves the frame as stored)."""
    box = (state.x, state.y, state.width, state.height)
    kind = StateKind(state.kind)
    return box if kind is StateKind.STATE else marker_frame(kind, box, state.label, LabelPosition(state.label_position))


def _outside_label(state: StateOut) -> BesideLayout | None:
    """The layout of a marker's label drawn outside its symbol, or None (an ordinary state, no label, or a label inside)."""
    if StateKind(state.kind) is StateKind.STATE:
        return None
    x, y, w, h = _box(state)
    return beside_label(state.label, LabelPosition(state.label_position), w, h)


def _reach(state: StateOut) -> tuple[float, float, float, float]:
    """The left, top, right and bottom of everything drawn for a state: its frame and the text outside it."""
    x, y, w, h = _box(state)
    left, top, right, bottom = x, y, x + w, y + h
    beside = _outside_label(state)
    if beside is not None:
        left, top = min(left, x + beside.x), min(top, y + beside.y)
        right, bottom = max(right, x + beside.x + beside.width), max(bottom, y + beside.y + beside.height)
    return left, top, right, bottom


def _depths(states: list[StateOut]) -> dict[uuid.UUID, int]:
    """How deep each state is nested (0 at the top level), following `parent_state_id` and ignoring a parent that is not
    in the diagram."""
    parents = {s.id: s.parent_state_id for s in states}
    depths: dict[uuid.UUID, int] = {}
    for state in states:
        depth, at = 0, parents.get(state.id)
        while at is not None and at in parents and depth < 20:
            depth, at = depth + 1, parents[at]
        depths[state.id] = depth
    return depths


def _marker(state: StateOut) -> str:
    """A marker state: its standard drawing scaled into its frame, the label (when it has one) inside it, and its name below
    when it is not just the kind's own label."""
    kind = StateKind(state.kind)
    x, y, w, h = _box(state)
    inside = LabelPosition(state.label_position) is LabelPosition.INSIDE
    layout = fit_label(kind, state.label) if inside else None
    beside = _outside_label(state)
    size, markup = (layout.size, labelled_svg(kind, layout.size)) if layout else STATE_MARKERS[kind]
    match = _ROOT.search(markup)
    inner = markup[match.end(): -len("</svg>")] if match else ""
    drawing = f'<g transform="translate({x:.1f} {y:.1f}) scale({w / size:.4f} {h / size:.4f})">{inner}</g>'
    if layout:
        lines = layout.lines
        colour = LABEL_ON_FILL if kind in LABEL_ON_FILL_KINDS else _TEXT_COLOR
        top = y + h / 2 - len(lines) * LABEL_LINE_HEIGHT / 2 + LABEL_FONT_SIZE
        drawing += "".join(
            f'<text x="{x + w / 2:.1f}" y="{top + i * LABEL_LINE_HEIGHT:.1f}" text-anchor="middle" '
            f'font-size="{LABEL_FONT_SIZE}" fill="{colour}">{_text(line)}</text>'
            for i, line in enumerate(lines)
        )
    if beside is not None:
        anchor, at = {"left": ("start", 0), "center": ("middle", beside.width / 2), "right": ("end", beside.width)}[beside.align]
        top = y + beside.y + LABEL_FONT_SIZE
        drawing += "".join(
            f'<text x="{x + beside.x + at:.1f}" y="{top + i * LABEL_LINE_HEIGHT:.1f}" text-anchor="{anchor}" '
            f'font-size="{LABEL_FONT_SIZE}" fill="{_TEXT_COLOR}">{_text(line)}</text>'
            for i, line in enumerate(beside.lines)
        )
    if state.name.strip() and state.name != STATE_KIND_LABEL.get(state.kind):
        below = beside.height + LABEL_PADDING if beside is not None and LabelPosition(state.label_position) is LabelPosition.BELOW else 0
        cx, ty = x + w / 2, y + h + below + 13
        drawing += f'<text x="{cx:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="10" fill="{_MUTED}">{_text(state.name)}</text>'
    return drawing


def _composite(state: StateOut) -> str:
    """A composite state: a frame with its name and code in a header strip."""
    x, y, w, h = _box(state)
    chars = max(int(w * _CHARS_PER_UNIT["name"]) - 6, 6)
    name = _wrap(state.name, chars, 1)[0] if state.name.strip() else ""
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{STATE_CORNER_RADIUS}" fill="#FFFFFF" '
        f'fill-opacity="0.92" stroke="{_INK}" stroke-width="2"/>'
        f'<line x1="{x:.1f}" y1="{y + COMPOSITE_HEADER_HEIGHT:.1f}" x2="{x + w:.1f}" y2="{y + COMPOSITE_HEADER_HEIGHT:.1f}" '
        f'stroke="{_INK}" stroke-width="1"/>'
        f'<text x="{x + 12:.1f}" y="{y + 21:.1f}" font-size="13" font-weight="bold" fill="{_TEXT_COLOR}">{_text(name)}</text>'
        f'<text x="{x + w - 10:.1f}" y="{y + 21:.1f}" text-anchor="end" font-size="10" fill="{_MUTED}">{_text(state.unique_code)}</text>'
    )


def _state(state: StateOut) -> str:
    """An ordinary state: name (up to two lines), code, a rule and the entry, exit and do lines that fit the box."""
    x, y, w, h = _box(state)
    parts = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{STATE_CORNER_RADIUS}" fill="#FFFFFF" '
        f'fill-opacity="0.92" stroke="{_INK}" stroke-width="2"/>'
    ]
    cx = x + w / 2
    names = _wrap(state.name, max(int(w * _CHARS_PER_UNIT["name"]), 6), 2) if state.name.strip() else []
    cursor = y + 20
    for line in names:
        parts.append(
            f'<text x="{cx:.1f}" y="{cursor:.1f}" text-anchor="middle" font-size="13" font-weight="bold" '
            f'fill="{_TEXT_COLOR}">{_text(line)}</text>'
        )
        cursor += 15
    parts.append(f'<text x="{cx:.1f}" y="{cursor - 2:.1f}" text-anchor="middle" font-size="10" fill="{_MUTED}">{_text(state.unique_code)}</text>')
    lines = action_lines(state.entry_action, state.exit_action, state.activity)
    room = int((y + h - (cursor + 12)) // _LINE_HEIGHT)
    if lines and room > 0:
        rule = cursor + 3
        parts.append(f'<line x1="{x:.1f}" y1="{rule:.1f}" x2="{x + w:.1f}" y2="{rule:.1f}" stroke="{_INK}" stroke-width="1"/>')
        chars = max(int((w - 16) * _CHARS_PER_UNIT["small"]), 6)
        shown = _note_lines("\n".join(lines), chars, room)
        for i, line in enumerate(shown):
            parts.append(f'<text x="{x + 8:.1f}" y="{rule + 13 + i * _LINE_HEIGHT:.1f}" font-size="10" fill="{_TEXT_COLOR}">{_text(line)}</text>')
    return "".join(parts)


def _label(lines: list[str], x: float, bottom: float, anchor: str) -> str:
    """A transition's label, one `<text>` per line with the last line's baseline at `bottom` and a white halo so it stays
    readable over a line."""
    return "".join(
        f'<text x="{x:.1f}" y="{bottom - (len(lines) - 1 - i) * 12:.1f}" text-anchor="{anchor}" font-size="10" '
        f'fill="{_TEXT_COLOR}" stroke="#FFFFFF" stroke-width="3" paint-order="stroke">{_text(line)}</text>'
        for i, line in enumerate(lines)
    )


_Entry = tuple[TransitionOut, list[str], str | None, Point, list[Point], Point, Point, str, Directions]


def _transition_entries(transitions: list[TransitionOut], boxes: dict[uuid.UUID, StateOut], default_shape: str) -> list[_Entry]:
    """Where each transition is drawn: `(transition, label lines, the loop's path or None, start, vertices, end, middle)`. A
    transition whose state is not in the diagram is left out. The points each transition meets its states at come from
    `diagram_line_anchors`: no two share a path, transitions left on the same points are spread sideways, and several loops
    on one state take different corners. A transition's own shape wins over `default_shape`, the diagram's."""
    placed = assign_line_anchors(
        {
            str(state_id): AnchorBox(
                *_box(state),
                marker_attach_points(state.label, LabelPosition(state.label_position))
                if StateKind(state.kind) is not StateKind.STATE else ATTACH_POINTS,
            )
            for state_id, state in boxes.items()
        },
        [
            AnchorLine(
                str(t.id), str(t.source_state_id), str(t.target_state_id), t.source_point, t.target_point, tuple((p.x, p.y) for p in t.points),
            )
            for t in transitions
        ],
    )
    entries: list[_Entry] = []
    for t in transitions:
        source, target = boxes.get(t.source_state_id), boxes.get(t.target_state_id)
        anchor = placed.get(str(t.id))
        if source is None or target is None or anchor is None:
            continue
        lines = [part for part in transition_label(t.event, t.guard, t.action).split("\n") if part]
        if anchor.loop_slot is not None:
            box = _box(source)
            # A marker is drawn only at the middle of its sides, so its loop runs between those (and off the side its label is on).
            is_marker = StateKind(source.kind) is not StateKind.STATE
            sides = marker_attach_points(source.label, LabelPosition(source.label_position)) if is_marker else None
            loop = self_loop(box, anchor.loop_slot, sides)
            entries.append((t, lines, self_loop_path(box, anchor.loop_slot, sides), (0, 0), [], (0, 0), loop["label"], loop["align"], NO_DIRECTIONS))
            continue
        vertices: list[Point] = [(p.x, p.y) for p in t.points]
        (x1, y1), (x2, y2) = point_xy(_box(source), anchor.source), point_xy(_box(target), anchor.target)
        x1, y1, x2, y2 = x1 + anchor.shift[0], y1 + anchor.shift[1], x2 + anchor.shift[0], y2 + anchor.shift[1]
        shape = effective_shape(t.line_shape, default_shape)
        # A Curved transition leaves each state along its outward direction; no other shape uses the directions.
        directions: Directions = (
            line_directions(_box(source), _box(target), anchor.source, anchor.target, vertices) if shape == "curved" else NO_DIRECTIONS
        )
        middle = (
            line_middle((x1, y1), vertices, (x2, y2), shape, directions) if vertices or shape == "curved" else ((x1 + x2) / 2, (y1 + y2) / 2)
        )
        entries.append((t, lines, None, (x1, y1), vertices, (x2, y2), middle, "start", directions))
    return entries


def _hop_lines(entries: list[_Entry], default_shape: str) -> list[HopLine]:
    """The transitions that are lines (not loops) as hop candidates."""
    return [
        HopLine(str(t.id), start, vertices, end, effective_shape(t.line_shape, default_shape), directions)
        for t, _, loop, start, vertices, end, _, _, directions in entries if loop is None
    ]


def _transitions(entries: list[_Entry], hops: dict[str, str], default_shape: str) -> tuple[str, str]:
    """The lines and then the labels of the transitions (labels are drawn last, above every box); a transition in `hops` is
    drawn along its hop path (`diagram_line_hops`)."""
    drawn: list[str] = []
    labels: list[str] = []
    for t, lines, loop, (x1, y1), vertices, (x2, y2), (mx, my), align, directions in entries:
        if loop is not None:
            drawn.append(f'<path d="{loop}" fill="none" stroke="{_INK}" stroke-width="2" marker-end="url(#arrow)"/>')
            if lines:
                labels.append(_label(lines, mx + 4 if align == "start" else mx - 4, my - 4, align))
            continue
        shape = effective_shape(t.line_shape, default_shape)
        if vertices or str(t.id) in hops or shape != "straight":
            path = hops.get(str(t.id)) or line_path((x1, y1), vertices, (x2, y2), shape, directions)
            drawn.append(f'<path d="{path}" fill="none" stroke="{_INK}" stroke-width="2" marker-end="url(#arrow)"/>')
        else:
            drawn.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{_INK}" stroke-width="2" marker-end="url(#arrow)"/>'
            )
        if lines:
            labels.append(_label(lines, mx, my - 5, "middle"))
    return "".join(drawn), "".join(labels)


def render_state_machine(model: StateMachineModel) -> str:
    """The state machine diagram as an SVG document.

    Args:
        model: The diagram with its states, transitions and notes (`state_machines.model_of`).

    Returns:
        The SVG text.
    """
    states = model.states
    title = _text(f"{model.diagram.unique_code} {model.diagram.name}")
    notes: list[NoteOut] = _framed_notes(model.notes)
    drawn_notes = _drawn_notes(notes)
    defs = ""
    if not states and not drawn_notes:
        min_x, min_y, width, height = 0.0, 0.0, 320.0, 120.0
        body = '<text x="160" y="60" text-anchor="middle" font-size="12" fill="#64748B">No states</text>'
    else:
        depths = _depths(states)
        ordered = sorted(states, key=lambda s: depths[s.id])
        holding = {s.parent_state_id for s in states if s.parent_state_id is not None}
        boxes = {s.id: s for s in states}
        default_shape = model.diagram.line_shape.value
        entries = _transition_entries(model.transitions, boxes, default_shape)
        leader_runs = _leader_runs(
            notes, {}, {}, [], {s.id: _box(s) for s in states}, {entry[0].id: entry[6] for entry in entries},
        )
        hops: dict[str, str] = {}
        if model.diagram.line_hops:
            lines = _hop_lines(entries, default_shape)
            for n in drawn_notes:
                for leader in n.leaders:
                    if leader.id in leader_runs:
                        start, vertices, end, directions = leader_runs[leader.id]
                        lines.append(HopLine(str(leader.id), start, vertices, end, leader_shape(leader, default_shape), directions))
            hops = line_hops(lines)
        lines_svg, labels = _transitions(entries, hops, default_shape)
        note_defs, leaders, note_blocks = _notes(notes, leader_runs, hops, default_shape)
        defs += note_defs
        looped = {t.source_state_id for t in model.transitions if t.source_state_id == t.target_state_id}
        reach = {s.id: _reach(s) for s in states}
        xs = [v for s in states for v in (reach[s.id][0], reach[s.id][2] + (SELF_LOOP_REACH if s.id in looped else 0))]
        ys = [v for s in states for v in (reach[s.id][1] - (SELF_LOOP_REACH if s.id in looped else 6), reach[s.id][3] + 18)]
        for t in model.transitions:
            xs.extend(p.x for p in t.points)
            ys.extend(p.y for p in t.points)
        for n in drawn_notes:
            xs.extend((n.x, n.x + n.width))
            ys.extend((n.y, n.y + n.height))
            for leader in n.leaders:
                xs.extend(p.x for p in leader.points)
                ys.extend(p.y for p in leader.points)
                if leader.x is not None and leader.y is not None:
                    xs.append(leader.x)
                    ys.append(leader.y)
        min_x, min_y = min(xs) - _MARGIN, min(ys) - _MARGIN
        width, height = max(xs) - min_x + _MARGIN, max(ys) - min_y + _MARGIN
        composites = "".join(_composite(s) for s in ordered if s.id in holding and StateKind(s.kind) is StateKind.STATE)
        leaves = "".join(
            _marker(s) if StateKind(s.kind) is not StateKind.STATE else _state(s)
            for s in ordered if not (s.id in holding and StateKind(s.kind) is StateKind.STATE)
        )
        body = f"{composites}{lines_svg}{leaders}{leaves}{labels}{note_blocks}"
    arrow = (
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{_INK}"/></marker>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="Helvetica, Arial, sans-serif" role="img" aria-label="{title}">'
        f"<title>{title}</title><defs>{arrow}{defs}</defs>{body}</svg>"
    )
