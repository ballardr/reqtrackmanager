"""
Module: modules.architecture.state_shapes

The standard geometry of a state machine diagram's items (UML state machine notation), as the server's drawing uses it.

Responsibilities:
- Give the markers: the filled dot of an initial state, the ringed dot of a final state and the diamond of a choice, each
  with its frame size and SVG markup, and the drawing each takes at any larger size when it carries a label (`labelled_svg`).
- Give the sizes a state, a composite state's header and padding and the corner radius use.
- Give the curve of a self loop (a transition from a state to itself) and the point its label sits at.
- Give the text a state's entry, exit and do lines and a transition's `event [guard] / action` label are written as.

Design decisions:
- **One table, two implementations.** The browser draws the markers and loops with TypeScript copies
  (`frontend/src/modules/architecture/stateShapes.ts`, `frontend/src/components/graphSelfLoop.ts`); this file is the
  server's copy for the SVG, and the shared cases in `stateShapeCases.json` and `graphSelfLoopCases.json` (written by
  `tests/test_architecture_state_shapes.py`) keep them equal; the label rules have their own copy in
  `stateMachineModel.ts` and cases in `stateLabelCases.json`. A change is made in both.
- **A label grows the symbol, not the stored box.** A symbol with a label is drawn at least as large as its label needs
  (`diagram_symbol_label.fit_label`: whole words, never split), centred on the stored box (`marker_frame`), so setting or
  clearing a label never rewrites the layout and a diagram with no labels is drawn exactly as before. A filled symbol's text is
  white (`LABEL_ON_FILL_KINDS`), a diamond's the page's text colour.
- The shapes are fixed standard geometry, not the symbol library. The markup uses one neutral slate that keeps at least 3:1
  contrast on a light and a dark background, because an image cannot read the page's colour tokens.

Dependencies: `enums` (the state kinds), `diagram_symbol_label` (the label's size and lines).
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.modules.architecture.diagram_points import SIDE_POINTS
from app.modules.architecture.diagram_symbol_label import (
    BASE_SIZE,
    LABEL_FONT_SIZE,
    LABEL_LINE_HEIGHT,
    MAX_SIZE,
    SIZE_STEP,
    TEXT_PERCENT,
    fit_label,
)
from app.modules.architecture.enums import AttachPoint, LabelPosition, StateKind

Point = tuple[float, float]

#: How far a self loop reaches beyond its box, in diagram units.
SELF_LOOP_REACH = 36.0

#: The size a new ordinary state is drawn at, and the corner radius of a state and of a composite state's frame.
STATE_DEFAULT_WIDTH = 160
STATE_DEFAULT_HEIGHT = 64
STATE_CORNER_RADIUS = 12

#: A composite state's name strip across the top of its frame, and the gap its child states keep from the frame.
COMPOSITE_HEADER_HEIGHT = 32
COMPOSITE_PADDING = 16

#: The longest `event [guard] / action` shown on one line; a longer label breaks before the action.
LABEL_LINE_LENGTH = 28

_INK = "#64748b"


def _open(size: int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'


#: Each marker kind with its square frame size and SVG markup.
STATE_MARKERS: dict[StateKind, tuple[int, str]] = {
    StateKind.INITIAL: (20, f'{_open(20)}<circle cx="10" cy="10" r="9" fill="{_INK}"/></svg>'),
    StateKind.FINAL: (
        28,
        f'{_open(28)}<circle cx="14" cy="14" r="12.5" fill="none" stroke="{_INK}" stroke-width="2"/>'
        f'<circle cx="14" cy="14" r="7" fill="{_INK}"/></svg>',
    ),
    StateKind.CHOICE: (
        36,
        f'{_open(36)}<polygon points="18,1 35,18 18,35 1,18" fill="none" stroke="{_INK}" stroke-width="2" '
        'stroke-linejoin="round"/></svg>',
    ),
}


#: The text colour on a filled symbol (an initial state's dot, a final state's inner disc): white on the slate ink is 4.7:1.
LABEL_ON_FILL = "#FFFFFF"

#: The kinds whose label sits on the symbol's fill (an initial state's dot, a final state's inner disc); a choice's sits on the page.
LABEL_ON_FILL_KINDS = frozenset({StateKind.INITIAL, StateKind.FINAL})

#: The sizes the shared table samples each labelled drawing at (the base size is each kind's own).
_SAMPLE_SIZE = 200


def labelled_svg(kind: StateKind, size: int) -> str:
    """A marker drawn at `size` (a multiple of `SIZE_STEP`) to hold a label. The initial dot is drawn larger only for a label;
    the final ring keeps its inner disc so the text sits on the disc; the diamond is larger because only its middle holds text.
    Strokes keep their width at every size.

    Args:
        kind: An initial, final or choice state kind.
        size: The side of the square frame.

    Returns:
        The SVG markup, with a `viewBox` of `size` by `size`.
    """
    half = size // 2
    if kind is StateKind.INITIAL:
        return f'{_open(size)}<circle cx="{half}" cy="{half}" r="{half - 1}" fill="{_INK}"/></svg>'
    if kind is StateKind.FINAL:
        disc = (26 * size + 36) // 72
        return (
            f'{_open(size)}<circle cx="{half}" cy="{half}" r="{half - 1}" fill="none" stroke="{_INK}" stroke-width="2"/>'
            f'<circle cx="{half}" cy="{half}" r="{disc}" fill="{_INK}"/></svg>'
        )
    return (
        f'{_open(size)}<polygon points="{half},1 {size - 1},{half} {half},{size - 1} 1,{half}" fill="none" stroke="{_INK}" '
        'stroke-width="2" stroke-linejoin="round"/></svg>'
    )


def marker_frame(
    kind: StateKind, box: tuple[float, float, float, float], label: str, position: LabelPosition = LabelPosition.INSIDE,
) -> tuple[float, float, float, float]:
    """The frame a marker is drawn in: its stored box, or, when it carries a label inside it, at least the size the label
    needs and centred on the stored box. A label outside the symbol leaves the symbol at its stored box (the text is drawn
    beside it, see `diagram_symbol_label.beside_label`).

    Args:
        kind: An initial, final or choice state kind.
        box: `(x, y, width, height)` of the stored box.
        label: The symbol's label (blank means none).
        position: Where the label is drawn.

    Returns:
        The frame to draw and to attach lines to.
    """
    x, y, w, h = box
    layout = fit_label(kind, label) if position is LabelPosition.INSIDE else None
    if layout is None:
        return box
    size = layout.size
    width, height = max(w, size), max(h, size)
    return (x - (width - w) / 2, y - (height - h) / 2, width, height)


#: The side of a symbol each outside label position covers (the point that side's attach point is).
_LABEL_SIDE: dict[LabelPosition, AttachPoint] = {
    LabelPosition.LEFT: AttachPoint.LEFT, LabelPosition.RIGHT: AttachPoint.RIGHT,
    LabelPosition.ABOVE: AttachPoint.TOP, LabelPosition.BELOW: AttachPoint.BOTTOM,
}


def marker_attach_points(label: str, position: LabelPosition) -> tuple[AttachPoint, ...]:
    """The attach points an open line end may choose on a marker: the middle of each side, without the side its label is on
    (a line there would run through the text). A fixed end a person chose is used as given.

    Args:
        label: The symbol's label (blank means none, so every side is offered).
        position: Where the label is drawn.

    Returns:
        The points, in tie-break order.
    """
    covered = _LABEL_SIDE.get(position) if label.strip() else None
    return tuple(point for point in SIDE_POINTS if point is not covered)


def shape_table() -> dict[str, Any]:
    """The table the browser's copy is tested against: every marker's size and markup (plain, and labelled at its base size and
    at a sample size), the label's measures, and the state and composite sizes."""
    return {
        "markers": {kind.value: {"size": size, "svg": svg} for kind, (size, svg) in STATE_MARKERS.items()},
        "labelled_markers": {
            kind.value: {
                "base_size": BASE_SIZE[kind], "text_percent": TEXT_PERCENT[kind], "on_fill": kind in LABEL_ON_FILL_KINDS,
                "svg_at_base": labelled_svg(kind, BASE_SIZE[kind]), "svg_at_sample": labelled_svg(kind, _SAMPLE_SIZE),
            }
            for kind in BASE_SIZE
        },
        "label": {
            "font_size": LABEL_FONT_SIZE, "line_height": LABEL_LINE_HEIGHT, "size_step": SIZE_STEP, "max_size": MAX_SIZE,
            "sample_size": _SAMPLE_SIZE,
        },
        "state": {
            "width": STATE_DEFAULT_WIDTH, "height": STATE_DEFAULT_HEIGHT, "corner_radius": STATE_CORNER_RADIUS,
        },
        "composite": {"header_height": COMPOSITE_HEADER_HEIGHT, "padding": COMPOSITE_PADDING},
    }


class SelfLoopShape(TypedDict):
    """A loop's cubic curve, its label point and the side of that point the text runs."""

    start: Point
    control1: Point
    control2: Point
    end: Point
    label: Point
    align: str


def self_loop(box: tuple[float, float, float, float], slot: int = 0) -> SelfLoopShape:
    """The loop of a box: a cubic curve leaving the top side three quarters across and returning to the right side.

    Args:
        box: `(x, y, width, height)` of the box.
        slot: Which corner the loop takes: 0 the top right (the default), then 1 the bottom right, 2 the bottom left and 3
            the top left; from 4 the loops go round again, reaching further out each time.

    Returns:
        `start`, `control1`, `control2`, `end` (the cubic's points), `label` (the curve's middle: the bottom-left corner of
        the label's text, so it rises above the box and clear of it) and `align` (`start` when the text begins at the label
        point, `end` when it ends there, for a loop on a left corner).
    """
    x, y, w, h = box
    corner = slot % 4
    reach = SELF_LOOP_REACH * (1 + slot // 4)
    right = corner in (0, 1)
    bottom = corner in (1, 2)
    across = 0.75 if right else 0.25
    down = 0.75 if bottom else 0.25
    side_y = y + h if bottom else y
    side_x = x + w if right else x
    start = (x + across * w, side_y)
    control1 = (x + across * w, side_y + reach if bottom else side_y - reach)
    control2 = (side_x + reach if right else side_x - reach, y + down * h)
    end = (side_x, y + down * h)
    # The point at t = 0.5 of a cubic Bezier is (P0 + 3 P1 + 3 P2 + P3) / 8.
    label = (
        (start[0] + 3 * control1[0] + 3 * control2[0] + end[0]) / 8,
        (start[1] + 3 * control1[1] + 3 * control2[1] + end[1]) / 8,
    )
    return {
        "start": start, "control1": control1, "control2": control2, "end": end, "label": label,
        "align": "start" if right else "end",
    }


def self_loop_path(box: tuple[float, float, float, float], slot: int = 0) -> str:
    """The SVG path (`M … C …`) of a box's self loop in `slot`, numbers rounded to two decimals."""
    loop = self_loop(box, slot)

    def n(value: float) -> str:
        return f"{round(value, 2):.2f}".rstrip("0").rstrip(".")

    def p(point: Point) -> str:
        return f"{n(point[0])} {n(point[1])}"

    return f"M {p(loop['start'])} C {p(loop['control1'])} {p(loop['control2'])} {p(loop['end'])}"


def action_lines(entry_action: str, exit_action: str, activity: str) -> list[str]:
    """The `entry /`, `exit /` and `do /` lines of a state, one each for the ones that are set (empty when none is)."""
    return [
        line for line in (
            f"entry / {entry_action}" if entry_action else "",
            f"exit / {exit_action}" if exit_action else "",
            f"do / {activity}" if activity else "",
        ) if line
    ]


def transition_label(event: str, guard: str, action: str) -> str:
    """The text on a transition's line: `event [guard] / action`, broken before the action when it is long.

    Args:
        event: The event that triggers the transition (may be empty).
        guard: The condition that must hold (may be empty).
        action: What is done when it is taken (may be empty).

    Returns:
        The label, with a line break (`\\n`) before the action when the one-line form is longer than `LABEL_LINE_LENGTH`
        and there is an event or guard to keep on the first line; empty when all three are empty.
    """
    head = " ".join(part for part in (event, f"[{guard}]" if guard else "") if part)
    if not action:
        return head
    one = f"{head} / {action}" if head else f"/ {action}"
    return one if len(one) <= LABEL_LINE_LENGTH or not head else f"{head}\n/ {action}"
