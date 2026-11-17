"""Tests for the waypoint line rule (`diagram_line_path`) and its shared cases file.

The canvas draws a routed line with a TypeScript copy (`frontend/src/components/graphLinePath.ts`) and the server's drawings use
`diagram_line_path`. Both are checked against `frontend/src/components/graphLinePathCases.json`, which this file produces from
the Python rule; the browser copy's story compares its own result with the file and this test fails when the file is out of
date. To refresh it after a deliberate change, run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update the
browser copy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.modules.architecture.diagram_line_path import line_middle, line_path

CASES_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "components" / "graphLinePathCases.json"

Point = tuple[float, float]
Directions = tuple[Point | None, Point | None]
RIGHT, LEFT, UP, DOWN = (1.0, 0.0), (-1.0, 0.0), (0.0, -1.0), (0.0, 1.0)
DIAGONAL = (0.7071067811865476, -0.7071067811865476)
NONE: Directions = (None, None)
CASES: list[tuple[str, Point, list[Point], Point, str, Directions]] = [
    ("no waypoints is a straight line", (0, 0), [], (100, 0), "straight", NONE),
    ("no waypoints stays straight when spline is asked", (0, 0), [], (100, 40), "spline", NONE),
    ("one vertex, straight", (0, 0), [(50, 60)], (100, 0), "straight", NONE),
    ("one vertex, spline", (0, 0), [(50, 60)], (100, 0), "spline", NONE),
    ("one vertex, curved without directions is the spline", (0, 0), [(50, 60)], (100, 0), "curved", NONE),
    ("three vertices, straight", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), "straight", NONE),
    ("three vertices, spline", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), "spline", NONE),
    ("fractional and negative values", (-12.345, 0.5), [(3.14159, -7.777)], (99.999, 20.005), "spline", NONE),
    ("the same point twice", (0, 0), [(40, 40), (40, 40)], (80, 0), "straight", NONE),
    ("a line that returns to its start", (0, 0), [(30, 30)], (0, 0), "straight", NONE),
    ("spline ignores the directions", (0, 0), [(50, 60)], (100, 0), "spline", (UP, UP)),
    ("curved with no vertices and no directions is straight", (0, 0), [], (100, 40), "curved", NONE),
    ("curved boxes facing each other in line give a straight line", (160, 40), [], (300, 40), "curved", (RIGHT, LEFT)),
    ("curved boxes facing each other, stored the other way round", (300, 40), [], (160, 40), "curved", (LEFT, RIGHT)),
    ("curved boxes offset sideways give a gentle S", (160, 40), [], (300, 140), "curved", (RIGHT, LEFT)),
    ("curved boxes offset sideways, stored the other way round", (300, 140), [], (160, 40), "curved", (LEFT, RIGHT)),
    ("curved boxes stacked, offset sideways", (80, 80), [], (140, 220), "curved", (DOWN, UP)),
    ("curved line from a box whose end points away from the other box", (0, 0), [], (-100, 60), "curved", (RIGHT, LEFT)),
    ("curved line between two top sides is a bump", (0, 100), [], (200, 100), "curved", (UP, UP)),
    ("curved line from a corner leaves along the diagonal", (100, 100), [], (300, 20), "curved", (DIAGONAL, LEFT)),
    ("curved with only the start direction arrives along the chord", (0, 0), [], (200, 100), "curved", (UP, None)),
    ("curved with only the end direction leaves along the chord", (0, 0), [], (200, 100), "curved", (None, UP)),
    ("curved with no vertices on a short line keeps the least handle", (10, 10), [], (30, 10), "curved", (RIGHT, LEFT)),
    ("curved with no vertices on a long line stops at the greatest handle", (0, 0), [], (1000, 400), "curved", (RIGHT, LEFT)),
    ("curved with no length is a point", (5, 5), [], (5, 5), "curved", (RIGHT, LEFT)),
    ("fractional curved line", (-12.345, 0.5), [], (99.999, 20.005), "curved", (RIGHT, DOWN)),
    ("curved through one vertex with outward ends", (0, 0), [(50, 60)], (100, 0), "curved", (UP, UP)),
    ("curved through vertices with only the start direction", (0, 0), [(50, 60), (80, 10)], (100, 0), "curved", (LEFT, None)),
    ("curved through three vertices with outward ends", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), "curved", (LEFT, RIGHT)),
]


def line_cases() -> list[dict]:
    """Every case with the path and the middle the Python rule gives."""
    out = []
    for name, start, points, end, shape, directions in CASES:
        middle = line_middle(start, points, end, shape, directions)
        out.append({
            "name": name, "start": list(start), "points": [list(p) for p in points], "end": list(end), "shape": shape,
            **({"start_direction": list(directions[0])} if directions[0] is not None else {}),
            **({"end_direction": list(directions[1])} if directions[1] is not None else {}),
            "path": line_path(start, points, end, shape, directions), "middle": [round(middle[0], 6), round(middle[1], 6)],
        })
    return out


def test_the_shared_line_path_cases_are_current():
    produced = json.dumps(line_cases(), indent=2) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "graphLinePathCases.json is out of date with diagram_line_path; run this test with UPDATE_SHAPE_CASES=1, review "
        "the diff and update graphLinePath.ts to match."
    )


def test_a_straight_line_through_one_vertex_has_two_segments():
    assert line_path((0, 0), [(50, 60)], (100, 0), "straight") == "M 0 0 L 50 60 L 100 0"


def test_a_spline_ends_exactly_on_its_points_and_has_one_curve_per_segment():
    path = line_path((0, 0), [(50, 60), (80, 10)], (100, 0), "spline")
    assert path.startswith("M 0 0 C ") and path.count("C") == 3 and path.endswith("100 0")


def test_the_middle_is_half_way_along_the_segments():
    assert line_middle((0, 0), [], (100, 0)) == (50, 0)
    assert line_middle((0, 0), [(100, 0)], (100, 100)) == (100, 0)
    assert line_middle((0, 0), [(10, 0)], (10, 10)) == (10, 0)


def test_a_zero_length_line_has_its_start_as_middle():
    assert line_middle((5, 5), [], (5, 5)) == (5, 5)


def _near_line(path_points: list[Point], a: Point, b: Point) -> float:
    """The greatest distance of the points from the straight line through `a` and `b`."""
    import math

    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return max(abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length for p in path_points)


def _curve_points(start: Point, end: Point, directions: Directions, samples: int = 20) -> list[Point]:
    from app.modules.architecture.diagram_line_path import outward_span

    span = outward_span(start, end, directions)
    assert span is not None
    p0, p1, p2, p3 = span
    out = []
    for i in range(samples + 1):
        t = i / samples
        m = 1 - t
        out.append((
            m**3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t**3 * p3[0],
            m**3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t**3 * p3[1],
        ))
    return out


def test_a_curved_line_between_boxes_that_face_each_other_in_line_is_straight():
    points = _curve_points((160, 40), (300, 40), (RIGHT, LEFT))
    assert _near_line(points, (160, 40), (300, 40)) < 1e-9
    assert line_middle((160, 40), [], (300, 40), "curved", (RIGHT, LEFT)) == (230, 40)


def test_a_curved_line_with_no_directions_or_no_length_is_straight():
    assert line_path((0, 0), [], (100, 40), "curved") == "M 0 0 L 100 40"
    assert line_path((5, 5), [], (5, 5), "curved", (RIGHT, LEFT)) == "M 5 5 L 5 5"


def test_a_curved_line_leaves_each_end_along_its_direction():
    from app.modules.architecture.diagram_line_path import outward_span

    start, c1, c2, end = outward_span((160, 40), (300, 140), (RIGHT, LEFT)) or ((0, 0),) * 4
    assert (start, end) == ((160, 40), (300, 140))
    # The control points lie along the directions, so the curve leaves both boxes square on, and the handle is 0.4 of the chord.
    assert c1[1] == 40 and c1[0] > 160 and c2[1] == 140 and c2[0] < 300


def test_the_same_curve_is_drawn_whichever_way_the_connection_is_stored():
    forward = _curve_points((160, 40), (300, 140), (RIGHT, LEFT))
    backward = _curve_points((300, 140), (160, 40), (LEFT, RIGHT))
    assert all(abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9 for a, b in zip(forward, reversed(backward), strict=True))


def test_the_handle_is_bounded_so_a_long_line_does_not_swing_wide_and_a_short_one_can_turn():
    from app.modules.architecture.diagram_line_path import HANDLE_MAX, HANDLE_MIN, outward_span

    long = outward_span((0, 0), (2000, 500), (RIGHT, LEFT))
    short = outward_span((0, 0), (20, 0), (RIGHT, LEFT))
    assert long is not None and long[1][0] == HANDLE_MAX
    assert short is not None and short[1][0] == HANDLE_MIN


def test_a_curved_line_through_vertices_leaves_outward_and_passes_through_them():
    path = line_path((0, 0), [(50, 60)], (100, 0), "curved", (UP, UP))
    spline = line_path((0, 0), [(50, 60)], (100, 0), "spline")
    assert path != spline and path.startswith("M 0 0 C 0 -") and path.count("C") == 2 and "50 60" in path and path.endswith("100 0")


def test_a_curved_line_with_a_free_end_arrives_along_the_chord():
    from app.modules.architecture.diagram_line_path import outward_span

    span = outward_span((0, 0), (200, 100), (UP, None))
    assert span is not None and span[1][0] == 0 and span[1][1] < 0
    # The arriving control point is behind the end along the chord (up and to the left of it).
    assert span[2][0] < 200 and span[2][1] < 100


def test_a_line_follows_its_diagram_unless_it_has_a_shape_of_its_own():
    from app.modules.architecture.diagram_line_path import effective_shape

    assert effective_shape(None, "curved") == "curved"
    assert effective_shape("spline", "curved") == "spline"
    assert effective_shape("nonsense", "curved") == "straight"
    assert effective_shape(None, "nonsense") == "straight"


def test_a_bundle_row_reads_its_shape_or_a_legacy_smooth_flag():
    from app.modules.architecture.diagram_line_path import bundle_default_shape, bundle_line_shape

    assert bundle_line_shape({"line_shape": "curved"}) == "curved"
    assert bundle_line_shape({"smooth": True}) == "spline"
    assert bundle_line_shape({"smooth": False}) is None
    assert bundle_line_shape({"line_shape": "nonsense"}) is None
    assert bundle_default_shape({"line_shape": "spline"}) == "spline"
    assert bundle_default_shape({}) == "straight"
