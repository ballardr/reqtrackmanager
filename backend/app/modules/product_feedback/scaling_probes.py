"""
Module: modules.product_feedback.scaling_probes

The `ScalingProbe` for `enhancement_request`: creates N requests through the
real create endpoint (only a title is required) and names the list endpoint,
for the scaling-shape guard. Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/product_feedback"


def _create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    systems = [e["id"] for e in api.get(f"/projects/{project_id}/external-systems")]
    return [
        api.post(
            f"/projects/{project_id}/{_BASE}/requests",
            {
                "title": f"Probe request {start + i}", "description": "Let me export this list.",
                "references": [{"system_id": systems[i % len(systems)], "key": f"PROJ-{start + i}"}] if systems else [],
            },
        )["id"]
        for i in range(count)
    ]


SCALING_PROBES = {"enhancement_request": ScalingProbe(list_path=f"{_BASE}/requests", create=_create)}
