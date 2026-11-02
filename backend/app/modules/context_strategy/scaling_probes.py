"""
Module: modules.context_strategy.scaling_probes

The `ScalingProbe`s for the five Context & Strategy artefact types (strategy, future state, pain point, guiding
principle, open question): how the scaling-shape guard fills and reads them through the API.

Responsibilities:
- Create N records of each type through its real create endpoint and name its list endpoint.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/context_strategy"


def _creator(path: str, body: Callable[[int], dict[str, Any]]) -> Callable[[Any, str, int, int], list[str]]:
    """A `ScalingProbe.create` that posts `body(n)` to the project's `path` for each record."""

    def create(api: Any, project_id: str, start: int, count: int) -> list[str]:
        return [api.post(f"/projects/{project_id}/{_BASE}/{path}", body(start + i))["id"] for i in range(count)]

    return create


def _create_pain_points(api: Any, project_id: str, start: int, count: int) -> list[str]:
    type_id = api.get(f"/projects/{project_id}/{_BASE}/pain-point-types")[0]["id"]
    return _creator("pain-points", lambda n: {"title": f"Probe pain point {n}", "pain_point_type_id": type_id})(
        api, project_id, start, count
    )


SCALING_PROBES = {
    "strategy": ScalingProbe(
        list_path=f"{_BASE}/strategies",
        create=_creator("strategies", lambda n: {"title": f"Probe strategy {n}", "objective": "Grow."}),
    ),
    "future_state": ScalingProbe(
        list_path=f"{_BASE}/future-states", create=_creator("future-states", lambda n: {"title": f"Probe future state {n}"}),
    ),
    "pain_point": ScalingProbe(list_path=f"{_BASE}/pain-points", create=_create_pain_points),
    "guiding_principle": ScalingProbe(
        list_path=f"{_BASE}/guiding-principles",
        create=_creator(
            "guiding-principles", lambda n: {"name": f"Probe principle {n}", "principle_statement": "Prefer the simple option."}
        ),
    ),
    "open_question": ScalingProbe(
        list_path=f"{_BASE}/open-questions", create=_creator("open-questions", lambda n: {"question": f"Probe question {n}?"}),
    ),
}
