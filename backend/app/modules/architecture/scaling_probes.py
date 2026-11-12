"""
Module: modules.architecture.scaling_probes

The `ScalingProbe`s for the `architecture_element` and `architecture_connection` artefact types: how the
scaling-shape guard fills and reads them through the API.

Responsibilities:
- Create N elements (children of the first, each with a port) or N connections (between elements the
  probe creates) through the real create endpoints, and name the list endpoints.

Design decisions:
- Neither type has a comment thread, so `has_comments` is off.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
from app.modules.registry import ScalingProbe

_BASE = "modules/architecture"


def _vocabulary_ids(api: Any, project_id: str) -> tuple[str, str]:
    """The first element type and connection type the project offers."""
    element_type = api.get(f"/projects/{project_id}/{_BASE}/element-types")[0]["id"]
    connection_type = api.get(f"/projects/{project_id}/{_BASE}/connection-types")[0]["id"]
    return element_type, connection_type


def _create_elements(api: Any, project_id: str, start: int, count: int) -> list[str]:
    element_type, connection_type = _vocabulary_ids(api, project_id)
    ids: list[str] = []
    for i in range(count):
        body: dict[str, Any] = {
            "name": f"Probe element {start + i}", "description": "A part of the probe system.",
            "element_type_id": element_type,
            "ports": [{"name": "Main", "direction": "both", "connection_type_id": connection_type}],
        }
        if ids:
            body["parent_id"] = ids[0]
        ids.append(api.post(f"/projects/{project_id}/{_BASE}/elements", body)["id"])
    return ids


def _create_connections(api: Any, project_id: str, start: int, count: int) -> list[str]:
    element_type, connection_type = _vocabulary_ids(api, project_id)
    ends = [
        api.post(
            f"/projects/{project_id}/{_BASE}/elements",
            {"name": f"Probe end {start + i}", "element_type_id": element_type, "ports": [{"name": "Main"}]},
        )
        for i in range(count + 1)
    ]
    return [
        api.post(
            f"/projects/{project_id}/{_BASE}/connections",
            {
                "name": f"Probe connection {start + i}", "connection_type_id": connection_type,
                "source_element_id": ends[i]["id"], "source_port_id": ends[i]["ports"][0]["id"],
                "target_element_id": ends[i + 1]["id"], "target_port_id": ends[i + 1]["ports"][0]["id"],
                "protocol": "v1",
            },
        )["id"]
        for i in range(count)
    ]


SCALING_PROBES = {
    ELEMENT_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/elements", create=_create_elements, has_comments=False),
    CONNECTION_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/connections", create=_create_connections, has_comments=False),
}
