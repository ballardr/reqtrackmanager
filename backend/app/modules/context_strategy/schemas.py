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

Phase 2 (Future State) adds the same shapes (`FutureStateCreate`/`Update`/
`Out`/`VersionOut`/`TransitionRequest`/`CommentCreate`/`CommentUpdate`/
`CommentOut`) for the standalone Future State artefact, following every
one of the conventions above identically.

Phase 3 (Pain Points) adds `PainPointTypeOut` (a plain `PainPointTypeDefinition`
row, org-scoped type CRUD), `EffectivePainPointTypeOut` (one row of a
project's merged effective type list — mirrors `service.
EffectivePainPointType` field-for-field, a Pydantic sibling of that plain
dataclass since the dataclass itself is never returned directly over HTTP),
`ProjectPainPointTypeOut` (a raw `ProjectPainPointType` override/local row,
returned by its own create/override endpoints), and `PainPointCreate`/
`Update`/`Out`/`TransitionRequest`/`CommentCreate`/`CommentUpdate`/
`CommentOut` for the artefact itself — no `PainPointVersionOut` (no version
table; see `models.py`'s own docstring).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    PainPointPriority,
    PainPointStatus,
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


# --- Future State (Phase 2) -------------------------------------------------


class FutureStateCreate(BaseModel):
    title: str
    current_state: str = ""
    desired_state: str = ""
    target_date: date | None = None
    outcomes: str = ""
    success_measures: str = ""
    constraints: str = ""
    assumptions: str = ""


class FutureStateUpdate(BaseModel):
    """Full replace of every content field — rejected outright (409) by the
    router once the Future State's own current version is locked, exact
    mirror of `StrategyUpdate`."""

    title: str
    current_state: str = ""
    desired_state: str = ""
    target_date: date | None = None
    outcomes: str = ""
    success_measures: str = ""
    constraints: str = ""
    assumptions: str = ""
    change_note: str = ""


class FutureStateOut(BaseModel):
    """Always built explicitly by the router (`future_state_to_out`) — exact
    mirror of `StrategyOut`."""

    id: UUID
    scope: FutureStateScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    title: str
    current_state: str
    desired_state: str
    target_date: date | None
    outcomes: str
    success_measures: str
    constraints: str
    assumptions: str
    status: FutureStateStatus
    version_number: int
    is_locked: bool

    created_at: datetime
    updated_at: datetime


class FutureStateVersionOut(BaseModel):
    """One historical `FutureStateVersion` snapshot — exact mirror of
    `StrategyVersionOut`."""

    model_config = {"from_attributes": True}

    id: UUID
    future_state_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    title: str
    current_state: str
    desired_state: str
    target_date: date | None
    outcomes: str
    success_measures: str
    constraints: str
    assumptions: str
    status: FutureStateStatus
    change_note: str
    created_by: UUID
    created_at: datetime


class FutureStateTransitionRequest(BaseModel):
    """Payload for every Future State lifecycle-transition endpoint — exact
    mirror of `StrategyTransitionRequest`."""

    comment: str | None = None


class FutureStateCommentCreate(BaseModel):
    body: str


class FutureStateCommentUpdate(BaseModel):
    body: str


class FutureStateCommentOut(BaseModel):
    """Built explicitly by the router — exact mirror of `StrategyCommentOut`."""

    id: UUID
    future_state_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


# --- Pain Points (Phase 3) ---------------------------------------------------


class PainPointTypeCreate(BaseModel):
    name: str


class PainPointTypeOut(BaseModel):
    """A plain, org-scoped `PainPointTypeDefinition` row."""

    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool


class PainPointTypeUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class EffectivePainPointTypeOut(BaseModel):
    """One row of a project's merged effective Pain Point type list —
    Pydantic sibling of `service.EffectivePainPointType` (see that
    dataclass's own docstring for what `id`/`source` mean). `from_attributes`
    is enabled since the router returns `service.EffectivePainPointType`
    dataclass instances directly (not already this schema type), mirroring
    `StrategyVersionOut`'s identical need for it when returning ORM rows
    verbatim."""

    model_config = {"from_attributes": True}

    id: UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


class ProjectPainPointTypeCreate(BaseModel):
    """Payload for creating a fully project-local Pain Point type (§6.2)."""

    name: str
    display_order: int | None = None


class ProjectPainPointTypeOverrideUpdate(BaseModel):
    """Payload for `PUT .../pain-point-types/{type_ref_id}` — applies a
    partial override to either an org-backed type (creating the override
    row the first time, if none exists yet) or a project-local type's own
    fields. Only non-`None` fields are changed."""

    name: str | None = None
    display_order: int | None = None
    is_enabled: bool | None = None


class ProjectPainPointTypeOut(BaseModel):
    """A raw `ProjectPainPointType` row (override or project-local)."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    org_type_id: UUID | None
    name_override: str | None
    display_order_override: int | None
    is_enabled: bool


class PainPointCreate(BaseModel):
    """`pain_point_type_id` is an `EffectivePainPointTypeOut.id` (see that
    schema's own docstring for what it may resolve to)."""

    pain_point_type_id: UUID
    title: str
    description: str = ""
    source: str = ""
    impact: str = ""
    evidence: str = ""
    priority: PainPointPriority = PainPointPriority.MEDIUM
    date_identified: date | None = None


class PainPointUpdate(BaseModel):
    """Full content update — rejected outright (409) by the router once
    the Pain Point is in a `service.PAIN_POINT_LOCKED_STATUSES` terminal
    state. Manager-only (`_shared.require_pain_point_manage_role`), unlike
    Strategy's creator-may-not-edit-but-may-propose split — Pain Point's
    broad-creation model (§6.5) grants create/comment/evidence, not a
    standing edit right over submitted content; see `project_router.py`'s
    own docstring."""

    pain_point_type_id: UUID
    title: str
    description: str = ""
    source: str = ""
    impact: str = ""
    evidence: str = ""
    priority: PainPointPriority
    owner_id: UUID | None = None
    date_identified: date | None = None


class PainPointOut(BaseModel):
    id: UUID
    project_id: UUID
    pain_point_type_id: UUID
    pain_point_type_name: str
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    title: str
    description: str
    source: str
    impact: str
    evidence: str
    priority: PainPointPriority
    status: PainPointStatus
    owner_id: UUID | None
    date_identified: date
    is_locked: bool

    created_at: datetime
    updated_at: datetime


class PainPointTransitionRequest(BaseModel):
    """Payload for every lifecycle-transition endpoint (`triage`/`reject`/
    `mark-duplicate`/`accept`/`address`/`close`). `comment` is validated as
    mandatory specifically for `reject`/`mark-duplicate`, at the router
    layer, not here — mirrors `StrategyTransitionRequest`'s identical
    optional-here, enforced-at-the-router shape."""

    comment: str | None = None


class PainPointCommentCreate(BaseModel):
    body: str


class PainPointCommentUpdate(BaseModel):
    body: str


class PainPointCommentOut(BaseModel):
    """Built explicitly by the router — exact mirror of `StrategyCommentOut`."""

    id: UUID
    pain_point_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []
