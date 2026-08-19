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
from itertools import groupby
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
from app.services.csv_safety import csv_safe
from app.services.labels import requirement_status_label

_md = MarkdownIt()
_styles = getSampleStyleSheet()


def resolve_report_config(project: Project, org: Organization) -> ProjectReportConfig:
    """Resolves a project's *effective* report intro/chapters/appendices —
    the project's own value if it's set anything, otherwise (intro only)
    the project's own description (`Project.summary`), otherwise the owning
    organisation's default (UI/UX pass), otherwise blank. Used both by the
    Report Setup editor (so an admin sees what will actually be used, not
    just what this project has explicitly overridden) and by
    `routers/reports.py::generate_pdf`'s own fallback when a generation
    request doesn't supply ad-hoc `pre_markdown`/`post_markdown`.

    Each of the three fields resolves independently — a project can
    customise just its intro and still inherit the organisation's default
    chapters, for instance. The description fallback exists only for intro:
    a project's summary is naturally introduction-shaped free text, but
    there's no equivalent project field to fall back to for chapters or
    appendices.
    """
    intro = project.report_intro or project.summary or org.default_report_intro or ""
    chapters = project.report_chapters or org.default_report_chapters or []
    appendices = project.report_appendices or org.default_report_appendices or []
    return ProjectReportConfig(
        intro=intro,
        chapters=[ReportChapter(**c) for c in chapters],
        appendices=[ReportChapter(**c) for c in appendices],
        intro_is_organisation_default=bool(not project.report_intro and not project.summary and org.default_report_intro),
        chapters_is_organisation_default=bool(not project.report_chapters and org.default_report_chapters),
        appendices_is_organisation_default=bool(not project.report_appendices and org.default_report_appendices),
        default_report_template_id=project.default_report_template_id,
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
        default_report_template_id=base.default_report_template_id,
    )


@dataclass
class ReportRequirementRow:
    """One requirement row included in a generated report.

    `component_sort_order`/`category_sort_order` mirror
    `ProjectComponent.sort_order`/`ProjectCategory.sort_order` (the same
    ordering the component/category tree UI uses) — `generate_pdf_report`
    groups rows into per-component chapters and per-category sub-sections
    using these, rather than the `unique_code`-sorted order this row list
    otherwise carries (which stays unique_code-sorted for the CSV export,
    `generate_csv_report`, unaffected by this).
    """

    unique_code: str
    name: str
    reasoning: str
    clarification: str
    status: str
    component_name: str
    category_name: str
    component_sort_order: int = 0
    category_sort_order: int = 0


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


def _group_rows_by_component_and_category(
    rows: list[ReportRequirementRow],
) -> list[tuple[str, list[tuple[str, list[ReportRequirementRow]]]]]:
    """Groups requirement rows into chapter-per-component, sub-section-per-
    category order for the PDF report (R-G's "chapters" concept, one level
    down from the intro/appendix chapters a project/org author writes by
    hand). Pulled out as its own pure function, separate from
    `generate_pdf_report`'s ReportLab flowable-building, so the actual
    grouping/ordering logic can be tested directly without parsing PDF
    bytes back out (no PDF-text-extraction dependency exists in this
    project's test suite, deliberately — see test_report_images.py).

    Ordered by `component_sort_order`/`category_sort_order` (matching the
    component/category tree UI's own ordering), not alphabetically or by
    `unique_code`; requirements within a category are ordered by
    `unique_code`. Grouped on `(sort_order, name)` rather than name alone:
    two components could in principle share a display name (uniqueness is
    only enforced on `(project_id, prefix)`), and colliding on sort_order
    too as well would be a genuine data anomaly, not a realistic case to
    guard further against.

    Returns:
        `[(component_name, [(category_name, [row, ...]), ...]), ...]`.
    """
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.component_sort_order, r.component_name, r.category_sort_order, r.category_name, r.unique_code),
    )
    chapters: list[tuple[str, list[tuple[str, list[ReportRequirementRow]]]]] = []
    for (_, component_name), component_rows_iter in groupby(sorted_rows, key=lambda r: (r.component_sort_order, r.component_name)):
        sections: list[tuple[str, list[ReportRequirementRow]]] = []
        for (_, category_name), category_rows_iter in groupby(
            component_rows_iter, key=lambda r: (r.category_sort_order, r.category_name)
        ):
            sections.append((category_name, list(category_rows_iter)))
        chapters.append((component_name, sections))
    return chapters


def default_chapters_per_component(rows: list[ReportRequirementRow]) -> bool:
    """The `chapters_per_component` default when neither a selected
    template nor an explicit per-generation choice sets it (see
    `ReportRequest.chapters_per_component`'s docstring for the full
    precedence): chaptered (`True`) unless some component in the report's
    scope has fewer than three requirements, in which case a continuous
    layout reads better than a near-empty chapter (a whole page break for
    one or two requirements). An empty report (no rows at all) defaults to
    chaptered — there's no sparse-chapter problem to avoid when there's
    nothing to chapter.
    """
    for _, sections in _group_rows_by_component_and_category(rows):
        count = sum(len(category_rows) for _, category_rows in sections)
        if count < 3:
            return False
    return True


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
    chapters_per_component: bool = True,
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
        chapters_per_component: When `True` (the default), each component
            gets its own chapter heading and starts on a fresh page, with a
            sub-section per category underneath. When `False`, the
            per-category headings and tables are unchanged but there's no
            component-level heading or forced page break — categories just
            flow continuously in component/category tree order. The
            caller (`routers/reports.py::generate_pdf`) resolves which of
            the two applies before calling this — see
            `default_chapters_per_component`'s docstring for that
            precedence.

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
    header = ["ID", "Name", "Reasoning", "Status"]

    def _requirement_table(category_rows: list[ReportRequirementRow]) -> Table:
        data = [header]
        for row in category_rows:
            data.append([
                Paragraph(_safe(row.unique_code), table_style), Paragraph(_safe(row.name), table_style),
                Paragraph(_safe(row.reasoning), table_style),
                Paragraph(_safe(requirement_status_label(row.status)), table_style),
            ])
        # Same total width (17.5cm) the single combined table used to sum
        # to — Component/Category no longer need their own columns (R-G's
        # chapter-per-component/section-per-category structure below
        # already conveys that), so their width goes to Name/Reasoning.
        table = Table(data, repeatRows=1, colWidths=[3 * cm, 5 * cm, 7.5 * cm, 2 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    # Chapter per component (each starting on its own page) with a
    # sub-section per category underneath when chapters_per_component,
    # otherwise just the category headings/tables flowing continuously
    # with no component heading or page break — see
    # _group_rows_by_component_and_category's docstring for the ordering
    # rules, which apply identically either way.
    for component_name, sections in _group_rows_by_component_and_category(rows):
        if chapters_per_component:
            story.append(PageBreak())
            story.append(Paragraph(_safe(component_name), _styles["Heading1"]))
            story.append(Spacer(1, 0.3 * cm))
        for category_name, category_rows in sections:
            story.append(Paragraph(_safe(category_name), _styles["Heading2"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(_requirement_table(category_rows))
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


def generate_csv_report(rows: list[ReportRequirementRow], terminology: dict[str, str] | None = None) -> bytes:
    """Builds a CSV export of requirement rows (R-F-02).

    Args:
        rows: The requirement rows to export.
        terminology: The owning project's terminology overrides (C-C-03),
            keyed by the fixed `TERMINOLOGY_KEYS` set. Used to render the
            "Component"/"Category" header cells in the project's own
            configured vocabulary instead of always the English default;
            every other header cell is a fixed report column, not one of
            the six overridable nouns, so it stays literal regardless of
            override. `None` (or a dict missing a key) falls back to the
            English default the same as an unset override would.

    Returns:
        The generated CSV file content as bytes.
    """
    terminology = terminology or {}
    component_label = (terminology.get("component") or "component").capitalize()
    category_label = (terminology.get("category") or "category").capitalize()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Name", component_label, category_label, "Status", "Reasoning", "Clarification"])
    for row in rows:
        writer.writerow([
            csv_safe(row.unique_code), csv_safe(row.name), csv_safe(row.component_name),
            csv_safe(row.category_name), csv_safe(requirement_status_label(row.status)), csv_safe(row.reasoning),
            csv_safe(row.clarification),
        ])
    return buffer.getvalue().encode("utf-8")
