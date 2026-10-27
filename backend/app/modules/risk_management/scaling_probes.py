"""
Module: modules.risk_management.scaling_probes

The `ScalingProbe` for the `risk` artefact type: how the scaling-shape guard fills and reads risks through the API.

Responsibilities:
- Create N risks through the real create endpoint (only a title is required) and name the list endpoint.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/risk_management"


def _create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    return [
        api.post(f"/projects/{project_id}/{_BASE}/risks", {"title": f"Probe risk {start + i}", "statement": "If a, then b."})["id"]
        for i in range(count)
    ]


SCALING_PROBES = {"risk": ScalingProbe(list_path=f"{_BASE}/risks", create=_create)}
