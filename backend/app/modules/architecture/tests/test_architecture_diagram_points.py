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

from app.modules.architecture.diagram_points import ATTACH_POINTS, Box, line_points, nearest_pair, point_xy
from app.modules.architecture.enums import AttachPoint

CASES_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "components" / "graphAttachPointCases.json"


def _case(
    name: str, source: Box, target: Box, source_point: AttachPoint | None = None, target_point: AttachPoint | None = None,
) -> dict:
    """One case: the inputs and the points the rule returns."""
    chosen = line_points(source, target, source_point, target_point)
    return {
        "name": name, "source": list(source), "target": list(target),
        "source_point": source_point.value if source_point else None,
        "target_point": target_point.value if target_point else None,
        "expected": [chosen[0].value, chosen[1].value],
    }


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
