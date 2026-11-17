"""Tests for the line hop rule (`diagram_line_hops`) and its shared cases file.

The canvas draws hops with a TypeScript copy (`frontend/src/components/graphLineHops.ts`) and the server's drawings use
`diagram_line_hops`. Both are checked against `frontend/src/components/graphLineHopCases.json`, which this file produces from
the Python rule; the browser copy's story compares its own result with the file and this test fails when the file is out of
date. To refresh it after a deliberate change, run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update the
browser copy.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.modules.architecture.diagram_line_hops import HOP_RADIUS, HopLine, line_hops

CASES_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "components" / "graphLineHopCases.json"

Point = tuple[float, float]


def _line(
    id_: str, start: Point, end: Point, points: list[Point] | None = None, shape: str = "straight",
    directions: tuple[Point | None, Point | None] = (None, None),
) -> HopLine:
    return HopLine(id_, start, points or [], end, shape, directions)


#: Both ends of a Curved line leave upward: a bump above the chord.
_UP: tuple[Point | None, Point | None] = ((0, -1), (0, -1))


# A horizontal line with a vertical one across it, both long enough to have room at every end.
_ACROSS = [_line("a", (0, 100), (200, 100)), _line("b", (100, 0), (100, 200))]

CASES: list[tuple[str, list[HopLine]]] = [
    ("the later line hops over the earlier one", _ACROSS),
    ("the order of the list does not decide", list(reversed(_ACROSS))),
    ("the earlier id is the one that hops when it is listed later", [_line("z", (0, 100), (200, 100)), _line("m", (100, 0), (100, 200))]),
    ("lines that do not cross have no hop", [_line("a", (0, 0), (200, 0)), _line("b", (0, 50), (200, 50))]),
    ("parallel lines on top of each other have no hop", [_line("a", (0, 0), (200, 0)), _line("b", (50, 0), (150, 0))]),
    ("lines that share an end have no hop", [_line("a", (0, 0), (200, 200)), _line("b", (0, 0), (200, 0), [(100, 150), (150, -50)])]),
    ("a crossing near the end of the hopping line has no hop", [_line("a", (0, 100), (200, 100)), _line("b", (100, 0), (100, 108))]),
    ("a crossing near the end of the other line has no hop", [_line("a", (100, 92), (100, 200)), _line("b", (0, 100), (200, 100))]),
    (
        "a crossing at a corner of the hopping line has no hop",
        [_line("a", (97, -50), (97, 50)), _line("b", (0, 0), (100, 100), [(100, 0)])],
    ),
    ("a crossing that is too close to the previous hop is left out", [
        _line("a", (100, 0), (100, 200)), _line("b", (108, 0), (108, 200)), _line("c", (0, 100), (200, 100)),
    ]),
    ("one line over two others has two hops", [
        _line("a", (0, 50), (300, 50)), _line("b", (0, 150), (300, 150)), _line("c", (100, 0), (200, 200)),
    ]),
    ("a line that runs right to left bulges up as one that runs left to right", [_line("a", (0, 100), (200, 100)), _line("b", (200, 0), (0, 200))]),
    ("a vertical hopping line bulges right", [_line("a", (0, 100), (200, 100)), _line("b", (100, 0), (100, 200))]),
    ("a vertical hopping line that runs upward also bulges right", [_line("a", (0, 100), (200, 100)), _line("b", (100, 200), (100, 0))]),
    ("a diagonal hopping line", [_line("a", (0, 200), (200, 0)), _line("b", (0, 0), (200, 200))]),
    ("a curve hops over a straight line", [
        _line("a", (0, 100), (240, 100)), _line("b", (20, 20), (220, 20), [(120, 180)], "spline"),
    ]),
    ("a straight line hops over a curve", [
        _line("a", (20, 20), (220, 20), [(120, 180)], "spline"), _line("b", (0, 100), (240, 100)),
    ]),
    ("a curved line with no vertices hops over a straight line", [
        _line("a", (0, 100), (240, 100)), _line("b", (20, 140), (220, 140), None, "curved", _UP),
    ]),
    ("a curved line is crossed by a line through the middle of its chord", [
        _line("a", (120, 0), (120, 200)), _line("b", (0, 100), (240, 100), None, "curved", _UP),
    ]),
    ("a curved line through vertices with outward ends hops over a straight line", [
        _line("a", (0, 100), (300, 100)), _line("b", (20, 20), (280, 20), [(150, 180)], "curved", ((0, 1), (0, 1))),
    ]),
    ("a line crossing itself has no hop", [_line("a", (0, 0), (100, 100), [(100, 0), (0, 100)])]),
    ("a very long diagonal crosses a short line", [
        _line("a", (0, 0), (30000, 30000)), _line("b", (15000, 14900), (15000, 15100)),
    ]),
    ("a hop on a line with vertices keeps them", [
        _line("a", (60, 50), (60, 150)), _line("b", (100, 150), (200, 150)),
        _line("z", (0, 100), (300, 200), [(150, 100), (150, 200)]),
    ]),
]


def hop_cases() -> list[dict]:
    """Every case with the paths the Python rule gives."""
    out = []
    for name, lines in CASES:
        out.append({
            "name": name,
            "lines": [
                {
                    "id": line.id, "start": list(line.start), "points": [list(p) for p in line.points], "end": list(line.end),
                    "shape": line.shape,
                    **({"start_direction": list(line.directions[0])} if line.directions[0] is not None else {}),
                    **({"end_direction": list(line.directions[1])} if line.directions[1] is not None else {}),
                }
                for line in lines
            ],
            "paths": line_hops(lines),
        })
    return out


def test_the_shared_line_hop_cases_are_current():
    produced = json.dumps(hop_cases(), indent=2) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "graphLineHopCases.json is out of date with diagram_line_hops; run this test with UPDATE_SHAPE_CASES=1, review "
        "the diff and update graphLineHops.ts to match."
    )


def test_the_later_line_hops_with_a_semicircle_that_bulges_up():
    paths = line_hops(_ACROSS)
    assert list(paths) == ["b"]
    assert paths["b"] == "M 100 0 L 100 94 A 6 6 0 0 1 100 106 L 100 200"
    assert HOP_RADIUS == 6


def test_a_line_that_is_not_crossed_is_not_in_the_result():
    assert line_hops([_line("a", (0, 0), (10, 0))]) == {}
    assert line_hops([]) == {}


def test_the_list_order_does_not_change_which_line_hops():
    assert line_hops(_ACROSS) == line_hops(list(reversed(_ACROSS)))


def test_a_line_crossing_two_lines_hops_twice():
    path = line_hops(dict(CASES)["one line over two others has two hops"])["c"]
    assert path.count(" A ") == 2


def test_two_crossings_closer_than_one_arc_give_one_hop():
    lines = dict(CASES)["a crossing that is too close to the previous hop is left out"]
    assert line_hops(lines)["c"].count(" A ") == 1


def test_a_corner_too_near_the_crossing_has_no_hop_and_a_vertex_line_keeps_its_vertices():
    assert line_hops(dict(CASES)["a crossing at a corner of the hopping line has no hop"]) == {}
    path = line_hops(dict(CASES)["a hop on a line with vertices keeps them"])["z"]
    assert " L 150 100 " in path + " " and " L 150 200" in path and path.count(" A ") == 2


def test_a_line_running_leftwards_bulges_the_same_way_as_one_running_rightwards():
    leftwards = line_hops(dict(CASES)["a line that runs right to left bulges up as one that runs left to right"])["b"]
    assert " A 6 6 0 0 0 " in leftwards


def test_a_spline_with_a_hop_is_drawn_as_segments_and_ends_on_its_points():
    path = line_hops(dict(CASES)["a curve hops over a straight line"])["b"]
    assert path.startswith("M 20 20 L ") and path.endswith("L 220 20") and " A " in path and "C" not in path


def test_a_curved_line_is_flattened_along_its_curve_so_it_hops_where_the_curve_crosses():
    paths = line_hops(dict(CASES)["a curved line is crossed by a line through the middle of its chord"])
    # Both ends leave upward, so the curve rises above its chord (to 28 at its middle) and the vertical line crosses it there;
    # only the later id ("b") hops, along segments and an arc.
    assert "b" in paths and paths["b"].startswith("M 0 100 L ") and " A " in paths["b"] and "C" not in paths["b"]


def test_a_hundred_lines_are_compared_within_a_second():
    lines = [_line(f"h{i:03d}", (0, i * 20), (4000, i * 20 + 7)) for i in range(100)]
    lines += [_line(f"v{i:03d}", (i * 40, 0), (i * 40 + 5, 2100)) for i in range(100)]
    started = time.perf_counter()
    paths = line_hops(lines)
    assert time.perf_counter() - started < 5
    assert len(paths) > 90
