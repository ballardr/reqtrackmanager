"""
Module: services.reports

Generates requirement reports as PDF (R-F-01), DOCX and CSV (R-F-02), with the organisation's shared resource files
appended as Markdown sections (R-G-04).

Responsibilities:
- Requirement-specific parts only: `ReportRequirementRow`, grouping into component chapters and category sections, the
  five-column table and the terminology-aware CSV. Document-level parts (branding, cover, footer, Markdown, image
  resolution, escaping) are in `services.report_document`.

Design decisions:
- The report is built once as a neutral `ReportDocument` (`services.report_model`) and rendered by `report_pdf` or
  `report_docx`, so the formats cannot drift.
- Resource images (`![alt](attachment:<file id>)`) come from a pre-fetched `images: dict[str, bytes]` the caller passes;
  `report_document.resolve_report_images` does the tenant check first.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from itertools import groupby

from app.models.report_layout import FAMILY_TABLE
from app.services.csv_safety import csv_safe
from app.services.labels import REQUIREMENT_STATUS_TONE, requirement_status_label
from app.services.report_diagram import DiagramBudget
from app.services.report_document import ReportBranding
from app.services.report_docx import render_docx_document
from app.services.report_html import render_html_document
from app.services.report_model import Block, Gap, Heading, PageBreak, ReportDocument, Sheet, Table, markdown_to_blocks
from app.services.report_odt import render_odt_document
from app.services.report_pdf import render_pdf_document
from app.services.report_render import RenderInput, render

__all__ = [
    "ReportBranding",
    "ReportRequirementRow",
    "build_requirement_document",
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
    # The code of the requirement's own place when this row is one of its further places (an alias), so the entry
    # reads "Same as REQ-001"; empty for the requirement's own place.
    same_as: str = ""


def _group_rows_by_component_and_category(
    rows: list[ReportRequirementRow],
) -> list[tuple[str, list[tuple[str, list[ReportRequirementRow]]]]]:
    """Groups requirement rows into a chapter per component and a sub-section per category, in order, for the PDF report.

    A pure function, separate from the ReportLab flowable building, so the grouping can be tested without parsing PDF bytes.
    Ordering is by `component_sort_order` and `category_sort_order` (the tree UI's order), then `unique_code` within a
    category. Grouping is on `(sort_order, name)` because two components may share a display name (uniqueness is only on
    `(project_id, prefix)`).

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


def build_requirement_document(
    *,
    project_name: str,
    rows: list[ReportRequirementRow],
    post_markdown: str,
    branding: ReportBranding | None = None,
    images: dict[str, bytes] | None = None,
    chapters_per_component: bool = True,
) -> ReportDocument:
    """Builds the neutral document for a project's requirements report, consumed by the PDF and DOCX renderers.

    Args:
        project_name: The project's display name, used as the report title.
        rows: The requirement rows to tabulate.
        post_markdown: Markdown rendered after the requirement table (the selected resource files, R-G-04).
        branding: Optional organisation report look (R-G-05): table header accent, cover page and footer.
        images: Pre-resolved `attachment:<id>` to image bytes for images in `post_markdown`
            (see `report_model.markdown_to_blocks`). A Mermaid block is drawn when the converter service is
            configured, else printed as its source.
        chapters_per_component: When `True`, each component is a chapter starting on a new page with a sub-section per
            category. When `False`, categories flow continuously in tree order with no component heading or page break.
            The caller resolves the request's choice, else the organisation's setting.

    Returns:
        The portrait requirements document.
    """
    blocks: list[Block] = []
    # Total width 17.5 cm; the chapter and section headings convey component and category, so no columns for them.
    widths = [3, 4.5, 6, 2, 2]
    header = ["ID", "Name", "Reasoning", "Status", "Tags"]

    # A chapter per component when chapters_per_component, else categories flow continuously; same ordering either way.
    for component_name, sections in _group_rows_by_component_and_category(rows):
        if chapters_per_component:
            blocks += [PageBreak(), Heading(component_name, 1), Gap(0.3)]
        for category_name, category_rows in sections:
            blocks += [
                Heading(category_name, 2), Gap(0.2),
                Table(
                    header,
                    [
                        [
                            r.unique_code, f"{r.name} (same as {r.same_as})" if r.same_as else r.name, r.reasoning,
                            requirement_status_label(r.status), r.tags,
                        ]
                        for r in category_rows
                    ],
                    col_widths_cm=widths,
                    # The Status cell takes the badge colour the screen gives that status.
                    tones=[[None, None, None, REQUIREMENT_STATUS_TONE.get(r.status), None] for r in category_rows],
                ),
                Gap(0.5),
            ]

    blocks += markdown_to_blocks(post_markdown, images, diagrams=DiagramBudget())
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


def generate_odt_report(**kwargs) -> bytes:
    """Builds an OpenDocument text report of a project's requirements.

    Args:
        **kwargs: As for `build_requirement_document`.

    Returns:
        The generated ODT file content as bytes.
    """
    return render_odt_document(build_requirement_document(**kwargs))


def generate_html_report(**kwargs) -> bytes:
    """Builds a standalone HTML report of a project's requirements.

    Args:
        **kwargs: As for `build_requirement_document`.

    Returns:
        The generated HTML page as bytes.
    """
    return render_html_document(build_requirement_document(**kwargs))


def requirement_table(rows: list[ReportRequirementRow], terminology: dict[str, str] | None = None) -> tuple[list[str], list[list[str]]]:
    """The requirement rows as a header and plain-text rows: the table behind the CSV, Excel and OpenDocument
    spreadsheet exports (R-F-02), so their columns cannot drift. Cells are not yet guarded against spreadsheet
    formulas; each writer does that.

    Args:
        rows: The requirement rows to export.
        terminology: The project's terminology overrides (C-C-03); renders the "Component"/"Category" header cells in
            the project's own words. `None`, or a missing key, gives the English default.

    Returns:
        `(header, body rows)`.
    """
    terminology = terminology or {}
    component_label = (terminology.get("component") or "component").capitalize()
    category_label = (terminology.get("category") or "category").capitalize()
    header = ["ID", "Name", component_label, category_label, "Status", "Reasoning", "Clarification", "Tags"]
    body = [[
        row.unique_code, row.name, row.component_name, row.category_name, requirement_status_label(row.status),
        row.reasoning, row.clarification, row.tags,
    ] for row in rows]
    if any(row.same_as for row in rows):
        # Only a report that lists a requirement under more than one place needs the cross-reference column.
        header.append("Same as")
        for row, cells in zip(rows, body, strict=True):
            cells.append(row.same_as)
    return header, body


def generate_sheet_report(
    fmt: str, rows: list[ReportRequirementRow], title: str, terminology: dict[str, str] | None = None,
) -> bytes:
    """Builds an Excel (`xlsx`) or OpenDocument spreadsheet (`ods`) export of requirement rows.

    Args:
        fmt: `xlsx` or `ods`.
        rows: The requirement rows to export.
        title: The workbook title.
        terminology: As for `requirement_table`.

    Returns:
        The workbook bytes.

    Raises:
        KeyError: `fmt` is not a table-family format.
    """
    header, body = requirement_table(rows, terminology)
    sheet = Sheet(name="Requirements", columns=header, rows=body)
    return render(fmt, FAMILY_TABLE, RenderInput(title=title, sheets=[sheet])).content


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
    header, body = requirement_table(rows, terminology)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in body:
        writer.writerow([csv_safe(cell) for cell in row])
    return buffer.getvalue().encode("utf-8")
