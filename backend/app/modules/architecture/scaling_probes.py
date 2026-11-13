"""
Module: modules.architecture.scaling_probes

The `ScalingProbe`s for the `architecture_element`, `architecture_connection` and `architecture_diagram`
artefact types: how the scaling-shape guard fills and reads them through the API.

Responsibilities:
- Create N elements (children of the first, each with a port), N connections (between elements the
  probe creates) or N diagrams (each placing the same few probe elements) through the real create
  endpoints, and name the list endpoints.

Design decisions:
- No type has a comment thread, so `has_comments` is off.
- Diagrams are of the inside of one scope element and each draws its outer connection as a boundary box, realised by an
  inner connection, so the box reads are part of the measurement.
- Each diagram places the same fixed number of elements, so the statements behind a diagram's list, detail and
  bundle export are compared at two diagram counts, not two diagram sizes; the resolver's cost with a large diagram
  is guarded by its own test.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.architecture.service import CONNECTION_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE, ELEMENT_ARTEFACT_TYPE
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


#: How many elements each probe diagram places.
_PLACED = 3


def _create_diagrams(api: Any, project_id: str, start: int, count: int) -> list[str]:
    """Creates `count` diagrams of the inside of one scope element, each placing the same inner elements and drawing the
    scope's outer connection as a boundary box that an inner connection realises, so the boundary reads and the bundle
    section are measured. The last `post` places an element (the request the creation check runs as another person)."""
    element_type, connection_type = _vocabulary_ids(api, project_id)
    base = f"/projects/{project_id}/{_BASE}"
    scope = api.post(f"{base}/elements", {"name": f"Probe scope {start}", "element_type_id": element_type, "ports": [{"name": "Main"}]})
    outside = api.post(f"{base}/elements", {"name": f"Probe outside {start}", "element_type_id": element_type})
    ends = [
        api.post(
            f"{base}/elements",
            {"name": f"Probe diagram element {start}-{i}", "element_type_id": element_type, "parent_id": scope["id"], "ports": [{"name": "Main"}]},
        )
        for i in range(_PLACED)
    ]
    api.post(
        f"{base}/connections",
        {
            "name": f"Probe diagram connection {start}", "connection_type_id": connection_type,
            "source_element_id": ends[0]["id"], "target_element_id": ends[1]["id"],
        },
    )
    outer = api.post(
        f"{base}/connections",
        {
            "name": f"Probe outer connection {start}", "connection_type_id": connection_type,
            "source_element_id": scope["id"], "target_element_id": outside["id"],
        },
    )
    inner = api.post(
        f"{base}/connections",
        {
            "name": f"Probe realising connection {start}", "connection_type_id": connection_type,
            "source_element_id": ends[0]["id"], "target_element_id": scope["id"],
        },
    )
    api.put(f"{base}/connections/{inner['id']}/realisations", {"version": inner["version"], "outer_connection_ids": [outer["id"]]})
    ids: list[str] = []
    for i in range(count):
        diagram = api.post(
            f"{base}/diagrams",
            {"name": f"Probe diagram {start + i}", "purpose": "A view of the probe system.", "scope_element_id": scope["id"]},
        )
        diagram = api.put(f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"],
            "placements": [{"element_id": end["id"], "x": order * 200, "y": 0} for order, end in enumerate(ends[:-1])],
            "boundaries": [{"connection_id": outer["id"], "x": -240, "y": 0}],
        })
        diagram = api.post(
            f"{base}/diagrams/{diagram['id']}/placements",
            {"version": diagram["version"], "element_id": ends[-1]["id"], "x": (_PLACED - 1) * 200, "y": 0},
        )
        ids.append(diagram["id"])
    return ids


SCALING_PROBES = {
    ELEMENT_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/elements", create=_create_elements, has_comments=False),
    CONNECTION_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/connections", create=_create_connections, has_comments=False),
    DIAGRAM_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/diagrams", create=_create_diagrams, has_comments=False),
}
