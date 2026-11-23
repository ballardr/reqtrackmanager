"""
Module: modules.architecture.diagram_points

Where a diagram line meets its boxes: the eight attach points of a box and the rule that picks the two a line uses.

Responsibilities:
- Give the position of each of a box's eight attach points (the middle of each side and the four corners).
- Choose the points of one line: the stored choice for an end when a person made one, otherwise the nearest.

Design decisions:
- One rule, two implementations: the browser draws with a TypeScript port (`components/graphAttachPoints.ts`) so
  lines follow a box while it is dragged; this is the server's copy for the SVG. The shared cases in
  `frontend/src/components/graphAttachPointCases.json` (written by `tests/test_architecture_diagram_points.py`)
  keep them equal, so a rule change is made in both.
- Nearest means least squared distance, compared with a small tolerance and decided in the fixed order of
  `ATTACH_POINTS` (sides before corners), so a tie (two boxes side by side whose facing corners are as close as
  their facing sides) gives the sides. Squared distances avoid a square root, so both languages agree to the
  last bit.
- A marker offers fewer points: a dot or diamond (`SIDE_POINTS`) is met only at the middle of a side; the
  browser's box carries the same list as `points`.
- A line leaves a box outward: `outward_direction` gives the direction from the box's centre through an attach
  point (a side's normal; a corner takes the least-bent of the diagonal and its two side normals toward the
  line's next point). A Curved line starts along it (`diagram_line_path`); the port is `outwardDirection` in
  `graphAttachPoints.ts`.
- With one end fixed by a person, the other end is the point of its box nearest the fixed one; with neither
  fixed, the pair of points nearest each other.

Dependencies: `enums` (the point names).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

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


#: A direction as a unit vector `(dx, dy)`.
Direction = tuple[float, float]

#: Two dot products are told apart only when they differ by more than this, so a tie keeps the earlier candidate.
_DIRECTION_TOLERANCE = 1e-9

_SIDE_NORMALS: Mapping[AttachPoint, Direction] = {
    AttachPoint.TOP: (0, -1), AttachPoint.RIGHT: (1, 0), AttachPoint.BOTTOM: (0, 1), AttachPoint.LEFT: (-1, 0),
}
#: For a corner: the signs of its centre-to-corner diagonal, its vertical side normal and its horizontal side normal.
_CORNERS: Mapping[AttachPoint, tuple[int, int, Direction, Direction]] = {
    AttachPoint.TOP_RIGHT: (1, -1, (0, -1), (1, 0)),
    AttachPoint.BOTTOM_RIGHT: (1, 1, (0, 1), (1, 0)),
    AttachPoint.BOTTOM_LEFT: (-1, 1, (0, 1), (-1, 0)),
    AttachPoint.TOP_LEFT: (-1, -1, (0, -1), (-1, 0)),
}


def outward_direction(box: Box, point: AttachPoint, toward: Point | None) -> Direction:
    """The direction a line leaves `box` at `point`: the way from the box's centre through the point.

    A side point has one (its side's normal). A corner has three candidates (the centre-to-corner diagonal and the two side
    normals it lies on) and takes the one with the smallest angle to the straight line toward `toward`, so a corner bends no
    more than the boxes' positions need; a tie goes to the diagonal, then to the vertical side.

    Args:
        box: The box the line meets.
        point: The attach point on it.
        toward: Where the line is heading from the point (the other end, or the nearest vertex); `None` chooses the diagonal.

    Returns:
        A unit vector pointing out of the box.
    """
    side = _SIDE_NORMALS.get(point)
    if side is not None:
        return side
    sx, sy, vertical, horizontal = _CORNERS[point]
    dx, dy = sx * box[2] / 2, sy * box[3] / 2
    norm = math.sqrt(dx * dx + dy * dy)
    diagonal: Direction = vertical if norm == 0 else (dx / norm, dy / norm)
    if toward is None:
        return diagonal
    at = point_xy(box, point)
    lx, ly = toward[0] - at[0], toward[1] - at[1]
    length = math.sqrt(lx * lx + ly * ly)
    if length == 0:
        return diagonal
    ux, uy = lx / length, ly / length
    best, best_dot = diagonal, diagonal[0] * ux + diagonal[1] * uy
    for candidate in (vertical, horizontal):
        dot = candidate[0] * ux + candidate[1] * uy
        if dot > best_dot + _DIRECTION_TOLERANCE:
            best, best_dot = candidate, dot
    return best


def line_directions(
    source: Box, target: Box, source_point: AttachPoint, target_point: AttachPoint, waypoints: Sequence[Point],
) -> tuple[Direction, Direction]:
    """The directions a line leaves its two boxes in: each end's outward direction toward the line's next point (the nearest
    vertex, else the other end's attach point).

    Args:
        source: The source box.
        target: The target box.
        source_point: The attach point used on the source box.
        target_point: The attach point used on the target box.
        waypoints: The vertices in order from the source to the target.

    Returns:
        `(source direction, target direction)`.
    """
    source_toward = waypoints[0] if waypoints else point_xy(target, target_point)
    target_toward = waypoints[-1] if waypoints else point_xy(source, source_point)
    return outward_direction(source, source_point, source_toward), outward_direction(target, target_point, target_toward)


def route_points(
    source: Box, target: Box, source_point: AttachPoint | None, target_point: AttachPoint | None,
    waypoints: Sequence[Point],
    source_offered: tuple[AttachPoint, ...] = ATTACH_POINTS, target_offered: tuple[AttachPoint, ...] = ATTACH_POINTS,
) -> tuple[AttachPoint, AttachPoint]:
    """The two points a line uses when it has vertices: an open end is the point of its box nearest the vertex next to it
    (the first for the source, the last for the target), not the other box. With no vertices this is `line_points`.

    Args:
        source: The source box.
        target: The target box.
        source_point: The point a person chose on the source box, or `None` for automatic.
        target_point: The point a person chose on the target box, or `None` for automatic.
        waypoints: The vertices in order from the source to the target.
        source_offered: The points an automatic end of the source box may choose.
        target_offered: The points an automatic end of the target box may choose.

    Returns:
        `(source point, target point)`.
    """
    if not waypoints:
        return line_points(source, target, source_point, target_point, source_offered, target_offered)
    return (
        source_point if source_point is not None else nearest_point(source, waypoints[0], source_offered),
        target_point if target_point is not None else nearest_point(target, waypoints[-1], target_offered),
    )
