"""
Module: schemas.stage_workflow

Request and response shapes for stage workflows (`routers.stage_workflows`) and the stage
transition request (`routers.projects.stages`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import StagePhaseKind
from app.models.stage_workflow import MAX_WORKFLOW_NAME_LENGTH
from app.schemas.principal import PrincipalOut, PrincipalRef


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


class ComponentPhasesSettingSet(BaseModel):
    """Set the project's own component-phases switch; `null` follows the nearest ancestor."""

    mode: Literal["on", "off"] | None = None


class ComponentTrackUpdate(BaseModel):
    """Change one component's track for a stage. Only the fields sent change: `workflow_id` null returns to the
    stage's workflow, `owner` null clears the owner."""

    workflow_id: UUID | None = None
    not_applicable: bool | None = None
    owner: PrincipalRef | None = None


class ComponentTrackOut(BaseModel):
    """One component's standing in one stage (a component with no stored row shows the stage's defaults)."""

    component_id: UUID
    stage_id: UUID
    workflow_id: UUID
    workflow_name: str
    phase_id: UUID
    phase_name: str
    phase_kind: StagePhaseKind
    not_applicable: bool
    customised: bool
    owner: PrincipalOut | None = None
    approved_at: datetime | None = None
    completed_at: datetime | None = None
    previous_closed: bool
    can_move: bool


class ComponentPhasesOut(BaseModel):
    """The project's component-phases state: the effective mode, its own setting and, when on, every track."""

    mode: Literal["on", "off"]
    own_mode: Literal["on", "off"] | None
    inherited: bool
    tracks: list[ComponentTrackOut]
