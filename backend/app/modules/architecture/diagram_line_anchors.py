"""
Module: modules.architecture.diagram_line_anchors

Where every line of a diagram meets its boxes, so that no two lines draw over each other.

Responsibilities:
- Choose each line's attach point at both ends (`diagram_points` gives the points and the single-line rule)
  while considering every other line of the diagram.
- Spread lines that still share both ends sideways in parallel lanes, and give each loop (a line from a box
  back to itself) a slot so several loops on one box take different corners.

Design decisions:
- One rule, two implementations: the browser uses a TypeScript port (`components/graphLineAnchors.ts`); this
  is the server's copy for SVG and PNG. The shared cases in
  `frontend/src/components/graphLineAnchorCases.json` (written by `tests/test_architecture_line_anchors.py`)
  keep them equal, so a rule change is made in both. Only +, -, *, / and square roots are used so both agree
  to the last bit.
- A person's choice is never moved: a fixed end keeps its point, and a line with vertices is the person's
  drawing, its ends following the vertices (`diagram_points.route_points`) and never spread. Both still count
  as using their points, so an automatic line keeps clear of them in any order.
- Automatic lines are placed in the order given (callers pass creation order, so adding a line moves no
  earlier line except to keep clear of a fixed end), each choosing the nearest pair of free points (facing
  sides first). A point already used by another line is taken only when no free pair is left, and then the
  least used pair.
- Lanes are the last resort: two lines ending on the same two points are shifted sideways in parallel, 16 units
  apart, along the normal of the direction from the lower-ordered end, so opposite directions take opposite
  sides. A line with vertices is never shifted.
- A line whose box is missing from `boxes` is left out of the result.

Dependencies: `diagram_points` (the points), `enums` (the point names).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.modules.architecture.diagram_points import (
    ATTACH_POINTS,
    Box,
    Point,
    point_xy,
    route_points,
)
from app.modules.architecture.enums import AttachPoint

#: The distance between two parallel lanes, in canvas units.
LANE_GAP = 16.0

#: A distance must be smaller than the best so far by more than this to win, so equal distances keep the earlier pair.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class AnchorBox:
    """A box a line can meet: its top-left corner, size and the points an automatic end may choose."""

    x: float
    y: float
    width: float
    height: float
    offered: tuple[AttachPoint, ...] = ATTACH_POINTS

    @property
    def box(self) -> Box:
        """The box as `(x, y, width, height)`."""
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class AnchorLine:
    """A line to place: its id, the ids of its two boxes, the points a person fixed (`None` for automatic) and its vertices."""

    id: str
    source: str
    target: str
    source_point: AttachPoint | None = None
    target_point: AttachPoint | None = None
    vertices: tuple[Point, ...] = ()


@dataclass(frozen=True)
class LineAnchor:
    """Where one line meets its boxes: the point at each end and the sideways shift of its lane.

    For a loop `loop_slot` is its slot (0 is the top right corner) and the points and shift carry no meaning.
    """

    source: AttachPoint
    target: AttachPoint
    shift: Point = (0.0, 0.0)
    loop_slot: int | None = None


def _squared(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def assign_line_anchors(boxes: Mapping[str, AnchorBox], lines: Sequence[AnchorLine]) -> dict[str, LineAnchor]:
    """Place every line of a diagram.

    Args:
        boxes: Every box by id.
        lines: The lines in the order they were created (the order decides who keeps a point when the choice is a tie).

    Returns:
        The anchor of each line by id (a line whose box is missing is not in the result).
    """
    used: dict[tuple[str, AttachPoint], int] = {}
    placed: dict[str, tuple[AttachPoint, AttachPoint]] = {}
    result: dict[str, LineAnchor] = {}
    loops_on: dict[str, int] = {}
    pending: list[AnchorLine] = []

    def claim(box_id: str, point: AttachPoint) -> None:
        used[(box_id, point)] = used.get((box_id, point), 0) + 1

    for line in lines:
        a, b = boxes.get(line.source), boxes.get(line.target)
        if a is None or b is None:
            continue
        if line.source == line.target:
            slot = loops_on.get(line.source, 0)
            loops_on[line.source] = slot + 1
            result[line.id] = LineAnchor(AttachPoint.TOP, AttachPoint.TOP, (0.0, 0.0), slot)
        elif line.vertices:
            ends = route_points(
                a.box, b.box, line.source_point, line.target_point, list(line.vertices), a.offered, b.offered,
            )
            placed[line.id] = ends
            claim(line.source, ends[0])
            claim(line.target, ends[1])
        elif line.source_point is not None and line.target_point is not None:
            placed[line.id] = (line.source_point, line.target_point)
            claim(line.source, line.source_point)
            claim(line.target, line.target_point)
        else:
            if line.source_point is not None:
                claim(line.source, line.source_point)
            if line.target_point is not None:
                claim(line.target, line.target_point)
            pending.append(line)

    for line in pending:
        a, b = boxes[line.source], boxes[line.target]
        sources = (line.source_point,) if line.source_point is not None else a.offered
        targets = (line.target_point,) if line.target_point is not None else b.offered
        best: tuple[int, float] | None = None
        chosen = (sources[0], targets[0])
        for pa in sources:
            used_a = 0 if line.source_point is not None else used.get((line.source, pa), 0)
            xy_a = point_xy(a.box, pa)
            for pb in targets:
                total = used_a + (0 if line.target_point is not None else used.get((line.target, pb), 0))
                distance = _squared(xy_a, point_xy(b.box, pb))
                if best is None or total < best[0] or (total == best[0] and distance < best[1] - _TOLERANCE):
                    best, chosen = (total, distance), (pa, pb)
        placed[line.id] = chosen
        if line.source_point is None:
            claim(line.source, chosen[0])
        if line.target_point is None:
            claim(line.target, chosen[1])

    # Lines left on the same two points are spread into lanes, in the order they were given.
    groups: dict[tuple[tuple[str, str], tuple[str, str]], list[AnchorLine]] = {}
    ends_of: dict[str, tuple[tuple[str, AttachPoint], tuple[str, AttachPoint]]] = {}
    for line in lines:
        if line.id not in placed or line.vertices or line.source == line.target:
            continue
        pa, pb = placed[line.id]
        first, second = sorted([(line.source, pa), (line.target, pb)], key=lambda end: (end[0], end[1].value))
        ends_of[line.id] = (first, second)
        groups.setdefault(((first[0], first[1].value), (second[0], second[1].value)), []).append(line)
    for members in groups.values():
        first, second = ends_of[members[0].id]
        x1, y1 = point_xy(boxes[first[0]].box, first[1])
        x2, y2 = point_xy(boxes[second[0]].box, second[1])
        length = math.sqrt((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)) or 1.0
        for rank, line in enumerate(members):
            offset = (rank - (len(members) - 1) / 2) * LANE_GAP
            shift = (0.0, 0.0) if offset == 0 else (-(y2 - y1) / length * offset + 0.0, (x2 - x1) / length * offset + 0.0)
            result[line.id] = LineAnchor(placed[line.id][0], placed[line.id][1], shift)
    for line in lines:
        if line.id in placed and line.id not in result:
            result[line.id] = LineAnchor(placed[line.id][0], placed[line.id][1])
    return result
