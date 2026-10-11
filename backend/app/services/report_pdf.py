"""
Module: services.report_pdf

Renders a neutral `ReportDocument` (`services.report_model`) to PDF with
ReportLab. It is the only place block types are turned into flowables, so the
requirement report and every module report share one layout.

Design decisions:
- Every string goes through `report_document.safe` before reaching a
  `Paragraph` (ReportLab parses markup, so unescaped user text is an SSRF /
  local-file-read primitive; see that function's docstring).
- Page setup follows orientation: portrait is A4 with 2 cm top and bottom
  margins, landscape is A4 with 1.5 cm all round.

Dependencies: ReportLab, `services.report_document`, `services.report_model`.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
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
    image_flowable,
    safe,
    styled_table,
    title_flowables,
)
from app.services.report_model import (
    BulletList,
    Gap,
    Heading,
    Image,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Table,
)

_NOTE = ParagraphStyle("report_note", parent=STYLES["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
_CELL = ParagraphStyle("report_cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9.5)
_HEAD = ParagraphStyle("report_head", parent=_CELL, textColor=colors.white, fontName="Helvetica-Bold")
_PLAIN_CELL = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=8, leading=10)
_PORTRAIT_MARGINS = {"topMargin": 2 * cm, "bottomMargin": 2 * cm}
_LANDSCAPE_MARGINS = {"leftMargin": 1.5 * cm, "rightMargin": 1.5 * cm, "topMargin": 1.5 * cm, "bottomMargin": 1.5 * cm}


def _table(block: Table, accent, usable_width: float):
    """A block table as a styled ReportLab table (compact or plain grid)."""
    if block.col_widths_cm:
        widths = [w * cm for w in block.col_widths_cm]
    else:
        widths = [usable_width / len(block.columns)] * len(block.columns)
    if block.compact:
        data = [[RlParagraph(safe(c), _HEAD) for c in block.columns]]
        data += [[RlParagraph(safe(cell), _CELL) for cell in row] for row in block.rows]
    else:
        data = [list(block.columns)]
        data += [[RlParagraph(safe(cell), _PLAIN_CELL) for cell in row] for row in block.rows]
    return styled_table(data, col_widths=widths, accent_color=accent, compact=block.compact)


def render_pdf_document(document: ReportDocument) -> bytes:
    """Renders `document` as a PDF.

    Args:
        document: The neutral report.

    Returns:
        PDF bytes.
    """
    branding = document.branding
    accent = colors.HexColor((branding or ReportBranding(accent_color_hex=DEFAULT_ACCENT_COLOR_HEX)).accent_color_hex)
    pagesize = landscape(A4) if document.landscape else A4
    margins = _LANDSCAPE_MARGINS if document.landscape else _PORTRAIT_MARGINS
    usable_width = pagesize[0] - margins.get("leftMargin", 72) - margins.get("rightMargin", 72)

    story: list = title_flowables(document.title, branding)
    for block in document.blocks:
        if isinstance(block, Heading):
            story.append(RlParagraph(safe(block.text), STYLES[f"Heading{min(max(block.level, 1), 4)}"]))
        elif isinstance(block, Paragraph):
            story.append(RlParagraph(safe(block.text), STYLES["BodyText"]))
        elif isinstance(block, Note):
            story.append(RlParagraph(safe(block.text), _NOTE))
        elif isinstance(block, BulletList):
            story.append(ListFlowable([ListItem(RlParagraph(safe(i), STYLES["BodyText"])) for i in block.items], bulletType="bullet"))
        elif isinstance(block, Image):
            flowable = image_flowable(block.data)
            if flowable is not None:
                story.append(flowable)
        elif isinstance(block, Table):
            story.append(_table(block, accent, usable_width))
        elif isinstance(block, Gap):
            story.append(Spacer(1, block.cm * cm))
        elif isinstance(block, PageBreak):
            story.append(RlPageBreak())
    return build_pdf(
        story, footer_text=branding.footer_text if branding else None, pagesize=pagesize, title=document.title, **margins,
    )
