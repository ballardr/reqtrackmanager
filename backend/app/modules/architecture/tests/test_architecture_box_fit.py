"""Tests for the size an element box needs (`diagram_box_fit`): the name breaks between words, a symbol, the code line and every
line of the name are held by the frame, the stored size is only ever made larger, and the frame is the same one the browser's
copy computes and the server SVG draws.

`frontend/src/modules/architecture/elementBoxFitCases.json` holds the cases the browser's copy (`elementBoxFit.ts`) is tested
against; this file produces it from the Python rule and fails when it is out of date. To refresh it after a deliberate change,
run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update the browser copy to match.
"""

from __future__ import annotations

import json
import os
import re
import uuid

from sqlalchemy.orm import Session

from app.modules.architecture.diagram_box_fit import (
    BOX_MIN_HEIGHT,
    BOX_MIN_WIDTH,
    CAPTION_LINE_HEIGHT,
    INSET_LEFT,
    INSET_RIGHT,
    INSET_Y,
    NAME_FONT_SIZE,
    NAME_LINE_HEIGHT,
    NAME_PERCENT,
    SYMBOL_GAP,
    SYMBOL_HEIGHT,
    drawn_box_size,
    fit_box,
)
from app.modules.architecture.diagram_svg import _framed_nodes, _node, render_diagram
from app.modules.architecture.diagram_symbol_label import text_width
from app.modules.architecture.schemas import ViewNode
from app.modules.architecture.tests._repository import FRONTEND_SRC, needs_repository

CASES_FILE = FRONTEND_SRC / "modules" / "architecture" / "elementBoxFitCases.json"

LONG = "Flight controller and motor driver board"
CAPTION = "ELM-001 · Subsystem"

#: (name, has_symbol, caption, element name)
BOXES = [
    ("no symbol, a short name", False, CAPTION, "Gateway"),
    ("a symbol, a short name", True, CAPTION, "Gateway"),
    ("a symbol, a long name", True, CAPTION, LONG),
    ("no symbol, a long name", False, CAPTION, LONG),
    ("one very long word", True, CAPTION, "Supercalifragilisticexpialidocious"),
    ("two long words", False, CAPTION, "Telecommunications Infrastructure"),
    ("a long type name in the caption", False, "ELM-001 · Hardware-in-the-loop simulation rig", "Rig"),
    ("hyphenated words break after the hyphen", False, CAPTION, "Command-and-control-segment-gateway"),
    ("non-Latin text breaks between characters", True, CAPTION, "電源が入っているかどうかを確認する電源制御ユニット"),
    ("an empty name", True, CAPTION, ""),
    ("a locked box measures its code", False, "", "ELM-001"),
    ("capitals and signs are wider", False, CAPTION, "ABS MWM @ 100% WWW"),
]

WIDTHS = [80.0, 160.0, 400.0]


def box_cases() -> dict:
    """Every box with the fit the Python rule gives it at some fixed stored widths."""
    cases = []
    for name, has_symbol, caption, element_name in BOXES:
        fits = []
        for width in WIDTHS:
            fit = fit_box(has_symbol, caption, element_name, width)
            fits.append({"width": width, "min_width": fit.min_width, "min_height": fit.min_height, "lines": fit.lines})
        cases.append({"name": name, "has_symbol": has_symbol, "caption": caption, "element_name": element_name, "fits": fits})
    drawn = []
    for name, has_symbol, caption, element_name in BOXES:
        for stored in [(160.0, 80.0), (60.0, 30.0), (300.0, 200.0)]:
            drawn.append({"name": name, "stored": list(stored), "size": list(drawn_box_size(has_symbol, caption, element_name, *stored))})
    return {"cases": cases, "drawn": drawn}


@needs_repository
def test_the_shared_box_fit_cases_are_current():
    produced = json.dumps(box_cases(), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "elementBoxFitCases.json is out of date with diagram_box_fit; run this test with UPDATE_SHAPE_CASES=1, review the "
        "diff and update elementBoxFit.ts to match."
    )


def _units(width_thousandths: int) -> int:
    return (width_thousandths + 999) // 1000


def test_the_height_is_the_symbol_the_name_lines_the_caption_and_the_insets():
    plain = fit_box(False, CAPTION, "Gateway", 160)
    assert plain.lines == ["Gateway"]
    assert plain.min_height == max(BOX_MIN_HEIGHT, 2 * INSET_Y + NAME_LINE_HEIGHT + CAPTION_LINE_HEIGHT)
    symbol = fit_box(True, CAPTION, "Gateway", 160)
    assert symbol.min_height == plain.min_height + SYMBOL_HEIGHT + SYMBOL_GAP


def test_a_long_name_wraps_between_words_at_the_drawn_width_and_the_frame_holds_every_line():
    fit = fit_box(True, CAPTION, LONG, 160)
    assert len(fit.lines) > 1 and " ".join(fit.lines) == LONG
    for line in fit.lines:
        assert _units(text_width(line, NAME_FONT_SIZE, NAME_PERCENT)) <= 160 - INSET_LEFT - INSET_RIGHT
    assert fit.min_height == 2 * INSET_Y + len(fit.lines) * NAME_LINE_HEIGHT + CAPTION_LINE_HEIGHT + SYMBOL_HEIGHT + SYMBOL_GAP
    # A wider box wraps less, so it needs less height.
    assert fit_box(True, CAPTION, LONG, 400).min_height < fit.min_height


def test_one_very_long_word_is_kept_whole_and_sets_the_width():
    word = "Supercalifragilisticexpialidocious"
    fit = fit_box(False, CAPTION, word, 100)
    assert fit.lines == [word]
    assert fit.min_width == _units(text_width(word, NAME_FONT_SIZE, NAME_PERCENT)) + INSET_LEFT + INSET_RIGHT
    assert fit.min_width > BOX_MIN_WIDTH


def test_the_caption_and_the_symbol_set_the_width_too():
    wide = "ELM-001 · Hardware-in-the-loop simulation rig"
    fit = fit_box(False, wide, "Rig", 80)
    assert fit.min_width == _units(text_width(wide, 11)) + INSET_LEFT + INSET_RIGHT
    assert fit_box(True, "", "", 10).min_width == BOX_MIN_WIDTH
    assert fit_box(False, "", "", 10).min_height == BOX_MIN_HEIGHT


def test_the_stored_size_is_only_ever_made_larger():
    assert drawn_box_size(True, CAPTION, LONG, 400, 300) == (400.0, 300.0)
    width, height = drawn_box_size(True, CAPTION, LONG, 160, 80)
    assert width == 160.0 and height == float(fit_box(True, CAPTION, LONG, 160).min_height) > 80
    width, height = drawn_box_size(False, CAPTION, "Supercalifragilisticexpialidocious", 40, 20)
    assert width > 40 and height >= BOX_MIN_HEIGHT


def _node_view(
    *, symbol_id: uuid.UUID | None = None, name: str = LONG, locked: bool = False, width: float = 160.0, height: float = 80.0,
) -> ViewNode:
    """A node of the view at the origin, with the fields the fit reads."""
    return ViewNode(
        placement_id=uuid.uuid4(), element_id=uuid.uuid4(), unique_code="ELM-001", name=name, display_note="", locked=locked,
        shared=False, hidden=False, status="active", parent_id=None, element_type_id=None, element_type_name="Subsystem",
        shape="rounded", color_light="#dbeafe", color_dark=None, symbol_id=symbol_id, ports=[], x=0.0, y=0.0, width=width,
        height=height, collapsed=False, internal_connection_ids=[],
    )


SYMBOL = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect x="2" y="2" width="36" height="36"/></svg>'


def test_the_export_draws_the_framed_node_and_every_line_of_the_name_whole():
    symbol_id = uuid.uuid4()
    node = _node_view(symbol_id=symbol_id)
    [framed] = _framed_nodes([node], {symbol_id: SYMBOL})
    fit = fit_box(True, "ELM-001 · Subsystem", LONG, 160)
    assert (framed.width, framed.height) == (160.0, float(fit.min_height))
    svg = _node(framed, {symbol_id: SYMBOL})
    for line in fit.lines:
        assert f">{line}</text>" in svg
    assert "…" not in svg
    # The symbol sits at its fixed height inside the frame and the last name line ends above the frame's bottom edge.
    assert f'height="{SYMBOL_HEIGHT:.1f}"' in svg
    baselines = [float(y) for y in re.findall(r'<text x="[\d.]+" y="([\d.]+)" text-anchor="middle" font-size="12"', svg)]
    assert len(baselines) == len(fit.lines) and max(baselines) < framed.y + framed.height


def test_a_locked_node_is_framed_on_its_code_and_a_symbol_the_export_cannot_read_adds_no_room():
    [locked] = _framed_nodes([_node_view(locked=True, name="", width=40.0, height=20.0)], {})
    fit = fit_box(False, "", "ELM-001", 40)
    assert (locked.width, locked.height) == (float(BOX_MIN_WIDTH), float(fit.min_height))
    # With room the code needs only the least box.
    [roomy] = _framed_nodes([_node_view(locked=True, width=160.0, height=20.0)], {})
    assert (roomy.width, roomy.height) == (160.0, float(BOX_MIN_HEIGHT))
    unread = _node_view(symbol_id=uuid.uuid4(), name="Gateway")
    [plain] = _framed_nodes([unread], {})
    assert plain.height == 80.0


def test_render_diagram_is_deterministic_and_keeps_the_stored_size_in_the_view():
    from app.modules.architecture.enums import LineShape
    from app.modules.architecture.schemas import DiagramView
    node = _node_view()
    view = DiagramView.model_construct(
        diagram=type("D", (), {"unique_code": "DGM-001", "name": "d", "line_hops": False, "line_shape": LineShape.STRAIGHT})(),
        toggles=[], nodes=[node], edges=[], notes=[], anchors=[], boundaries=[],
    )
    db = Session()
    first = render_diagram(db, view)
    assert render_diagram(db, view) == first
    assert node.height == 80.0
