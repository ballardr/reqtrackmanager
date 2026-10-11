"""
Module: schemas.report

Request model for generated requirement reports (R-G-01, R-G-02, R-G-03,
R-G-04, R-F-01, R-F-02).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import RequirementStatus


class ReportRequest(BaseModel):
    """Options controlling generated report content.

    Attributes:
        format: Which output format to generate — `"pdf"` (R-F-01), `"docx"`
            (an editable Word file with the same content and branding as the
            PDF) or `"csv"` (R-F-02). `routers.reports.generate_report` dispatches
            on this instead of there being two separate endpoints (2026-09-22
            merge, see docs/decisions.md — one endpoint per resource, with
            the specific format as a parameter, so a future report-type/
            template parameter has one place to land rather than two).
        pre_markdown: Custom Markdown inserted at the beginning of the
            report, e.g. an introduction chapter (R-G-02).
        post_markdown: Custom Markdown appended at the end of the report,
            e.g. appendices (R-G-01).
        include_archived: Whether archived requirements are included.
        component_id / category_id / status / keyword: Optional filters on
            which requirements are included (R-G-03).
        resource_file_ids: Organisation shared resource files (C-M-03) to
            render as additional report sections, appended after the
            requirement table (R-G-04). Only text/markdown files can be
            rendered as text; other content types are noted but skipped.
        report_template_id: An optional selected `ReportTemplate` (R-G-05)
            to brand the PDF with (accent colour, cover page, footer, logo).
            Ignored for CSV exports, which have no branded layout.
        chapters_per_component: Per-generation override of whether the PDF
            chapters by component (`True`) or renders continuously
            (`False`) — `None` (the default) defers to the selected
            template's own setting, or — with no template — a heuristic
            (`services.reports.default_chapters_per_component`). Always
            wins over both when explicitly set. Ignored for CSV exports.
    """

    format: Literal["pdf", "csv", "docx"]
    pre_markdown: str = ""
    post_markdown: str = ""
    include_archived: bool = False
    component_id: UUID | None = None
    category_id: UUID | None = None
    status: RequirementStatus | None = None
    keyword: str | None = None
    resource_file_ids: list[UUID] = []
    report_template_id: UUID | None = None
    chapters_per_component: bool | None = None


class ReportChapter(BaseModel):
    title: str = Field(max_length=500)
    body: str = Field(default="", max_length=200_000)


class ReportContentEntry(BaseModel):
    """The introduction, chapters and appendices one scope holds for one report
    type (`models.report_content.ReportContent`). A blank entry is "inherit"
    and is not stored.

    Attributes:
        report_key: `"requirements"`, `"<module_key>.<report_key>"`, or `"*"`
            (every report without an entry of its own).
        intro: Markdown printed first.
        chapters: Chapters printed after the intro.
        appendices: Chapters printed after the report.
    """

    report_key: str = Field(min_length=1, max_length=100)
    intro: str = Field(default="", max_length=100_000)
    chapters: list[ReportChapter] = Field(default_factory=list, max_length=100)
    appendices: list[ReportChapter] = Field(default_factory=list, max_length=100)


class ProjectReportConfig(BaseModel):
    """A project's own report setup (the "Report Setup" tab): its default
    template and the content it owns, per report type. Inherited content is not
    included (`ReportContentSourceOut` / the effective-content endpoint
    describes it)."""

    default_report_template_id: UUID | None = None
    content: list[ReportContentEntry] = Field(default_factory=list, max_length=100)


class OrgReportDefaults(BaseModel):
    """Organisation-level default report content, per report type; a project
    falls back to it when it and its ancestors set nothing."""

    content: list[ReportContentEntry] = Field(default_factory=list, max_length=100)


class ReportContentSourceOut(BaseModel):
    """Where an effective value came from (`services.report_content.ContentSource`)."""

    scope_type: Literal["template", "project", "organization", "project_summary"]
    scope_id: UUID
    scope_name: str
    report_key: str


class EffectiveReportContentOut(BaseModel):
    """The content a report of one type would use, with where each field came
    from (`null` source = nothing set it). `report_key` echoes the request."""

    report_key: str
    intro: str = ""
    chapters: list[ReportChapter] = Field(default_factory=list)
    appendices: list[ReportChapter] = Field(default_factory=list)
    intro_source: ReportContentSourceOut | None = None
    chapters_source: ReportContentSourceOut | None = None
    appendices_source: ReportContentSourceOut | None = None
