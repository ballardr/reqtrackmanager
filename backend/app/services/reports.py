"""
Module: services.reports

Generates requirement reports as PDF (R-F-01) and CSV (R-F-02), with support
for custom Markdown content prepended/appended to the report (R-G-01,
R-G-02). PDF generation uses ReportLab (pure-Python, no system dependencies)
driven by a minimal Markdown-to-flowable renderer built on markdown-it-py,
covering headings, paragraphs, bullet lists, and images-on-their-own-line —
sufficient for introduction/appendix style report sections without pulling
in a full HTML rendering stack.

Image support (`![alt](attachment:<file id>)`, inserted via the report
content editor's attachment panel) is deliberately resolved from a
pre-fetched `images: dict[str, bytes]` mapping passed in by the caller,
never fetched by this module itself over HTTP or the filesystem — the exact
same "never let user-supplied markup reach out to a URL server-side"
reasoning `_safe`'s docstring documents for why raw `<img>`/`<font>` markup
is escaped rather than interpreted. `routers/reports.py::generate_pdf` is
responsible for resolving each reference to bytes *with an organisation
ownership check*, so this module never has to reason about tenant
isolation itself.
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
from reportlab.platypus import Image, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.schemas.report import ProjectReportConfig, ReportChapter
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.labels import requirement_status_label

_md = MarkdownIt()
_styles = getSampleStyleSheet()


def resolve_report_config(project: Project, org: Organization) -> ProjectReportConfig:
    """Resolves a project's *effective* report intro/chapters/appendices —
    the project's own value if it's set anything, otherwise the owning
    organisation's default (UI/UX pass), otherwise blank. Used both by the
    Report Setup editor (so an admin sees what will actually be used, not
    just what this project has explicitly overridden) and by
    `routers/reports.py::generate_pdf`'s own fallback when a generation
    request doesn't supply ad-hoc `pre_markdown`/`post_markdown`.

    Each of the three fields resolves independently — a project can
    customise just its intro and still inherit the organisation's default
    chapters, for instance.
    """
    intro = project.report_intro or org.default_report_intro or ""
    chapters = project.report_chapters or org.default_report_chapters or []
    appendices = project.report_appendices or org.default_report_appendices or []
    return ProjectReportConfig(
        intro=intro,
        chapters=[ReportChapter(**c) for c in chapters],
        appendices=[ReportChapter(**c) for c in appendices],
        intro_is_organisation_default=bool(not project.report_intro and org.default_report_intro),
        chapters_is_organisation_default=bool(not project.report_chapters and org.default_report_chapters),
        appendices_is_organisation_default=bool(not project.report_appendices and org.default_report_appendices),
    )


def resolve_report_config_with_template(
    project: Project, org: Organization, template: ReportTemplate | None
) -> ProjectReportConfig:
    """Like `resolve_report_config`, with one more, more-specific tier: a
    selected report template's own intro/chapters/appendices (if it set
    any) take precedence over the project/org-resolved content, per field
    independently — same "falls back if not set" shape as the two tiers
    below it. `template=None` (no template selected) is identical to
    calling `resolve_report_config` directly.
    """
    base = resolve_report_config(project, org)
    if template is None:
        return base
    intro = template.intro or base.intro
    chapters = [ReportChapter(**c) for c in template.chapters] if template.chapters else base.chapters
    appendices = [ReportChapter(**c) for c in template.appendices] if template.appendices else base.appendices
    return ProjectReportConfig(
        intro=intro, chapters=chapters, appendices=appendices,
        intro_is_organisation_default=bool(not template.intro and base.intro_is_organisation_default),
        chapters_is_organisation_default=bool(not template.chapters and base.chapters_is_organisation_default),
        appendices_is_organisation_default=bool(not template.appendices and base.appendices_is_organisation_default),
    )


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


_MAX_IMAGE_WIDTH = A4[0] - 4 * cm  # matches SimpleDocTemplate's leftMargin+rightMargin default (2cm each)


def _image_flowable(image_bytes: bytes):
    """Builds a page-width-constrained ReportLab `Image` flowable, or
    `None` if `image_bytes` isn't a decodable image — the same
    "a bad image must never break report generation" handling already used
    for the cover-page logo (see `generate_pdf_report` below)."""
    try:
        img = Image(io.BytesIO(image_bytes))
        if img.imageWidth > _MAX_IMAGE_WIDTH:
            scale = _MAX_IMAGE_WIDTH / float(img.imageWidth)
            img.drawWidth = _MAX_IMAGE_WIDTH
            img.drawHeight = img.imageHeight * scale
        return img
    except Exception:  # noqa: BLE001 - malformed/unsupported image content must never break report generation
        return None


def _markdown_to_flowables(markdown_text: str, images: dict[str, bytes] | None = None) -> list:
    """Converts a Markdown string into a list of ReportLab flowables.

    Args:
        markdown_text: The Markdown source.
        images: Maps an image reference (as it appears in
            `![alt](ref)`, e.g. `"attachment:<uuid>"`) to already-resolved
            image bytes. A paragraph consisting of *only* an image (the
            normal "image on its own line" Markdown shape) is rendered as
            a `reportlab.platypus.Image`; a reference missing from `images`
            (not resolved, wrong org, not actually an image) is skipped
            silently rather than failing report generation. Images mixed
            inline with other paragraph text are not supported — the
            paragraph falls back to its literal escaped text, matching this
            renderer's existing "match the supported subset, nothing more"
            scope (see module docstring).
    """
    flowables: list = []
    if not markdown_text.strip():
        return flowables
    images = images or {}

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
            inline = tokens[i + 1]
            image_children = [c for c in (inline.children or []) if c.type == "image"]
            if len(image_children) == 1 and len(inline.children) == 1:
                ref = image_children[0].attrs.get("src", "")
                image_bytes = images.get(ref)
                flowable = _image_flowable(image_bytes) if image_bytes else None
                if flowable is not None:
                    flowables.append(flowable)
                    flowables.append(Spacer(1, 0.2 * cm))
                # Missing/unresolvable reference: skip silently, no placeholder.
            else:
                text = _safe(inline.content)
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


@dataclass
class ReportBranding:
    """Optional per-report branding, sourced from an org's `ReportTemplate`
    (R-G-05). `generate_pdf_report` falls back to today's plain, unbranded
    styling when this is omitted entirely."""

    accent_color_hex: str = DEFAULT_ACCENT_COLOR_HEX
    include_cover_page: bool = False
    footer_text: str | None = None
    logo_bytes: bytes | None = None


def generate_pdf_report(
    *,
    project_name: str,
    pre_markdown: str,
    rows: list[ReportRequirementRow],
    post_markdown: str,
    branding: ReportBranding | None = None,
    images: dict[str, bytes] | None = None,
) -> bytes:
    """Builds a PDF report of a project's requirements.

    Args:
        project_name: The project's display name, used as the report title.
        pre_markdown: Custom Markdown rendered before the requirement table
            (R-G-02, e.g. an introduction).
        rows: The requirement rows to tabulate.
        post_markdown: Custom Markdown rendered after the requirement table
            (R-G-01, e.g. appendices).
        branding: Optional selected `ReportTemplate` styling (R-G-05) — an
            accent colour applied to the table header, an optional cover
            page (with the org logo if provided), and an optional footer.
        images: Pre-resolved `attachment:<id>` -> image bytes mapping for
            any images referenced in `pre_markdown`/`post_markdown` — see
            `_markdown_to_flowables`'s docstring.

    Returns:
        The generated PDF file content as bytes.
    """
    accent_color = colors.HexColor((branding or ReportBranding()).accent_color_hex)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story: list = []

    if branding and branding.include_cover_page:
        cover_style = ParagraphStyle("cover_title", parent=_styles["Title"], textColor=accent_color, fontSize=28)
        story.append(Spacer(1, 6 * cm))
        if branding.logo_bytes:
            try:
                story.append(Image(io.BytesIO(branding.logo_bytes), width=4 * cm, height=4 * cm, kind="proportional"))
                story.append(Spacer(1, 1 * cm))
            except Exception:  # noqa: BLE001 - a malformed/unsupported logo image must never break report generation
                pass
        story.append(Paragraph(_safe(project_name), cover_style))
        story.append(PageBreak())
        story.append(Spacer(1, 0.5 * cm))
    else:
        story.append(Paragraph(_safe(project_name), _styles["Title"]))
        story.append(Spacer(1, 0.5 * cm))

    story.extend(_markdown_to_flowables(pre_markdown, images))

    table_style = ParagraphStyle("cell", parent=_styles["BodyText"], fontSize=8, leading=10)
    header = ["ID", "Name", "Component", "Category", "Status", "Reasoning"]
    data = [header]
    for row in rows:
        data.append([
            Paragraph(_safe(row.unique_code), table_style), Paragraph(_safe(row.name), table_style),
            Paragraph(_safe(row.component_name), table_style), Paragraph(_safe(row.category_name), table_style),
            Paragraph(_safe(requirement_status_label(row.status)), table_style), Paragraph(_safe(row.reasoning), table_style),
        ])
    # ID (e.g. "AUTH-SEC-001") was wrapping mid-code at 2.2cm — widened to 3cm
    # (enough for the longest realistic code at this font size) and taken
    # from Reasoning, the widest column, so the table's total width is
    # unchanged.
    table = Table(data, repeatRows=1, colWidths=[3 * cm, 3.5 * cm, 2.3 * cm, 2.3 * cm, 2 * cm, 4.4 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.5 * cm))
    story.extend(_markdown_to_flowables(post_markdown, images))

    footer_text = branding.footer_text if branding else None

    def _draw_footer(canvas, doc_):
        if not footer_text:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(doc_.pagesize[0] / 2, 1 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralizes CSV formula/DDE injection (OWASP CSV injection).

    A cell starting with `=`, `+`, `-`, `@`, tab, or CR is interpreted as a
    formula by Excel/LibreOffice/Sheets when the file is opened — since
    these values come straight from user-editable requirement fields and
    this export exists specifically for spreadsheet review (R-F-02), a
    prefixed `'` (which spreadsheet apps strip from display but never
    execute) neutralizes it without altering how the value reads.
    """
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


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
            _csv_safe(row.unique_code), _csv_safe(row.name), _csv_safe(row.component_name),
            _csv_safe(row.category_name), _csv_safe(requirement_status_label(row.status)), _csv_safe(row.reasoning),
            _csv_safe(row.clarification),
        ])
    return buffer.getvalue().encode("utf-8")
