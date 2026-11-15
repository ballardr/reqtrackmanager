"""
Module: diagram_line_hops

Where one drawn line crosses another and which of the two draws a small arc over the other (a hop), so a crossing reads as a
crossing and not as a junction. Pure functions with no database or HTTP, used by the server's drawings (block diagram and
state machine SVG); the browser draws with a TypeScript copy.

Responsibilities:
- Flatten each line (curves included) to segments, find where segments of different lines cross, and decide which crossings
  are drawn as a hop.
- Give the SVG path of each line that hops, with the arcs in place.

Design decisions:
- **One rule for every line.** Connections, transitions and leaders are all lines of one set; a line never hops over itself,
  and a loop on one box is not in the set.
- **The later line hops.** Of two lines that cross, the one whose id sorts later is drawn with the arc, so the same crossing
  looks the same on every screen and in every export.
- **No hop where it would not read.** None within `HOP_CLEARANCE` canvas units (along the line) of either line's end, between
  two lines that share an end point (they read as a branch), where the arc would not fit inside one segment or one curve span
  of the hopping line (it would cut a corner), or closer than one arc's width to the previous hop of that line.
- **Arcs are semicircles bulging one way**: up for a line that runs left to right and right for one that runs top to bottom
  (the sweep follows the chord's direction), so arcs on parallel lines match.
- **Deterministic and equal to the browser.** Only addition, subtraction, multiplication, division and square roots are used
  (each gives the same result in Python and JavaScript), and numbers are written by `diagram_line_path.format_point`.
  `graphLineHopCases.json` holds the cases both are tested against (`tests/test_architecture_line_hops.py`), so a change to
  the rule is made in both.
- **Not quadratic in the number of lines.** Segments are put in a grid of cells and only segments sharing a cell are compared;
  a segment that covers more than `MAX_CELLS` cells is compared with every other segment instead.

Dependencies: `diagram_line_path` (the curve spans and number format).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.architecture.diagram_line_path import Point, curve_spans, format_point

#: Radius of a hop in canvas units (the arc is a semicircle, so it is twice this wide).
HOP_RADIUS = 6.0
#: A hop is not drawn within this distance, along a line, of either line's end.
HOP_CLEARANCE = 12.0
#: Straight pieces a curve span is cut into.
CURVE_STEPS = 16
#: Width and height of a cell of the grid the segments are put in.
CELL = 64.0
#: Two end points this close (canvas units) are the same end.
SHARED_END = 1.0
#: A segment that covers more cells than this is compared with every other segment, not put in the grid.
MAX_CELLS = 256


@dataclass(frozen=True)
class HopLine:
    """One line of the drawing: its id (the order of hopping) and the geometry `diagram_line_path.line_path` draws.

    Attributes:
        id: The line's id; of two crossing lines the one whose id sorts later hops.
        start / end: The points on the source and target.
        points: The waypoints in order from the start to the end.
        smooth: True for a curve through the points.
    """

    id: str
    start: Point
    points: Sequence[Point]
    end: Point
    smooth: bool


@dataclass
class _Flat:
    """A line cut into segments: its points, the length along it at each, and the index range of each piece (a straight
    segment, or one curve span) a hop must fit inside."""

    poly: list[Point]
    cum: list[float]
    pieces: list[tuple[int, int]]


def _flatten(line: HopLine) -> _Flat:
    """The line as straight segments, with a curve cut into `CURVE_STEPS` pieces per span."""
    nodes = [line.start, *line.points, line.end]
    poly: list[Point] = [nodes[0]]
    pieces: list[tuple[int, int]] = []
    if not line.smooth or not line.points:
        for i in range(1, len(nodes)):
            pieces.append((i - 1, i))
            poly.append(nodes[i])
    else:
        for p1, c1, c2, p2 in curve_spans(line.start, line.points, line.end):
            first = len(poly) - 1
            for step in range(1, CURVE_STEPS + 1):
                t = step / CURVE_STEPS
                mt = 1 - t
                a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
                poly.append((a * p1[0] + b * c1[0] + c * c2[0] + d * p2[0], a * p1[1] + b * c1[1] + c * c2[1] + d * p2[1]))
            pieces.append((first, len(poly) - 1))
    cum = [0.0]
    for i in range(1, len(poly)):
        dx, dy = poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1]
        cum.append(cum[-1] + math.sqrt(dx * dx + dy * dy))
    return _Flat(poly, cum, pieces)


def _crossing(a: Point, b: Point, c: Point, d: Point) -> tuple[float, float] | None:
    """Where segment `a`-`b` crosses segment `c`-`d`: the fraction of each at the crossing, or `None` for a pair that is
    parallel or does not cross. A crossing at the very start of a segment counts for that segment, so one at a shared
    vertex is found once."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if denominator == 0:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if t < 0 or t >= 1 or u < 0 or u >= 1:
        return None
    return t, u


def _near(a: Point, b: Point) -> bool:
    dx, dy = a[0] - b[0], a[1] - b[1]
    return dx * dx + dy * dy <= SHARED_END * SHARED_END


def _point_at(flat: _Flat, s: float) -> Point:
    """The point at length `s` along the line."""
    cum, poly = flat.cum, flat.poly
    k = 0
    while k < len(poly) - 2 and cum[k + 1] < s:
        k += 1
    length = cum[k + 1] - cum[k]
    t = 0.0 if length == 0 else (s - cum[k]) / length
    a, b = poly[k], poly[k + 1]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _fits_in_a_piece(flat: _Flat, s: float) -> bool:
    """Whether the arc around length `s` lies inside one straight segment or one curve span."""
    for first, last in flat.pieces:
        if s <= flat.cum[last]:
            return s - HOP_RADIUS >= flat.cum[first] and s + HOP_RADIUS <= flat.cum[last]
    return False


def _hop_path(flat: _Flat, hops: list[float]) -> str:
    """The line's path with an arc at each length in `hops` (ascending)."""
    poly, cum = flat.poly, flat.cum
    out = [f"M {format_point(poly[0])}"]
    k = 1
    for s in hops:
        before, after = s - HOP_RADIUS, s + HOP_RADIUS
        while k < len(poly) and cum[k] <= before:
            out.append(f"L {format_point(poly[k])}")
            k += 1
        start, end = _point_at(flat, before), _point_at(flat, after)
        dx, dy = end[0] - start[0], end[1] - start[1]
        sweep = 1 if dx > 0 or (dx == 0 and dy > 0) else 0
        radius = format_point((HOP_RADIUS, HOP_RADIUS))
        out.append(f"L {format_point(start)} A {radius} 0 0 {sweep} {format_point(end)}")
        while k < len(poly) and cum[k] <= after:
            k += 1
    while k < len(poly):
        out.append(f"L {format_point(poly[k])}")
        k += 1
    return " ".join(out)


def line_hops(lines: Sequence[HopLine]) -> dict[str, str]:
    """The paths of the lines that hop over another line.

    Args:
        lines: Every line of the drawing (ids are unique).

    Returns:
        The SVG path (`M … L … A …`, the line flattened to segments) of each line that has at least one hop, by id. A line
        with no hop is absent and is drawn as `diagram_line_path.line_path` draws it.
    """
    flats = [_flatten(line) for line in lines]
    segments: list[tuple[int, int]] = []
    grid: dict[tuple[int, int], list[int]] = {}
    long_segments: list[int] = []
    for i, flat in enumerate(flats):
        if flat.cum[-1] == 0:
            continue
        for k in range(len(flat.poly) - 1):
            a, b = flat.poly[k], flat.poly[k + 1]
            index = len(segments)
            segments.append((i, k))
            x0, x1 = math.floor(min(a[0], b[0]) / CELL), math.floor(max(a[0], b[0]) / CELL)
            y0, y1 = math.floor(min(a[1], b[1]) / CELL), math.floor(max(a[1], b[1]) / CELL)
            if (x1 - x0 + 1) * (y1 - y0 + 1) > MAX_CELLS:
                long_segments.append(index)
                continue
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    grid.setdefault((cx, cy), []).append(index)

    pairs: set[tuple[int, int]] = set()
    for members in grid.values():
        for p in range(len(members)):
            for q in range(p + 1, len(members)):
                pairs.add((members[p], members[q]) if members[p] < members[q] else (members[q], members[p]))
    for g in long_segments:
        for other in range(len(segments)):
            if other != g:
                pairs.add((g, other) if g < other else (other, g))

    shares_end: dict[tuple[int, int], bool] = {}
    hops: dict[int, list[float]] = {}
    for g, h in sorted(pairs):
        (i, k), (j, m) = segments[g], segments[h]
        if i == j:
            continue
        fi, fj = flats[i], flats[j]
        found = _crossing(fi.poly[k], fi.poly[k + 1], fj.poly[m], fj.poly[m + 1])
        if found is None:
            continue
        key = (i, j) if i < j else (j, i)
        if key not in shares_end:
            ends_i = (lines[i].start, lines[i].end)
            ends_j = (lines[j].start, lines[j].end)
            shares_end[key] = any(_near(a, b) for a in ends_i for b in ends_j)
        if shares_end[key]:
            continue
        s_i = fi.cum[k] + found[0] * (fi.cum[k + 1] - fi.cum[k])
        s_j = fj.cum[m] + found[1] * (fj.cum[m + 1] - fj.cum[m])
        if not all(HOP_CLEARANCE <= s <= f.cum[-1] - HOP_CLEARANCE for s, f in ((s_i, fi), (s_j, fj))):
            continue
        hopper, s = (i, s_i) if lines[i].id > lines[j].id else (j, s_j)
        if _fits_in_a_piece(flats[hopper], s):
            hops.setdefault(hopper, []).append(s)

    paths: dict[str, str] = {}
    for i, found_at in hops.items():
        kept: list[float] = []
        for s in sorted(found_at):
            if not kept or s - kept[-1] >= 2 * HOP_RADIUS:
                kept.append(s)
        paths[lines[i].id] = _hop_path(flats[i], kept)
    return paths
