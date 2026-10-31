"""
Module: services.report_module_run

Runs a module's report (`ReportDefinition`) from service code, as the caller, with the gates the report's own
routes apply (`report_framework.build_report_routers`). A report pack uses it for its module report entries.

Responsibilities:
- `find_report`: the registered report a pack entry names.
- `run_module_report`: collect the report for a project or for the organisation and return its `ReportResult`.
- `render_module_report`: produce the file of a result in any format a module report offers, with the organisation template's
  branding.

Design decisions:
- **Same gates as the route, never fewer.** A project run needs the module (and the report's sub-component) enabled
  for the project; an organisation-wide run needs the report to have an organisation variant, the module enabled for
  the organisation and the caller to hold the report's module role. A refusal is `ModuleReportUnavailableError`
  with a reason safe to show, so a pack can list the entry as not available instead of failing.
- **Scope is never widened.** Projects come from `report_framework.scope_projects`, so a record the caller cannot
  read is not in the result, exactly as for the route.
- The collector is the module's own; nothing is added to the module or to a core file per report.

Dependencies: `services.report_framework`, `modules.registry`, `services.rbac`.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    ReportDefinition,
    get_all_reports,
    report_enabled_for_organization,
    report_enabled_for_project,
)
from app.services.rbac import user_satisfies_module_role
from app.services.report_document import resolve_branding
from app.services.report_framework import (
    ReportContext,
    ReportResult,
    apply_cell_tones,
    render_result,
    scope_projects,
)


class ModuleReportUnavailableError(LookupError):
    """The report cannot be run here; the message is safe to show the caller."""


def find_report(module_key: str, report_key: str) -> ReportDefinition | None:
    """The registered report `(module_key, report_key)`, or `None`."""
    return next((d for mk, d in get_all_reports() if mk == module_key and d.key == report_key), None)


def typed_params(definition: ReportDefinition, given: dict[str, Any] | None) -> dict[str, Any]:
    """The values a collector receives: every declared parameter, with its default when unset (dates and ids typed)."""
    out: dict[str, Any] = {}
    supplied = given or {}
    for param in definition.params:
        value = supplied.get(param.name)
        if value is None:
            value = param.default
        elif param.type == "date":
            value = date.fromisoformat(value)
        elif param.type == "uuid":
            value = uuid.UUID(value)
        out[param.name] = value
    return out


def run_module_report(
    db: Session, user: User, *, organization: Organization, project: Project | None, module_key: str,
    definition: ReportDefinition, params: dict[str, Any] | None = None, include_children: bool = False,
) -> ReportResult:
    """Collects a module report for `user`.

    Args:
        db: Active session (read only).
        user: The caller.
        organization: The organisation.
        project: The project of a project-level run (the caller has been authorised for it), or `None` for an
            organisation-wide run.
        module_key / definition: The report.
        params: Values of the report's declared parameters (already checked against the declaration).
        include_children: Also cover the project's readable child projects.

    Returns:
        The collected result, cell tones applied.

    Raises:
        ModuleReportUnavailableError: The module or sub-component is off, the report has no organisation variant, or
            the caller lacks the role it needs.
    """
    if project is not None:
        if not report_enabled_for_project(db, project.id, module_key, definition):
            raise ModuleReportUnavailableError("Its module is not enabled for this project.")
    else:
        if not definition.org_level:
            raise ModuleReportUnavailableError("It has no organisation-wide version.")
        if not report_enabled_for_organization(db, organization.id, module_key, definition):
            raise ModuleReportUnavailableError("Its module is not enabled for this organisation.")
        assert definition.org_role_key is not None  # validate_report_definitions requires it for org_level
        if not user_satisfies_module_role(
            db, user, module_key, definition.org_role_key, organization_id=organization.id, project_id=None,
        ):
            raise ModuleReportUnavailableError("You do not hold the role it needs.")
    projects = scope_projects(
        db, user, definition=definition, organization=organization, root_project=project, include_children=include_children,
    )
    if not projects:
        raise ModuleReportUnavailableError("There is no project to run it for.")
    ctx = ReportContext(
        module_key=module_key, organization=organization, root_project=project, params=typed_params(definition, params),
        all_org_projects=project is None and definition.org_scope == "all_org_projects", projects=projects,
    )
    return apply_cell_tones(definition.collector(db, ctx), definition.cell_tones)


def render_module_report(db: Session, result: ReportResult, fmt: str, *, organization: Organization) -> bytes:
    """The file of a collected report in `fmt` (any of `report_framework.REPORT_FORMATS` but `json`), with the
    document formats carrying the organisation's report look.

    Raises:
        ValueError: `fmt` is not one of those.
    """
    return render_result(result, fmt, branding=resolve_branding(db, organization)).content


__all__ = [
    "ModuleReportUnavailableError", "find_report", "render_module_report", "run_module_report", "typed_params",
]
