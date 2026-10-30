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
- Page setup follows the document's page style (paper, orientation, margins, gutter): one ReportLab page template per
  style, switched where a `PageStyleChange` falls. Mirrored margins give each style a right-hand and a left-hand
  template that alternate, and a style change picks the one that matches the parity of the page it starts on.

Dependencies: ReportLab, `services.report_document`, `services.report_fonts`, `services.report_math`,
`services.report_model`, `services.report_svg` (a figure given as SVG is drawn as vector).
"""

from __future__ import annotations

import html
import io
import tempfile
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import ActionFlowable, BaseDocTemplate, Frame, KeepTogether, ListFlowable, ListItem, PageTemplate, Spacer
from reportlab.platypus import PageBreak as RlPageBreak
from reportlab.platypus import Paragraph as RlParagraph

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_document import (
    STYLES,
    ReportBranding,
    header_text_color,
    image_flowable,
    safe,
    styled_table,
    title_flowables,
    toned_paragraph,
)
from app.services.report_fonts import draw_centred, text_width
from app.services.report_image_layout import placed_size_cm
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
    PageStyle,
    PageStyleChange,
    Paragraph,
    ReportDocument,
    Styled,
    Table,
    finalize_links,
    text_runs,
)
from app.services.report_svg import svg_flowable

_CAPTION_ALIGN: dict[str, Any] = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
_CAPTIONS = {
    align: ParagraphStyle(f"report_caption_{align}", parent=STYLES["BodyText"], fontSize=9, leading=12, alignment=value,
                          textColor=colors.HexColor("#444444"))
    for align, value in _CAPTION_ALIGN.items()
}
_NOTE = ParagraphStyle("report_note", parent=STYLES["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
_CELL = ParagraphStyle("report_cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9.5)
_HEAD = ParagraphStyle("report_head", parent=_CELL, fontName="Helvetica-Bold")
_PLAIN_CELL = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=8, leading=10)
_CELL_FONT_SIZE = 7.5
_MAX_CELL_POINTS = 70.0
_MAX_WORD_POINTS = 100.0  # a pasted unbroken string must not claim the page; ReportLab breaks it
_CELL_PADDING_POINTS = 14.0
_FOOTER_SIZE = 7
#: Where the footer text sits above the bottom edge, in points; kept inside a small bottom margin.
_FOOTER_BASELINE = 1 * cm


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


def _image_flowables(block: Image, usable_width: float) -> list:
    """An image block as flowables: the picture at its placed size and alignment, with its caption kept beside it.

    Returns `[]` when the picture cannot be drawn, so a bad image never breaks the report.
    """
    size = placed_size_cm(block, usable_width / cm)
    if size is None:
        return []
    width, height = size[0] * cm, size[1] * cm
    flowable: Any = svg_flowable(block.svg, width) if block.svg is not None else image_flowable(block.data)
    if flowable is None:
        return []
    if block.svg is not None and hasattr(flowable, "scale"):  # a vector drawing is scaled to the placed size
        flowable.scale(width / flowable.width, height / flowable.height)
        flowable.width, flowable.height = width, height
    else:
        flowable.drawWidth, flowable.drawHeight = width, height
    flowable.hAlign = block.align.upper()
    if not block.caption:
        return [flowable]
    caption = RlParagraph(safe(block.caption), _CAPTIONS.get(block.align, _CAPTIONS["center"]))
    return [KeepTogether([caption, flowable] if block.caption_above else [flowable, caption])]


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


class _UseStyle(ActionFlowable):
    """Selects the page templates for the pages that follow: one template, or the right- and left-hand pair of a mirrored
    style in turn, starting with the side that matches the parity of the next page (odd pages are right-hand)."""

    def __init__(self, recto: str, verso: str) -> None:
        super().__init__(("nextPageTemplate", recto))
        self.recto, self.verso = recto, verso

    def apply(self, doc) -> None:
        """Queues the template (or the alternating pair) for the page after the current one."""
        if self.recto == self.verso:
            doc.handle_nextPageTemplate(self.recto)
        else:
            doc.handle_nextPageTemplate([self.recto, self.verso] if (doc.page + 1) % 2 else [self.verso, self.recto])


def _template_ids(index: int, style: PageStyle) -> tuple[str, str]:
    """The (right-hand, left-hand) page template ids of style number `index`; both the same when margins do not mirror."""
    return (f"s{index}r", f"s{index}v" if style.mirror else f"s{index}r")


def _page_templates(styles: list[PageStyle], footer_text: str | None) -> list[PageTemplate]:
    """One page template per style (two when margins mirror), each with a frame inside its margins and the footer."""

    def draw_footer(canvas, doc_) -> None:
        if footer_text:
            canvas.saveState()
            draw_centred(canvas, canvas._pagesize[0] / 2, _FOOTER_BASELINE, footer_text, _FOOTER_SIZE)
            canvas.restoreState()

    templates: list[PageTemplate] = []
    for index, style in enumerate(styles):
        width, height = (side * cm for side in style.dimensions_cm)
        recto, verso = _template_ids(index, style)
        for template_id, is_verso in ((recto, False), (verso, True)):
            if is_verso and recto == verso:
                continue
            left, right = (edge * cm for edge in style.edges_cm(verso=is_verso))
            bottom = style.margins.bottom * cm
            frame = Frame(left, bottom, width - left - right, height - bottom - style.margins.top * cm, id=f"frame-{template_id}")
            templates.append(PageTemplate(id=template_id, frames=[frame], onPage=draw_footer, pagesize=(width, height)))
    return templates


def _build_pdf(story: list, styles: list[PageStyle], footer_text: str | None, title: str) -> bytes:
    """Builds the PDF: the first style's first page template starts the document.

    Args:
        story: The flowables.
        styles: Every page style the story uses; the document's own first.
        footer_text: Centred footer text, or `None`.
        title: The PDF's title.

    Returns:
        The PDF file content.
    """
    buffer = io.BytesIO()
    first = tuple(side * cm for side in styles[0].dimensions_cm)
    doc = BaseDocTemplate(buffer, pagesize=first, title=title)
    doc.addPageTemplates(_page_templates(styles, footer_text))
    doc.build(story)
    return buffer.getvalue()


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
    styles = [document.style]
    usable_width = document.style.usable_width_cm * cm

    story: list = [_UseStyle(*_template_ids(0, document.style)), *title_flowables(document.title, branding)]
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
            story.extend(_image_flowables(block, usable_width))
        elif isinstance(block, Table):
            story.append(_table(block, accent, usable_width, images))
        elif isinstance(block, Gap):
            story.append(Spacer(1, block.cm * cm))
        elif isinstance(block, PageBreak):
            story.append(RlPageBreak())
        elif isinstance(block, PageStyleChange):
            if block.style not in styles:
                styles.append(block.style)
            story += [_UseStyle(*_template_ids(styles.index(block.style), block.style)), RlPageBreak()]
            usable_width = block.style.usable_width_cm * cm
    try:
        return _build_pdf(story, styles, branding.footer_text if branding else None, document.title)
    finally:
        images.close()
