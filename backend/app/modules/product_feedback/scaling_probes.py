"""
Module: modules.product_feedback.scaling_probes

The `ScalingProbe` for the `enhancement_request` artefact type: how the scaling-shape guard fills and reads
requests through the API.

Responsibilities:
- Create N requests through the real create endpoint (only a title is required) and name the list endpoint.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/product_feedback"


def _create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    return [
        api.post(
            f"/projects/{project_id}/{_BASE}/requests",
            {"title": f"Probe request {start + i}", "description": "Let me export this list."},
        )["id"]
        for i in range(count)
    ]


SCALING_PROBES = {"enhancement_request": ScalingProbe(list_path=f"{_BASE}/requests", create=_create)}
