"""
Module: modules.context_strategy.report_router

HTTP surface for the Context & Strategy reports R1–R9 (docs/plans/module-01-
context-and-strategy-plan.md Phase 12). Two routers, mounted under the
module's existing org and project routers at `/reports/<slug>`; one route per
catalogue entry is generated from `reports.REPORTS`, so adding a report needs
no router code.

Every route returns `?format=json` (default, the on-screen/MCP shape),
`pdf` or `csv`, all from the same collected `ReportResult`.

Access:
- Project routes require project membership and the report's sub-component
  (`require_project_subcomponent_enabled`, 404 when off). `include_children`
  adds child projects the caller can also read.
- Organisation routes (R1, R3, R4, R8, R9 only) additionally require the
  `org_reports_viewer` module role (`_shared.require_org_reports_role`) and
  silently drop any project the caller cannot read.
- Report reads are not audit-logged (see `reports.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy._shared import MODULE_KEY, require_org_reports_role
from app.modules.context_strategy.pain_point_scores import RollupMethod
from app.modules.context_strategy.report_render import render_csv, render_pdf
from app.modules.context_strategy.reports import REPORTS, ReportRequest, ReportResult, ReportSpec, readable_projects
from app.services.downloads import filename_safe
from app.services.rbac import (
    require_org_module_enabled,
    require_project_module_enabled,
    require_project_subcomponent_enabled,
)

ReportFormat = Literal["json", "pdf", "csv"]


class ReportSectionOut(BaseModel):
    """One table of a report."""

    key: str
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    gap: bool = False


class ReportMetricOut(BaseModel):
    """One headline figure."""

    label: str
    value: int | str


class ReportOut(BaseModel):
    """A collected report as JSON (`data` is report-specific, see each
    `collect_*` function)."""

    key: str
    title: str
    scope_label: str
    generated_at: str
    notes: list[str]
    sections: list[ReportSectionOut]
    metrics: list[ReportMetricOut]
    data: Any = None
    eligible_projects: int


def _parse_rollup(value: str) -> RollupMethod:
    """Parses a roll-up query value, 400 for an unknown one."""
    try:
        return RollupMethod(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown roll-up method '{value}'.") from exc


def _to_out(result: ReportResult) -> ReportOut:
    """Converts a collected report to its JSON shape."""
    return ReportOut(
        key=result.key, title=result.title, scope_label=result.scope_label,
        generated_at=result.generated_at.isoformat(), notes=result.notes,
        sections=[ReportSectionOut(**jsonable_encoder(s)) for s in result.sections],
        metrics=[ReportMetricOut(label=name, value=value) for name, value in result.metrics],
        data=jsonable_encoder(result.data), eligible_projects=result.eligible_projects,
    )


def _respond(result: ReportResult, spec: ReportSpec, fmt: ReportFormat, scope_name: str) -> Response | ReportOut:
    """Serialises `result` as `fmt`."""
    if fmt == "json":
        return _to_out(result)
    stem = f"{filename_safe(scope_name, fallback='report')}-{spec.slug}"
    if fmt == "csv":
        return Response(
            content=render_csv(result), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )
    return Response(
        content=render_pdf(result), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
    )


def _build_project_route(spec: ReportSpec) -> Callable[..., Any]:
    dependency = (
        require_project_subcomponent_enabled(MODULE_KEY, spec.subcomponent)
        if spec.subcomponent else require_project_module_enabled(MODULE_KEY)
    )

    def endpoint(
        project_id: UUID, format: ReportFormat = Query("json"), model_key: str | None = None,
        rollup: str = RollupMethod.WEIGHTED_AVERAGE.value, include_children: bool = False,
        stale_months: int = Query(6, ge=1, le=120), since: date | None = None,
        current_user: User = Depends(dependency), db: Session = Depends(get_db),
    ):
        project = db.get(Project, project_id)
        organization = db.get(Organization, project.organization_id)
        request = ReportRequest(
            organization=organization, root_project=project, model_key=model_key, rollup=_parse_rollup(rollup),
            stale_months=stale_months, since=since,
            projects=readable_projects(
                db, current_user, organization=organization, root_project=project, include_children=include_children,
            ),
        )
        return _respond(spec.collector(db, request), spec, format, project.name)

    endpoint.__doc__ = (
        f"{spec.title} for this project: {spec.description} `format` is json (default), pdf or csv; "
        "`include_children` adds readable child projects; `model_key`/`rollup` choose the Pain Point scoring "
        "model and persona roll-up where relevant; `stale_months`/`since` apply to the change history."
    )
    return endpoint


def _build_org_route(spec: ReportSpec) -> Callable[..., Any]:
    module_dependency = require_org_module_enabled(MODULE_KEY)

    def endpoint(
        organization_id: UUID, format: ReportFormat = Query("json"), model_key: str | None = None,
        rollup: str = RollupMethod.WEIGHTED_AVERAGE.value,
        current_user: User = Depends(module_dependency), db: Session = Depends(get_db),
    ):
        require_org_reports_role(db, current_user, organization_id=organization_id)
        organization = db.get(Organization, organization_id)
        request = ReportRequest(
            organization=organization, root_project=None, model_key=model_key, rollup=_parse_rollup(rollup),
            projects=readable_projects(
                db, current_user, organization=organization, root_project=None, include_children=False,
            ),
        )
        return _respond(spec.collector(db, request), spec, format, organization.name)

    endpoint.__doc__ = (
        f"{spec.title} across the organisation: {spec.description} Needs the Organisation Reports Viewer role "
        "(org admins hold it) and covers only projects the caller can read."
    )
    return endpoint


project_reports_router = APIRouter(prefix="/reports")
org_reports_router = APIRouter(prefix="/reports")

for _spec in REPORTS.values():
    project_reports_router.add_api_route(
        f"/{_spec.slug}", _build_project_route(_spec), methods=["GET"], response_model=None,
        name=f"project_report_{_spec.key}", summary=_spec.title,
        responses={200: {"model": ReportOut, "description": "JSON, or a PDF/CSV file for `format=pdf|csv`."}},
    )
    if _spec.org_level:
        org_reports_router.add_api_route(
            f"/{_spec.slug}", _build_org_route(_spec), methods=["GET"], response_model=None,
            name=f"org_report_{_spec.key}", summary=f"{_spec.title} (organisation-wide)",
            responses={200: {"model": ReportOut, "description": "JSON, or a PDF/CSV file for `format=pdf|csv`."}},
        )
