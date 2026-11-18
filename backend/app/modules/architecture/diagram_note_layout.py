"""
Module: modules.architecture.diagram_note_layout

The layout of an annotation note's text on a diagram: where its lines break and, for a note whose size is Automatic, the frame
that holds them.

Responsibilities:
- Break a note's title (bold) and text into lines (`note_lines`) at a given inner width, keeping the line breaks a person typed
  (a blank line stays one empty line) and wrapping between words only.
- Size an Automatic note to its content (`automatic_frame`): the widest line and the line count, each with `NOTE_PADDING`
  around them, wrapped at `NOTE_MAX_WIDTH` (a single word wider than that is kept whole and sets the width).
- Give the frame a note is drawn in (`drawn_size`): the computed one for an Automatic note with content, the stored size
  otherwise.

Design decisions:
- **One rule, two implementations.** The browser draws the same lines in the same frame (`frontend/src/modules/architecture/
  noteLayout.ts` is the TypeScript copy) and every export reads it from here, so a leader starts the same distance from the
  words on the screen and in the exports. `noteLayoutCases.json`, written by `tests/test_architecture_note_layout.py`, holds the
  cases both are tested against; a change is made in both.
- **One measure for every text.** Widths come from the symbol label's width table (`diagram_symbol_label.text_width`) at the
  note's font size, wider than the system fonts' glyphs, so a note may draw a little larger than its text needs and never smaller.
  The bold title is measured `TITLE_PERCENT` wider than regular text.
- **`NOTE_PADDING` is the distance from the frame's edge to the text on every side**, borders included, so a leader that ends
  at the frame ends that close to the words. A note's caption (the word "Note" a toned note draws under its text) adds
  `NOTE_CAPTION_HEIGHT`.
- **An empty note has no content frame**: it keeps its stored size, which is what the editor shows for the placeholder.

Dependencies: `diagram_symbol_label` (the width table and word wrapping), `enums`.
"""

from __future__ import annotations

from typing import NamedTuple

from app.modules.architecture.diagram_symbol_label import text_width, wrap_label
from app.modules.architecture.enums import NoteSizeMode, NoteTone

#: The font size and line height a note's text is drawn at (diagram units).
NOTE_FONT_SIZE = 13
NOTE_LINE_HEIGHT = 16

#: The distance from a note's frame to its text, on every side (diagram units, borders included).
NOTE_PADDING = 6

#: The widest an Automatic note's text is wrapped to, the narrowest its frame is drawn, and the height of the caption row.
NOTE_MAX_WIDTH = 320
NOTE_MIN_WIDTH = 48
NOTE_CAPTION_HEIGHT = 14

#: How much wider (percent) the bold title is measured than regular text.
TITLE_PERCENT = 110


class NoteLines(NamedTuple):
    """The lines a note draws, top to bottom.

    Attributes:
        title: The title's lines (bold), none when there is no title.
        text: The text's lines, an empty string for a blank line the person typed.
    """

    title: list[str]
    text: list[str]


def clean_text(text: str) -> str:
    """A note's text as it is drawn: line endings made `\\n`, leading line breaks and trailing whitespace dropped."""
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n").rstrip()


def clean_title(title: str) -> str:
    """A note's title as it is drawn: one line, with its whitespace collapsed."""
    return " ".join(title.split())


def _paragraphs(text: str, limit: int) -> list[str]:
    """`text` wrapped to `limit` (thousandths of a unit), each typed line on its own and a blank line kept as an empty line."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        out.extend(wrap_label(paragraph, limit, NOTE_FONT_SIZE) or [""])
    return out


def note_lines(title: str, text: str, inner_width: int) -> NoteLines:
    """The lines a note draws at a given width.

    Args:
        title: The note's title (may be empty).
        text: The note's text (may be empty).
        inner_width: The width available to the text, in diagram units (the frame's width less its padding).

    Returns:
        The title's lines and the text's lines, wrapped between words, the typed line breaks kept.
    """
    limit = max(inner_width, 1) * 1000
    clean_head = clean_title(title)
    head = wrap_label(clean_head, limit, NOTE_FONT_SIZE, TITLE_PERCENT) if clean_head else []
    body = _paragraphs(clean_text(text), limit) if clean_text(text) else []
    return NoteLines(head, body)


def _widest(lines: NoteLines) -> int:
    """The widest line, in whole diagram units rounded up."""
    widths = [text_width(line, NOTE_FONT_SIZE, TITLE_PERCENT) for line in lines.title]
    widths += [text_width(line, NOTE_FONT_SIZE) for line in lines.text]
    return (max(widths, default=0) + 999) // 1000


def automatic_frame(title: str, text: str, has_caption: bool) -> tuple[int, int] | None:
    """The frame that holds a note's content.

    Args:
        title: The note's title.
        text: The note's text.
        has_caption: Whether the note draws a caption under its text (a toned note does).

    Returns:
        `(width, height)` in diagram units, or None when the note has neither title nor text.
    """
    lines = note_lines(title, text, NOTE_MAX_WIDTH - 2 * NOTE_PADDING)
    count = len(lines.title) + len(lines.text)
    if count == 0:
        return None
    width = max(NOTE_MIN_WIDTH, _widest(lines) + 2 * NOTE_PADDING)
    height = count * NOTE_LINE_HEIGHT + 2 * NOTE_PADDING + (NOTE_CAPTION_HEIGHT if has_caption else 0)
    return width, height


def drawn_size(
    size_mode: NoteSizeMode | str, tone: NoteTone | str, title: str, text: str, width: float, height: float,
) -> tuple[float, float]:
    """The size a note is drawn at.

    Args:
        size_mode: Automatic or Manual.
        tone: The note's tone (a note with no tone draws no caption).
        title: The note's title.
        text: The note's text.
        width: The stored width.
        height: The stored height.

    Returns:
        The computed frame for an Automatic note with a title or text, else the stored width and height.
    """
    if NoteSizeMode(size_mode) is NoteSizeMode.AUTOMATIC:
        frame = automatic_frame(title, text, NoteTone(tone) is not NoteTone.NONE)
        if frame is not None:
            return float(frame[0]), float(frame[1])
    return width, height
