"""
Module: diagram_line_path

The shape of a drawn line that has waypoints: the SVG path through them and the point its label sits at. Pure functions
with no database or HTTP, used by the server's drawings (block diagram and state machine SVG).

Responsibilities:
- Turn a line's two end points and its ordered waypoints into an SVG path, straight between the points or smooth
  (a curve through every point).
- Give the middle of the line, measured along the straight segments, where a label and a comment pin sit.

Design decisions:
- Coordinates are absolute canvas units, so a box nested in another and the snap grid behave as on the screen.
- Smooth is a Catmull-Rom curve (tension one half) written as cubic Beziers (`curve_spans`): the control points of the segment
  from `p1` to `p2` are `p1 + (p2 - p0) / 6` and `p2 - (p3 - p1) / 6`, the missing neighbour at either end being the end itself.
- A line with no waypoints is always straight, whatever `smooth` says: there is nothing to curve through.
- The browser draws with a TypeScript copy (`frontend/src/components/graphLinePath.ts`); `graphLinePathCases.json` holds the
  cases both are tested against (`tests/test_architecture_line_path.py`), so a change to the rule is made in both.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

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


def curve_spans(start: Point, points: Sequence[Point], end: Point) -> list[tuple[Point, Point, Point, Point]]:
    """The cubic Bezier spans of a smooth line through `start`, `points` and `end`, one per segment.

    Returns:
        `(from, control 1, control 2, to)` for each segment in order; the ends of a span are the line's own points, so the curve
        passes through every one.
    """
    nodes = [start, *points, end]
    spans: list[tuple[Point, Point, Point, Point]] = []
    for i in range(len(nodes) - 1):
        p0 = nodes[i - 1] if i > 0 else nodes[i]
        p1, p2 = nodes[i], nodes[i + 1]
        p3 = nodes[i + 2] if i + 2 < len(nodes) else nodes[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        spans.append((p1, c1, c2, p2))
    return spans


def line_path(start: Point, points: Sequence[Point], end: Point, smooth: bool) -> str:
    """The SVG path of a line from `start` to `end` through `points`.

    Args:
        start: The point on the source box.
        points: The waypoints in order from the source to the target (may be empty).
        end: The point on the target box.
        smooth: True for a curve through every point, False for straight segments.

    Returns:
        `M … L …` for straight segments (and for a line with no waypoints), `M … C …` for a smooth line.
    """
    nodes = [start, *points, end]
    if not smooth or not points:
        return "M " + " L ".join(_p(point) for point in nodes)
    parts = [f"M {_p(nodes[0])}"]
    for _, c1, c2, p2 in curve_spans(start, points, end):
        parts.append(f"C {_p(c1)} {_p(c2)} {_p(p2)}")
    return " ".join(parts)


def line_middle(start: Point, points: Sequence[Point], end: Point) -> Point:
    """The point half way along the straight segments from `start` through `points` to `end` (the label position).

    A curve's middle is taken on the straight segments too, so the label stays close to a smooth line without a curve
    length to compute.
    """
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
