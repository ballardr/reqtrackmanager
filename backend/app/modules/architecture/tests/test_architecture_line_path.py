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
CASES: list[tuple[str, Point, list[Point], Point, bool]] = [
    ("no waypoints is a straight line", (0, 0), [], (100, 0), False),
    ("no waypoints stays straight when smooth is asked", (0, 0), [], (100, 40), True),
    ("one vertex, straight", (0, 0), [(50, 60)], (100, 0), False),
    ("one vertex, smooth", (0, 0), [(50, 60)], (100, 0), True),
    ("three vertices, straight", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), False),
    ("three vertices, smooth", (10, 10), [(60, 10), (60, 90), (140, 90)], (140, 20), True),
    ("fractional and negative values", (-12.345, 0.5), [(3.14159, -7.777)], (99.999, 20.005), True),
    ("the same point twice", (0, 0), [(40, 40), (40, 40)], (80, 0), False),
    ("a line that returns to its start", (0, 0), [(30, 30)], (0, 0), False),
]


def line_cases() -> list[dict]:
    """Every case with the path and the middle the Python rule gives."""
    out = []
    for name, start, points, end, smooth in CASES:
        middle = line_middle(start, points, end)
        out.append({
            "name": name, "start": list(start), "points": [list(p) for p in points], "end": list(end), "smooth": smooth,
            "path": line_path(start, points, end, smooth), "middle": [round(middle[0], 6), round(middle[1], 6)],
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
    assert line_path((0, 0), [(50, 60)], (100, 0), False) == "M 0 0 L 50 60 L 100 0"


def test_a_smooth_line_ends_exactly_on_its_points_and_has_one_curve_per_segment():
    path = line_path((0, 0), [(50, 60), (80, 10)], (100, 0), True)
    assert path.startswith("M 0 0 C ") and path.count("C") == 3 and path.endswith("100 0")


def test_the_middle_is_half_way_along_the_segments():
    assert line_middle((0, 0), [], (100, 0)) == (50, 0)
    assert line_middle((0, 0), [(100, 0)], (100, 100)) == (100, 0)
    assert line_middle((0, 0), [(10, 0)], (10, 10)) == (10, 0)


def test_a_zero_length_line_has_its_start_as_middle():
    assert line_middle((5, 5), [], (5, 5)) == (5, 5)
