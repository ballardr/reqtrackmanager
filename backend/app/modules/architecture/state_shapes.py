"""
Module: modules.architecture.state_shapes

The standard geometry of a state machine diagram's items (UML state machine notation), as the server's drawing uses it.

Responsibilities:
- Give the markers: the filled dot of an initial state, the ringed dot of a final state and the diamond of a choice, each
  with its frame size and SVG markup, and the larger form each takes when it carries a label (`LABELLED_MARKERS`), with the
  width its text may use and the lines it may take.
- Give the sizes a state, a composite state's header and padding and the corner radius use.
- Give the curve of a self loop (a transition from a state to itself) and the point its label sits at.
- Give the text a state's entry, exit and do lines and a transition's `event [guard] / action` label are written as.

Design decisions:
- **One table, two implementations.** The browser draws the markers and loops with TypeScript copies
  (`frontend/src/modules/architecture/stateShapes.ts`, `frontend/src/components/graphSelfLoop.ts`); this file is the
  server's copy for the SVG, and the shared cases in `stateShapeCases.json` and `graphSelfLoopCases.json` (written by
  `tests/test_architecture_state_shapes.py`) keep them equal; the label rules have their own copy in
  `stateMachineModel.ts` and cases in `stateLabelCases.json`. A change is made in both.
- **A label grows the symbol, not the stored box.** A symbol with a label is drawn at least as large as its labelled size,
  centred on the stored box (`marker_frame`), so setting or clearing a label never rewrites the layout and a diagram with no
  labels is drawn exactly as before. The label is plain text, wrapped to `text_width` over at most `text_lines` lines and cut
  with an ellipsis; a filled symbol's text is white (`LABEL_ON_FILL`), a diamond's the page's text colour.
- The shapes are fixed standard geometry, not the symbol library. The markup uses one neutral slate that keeps at least 3:1
  contrast on a light and a dark background, because an image cannot read the page's colour tokens.

Dependencies: `enums` (the state kinds).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from app.modules.architecture.enums import StateKind

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

#: The lines of text a symbol's label may take, and the label's font size and line height (diagram units).
LABEL_MAX_LINES = 3
LABEL_FONT_SIZE = 10
LABEL_LINE_HEIGHT = 12


class LabelledMarker(NamedTuple):
    """A marker drawn larger to hold a label.

    Attributes:
        size: The square frame's size.
        svg: The drawing at that size.
        text_width: The width the label's text may use, centred in the frame.
        on_fill: True when the text sits on the symbol's fill (drawn white), False when it sits on the page (the diamond).
    """

    size: int
    svg: str
    text_width: int
    on_fill: bool


#: Each marker kind's larger form. The initial dot is drawn larger only for a label; the final ring keeps its inner disc so the
#: text sits on the disc; the diamond is larger because only its middle holds text.
LABELLED_MARKERS: dict[StateKind, LabelledMarker] = {
    StateKind.INITIAL: LabelledMarker(52, f'{_open(52)}<circle cx="26" cy="26" r="25" fill="{_INK}"/></svg>', 36, True),
    StateKind.FINAL: LabelledMarker(
        72,
        f'{_open(72)}<circle cx="36" cy="36" r="34" fill="none" stroke="{_INK}" stroke-width="2"/>'
        f'<circle cx="36" cy="36" r="26" fill="{_INK}"/></svg>',
        38, True,
    ),
    StateKind.CHOICE: LabelledMarker(
        96,
        f'{_open(96)}<polygon points="48,1 95,48 48,95 1,48" fill="none" stroke="{_INK}" stroke-width="2" '
        'stroke-linejoin="round"/></svg>',
        48, False,
    ),
}


def marker_frame(kind: StateKind, box: tuple[float, float, float, float], label: str) -> tuple[float, float, float, float]:
    """The frame a marker is drawn in: its stored box, or, when it carries a label, at least the labelled size and centred on
    the stored box.

    Args:
        kind: An initial, final or choice state kind.
        box: `(x, y, width, height)` of the stored box.
        label: The symbol's label (blank means none).

    Returns:
        The frame to draw and to attach lines to.
    """
    x, y, w, h = box
    if not label.strip():
        return box
    size = LABELLED_MARKERS[kind].size
    width, height = max(w, size), max(h, size)
    return (x - (width - w) / 2, y - (height - h) / 2, width, height)


def shape_table() -> dict[str, Any]:
    """The table the browser's copy is tested against: every marker's size and markup (plain and labelled), and the state and
    composite sizes."""
    return {
        "markers": {kind.value: {"size": size, "svg": svg} for kind, (size, svg) in STATE_MARKERS.items()},
        "labelled_markers": {
            kind.value: {"size": m.size, "svg": m.svg, "text_width": m.text_width, "on_fill": m.on_fill}
            for kind, m in LABELLED_MARKERS.items()
        },
        "label": {"max_lines": LABEL_MAX_LINES, "font_size": LABEL_FONT_SIZE, "line_height": LABEL_LINE_HEIGHT},
        "state": {
            "width": STATE_DEFAULT_WIDTH, "height": STATE_DEFAULT_HEIGHT, "corner_radius": STATE_CORNER_RADIUS,
        },
        "composite": {"header_height": COMPOSITE_HEADER_HEIGHT, "padding": COMPOSITE_PADDING},
    }


def self_loop(box: tuple[float, float, float, float]) -> dict[str, Point]:
    """The loop of a box: a cubic curve leaving the top side three quarters across and returning to the right side.

    Args:
        box: `(x, y, width, height)` of the box.

    Returns:
        `start`, `control1`, `control2`, `end` (the cubic's points) and `label` (the curve's middle: the bottom-left
        corner of the label's text, so it rises above the box and clear of it).
    """
    x, y, w, h = box
    start = (x + 0.75 * w, y)
    control1 = (x + 0.75 * w, y - SELF_LOOP_REACH)
    control2 = (x + w + SELF_LOOP_REACH, y + 0.25 * h)
    end = (x + w, y + 0.25 * h)
    # The point at t = 0.5 of a cubic Bezier is (P0 + 3 P1 + 3 P2 + P3) / 8.
    label = (
        (start[0] + 3 * control1[0] + 3 * control2[0] + end[0]) / 8,
        (start[1] + 3 * control1[1] + 3 * control2[1] + end[1]) / 8,
    )
    return {"start": start, "control1": control1, "control2": control2, "end": end, "label": label}


def self_loop_path(box: tuple[float, float, float, float]) -> str:
    """The SVG path (`M … C …`) of a box's self loop, numbers rounded to two decimals."""
    loop = self_loop(box)

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
