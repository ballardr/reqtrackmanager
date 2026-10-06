"""
Module: services.reports

Generates requirement reports as PDF (R-F-01) and CSV (R-F-02), with support
for custom Markdown content prepended/appended to the report (R-G-01,
R-G-02). This module holds only what is specific to requirement reports:
`ReportRequirementRow`, grouping into component chapters and category
sections, the four-column table, the terminology-aware CSV, and the effective
intro/chapters/appendices resolution. Everything document-level (branding,
cover page, footer, the Markdown renderer, image resolution, markup escaping)
lives in `services.report_document`, shared with every module's reports.

Image support (`![alt](attachment:<file id>)`, inserted via the report
content editor's attachment panel) is deliberately resolved from a
pre-fetched `images: dict[str, bytes]` mapping passed in by the caller —
see `report_document.resolve_report_images` for the tenant-isolation check
that runs before any image reaches the PDF.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from itertools import groupby

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.schemas.report import ProjectReportConfig, ReportChapter
from app.services.csv_safety import csv_safe
from app.services.labels import requirement_status_label
from app.services.report_document import (
    STYLES,
    ReportBranding,
    build_pdf,
    markdown_to_flowables,
    safe,
    styled_table,
    title_flowables,
)

__all__ = [
    "ReportBranding",
    "ReportRequirementRow",
    "default_chapters_per_component",
    "generate_csv_report",
    "generate_pdf_report",
    "resolve_report_config",
    "resolve_report_config_with_template",
]


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
            `report_document.markdown_to_flowables`'s docstring.
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
    story: list = title_flowables(project_name, branding)
    story.extend(markdown_to_flowables(pre_markdown, images))

    table_style = ParagraphStyle("cell", parent=STYLES["BodyText"], fontSize=8, leading=10)
    header = ["ID", "Name", "Reasoning", "Status"]

    def _requirement_table(category_rows: list[ReportRequirementRow]):
        data = [header]
        for row in category_rows:
            data.append([
                Paragraph(safe(row.unique_code), table_style), Paragraph(safe(row.name), table_style),
                Paragraph(safe(row.reasoning), table_style),
                Paragraph(safe(requirement_status_label(row.status)), table_style),
            ])
        # Same total width (17.5cm) the single combined table used to sum
        # to — Component/Category no longer need their own columns (R-G's
        # chapter-per-component/section-per-category structure below
        # already conveys that), so their width goes to Name/Reasoning.
        return styled_table(data, col_widths=[3 * cm, 5 * cm, 7.5 * cm, 2 * cm], accent_color=accent_color)

    # Chapter per component (each starting on its own page) with a
    # sub-section per category underneath when chapters_per_component,
    # otherwise just the category headings/tables flowing continuously
    # with no component heading or page break — see
    # _group_rows_by_component_and_category's docstring for the ordering
    # rules, which apply identically either way.
    for component_name, sections in _group_rows_by_component_and_category(rows):
        if chapters_per_component:
            story.append(PageBreak())
            story.append(Paragraph(safe(component_name), STYLES["Heading1"]))
            story.append(Spacer(1, 0.3 * cm))
        for category_name, category_rows in sections:
            story.append(Paragraph(safe(category_name), STYLES["Heading2"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(_requirement_table(category_rows))
            story.append(Spacer(1, 0.5 * cm))

    story.extend(markdown_to_flowables(post_markdown, images))
    return build_pdf(
        story, footer_text=branding.footer_text if branding else None, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm,
    )


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
