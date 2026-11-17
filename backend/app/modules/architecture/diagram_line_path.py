"""
Module: diagram_line_path

The shape of a drawn line that has waypoints: the SVG path through them and the point its label sits at. Pure functions
with no database or HTTP, used by the server's drawings (block diagram and state machine SVG).

Responsibilities:
- Turn a line's two end points, its ordered waypoints and its shape (Straight, Curved or Spline) into an SVG path.
- Give the middle of the line, where a label and a comment pin sit.
- Resolve a line's own shape against its diagram's default.

Design decisions:
- Coordinates are absolute canvas units, so a box nested in another and the snap grid behave as on the screen.
- Smooth is a Catmull-Rom curve (tension one half) written as cubic Beziers (`curve_spans`): the control points of the segment
  from `p1` to `p2` are `p1 + (p2 - p0) / 6` and `p2 - (p3 - p1) / 6`, the missing neighbour at either end being the end itself.
- Three shapes (`LINE_SHAPES`): Straight is segments through the waypoints; Spline is the Catmull-Rom curve through them (straight
  with none, there being nothing to curve through); Curved is that same curve through the waypoints when there are any, and with
  none one arc bowed to the left of the line's direction (`bow_span`). The arc is a single cubic span, so the hop rule treats it as
  any other curve span. A line stores its own shape or none, which follows its diagram's default (`effective_shape`).
- The browser draws with a TypeScript copy (`frontend/src/components/graphLinePath.ts`); `graphLinePathCases.json` holds the
  cases both are tested against (`tests/test_architecture_line_path.py`), so a change to the rule is made in both.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence

Point = tuple[float, float]
Span = tuple[Point, Point, Point, Point]

#: The shapes a line can be drawn in; a diagram's default is one of them and a line's own may also be unset (the default).
LINE_SHAPES = ("straight", "curved", "spline")
#: How far a Curved line with no waypoints bows from its chord, as a fraction of the chord's length, and the most it may bow.
BOW_RATIO = 0.25
BOW_LIMIT = 60.0

#: The most waypoints one line may have (the schemas' list cap).
MAX_WAYPOINTS = 16


def _n(value: float) -> str:
    """A number rounded to two decimals, halves toward positive infinity as the browser's `Math.round` does, with no
    trailing zeros (`-0` is written `0`)."""
    text = f"{math.floor(value * 100 + 0.5) / 100:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _p(point: Point) -> str:
    return f"{_n(point[0])} {_n(point[1])}"


def format_point(point: Point) -> str:
    """A point as the two numbers of an SVG path command, written by the one rounding rule."""
    return _p(point)


def effective_shape(own: str | enum.Enum | None, default: str | enum.Enum) -> str:
    """The shape a line is drawn in: its own when it has one, else its diagram's default.

    Args:
        own: The line's stored shape, or `None` to follow the diagram.
        default: The diagram's default shape.

    Returns:
        A value of `LINE_SHAPES` (an unknown value is read as straight).
    """
    shape = own if own is not None else default
    plain = shape.value if isinstance(shape, enum.Enum) else shape
    return plain if plain in LINE_SHAPES else "straight"


def bow_span(start: Point, end: Point) -> Span | None:
    """The one cubic span of a Curved line that has no waypoints: an arc bowed to the left of the direction of travel.

    The control points are a third and two thirds of the way along the chord, each moved sideways by the bow, so the curve
    leaves the chord by three quarters of it at its middle.

    Returns:
        `(start, control 1, control 2, end)`, or `None` when the two points coincide (nothing to bow).
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        return None
    bow = min(length * BOW_RATIO, BOW_LIMIT)
    nx, ny = dy / length * bow, -dx / length * bow
    c1 = (start[0] + dx / 3 + nx, start[1] + dy / 3 + ny)
    c2 = (start[0] + dx * 2 / 3 + nx, start[1] + dy * 2 / 3 + ny)
    return (start, c1, c2, end)


def shape_spans(start: Point, points: Sequence[Point], end: Point, shape: str) -> list[Span]:
    """The cubic spans a line of `shape` is drawn with, or none when it is drawn as straight segments.

    Returns:
        Straight: none. Spline: the Catmull-Rom spans through the waypoints (none without waypoints). Curved: the same spans
        through the waypoints, or the single bowed arc without any.
    """
    if shape == "straight":
        return []
    if points:
        return curve_spans(start, points, end)
    if shape == "curved":
        arc = bow_span(start, end)
        return [arc] if arc is not None else []
    return []


def curve_spans(start: Point, points: Sequence[Point], end: Point) -> list[Span]:
    """The cubic Bezier spans of a smooth line through `start`, `points` and `end`, one per segment.

    Returns:
        `(from, control 1, control 2, to)` for each segment in order; the ends of a span are the line's own points, so the curve
        passes through every one.
    """
    nodes = [start, *points, end]
    spans: list[Span] = []
    for i in range(len(nodes) - 1):
        p0 = nodes[i - 1] if i > 0 else nodes[i]
        p1, p2 = nodes[i], nodes[i + 1]
        p3 = nodes[i + 2] if i + 2 < len(nodes) else nodes[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        spans.append((p1, c1, c2, p2))
    return spans


def line_path(start: Point, points: Sequence[Point], end: Point, shape: str = "straight") -> str:
    """The SVG path of a line from `start` to `end` through `points`.

    Args:
        start: The point on the source box.
        points: The waypoints in order from the source to the target (may be empty).
        end: The point on the target box.
        shape: A value of `LINE_SHAPES`.

    Returns:
        `M … L …` for straight segments (and for a line that has nothing to curve), `M … C …` for a curved one.
    """
    spans = shape_spans(start, points, end, shape)
    if not spans:
        return "M " + " L ".join(_p(point) for point in [start, *points, end])
    parts = [f"M {_p(start)}"]
    for _, c1, c2, p2 in spans:
        parts.append(f"C {_p(c1)} {_p(c2)} {_p(p2)}")
    return " ".join(parts)


def line_middle(start: Point, points: Sequence[Point], end: Point, shape: str = "straight") -> Point:
    """The point half way along the straight segments from `start` through `points` to `end` (the label position).

    A curve through waypoints takes its middle on the straight segments too, so the label stays close to it without a curve
    length to compute. A Curved line with no waypoints has its label on the arc itself, whose middle is a third of the way
    from each control point (`(start + 3 c1 + 3 c2 + end) / 8`).
    """
    if shape == "curved" and not points:
        arc = bow_span(start, end)
        if arc is not None:
            return ((arc[0][0] + 3 * arc[1][0] + 3 * arc[2][0] + arc[3][0]) / 8, (arc[0][1] + 3 * arc[1][1] + 3 * arc[2][1] + arc[3][1]) / 8)
    nodes = [start, *points, end]
    lengths = [math.dist(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]
    total = sum(lengths)
    if total == 0:
        return start
    remaining = total / 2
    for i, length in enumerate(lengths):
        if remaining <= length or i == len(lengths) - 1:
            t = 0.0 if length == 0 else min(remaining / length, 1.0)
            a, b = nodes[i], nodes[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        remaining -= length
    return end  # pragma: no cover - the loop returns on its last segment


def bundle_line_shape(entry: dict[str, object]) -> str | None:
    """A line's own shape as a bundle row carries it: `line_shape` when it names a shape, else (a bundle written before shapes)
    `smooth: true` reads as a spline; anything else is no shape of its own (it follows the diagram's default)."""
    shape = entry.get("line_shape")
    if isinstance(shape, str) and shape in LINE_SHAPES:
        return shape
    return "spline" if entry.get("smooth") is True else None


def bundle_default_shape(entry: dict[str, object]) -> str:
    """A diagram's default shape as a bundle row carries it; a missing or unknown value is straight."""
    shape = entry.get("line_shape")
    return shape if isinstance(shape, str) and shape in LINE_SHAPES else "straight"


#: The largest absolute coordinate a waypoint may have (the schemas' coordinate limit).
COORDINATE_LIMIT = 1_000_000.0


def clean_waypoints(raw: object) -> list[dict[str, float]]:
    """The valid vertices of a stored or imported value, as `{x, y}` floats.

    Args:
        raw: What a bundle carries: normally a list of `{x, y}`; anything else is read as no vertices.

    Returns:
        The entries with finite numeric `x` and `y` inside the coordinate limit, at most `MAX_WAYPOINTS`; others are left out.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, float]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        x, y = entry.get("x"), entry.get("y")
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int | float) or not isinstance(y, int | float):
            continue
        if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > COORDINATE_LIMIT or abs(y) > COORDINATE_LIMIT:
            continue
        out.append({"x": float(x), "y": float(y)})
    return out[:MAX_WAYPOINTS]
