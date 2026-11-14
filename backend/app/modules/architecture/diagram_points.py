"""
Module: modules.architecture.diagram_points

Where a diagram line meets its boxes: the eight attach points of a box and the rule that picks the two a line uses.

Responsibilities:
- Give the position of each of a box's eight attach points (the middle of each side and the four corners).
- Choose the points of one line: the stored choice for an end when a person made one, and otherwise the nearest.

Design decisions:
- **One rule, two implementations.** The browser draws lines with a TypeScript port (`components/graphAttachPoints.ts`) so
  they follow a box while it is dragged; this file is the server's copy, used for the SVG, and the shared cases in
  `frontend/src/components/graphAttachPointCases.json` (written by `tests/test_architecture_diagram_points.py`) keep the
  two equal. A change to the rule is made in both.
- **Nearest means least squared distance**, compared with a small tolerance and decided in the fixed order of
  `ATTACH_POINTS` (the sides before the corners) so a tie, such as two boxes side by side whose facing corners are as
  close as their facing sides, always gives the sides. Squared distances avoid a square root, so both languages agree to
  the last bit.
- **A marker offers fewer points.** A dot or a diamond (`SIDE_POINTS`) is met only at the middle of a side; the browser's
  box carries the same list as `points`.
- **An end left to chance follows the other.** With one end fixed by a person, the other end is the point of its box
  nearest to the fixed one; with neither fixed, the pair of points nearest each other.

Dependencies: `enums` (the point names).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.modules.architecture.enums import AttachPoint

#: A box as `(x, y, width, height)`.
Box = tuple[float, float, float, float]
Point = tuple[float, float]

#: The points in tie-break order: the middle of each side, then the corners.
ATTACH_POINTS: tuple[AttachPoint, ...] = (
    AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT,
    AttachPoint.TOP_RIGHT, AttachPoint.BOTTOM_RIGHT, AttachPoint.BOTTOM_LEFT, AttachPoint.TOP_LEFT,
)

#: The middle of each side: all a marker (a dot or a diamond) offers, since its corners are not on its outline.
SIDE_POINTS: tuple[AttachPoint, ...] = (AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT)

#: A distance must be smaller than the best so far by more than this to win, so equal distances keep the earlier point.
_TOLERANCE = 1e-6


def point_xy(box: Box, point: AttachPoint) -> Point:
    """Where `point` of `box` is.

    Args:
        box: `(x, y, width, height)` of the box.
        point: The attach point.

    Returns:
        The point's `(x, y)`.
    """
    x, y, w, h = box
    positions: Mapping[AttachPoint, Point] = {
        AttachPoint.TOP: (x + w / 2, y), AttachPoint.RIGHT: (x + w, y + h / 2),
        AttachPoint.BOTTOM: (x + w / 2, y + h), AttachPoint.LEFT: (x, y + h / 2),
        AttachPoint.TOP_RIGHT: (x + w, y), AttachPoint.BOTTOM_RIGHT: (x + w, y + h),
        AttachPoint.BOTTOM_LEFT: (x, y + h), AttachPoint.TOP_LEFT: (x, y),
    }
    return positions[point]


def _squared(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def nearest_pair(
    source: Box, target: Box,
    source_offered: tuple[AttachPoint, ...] = ATTACH_POINTS, target_offered: tuple[AttachPoint, ...] = ATTACH_POINTS,
) -> tuple[AttachPoint, AttachPoint]:
    """The point of each box that lies nearest each other (ties go to the sides, then in `ATTACH_POINTS` order).

    Args:
        source: The source box.
        target: The target box.
        source_offered: The points the source box offers (in `ATTACH_POINTS` order); all eight by default.
        target_offered: The points the target box offers; all eight by default.
    """
    best = float("inf")
    chosen = (source_offered[0], target_offered[0])
    for a in source_offered:
        pa = point_xy(source, a)
        for b in target_offered:
            distance = _squared(pa, point_xy(target, b))
            if distance < best - _TOLERANCE:
                best, chosen = distance, (a, b)
    return chosen


def nearest_point(box: Box, to: Point, offered: tuple[AttachPoint, ...] = ATTACH_POINTS) -> AttachPoint:
    """The point of `box` nearest the position `to` among the points it offers (ties as in `nearest_pair`)."""
    best = float("inf")
    chosen = offered[0]
    for a in offered:
        distance = _squared(point_xy(box, a), to)
        if distance < best - _TOLERANCE:
            best, chosen = distance, a
    return chosen


def line_points(
    source: Box, target: Box, source_point: AttachPoint | None = None, target_point: AttachPoint | None = None,
    source_offered: tuple[AttachPoint, ...] = ATTACH_POINTS, target_offered: tuple[AttachPoint, ...] = ATTACH_POINTS,
) -> tuple[AttachPoint, AttachPoint]:
    """The two points a line between the boxes uses.

    Args:
        source: The source box.
        target: The target box.
        source_point: The point a person chose on the source box, or `None` for automatic.
        target_point: The point a person chose on the target box, or `None` for automatic.
        source_offered: The points an automatic end of the source box may choose (the sides only for a marker).
        target_offered: The points an automatic end of the target box may choose.

    Returns:
        `(source point, target point)`: a chosen end as chosen, an automatic end the nearest to the other end.
    """
    if source_point is not None and target_point is not None:
        return source_point, target_point
    if source_point is not None:
        return source_point, nearest_point(target, point_xy(source, source_point), target_offered)
    if target_point is not None:
        return nearest_point(source, point_xy(target, target_point), source_offered), target_point
    return nearest_pair(source, target, source_offered, target_offered)
