"""
Module: schemas.report

Request model for generated requirement reports (R-G-01, R-G-02, R-G-03,
R-G-04, R-F-01, R-F-02).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RequirementStatus


class ReportRequest(BaseModel):
    """Options controlling generated report content.

    Attributes:
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
    """

    pre_markdown: str = ""
    post_markdown: str = ""
    include_archived: bool = False
    component_id: UUID | None = None
    category_id: UUID | None = None
    status: RequirementStatus | None = None
    keyword: str | None = None
    resource_file_ids: list[UUID] = []
    report_template_id: UUID | None = None


class ReportChapter(BaseModel):
    title: str
    body: str = ""


class ProjectReportConfig(BaseModel):
    """Persisted report structure (mock's "Report Setup"), used as the
    default report content when a generation request doesn't override it
    with ad-hoc pre_markdown/post_markdown."""

    intro: str = ""
    chapters: list[ReportChapter] = []
    appendices: list[ReportChapter] = []
