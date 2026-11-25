"""
Module: schemas.report

Request model for generated requirement reports (R-G-03,
R-G-04, R-F-01, R-F-02).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RequirementStatus


class ReportRequest(BaseModel):
    """Options controlling generated report content.

    Attributes:
        format: Which output format to generate — `"pdf"` (R-F-01), `"docx"`
            (an editable Word file with the same content and branding as the
            PDF), `"odt"` and `"html"` (the same document), or the flat table as `"csv"`, `"xlsx"` or `"ods"` (R-F-02).
            `routers.reports.generate_report` dispatches on this: one endpoint
            per resource, with the format as a parameter.
        include_archived: Whether archived requirements are included.
        component_id / category_id / status / keyword: Optional filters on
            which requirements are included (R-G-03).
        primary_places_only: When `False` (the default) a requirement that sits in further components and categories
            is listed under each place with that place's own code and a "Same as" reference to its own code; when
            `True` it is listed once, under its own place, so a document does not repeat its text.
        resource_file_ids: Organisation shared resource files (C-M-03) to
            render as additional report sections, appended after the
            requirement table (R-G-04). Only text/markdown files can be
            rendered as text; other content types are noted but skipped.
        chapters_per_component: Per-generation override of whether the PDF
            chapters by component (`True`) or renders continuously
            (`False`) — `None` (the default) defers to the organisation's
            setting (`Organization.report_chapters_per_component`). Ignored for the table formats.
    """

    format: Literal["pdf", "docx", "odt", "html", "csv", "xlsx", "ods"]
    include_archived: bool = False
    component_id: UUID | None = None
    category_id: UUID | None = None
    status: RequirementStatus | None = None
    keyword: str | None = None
    primary_places_only: bool = False
    resource_file_ids: list[UUID] = []
    chapters_per_component: bool | None = None
