"""Tests for the line anchor rule (`diagram_line_anchors`) and its shared cases file.

The canvas places lines with a TypeScript copy (`frontend/src/components/graphLineAnchors.ts`) and the server's drawings use
`diagram_line_anchors`. Both are checked against `frontend/src/components/graphLineAnchorCases.json`, which this file produces
from the Python rule; the browser copy's story compares its own result with the file and this test fails when the file is
out of date. To refresh it after a deliberate change, run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update
the browser copy.

The rule's own promises (no two lines on the same path, a person's choice kept, an earlier line unmoved when one is added,
the same answer in either order of two boxes) are asserted here directly, not only through the cases.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app.modules.architecture.diagram_line_anchors import AnchorBox, AnchorLine, LineAnchor, assign_line_anchors
from app.modules.architecture.diagram_points import ATTACH_POINTS, SIDE_POINTS, point_xy
from app.modules.architecture.enums import AttachPoint

CASES_FILE = Path(__file__).resolve().parents[5] / "frontend" / "src" / "components" / "graphLineAnchorCases.json"

P = AttachPoint


def box(x: float, y: float, w: float = 160, h: float = 80, sides: bool = False) -> AnchorBox:
    """A box; one that offers only the middle of each side (a marker) says so."""
    return AnchorBox(x, y, w, h, SIDE_POINTS if sides else ATTACH_POINTS)


def line(
    id_: str, source: str, target: str, source_point: AttachPoint | None = None, target_point: AttachPoint | None = None,
    via: tuple[tuple[float, float], ...] = (),
) -> AnchorLine:
    return AnchorLine(id_, source, target, source_point, target_point, via)


A, B, C = box(0, 0), box(300, 0), box(300, 200)

# The User's case: a block, a choice to its right, an outcome further on, and a loop back from the choice to the block.
CHOICE = box(300, 20, 40, 40, sides=True)
OUTCOME = box(500, 0)

CASES: list[tuple[str, dict[str, AnchorBox], list[AnchorLine]]] = [
    ("one line takes the facing sides", {"a": A, "b": B}, [line("l1", "a", "b")]),
    ("a line each way between two boxes takes two paths", {"a": A, "b": B}, [line("l1", "a", "b"), line("l2", "b", "a")]),
    (
        "three lines between one pair take three paths",
        {"a": A, "b": B}, [line("l1", "a", "b"), line("l2", "b", "a"), line("l3", "a", "b")],
    ),
    (
        "a transition into a choice and the loop back out of it",
        {"block": A, "choice": CHOICE, "outcome": OUTCOME},
        [line("in", "block", "choice"), line("out", "choice", "outcome"), line("back", "choice", "block")],
    ),
    (
        "a box with more lines than points shares points and then spreads into lanes",
        {"a": box(0, 0, 40, 40, sides=True), "b": box(300, 0, 40, 40, sides=True)},
        [line(f"l{n}", "a" if n % 2 else "b", "b" if n % 2 else "a") for n in range(1, 7)],
    ),
    (
        "a point a person fixed is never moved and an earlier automatic line gives way",
        {"a": A, "b": B}, [line("auto", "a", "b"), line("fixed", "a", "b", P.RIGHT, P.LEFT)],
    ),
    (
        "one fixed end leaves the other to the nearest free point",
        {"a": A, "b": B}, [line("l1", "a", "b", P.BOTTOM, None), line("l2", "b", "a", None, P.TOP)],
    ),
    (
        "two lines fixed to the same two points are laned",
        {"a": A, "b": B}, [line("l1", "a", "b", P.RIGHT, P.LEFT), line("l2", "a", "b", P.RIGHT, P.LEFT)],
    ),
    (
        "a line with vertices keeps its own ends and is never laned",
        {"a": A, "b": B}, [line("bent", "a", "b", via=((150, -80),)), line("auto", "a", "b")],
    ),
    (
        "a self loop beside a pair takes the first corner and the pair is unchanged",
        {"a": A, "b": B}, [line("loop", "a", "a"), line("l1", "a", "b")],
    ),
    (
        "several loops on one box take different slots",
        {"a": A, "b": B}, [line("x", "a", "a"), line("y", "a", "a"), line("z", "b", "b"), line("w", "a", "a")],
    ),
    (
        "boxes up and to the right meet corner to corner and a second line takes the next corners",
        {"a": A, "b": box(300, -200)}, [line("l1", "a", "b"), line("l2", "a", "b")],
    ),
    (
        "a hub spreads its lines over its free points",
        {"hub": box(200, 200), "n": box(200, 0), "e": box(500, 200), "s": box(200, 400), "w": box(-100, 200)},
        [line("ln", "hub", "n"), line("le", "hub", "e"), line("ls", "hub", "s"), line("lw", "hub", "w"), line("ln2", "hub", "n")],
    ),
    ("a line whose box is missing is left out", {"a": A}, [line("l1", "a", "gone"), line("l2", "a", "a")]),
    ("identical boxes choose the first pair in the fixed order", {"a": A, "b": A}, [line("l1", "a", "b")]),
    (
        "the order of the lines decides a tie",
        {"a": A, "b": B}, [line("second", "b", "a"), line("first", "a", "b")],
    ),
]


def _anchors(boxes: dict[str, AnchorBox], lines: list[AnchorLine]) -> dict[str, LineAnchor]:
    return assign_line_anchors(boxes, lines)


def cases() -> list[dict]:
    """Every case with the rule's answer."""
    out = []
    for name, boxes, lines in CASES:
        result = _anchors(boxes, lines)
        out.append({
            "name": name,
            "boxes": {
                id_: {"box": [b.x, b.y, b.width, b.height], **({"offers": [p.value for p in b.offered]} if b.offered != ATTACH_POINTS else {})}
                for id_, b in boxes.items()
            },
            "lines": [
                {
                    "id": x.id, "source": x.source, "target": x.target,
                    "source_point": x.source_point.value if x.source_point else None,
                    "target_point": x.target_point.value if x.target_point else None,
                    "via": [list(p) for p in x.vertices],
                }
                for x in lines
            ],
            "expected": {
                id_: (
                    {"loop_slot": a.loop_slot} if a.loop_slot is not None
                    else {"source": a.source.value, "target": a.target.value, "shift": list(a.shift)}
                )
                for id_, a in result.items()
            },
        })
    return out


def test_the_shared_cases_are_current():
    produced = json.dumps(cases(), indent=2) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "graphLineAnchorCases.json is out of date with diagram_line_anchors; run this test with UPDATE_SHAPE_CASES=1, "
        "review the diff and update the browser copy to match."
    )


def _segment(boxes: dict[str, AnchorBox], x: AnchorLine, a: LineAnchor) -> tuple[tuple[float, float], tuple[float, float]]:
    (x1, y1), (x2, y2) = point_xy(boxes[x.source].box, a.source), point_xy(boxes[x.target].box, a.target)
    return (x1 + a.shift[0], y1 + a.shift[1]), (x2 + a.shift[0], y2 + a.shift[1])


@pytest.mark.parametrize(("name", "boxes", "lines"), CASES, ids=[c[0] for c in CASES])
def test_no_two_straight_lines_are_drawn_on_the_same_path(name, boxes, lines):
    if name.startswith("a box with more lines than points"):
        pytest.skip("this case is about running out of points: lanes keep them apart, asserted below")
    result = _anchors(boxes, lines)
    seen: dict[frozenset, str] = {}
    for x in lines:
        a = result.get(x.id)
        if a is None or a.loop_slot is not None or x.vertices:
            continue
        ends = frozenset(_segment(boxes, x, a))
        assert ends not in seen, f"{x.id} is drawn over {seen[ends]}"
        seen[ends] = x.id


def test_lines_that_run_out_of_points_are_kept_apart_by_lanes():
    boxes = {"a": box(0, 0, 40, 40, sides=True), "b": box(300, 0, 40, 40, sides=True)}
    lines = [line(f"l{n}", "a" if n % 2 else "b", "b" if n % 2 else "a") for n in range(1, 13)]
    result = _anchors(boxes, lines)
    segments = {frozenset(_segment(boxes, x, result[x.id])) for x in lines}
    assert len(segments) == len(lines)


def test_a_person_s_choice_is_kept_whatever_the_order():
    boxes = {"a": A, "b": B}
    fixed, auto = line("fixed", "a", "b", P.RIGHT, P.LEFT), line("auto", "a", "b")
    for order in ([auto, fixed], [fixed, auto]):
        result = _anchors(boxes, order)
        assert (result["fixed"].source, result["fixed"].target) == (P.RIGHT, P.LEFT)
        assert (result["auto"].source, result["auto"].target) != (P.RIGHT, P.LEFT)


def test_adding_a_line_moves_no_earlier_automatic_line():
    boxes = {"hub": box(200, 200), "n": box(200, 0), "e": box(500, 200), "s": box(200, 400), "w": box(-100, 200)}
    lines = [
        line("ln", "hub", "n"), line("le", "hub", "e"), line("ls", "hub", "s"), line("lw", "hub", "w"),
        line("x", "n", "hub"), line("y", "hub", "e"),
    ]
    for count in range(1, len(lines)):
        before, after = _anchors(boxes, lines[:count]), _anchors(boxes, lines[: count + 1])
        for x in lines[:count]:
            assert (before[x.id].source, before[x.id].target) == (after[x.id].source, after[x.id].target), x.id


def test_the_facing_sides_are_used_when_nothing_else_is_on_the_boxes():
    result = _anchors({"a": A, "b": B}, [line("l1", "a", "b")])
    assert (result["l1"].source, result["l1"].target, result["l1"].shift) == (P.RIGHT, P.LEFT, (0.0, 0.0))


def test_the_lane_of_a_line_each_way_is_on_its_own_side():
    result = _anchors({"a": box(0, 0, 40, 40, sides=True), "b": box(300, 0, 40, 40, sides=True)}, [
        line("l1", "a", "b", P.RIGHT, P.LEFT), line("l2", "b", "a", P.LEFT, P.RIGHT),
    ])
    assert result["l1"].shift == (0.0, -8.0) and result["l2"].shift == (0.0, 8.0)


def test_a_loop_is_given_the_next_slot_of_its_box():
    result = _anchors({"a": A, "b": B}, [line("x", "a", "a"), line("y", "b", "b"), line("z", "a", "a")])
    assert [result[i].loop_slot for i in ("x", "y", "z")] == [0, 0, 1]


def test_a_large_diagram_is_placed_in_a_fraction_of_a_second():
    boxes = {f"b{n}": box((n % 30) * 220, (n // 30) * 140) for n in range(900)}
    lines = [line(f"l{n}", f"b{n % 900}", f"b{(n * 7 + 1) % 900}") for n in range(1500)]
    started = time.perf_counter()
    result = _anchors(boxes, lines)
    assert time.perf_counter() - started < 2.0
    assert len(result) == len([x for x in lines if x.source in boxes and x.target in boxes])
