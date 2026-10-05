"""
Module: modules.context_strategy.report_render

Turns a collected `reports.ReportResult` into a downloadable PDF or CSV
(Module 1 Phase 12). Rendering is generic over `ReportSection`s, so a new
report needs no rendering code, and every figure in a file comes from the
same `ReportResult` the on-screen JSON uses.

Design decisions:
- The CSV is the report's first section only (its main table), the same
  "CSV is the flat export, PDF carries the full layout" split
  `modules.compliance.reports` uses. Every cell goes through `csv_safe` to
  neutralise spreadsheet formula injection, since cells hold user-entered
  titles and notes.
- Every PDF cell is XML-escaped before reaching a ReportLab `Paragraph`
  (user text could otherwise inject markup).

Dependencies: ReportLab, `app.services.csv_safety`, `app.services.branding`.
"""

from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.context_strategy.reports import ReportResult, ReportSection
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.csv_safety import csv_safe

_styles = getSampleStyleSheet()
_ACCENT = colors.HexColor(DEFAULT_ACCENT_COLOR_HEX)
_CELL = ParagraphStyle("cell", parent=_styles["BodyText"], fontSize=7.5, leading=9.5)
_HEAD = ParagraphStyle("head", parent=_CELL, textColor=colors.white, fontName="Helvetica-Bold")
_NOTE = ParagraphStyle("note", parent=_styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))


def render_csv(result: ReportResult) -> bytes:
    """Renders the report's main table (its first section) as UTF-8 CSV.

    Args:
        result: The collected report.

    Returns:
        CSV bytes with a header row; empty body rows when there is no data.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    main = result.sections[0] if result.sections else ReportSection("empty", "", [], [])
    writer.writerow([csv_safe(c) for c in main.columns])
    for row in main.rows:
        writer.writerow([csv_safe(c) for c in row])
    return buffer.getvalue().encode("utf-8")


def _table(section: ReportSection, width: float) -> Table:
    """Builds one section's table, equal-width columns with repeating header."""
    data = [[Paragraph(escape(c), _HEAD) for c in section.columns]]
    data += [[Paragraph(escape(cell), _CELL) for cell in row] for row in section.rows]
    table = Table(data, colWidths=[width / len(section.columns)] * len(section.columns), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    return table


def render_pdf(result: ReportResult) -> bytes:
    """Renders the whole report (every section) as a landscape A4 PDF.

    Args:
        result: The collected report.

    Returns:
        PDF bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
        bottomMargin=1.5 * cm, title=result.title,
    )
    width = landscape(A4)[0] - 3 * cm
    story = [
        Paragraph(escape(result.title), _styles["Title"]),
        Paragraph(escape(f"{result.scope_label} · generated {result.generated_at.strftime('%Y-%m-%d %H:%M')} UTC"), _NOTE),
        Spacer(1, 0.2 * cm),
    ]
    story += [Paragraph(escape(n), _NOTE) for n in result.notes]
    for section in result.sections:
        story += [Spacer(1, 0.4 * cm), Paragraph(escape(section.title), _styles["Heading2"])]
        if section.note:
            story.append(Paragraph(escape(section.note), _NOTE))
        story.append(_table(section, width) if section.rows else Paragraph("None.", _NOTE))
    doc.build(story)
    return buffer.getvalue()
