"""Tests that keep the browser's copies of the state shape table and the self-loop rule in step with `state_shapes`.

The canvas draws the markers, a state's sizes and a self loop with TypeScript copies
(`frontend/src/modules/architecture/stateShapes.ts`, `frontend/src/components/graphSelfLoop.ts`); the server's drawing uses
`state_shapes`. Both are checked against shared files that this file produces from the Python rule:
`frontend/src/modules/architecture/stateShapeCases.json` (the table) and `frontend/src/components/graphSelfLoopCases.json`
(the loop of several boxes). Each copy's story compares its own result with the file, and these tests fail when a file is out
of date, so a change cannot reach one side only.

To refresh the files after a deliberate change, run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update the
browser copies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.modules.architecture.enums import AttachPoint, StateKind
from app.modules.architecture.state_shapes import (
    COMPOSITE_HEADER_HEIGHT,
    COMPOSITE_PADDING,
    SELF_LOOP_REACH,
    STATE_MARKERS,
    self_loop,
    self_loop_path,
    shape_table,
)

FRONTEND = Path(__file__).resolve().parents[5] / "frontend" / "src"
TABLE_FILE = FRONTEND / "modules" / "architecture" / "stateShapeCases.json"
LOOP_FILE = FRONTEND / "components" / "graphSelfLoopCases.json"

BOXES = [
    ("a default state", (0, 0, 160, 64)),
    ("a state away from the origin", (300, 120, 160, 64)),
    ("a large composite frame", (20, 40, 480, 320)),
    ("a small box", (-50, -30, 40, 24)),
    ("fractional position and size", (10.5, 20.25, 120.5, 60.75)),
]


#: The sides a marker offers in each case: all four, none covered by a label, and with the right or the top covered by one.
MARKER_BOXES = [
    ("a choice offering every side", (0, 0, 96, 96), None, ["top", "right", "bottom", "left"]),
    ("a dot with its label on the right", (100, 40, 20, 20), None, ["top", "bottom", "left"]),
    ("a diamond with its label above", (10, 10, 36, 36), None, ["right", "bottom", "left"]),
]


def loop_cases() -> list[dict]:
    """Every loop case with the curve, the label position and the path the Python rule gives: each box in the first slot, the
    first box in every slot of two rounds, and a marker's loop (between the middles of its offered sides) in each case in every slot
    of two rounds."""
    cases = []
    rows = [
        *[(name, box, 0, None) for name, box in BOXES],
        *[(f"{BOXES[0][0]}, slot {n}", BOXES[0][1], n, None) for n in range(1, 9)],
        *[(f"{name}, slot {n}", box, n, [AttachPoint(s) for s in sides]) for name, box, _x, sides in MARKER_BOXES for n in range(0, 9)],
    ]
    for name, box, slot, sides in rows:
        loop = self_loop(box, slot, sides)
        cases.append({
            "name": name, "box": list(box), "slot": slot,
            **({"sides": [s.value for s in sides]} if sides is not None else {}),
            "reach": SELF_LOOP_REACH,
            "loop": {key: list(loop[key]) for key in ("start", "control1", "control2", "end", "label")},
            "align": loop["align"],
            "path": self_loop_path(box, slot, sides),
        })
    return cases


def _check_file(path: Path, produced: str) -> None:
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        path.write_text(produced, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == produced, (
        f"{path.name} is out of date with state_shapes; run this test with UPDATE_SHAPE_CASES=1, review the diff "
        "and update the browser copy to match."
    )


def test_the_shared_shape_table_is_current():
    _check_file(TABLE_FILE, json.dumps(shape_table(), indent=2) + "\n")


def test_the_shared_self_loop_cases_are_current():
    _check_file(LOOP_FILE, json.dumps(loop_cases(), indent=2) + "\n")


def test_every_marker_kind_has_a_square_frame_and_a_drawing_that_fits_it():
    assert set(STATE_MARKERS) == {StateKind.INITIAL, StateKind.FINAL, StateKind.CHOICE}
    for size, svg in STATE_MARKERS.values():
        assert f'viewBox="0 0 {size} {size}"' in svg and svg.startswith("<svg") and svg.endswith("</svg>")
        assert "<script" not in svg and "href" not in svg


def test_a_loop_leaves_the_top_side_and_returns_to_the_right_side_with_its_label_anchor_above_the_box():
    x, y, w, h = 10.0, 20.0, 160.0, 64.0
    loop = self_loop((x, y, w, h))
    assert loop["start"] == (x + 0.75 * w, y)
    assert loop["end"] == (x + w, y + 0.25 * h)
    # The label's bottom-left corner sits at this anchor, so the text rises above the box and clear of it.
    label_x, label_y = loop["label"]
    assert label_y < y and label_x > x + w / 2


def test_loops_on_one_box_take_four_different_corners_and_then_reach_further_out():
    box = (0.0, 0.0, 160.0, 64.0)
    paths = [self_loop_path(box, slot) for slot in range(12)]
    assert len(set(paths)) == 12
    first, second, third, fourth = (self_loop(box, slot) for slot in range(4))
    assert second["start"][1] == 64 and second["end"][0] == 160  # the bottom right
    assert third["start"][1] == 64 and third["end"][0] == 0 and third["align"] == "end"  # the bottom left
    assert fourth["start"][1] == 0 and fourth["end"][0] == 0  # the top left
    assert first["align"] == "start"
    assert self_loop(box, 4)["control2"][0] > first["control2"][0]


def test_a_markers_loop_runs_between_the_middles_of_its_sides_not_the_corners_of_its_frame():
    """The reported defect: a loop on a diamond floated away because it joined points of its bounding box, where the diamond has no
    outline."""
    x, y, w, h = 100.0, 50.0, 96.0, 96.0
    every = [AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT]
    first = self_loop((x, y, w, h), 0, every)
    assert first["start"] == (x + w / 2, y) and first["end"] == (x + w, y + h / 2) and first["align"] == "start"
    # Both ends are vertices of the diamond: the top and the right.
    second, third, fourth = (self_loop((x, y, w, h), slot, every) for slot in (1, 2, 3))
    assert second["start"] == (x + w / 2, y + h) and second["end"] == (x + w, y + h / 2)
    assert third["start"] == (x + w / 2, y + h) and third["end"] == (x, y + h / 2) and third["align"] == "end"
    assert fourth["start"] == (x + w / 2, y) and fourth["end"] == (x, y + h / 2)


def test_a_markers_loop_keeps_off_the_side_its_label_is_on_and_a_box_without_sides_is_unchanged():
    box = (0.0, 0.0, 36.0, 36.0)
    no_right = [AttachPoint.TOP, AttachPoint.BOTTOM, AttachPoint.LEFT]  # a label on the right
    assert self_loop(box, 0, no_right)["end"][0] == 0  # the first usable corner is the top left
    no_top = [AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT]  # a label above
    assert self_loop(box, 0, no_top)["start"][1] == 36
    assert self_loop(box, 0, []) == self_loop(box, 0, [AttachPoint.TOP, AttachPoint.RIGHT, AttachPoint.BOTTOM, AttachPoint.LEFT])
    assert self_loop((0.0, 0.0, 160.0, 64.0), 0, None)["start"] == (120.0, 0.0)  # an ordinary state keeps the box rule


def test_the_svg_draws_a_choices_loop_on_its_diamond_not_floating_beside_it(client, admin_token):
    import re

    from app.modules.architecture.tests._helpers import add_state, add_transition, make_element, make_machine, project_base, setup
    from tests.conftest import auth_headers

    _org, project, token = setup(client, admin_token, "Arch marker loop")
    element = make_element(client, token, project["id"], "Gauge")
    machine = make_machine(client, token, project["id"], element["id"])
    choice = add_state(client, token, project["id"], machine["id"], "Ask", kind="choice", x=100, y=100, width=36, height=36)
    add_transition(client, token, project["id"], machine["id"], choice["id"], choice["id"], guard="no")
    svg = client.get(f"{project_base(project['id'])}/state-machine-diagrams/{machine['id']}/svg", headers=auth_headers(token)).text
    path = re.search(r'<path d="(M [^"]+ C [^"]+)"', svg)
    assert path, svg
    numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", path.group(1))]
    # It starts at the diamond's top vertex (118, 100) and ends at its right vertex (136, 118).
    assert (numbers[0], numbers[1]) == (118.0, 100.0) and (numbers[-2], numbers[-1]) == (136.0, 118.0)


def test_the_composite_frame_leaves_room_for_a_name_and_a_gap():
    assert COMPOSITE_HEADER_HEIGHT > 0 and COMPOSITE_PADDING > 0
