"""
Module: services.scaling_probes_core

The `ScalingProbe`s of the core artefact types (requirements, actions and change requests): how the scaling-shape guard
(`tests/test_scaling_shapes.py`) fills each through its public API.

Responsibilities:
- Declare, per core type, the list endpoint and a `create` that makes N records through the real create endpoint.

Design decisions:
- Core owns these types, so they register here; a module's types are registered by the module on
  `ModuleDefinition.scaling_probes`, never listed here.
- Records are made through the API, not the ORM, so a probe exercises the same create path, gates, numbering and audit
  a person does, and cannot drift from them.
- A probe fetches its own prerequisites (component, category, action type, a modifiable requirement) on every call; the
  guard calls it once per data size.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe


def _component_and_category(api: Any, project_id: str) -> tuple[str, str]:
    """The project's first component and category, creating them when it has none."""
    base = f"/projects/{project_id}"
    components = api.get(f"{base}/components")
    component_id = components[0]["id"] if components else api.post(
        f"{base}/components", {"name": "Software", "prefix": "SW"}
    )["id"]
    categories = api.get(f"{base}/categories")
    category_id = categories[0]["id"] if categories else api.post(
        f"{base}/categories", {"name": "Performance", "prefix": "PERF", "component_id": component_id}
    )["id"]
    return component_id, category_id


def _create_requirements(api: Any, project_id: str, start: int, count: int) -> list[str]:
    component_id, category_id = _component_and_category(api, project_id)
    return [
        api.post(
            f"/projects/{project_id}/requirements",
            {"name": f"Probe requirement {start + i}", "component_id": component_id, "category_id": category_id,
             "keywords": [f"kw{start + i}"]},
        )["id"]
        for i in range(count)
    ]


def _create_actions(api: Any, project_id: str, start: int, count: int) -> list[str]:
    action_type_id = api.get(f"/projects/{project_id}/action-types")[0]["id"]
    return [
        api.post(f"/projects/{project_id}/actions", {"title": f"Probe action {start + i}", "action_type_id": action_type_id})["id"]
        for i in range(count)
    ]


def _create_change_requests(api: Any, project_id: str, start: int, count: int) -> list[str]:
    component_id, category_id = _component_and_category(api, project_id)
    return [
        api.post(
            f"/projects/{project_id}/change-requests",
            {"kind": "new_requirement", "proposed_name": f"Probe change {start + i}", "proposed_component_id": component_id,
             "proposed_category_id": category_id, "reason": "Scaling probe"},
        )["id"]
        for i in range(count)
    ]


CORE_SCALING_PROBES: dict[str, ScalingProbe] = {
    "requirement": ScalingProbe(list_path="requirements", create=_create_requirements),
    "requirement_action": ScalingProbe(list_path="actions", create=_create_actions),
    "change_request": ScalingProbe(list_path="change-requests", create=_create_change_requests),
}
