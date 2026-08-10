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
        chapters_per_component: Per-generation override of whether the PDF
            chapters by component (`True`) or renders continuously
            (`False`) — `None` (the default) defers to the selected
            template's own setting, or — with no template — a heuristic
            (`services.reports.default_chapters_per_component`). Always
            wins over both when explicitly set. Ignored for CSV exports.
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
    chapters_per_component: bool | None = None


class ReportChapter(BaseModel):
    title: str
    body: str = ""


class ProjectReportConfig(BaseModel):
    """Persisted report structure (mock's "Report Setup"), used as the
    default report content when a generation request doesn't override it
    with ad-hoc pre_markdown/post_markdown.

    `intro`/`chapters`/`appendices` are always the *effective* values on a
    `GET` (falling back to the organisation's own default per-field when
    the project hasn't set its own — `services.reports.resolve_report_config`)
    and the *raw* project-level values on a `PUT` (this schema doubles as
    the request body; the `*_is_organisation_default` fields are
    response-only and simply ignored if present on a request).
    """

    intro: str = ""
    chapters: list[ReportChapter] = []
    appendices: list[ReportChapter] = []
    intro_is_organisation_default: bool = False
    chapters_is_organisation_default: bool = False
    appendices_is_organisation_default: bool = False
    # Not part of the intro/chapters/appendices per-field fallback
    # resolution above (there's no organisation-level default template to
    # fall back to) — just the project's own raw setting, read/written
    # directly, ignored if present on a PUT (matches how the
    # `*_is_organisation_default` fields are documented above).
    default_report_template_id: UUID | None = None


class OrgReportDefaults(BaseModel):
    """Organisation-level default report content (UI/UX pass) — a project
    falls back to these per-field when its own is blank/empty. Symmetric
    with `Project`'s own fields: an empty string/list here means "no
    organisation default set", not "explicitly blank"."""

    intro: str = ""
    chapters: list[ReportChapter] = []
    appendices: list[ReportChapter] = []
