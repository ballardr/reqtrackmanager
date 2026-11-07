"""
Module: schemas.stage_workflow

Request and response shapes for stage workflows (`routers.stage_workflows`) and the stage
transition request (`routers.projects.stages`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import StagePhaseKind
from app.models.stage_workflow import MAX_WORKFLOW_NAME_LENGTH


class PhaseWrite(BaseModel):
    """A phase in a workflow being saved; `id` is set for an existing phase so it keeps its identity."""

    id: UUID | None = None
    name: str = Field(max_length=MAX_WORKFLOW_NAME_LENGTH)
    kind: StagePhaseKind


class WorkflowWrite(BaseModel):
    """Create or replace a workflow: its name and its phases in order (the first is the start)."""

    name: str = Field(max_length=MAX_WORKFLOW_NAME_LENGTH)
    phases: list[PhaseWrite]


class PhaseOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    kind: StagePhaseKind
    sort_order: int


class WorkflowOut(BaseModel):
    id: UUID
    name: str
    scope: Literal["organisation", "project"]
    sort_order: int
    phases: list[PhaseOut]
    in_use: bool


class HiddenWorkflowOut(BaseModel):
    id: UUID
    name: str


class RestoreWorkflowsRequest(BaseModel):
    """Workflows to show again; omit to restore every hidden one."""

    workflow_ids: list[UUID] | None = None


class StageTransitionRequest(BaseModel):
    """Move a stage to a phase of its workflow. `cascade_to_requirements` applies only when the phase
    is a closed one (it marks the stage's approved requirements completed)."""

    phase_id: UUID
    cascade_to_requirements: bool = False
