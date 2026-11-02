"""
Module: modules.compliance.scaling_probes

The `ScalingProbe` for the `compliance_evidence` artefact type. The other three compliance types are produced by
assigning a standard to a project (an assessment per requirement and an assessment per required action), not created
one at a time, so they have no probe.

Responsibilities:
- Create N evidence records through the real create endpoint (only a title is required) and name the list endpoint.

Dependencies: `modules.registry` (`ScalingProbe`).
"""

from __future__ import annotations

from typing import Any

from app.modules.registry import ScalingProbe

_BASE = "modules/compliance"


def _create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    return [api.post(f"/projects/{project_id}/{_BASE}/evidence", {"title": f"Probe evidence {start + i}"})["id"] for i in range(count)]


SCALING_PROBES = {"compliance_evidence": ScalingProbe(list_path=f"{_BASE}/evidence", create=_create, has_comments=False)}
