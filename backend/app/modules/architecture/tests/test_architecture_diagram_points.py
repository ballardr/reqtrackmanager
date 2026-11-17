"""Tests that keep the browser's copy of the attach-point rule in step with `diagram_points`.

The canvas draws each line between two of a box's eight attach points with a TypeScript port of the rule
(`frontend/src/components/graphAttachPoints.ts`); the server SVG uses `diagram_points`. Both run the same cases, whose
inputs and expected results live in `frontend/src/components/graphAttachPointCases.json`: this file produces the expected
results from the Python rule, and the port's story test checks that it returns the same. The test fails when the file is
out of date, so a change to the rule cannot reach one side only.

To refresh the file after a deliberate change to the rule, run this test with `UPDATE_POINT_CASES=1`, review the diff and
update the port.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.modules.architecture.diagram_points import (
    ATTACH_POINTS,
    SIDE_POINTS,
    Box,
    line_directions,
    line_points,
    nearest_pair,
    outward_direction,
    point_xy,
    route_points,
)
from app.modules.architecture.enums import AttachPoint

CASES_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "components" / "graphAttachPointCases.json"


def _case(
    name: str, source: Box, target: Box, source_point: AttachPoint | None = None, target_point: AttachPoint | None = None,
    source_sides: bool = False, target_sides: bool = False, via: list[tuple[float, float]] | None = None,
) -> dict:
    """One case: the inputs and the points the rule returns. A box that offers only the sides (a marker) says so, and a
    line with vertices (`via`) chooses its open ends toward the nearest vertex."""
    offered = (SIDE_POINTS if source_sides else ATTACH_POINTS, SIDE_POINTS if target_sides else ATTACH_POINTS)
    chosen = (
        route_points(source, target, source_point, target_point, via, *offered) if via
        else line_points(source, target, source_point, target_point, *offered)
    )
    result: dict = {
        "name": name, "source": list(source), "target": list(target),
        "source_point": source_point.value if source_point else None,
        "target_point": target_point.value if target_point else None,
    }
    if source_sides:
        result["source_offers"] = [p.value for p in SIDE_POINTS]
    if target_sides:
        result["target_offers"] = [p.value for p in SIDE_POINTS]
    if via:
        result["via"] = [list(p) for p in via]
    result["expected"] = [chosen[0].value, chosen[1].value]
    out_a, out_b = line_directions(source, target, chosen[0], chosen[1], via or [])
    result["directions"] = [[round(out_a[0], 9), round(out_a[1], 9)], [round(out_b[0], 9), round(out_b[1], 9)]]
    return result


def cases() -> list[dict]:
    """Every case with the rule's answer."""
    a: Box = (0, 0, 160, 80)
    return [
        _case("boxes side by side meet on the facing sides, not the facing corners", a, (300, 0, 160, 80)),
        _case("boxes side by side the other way round", (300, 0, 160, 80), a),
        _case("boxes stacked meet on the facing sides", a, (0, 200, 160, 80)),
        _case("a box up and to the right meets corner to corner", a, (300, -200, 160, 80)),
        _case("a box down and to the left meets corner to corner", a, (-300, 200, 160, 80)),
        _case("a box far to the right and slightly lower meets at the nearest corner of that box", a, (400, 30, 160, 80)),
        _case("a box beside but offset meets the nearest pair of points", a, (200, 120, 100, 60)),
        _case("a small box inside the reach of a large one", (0, 0, 400, 300), (500, 100, 60, 40)),
        _case("overlapping boxes still choose a pair", a, (80, 40, 160, 80)),
        _case("identical boxes choose the first pair in the fixed order", a, a),
        _case("fractional positions", (0.5, 0.25, 160.5, 80.75), (301.3, 10.1, 120.2, 60.6)),
        _case("a fixed source end makes the target the nearest point to it", a, (300, 0, 160, 80), AttachPoint.BOTTOM, None),
        _case("a fixed target end makes the source the nearest point to it", a, (300, 0, 160, 80), None, AttachPoint.TOP),
        _case("a fixed source corner pulls the target to the nearest corner", a, (300, 200, 160, 80), AttachPoint.TOP_LEFT, None),
        _case("both ends fixed are used as given", a, (300, 0, 160, 80), AttachPoint.LEFT, AttachPoint.RIGHT),
        _case("a fixed end on the far side of its box is kept", a, (300, 0, 160, 80), AttachPoint.LEFT, None),
        _case("a marker up and to the right is met on a side, not the corner", a, (300, -200, 24, 24), None, None, False, True),
        _case("a marker down and to the left of a marker meets side to side", (0, 0, 24, 24), (-300, 200, 24, 24), None, None, True, True),
        _case("a marker as the source offers only its sides", (0, 0, 36, 36), (200, 150, 160, 80), None, None, True, False),
        _case("a fixed end on a marker is used as given", (0, 0, 36, 36), a, AttachPoint.TOP_RIGHT, None, True, False),
        _case("a vertex above the boxes pulls both open ends to the top", a, (300, 0, 160, 80), None, None, False, False, [(230, -120)]),
        _case("a fixed end is kept and the other follows its vertex", a, (300, 0, 160, 80), AttachPoint.LEFT, None, False, False, [(230, 200)]),
        _case("two vertices: each end follows the vertex beside it", a, (300, 0, 160, 80), None, None, False, False, [(80, 200), (380, 200)]),
        _case("a marker end follows the vertex on a side", (0, 0, 36, 36), (300, 0, 160, 80), None, None, True, False, [(18, 200)]),
        # A corner leaves along the least-bent of the diagonal and its two side normals toward the line's next point.
        _case(
            "a top right corner with the other end straight above leaves upward",
            a, (60, -300, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.BOTTOM,
        ),
        _case(
            "a top right corner with the other end level to the right leaves rightward",
            a, (400, -20, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.LEFT,
        ),
        _case(
            "a top right corner with the other end up and to the right leaves along the diagonal",
            a, (400, -300, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.BOTTOM_LEFT,
        ),
        _case("a top right corner with the other end below leaves rightward", a, (400, 200, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.TOP),
        _case("a bottom right corner with the other end below leaves downward", a, (60, 300, 100, 80), AttachPoint.BOTTOM_RIGHT, AttachPoint.TOP),
        _case(
            "a bottom left corner with the other end to the left leaves leftward",
            a, (-400, 60, 100, 80), AttachPoint.BOTTOM_LEFT, AttachPoint.RIGHT,
        ),
        _case(
            "a bottom left corner with the other end down and to the left leaves along the diagonal",
            a, (-400, 300, 100, 80), AttachPoint.BOTTOM_LEFT, AttachPoint.TOP_RIGHT,
        ),
        _case(
            "a top left corner with the other end up and to the left leaves along the diagonal",
            a, (-400, -300, 100, 80), AttachPoint.TOP_LEFT, AttachPoint.BOTTOM_RIGHT,
        ),
        _case("a top left corner with the other end above leaves upward", a, (-20, -300, 100, 80), AttachPoint.TOP_LEFT, AttachPoint.BOTTOM),
        _case("a corner of a wide box has a flatter diagonal", (0, 0, 400, 40), (600, -400, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.BOTTOM_LEFT),
        _case(
            "a corner with the other end at the corner itself takes the diagonal",
            a, (160, 0, 100, 80), AttachPoint.TOP_RIGHT, AttachPoint.TOP_LEFT,
        ),
        _case(
            "a corner with a vertex leaves toward the vertex, not the other box",
            a, (400, -300, 100, 80), AttachPoint.TOP_RIGHT, None, False, False, [(160, 200)],
        ),
    ]


def test_the_shared_attach_point_cases_are_current():
    produced = json.dumps(cases(), indent=2) + "\n"
    if os.environ.get("UPDATE_POINT_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "graphAttachPointCases.json is out of date with diagram_points; run this test with UPDATE_POINT_CASES=1, "
        "review the diff and update the browser port to match."
    )


def test_the_cases_reach_every_point_and_every_kind_of_choice():
    used = {p for case in cases() for p in case["expected"]}
    assert used == {p.value for p in AttachPoint}
    assert any("source_offers" in case or "target_offers" in case for case in cases())
    assert any(case["source_point"] and not case["target_point"] for case in cases())
    assert any(case["target_point"] and not case["source_point"] for case in cases())
    assert any(case["source_point"] and case["target_point"] for case in cases())


def test_there_are_eight_distinct_points_at_the_sides_and_corners():
    box: Box = (10, 20, 100, 60)
    where = {p: point_xy(box, p) for p in ATTACH_POINTS}
    assert len(set(where.values())) == 8
    assert where[AttachPoint.TOP] == (60, 20) and where[AttachPoint.LEFT] == (10, 50)
    assert where[AttachPoint.BOTTOM_RIGHT] == (110, 80) and where[AttachPoint.TOP_LEFT] == (10, 20)


@pytest.mark.parametrize("gap", [0.5, 40, 140, 1000])
def test_boxes_side_by_side_always_meet_on_the_sides_whatever_the_gap(gap):
    """The facing corners are exactly as close as the facing sides; the sides win by the fixed order."""
    left: Box = (0, 0, 160, 80)
    right: Box = (160 + gap, 0, 160, 80)
    assert nearest_pair(left, right) == (AttachPoint.RIGHT, AttachPoint.LEFT)
    assert nearest_pair(right, left) == (AttachPoint.LEFT, AttachPoint.RIGHT)


def test_a_marker_never_meets_a_line_at_a_corner_unless_one_is_fixed():
    marker: Box = (0, 0, 24, 24)
    for target in [(300, -200, 160, 80), (-300, 200, 160, 80), (200, 150, 160, 80), (100, -100, 50, 50)]:
        a, _ = line_points(marker, target, None, None, SIDE_POINTS, ATTACH_POINTS)
        assert a in SIDE_POINTS


def test_a_side_point_leaves_along_its_sides_normal_and_the_corners_along_a_unit_vector():
    box: Box = (10, 20, 100, 60)
    assert outward_direction(box, AttachPoint.TOP, (500, 500)) == (0, -1)
    assert outward_direction(box, AttachPoint.RIGHT, None) == (1, 0)
    assert outward_direction(box, AttachPoint.BOTTOM, (0, 0)) == (0, 1)
    assert outward_direction(box, AttachPoint.LEFT, (0, 0)) == (-1, 0)
    for point in (AttachPoint.TOP_RIGHT, AttachPoint.BOTTOM_RIGHT, AttachPoint.BOTTOM_LEFT, AttachPoint.TOP_LEFT):
        dx, dy = outward_direction(box, point, None)
        assert abs(dx * dx + dy * dy - 1) < 1e-12


def test_a_corner_with_no_target_or_a_target_on_it_takes_the_diagonal():
    box: Box = (0, 0, 100, 100)
    expected = outward_direction(box, AttachPoint.TOP_RIGHT, None)
    assert expected[0] > 0 > expected[1] and abs(expected[0] + expected[1]) < 1e-12
    assert outward_direction(box, AttachPoint.TOP_RIGHT, (100, 0)) == expected


def test_a_corner_chooses_the_candidate_with_the_least_angle_to_the_line():
    box: Box = (0, 0, 100, 100)
    # Up and slightly right: the vertical normal is nearer than the diagonal.
    assert outward_direction(box, AttachPoint.TOP_RIGHT, (110, -300)) == (0, -1)
    # Right and slightly up: the horizontal normal.
    assert outward_direction(box, AttachPoint.TOP_RIGHT, (400, -10)) == (1, 0)
    # Exactly diagonal: the diagonal.
    dx, dy = outward_direction(box, AttachPoint.TOP_RIGHT, (300, -200))
    assert dx > 0 > dy and abs(dx + dy) < 1e-12
