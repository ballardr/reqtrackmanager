"""
Module: services.reports

Generates requirement reports as PDF (R-F-01), DOCX and CSV (R-F-02), with support
for custom Markdown content prepended/appended to the report (R-G-01,
R-G-02). This module holds only what is specific to requirement reports:
`ReportRequirementRow`, grouping into component chapters and category
sections, the four-column table and the terminology-aware CSV. The
intro/chapters/appendices a report carries are resolved by
`services.report_content`. Everything document-level (branding,
cover page, footer, the Markdown renderer, image resolution, markup escaping)
lives in `services.report_document`, shared with every module's reports. The
report is built once as a neutral `ReportDocument` (`services.report_model`) and
rendered by `report_pdf` or `report_docx`, so the two formats cannot drift.

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

from app.services.csv_safety import csv_safe
from app.services.labels import REQUIREMENT_STATUS_TONE, requirement_status_label
from app.services.report_document import ReportBranding
from app.services.report_docx import render_docx_document
from app.services.report_model import Block, Gap, Heading, PageBreak, ReportDocument, Table, markdown_to_blocks
from app.services.report_pdf import render_pdf_document

__all__ = [
    "ReportBranding",
    "ReportRequirementRow",
    "build_requirement_document",
    "default_chapters_per_component",
    "generate_csv_report",
    "generate_docx_report",
    "generate_pdf_report",
]


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
    tags: str = ""


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


def build_requirement_document(
    *,
    project_name: str,
    pre_markdown: str,
    rows: list[ReportRequirementRow],
    post_markdown: str,
    branding: ReportBranding | None = None,
    images: dict[str, bytes] | None = None,
    chapters_per_component: bool = True,
    placeholders: dict[str, str] | None = None,
) -> ReportDocument:
    """Builds the neutral document for a project's requirements report, which
    the PDF and DOCX renderers both consume.

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
            `report_model.markdown_to_blocks`'s docstring.
        chapters_per_component: When `True` (the default), each component
            gets its own chapter heading and starts on a fresh page, with a
            sub-section per category underneath. When `False`, the
            per-category headings and tables are unchanged but there's no
            component-level heading or forced page break — categories just
            flow continuously in component/category tree order. The
            caller (`routers/reports.py::generate_report`) resolves which of
            the two applies before calling this — see
            `default_chapters_per_component`'s docstring for that
            precedence.
        placeholders: Values for the `{{...}}` placeholders in the pre/post
            Markdown (`report_content.build_placeholders`).

    Returns:
        The portrait requirements document.
    """
    blocks: list[Block] = list(markdown_to_blocks(pre_markdown, images, placeholders))
    # Same total width (17.5cm) the single combined table used to sum to —
    # Component/Category don't need their own columns (the chapter-per-component /
    # section-per-category structure below already conveys them), so their
    # width goes to Name/Reasoning.
    widths = [3, 4.5, 6, 2, 2]
    header = ["ID", "Name", "Reasoning", "Status", "Tags"]

    # Chapter per component (each starting on its own page) with a sub-section
    # per category underneath when chapters_per_component, otherwise just the
    # category headings/tables flowing continuously — see
    # _group_rows_by_component_and_category's docstring for the ordering rules,
    # which apply identically either way.
    for component_name, sections in _group_rows_by_component_and_category(rows):
        if chapters_per_component:
            blocks += [PageBreak(), Heading(component_name, 1), Gap(0.3)]
        for category_name, category_rows in sections:
            blocks += [
                Heading(category_name, 2), Gap(0.2),
                Table(
                    header,
                    [[r.unique_code, r.name, r.reasoning, requirement_status_label(r.status), r.tags] for r in category_rows],
                    col_widths_cm=widths,
                    # The Status cell takes the badge colour the screen gives that status.
                    tones=[[None, None, None, REQUIREMENT_STATUS_TONE.get(r.status), None] for r in category_rows],
                ),
                Gap(0.5),
            ]

    blocks += markdown_to_blocks(post_markdown, images, placeholders)
    return ReportDocument(title=project_name, blocks=blocks, branding=branding)


def generate_pdf_report(**kwargs) -> bytes:
    """Builds a PDF report of a project's requirements.

    Args:
        **kwargs: As for `build_requirement_document`.

    Returns:
        The generated PDF file content as bytes.
    """
    return render_pdf_document(build_requirement_document(**kwargs))


def generate_docx_report(**kwargs) -> bytes:
    """Builds an editable Word (DOCX) report of a project's requirements.

    Args:
        **kwargs: As for `build_requirement_document`.

    Returns:
        The generated DOCX file content as bytes.
    """
    return render_docx_document(build_requirement_document(**kwargs))


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
    writer.writerow(["ID", "Name", component_label, category_label, "Status", "Reasoning", "Clarification", "Tags"])
    for row in rows:
        writer.writerow([
            csv_safe(row.unique_code), csv_safe(row.name), csv_safe(row.component_name),
            csv_safe(row.category_name), csv_safe(requirement_status_label(row.status)), csv_safe(row.reasoning),
            csv_safe(row.clarification), csv_safe(row.tags),
        ])
    return buffer.getvalue().encode("utf-8")
