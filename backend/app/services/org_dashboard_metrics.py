"""
Module: services.org_dashboard_metrics

The bounded catalogue of figures an organisation dashboard's widgets show, and the batched evaluation behind them.

Responsibilities:
- Define the core organisation metrics (projects, requirements, members, file storage, projects by status, and a
  record count over any registered type summed across the projects the caller may read).
- Validate a metric reference against that catalogue, for a stored layout and for a request alike.
- Evaluate a batch for a caller: identical references once, a cap, a time budget, and a state per result so one slow
  or unreadable figure never blanks the page.

Design decisions:
- The headline counts reuse `org_overview_stats`, so the dashboard and the stats endpoint cannot disagree: an
  organisation administrator sees the organisation's real totals, anyone else sees what their own roles let them open.
- A figure the caller may not read is `unavailable`, never zero (a zero would show that nothing is hidden).
- A metric is never an arbitrary query; the record count accepts a registered record type and nothing else.
- A module adds organisation figures either as a metric (`ModuleDefinition.org_overview_metrics`, usable by the tile,
  gauge and chart widgets and offered only while the organisation has the module enabled) or as a whole widget of its
  own (`org_overview_widgets`).

External dependencies: `services.org_overview_stats`, `services.project_access`, `services.record_counts`,
`modules.registry`.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.project_status import ProjectStatusDefinition
from app.models.user import User
from app.modules.registry import (
    OverviewMetric,
    OverviewMetricValue,
    artefact_type_module,
    get_org_overview_metrics,
    get_record_table_providers,
    is_module_enabled,
    is_module_enabled_for_project,
)
from app.schemas.org import OrgOverviewStatsOut
from app.services.org_overview_stats import org_overview_stats
from app.services.overview_metrics import (
    MAX_METRICS_PER_REQUEST,
    TIME_BUDGET_SECONDS,
    MetricResult,
    MetricSpec,
    MetricUnavailable,
    build_record_filters,
    validate_filters,
)
from app.services.project_access import accessible_project_ids
from app.services.rbac import get_effective_org_roles
from app.services.record_counts import count_in_project

_log = logging.getLogger(__name__)

RECORD_COUNT_KEY = "org_record_count"


def _refuse(message: str) -> HTTPException:
    """A 422 with `message`."""
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


@dataclass
class OrgMetricContext:
    """What an organisation metric's `evaluate` receives for one request.

    Attributes:
        db: Active session (read only).
        user: The caller.
        organization: The organisation.
    """

    db: Session
    user: User
    organization: Organization
    _stats: OrgOverviewStatsOut | None = field(default=None, repr=False)
    _projects: list[Project] | None = field(default=None, repr=False)

    def stats(self) -> OrgOverviewStatsOut:
        """The headline figures, read once per request."""
        if self._stats is None:
            self._stats = org_overview_stats(self.db, self.user, self.organization.id)
        return self._stats

    def projects(self) -> list[Project]:
        """The active projects of the organisation the caller may count: all for an organisation administrator, else
        those they can open. Read once per request."""
        if self._projects is None:
            query = select(Project).where(Project.organization_id == self.organization.id, Project.is_archived.is_(False))
            if not self.stats().is_full_org_total:
                query = query.where(Project.id.in_(accessible_project_ids(self.db, self.user.id)))
            self._projects = list(self.db.scalars(query.order_by(Project.name)))
        return self._projects


def _scalar(read: Any) -> Any:
    """An `evaluate` for a single figure read from the context."""
    return lambda ctx, params: OverviewMetricValue(value=float(read(ctx)))


def _projects_by_status(ctx: OrgMetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """The caller's projects grouped by their status, in the statuses' own order."""
    counts = Counter(project.status_id for project in ctx.projects())
    if not counts:
        return OverviewMetricValue(breakdown=[])
    statuses = ctx.db.scalars(select(ProjectStatusDefinition).where(ProjectStatusDefinition.id.in_(counts))).all()
    ordered = sorted(statuses, key=lambda s: (s.sort_order, s.name))
    return OverviewMetricValue(breakdown=[(str(s.id), s.name, float(counts[s.id])) for s in ordered])


def _record_count(ctx: OrgMetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """The records of one type across the projects the caller may read, each project counted by the type's own rules."""
    artefact_type = str(params["record_type"])
    definition = artefact_type_module(artefact_type)
    provider = get_record_table_providers()[artefact_type]
    filters, tag_filter_for = build_record_filters(ctx.db, params.get("filters") or {}, provider.filter_params)
    total = 0
    readable = False
    for project in ctx.projects():
        if definition is not None and not is_module_enabled_for_project(ctx.db, project.id, definition.key):
            continue
        counted = count_in_project(ctx.db, ctx.user, project, artefact_type, filters=filters, tag_filter_for=tag_filter_for)
        if counted is not None:
            readable = True
            total += counted
    if not readable:
        raise MetricUnavailable
    return OverviewMetricValue(value=float(total))


def core_metrics() -> dict[str, OverviewMetric]:
    """The metrics every organisation dashboard has, by key."""
    return {
        "org_project_count": OverviewMetric("Projects", "count", _scalar(lambda c: c.stats().project_count)),
        "org_requirement_count": OverviewMetric("Requirements", "count", _scalar(lambda c: c.stats().requirement_count)),
        "org_member_count": OverviewMetric("Members", "count", _scalar(lambda c: c.stats().member_count)),
        "org_file_storage": OverviewMetric("File storage", "bytes", _scalar(lambda c: c.stats().total_file_size_bytes)),
        "org_projects_by_status": OverviewMetric("Projects by status", "count", _projects_by_status, breakdown=True, scalar=False),
        RECORD_COUNT_KEY: OverviewMetric("Record count", "count", _record_count, params=frozenset({"record_type", "filters"})),
    }


def record_type_options(db: Session, organization_id: uuid.UUID) -> list[tuple[str, str, list[str]]]:
    """`(type, plural label, filter names)` of every record type the organisation may count: types that count in the
    project overview, whose module the organisation has enabled (a core type always qualifies), by label."""
    options: list[tuple[str, str, list[str]]] = []
    for artefact_type, provider in get_record_table_providers().items():
        if not provider.in_overview:
            continue
        definition = artefact_type_module(artefact_type)
        if definition is not None and not is_module_enabled(db, organization_id, definition.key):
            continue
        options.append((artefact_type, provider.label, sorted(provider.filter_params)))
    return sorted(options, key=lambda option: option[1])


def catalogue_for(db: Session, organization_id: uuid.UUID) -> dict[str, tuple[str | None, OverviewMetric]]:
    """The metrics an organisation's dashboards can show as `{key: (module_key, metric)}`: the core ones and each module's
    the organisation has enabled."""
    found: dict[str, tuple[str | None, OverviewMetric]] = {key: (None, metric) for key, metric in core_metrics().items()}
    for key, (module_key, metric) in get_org_overview_metrics().items():
        if is_module_enabled(db, organization_id, module_key):
            found[key] = (module_key, metric)
    return found


def validate_reference(db: Session, organization_id: uuid.UUID, raw_metric: Any, raw_params: Any) -> tuple[str, dict[str, Any]]:
    """Checks a `metric` key and its `params` against the organisation catalogue.

    Raises:
        HTTPException: 422 for an unknown metric, an unknown parameter, or a record type the organisation cannot count.
    """
    catalogue = {key: metric for key, (_module, metric) in catalogue_for(db, organization_id).items()}
    if not isinstance(raw_metric, str) or raw_metric not in catalogue:
        raise _refuse("Choose a metric from the list.")
    params = {} if raw_params in (None, {}) else raw_params
    if not isinstance(params, dict):
        raise _refuse("The metric settings must be a set of named values.")
    unknown = sorted(set(params) - catalogue[raw_metric].params)
    if unknown:
        raise _refuse(f"The metric does not accept: {', '.join(unknown)}.")
    if raw_metric == RECORD_COUNT_KEY:
        record_type = params.get("record_type")
        if not isinstance(record_type, str) or record_type not in {t for t, _, _ in record_type_options(db, organization_id)}:
            raise _refuse("Choose a record type to count.")
        cleaned: dict[str, Any] = {"record_type": record_type}
        filters = validate_filters(params.get("filters"), record_type)
        if filters:
            cleaned["filters"] = filters
        return raw_metric, cleaned
    return raw_metric, {}


def _label_of(metric_key: str, metric: OverviewMetric, params: Mapping[str, Any]) -> str:
    """The default title of a figure: the metric's name, or the counted type's plural name for a record count."""
    if metric_key == RECORD_COUNT_KEY:
        provider = get_record_table_providers().get(str(params.get("record_type")))
        if provider is not None:
            return provider.label
    return metric.label


def evaluate_batch(db: Session, user: User, organization: Organization, specs: list[MetricSpec]) -> dict[str, MetricResult]:
    """Evaluates every reference once per distinct figure.

    Args:
        db: Active session (read only).
        user: The caller (already a member of `organization`).
        organization: The organisation.
        specs: The references, already validated (`validate_reference`).

    Returns:
        A result per reference id.

    Raises:
        HTTPException: 422 when the batch exceeds `MAX_METRICS_PER_REQUEST` references or an id repeats.
    """
    if len(specs) > MAX_METRICS_PER_REQUEST:
        raise _refuse(f"At most {MAX_METRICS_PER_REQUEST} metrics may be requested at once.")
    if len({spec.id for spec in specs}) != len(specs):
        raise _refuse("Each requested metric needs its own id.")
    if not get_effective_org_roles(db, user.id, organization.id):
        return {spec.id: MetricResult("unavailable") for spec in specs}
    catalogue = {key: metric for key, (_module, metric) in catalogue_for(db, organization.id).items()}
    ctx = OrgMetricContext(db=db, user=user, organization=organization)
    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    by_figure: dict[str, MetricResult] = {}
    results: dict[str, MetricResult] = {}
    for spec in specs:
        figure = f"{spec.metric}|{sorted(spec.params.items())}"
        if figure not in by_figure:
            by_figure[figure] = _evaluate_one(ctx, spec, catalogue, deadline)
        results[spec.id] = by_figure[figure]
    return results


def _evaluate_one(ctx: OrgMetricContext, spec: MetricSpec, catalogue: Mapping[str, OverviewMetric], deadline: float) -> MetricResult:
    """One reference's result; never raises for a figure that cannot be shown."""
    metric = catalogue.get(spec.metric)
    if metric is None:
        return MetricResult("unavailable")
    label = _label_of(spec.metric, metric, spec.params)
    if time.monotonic() > deadline:
        return MetricResult("timeout", unit=metric.unit, label=label)
    try:
        found = metric.evaluate(ctx, spec.params)
    except MetricUnavailable:
        return MetricResult("unavailable", unit=metric.unit, label=label)
    except Exception:  # a failing metric must not blank the whole dashboard
        _log.exception("Organisation dashboard metric %s failed", spec.metric)
        return MetricResult("error", unit=metric.unit, label=label)
    value = found.value if found.value is None or math.isfinite(found.value) else None
    return MetricResult(
        "ok", unit=metric.unit, value=value, breakdown=found.breakdown, detail=found.detail, label=label, projects=len(ctx.projects()),
    )
