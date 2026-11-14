"""
Module: modules.architecture.allocation_metrics

The allocation figures a project overview tile or gauge can show (`ModuleDefinition.overview_metrics`): how much of
the requirements document is allocated to an element, and what is left to decide. Each reads `allocation.coverage`, so
a figure on the overview and on the allocation screens cannot differ; the overview reads it once per request.

Design decisions (Decided by: Agent):
- Figures cover the request project only: a component, a requirement and an element belong to one project, and the
  overview's nested-project scope is for core record counts.
- A project with no requirement shows 0% allocated rather than an undefined figure.

Dependencies: `modules.architecture.allocation`, `modules.registry` (the metric types).
"""

from __future__ import annotations

from app.modules.architecture import allocation
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY
from app.modules.registry import OverviewMetric, OverviewMetricValue

_GATE = (ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)


def _percent_allocated(ctx, _params) -> OverviewMetricValue:
    """Requirements allocated to at least one element, as a percentage of the project's requirements."""
    found = allocation.coverage(ctx.db, ctx.project)
    return OverviewMetricValue(value=round(100 * found.allocated_requirements / found.requirements, 1) if found.requirements else 0.0)


def _unallocated(ctx, _params) -> OverviewMetricValue:
    """Requirements with no element allocated."""
    found = allocation.coverage(ctx.db, ctx.project)
    return OverviewMetricValue(value=float(found.requirements - found.allocated_requirements))


def _elements_without_requirement(ctx, _params) -> OverviewMetricValue:
    """The project's elements no requirement is allocated to."""
    found = allocation.coverage(ctx.db, ctx.project)
    return OverviewMetricValue(value=float(found.elements - found.allocated_elements))


def _suggestions(ctx, _params) -> OverviewMetricValue:
    """Suggested allocations awaiting a decision."""
    return OverviewMetricValue(value=float(allocation.coverage(ctx.db, ctx.project).suggestions))


OVERVIEW_METRICS: dict[str, OverviewMetric] = {
    "requirements_allocated": OverviewMetric("Requirements allocated", "percent", _percent_allocated, gate=_GATE),
    "requirements_unallocated": OverviewMetric("Requirements not allocated", "count", _unallocated, gate=_GATE),
    "elements_without_requirement": OverviewMetric(
        "Elements with no requirement", "count", _elements_without_requirement, gate=_GATE,
    ),
    "suggested_allocations": OverviewMetric("Suggested allocations", "count", _suggestions, gate=_GATE),
}
