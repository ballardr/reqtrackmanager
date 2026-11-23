"""
Module: modules.architecture.diagram_symbol_label

The layout of the label drawn inside an initial, final or choice symbol of a state machine diagram: where its
lines break and how large the symbol must be to hold them.

Responsibilities:
- Measure a text with a fixed, font-independent width table (`text_width`) at any font size; annotation notes
  (`diagram_note_layout`) use the same table, so every text on a diagram breaks at the same words.
- Break a label into lines between words only (`wrap_label`): at spaces, after a hyphen, between East Asian
  characters and at a typed line break; a word is never split.
- Find the smallest symbol that holds the label (`fit_label`): it grows from its labelled base size in steps
  until the text, `LABEL_PADDING` clear of the symbol's inner edge on every side, fits (`holds`).
- Place a label outside its symbol (`beside_label`): the symbol keeps its plain size and the text block sits
  against one side, `LABEL_PADDING` clear of the outer edge, wrapped to `BESIDE_MAX_WIDTH` and aligned toward
  the symbol.

Design decisions:
- One rule, two implementations: the browser draws the lines this module gives
  (`frontend/src/modules/architecture/symbolLabelLayout.ts` is the TypeScript copy) and the server SVG draws
  the same lines, so screen and exports break a label at the same words. `symbolLabelCases.json`, written by
  `tests/test_architecture_symbol_label.py`, holds the shared cases; a change is made in both.
- A fixed width table, not font metrics: the server has no font and browsers' glyph widths differ by platform.
  Average widths in thousandths of the font size, integers only so both languages agree exactly, are the one
  shared measure; the table is wider than system glyphs, so real text keeps its padding.
- Padding is measured: the text block's rectangle (widest line by line count) is centred on the symbol and its
  nearest corner must be at least `LABEL_PADDING` from the inner edge of the circle, ring disc or diamond (the
  diamond's edge measured at right angles, inside its stroke), in integers (thousandths of a unit, squares
  instead of roots). `TEXT_PERCENT` only sets how wide a line is first tried, so lines wrap before the exact check.
- Text outside a symbol keeps the same gap from its outer edge. The block is measured with the same table and
  rounded up to a whole unit so both languages place it identically; it lies outside the symbol's own box (the
  box lines attach to), so it is positioned relative to that box and may be negative.
- A word longer than the largest symbol's text area has no good drawing: it stays whole on one line at the
  largest size and `fits` is False, so the Selection card can warn; it is never broken mid-word or clipped.

Dependencies: `enums` (the state kinds).
"""

from __future__ import annotations

from typing import NamedTuple

from app.modules.architecture.enums import LabelPosition, StateKind

#: The label's font size and line height (diagram units).
LABEL_FONT_SIZE = 10
LABEL_LINE_HEIGHT = 12

#: The smallest labelled symbol of each kind (its square frame), the share of the symbol's size a line is first wrapped to
#: (percent), the step a symbol grows by while the label does not fit, and the largest size.
BASE_SIZE: dict[StateKind, int] = {StateKind.INITIAL: 52, StateKind.FINAL: 72, StateKind.CHOICE: 96}
TEXT_PERCENT: dict[StateKind, int] = {StateKind.INITIAL: 56, StateKind.FINAL: 42, StateKind.CHOICE: 40}

#: The least distance (diagram units) between text and a symbol's edge: inside the symbol from its inner edge, outside it from
#: its outer edge.
LABEL_PADDING = 4
SIZE_STEP = 4
MAX_SIZE = 320

#: The widest a label placed outside its symbol is first wrapped to (diagram units); a single longer word is kept whole.
BESIDE_MAX_WIDTH = 160

#: Glyph widths in thousandths of the font size, set above what the product's system font stack draws (measured with the
#: browser's canvas in the system UI font, Arial, Helvetica and Roboto; the widest rendered label was 7% under the table), so
#: the real text keeps its padding: a space, narrow glyphs, capitals, the widest capitals and signs, a full-width
#: (East Asian) character, and everything else.
_SPACE, _NARROW, _CAPITAL, _WIDE, _FULL, _OTHER = 320, 340, 740, 1000, 1000, 620
_NARROW_GLYPHS = frozenset("iljtfI.,:;'|!()[]/\\")
_WIDE_GLYPHS = frozenset("MWmw@%")
#: Code point ranges drawn full width, and so broken between any two characters.
_FULL_WIDTH = (
    (0x1100, 0x11FF), (0x2E80, 0xA4CF), (0xAC00, 0xD7AF), (0xF900, 0xFAFF), (0xFE30, 0xFE6F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6),
)


class SymbolLabelLayout(NamedTuple):
    """The drawing of a label inside its symbol.

    Attributes:
        size: The side of the square symbol that holds the label (a multiple of `SIZE_STEP`).
        lines: The label's lines, top to bottom.
        fits: False when the text does not fit the largest symbol with its padding (a word longer than its text area, drawn
            whole on a line of its own and wider than the symbol, or lines taller than it).
    """

    size: int
    lines: list[str]
    fits: bool


class BesideLayout(NamedTuple):
    """The drawing of a label placed outside its symbol.

    Attributes:
        lines: The label's lines, top to bottom.
        x: The text block's left edge, relative to the symbol's top left corner (negative to its left).
        y: The text block's top edge, relative to the symbol's top left corner (negative above it).
        width: The widest line (a whole number of units, from the width table).
        height: The block's height (lines times the line height).
        align: How the lines are aligned within the block: `left`, `center` or `right`, toward the symbol.
    """

    lines: list[str]
    x: float
    y: float
    width: int
    height: int
    align: str


def _is_full_width(code: int) -> bool:
    """True when the code point is a full-width character (drawn one em wide, and a place a line may break)."""
    return any(low <= code <= high for low, high in _FULL_WIDTH)


def _glyph(char: str) -> int:
    """The width of one character, in thousandths of the font size."""
    if char == " ":
        return _SPACE
    if char in _NARROW_GLYPHS:
        return _NARROW
    if char in _WIDE_GLYPHS:
        return _WIDE
    if "A" <= char <= "Z":
        return _CAPITAL
    return _FULL if _is_full_width(ord(char)) else _OTHER


def text_width(text: str, font_size: int = LABEL_FONT_SIZE, percent: int = 100) -> int:
    """The width a text takes at a font size (by default the label's).

    Args:
        text: Plain text.
        font_size: The font size in diagram units (annotation notes measure at their own size, with this one table).
        percent: A width factor in percent (bold text is measured wider than regular text).

    Returns:
        The width in thousandths of a diagram unit (an integer, so the browser's copy agrees exactly).
    """
    return sum(_glyph(char) for char in text) * font_size * percent // 100


def _pieces(paragraph: str) -> list[tuple[str, str]]:
    """The pieces a paragraph may be broken into, each with the separator that joins it to the one before (a space between
    words, nothing after a hyphen or between full-width characters)."""
    pieces: list[tuple[str, str]] = []
    for word in paragraph.split():
        parts: list[str] = []
        current = ""
        for char in word:
            if _is_full_width(ord(char)):
                if current:
                    parts.append(current)
                parts.append(char)
                current = ""
                continue
            current += char
            if char == "-":
                parts.append(current)
                current = ""
        if current:
            parts.append(current)
        for index, part in enumerate(parts):
            pieces.append((" " if index == 0 and pieces else "", part))
    return pieces


def wrap_label(label: str, limit: int, font_size: int = LABEL_FONT_SIZE, percent: int = 100) -> list[str]:
    """Break a label into lines, between words only.

    Args:
        label: The label text; a line break the person typed starts a new line.
        limit: The widest a line may be, in thousandths of a diagram unit.
        font_size: The font size the text is measured at (see `text_width`).
        percent: The width factor the text is measured with (see `text_width`).

    Returns:
        The lines, none empty. A word wider than `limit` is kept whole on a line of its own.
    """
    lines: list[str] = []
    for paragraph in label.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current, current_width = "", 0
        for separator, part in _pieces(paragraph):
            part_width = text_width(part, font_size, percent)
            if current and current_width + text_width(separator, font_size, percent) + part_width > limit:
                lines.append(current)
                current, current_width = part, part_width
            elif current:
                current += separator + part
                current_width += text_width(separator, font_size, percent) + part_width
            else:
                current, current_width = part, part_width
        if current:
            lines.append(current)
    return lines


def holds(kind: StateKind, size: int, lines: list[str]) -> bool:
    """Whether a symbol of `size` holds the lines with `LABEL_PADDING` clear of its inner edge.

    Args:
        kind: An initial, final or choice state kind.
        size: The side of the square frame.
        lines: The label's lines.

    Returns:
        True when the corner of the text block nearest the edge is at least `LABEL_PADDING` inside it.
    """
    width = max(text_width(line) for line in lines)  # thousandths of a unit
    height = len(lines) * LABEL_LINE_HEIGHT * 1000
    half = size // 2
    if kind is StateKind.CHOICE:
        # The diamond's inner edge is |x| + |y| = half - 2 (inside the 2-unit stroke); the corner (width/2, height/2) must be
        # `LABEL_PADDING` from it measured at right angles, i.e. slack >= padding * sqrt(2) (compared squared).
        slack2 = (half - 2) * 2000 - (width + height)
        return slack2 >= 0 and slack2 * slack2 >= 8_000_000 * LABEL_PADDING * LABEL_PADDING
    # A circle: the dot's radius, or the final state's inner disc (the text sits on the disc).
    radius = half - 1 if kind is StateKind.INITIAL else (26 * size + 36) // 72
    room = radius - LABEL_PADDING
    return room > 0 and width * width + height * height <= 4 * room * room * 1_000_000


def text_side(kind: StateKind, size: int) -> int:
    """The width a line is first tried at in a symbol of `size`: the side of the square that fits it (diagram units, whole)."""
    return size * TEXT_PERCENT[kind] // 100


def fit_label(kind: StateKind, label: str) -> SymbolLabelLayout | None:
    """The smallest symbol that holds a label, and the lines drawn in it.

    Args:
        kind: An initial, final or choice state kind.
        label: The symbol's label.

    Returns:
        The size and lines, or None when the label is blank (no label, so the symbol keeps its plain size).
    """
    text = label.strip()
    if not text:
        return None
    for size in range(BASE_SIZE[kind], MAX_SIZE + 1, SIZE_STEP):
        lines = wrap_label(text, text_side(kind, size) * 1000)
        if holds(kind, size, lines):
            return SymbolLabelLayout(size, lines, True)
    return SymbolLabelLayout(MAX_SIZE, wrap_label(text, text_side(kind, MAX_SIZE) * 1000), False)


def beside_label(label: str, position: LabelPosition, symbol_width: float, symbol_height: float) -> BesideLayout | None:
    """Where a label sits when it is outside its symbol.

    Args:
        label: The symbol's label.
        position: `LEFT`, `RIGHT`, `ABOVE` or `BELOW` (`INSIDE` is not a place outside, see `fit_label`).
        symbol_width: The width of the symbol's own box.
        symbol_height: The height of the symbol's own box.

    Returns:
        The lines and the text block's place relative to the symbol's top left corner, or None when the label is blank or the
        position is `INSIDE`. The block is `LABEL_PADDING` from the symbol's edge on its side and centred along it.
    """
    text = label.strip()
    if not text or position is LabelPosition.INSIDE:
        return None
    lines = wrap_label(text, BESIDE_MAX_WIDTH * 1000)
    width = (max(text_width(line) for line in lines) + 999) // 1000
    height = len(lines) * LABEL_LINE_HEIGHT
    if position is LabelPosition.RIGHT:
        return BesideLayout(lines, symbol_width + LABEL_PADDING, (symbol_height - height) / 2, width, height, "left")
    if position is LabelPosition.LEFT:
        return BesideLayout(lines, -(LABEL_PADDING + width), (symbol_height - height) / 2, width, height, "right")
    if position is LabelPosition.ABOVE:
        return BesideLayout(lines, (symbol_width - width) / 2, -(LABEL_PADDING + height), width, height, "center")
    return BesideLayout(lines, (symbol_width - width) / 2, symbol_height + LABEL_PADDING, width, height, "center")
