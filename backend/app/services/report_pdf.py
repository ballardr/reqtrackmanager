"""
Module: services.report_pdf

Renders a neutral `ReportDocument` (`services.report_model`) to PDF with
ReportLab. It is the only place block types are turned into flowables, so the
requirement report and every module report share one layout.

Design decisions:
- Every string goes through `report_document.safe` before reaching a
  `Paragraph` (ReportLab parses markup, so unescaped user text is an SSRF /
  local-file-read primitive; see that function's docstring).
- Equations: a display `Equation` is the `report_math` SVG drawn as vector (centred); an inline one is a PNG of the
  same drawing placed in the paragraph with an `<img>` tag on the text baseline, because ReportLab reads an inline
  image only from a file path, so the PNGs live in a temporary directory that exists for one render. The `<img>`
  tags are built here from numbers and a path this module made, never from text; one that cannot be drawn is
  printed as its source.
- Page setup follows the layout's page size (A4 by default) and orientation: portrait has 2 cm top and bottom
  margins, landscape 1.5 cm all round.

Dependencies: ReportLab, `services.report_document`, `services.report_fonts`, `services.report_math`,
`services.report_model`, `services.report_svg` (a figure given as SVG is drawn as vector).
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Spacer
from reportlab.platypus import PageBreak as RlPageBreak
from reportlab.platypus import Paragraph as RlParagraph

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_document import (
    STYLES,
    ReportBranding,
    build_pdf,
    header_text_color,
    image_flowable,
    safe,
    styled_table,
    title_flowables,
    toned_paragraph,
)
from app.services.report_fonts import text_width
from app.services.report_math import png_of, typeset
from app.services.report_model import (
    BulletList,
    Equation,
    Gap,
    Heading,
    Image,
    Note,
    NumberedList,
    PageBreak,
    Paragraph,
    ReportDocument,
    Styled,
    Table,
    finalize_links,
    page_dimensions_cm,
    text_runs,
)
from app.services.report_svg import svg_flowable

_NOTE = ParagraphStyle("report_note", parent=STYLES["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
_CELL = ParagraphStyle("report_cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9.5)
_HEAD = ParagraphStyle("report_head", parent=_CELL, fontName="Helvetica-Bold")
_PLAIN_CELL = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=8, leading=10)
_CELL_FONT_SIZE = 7.5
_MAX_CELL_POINTS = 70.0
_MAX_WORD_POINTS = 100.0  # a pasted unbroken string must not claim the page; ReportLab breaks it
_CELL_PADDING_POINTS = 14.0
_PORTRAIT_MARGINS = {"topMargin": 2 * cm, "bottomMargin": 2 * cm}
_LANDSCAPE_MARGINS = {"leftMargin": 1.5 * cm, "rightMargin": 1.5 * cm, "topMargin": 1.5 * cm, "bottomMargin": 1.5 * cm}


class _InlineImages:
    """The temporary directory that holds the PNGs of inline equations for one render (see the module docstring)."""

    def __init__(self) -> None:
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._count = 0

    def add(self, png: bytes) -> str:
        """Writes `png` and returns the path to give an `<img>` tag."""
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(prefix="report-math-")
        self._count += 1
        path = Path(self._directory.name) / f"eq{self._count}.png"
        path.write_bytes(png)
        return str(path)

    def close(self) -> None:
        """Deletes the directory and everything in it."""
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None


def _inline_equation(equation: Equation, images: _InlineImages) -> str:
    """Paragraph markup for an inline equation: an `<img>` on the baseline, or the escaped source."""
    drawn = typeset(equation.tex, False)
    png = png_of(drawn) if drawn is not None else None
    if drawn is None or png is None:
        return safe(equation.text)
    path = html.escape(images.add(png), quote=True)
    return f'<img src="{path}" width="{drawn.width:.2f}" height="{drawn.height:.2f}" valign="{-drawn.descent:.2f}"/>'


def _styled_markup(run: Styled, *, bold: bool) -> str:
    """Paragraph markup for a bold / italic / code run: the escaped words inside the matching tags."""
    inner = safe(run.text, bold=bold or run.bold)
    if run.code:
        inner = f'<font face="Courier">{inner}</font>'
    if run.italic:
        inner = f"<i>{inner}</i>"
    if run.bold and not bold:
        inner = f"<b>{inner}</b>"
    if run.href:
        # A link was checked by `finalize_links`; its address is an escaped attribute value, never markup.
        inner = f'<a href="{html.escape(run.href, quote=True)}" color="#0563C1"><u>{inner}</u></a>'
    return inner


def _markup(value: str, images: _InlineImages, *, bold: bool = False) -> str:
    """Paragraph markup for model text: its runs escaped, its styles applied and its equations drawn inline."""
    return "".join(
        safe(run, bold=bold) if isinstance(run, str)
        else _styled_markup(run, bold=bold) if isinstance(run, Styled)
        else _inline_equation(run, images)
        for run in text_runs(value)
    )


def _list(items: list[str], images: _InlineImages, bullet_type: str) -> ListFlowable:
    """A bulleted (`"bullet"`) or numbered (`"1"`) list of marked-up items."""
    flowables: list[Any] = [ListItem(RlParagraph(_markup(item, images), STYLES["BodyText"])) for item in items]
    return ListFlowable(flowables, bulletType=bullet_type, bulletFormat="%s." if bullet_type == "1" else None)


def _display_equation(block: Equation, usable_width: float) -> list:
    """Flowables for a display equation: the centred vector drawing between small gaps, or its source."""
    drawn = typeset(block.tex, True)
    drawing = svg_flowable(drawn.svg, usable_width) if drawn is not None else None
    if drawing is None:
        return [RlParagraph(safe(block.text), STYLES["BodyText"])]
    drawing.hAlign = "CENTER"
    return [Spacer(1, 4), drawing, Spacer(1, 6)]


def _content_widths(block: Table, usable_width: float) -> list[float]:
    """Column widths for a table that gave none, sized from what each column holds.

    Equal widths split a record code (`ACME-PER-001`) across two lines in a table of a dozen
    columns. A column needs the width of its longest unbreakable word (measured in the cell font, so
    a code always fits on one line, up to a cap so a pasted unbroken string cannot claim the page) or,
    if more, its longest cell up to a cap, plus the cell padding.
    The spare width is shared in proportion to those needs; when the needs exceed the page they are
    scaled down together.

    Args:
        block: The table.
        usable_width: The width available between the margins, in points.

    Returns:
        One width per column, summing to `usable_width`.
    """
    needs = []
    for index, heading in enumerate(block.columns):
        cells = [str(row[index]) for row in block.rows if index < len(row)]
        words = max(
            (text_width(word, _CELL_FONT_SIZE, bold=True) for word in heading.split()), default=0.0,
        )
        words = max([words, *(text_width(word, _CELL_FONT_SIZE) for cell in cells for word in cell.split())])
        whole = max((text_width(cell, _CELL_FONT_SIZE) for cell in cells), default=0.0)
        needs.append(max(min(words, _MAX_WORD_POINTS), min(whole, _MAX_CELL_POINTS)) + _CELL_PADDING_POINTS)
    if sum(needs) >= usable_width:
        return [usable_width * need / sum(needs) for need in needs]
    spare = usable_width - sum(needs)
    return [need + spare * need / sum(needs) for need in needs]


def _table(block: Table, accent, usable_width: float, images: _InlineImages):
    """A block table as a styled ReportLab table (compact or plain grid)."""
    if block.col_widths_cm:
        widths = [w * cm for w in block.col_widths_cm]
    elif block.compact:
        widths = _content_widths(block, usable_width)
    else:
        widths = [usable_width / len(block.columns)] * len(block.columns)
    body_style = _CELL if block.compact else _PLAIN_CELL
    head_style = ParagraphStyle("report_head_text", parent=_HEAD, textColor=header_text_color(accent))
    data = [[RlParagraph(safe(c, bold=True), head_style) for c in block.columns]] if block.compact else [list(block.columns)]
    data += [
        [toned_paragraph(cell, body_style, block.tone_at(r, c), _markup(cell, images)) for c, cell in enumerate(row)]
        for r, row in enumerate(block.rows)
    ]
    return styled_table(data, col_widths=widths, accent_color=accent, compact=block.compact)


def render_pdf_document(document: ReportDocument) -> bytes:
    """Renders `document` as a PDF.

    Args:
        document: The neutral report.

    Returns:
        PDF bytes.
    """
    document = finalize_links(document)
    branding = document.branding
    accent = colors.HexColor((branding or ReportBranding(accent_color_hex=DEFAULT_ACCENT_COLOR_HEX)).accent_color_hex)
    page_cm = page_dimensions_cm(document)
    pagesize = (page_cm[0] * cm, page_cm[1] * cm)
    margins = _LANDSCAPE_MARGINS if document.landscape else _PORTRAIT_MARGINS
    usable_width = pagesize[0] - margins.get("leftMargin", 72) - margins.get("rightMargin", 72)

    story: list = title_flowables(document.title, branding)
    images = _InlineImages()
    for block in document.blocks:
        if isinstance(block, Heading):
            target = f'<a name="{html.escape(block.anchor, quote=True)}"/>' if block.anchor else ""
            story.append(RlParagraph(target + _markup(block.text, images, bold=True), STYLES[f"Heading{min(max(block.level, 1), 4)}"]))
        elif isinstance(block, Paragraph):
            story.append(RlParagraph(_markup(block.text, images), STYLES["BodyText"]))
        elif isinstance(block, Equation):
            story.extend(_display_equation(block, usable_width))
        elif isinstance(block, Note):
            story.append(RlParagraph(safe(block.text), _NOTE))
        elif isinstance(block, NumberedList):
            story.append(_list(block.items, images, "1"))
        elif isinstance(block, BulletList):
            story.append(_list(block.items, images, "bullet"))
        elif isinstance(block, Image):
            flowable = svg_flowable(block.svg, usable_width) if block.svg is not None else image_flowable(block.data)
            if flowable is not None:
                story.append(flowable)
        elif isinstance(block, Table):
            story.append(_table(block, accent, usable_width, images))
        elif isinstance(block, Gap):
            story.append(Spacer(1, block.cm * cm))
        elif isinstance(block, PageBreak):
            story.append(RlPageBreak())
    try:
        return build_pdf(
            story, footer_text=branding.footer_text if branding else None, pagesize=pagesize, title=document.title, **margins,
        )
    finally:
        images.close()
