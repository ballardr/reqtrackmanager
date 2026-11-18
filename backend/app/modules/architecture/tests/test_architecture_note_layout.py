"""Tests for the layout of an annotation note (`diagram_note_layout`): the lines of a note keep the breaks a person typed and wrap
between words, an Automatic note is drawn in the frame its content needs (and a Manual or an empty one at its stored size), and
the frame is the same one the browser's copy computes.

`frontend/src/modules/architecture/noteLayoutCases.json` holds the cases the browser's copy (`noteLayout.ts`) is tested against;
this file produces it from the Python rule and fails when it is out of date. To refresh it after a deliberate change, run this
test with `UPDATE_SHAPE_CASES=1`, review the diff and update the browser copy to match.
"""

from __future__ import annotations

import json
import os

import pytest

from app.modules.architecture.diagram_note_layout import (
    NOTE_CAPTION_HEIGHT,
    NOTE_FONT_SIZE,
    NOTE_LINE_HEIGHT,
    NOTE_MAX_WIDTH,
    NOTE_MIN_WIDTH,
    NOTE_PADDING,
    TITLE_PERCENT,
    automatic_frame,
    drawn_size,
    note_lines,
)
from app.modules.architecture.diagram_symbol_label import text_width
from app.modules.architecture.enums import NoteSizeMode, NoteTone
from app.modules.architecture.tests._repository import FRONTEND_SRC, needs_repository

CASES_FILE = FRONTEND_SRC / "modules" / "architecture" / "noteLayoutCases.json"

LONG = "The flight controller reads the inertial unit and the barometer before it commands the motors at one kilohertz"

#: (name, title, text)
NOTES = [
    ("one short line", "", "Check with ops"),
    ("a long line wraps at the maximum width", "", LONG),
    ("typed breaks and a blank line are kept", "", "One\n\nTwo\nThree"),
    ("a title wider than the text", "A fairly long heading for a note", "Hi"),
    ("a title alone", "Heading", ""),
    ("a title that wraps", "A heading so long that it has to wrap onto a second line of the bold text in the note", "x"),
    ("an empty note", "", ""),
    ("only blanks", "   ", "\n\n  "),
    ("one very long word is kept whole", "", "x" * 80),
    ("non-Latin text breaks between characters", "", "電源が入っているかどうかを確認する電源が入っているかどうかを確認する電源が入っている"),
    ("leading line breaks and trailing space are dropped", "", "\n\nText  \n"),
    ("windows line endings", "", "a\r\nb"),
    ("a title with extra spaces", "  A   B ", "t"),
    ("capitals and signs are wider", "", "ABS MWM @ 100%"),
]

NARROW_WIDTHS = [88, 148, 308]


def note_cases() -> dict:
    """Every note with the lines and frame the Python rule gives it, with and without a caption, and at some fixed widths."""
    cases = []
    for name, title, text in NOTES:
        at_max = note_lines(title, text, NOTE_MAX_WIDTH - 2 * NOTE_PADDING)
        cases.append({
            "name": name, "title": title, "text": text,
            "lines": {"title": at_max.title, "text": at_max.text},
            "frame": automatic_frame(title, text, False),
            "frame_with_caption": automatic_frame(title, text, True),
            "wrapped": [
                {"inner": inner, "title": (laid := note_lines(title, text, inner)).title, "text": laid.text}
                for inner in NARROW_WIDTHS
            ],
        })
    drawn = []
    for mode in NoteSizeMode:
        for tone in (NoteTone.NONE, NoteTone.WARNING):
            for name, title, text in NOTES[:4] + NOTES[6:7]:
                width, height = drawn_size(mode, tone, title, text, 160.0, 60.0)
                drawn.append({"mode": mode.value, "tone": tone.value, "name": name, "size": [width, height]})
    return {"cases": cases, "drawn": drawn}


@needs_repository
def test_the_shared_note_layout_cases_are_current():
    produced = json.dumps(note_cases(), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SHAPE_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "noteLayoutCases.json is out of date with diagram_note_layout; run this test with UPDATE_SHAPE_CASES=1, review the "
        "diff and update noteLayout.ts to match."
    )


def _units(width_thousandths: int) -> int:
    return (width_thousandths + 999) // 1000


def test_a_short_note_is_drawn_the_padding_from_its_text_on_every_side():
    frame = automatic_frame("", "Check with ops", False)
    assert frame is not None
    width = _units(text_width("Check with ops", NOTE_FONT_SIZE)) + 2 * NOTE_PADDING
    assert frame == (max(NOTE_MIN_WIDTH, width), NOTE_LINE_HEIGHT + 2 * NOTE_PADDING)


def test_a_long_line_wraps_at_the_maximum_width_and_the_frame_holds_every_line():
    laid = note_lines("", LONG, NOTE_MAX_WIDTH - 2 * NOTE_PADDING)
    assert len(laid.text) > 1 and " ".join(laid.text) == LONG
    frame = automatic_frame("", LONG, False)
    assert frame is not None and frame[0] <= NOTE_MAX_WIDTH
    assert frame[1] == len(laid.text) * NOTE_LINE_HEIGHT + 2 * NOTE_PADDING
    widest = max(_units(text_width(line, NOTE_FONT_SIZE)) for line in laid.text)
    assert frame[0] == widest + 2 * NOTE_PADDING


def test_typed_breaks_are_kept_and_a_blank_line_is_one_empty_line():
    assert note_lines("", "One\n\nTwo\nThree", 300).text == ["One", "", "Two", "Three"]
    assert note_lines("", "\n\nText  \n", 300).text == ["Text"]
    assert note_lines("", "a\r\nb", 300).text == ["a", "b"]


def test_a_title_is_one_line_of_bold_text_measured_wider_than_regular_text():
    assert note_lines("  A   B ", "", 300).title == ["A B"]
    frame = automatic_frame("A fairly long heading for a note", "Hi", False)
    assert frame is not None
    bold = _units(text_width("A fairly long heading for a note", NOTE_FONT_SIZE, TITLE_PERCENT))
    assert bold > _units(text_width("A fairly long heading for a note", NOTE_FONT_SIZE))
    assert frame[0] == bold + 2 * NOTE_PADDING and frame[1] == 2 * NOTE_LINE_HEIGHT + 2 * NOTE_PADDING


def test_one_very_long_word_is_kept_whole_and_sets_the_width():
    frame = automatic_frame("", "x" * 80, False)
    assert frame is not None and frame[0] == _units(text_width("x" * 80, NOTE_FONT_SIZE)) + 2 * NOTE_PADDING > NOTE_MAX_WIDTH
    assert note_lines("", "x" * 80, 100).text == ["x" * 80]


def test_a_toned_note_has_room_for_its_caption():
    plain, captioned = automatic_frame("", "Hi", False), automatic_frame("", "Hi", True)
    assert plain is not None and captioned is not None
    assert captioned == (plain[0], plain[1] + NOTE_CAPTION_HEIGHT)
    assert drawn_size("automatic", "none", "", "Hi", 160, 60) == (float(plain[0]), float(plain[1]))
    assert drawn_size("automatic", "warning", "", "Hi", 160, 60) == (float(captioned[0]), float(captioned[1]))


@pytest.mark.parametrize("title,text", [("", ""), ("   ", "\n\n  ")])
def test_an_empty_note_has_no_content_frame_and_keeps_its_stored_size(title, text):
    assert automatic_frame(title, text, False) is None
    assert drawn_size("automatic", "none", title, text, 160, 60) == (160, 60)


def test_a_manual_note_is_drawn_at_its_stored_size():
    assert drawn_size("manual", "none", "", "Hi", 200, 90) == (200, 90)
    assert drawn_size(NoteSizeMode.MANUAL, NoteTone.WARNING, "T", "Hi", 123.5, 45.5) == (123.5, 45.5)
