"""
Module: modules.architecture.scaling_probes

The `ScalingProbe`s for the `architecture_element`, `architecture_connection`, `architecture_diagram`,
`architecture_state_machine_diagram` and `architecture_state` artefact types: how the scaling-shape guard fills and reads them through the API.

Responsibilities:
- Create N elements (children of the first, each with a port), N connections (between elements the
  probe creates) or N diagrams (each placing the same few probe elements) through the real create
  endpoints, and name the list endpoints.

Design decisions:
- Every type takes comments through the generic record comments, so each is read at its own `/comments` route.
- Diagrams are of the inside of one scope element and each draws its outer connection as a boundary box, realised by an
  inner connection, so the box reads are part of the measurement.
- Every record goes in a two-level folder, so the folder paths read for a list, a detail and a bundle are measured.
- Each diagram places the same fixed number of elements, so the statements behind a diagram's list, detail and
  bundle export are compared at two diagram counts, not two diagram sizes; the resolver's cost with a large diagram
  is guarded by its own test.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    STATE_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
)
from app.modules.registry import ScalingProbe

_BASE = "modules/architecture"


def _vocabulary_ids(api: Any, project_id: str) -> tuple[str, str]:
    """The first element type and connection type the project offers."""
    element_type = api.get(f"/projects/{project_id}/{_BASE}/element-types")[0]["id"]
    connection_type = api.get(f"/projects/{project_id}/{_BASE}/connection-types")[0]["id"]
    return element_type, connection_type


def _folder_id(api: Any, project_id: str, kind: str, start: int) -> str:
    """A two-level folder for the probe's records (so the folder paths are part of what is measured); the folder is
    created before the records so a probe's last `post` is still the record under test."""
    top = api.post(f"/projects/{project_id}/{_BASE}/{kind}-folders", {"name": f"Probe folder {start}"})
    return api.post(f"/projects/{project_id}/{_BASE}/{kind}-folders", {"name": "Sub", "parent_id": top["id"]})["id"]


def _create_elements(api: Any, project_id: str, start: int, count: int) -> list[str]:
    element_type, connection_type = _vocabulary_ids(api, project_id)
    folder_id = _folder_id(api, project_id, "element", start)
    ids: list[str] = []
    for i in range(count):
        body: dict[str, Any] = {
            "name": f"Probe element {start + i}", "description": "A part of the probe system.", "display_note": "Probe note.",
            "element_type_id": element_type, "folder_id": folder_id,
            "ports": [{"name": "Main", "direction": "both", "connection_type_id": connection_type}],
        }
        if ids:
            body["parent_id"] = ids[0]
        ids.append(api.post(f"/projects/{project_id}/{_BASE}/elements", body)["id"])
    return ids


def _create_connections(api: Any, project_id: str, start: int, count: int) -> list[str]:
    element_type, connection_type = _vocabulary_ids(api, project_id)
    folder_id = _folder_id(api, project_id, "connection", start)
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
                "protocol": "v1", "folder_id": folder_id,
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
    folder_id = _folder_id(api, project_id, "diagram", start)
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
            {
                "name": f"Probe diagram {start + i}", "purpose": "A view of the probe system.", "scope_element_id": scope["id"],
                "folder_id": folder_id,
            },
        )
        diagram = api.put(f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"],
            "placements": [{"element_id": end["id"], "x": order * 200, "y": 0} for order, end in enumerate(ends[:-1])],
            "boundaries": [{"connection_id": outer["id"], "x": -240, "y": 0}],
            "notes": [
                {"text": "Probe note", "x": 0, "y": -120, "tone": "info", "leader_kind": "element", "leader_element_id": ends[0]["id"]},
                {"text": "Probe line note", "x": 200, "y": -120, "leader_kind": "connection", "leader_connection_id": outer["id"]},
                {"text": "Probe spot note", "x": 400, "y": -120, "leader_kind": "point", "leader_x": 440, "leader_y": -220},
            ],
        })
        diagram = api.post(
            f"{base}/diagrams/{diagram['id']}/placements",
            {"version": diagram["version"], "element_id": ends[-1]["id"], "x": (_PLACED - 1) * 200, "y": 0},
        )
        ids.append(diagram["id"])
    return ids


#: The states each probe state machine diagram holds (an initial marker, two nested states and a final marker).
_PROBE_STATES = 4


def _create_state_machines(api: Any, project_id: str, start: int, count: int) -> tuple[list[str], list[str]]:
    """Creates `count` state machine diagrams describing one element, each with the same few states (one nested in
    another) and transitions, and returns the diagram ids and the state ids. Every diagram holds the same fixed number
    of states, so the statements behind the lists, detail, comments and bundle export are compared at two diagram
    counts. The last `post` adds a transition (the request the creation check runs as another person)."""
    element_type, _connection_type = _vocabulary_ids(api, project_id)
    base = f"/projects/{project_id}/{_BASE}"
    element = api.post(f"{base}/elements", {"name": f"Probe behaviour {start}", "element_type_id": element_type})
    diagram_ids: list[str] = []
    state_ids: list[str] = []
    for i in range(count):
        diagram = api.post(
            f"{base}/state-machine-diagrams",
            {"name": f"Probe state machine {start + i}", "description": "The modes of the probe element.", "element_id": element["id"]},
        )
        version = diagram["version"]
        made: list[dict[str, Any]] = []
        for name, kind, parent in (
            ("Start", "initial", None), ("Running", "state", None), ("Idle", "state", 1), ("Stop", "final", None),
        ):
            body = {
                "version": version, "name": f"{name} {start + i}", "kind": kind, "description": "A state of the probe.",
                "entry_action": "start()" if kind == "state" else "", "x": len(made) * 200.0, "y": 0.0,
                "parent_state_id": made[parent]["id"] if parent is not None else None,
            }
            state = api.post(f"{base}/state-machine-diagrams/{diagram['id']}/states", body)
            version = state["state_machine_diagram_version"]
            made.append(state)
        for source, target, event in ((0, 1, ""), (1, 3, "halt"), (2, 2, "tick")):
            transition = api.post(
                f"{base}/state-machine-diagrams/{diagram['id']}/transitions",
                {"version": version, "source_state_id": made[source]["id"], "target_state_id": made[target]["id"], "event": event},
            )
            version = transition["state_machine_diagram_version"]
        diagram_ids.append(diagram["id"])
        state_ids.extend(s["id"] for s in made)
    return diagram_ids, state_ids


def _create_machine_ids(api: Any, project_id: str, start: int, count: int) -> list[str]:
    """Creates `count` state machine diagrams and returns their ids."""
    return _create_state_machines(api, project_id, start, count)[0]


def _create_state_ids(api: Any, project_id: str, start: int, count: int) -> list[str]:
    """Creates enough state machine diagrams to hold `count` states and returns the state ids (rounded up to whole
    diagrams, so the list's size is a multiple of `_PROBE_STATES`)."""
    diagrams = max(1, -(-count // _PROBE_STATES))
    return _create_state_machines(api, project_id, start, diagrams)[1]


SCALING_PROBES = {
    ELEMENT_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/elements", create=_create_elements),
    CONNECTION_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/connections", create=_create_connections),
    DIAGRAM_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/diagrams", create=_create_diagrams),
    STATE_MACHINE_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/state-machine-diagrams", create=_create_machine_ids),
    STATE_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/states", create=_create_state_ids, has_comments=False),
}
