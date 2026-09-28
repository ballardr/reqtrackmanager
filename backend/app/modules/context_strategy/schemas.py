"""
Module: modules.context_strategy.schemas

Pydantic request/response models for Context & Strategy's Phase 1 backend
API — sits alongside `models.py` (the ORM shapes these expose over HTTP),
`service.py` (versioning/lifecycle logic), and the two routers (`router.py`
org-scoped, `project_router.py` project-scoped).

Conventions, matching `app.modules.decisions.schemas`'s own established
shape for this codebase's module schemas:
- `StrategyOut` is always built explicitly by the router (`_strategy_to_out`),
  never `from_attributes` alone — it merges the `Strategy` identity row with
  its *current* `StrategyVersion`'s content, and `is_locked` is a computed
  field, not a column, mirroring `DecisionOut`'s identical pattern.
- `StrategyCommentOut` mirrors `DecisionCommentOut`'s shape (no reaction
  fields — `StrategyComment` has no reaction mechanism, same reasoning).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.context_strategy.enums import (
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.schemas.file import FileAssetOut

# --- Strategies --------------------------------------------------------------


class StrategyCreate(BaseModel):
    title: str
    objective: str
    current_state: str = ""
    desired_future_state: str = ""
    rationale: str = ""
    expected_outcomes: str = ""
    constraints: str = ""
    measures_of_success: str = ""
    priority: StrategyPriority = StrategyPriority.MEDIUM
    time_horizon: StrategyTimeHorizon = StrategyTimeHorizon.MEDIUM_TERM


class StrategyUpdate(BaseModel):
    """Full replace of every content field — rejected outright (409) by
    the router once the Strategy's own current version is locked (past
    `UNDER_REVIEW` — see `service.LOCKED_STATUSES`), mirroring Decision
    Management's identical router-layer enforcement pattern."""

    title: str
    objective: str
    current_state: str = ""
    desired_future_state: str = ""
    rationale: str = ""
    expected_outcomes: str = ""
    constraints: str = ""
    measures_of_success: str = ""
    priority: StrategyPriority
    time_horizon: StrategyTimeHorizon
    change_note: str = ""


class StrategyOut(BaseModel):
    """Always built explicitly by the router (`_strategy_to_out`) — merges
    the `Strategy` identity row with its current `StrategyVersion`'s
    content; `is_locked` is computed, not a column (see this module's own
    docstring)."""

    id: UUID
    scope: StrategyScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    title: str
    objective: str
    current_state: str
    desired_future_state: str
    rationale: str
    expected_outcomes: str
    constraints: str
    measures_of_success: str
    priority: StrategyPriority
    time_horizon: StrategyTimeHorizon
    status: StrategyStatus
    version_number: int
    is_locked: bool

    created_at: datetime
    updated_at: datetime


class StrategyVersionOut(BaseModel):
    """One historical `StrategyVersion` snapshot, for the version-history
    endpoint."""

    model_config = {"from_attributes": True}

    id: UUID
    strategy_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    title: str
    objective: str
    current_state: str
    desired_future_state: str
    rationale: str
    expected_outcomes: str
    constraints: str
    measures_of_success: str
    priority: StrategyPriority
    time_horizon: StrategyTimeHorizon
    status: StrategyStatus
    change_note: str
    created_by: UUID
    created_at: datetime


class StrategyTransitionRequest(BaseModel):
    """Payload for every lifecycle-transition endpoint (`propose`/`submit-
    for-review`/`send-back`/`approve`/`activate`/`supersede`/`retire`).
    `comment` is validated as mandatory specifically for `send-back`, at
    the router layer, not here — mirrors `DecisionTransitionRequest`'s
    identical optional-here, enforced-at-the-router-for-one-specific-
    action shape."""

    comment: str | None = None


# --- Comments ----------------------------------------------------------------


class StrategyCommentCreate(BaseModel):
    body: str


class StrategyCommentUpdate(BaseModel):
    body: str


class StrategyCommentOut(BaseModel):
    """Built explicitly by the router (`_comment_to_out`) — the author's
    display name isn't a column on `StrategyComment` itself."""

    id: UUID
    strategy_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []
