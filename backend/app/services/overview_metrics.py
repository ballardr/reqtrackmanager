"""
Module: services.overview_metrics

The bounded catalogue of figures the project overview's widgets show, and the batched evaluation behind them.

Responsibilities:
- Define the core metrics (requirement and change request counts, completion, files, breakdowns, stage progress,
  records by type, and a generic record count with the list filters) and merge those a module contributes
  (`ModuleDefinition.overview_metrics`).
- Validate a metric reference (`metric` key and `params`) against the catalogue, for a stored layout and for a
  request alike, so a configuration can reach only what a metric defines.
- Evaluate a batch of references for a caller in one pass: identical references once, a cap on the batch, a time
  budget, and a state per result instead of a failure of the whole batch. Each reference names its own project
  scope (this project, with parents, with children, or both), so one overview can show a project's own count beside
  a roll-up of its children.

Design decisions:
- A metric is never an arbitrary query. Filters on a record count are limited to the type's declared
  `filter_params` plus the shared tag and placement filters, the same vocabulary its list accepts.
- Components and categories in a filter are named by prefix (`API`, `API/UX`), not id, so a stored layout is
  portable across a bundle, a template clone and a child project that inherits it; they resolve to ids in the
  project being read, and a name with no match counts nothing.
- A figure the caller may not read (a type whose module is off, or without the `view` permission) is reported as
  `unavailable`, never as zero, because a zero would reveal nothing but a count would reveal that hidden records exist.
- No module is named here: module metrics and record types come from the registry.

External dependencies: `modules.registry`, `services.record_counts`, `services.project_counts`,
`services.project_scope`, `services.tags`.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.user import User
from app.modules.registry import (
    OverviewMetric,
    OverviewMetricValue,
    RecordFilters,
    artefact_type_module,
    get_overview_metrics,
    get_record_table_providers,
    is_module_enabled,
)
from app.modules.registry import is_module_enabled_for_project as module_enabled_for_project
from app.services.client_date import effective_today
from app.services.project_counts import ProjectCounts, project_counts, project_stage_progress
from app.services.project_scope import ProjectScope, gate_open
from app.services.record_counts import count_record_type, count_records_by_type, readable_provider
from app.services.stage_phase_plans import phase_attention_counts
from app.services.tags import TagFilter

#: Most references one request may carry.
MAX_METRICS_PER_REQUEST = 24

#: Seconds a request may spend evaluating; references not reached are reported as `timeout`.
TIME_BUDGET_SECONDS = 8.0

#: Tag and placement filters every record count accepts, besides the type's own `filter_params`.
SHARED_FILTERS = frozenset({"tag", "tag_mode", "component", "category"})

#: Most values one filter may list, and the longest value.
_MAX_FILTER_VALUES = 20
_MAX_FILTER_VALUE_LENGTH = 200

#: Matches no component or category; used when a filter names one this project does not have.
_NO_MATCH = uuid.UUID(int=0)

RECORD_COUNT_KEY = "record_count"

#: The project scopes a figure may be read in (`services.project_scope`).
ScopeName = Literal["this", "parents", "children", "both"]

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhaseAttention:
    """One project's scheduled phases that are overdue or start soon (`id` is the project id, as `collect` needs)."""

    id: uuid.UUID
    overdue: int
    upcoming: int


class MetricUnavailable(Exception):
    """The caller may not read this figure here (type, module or permission), so it is shown as unavailable."""


@dataclass
class MetricContext:
    """What a metric's `evaluate` receives for one request.

    Attributes:
        db: Active session (read only).
        user: The caller.
        project: The request project.
        project_scope: The overview's `?project_scope=`.
    """

    db: Session
    user: User
    project: Project
    project_scope: ProjectScope
    _counts: list[ProjectCounts] | None = field(default=None, repr=False)

    def counts(self) -> list[ProjectCounts]:
        """The requirement and change request counts of every project in scope, read once per request."""
        if self._counts is None:
            self._counts = self.project_scope.collect(
                self.db, self.project, self.user.id, "requirement", lambda pid: [project_counts(self.db, pid)],
            )
        return self._counts

    def own(self) -> ProjectCounts:
        """The request project's own counts."""
        return next(c for c in self.counts() if c.id == self.project.id)


# --- core metrics ------------------------------------------------------------------------------------


def _scalar(read: Callable[[MetricContext], float]) -> Callable[[MetricContext, Mapping[str, Any]], OverviewMetricValue]:
    """An `evaluate` for a single figure read from the context."""
    return lambda ctx, params: OverviewMetricValue(value=float(read(ctx)))


def _percent_complete(ctx: MetricContext) -> float:
    """Completed share of the live requirements in scope, one decimal."""
    total = sum(c.requirements for c in ctx.counts())
    done = sum(c.completed for c in ctx.counts())
    return round(done / total * 100.0, 1) if total else 0.0


def _requirements_by_status(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """Live requirements by status, in scope."""
    merged: dict[str, int] = {}
    for c in ctx.counts():
        for key, value in c.by_status.items():
            merged[key] = merged.get(key, 0) + value
    return OverviewMetricValue(breakdown=[(key, key, float(value)) for key, value in merged.items()])


def _change_requests_by_outcome(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """Change requests by outcome, in scope (`active`, `approved`, `rejected`)."""
    counts = ctx.counts()
    rows = [
        ("active", "Proposed", float(sum(c.proposed for c in counts))),
        ("approved", "Approved", float(sum(c.approved for c in counts))),
        ("rejected", "Rejected", float(sum(c.rejected for c in counts))),
    ]
    return OverviewMetricValue(breakdown=rows)


def _phase_attention(index: int) -> Callable[[MetricContext, Mapping[str, Any]], OverviewMetricValue]:
    """An `evaluate` for the scheduled phases that are overdue (`0`) or start soon (`1`) across the scope's projects."""

    def evaluate(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
        today = effective_today()
        found = ctx.project_scope.collect(
            ctx.db, ctx.project, ctx.user.id, "requirement",
            lambda pid: [PhaseAttention(pid, *phase_attention_counts(ctx.db, ctx.db.get(Project, pid) or ctx.project, today))],
            id_of=lambda row: row.id,
        )
        return OverviewMetricValue(value=float(sum((row.overdue, row.upcoming)[index] for row in found)))

    return evaluate


def _stage_progress(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """Each stage's completion percentage; always the request project's own stages."""
    rows = project_stage_progress(ctx.db, ctx.project.id, ctx.own().requirements)
    return OverviewMetricValue(
        breakdown=[(str(r.stage_id), r.name, r.completed_percent) for r in rows],
        detail={str(r.stage_id): r.phase_name for r in rows},
    )


def _records_by_type(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """Records of each readable type in scope (the overview's total-records chart)."""
    found = count_records_by_type(ctx.db, ctx.user, ctx.project, ctx.project_scope)
    return OverviewMetricValue(value=float(sum(c.count for c in found)), breakdown=[(c.type, c.label, float(c.count)) for c in found])


def _record_count(ctx: MetricContext, params: Mapping[str, Any]) -> OverviewMetricValue:
    """How many records of one type match the configured filters.

    Raises:
        MetricUnavailable: The caller may not read the type in this project.
    """
    record_type = str(params["record_type"])
    provider = readable_provider(ctx.db, ctx.user, ctx.project, record_type)
    if provider is None:
        raise MetricUnavailable
    filters, tag_filter_for = build_record_filters(ctx.db, params.get("filters") or {}, provider.filter_params)
    total = count_record_type(
        ctx.db, ctx.user, ctx.project, ctx.project_scope, record_type, filters=filters, tag_filter_for=tag_filter_for,
    )
    if total is None:
        raise MetricUnavailable
    return OverviewMetricValue(value=float(total))


def core_metrics() -> dict[str, OverviewMetric]:
    """The metrics every project has, by key."""
    return {
        "requirement_count": OverviewMetric("Requirements", "count", _scalar(lambda c: sum(x.requirements for x in c.counts()))),
        "requirement_completed_percent": OverviewMetric("Requirements complete", "percent", _scalar(_percent_complete)),
        "phases_overdue": OverviewMetric("Phases overdue", "count", _phase_attention(0)),
        "phases_upcoming": OverviewMetric("Phases starting soon", "count", _phase_attention(1)),
        "file_count": OverviewMetric("Files", "count", _scalar(lambda c: sum(x.files for x in c.counts()))),
        "change_requests_proposed": OverviewMetric("Change requests proposed", "count", _scalar(lambda c: sum(x.proposed for x in c.counts()))),
        "change_requests_approved": OverviewMetric("Change requests approved", "count", _scalar(lambda c: sum(x.approved for x in c.counts()))),
        "change_requests_rejected": OverviewMetric("Change requests rejected", "count", _scalar(lambda c: sum(x.rejected for x in c.counts()))),
        "requirements_by_status": OverviewMetric("Requirements by status", "count", _requirements_by_status, breakdown=True, scalar=False),
        "change_requests_by_outcome": OverviewMetric(
            "Change requests by outcome", "count", _change_requests_by_outcome, breakdown=True, scalar=False,
        ),
        "stage_progress": OverviewMetric("Stage progress", "percent", _stage_progress, breakdown=True, scalar=False),
        "records_by_type": OverviewMetric("Records by type", "count", _records_by_type, breakdown=True),
        RECORD_COUNT_KEY: OverviewMetric("Record count", "count", _record_count, params=frozenset({"record_type", "filters"})),
    }


def all_metrics() -> dict[str, OverviewMetric]:
    """Every metric a stored layout may name: the core metrics and each module's (`<module_key>:<key>`), enabled or not."""
    merged = core_metrics()
    for key, (_module_key, metric) in get_overview_metrics().items():
        merged[key] = metric
    return merged


def metrics_for_project(db: Session, project: Project) -> dict[str, tuple[str | None, OverviewMetric]]:
    """The metrics the project can show, as `{key: (module_key, metric)}`: the core ones and each enabled module's."""
    found: dict[str, tuple[str | None, OverviewMetric]] = {key: (None, metric) for key, metric in core_metrics().items()}
    for key, (module_key, metric) in get_overview_metrics().items():
        if module_enabled_for_project(db, project.id, module_key):
            found[key] = (module_key, metric)
    return found


# --- validation --------------------------------------------------------------------------------------


def _refuse(message: str) -> HTTPException:
    """A 422 with `message`."""
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _text_values(name: str, raw: Any) -> list[str]:
    """`raw` as a short list of short plain strings.

    Raises:
        HTTPException: 422 for a non-list, too many values, or a value that is not a short single-line string.
    """
    if not isinstance(raw, list) or len(raw) > _MAX_FILTER_VALUES:
        raise _refuse(f"The filter '{name}' must list at most {_MAX_FILTER_VALUES} values.")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_FILTER_VALUE_LENGTH or not item.isprintable():
            raise _refuse(f"A value of the filter '{name}' is not valid.")
        values.append(item.strip())
    return values


def validate_filters(raw: Any, record_type: str) -> dict[str, list[str]]:
    """Checks a record count's `filters` and returns them cleaned.

    Args:
        raw: The `filters` value as stored or sent.
        record_type: The counted type, whose `filter_params` bound the names.

    Raises:
        HTTPException: 422 for a name the type's list does not accept, or a value that is not valid.
    """
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise _refuse("The filters must be a set of named lists.")
    provider = get_record_table_providers()[record_type]
    allowed = provider.filter_params | SHARED_FILTERS
    cleaned: dict[str, list[str]] = {}
    for name, values in raw.items():
        if name not in allowed:
            raise _refuse(f"This record type cannot be filtered by '{name}'.")
        listed = _text_values(name, values)
        if name == "tag_mode" and (len(listed) != 1 or listed[0] not in ("any", "all")):
            raise _refuse("The tag match must be 'any' or 'all'.")
        if listed:
            cleaned[name] = listed
    return cleaned


def validate_params(metric_key: str, metric: OverviewMetric, raw: Any) -> dict[str, Any]:
    """Checks a metric reference's `params` and returns them cleaned.

    Args:
        metric_key: The metric's catalogue key.
        metric: Its definition.
        raw: The `params` value as stored or sent.

    Raises:
        HTTPException: 422 for a parameter the metric does not declare, an unknown record type, or invalid filters.
    """
    if raw in (None, {}):
        raw = {}
    if not isinstance(raw, dict):
        raise _refuse("The metric settings must be a set of named values.")
    unknown = sorted(set(raw) - metric.params)
    if unknown:
        raise _refuse(f"The metric does not accept: {', '.join(unknown)}.")
    if metric_key == RECORD_COUNT_KEY:
        record_type = raw.get("record_type")
        if not isinstance(record_type, str) or record_type not in get_record_table_providers():
            raise _refuse("Choose a record type to count.")
        cleaned: dict[str, Any] = {"record_type": record_type}
        filters = validate_filters(raw.get("filters"), record_type)
        if filters:
            cleaned["filters"] = filters
        return cleaned
    cleaned = {}
    for name, value in raw.items():
        listed = value if isinstance(value, list) else [value]
        if len(listed) > _MAX_FILTER_VALUES or any(
            not isinstance(v, str | int | float | bool) or (isinstance(v, str) and len(v) > _MAX_FILTER_VALUE_LENGTH) for v in listed
        ):
            raise _refuse(f"The setting '{name}' is not valid.")
        cleaned[name] = value
    return cleaned


def validate_reference(raw_metric: Any, raw_params: Any) -> tuple[str, dict[str, Any]]:
    """Checks a `metric` key and its `params` against the catalogue.

    Raises:
        HTTPException: 422 for an unknown metric or invalid params.
    """
    catalogue = all_metrics()
    if not isinstance(raw_metric, str) or raw_metric not in catalogue:
        raise _refuse("Choose a metric from the list.")
    return raw_metric, validate_params(raw_metric, catalogue[raw_metric], raw_params)


# --- record filters ----------------------------------------------------------------------------------


def build_record_filters(
    db: Session, filters: Mapping[str, list[str]], filter_params: frozenset[str],
) -> tuple[RecordFilters, Callable[[uuid.UUID], TagFilter | None] | None]:
    """The list filters and the per-project tag/placement filter for a record count's `filters`.

    Args:
        db: Active session (read only).
        filters: Validated filters (`validate_filters`).
        filter_params: The type's own list filters.

    Returns:
        The provider's `RecordFilters`, and a function building the `TagFilter` for one project (components and
        categories are resolved by prefix in that project), or `None` when no tag or placement filter is set.
    """
    own = RecordFilters(values={name: values for name, values in filters.items() if name in filter_params})
    tags = filters.get("tag", [])
    mode = (filters.get("tag_mode") or ["any"])[0]
    components = filters.get("component", [])
    categories = filters.get("category", [])
    if not (tags or components or categories):
        return own, None

    def for_project(project_id: uuid.UUID) -> TagFilter:
        component_ids: list[uuid.UUID] = []
        category_ids: list[uuid.UUID] = []
        if components:
            component_ids = list(db.scalars(
                select(ProjectComponent.id).where(ProjectComponent.project_id == project_id, ProjectComponent.prefix.in_(components))
            ).all())
        if categories:
            wanted = [tuple(value.split("/", 1)) for value in categories if "/" in value]
            if wanted:
                rows = db.execute(
                    select(ProjectCategory.id, ProjectComponent.prefix, ProjectCategory.prefix)
                    .join(ProjectComponent, ProjectComponent.id == ProjectCategory.component_id)
                    .where(ProjectComponent.project_id == project_id, ProjectCategory.prefix.in_({w[1] for w in wanted}))
                ).all()
                category_ids = [row[0] for row in rows if (row[1], row[2]) in set(wanted)]
        if (components or categories) and not (component_ids or category_ids):
            component_ids = [_NO_MATCH]
        return TagFilter(tag=list(tags), tag_mode="all" if mode == "all" else "any", component_id=component_ids, category_id=category_ids)

    return own, for_project


# --- evaluation --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricSpec:
    """One reference in a request: the caller's `id` for it, the metric key, its params and its project scope."""

    id: str
    metric: str
    params: dict[str, Any]
    scope: ScopeName = "this"


@dataclass(frozen=True)
class MetricResult:
    """The outcome of one reference.

    Attributes:
        state: `ok`, `unavailable` (not readable here, or the metric's module is off), `timeout` (the batch's time
            budget ran out first) or `error` (the metric failed; details are logged, never returned).
        unit: The metric's unit, when known.
        label: The metric's name (for a record count, the counted type's plural name), the default widget title.
        projects: How many projects the figure covers (1 unless its scope was widened).
        value: The single figure.
        breakdown: `(key, label, value)` rows.
        detail: Text per breakdown key.
    """

    state: str
    unit: str | None = None
    value: float | None = None
    breakdown: list[tuple[str, str, float]] | None = None
    detail: dict[str, str] = field(default_factory=dict)
    label: str | None = None
    projects: int = 1


def _label_of(metric_key: str, metric: OverviewMetric, params: Mapping[str, Any]) -> str:
    """The default title of a figure: the metric's name, or the counted type's plural name for a record count."""
    if metric_key == RECORD_COUNT_KEY:
        provider = get_record_table_providers().get(str(params.get("record_type")))
        if provider is not None:
            return provider.label
    return metric.label


def canonical(spec: MetricSpec) -> str:
    """A key equal for two references that ask for the same figure."""
    return json.dumps({"metric": spec.metric, "params": spec.params, "scope": spec.scope}, sort_keys=True, default=str)


def evaluate_batch(db: Session, user: User, project: Project, specs: list[MetricSpec]) -> dict[str, MetricResult]:
    """Evaluates every reference, once per distinct figure (a figure is a metric, its params and its scope).

    Args:
        db: Active session (read only).
        user: The caller (already allowed to open `project`).
        project: The request project.
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
    available = metrics_for_project(db, project)
    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    contexts: dict[str, MetricContext] = {}
    by_figure: dict[str, MetricResult] = {}
    results: dict[str, MetricResult] = {}
    for spec in specs:
        key = canonical(spec)
        if key not in by_figure:
            # One context per scope, so the requirement and change request counts of a scope are read once.
            ctx = contexts.setdefault(spec.scope, MetricContext(db=db, user=user, project=project, project_scope=ProjectScope(spec.scope)))
            by_figure[key] = _evaluate_one(ctx, spec, available, deadline)
        results[spec.id] = by_figure[key]
    return results


def _evaluate_one(
    ctx: MetricContext, spec: MetricSpec, available: Mapping[str, tuple[str | None, OverviewMetric]], deadline: float,
) -> MetricResult:
    """One reference's result; never raises for a figure that cannot be shown."""
    entry = available.get(spec.metric)
    if entry is None:
        return MetricResult("unavailable")
    _module_key, metric = entry
    label = _label_of(spec.metric, metric, spec.params)
    if metric.gate is not None and not gate_open(ctx.db, ctx.project.id, metric.gate):
        return MetricResult("unavailable", unit=metric.unit, label=label)
    if time.monotonic() > deadline:
        return MetricResult("timeout", unit=metric.unit, label=label)
    try:
        found = metric.evaluate(ctx, spec.params)
    except MetricUnavailable:
        return MetricResult("unavailable", unit=metric.unit, label=label)
    except Exception:  # a failing metric must not blank the whole overview
        _log.exception("Overview metric %s failed", spec.metric)
        return MetricResult("error", unit=metric.unit, label=label)
    value = found.value if found.value is None or math.isfinite(found.value) else None
    projects = len(ctx.project_scope.projects(ctx.db, ctx.project, ctx.user.id)) if ctx.project_scope.widened else 1
    return MetricResult("ok", unit=metric.unit, value=value, breakdown=found.breakdown, detail=found.detail, label=label, projects=projects)


# --- catalogue for the editor ------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordTypeOption:
    """A record type the editor offers for a record count, with the filters its list takes."""

    type: str
    label: str
    filter_params: list[str]


def record_type_options(db: Session, user: User, project: Project) -> list[RecordTypeOption]:
    """The record types the caller may count in `project`, with each type's own list filters (sorted by label)."""
    options: list[RecordTypeOption] = []
    for artefact_type in get_record_table_providers():
        provider = readable_provider(db, user, project, artefact_type)
        if provider is not None:
            options.append(RecordTypeOption(artefact_type, provider.label, sorted(provider.filter_params)))
    return sorted(options, key=lambda option: option.label)


def organization_record_type_options(db: Session, organization_id: uuid.UUID) -> list[RecordTypeOption]:
    """The record types an organisation default may count: every type that counts in the overview, whose module the
    organisation has enabled (a core type always qualifies)."""
    options: list[RecordTypeOption] = []
    for artefact_type, provider in get_record_table_providers().items():
        if not provider.in_overview:
            continue
        definition = artefact_type_module(artefact_type)
        if definition is not None and not is_module_enabled(db, organization_id, definition.key):
            continue
        options.append(RecordTypeOption(artefact_type, provider.label, sorted(provider.filter_params)))
    return sorted(options, key=lambda option: option.label)


def organization_metrics(db: Session, organization_id: uuid.UUID) -> dict[str, tuple[str | None, OverviewMetric]]:
    """The metrics an organisation default can name: the core ones and each module's the organisation has enabled."""
    found: dict[str, tuple[str | None, OverviewMetric]] = {key: (None, metric) for key, metric in core_metrics().items()}
    for key, (module_key, metric) in get_overview_metrics().items():
        if is_module_enabled(db, organization_id, module_key):
            found[key] = (module_key, metric)
    return found


__all__ = [
    "MAX_METRICS_PER_REQUEST", "MetricContext", "MetricResult", "MetricSpec", "MetricUnavailable", "RecordTypeOption",
    "all_metrics", "build_record_filters", "core_metrics", "evaluate_batch", "metrics_for_project", "organization_metrics",
    "organization_record_type_options", "record_type_options", "validate_filters", "validate_params", "validate_reference",
]
