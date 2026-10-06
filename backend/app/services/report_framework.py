"""
Module: services.report_framework

The module-neutral half of reporting (Module 1 Phase 12b): everything a
module's reports have in common, so a module contributes only `collect_*`
functions plus one `ReportDefinition` each (declared on
`ModuleDefinition.reports`).

Responsibilities:
- Result shapes: `ReportSection`, `ReportResult`, and their JSON form
  (`ReportOut`).
- Scope: `ReportContext` carries the organisation, the in-scope projects, the
  validated parameters and a cached per-sub-component enablement check;
  `readable_projects` / `scope_projects` are the only places report scope is
  decided.
- Output: `render_csv` (first section only, formula-neutralised) and
  `render_pdf` (every section, built on `services.report_document` so a
  template's cover, accent colour and footer apply).
- HTTP: `build_report_routers` turns `ReportDefinition`s into a project router
  and an organisation router (`GET .../reports/<slug>?format=json|pdf|csv`) for
  the module to include under its own prefixes, so routes stay inside the
  module's mount and MCP path verification keeps working.
- MCP: `report_mcp_tools` derives read-only tools from the same declarations.
- Catalogue: `project_catalogue` / `organization_catalogue` list what a caller
  can run (module and sub-component enabled, organisation role held).

Design decisions:
- Access is generic and fail-closed. A project route requires project
  membership plus the module (or declared sub-component) being enabled, 404
  otherwise. An organisation route additionally requires the definition's
  `org_role_key` (403). Which projects an organisation run covers is the
  definition's declared `org_scope`; the default is the stricter
  `readable_projects`. A report whose declaration is invalid against the
  registry (unknown sub-component or role) answers 404 and is not catalogued.
- Report reads are not audit-logged, following `modules.compliance.reports`:
  every field is already returned to the same caller by the module's JSON
  endpoints. A collector must not put Restricted data (secrets, file content)
  in a result.
- Parameters are declared, not hand-written: the generated route signature
  carries typed `Query` parameters (so FastAPI validates types and bounds, 422)
  and `choices` are checked here (400). Unknown query parameters are ignored.
- The CSV is the first section only (the flat export); the PDF carries the full
  layout. Every CSV cell goes through `csv_safe` and every PDF cell through
  `report_document.safe`, since cells hold user-entered text.

Dependencies: FastAPI/Pydantic, ReportLab (via `report_document`),
`modules.registry`, `services.rbac`.
"""

from __future__ import annotations

import csv
import inspect
import io
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, NamedTuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    McpToolDefinition,
    ReportDefinition,
    ReportParamDefinition,
    get_all_reports,
    get_module,
    get_module_reports,
    is_module_enabled,
    is_module_enabled_for_project,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
    validate_report_definitions,
)
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.csv_safety import csv_safe
from app.services.downloads import filename_safe
from app.services.project_hierarchy import get_descendant_project_ids
from app.services.rbac import (
    get_effective_project_roles,
    memoize_user_lookups,
    prefetch_project_roles,
    require_org_module_enabled,
    require_project_module_enabled,
    require_project_subcomponent_enabled,
    user_satisfies_module_role,
)
from app.services.report_document import (
    STYLES,
    ReportBranding,
    build_pdf,
    load_report_template,
    resolve_branding,
    safe,
    styled_table,
    title_flowables,
)

ReportFormat = Literal["json", "pdf", "csv"]
REPORT_FORMATS: tuple[str, ...] = ("json", "pdf", "csv")

# --- Result shapes -------------------------------------------------------------


@dataclass
class ReportSection:
    """One table of a report.

    Attributes:
        key: Stable machine key.
        title: Heading shown above the table.
        columns: Column headings.
        rows: Rows of already-formatted cell strings.
        note: Optional one-line explanation printed under the heading.
        gap: Whether this table lists problems to fix (a summary pack can
            re-list every report's gap tables).
        screen: Whether the on-screen view shows this table. `False` keeps a
            table that only exists for the exports (a flat form of figures the
            screen already shows as tiles); PDF and CSV always include it.
    """

    key: str
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    gap: bool = False
    screen: bool = True


class ReportMetric(NamedTuple):
    """One headline figure of a report.

    Attributes:
        label: Short measure name ("Overdue"), without the report's title.
        value: The figure.
        gap: Whether a non-zero value is a problem to fix (the same sense as
            `ReportSection.gap`), so the screen can flag it. Informational
            totals leave this `False`.
        group: Optional heading the figure belongs under; a pack combining
            several reports sets it to each source report's title so the screen
            can group the figures instead of listing them flat.
    """

    label: str
    value: int | str
    gap: bool = False
    group: str | None = None


def normalise_metrics(metrics: Sequence[ReportMetric | tuple[str, int | str]]) -> list[ReportMetric]:
    """Returns `metrics` as `ReportMetric`s, accepting plain `(label, value)` pairs."""
    return [m if isinstance(m, ReportMetric) else ReportMetric(*m) for m in metrics]


@dataclass
class ReportResult:
    """A collected report, shared by every output form.

    Attributes:
        key: The definition's key, e.g. `"r1"`.
        title: Report title.
        scope_label: Project or organisation name the report covers.
        generated_at: When it was collected.
        notes: Caveats shown at the top (scope, model, reserved features).
        sections: The tables; `sections[0]` is the CSV export.
        metrics: Headline figures: `ReportMetric`s, or plain `(label, value)` pairs.
        data: Report-specific structured data for on-screen views.
        eligible_projects: How many in-scope projects have the report's
            sub-component enabled (0 = nothing to report on).
    """

    key: str
    title: str
    scope_label: str
    generated_at: datetime
    notes: list[str]
    sections: list[ReportSection]
    metrics: list[ReportMetric | tuple[str, int | str]] = field(default_factory=list)
    data: Any = None
    eligible_projects: int = 0


@dataclass
class ReportContext:
    """Everything a collector needs.

    Attributes:
        module_key: The declaring module's key (for enablement checks).
        organization: The organisation reported on.
        projects: In-scope projects (see `readable_projects`); a collector
            never widens this set.
        root_project: The project the report was requested for, or `None` for
            an organisation-wide report.
        params: Validated values of the definition's declared parameters, by
            name (`None` when unset and without a default).
        all_org_projects: Whether `projects` is every project in the
            organisation rather than only those the caller can read.
        today: The reference date (UTC; injectable for tests).
    """

    module_key: str
    organization: Organization
    projects: list[Project]
    root_project: Project | None = None
    params: dict[str, Any] = field(default_factory=dict)
    all_org_projects: bool = False
    today: date = field(default_factory=lambda: datetime.now(UTC).date())
    _enabled: dict[tuple[uuid.UUID, str], bool] = field(default_factory=dict, repr=False)

    @property
    def scope_label(self) -> str:
        """The name printed as the report's scope."""
        return self.root_project.name if self.root_project is not None else self.organization.name

    @property
    def scope_note(self) -> str:
        """A caveat describing which projects are covered."""
        if self.root_project is None:
            qualifier = "" if self.all_org_projects else " that you can read"
            return f"Covers {len(self.projects)} project(s) in this organisation{qualifier}."
        if len(self.projects) > 1:
            return f"Covers this project and {len(self.projects) - 1} readable child project(s)."
        return "Covers this project only."

    def eligible(self, db: Session, subcomponent: str) -> list[Project]:
        """The in-scope projects that have `subcomponent` effectively enabled.

        Args:
            db: Database session.
            subcomponent: A sub-component key of the declaring module.

        Returns:
            The matching projects, in `projects` order (checks are cached).
        """
        for p in self.projects:
            if (p.id, subcomponent) not in self._enabled:
                self._enabled[(p.id, subcomponent)] = is_module_subcomponent_enabled(
                    db, p.id, self.module_key, subcomponent,
                )
        return [p for p in self.projects if self._enabled[(p.id, subcomponent)]]


# --- Scope ----------------------------------------------------------------------


def readable_projects(
    db: Session, user: User, *, organization: Organization, root_project: Project | None, include_children: bool,
) -> list[Project]:
    """Returns the projects a report may cover for `user`.

    Only projects on which the user holds an effective project role are
    returned (an org admin without a project role is not), so an aggregate
    report never exposes a project its reader cannot open. For a project
    report the root is always included (the caller's route dependency has
    already authorised it); child projects are added only when requested and
    only if readable.

    Args:
        db: Database session.
        user: The requesting user.
        organization: The organisation; projects of other organisations are
            never returned.
        root_project: The project for a project-level report, or `None`.
        include_children: Add readable descendants of `root_project`.

    Returns:
        Projects ordered by name.
    """
    if root_project is not None:
        candidate_ids = {root_project.id}
        if include_children:
            candidate_ids |= get_descendant_project_ids(db, root_project.id)
        candidates = list(db.scalars(
            select(Project).where(Project.id.in_(candidate_ids), Project.organization_id == organization.id)
        ).all())
    else:
        candidates = list(db.scalars(select(Project).where(Project.organization_id == organization.id)).all())
    with memoize_user_lookups():
        prefetch_project_roles(db, user.id, [p.id for p in candidates])
        readable = [
            p for p in candidates
            if (root_project is not None and p.id == root_project.id) or get_effective_project_roles(db, user.id, p.id)
        ]
    return sorted(readable, key=lambda p: (p.name.lower(), str(p.id)))


def scope_projects(
    db: Session, user: User, *, definition: ReportDefinition, organization: Organization,
    root_project: Project | None, include_children: bool,
) -> list[Project]:
    """The projects a run of `definition` covers.

    A project-level run, and an organisation-wide run whose definition keeps
    the default `org_scope`, use `readable_projects`. Only an organisation-wide
    run of a definition that explicitly declares `org_scope="all_org_projects"`
    covers every project of the organisation (its route has already required
    the definition's `org_role_key`).

    Args:
        db: Database session.
        user: The requesting user.
        definition: The report being run.
        organization: The organisation reported on.
        root_project: The project for a project-level run, or `None`.
        include_children: Add readable child projects (project-level only).

    Returns:
        The in-scope projects, ordered by name.
    """
    if root_project is None and definition.org_scope == "all_org_projects":
        projects = db.scalars(select(Project).where(Project.organization_id == organization.id)).all()
        return sorted(projects, key=lambda p: (p.name.lower(), str(p.id)))
    return readable_projects(
        db, user, organization=organization, root_project=root_project, include_children=include_children,
    )


# --- Rendering --------------------------------------------------------------------

_NOTE = ParagraphStyle("report_note", parent=STYLES["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
_CELL = ParagraphStyle("report_cell", parent=STYLES["BodyText"], fontSize=7.5, leading=9.5)
_HEAD = ParagraphStyle("report_head", parent=_CELL, textColor=colors.white, fontName="Helvetica-Bold")


def render_csv(result: ReportResult) -> bytes:
    """Renders the report's main table (its first section) as UTF-8 CSV.

    Every cell goes through `csv_safe`, neutralising spreadsheet formula
    injection from user-entered text.

    Args:
        result: The collected report.

    Returns:
        CSV bytes with a header row; empty body rows when there is no data.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    main = result.sections[0] if result.sections else ReportSection("empty", "", [], [])
    writer.writerow([csv_safe(c) for c in main.columns])
    for row in main.rows:
        writer.writerow([csv_safe(c) for c in row])
    return buffer.getvalue().encode("utf-8")


def render_pdf(result: ReportResult, *, branding: ReportBranding | None = None) -> bytes:
    """Renders the whole report (every section) as a landscape A4 PDF.

    Args:
        result: The collected report.
        branding: Optional organisation template branding (accent colour,
            cover page, logo, footer); `None` renders the plain default style.

    Returns:
        PDF bytes.
    """
    accent = colors.HexColor((branding or ReportBranding(accent_color_hex=DEFAULT_ACCENT_COLOR_HEX)).accent_color_hex)
    width = landscape(A4)[0] - 3 * cm
    story: list = title_flowables(result.title, branding)
    story += [
        Paragraph(safe(f"{result.scope_label} · generated {result.generated_at.strftime('%Y-%m-%d %H:%M')} UTC"), _NOTE),
        Spacer(1, 0.2 * cm),
    ]
    story += [Paragraph(safe(n), _NOTE) for n in result.notes]
    for section in result.sections:
        story += [Spacer(1, 0.4 * cm), Paragraph(safe(section.title), STYLES["Heading2"])]
        if section.note:
            story.append(Paragraph(safe(section.note), _NOTE))
        if section.rows and section.columns:
            data = [[Paragraph(safe(c), _HEAD) for c in section.columns]]
            data += [[Paragraph(safe(cell), _CELL) for cell in row] for row in section.rows]
            story.append(styled_table(
                data, col_widths=[width / len(section.columns)] * len(section.columns), accent_color=accent, compact=True,
            ))
        else:
            story.append(Paragraph("None.", _NOTE))
    return build_pdf(
        story, footer_text=branding.footer_text if branding else None, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=result.title,
    )


# --- JSON schema --------------------------------------------------------------------


class ReportSectionOut(BaseModel):
    """One table of a report."""

    key: str
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    gap: bool = False
    screen: bool = True


class ReportMetricOut(BaseModel):
    """One headline figure (see `ReportMetric`)."""

    label: str
    value: int | str
    gap: bool = False
    group: str | None = None


class ReportOut(BaseModel):
    """A collected report as JSON (`data` is report-specific, see each
    module's `collect_*` function)."""

    key: str
    title: str
    scope_label: str
    generated_at: str
    notes: list[str]
    sections: list[ReportSectionOut]
    metrics: list[ReportMetricOut]
    data: Any = None
    eligible_projects: int


def to_out(result: ReportResult) -> ReportOut:
    """Converts a collected report to its JSON shape."""
    return ReportOut(
        key=result.key, title=result.title, scope_label=result.scope_label,
        generated_at=result.generated_at.isoformat(), notes=result.notes,
        sections=[ReportSectionOut(**jsonable_encoder(s)) for s in result.sections],
        metrics=[ReportMetricOut(**m._asdict()) for m in normalise_metrics(result.metrics)],
        data=jsonable_encoder(result.data), eligible_projects=result.eligible_projects,
    )


# --- Parameters ---------------------------------------------------------------------

_PARAM_PY_TYPE: dict[str, Any] = {"string": str, "integer": int, "boolean": bool, "date": date, "uuid": UUID}
_PARAM_MCP_TYPE = {"string": "string", "integer": "integer", "boolean": "boolean", "date": "string", "uuid": "uuid"}


def validated_params(definition: ReportDefinition, values: dict[str, Any]) -> dict[str, Any]:
    """Collects the declared parameter values from the parsed query.

    Types and bounds were already enforced by the generated route signature
    (422); this applies the declared default when a value is absent and
    checks `choices`.

    Args:
        definition: The report being run.
        values: Parsed route arguments (may contain more than the declared
            parameters).

    Returns:
        `{name: value}` for every declared parameter.

    Raises:
        HTTPException: 400 when a value is not one of the declared choices.
    """
    out: dict[str, Any] = {}
    for param in definition.params:
        value = values.get(param.name)
        if value is None:
            value = param.default
        if value is not None and param.choices is not None and value not in param.choices:
            allowed = ", ".join(str(c) for c in param.choices)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown value '{value}' for '{param.name}'; use one of: {allowed}.")
        out[param.name] = value
    return out


# --- Routes -----------------------------------------------------------------------------


@dataclass
class ReportRouters:
    """The two routers `build_report_routers` returns; a module includes
    `project` in its project router and `org` in its organisation router."""

    project: APIRouter
    org: APIRouter


def _live_definition(module_key: str, definition: ReportDefinition) -> ReportDefinition:
    """The registry-validated `definition`, or 404.

    Declarations that name an unknown sub-component or org role are rejected
    by `get_module_reports`; a route built for one fails closed here rather
    than reaching a collector.
    """
    for live in get_module_reports(module_key):
        if live.slug == definition.slug:
            return live
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


def _respond(
    result: ReportResult, definition: ReportDefinition, fmt: str, scope_name: str, branding: ReportBranding | None,
) -> Response | ReportOut:
    """Serialises `result` as `fmt`."""
    if fmt == "json":
        return to_out(result)
    stem = f"{filename_safe(scope_name, fallback='report')}-{definition.slug}"
    if fmt == "csv":
        return Response(
            content=render_csv(result), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )
    return Response(
        content=render_pdf(result, branding=branding), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
    )


def _branding_for(db: Session, organization: Organization, template_id: UUID | None) -> ReportBranding | None:
    """The branding of the requested template, `None` when none was requested.

    Raises:
        HTTPException: 400 when the template is not one of the organisation's.
    """
    if template_id is None:
        return None
    template = load_report_template(db, organization.id, template_id)
    if template is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this organisation.")
    return resolve_branding(db, organization, template)


def _route_signature(path_param: str, definition: ReportDefinition, *, project_level: bool, dependency: Callable) -> inspect.Signature:
    """The generated endpoint's signature: path id, `format`, optional
    `include_children`, `report_template_id`, the declared parameters as typed
    `Query` values, then the user/session dependencies."""
    P = inspect.Parameter
    params = [
        P(path_param, P.POSITIONAL_OR_KEYWORD, annotation=UUID),
        P("format", P.POSITIONAL_OR_KEYWORD, annotation=ReportFormat, default=Query("json")),
    ]
    if project_level:
        params.append(P("include_children", P.POSITIONAL_OR_KEYWORD, annotation=bool, default=Query(False)))
    else:
        params.append(P(
            "project_id", P.POSITIONAL_OR_KEYWORD, annotation=UUID | None,
            default=Query(None, description="Narrow the report to this one project (must be in its scope)."),
        ))
    params.append(P("report_template_id", P.POSITIONAL_OR_KEYWORD, annotation=UUID | None, default=Query(None)))
    for param in definition.params:
        bounds = {"ge": param.minimum, "le": param.maximum} if param.type == "integer" else {}
        params.append(P(
            param.name, P.POSITIONAL_OR_KEYWORD, annotation=_PARAM_PY_TYPE[param.type] | None,
            default=Query(param.default, description=param.description or None, **bounds),
        ))
    params.append(P("current_user", P.POSITIONAL_OR_KEYWORD, annotation=User, default=Depends(dependency)))
    params.append(P("db", P.POSITIONAL_OR_KEYWORD, annotation=Session, default=Depends(get_db)))
    return inspect.Signature(params)


def _build_project_route(module_key: str, definition: ReportDefinition) -> Callable[..., Any]:
    dependency = (
        require_project_subcomponent_enabled(module_key, definition.subcomponent)
        if definition.subcomponent else require_project_module_enabled(module_key)
    )

    def endpoint(**kw: Any):
        live = _live_definition(module_key, definition)
        db: Session = kw["db"]
        project = db.get(Project, kw["project_id"])
        organization = db.get(Organization, project.organization_id)
        params = validated_params(live, kw)
        branding = _branding_for(db, organization, kw["report_template_id"])
        ctx = ReportContext(
            module_key=module_key, organization=organization, root_project=project, params=params,
            projects=readable_projects(
                db, kw["current_user"], organization=organization, root_project=project,
                include_children=kw["include_children"],
            ),
        )
        return _respond(live.collector(db, ctx), live, kw["format"], project.name, branding)

    endpoint.__signature__ = _route_signature("project_id", definition, project_level=True, dependency=dependency)  # type: ignore[attr-defined]
    endpoint.__doc__ = (
        f"{definition.title} for this project: {definition.description} `format` is json (default), pdf or csv; "
        "`include_children` adds readable child projects; `report_template_id` applies an organisation report "
        "template's branding to the PDF."
    )
    return endpoint


def _build_org_route(module_key: str, definition: ReportDefinition) -> Callable[..., Any]:
    dependency = require_org_module_enabled(module_key)

    def endpoint(**kw: Any):
        live = _live_definition(module_key, definition)
        db: Session = kw["db"]
        current_user: User = kw["current_user"]
        organization_id: UUID = kw["organization_id"]
        if not user_satisfies_module_role(
            db, current_user, module_key, live.org_role_key, organization_id=organization_id, project_id=None,
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not hold the role required for organisation-wide reports.")
        organization = db.get(Organization, organization_id)
        params = validated_params(live, kw)
        branding = _branding_for(db, organization, kw["report_template_id"])
        projects = scope_projects(
            db, current_user, definition=live, organization=organization, root_project=None, include_children=False,
        )
        if kw["project_id"] is not None:
            # Narrowing only: the project must already be in the caller's scope, so this can never widen it.
            projects = [p for p in projects if p.id == kw["project_id"]]
            if not projects:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "That project is not covered by this report.")
        ctx = ReportContext(
            module_key=module_key, organization=organization, root_project=None, params=params,
            all_org_projects=live.org_scope == "all_org_projects",
            projects=projects,
        )
        return _respond(live.collector(db, ctx), live, kw["format"], organization.name, branding)

    endpoint.__signature__ = _route_signature("organization_id", definition, project_level=False, dependency=dependency)  # type: ignore[attr-defined]
    scope = "every project in the organisation" if definition.org_scope == "all_org_projects" else "projects the caller can read"
    endpoint.__doc__ = (
        f"{definition.title} across the organisation: {definition.description} Needs the module role "
        f"`{definition.org_role_key}` (org admins hold module roles by default) and covers {scope}; `project_id` "
        "narrows it to one project in that scope."
    )
    return endpoint


def build_report_routers(module_key: str, definitions: Sequence[ReportDefinition]) -> ReportRouters:
    """Generates a module's report routes from its declarations.

    One project route per definition and one organisation route per
    `org_level` definition, both at `/reports/<slug>` (the routers carry the
    `/reports` prefix; the module includes them under its own mounts). Only
    structurally valid definitions are routed; ones that are invalid against
    the registry are routed but answer 404 (see `_live_definition`).

    Args:
        module_key: The declaring module's key.
        definitions: The module's `ModuleDefinition.reports`.

    Returns:
        The project and organisation routers.
    """
    valid, _ = validate_report_definitions(definitions)
    routers = ReportRouters(project=APIRouter(prefix="/reports"), org=APIRouter(prefix="/reports"))
    ok = {"200": {"model": ReportOut, "description": "JSON, or a PDF/CSV file for `format=pdf|csv`."}}
    for definition in valid:
        routers.project.add_api_route(
            f"/{definition.slug}", _build_project_route(module_key, definition), methods=["GET"], response_model=None,
            name=f"project_report_{definition.key}", summary=definition.title, responses=ok,
        )
        if definition.org_level:
            routers.org.add_api_route(
                f"/{definition.slug}", _build_org_route(module_key, definition), methods=["GET"], response_model=None,
                name=f"org_report_{definition.key}", summary=f"{definition.title} (organisation-wide)", responses=ok,
            )
    return routers


# --- MCP ----------------------------------------------------------------------------------


def _mcp_params(definition: ReportDefinition, *, project_level: bool) -> list[dict]:
    """MCP tool parameters derived from a definition's declarations."""
    params: list[dict] = []
    if project_level:
        params.append({
            "name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project to report on.",
        })
        params.append({
            "name": "include_children", "type": "boolean", "required": False, "in": "query",
            "description": "Also cover readable child projects.",
        })
    for param in definition.params:
        description = param.description
        if param.type == "date":
            description = f"{description} (ISO date, YYYY-MM-DD)".strip()
        if param.choices:
            description = f"{description} One of: {', '.join(str(c) for c in param.choices)}.".strip()
        params.append({
            "name": param.name, "type": _PARAM_MCP_TYPE[param.type], "required": False, "in": "query",
            "description": description,
        })
    return params


def report_mcp_tools(definitions: Sequence[ReportDefinition], *, project_router_prefix: str) -> tuple[McpToolDefinition, ...]:
    """Read-only MCP tools for a module's reports.

    Only project-level routes are declared (organisation-scoped endpoints have
    no MCP-safe path, as for other org-scoped module endpoints); the JSON form
    is what the tool returns. `build_mcp_tool_manifest` still verifies each
    path against the module's real routes.

    Args:
        definitions: The module's `ModuleDefinition.reports`.
        project_router_prefix: The module's project router prefix, e.g.
            `/api/v1/projects/{project_id}/modules/<key>`.

    Returns:
        One `get_<slug>_report` tool per valid definition.
    """
    valid, _ = validate_report_definitions(definitions)
    return tuple(
        McpToolDefinition(
            name=f"get_{d.slug.replace('-', '_')}_report", description=f"{d.title}: {d.description}", method="GET",
            path_template=f"{project_router_prefix}/reports/{d.slug}", params=_mcp_params(d, project_level=True),
        )
        for d in valid
    )


# --- Catalogue -------------------------------------------------------------------------------


class ReportParamOut(BaseModel):
    """A declared report parameter as the catalogue shows it."""

    name: str
    type: str
    default: Any = None
    choices: list[Any] | None = None
    minimum: int | None = None
    maximum: int | None = None
    description: str = ""
    label: str = ""
    choice_labels: dict[str, str] | None = None


class ReportProjectOut(BaseModel):
    """A project an organisation-wide report can be narrowed to."""

    id: UUID
    name: str


class ReportCatalogueEntryOut(BaseModel):
    """One report the caller can run.

    `path` is the report's route with the project or organisation id already
    substituted; `supports_include_children` is true for project-level
    entries and `supports_project_filter` for organisation-level ones (the
    optional `project_id` query narrows the run to one project in scope).
    For those, `projects` lists exactly the projects the caller may pick: in
    the report's scope for this caller, with the module (and declared
    sub-component) enabled, so the picker never offers one the route would 404.
    """

    module_key: str
    module_name: str
    key: str
    slug: str
    title: str
    description: str
    scope: Literal["project", "organization"]
    path: str
    formats: list[str]
    supports_include_children: bool
    supports_project_filter: bool
    projects: list[ReportProjectOut] = []
    params: list[ReportParamOut]


def _param_out(param: ReportParamDefinition) -> ReportParamOut:
    return ReportParamOut(
        name=param.name, type=param.type, default=param.default,
        choices=list(param.choices) if param.choices is not None else None,
        minimum=param.minimum, maximum=param.maximum, description=param.description, label=param.label,
        choice_labels={str(k): v for k, v in param.choice_labels.items()} if param.choice_labels else None,
    )


def _entry(
    module_key: str, definition: ReportDefinition, *, scope: Literal["project", "organization"], path: str,
    projects: Sequence[Project] = (),
) -> ReportCatalogueEntryOut:
    module = get_module(module_key)
    return ReportCatalogueEntryOut(
        module_key=module_key, module_name=module.name if module else module_key, key=definition.key,
        slug=definition.slug, title=definition.title, description=definition.description, scope=scope, path=path,
        formats=list(REPORT_FORMATS), supports_include_children=scope == "project", supports_project_filter=scope == "organization",
        projects=[ReportProjectOut(id=p.id, name=p.name) for p in projects],
        params=[_param_out(p) for p in definition.params],
    )


def project_catalogue(db: Session, project: Project) -> list[ReportCatalogueEntryOut]:
    """Every report runnable on `project`: the module is enabled for it and the
    declared sub-component (if any) is enabled. The caller's project access
    is the route's concern.

    Args:
        db: Database session.
        project: The project.

    Returns:
        Entries in registry order.
    """
    entries: list[ReportCatalogueEntryOut] = []
    for module_key, definition in get_all_reports():
        module = get_module(module_key)
        router = module.get_project_router() if module is not None and module.get_project_router is not None else None
        if router is None or not is_module_enabled_for_project(db, project.id, module_key):
            continue
        if definition.subcomponent and not is_module_subcomponent_enabled(db, project.id, module_key, definition.subcomponent):
            continue
        path = f"{router.prefix}/reports/{definition.slug}".replace("{project_id}", str(project.id))
        entries.append(_entry(module_key, definition, scope="project", path=path))
    return entries


def organization_catalogue(db: Session, user: User, organization_id: UUID) -> list[ReportCatalogueEntryOut]:
    """Every organisation-wide report `user` can run: the module (and declared
    sub-component) is enabled for the organisation and the user holds the
    definition's `org_role_key`.

    Args:
        db: Database session.
        user: The caller.
        organization_id: The organisation.

    Returns:
        Entries in registry order.
    """
    entries: list[ReportCatalogueEntryOut] = []
    organization = db.get(Organization, organization_id)
    scoped: dict[str, list[Project]] = {}  # per `org_scope`: the scope does not depend on the report
    for module_key, definition in get_all_reports():
        module = get_module(module_key)
        if not definition.org_level or module is None or not is_module_enabled(db, organization_id, module_key):
            continue
        if definition.subcomponent and not is_org_module_subcomponent_enabled(
            db, organization_id, module_key, definition.subcomponent,
        ):
            continue
        if not user_satisfies_module_role(
            db, user, module_key, definition.org_role_key, organization_id=organization_id, project_id=None,
        ):
            continue
        router = module.get_router()
        if router is None:
            continue
        path = f"{router.prefix}/reports/{definition.slug}".replace("{organization_id}", str(organization_id))
        if definition.org_scope not in scoped:
            scoped[definition.org_scope] = scope_projects(
                db, user, definition=definition, organization=organization, root_project=None, include_children=False,
            )
        pickable = [
            p for p in scoped[definition.org_scope]
            if is_module_enabled_for_project(db, p.id, module_key)
            and (not definition.subcomponent or is_module_subcomponent_enabled(db, p.id, module_key, definition.subcomponent))
        ]
        entries.append(_entry(module_key, definition, scope="organization", path=path, projects=pickable))
    return entries


__all__ = [
    "REPORT_FORMATS",
    "ReportCatalogueEntryOut",
    "ReportContext",
    "ReportFormat",
    "ReportMetric",
    "ReportOut",
    "ReportParamOut",
    "ReportProjectOut",
    "ReportResult",
    "ReportRouters",
    "ReportSection",
    "build_report_routers",
    "normalise_metrics",
    "organization_catalogue",
    "project_catalogue",
    "readable_projects",
    "render_csv",
    "render_pdf",
    "report_mcp_tools",
    "scope_projects",
    "to_out",
    "validated_params",
]
