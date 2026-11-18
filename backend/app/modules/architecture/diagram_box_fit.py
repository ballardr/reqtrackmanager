"""
Module: modules.architecture.diagram_box_fit

The least size an element box on a block diagram needs to show its symbol, its code line and its name whole.

Responsibilities:
- Break a box's name into lines at the width the box is drawn at, between words only (`fit_box`), and total the height of the
  symbol, the name's lines and the caption line with the box's insets.
- Give the size a box is drawn at (`drawn_box_size`): the larger of the stored size and that fit, in each direction.

Design decisions:
- **The stored size is never rewritten.** A symbol is set on an element, on its type, or changed on the type later, which touches
  boxes on diagrams nobody has open, so the fit is computed wherever a box is read and the stored width and height stay what the
  person last drew. A box that was already cut therefore grows to the right and down on an existing diagram.
- **One rule, two implementations.** The browser draws the same lines in the same frame (`frontend/src/modules/architecture/
  elementBoxFit.ts` is the TypeScript copy) and the server SVG reads it from here, so a line attaches to the same frame on the
  screen and in an export. `elementBoxFitCases.json`, written by `tests/test_architecture_box_fit.py`, holds the cases both are
  tested against; a change is made in both.
- **One measure for every text**, the symbol label's width table (`diagram_symbol_label.text_width`), which is wider than the
  system fonts' glyphs, so a box may draw a little larger than its text needs and never smaller. The name is measured at the
  bold factor because the exports draw it bold.
- **The symbol has a fixed height** (`SYMBOL_HEIGHT`) rather than a share of the box, so the box's height is a plain sum and a
  taller box leaves room, never a larger symbol.
- **A locked box measures what it draws**: the screen draws its code and "(not visible)", the export its code, so each passes its
  own text as the name.

Dependencies: `diagram_symbol_label` (the width table and word wrapping).
"""

from __future__ import annotations

from typing import NamedTuple

from app.modules.architecture.diagram_symbol_label import text_width, wrap_label

#: The least a box is drawn: the resize handles' minimum (diagram units).
BOX_MIN_WIDTH = 80
BOX_MIN_HEIGHT = 40

#: The distance from the frame's edge to the content: the left edge has a 4-unit accent border, the others a 1-unit border, each
#: inside 6 units of padding.
INSET_LEFT = 10
INSET_RIGHT = 7
INSET_Y = 7

#: The height of the symbol and the gap under it.
SYMBOL_HEIGHT = 40
SYMBOL_GAP = 4

#: The name's font size, its line height and the factor it is measured wider by (the exports draw it bold).
NAME_FONT_SIZE = 13
NAME_LINE_HEIGHT = 16
NAME_PERCENT = 110

#: The caption's (code and type) font size and line height.
CAPTION_FONT_SIZE = 11
CAPTION_LINE_HEIGHT = 17


class BoxFit(NamedTuple):
    """What a box needs.

    Attributes:
        min_width: The least width that shows every word and the caption whole.
        min_height: The least height at the width the box is drawn at (the larger of the stored width and `min_width`).
        lines: The name's lines at that width.
    """

    min_width: int
    min_height: int
    lines: list[str]


def _units(width_thousandths: int) -> int:
    """`width_thousandths` in whole diagram units, rounded up."""
    return (width_thousandths + 999) // 1000


def fit_box(has_symbol: bool, caption: str, name: str, width: float) -> BoxFit:
    """The least size a box needs.

    Args:
        has_symbol: Whether the box draws a symbol.
        caption: The small line under the name (the code and the type); empty for none.
        name: The element's name.
        width: The box's stored width, which the name's lines are broken for.

    Returns:
        The least width, the least height at the drawn width and the name's lines.
    """
    longest_word = max((text_width(line, NAME_FONT_SIZE, NAME_PERCENT) for line in wrap_label(name, 1, NAME_FONT_SIZE, NAME_PERCENT)), default=0)
    caption_width = text_width(caption, CAPTION_FONT_SIZE) if caption else 0
    content = max(_units(longest_word), _units(caption_width), SYMBOL_HEIGHT if has_symbol else 0)
    min_width = max(BOX_MIN_WIDTH, content + INSET_LEFT + INSET_RIGHT)
    drawn_width = max(width, min_width)
    lines = wrap_label(name, int((drawn_width - INSET_LEFT - INSET_RIGHT) * 1000), NAME_FONT_SIZE, NAME_PERCENT)
    height = 2 * INSET_Y + len(lines) * NAME_LINE_HEIGHT
    if has_symbol:
        height += SYMBOL_HEIGHT + SYMBOL_GAP
    if caption:
        height += CAPTION_LINE_HEIGHT
    return BoxFit(min_width, max(BOX_MIN_HEIGHT, height), lines)


def drawn_box_size(has_symbol: bool, caption: str, name: str, width: float, height: float) -> tuple[float, float]:
    """The size a box is drawn at.

    Args:
        has_symbol: Whether the box draws a symbol.
        caption: The small line under the name.
        name: The element's name.
        width: The stored width.
        height: The stored height.

    Returns:
        The stored size, made larger in either direction where the content needs it.
    """
    fit = fit_box(has_symbol, caption, name, width)
    return float(max(width, fit.min_width)), float(max(height, fit.min_height))
