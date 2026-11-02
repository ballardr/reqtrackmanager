"""
Module: modules.decisions.scaling_probes

The `ScalingProbe` for the `decision` artefact type: how the scaling-shape guard fills and reads decisions through the API.

Responsibilities:
- Create N decisions through the real create endpoint (the first decision type of the project) and name the list endpoint.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/decisions"


def _create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    decision_type_id = api.get(f"/projects/{project_id}/{_BASE}/decision-types")[0]["id"]
    return [
        api.post(
            f"/projects/{project_id}/{_BASE}",
            {"title": f"Probe decision {start + i}", "decision_statement": "We will do x.", "decision_type_id": decision_type_id},
        )["id"]
        for i in range(count)
    ]


SCALING_PROBES = {"decision": ScalingProbe(list_path=_BASE, create=_create)}
