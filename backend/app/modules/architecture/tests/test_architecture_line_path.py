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
CASES: list[tuple[str, Point, list[Point], Point, str]] = [
    ("no waypoints is a straight line", (0, 0), [], (100, 0), "straight"),
    ("no waypoints stays straight when spline is asked", (0, 0), [], (100, 40), "spline"),
    ("one vertex, straight", (0, 0), [(50, 60)], (100, 0), "straight"),
    ("one vertex, spline", (0, 0), [(50, 60)], (100, 0), "spline"),
    ("one vertex, curved is the spline", (0, 0), [(50, 60)], (100, 0), "curved"),
    ("three vertices, straight", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), "straight"),
    ("three vertices, spline", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), "spline"),
    ("fractional and negative values", (-12.345, 0.5), [(3.14159, -7.777)], (99.999, 20.005), "spline"),
    ("the same point twice", (0, 0), [(40, 40), (40, 40)], (80, 0), "straight"),
    ("a line that returns to its start", (0, 0), [(30, 30)], (0, 0), "straight"),
    ("curved with no vertices bows left of a line running right", (0, 0), [], (100, 0), "curved"),
    ("curved with no vertices bows left of a line running down", (0, 0), [], (0, 100), "curved"),
    ("curved with no vertices on a short line", (10, 10), [], (30, 10), "curved"),
    ("curved with no vertices on a long line bows by the limit", (0, 0), [], (1000, 400), "curved"),
    ("curved with no length is a point", (5, 5), [], (5, 5), "curved"),
    ("fractional curved line", (-12.345, 0.5), [], (99.999, 20.005), "curved"),
]


def line_cases() -> list[dict]:
    """Every case with the path and the middle the Python rule gives."""
    out = []
    for name, start, points, end, shape in CASES:
        middle = line_middle(start, points, end, shape)
        out.append({
            "name": name, "start": list(start), "points": [list(p) for p in points], "end": list(end), "shape": shape,
            "path": line_path(start, points, end, shape), "middle": [round(middle[0], 6), round(middle[1], 6)],
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


def test_a_curved_line_with_no_vertices_is_one_arc_bowed_to_the_left_of_its_direction():
    from app.modules.architecture.diagram_line_path import bow_span

    start, c1, c2, end = bow_span((0, 0), (100, 0)) or ((0, 0),) * 4
    assert (start, end) == ((0, 0), (100, 0))
    # Left of a line running right (+x) is up the screen (-y); the bow is a quarter of the length.
    assert c1[1] == c2[1] == -25
    assert line_path((0, 0), [], (100, 0), "curved").count("C") == 1
    assert line_middle((0, 0), [], (100, 0), "curved") == (50, -18.75)


def test_a_curved_line_with_vertices_is_the_spline_through_them():
    points = [(50, 60), (80, 10)]
    assert line_path((0, 0), points, (100, 0), "curved") == line_path((0, 0), points, (100, 0), "spline")


def test_the_bow_is_capped_on_a_long_line():
    from app.modules.architecture.diagram_line_path import BOW_LIMIT, bow_span

    arc = bow_span((0, 0), (2000, 0))
    assert arc is not None and arc[1][1] == -BOW_LIMIT


def test_a_zero_length_curved_line_is_straight():
    assert line_path((5, 5), [], (5, 5), "curved") == "M 5 5 L 5 5"


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
