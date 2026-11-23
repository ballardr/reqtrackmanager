"""
Module: services.report_running

The running header and footer of a document report, as the renderers share them.

Responsibilities:
- `apply_default_bands` (a plain "Page n" footer wherever the page style says nothing); `cell_lines`, `band_visible`,
  `band_for_page` (the rules every renderer applies alike); `read_marks` and `unmark` (a cell's `**bold**` and
  `*italic*`); `band_size_pt` and `band_line_cm`.

Design decisions:
- A band is an invisible three-column table in the page margin; each renderer draws it its own way (canvas callback,
  Word header part, ODF master page, HTML band) while content and rules are decided here once.
- A layout is never forced to print the organisation's footer text, logo or cover: it reads them as `{{org.footer_text}}`,
  the `org_logo` image and `if org.include_cover_page` (`report_org_values`). The default is only the page number, and
  only where no footer was written (the document's, for a style). An explicit empty band prints nothing.

Dependencies: `services.report_model`.
"""

from __future__ import annotations

import re
from dataclasses import replace

from app.services.report_model import (
    Marked,
    PageField,
    PageStyle,
    PageStyleChange,
    ReportDocument,
    RunningBand,
    SlotPart,
)

#: A band's default text size in points, and the least line height in cm (the height a larger size grows from).
BAND_SIZE_PT = 8.0
_MIN_LINE_CM = 0.4
_LEADING = 1.25
_PT_CM = 2.54 / 72
#: A run of asterisks: one is italic, two bold, three both. Four or more are literal text.
_STARS = re.compile(r"\\\*|\*+")


def band_size_pt(size: float | None) -> float:
    """The text size a band prints at: its own, else the default."""
    return BAND_SIZE_PT if size is None else float(size)


def band_line_cm(size: float | None) -> float:
    """The height of one line of a band's text in cm: the default line, or taller for a larger size."""
    return max(_MIN_LINE_CM, band_size_pt(size) * _LEADING * _PT_CM)


def read_marks(text: str) -> list[tuple[str, bool, bool]]:
    """A cell's text as `(words, bold, italic)` stretches, reading `**bold**`, `*italic*` and `***both***`.

    Only those marks are read (no code, links or equations). A mark opens before a word and closes after one, so a
    lone `*`, `2 * 3` or an unclosed mark stays as written; `\\*` is a literal asterisk. Placeholders are left in the
    words for the caller, which fills them stretch by stretch so a value is never read for marks.

    Args:
        text: One cell's text, which may hold line breaks.

    Returns:
        The stretches in order, without empty ones; plain text when nothing is marked.
    """
    items: list[list] = []  # [words, None] for text, [stars, can_open, can_close, applied] for a delimiter
    last = 0
    for match in _STARS.finditer(text):
        if match.start() > last:
            items.append([text[last:match.start()], None])
        last = match.end()
        token = match.group()
        if token == "\\*":
            items.append(["*", None])
            continue
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        items.append([len(token), bool(after) and not after.isspace(), bool(before) and not before.isspace(), False])
    if last < len(text):
        items.append([text[last:], None])
    opened: dict[str, int | None] = {"bold": None, "italic": None}
    kinds = {1: ("italic",), 2: ("bold",), 3: ("bold", "italic")}
    for index, item in enumerate(items):
        if item[1] is None or item[0] not in kinds:
            continue
        wanted = kinds[item[0]]
        if all(opened[k] is not None for k in wanted) and item[2]:
            for k in wanted:
                open_index = opened[k]
                if open_index is not None:
                    items[open_index][3] = items[index][3] = True
                opened[k] = None
        elif all(opened[k] is None for k in wanted) and item[1]:
            for k in wanted:
                opened[k] = index
    out: list[tuple[str, bool, bool]] = []
    bold = italic = False
    for item in items:
        if item[1] is None:
            if item[0]:
                out.append((item[0], bold, italic))
        elif item[3] and item[0] in kinds:
            for k in kinds[item[0]]:
                bold, italic = (not bold, italic) if k == "bold" else (bold, not italic)
        else:
            out.append(("*" * item[0], bold, italic))
    merged: list[tuple[str, bool, bool]] = []
    for words, b, i in out:
        if merged and merged[-1][1:] == (b, i):
            merged[-1] = (merged[-1][0] + words, b, i)
        else:
            merged.append((words, b, i))
    return merged


def unmark(part: SlotPart) -> tuple[str | PageField, bool, bool]:
    """A cell part as `(words or page field, bold, italic)`."""
    return (part.part, part.bold, part.italic) if isinstance(part, Marked) else (part, False, False)


def default_footer() -> RunningBand:
    """The footer a layout gets when its page style writes none: the page number, centred."""
    return RunningBand(centre=("Page ", PageField.PAGE), kind="footer")


def apply_default_bands(document: ReportDocument) -> ReportDocument:
    """`document` with a page-number footer wherever a page style has no footer of its own.

    Args:
        document: A layout's document, whose styles carry the layout's own bands (`None` where it wrote none).

    Returns:
        A copy in which every style (the document's and each section's) has a footer.
    """
    footer = default_footer()

    def filled(style: PageStyle) -> PageStyle:
        return replace(style, footer=style.footer if style.footer is not None else footer)

    blocks = [replace(b, style=filled(b.style)) if isinstance(b, PageStyleChange) else b for b in document.blocks]
    own = filled(document.style)
    return replace(document, blocks=blocks, header=own.header, footer=own.footer)


def cell_lines(parts: tuple[SlotPart, ...]) -> list[list[SlotPart]]:
    """A cell's parts split into lines at each line break in its text; an empty cell has no lines."""
    lines: list[list[SlotPart]] = [[]]
    for part in parts:
        words, bold, italic = unmark(part)
        if isinstance(words, PageField):
            lines[-1].append(part)
            continue
        for i, piece in enumerate(words.split("\n")):
            if i:
                lines.append([])
            if piece:
                lines[-1].append(Marked(piece, bold, italic) if bold or italic else piece)
    return lines if any(lines) else []


def band_visible(band: RunningBand | None, *, first_page: bool) -> bool:
    """Whether `band` prints on a page: it has content, and it is not the first page of a band that skips it."""
    return band is not None and not band.empty and (band.first_page or not first_page)


def band_for_page(band: RunningBand, *, mirrored: bool, verso: bool) -> RunningBand:
    """The band as printed on a page: the left-hand page of a double-sided document swaps the left and right cells."""
    return band.mirrored() if mirrored and verso else band


__all__ = [
    "BAND_SIZE_PT", "apply_default_bands", "band_for_page", "band_line_cm", "band_size_pt", "band_visible", "cell_lines",
    "default_footer", "read_marks", "unmark",
]
