"""
Module: modules.architecture.state_machine_svg

Renders a state machine diagram (`schemas.StateMachineModel`) as one SVG document, for the server's SVG endpoint (the PNG
download is this document drawn in the browser), in UML state machine notation.

Responsibilities:
- Draw each ordinary state as a rounded rectangle with its name, code and `entry /`, `exit /` and `do /` lines, a composite
  state (one that holds others) as a frame with its name in a header strip, and the initial, final and choice states as the
  standard markers of `state_shapes`.
- Draw each transition as an arrow between two attach points (the ones a person chose, else the nearest; markers offer only
  the middle of a side), a transition from a state to itself as the loop of `state_shapes`, and its `event [guard] / action`
  label.

Design decisions:
- **Everything user-supplied is text.** Names, codes, actions and labels are XML-escaped and stripped of control characters
  (the helpers of `diagram_svg`); the only markup embedded is the fixed marker table of `state_shapes`.
- **Same geometry as the screen.** The boxes are the stored layout (absolute coordinates at any nesting), the attach points use
  the shared rule (`diagram_points`), the loop and the marker shapes the shared table, and the label rule the shared
  `transition_label`, so the file shows what the editor shows.
- **Light-theme colours on a transparent background**, as the block diagram's file; the findings' tints are an editing aid and
  are not drawn.
- A composite state shows its name and code only: its inside is where its child states are drawn.
- **Deterministic.** Boxes and lines are drawn in the order of the model, parents first, so equal models give equal bytes.

Dependencies: `schemas` (the model), `state_shapes`, `diagram_points`, `diagram_svg` (text safety and wrapping), `labels`.
"""

from __future__ import annotations

import math
import uuid

from app.modules.architecture.diagram_points import ATTACH_POINTS, SIDE_POINTS, line_points, point_xy
from app.modules.architecture.diagram_svg import _ROOT, _note_lines, _text, _wrap
from app.modules.architecture.enums import StateKind
from app.modules.architecture.labels import STATE_KIND_LABEL
from app.modules.architecture.schemas import StateMachineModel, StateOut, TransitionOut
from app.modules.architecture.state_shapes import (
    COMPOSITE_HEADER_HEIGHT,
    SELF_LOOP_REACH,
    STATE_CORNER_RADIUS,
    STATE_MARKERS,
    action_lines,
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
    return (state.x, state.y, state.width, state.height)


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
    """A marker state: its standard drawing scaled into the state's box, with its name below it when it is not just the kind's
    own label."""
    size, markup = STATE_MARKERS[StateKind(state.kind)]
    match = _ROOT.search(markup)
    inner = markup[match.end(): -len("</svg>")] if match else ""
    scale_x, scale_y = state.width / size, state.height / size
    drawing = f'<g transform="translate({state.x:.1f} {state.y:.1f}) scale({scale_x:.4f} {scale_y:.4f})">{inner}</g>'
    if state.name.strip() and state.name != STATE_KIND_LABEL.get(state.kind):
        cx, ty = state.x + state.width / 2, state.y + state.height + 13
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


def _transitions(
    transitions: list[TransitionOut], boxes: dict[uuid.UUID, StateOut],
) -> tuple[str, str]:
    """The lines and then the labels of the transitions (labels are drawn last, above every box)."""
    drawn: list[str] = []
    labels: list[str] = []
    totals: dict[frozenset, int] = {}
    for t in transitions:
        key = frozenset((t.source_state_id, t.target_state_id))
        totals[key] = totals.get(key, 0) + 1
    rank: dict[frozenset, int] = {}
    for t in transitions:
        source, target = boxes.get(t.source_state_id), boxes.get(t.target_state_id)
        if source is None or target is None:
            continue
        lines = [part for part in transition_label(t.event, t.guard, t.action).split("\n") if part]
        if source.id == target.id:
            box = _box(source)
            drawn.append(
                f'<path d="{self_loop_path(box)}" fill="none" stroke="{_INK}" stroke-width="2" marker-end="url(#arrow)"/>'
            )
            if lines:
                lx, ly = self_loop(box)["label"]
                labels.append(_label(lines, lx + 4, ly - 4, "start"))
            continue
        key = frozenset((t.source_state_id, t.target_state_id))
        index = rank.get(key, 0)
        rank[key] = index + 1
        offset = (index - (totals[key] - 1) / 2) * 16
        a_marker, b_marker = StateKind(source.kind) is not StateKind.STATE, StateKind(target.kind) is not StateKind.STATE
        pa, pb = line_points(
            _box(source), _box(target), t.source_point, t.target_point,
            SIDE_POINTS if a_marker else ATTACH_POINTS, SIDE_POINTS if b_marker else ATTACH_POINTS,
        )
        (x1, y1), (x2, y2) = point_xy(_box(source), pa), point_xy(_box(target), pb)
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        nx, ny = -(y2 - y1) / length * offset, (x2 - x1) / length * offset
        x1, y1, x2, y2 = x1 + nx, y1 + ny, x2 + nx, y2 + ny
        drawn.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{_INK}" stroke-width="2" marker-end="url(#arrow)"/>'
        )
        if lines:
            labels.append(_label(lines, (x1 + x2) / 2, (y1 + y2) / 2 - 5, "middle"))
    return "".join(drawn), "".join(labels)


def render_state_machine(model: StateMachineModel) -> str:
    """The state machine diagram as an SVG document.

    Args:
        model: The diagram with its states and transitions (`state_machines.model_of`).

    Returns:
        The SVG text.
    """
    states = model.states
    title = _text(f"{model.diagram.unique_code} {model.diagram.name}")
    if not states:
        min_x, min_y, width, height = 0.0, 0.0, 320.0, 120.0
        body = '<text x="160" y="60" text-anchor="middle" font-size="12" fill="#64748B">No states</text>'
    else:
        depths = _depths(states)
        ordered = sorted(states, key=lambda s: depths[s.id])
        holding = {s.parent_state_id for s in states if s.parent_state_id is not None}
        boxes = {s.id: s for s in states}
        lines, labels = _transitions(model.transitions, boxes)
        looped = {t.source_state_id for t in model.transitions if t.source_state_id == t.target_state_id}
        xs = [v for s in states for v in (s.x, s.x + s.width + (SELF_LOOP_REACH if s.id in looped else 0))]
        ys = [v for s in states for v in (s.y - (SELF_LOOP_REACH if s.id in looped else 6), s.y + s.height + 18)]
        min_x, min_y = min(xs) - _MARGIN, min(ys) - _MARGIN
        width, height = max(xs) - min_x + _MARGIN, max(ys) - min_y + _MARGIN
        frames = "".join(_composite(s) for s in ordered if s.id in holding and StateKind(s.kind) is StateKind.STATE)
        leaves = "".join(
            _marker(s) if StateKind(s.kind) is not StateKind.STATE else _state(s)
            for s in ordered if not (s.id in holding and StateKind(s.kind) is StateKind.STATE)
        )
        body = f"{frames}{lines}{leaves}{labels}"
    defs = (
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{_INK}"/></marker>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="Helvetica, Arial, sans-serif" role="img" aria-label="{title}">'
        f"<title>{title}</title><defs>{defs}</defs>{body}</svg>"
    )
