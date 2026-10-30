"""
Module: modules.compliance.report_files

Every file format of the two compliance reports (project and organisation), behind one function each.

- PDF and CSV keep their dedicated writers in `reports.py` (the PDF's requirement cell is a multi-line narrative the
  neutral model's single-line cells cannot hold).
- Word, OpenDocument text and HTML are rendered from a neutral `ReportDocument` built here with the same sections as
  the PDF (the main table, then the evidence, review and mapping appendices, or the organisation drill-downs).
- Excel and OpenDocument spreadsheet are rendered from one `Sheet` holding the same main table as the CSV
  (`project_compliance_table` / `org_compliance_table`), so the three table formats cannot drift apart.

Design decisions:
- The router takes the format as `ComplianceReportFormat`; `backend/tests/test_report_download_surfaces.py` fails when
  a registered renderer is missing from it without a stated reason.
- A requirement's narrative (path, title, reasoning, clarification, justification, notes) is one cell of bold-labelled
  runs separated by " · ", because the neutral model's cells are single-line.
- No branding template is applied: the PDF never had one, and the formats must read the same.

Dependencies: `services.report_render` (renderers), `services.report_model` (blocks), `services.downloads`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import Response

from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import FAMILY_DOCUMENT, FAMILY_TABLE
from app.modules.compliance.labels import COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE
from app.modules.compliance.reports import (
    ComplianceReportRequirementRow,
    OrgComplianceReportData,
    ProjectComplianceReportData,
    _org_report_empty_message,
    _project_report_empty_message,
    org_compliance_table,
    project_compliance_table,
)
from app.services.downloads import file_response, filename_safe
from app.services.report_file_names import org_default_stem
from app.services.report_model import Block, Heading, MathText, PageBreak, ReportDocument, Sheet, Styled, Table
from app.services.report_model import Paragraph as ModelParagraph
from app.services.report_render import RenderInput, render

#: The formats a compliance report is offered in (the query parameter's type).
ComplianceReportFormat = Literal["pdf", "docx", "odt", "html", "csv", "xlsx", "ods"]
#: A compliance report's formats that come from the neutral document.
_DOCUMENT_FORMATS = ("docx", "odt", "html")
#: …and from the sheet.
_SHEET_FORMATS = ("xlsx", "ods")

_SEPARATOR = " · "


def _narrative(row: ComplianceReportRequirementRow) -> MathText:
    """One requirement as a single cell: the section path (italic), the title (bold), then each present free-text
    field behind its bold label. A field the requirement does not have is left out, as in the PDF."""
    parts: list[str | Styled] = []
    if row.ancestor_path:
        parts += [Styled(row.ancestor_path, italic=True), _SEPARATOR]
    title = f"{row.requirement_reference} {row.requirement_name}".strip() if row.requirement_reference else row.requirement_name
    parts.append(Styled(title, bold=True))
    for label, value in (
        ("Reasoning", row.requirement_reasoning), ("Description", row.requirement_description),
        ("Clarification", row.requirement_clarification), ("Justification", row.justification), ("Notes", row.notes),
    ):
        if value:
            parts += [_SEPARATOR, Styled(f"{label}:", bold=True), f" {value}"]
    return MathText(parts)


def _table(columns: list[str], rows: list[list[str]], widths: list[float], tones: list[list[str | None]] | None = None) -> Table:
    return Table(columns=columns, rows=rows, col_widths_cm=widths, compact=True, tones=tones)


def _validity_tones(width: int, column: int, validity_state: str) -> list[str | None]:
    """One body row's tones: the evidence validity badge's tone in `column`, none elsewhere."""
    tones: list[str | None] = [None] * width
    tones[column] = COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE.get(validity_state)
    return tones


def _section(title: str, table: Table) -> list[Block]:
    return [PageBreak(), Heading(title, 1), table]


def project_compliance_document(project_name: str, data: ProjectComplianceReportData) -> ReportDocument:
    """The project report as a neutral document: the main table, then the evidence register, review history and
    cross-standard mappings (each omitted when empty).

    Args:
        project_name: The project's name (for the title).
        data: What `collect_project_compliance_report` gathered.
    """
    blocks: list[Block] = []
    if not data.requirement_rows:
        blocks.append(ModelParagraph(_project_report_empty_message(data)))
    else:
        blocks.append(_table(
            ["Standard", "Requirement", "Applicability", "Status", "Approval", "Actions", "Evidence"],
            [[
                f"{r.standard_reference} v{r.version_label}", _narrative(r),
                f"{r.effective_applicability} ({r.applicability_source})" if r.applicability_source != "Explicit" else r.effective_applicability,
                r.compliance_status, r.approval_state, r.required_actions_summary, r.evidence_titles,
            ] for r in data.requirement_rows],
            [3.2, 9.5, 2.8, 2.4, 2.4, 3.2, 3.4],
        ))
    if data.evidence_rows:
        blocks += _section("Evidence Register", _table(
            ["Code", "Title", "Issuing organisation", "Issued", "Expiry", "Validity", "Provided by", "Linked to", "Archived", "Tags"],
            [[
                e.code, e.title, e.issuing_organisation, e.issued_date, e.expiry_date, e.validity_state.replace("_", " ").title(),
                e.provided_by_email, str(e.linked_requirement_count), "Yes" if e.is_archived else "No", e.tags,
            ] for e in data.evidence_rows],
            [2.2, 4.4, 3.2, 2.2, 2.2, 2.2, 3.6, 1.6, 1.8, 2.6],
            tones=[_validity_tones(10, 5, e.validity_state) for e in data.evidence_rows],
        ))
    if data.review_rows:
        blocks += _section("Review History", _table(
            ["Scope", "Frequency", "Next due", "Status", "Schedule", "Outcome", "Completed", "Completed by"],
            [[
                rv.scope, rv.frequency_label, rv.next_due_date, rv.status, rv.schedule_state, rv.outcome,
                rv.completed_at, rv.completed_by_email,
            ] for rv in data.review_rows],
            [4.4, 2.6, 2.6, 2.6, 2.6, 3.2, 3.2, 4.6],
        ))
    if data.mapping_rows:
        blocks += _section("Cross-Standard Mappings", _table(
            ["From", "Relationship", "To", "Notes"],
            [[m.from_label, m.relationship_type, m.to_label, m.notes] for m in data.mapping_rows],
            [8.0, 3.6, 8.0, 6.0],
        ))
    return ReportDocument(title=f"{project_name} — Compliance Report", blocks=blocks, landscape=True)


def org_compliance_document(org_name: str, data: OrgComplianceReportData) -> ReportDocument:
    """The organisation roll-up as a neutral document: the main table, then the non-compliant, pending-approval and
    expiring-evidence drill-downs across every project (each omitted when empty).

    Args:
        org_name: The organisation's name (for the title).
        data: What `collect_org_compliance_report` gathered.
    """
    blocks: list[Block] = []
    if not data.assignment_rows:
        blocks.append(ModelParagraph(_org_report_empty_message(data)))
    else:
        blocks.append(_table(
            ["Project", "Standard", "Compliance %", "Overall status", "Approval status", "Non-compliant", "Target date"],
            [[
                a.project_name, f"{a.standard_reference} v{a.version_label}", f"{a.compliance_percentage:.1f}%",
                a.overall_compliance_state, a.overall_approval_state, str(a.non_compliant_count), a.target_compliance_date,
            ] for a in data.assignment_rows],
            [5.0, 5.0, 2.6, 3.6, 3.6, 2.8, 3.0],
        ))
    if data.non_compliant_rows:
        blocks += _section("Non-Compliant Requirements", _table(
            ["Project", "Standard", "Requirement"],
            [[p, f"{r.standard_reference} v{r.version_label}", _narrative(r)] for p, r in data.non_compliant_rows],
            [4.4, 4.4, 17.0],
        ))
    if data.pending_approval_rows:
        blocks += _section("Pending Approvals", _table(
            ["Project", "Standard", "Requirement", "Status"],
            [[p, f"{r.standard_reference} v{r.version_label}", _narrative(r), r.compliance_status] for p, r in data.pending_approval_rows],
            [4.4, 4.4, 13.0, 4.0],
        ))
    if data.expiring_evidence_rows:
        blocks += _section("Expiring/Expired Evidence", _table(
            ["Project", "Code", "Title", "Expiry", "Validity", "Tags"],
            [[p, e.code, e.title, e.expiry_date, e.validity_state.replace("_", " ").title(), e.tags] for p, e in data.expiring_evidence_rows],
            [4.4, 3.0, 8.0, 3.0, 3.0, 4.4],
            tones=[_validity_tones(6, 4, e.validity_state) for _p, e in data.expiring_evidence_rows],
        ))
    return ReportDocument(title=f"{org_name} — Organisation Compliance Report", blocks=blocks, landscape=True)


def compliance_report_response(
    fmt: ComplianceReportFormat,
    owner_name: str,
    fallback: str,
    organization: Organization,
    project: Project | None,
    *,
    pdf: Callable[[], bytes],
    csv: Callable[[], bytes],
    document: Callable[[], ReportDocument],
    table: Callable[[], tuple[list[str], list[list[str]]]],
) -> Response:
    """The compliance report as a download in `fmt`.

    The builders are callables so only the one the format needs runs.

    Args:
        fmt: One of `ComplianceReportFormat`.
        owner_name: The project's or organisation's name (the file name's start).
        fallback: The file-name stem used when the name has no safe characters.
        organization: The organisation, whose default file name template names the file when it sets one.
        project: The project reported on, or `None` for the organisation-wide report.
        pdf: Builds the PDF.
        csv: Builds the CSV.
        document: Builds the neutral document (Word, OpenDocument text, HTML).
        table: Builds the main table (Excel, OpenDocument spreadsheet) as a header and rows.

    Returns:
        The file response.
    """
    def stem_for(extension: str) -> str:
        return org_default_stem(
            organization, project, title="Compliance report", extension=extension,
            fallback=f"{filename_safe(owner_name, fallback=fallback)}-compliance-report",
        )

    if fmt == "pdf":
        return file_response(pdf(), stem_for("pdf"), "pdf")
    if fmt == "csv":
        return file_response(csv(), stem_for("csv"), "csv")
    if fmt in _DOCUMENT_FORMATS:
        built = document()
        rendered = render(fmt, FAMILY_DOCUMENT, RenderInput(title=built.title, document=built))
    else:
        columns, rows = table()
        sheet = Sheet(name="Compliance", columns=columns, rows=rows)
        rendered = render(fmt, FAMILY_TABLE, RenderInput(title=sheet.name, sheets=[sheet]))
    return file_response(rendered.content, stem_for(rendered.extension), rendered.extension)


def project_report_response(
    fmt: ComplianceReportFormat, project: Project, organization: Organization, data: ProjectComplianceReportData, *,
    pdf: Callable[[], bytes], csv: Callable[[], bytes],
) -> Response:
    """The project compliance report in `fmt` (see `compliance_report_response`)."""
    return compliance_report_response(
        fmt, project.name, "project", organization, project, pdf=pdf, csv=csv,
        document=lambda: project_compliance_document(project.name, data), table=lambda: project_compliance_table(data),
    )


def org_report_response(
    fmt: ComplianceReportFormat, organization: Organization, data: OrgComplianceReportData, *,
    pdf: Callable[[], bytes], csv: Callable[[], bytes],
) -> Response:
    """The organisation compliance report in `fmt` (see `compliance_report_response`)."""
    return compliance_report_response(
        fmt, organization.name, "organisation", organization, None, pdf=pdf, csv=csv,
        document=lambda: org_compliance_document(organization.name, data), table=lambda: org_compliance_table(data),
    )


__all__ = [
    "ComplianceReportFormat", "compliance_report_response", "org_compliance_document", "org_report_response",
    "project_compliance_document", "project_report_response",
]
