"""Helpers for tests that move a project stage between workflow phases.

`move_stage` takes the old state names ("review", "approved", ...) and resolves each to the phase of the
stage's own workflow with that name, so a test reads the same whatever the phase ids are.
"""

from __future__ import annotations

from typing import Any

#: The old status names and the Standard workflow phases they became.
STANDARD_PHASE = {
    "scoping": "Scoping", "review": "Review", "approved": "Approved", "completed": "Completed", "archived": "Archived",
}


def stage_phase_id(client: Any, project_id: Any, stage_id: Any, phase: str, headers: dict[str, str]) -> Any:
    """The id of the stage's workflow phase named `phase` (a `STANDARD_PHASE` key or a phase name), or the
    failing response when the stage or workflow could not be read with `headers`."""
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=headers)
    if stages.status_code != 200:
        return stages
    stage = next(s for s in stages.json() if s["id"] == str(stage_id))
    workflows = client.get(f"/api/v1/projects/{project_id}/stage-workflows", headers=headers)
    if workflows.status_code != 200:
        return workflows
    workflow = next(w for w in workflows.json() if w["id"] == stage["workflow_id"])
    wanted = STANDARD_PHASE.get(phase, phase)
    return next(p["id"] for p in workflow["phases"] if p["name"] == wanted)


def move_stage(
    client: Any, project_id: Any, stage_id: Any, phase: str, *, headers: dict[str, str], cascade: bool = False,
) -> Any:
    """Moves a stage to the named phase and returns the transition response."""
    phase_id = stage_phase_id(client, project_id, stage_id, phase, headers)
    if not isinstance(phase_id, str):
        return phase_id
    return client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition",
        json={"phase_id": phase_id, "cascade_to_requirements": cascade}, headers=headers,
    )
