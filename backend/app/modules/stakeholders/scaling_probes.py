"""
Module: modules.stakeholders.scaling_probes

The `ScalingProbe`s for the Stakeholders module's artefact types (stakeholder, persona, need, group, engagement,
research finding): how the scaling-shape guard fills and reads them through the API.

Responsibilities:
- Create N records of each type through its real create endpoint and name its list endpoint. A finding belongs to an
  engagement, so its probe creates one engagement and N findings in it.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/stakeholders"


def _creator(path: str, body: Callable[[int], dict[str, Any]]) -> Callable[[Any, str, int, int], list[str]]:
    """A `ScalingProbe.create` that posts `body(n)` to the project's `path` for each record."""

    def create(api: Any, project_id: str, start: int, count: int) -> list[str]:
        return [api.post(f"/projects/{project_id}/{_BASE}/{path}", body(start + i))["id"] for i in range(count)]

    return create


def _typed_creator(
    path: str, types_path: str, field: str, body: Callable[[int], dict[str, Any]]
) -> Callable[[Any, str, int, int], list[str]]:
    """Like `_creator`, but each record takes one of the project's types in turn (`field` is the create payload's type
    column), so a list that names every row's type has to do it in bulk to stay flat."""

    def create(api: Any, project_id: str, start: int, count: int) -> list[str]:
        types = [t["id"] for t in api.get(f"/projects/{project_id}/{_BASE}/{types_path}")]
        return [
            api.post(
                f"/projects/{project_id}/{_BASE}/{path}",
                {**body(start + i), field: types[(start + i) % len(types)] if types else None},
            )["id"]
            for i in range(count)
        ]

    return create


def _engagement(n: int) -> dict[str, Any]:
    return {"title": f"Probe engagement {n}", "channel": "meeting", "engagement_date": "2026-01-15"}


def _create_findings(api: Any, project_id: str, start: int, count: int) -> list[str]:
    engagement_id = api.post(f"/projects/{project_id}/{_BASE}/engagements", _engagement(start))["id"]
    return [
        api.post(
            f"/projects/{project_id}/{_BASE}/engagements/{engagement_id}/findings", {"title": f"Probe finding {start + i}"}
        )["id"]
        for i in range(count)
    ]


SCALING_PROBES = {
    "stakeholder": ScalingProbe(
        list_path=f"{_BASE}/stakeholders",
        create=_typed_creator("stakeholders", "stakeholder-types", "stakeholder_type_id", lambda n: {"name": f"Probe stakeholder {n}"}),
    ),
    "persona": ScalingProbe(
        list_path=f"{_BASE}/personas",
        create=_typed_creator("personas", "persona-types", "persona_type_id", lambda n: {"name": f"Probe persona {n}"}),
    ),
    "stakeholder_need": ScalingProbe(
        list_path=f"{_BASE}/needs", create=_creator("needs", lambda n: {"name": f"Probe need {n}"}),
    ),
    "stakeholder_group": ScalingProbe(
        list_path=f"{_BASE}/stakeholder-groups", create=_creator("stakeholder-groups", lambda n: {"name": f"Probe group {n}"}),
        has_comments=False, has_detail=False,
    ),
    "engagement": ScalingProbe(list_path=f"{_BASE}/engagements", create=_creator("engagements", _engagement)),
    "research_finding": ScalingProbe(list_path=f"{_BASE}/findings", create=_create_findings, has_comments=False),
}
