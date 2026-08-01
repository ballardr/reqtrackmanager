"""
Module: services.reports

Generates requirement reports as PDF (R-F-01) and CSV (R-F-02), with support
for custom Markdown content prepended/appended to the report (R-G-01,
R-G-02). PDF generation uses ReportLab (pure-Python, no system dependencies)
driven by a minimal Markdown-to-flowable renderer built on markdown-it-py,
covering headings, paragraphs, and bullet lists — sufficient for
introduction/appendix style report sections without pulling in a full HTML
rendering stack.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from xml.sax.saxutils import escape as _xml_escape

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_md = MarkdownIt()
_styles = getSampleStyleSheet()


@dataclass
class ReportRequirementRow:
    """One requirement row included in a generated report."""

    unique_code: str
    name: str
    reasoning: str
    clarification: str
    status: str
    component_name: str
    category_name: str


def _safe(text: str) -> str:
    """Escapes `&`/`<`/`>` before handing text to a ReportLab `Paragraph`.

    ReportLab's `Paragraph` does not treat its `text` argument as plain
    text — it parses a restricted markup language supporting tags such as
    `<b>`, `<font>`, and `<img src="...">`. Since report content (Markdown
    sections, requirement names/reasoning) is user-supplied, passing it to
    `Paragraph` unescaped would let a `<img src="http://internal-host/...">`
    (or a `file:`-scheme source, trusted by default in ReportLab < 5) be
    parsed as real markup and fetched server-side — an SSRF/local-file-read
    primitive triggerable by any project member generating a report.
    Escaping neutralises this: the text renders literally instead of being
    interpreted as markup.
    """
    return _xml_escape(text)


def _markdown_to_flowables(markdown_text: str) -> list:
    """Converts a Markdown string into a list of ReportLab flowables."""
    flowables: list = []
    if not markdown_text.strip():
        return flowables

    tokens = _md.parse(markdown_text)
    i = 0
    heading_styles = {
        "h1": _styles["Heading1"], "h2": _styles["Heading2"], "h3": _styles["Heading3"],
        "h4": _styles["Heading4"], "h5": _styles["Heading4"], "h6": _styles["Heading4"],
    }
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            text = _safe(tokens[i + 1].content)
            flowables.append(Paragraph(text, heading_styles.get(token.tag, _styles["Heading3"])))
            i += 3
        elif token.type == "paragraph_open":
            text = _safe(tokens[i + 1].content)
            flowables.append(Paragraph(text, _styles["BodyText"]))
            flowables.append(Spacer(1, 0.2 * cm))
            i += 3
        elif token.type == "bullet_list_open":
            items = []
            j = i + 1
            while tokens[j].type != "bullet_list_close":
                if tokens[j].type == "inline":
                    items.append(ListItem(Paragraph(_safe(tokens[j].content), _styles["BodyText"])))
                j += 1
            flowables.append(ListFlowable(items, bulletType="bullet"))
            i = j + 1
        else:
            i += 1
    return flowables


def generate_pdf_report(
    *, project_name: str, pre_markdown: str, rows: list[ReportRequirementRow], post_markdown: str
) -> bytes:
    """Builds a PDF report of a project's requirements.

    Args:
        project_name: The project's display name, used as the report title.
        pre_markdown: Custom Markdown rendered before the requirement table
            (R-G-02, e.g. an introduction).
        rows: The requirement rows to tabulate.
        post_markdown: Custom Markdown rendered after the requirement table
            (R-G-01, e.g. appendices).

    Returns:
        The generated PDF file content as bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story: list = [Paragraph(_safe(project_name), _styles["Title"]), Spacer(1, 0.5 * cm)]
    story.extend(_markdown_to_flowables(pre_markdown))

    table_style = ParagraphStyle("cell", parent=_styles["BodyText"], fontSize=8, leading=10)
    header = ["ID", "Name", "Component", "Category", "Status", "Reasoning"]
    data = [header]
    for row in rows:
        data.append([
            Paragraph(_safe(row.unique_code), table_style), Paragraph(_safe(row.name), table_style),
            Paragraph(_safe(row.component_name), table_style), Paragraph(_safe(row.category_name), table_style),
            Paragraph(_safe(row.status), table_style), Paragraph(_safe(row.reasoning), table_style),
        ])
    table = Table(data, repeatRows=1, colWidths=[2.2 * cm, 3.5 * cm, 2.3 * cm, 2.3 * cm, 2 * cm, 5.2 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.5 * cm))
    story.extend(_markdown_to_flowables(post_markdown))

    doc.build(story)
    return buffer.getvalue()


def generate_csv_report(rows: list[ReportRequirementRow]) -> bytes:
    """Builds a CSV export of requirement rows (R-F-02).

    Args:
        rows: The requirement rows to export.

    Returns:
        The generated CSV file content as bytes.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Name", "Component", "Category", "Status", "Reasoning", "Clarification"])
    for row in rows:
        writer.writerow([
            row.unique_code, row.name, row.component_name, row.category_name, row.status,
            row.reasoning, row.clarification,
        ])
    return buffer.getvalue().encode("utf-8")
