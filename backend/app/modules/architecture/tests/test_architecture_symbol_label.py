"""Tests for the layout of a symbol's label (`diagram_symbol_label`): a label breaks between words only, the symbol grows to hold
it, and a word longer than the largest symbol stays whole and is reported as not fitting.

`frontend/src/modules/architecture/symbolLabelCases.json` holds the cases the browser's copy (`symbolLabelLayout.ts`) is tested
against; this file produces it from the Python rule and fails when it is out of date. To refresh it after a deliberate change,
run this test with `UPDATE_SHAPE_CASES=1`, review the diff and update the browser copy to match.
"""

from __future__ import annotations

import json
import math
import os

import pytest

from app.modules.architecture.diagram_symbol_label import (
    BASE_SIZE,
    BESIDE_MAX_WIDTH,
    LABEL_LINE_HEIGHT,
    LABEL_PADDING,
    MAX_SIZE,
    SIZE_STEP,
    beside_label,
    fit_label,
    holds,
    text_side,
    text_width,
    wrap_label,
)
from app.modules.architecture.enums import LabelPosition, StateKind
from app.modules.architecture.tests._repository import FRONTEND_SRC, needs_repository

CASES_FILE = FRONTEND_SRC / "modules" / "architecture" / "symbolLabelCases.json"

LABELS = [
    ("short", "Full?"),
    ("two words", "Power on"),
    ("a long phrase", "Is the tank level above the high-level alarm threshold for more than ten seconds"),
    ("a hyphen is a place to break", "Over-temperature protection trip"),
    ("one very long word", "Supercalifragilisticexpialidocious"),
    ("a word longer than any symbol holds", "x" * 60),
    ("a word that just fits the choice at its base size", "Verification"),
    ("capitals and signs are wider", "ABS MWM @ 100%"),
    ("narrow glyphs are narrower", "illi jilt fl."),
    ("non-Latin text breaks between characters", "電源が入っているかどうかを確認する"),
    ("a typed line break is kept", "First line\nSecond line"),
    ("spaces around and between words", "  spaced    out  "),
    ("the longest label", ("lorem ipsum dolor sit amet " * 10)[:256]),
]


def _case(kind: StateKind, name: str, label: str) -> dict:
    layout = fit_label(kind, label)
    assert layout is not None
    return {"kind": kind.value, "name": name, "label": label, "size": layout.size, "lines": layout.lines, "fits": layout.fits}


#: The symbol boxes a label outside a symbol is placed against (each marker kind's plain size, and a larger stored box).
BESIDE_BOXES = [(20.0, 20.0), (28.0, 28.0), (36.0, 36.0), (60.0, 40.0)]
OUTSIDE = [position for position in LabelPosition if position is not LabelPosition.INSIDE]


def _beside_case(name: str, label: str, position: LabelPosition, box: tuple[float, float]) -> dict:
    layout = beside_label(label, position, *box)
    assert layout is not None
    return {
        "name": name, "label": label, "position": position.value, "symbol": list(box), "lines": layout.lines, "x": layout.x,
        "y": layout.y, "width": layout.width, "height": layout.height, "align": layout.align,
    }


def label_cases() -> dict:
    """Every label on every symbol kind with the size and lines the Python rule gives, and the measured width of sample texts."""
    return {
        "cases": [_case(kind, name, label) for kind in StateKind if kind is not StateKind.STATE for name, label in LABELS],
        "beside": [
            _beside_case(name, label, position, box) for name, label in LABELS[:6] + LABELS[9:11] for position in OUTSIDE for box in BESIDE_BOXES
        ],
        "widths": [{"text": t, "width": text_width(t)} for t in ["", "iii", "WWW", "abc 123", "電源", "A-b"]],
    }


@needs_repository
def test_the_shared_label_cases_are_current():
    produced = json.dumps(label_cases(), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "symbolLabelCases.json is out of date with diagram_symbol_label; run this test with UPDATE_SHAPE_CASES=1, review the "
        "diff and update symbolLabelLayout.ts to match."
    )


def clearance(kind: StateKind, size: int, lines: list[str]) -> float:
    """The distance, by floating point and from first principles, between the nearest corner of the text block (centred on the
    symbol) and the symbol's inner edge: the circle's or disc's radius less the corner's distance from the centre, or the
    diamond's edge (inside its 2-unit stroke) measured at right angles."""
    a = max(text_width(line) for line in lines) / 1000 / 2
    b = len(lines) * LABEL_LINE_HEIGHT / 2
    half = size // 2
    if kind is StateKind.CHOICE:
        return ((half - 2) - (a + b)) / math.sqrt(2)
    radius = half - 1 if kind is StateKind.INITIAL else (26 * size + 36) // 72
    return radius - math.hypot(a, b)


MARKERS = [kind for kind in StateKind if kind is not StateKind.STATE]


@pytest.mark.parametrize("kind", MARKERS)
@pytest.mark.parametrize("name,label", LABELS)
def test_a_label_never_breaks_inside_a_word_and_the_symbol_holds_it_or_says_it_does_not(kind, name, label):
    layout = fit_label(kind, label)
    assert layout is not None and BASE_SIZE[kind] <= layout.size <= MAX_SIZE and layout.size % SIZE_STEP == 0
    if label.isascii():
        # Rejoining the lines gives back the same text without its spaces: nothing was dropped, cut or split.
        assert "".join("".join(layout.lines).split()) == "".join(label.split()), name
        assert all(line and line == line.strip() for line in layout.lines)
        # Every line break falls on a space, after a hyphen or at a line break the person typed.
        for upper, lower in zip(layout.lines, layout.lines[1:], strict=False):
            assert upper.endswith("-") or " ".join(label.split()).find(upper + " " + lower) >= 0 or "\n" in label, name
    if layout.fits:
        assert clearance(kind, layout.size, layout.lines) >= LABEL_PADDING - 1e-9, name


def test_a_symbol_is_the_smallest_that_holds_its_label():
    for kind in MARKERS:
        layout = fit_label(kind, "Is the tank level above the high-level alarm threshold for more than ten seconds")
        assert layout is not None and layout.fits and layout.size > BASE_SIZE[kind]
        smaller = layout.size - SIZE_STEP
        lines = wrap_label(
            "Is the tank level above the high-level alarm threshold for more than ten seconds", text_side(kind, smaller) * 1000,
        )
        assert smaller < BASE_SIZE[kind] or clearance(kind, smaller, lines) < LABEL_PADDING


def test_text_inside_a_symbol_keeps_the_padding_from_its_inner_edge_and_text_just_over_it_does_not():
    assert LABEL_PADDING == 4
    for kind in MARKERS:
        size = BASE_SIZE[kind]
        assert holds(kind, size, ["Go"]) and clearance(kind, size, ["Go"]) >= LABEL_PADDING
        # Text as wide as the whole symbol touches or passes its edge.
        assert not holds(kind, size, ["W" * 10]) and clearance(kind, size, ["W" * 10]) < LABEL_PADDING


def test_a_short_label_keeps_the_base_size_and_a_blank_one_has_no_layout():
    for kind in MARKERS:
        layout = fit_label(kind, "Go")
        assert layout is not None and layout.size == BASE_SIZE[kind]
    assert fit_label(StateKind.CHOICE, "") is None and fit_label(StateKind.CHOICE, "  \n ") is None


def test_a_word_longer_than_the_largest_symbol_is_kept_whole_on_a_line_of_its_own_and_reported():
    layout = fit_label(StateKind.CHOICE, "before " + "x" * 60 + " after")
    assert layout is not None and not layout.fits and layout.size == MAX_SIZE
    assert layout.lines == ["before", "x" * 60, "after"]


def test_a_hyphen_and_a_full_width_character_are_places_to_break_and_a_typed_line_break_is_kept():
    assert wrap_label("well-known fact", text_width("well-") + 1) == ["well-", "known", "fact"]
    assert wrap_label("電源電源", text_width("電源") + 1) == ["電源", "電源"]
    assert wrap_label("a\n\nb", 10**9) == ["a", "b"]


def test_the_width_table_measures_wide_and_narrow_glyphs_differently():
    assert text_width("iii") < text_width("abc") < text_width("WWW")
    assert text_width("") == 0


@pytest.mark.parametrize("position", OUTSIDE)
@pytest.mark.parametrize("name,label", LABELS)
def test_a_label_outside_its_symbol_keeps_the_padding_from_the_symbol_never_overlaps_it_and_never_splits_a_word(position, name, label):
    for width, height in BESIDE_BOXES:
        layout = beside_label(label, position, width, height)
        assert layout is not None
        if label.isascii():
            assert "".join("".join(layout.lines).split()) == "".join(label.split()), name
        left, top, right, bottom = layout.x, layout.y, layout.x + layout.width, layout.y + layout.height
        gaps = {
            LabelPosition.RIGHT: left - width, LabelPosition.LEFT: -right, LabelPosition.BELOW: top - height, LabelPosition.ABOVE: -bottom,
        }
        assert gaps[position] == LABEL_PADDING, name  # the block sits exactly the padding from the symbol's edge
        # It is centred along that edge, and its alignment faces the symbol.
        if position in (LabelPosition.LEFT, LabelPosition.RIGHT):
            assert (top + bottom) / 2 == height / 2
            assert layout.align == ("left" if position is LabelPosition.RIGHT else "right")
        else:
            assert (left + right) / 2 == width / 2 and layout.align == "center"


def test_a_label_outside_its_symbol_wraps_to_the_maximum_width_unless_one_word_is_wider():
    wide = beside_label("Is the tank level above the high-level alarm threshold for more than ten seconds", LabelPosition.RIGHT, 36, 36)
    assert wide is not None and len(wide.lines) > 1 and all(text_width(line) <= BESIDE_MAX_WIDTH * 1000 for line in wide.lines)
    word = beside_label("x" * 60, LabelPosition.ABOVE, 20, 20)
    assert word is not None and word.lines == ["x" * 60] and word.width > BESIDE_MAX_WIDTH


def test_a_blank_label_or_a_label_inside_has_no_outside_layout():
    assert beside_label("", LabelPosition.RIGHT, 20, 20) is None and beside_label("  ", LabelPosition.LEFT, 20, 20) is None
    assert beside_label("Go", LabelPosition.INSIDE, 20, 20) is None
