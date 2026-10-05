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

Phase 4 (Guiding Principles) adds `GuidingPrincipleCreate`/`Update`/`Out`/
`VersionOut`/`TransitionRequest`/`CommentCreate`/`CommentUpdate`/`CommentOut`
for the standalone Guiding Principle artefact, following every one of the
conventions above identically (`GuidingPrincipleOut` always built explicitly
by the router, merging identity + current version; `is_locked` computed).

Phase 5 (Open Questions) adds `OpenQuestionCreate`/`Update`/`Out`/
`TransitionRequest`/`CommentCreate`/`CommentUpdate`/`CommentOut` — back to
Pain Point's shape (no `OpenQuestionVersionOut`; no version table, see
`models.py`'s own docstring).

Phase 6 (Cross-artefact relationships) adds one shared `ContextStrategyLinkOut`
(returned by every source artefact's `GET .../relationships` and `POST
.../relationships` endpoints alike — one shape covers all five source types,
unlike Decision Management's single `DecisionLinkOut`, since this module has
five source types rather than one; `other_type`/`other_display_code`/
`other_display_name` are resolved the same best-effort way `modules.
decisions.project_router.relationships._resolve_other_artefact_display`
does, including declining to resolve a Decision-typed target per this
module's own "Decision-target relationships stay reserved" call, see
`service.py`'s own docstring) and one `*LinkCreate` request payload per
source artefact type (`kind` + `target_id` — `kind` is the corresponding
`service.*LinkKind` enum, so an invalid `target_type` string is never a
possible client input at all), plus `StrategySupersessionCreate`/
`FutureStateSupersessionCreate`/`GuidingPrincipleSupersessionCreate` (each
just `{old_<artefact>_id, comment}`, mirroring `DecisionSupersessionCreate`).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.service import (
    FutureStateLinkKind,
    GuidingPrincipleLinkKind,
    OpenQuestionLinkKind,
    PainPointLinkKind,
    StrategyLinkKind,
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
    is_intentional: bool = False


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
    is_intentional: bool | None = None  # None = leave unchanged


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
    is_intentional: bool
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


# --- Pain Point scoring (Phase 11) -------------------------------------------


class PainPointScoreEntryIn(BaseModel):
    """One requested score row. `target_id` null = all personas; a level id
    null = not scored on that axis."""

    target_id: UUID | None = None
    severity_level_id: UUID | None = None
    frequency_level_id: UUID | None = None
    confidence_level_id: UUID | None = None


class PainPointScoresUpdate(BaseModel):
    """Replaces a Pain Point's whole score set (empty list clears it). The
    cap is far above any real persona count; it just bounds the request."""

    scores: list[PainPointScoreEntryIn] = Field(max_length=500)


class ScoreOut(BaseModel):
    """A computed score: raw product, normalised 0–1 value and rating band."""

    raw: float
    normalised: float
    band_label: str | None = None
    band_tone: str | None = None


class PainPointScoreEntryOut(BaseModel):
    """One resolved score row. `status` is `all`/`active`/`inactive`/
    `unavailable` (see `pain_point_scores.TargetStatus`); `label` and
    `weight` come from the target (null for all-personas/unavailable)."""

    target_id: UUID | None
    target_type: str | None
    label: str | None
    weight: float | None
    status: str
    severity_level_id: UUID | None
    frequency_level_id: UUID | None
    confidence_level_id: UUID | None
    score: ScoreOut | None
    is_blocker: bool


class PainPointScoringSummaryOut(BaseModel):
    """A Pain Point's roll-up under the requested model and method."""

    pain_point_id: UUID
    scope: str
    score: ScoreOut | None
    counted: int
    is_blocker: bool
    blocker_labels: list[str]
    personas_degraded: bool
    entries: list[PainPointScoreEntryOut]


class ScoringTargetOut(BaseModel):
    """A persona the project can score against."""

    id: UUID
    label: str
    weight: float | None
    is_active: bool


class PainPointScoringListOut(BaseModel):
    """`GET .../pain-point-scores`: every (non-archived) Pain Point's roll-up
    under one model and method."""

    # `model_key`/`model_source` are scoring-domain names, not Pydantic internals.
    model_config = {"protected_namespaces": ()}

    model_key: str
    model_source: str
    rollup: str
    items: list[PainPointScoringSummaryOut]


class PainPointScoresOut(PainPointScoringSummaryOut):
    """One Pain Point's roll-up plus what the score grid needs: the
    model/method used and the personas available to score against
    (empty if Module 2's personas are off — then only "all personas"
    scoring is possible)."""

    model_config = {"protected_namespaces": ()}

    model_key: str
    model_source: str
    rollup: str
    available_targets: list[ScoringTargetOut]


# --- Guiding Principles (Phase 4) --------------------------------------------


class GuidingPrincipleCreate(BaseModel):
    name: str
    principle_statement: str
    rationale: str = ""
    priority: GuidingPrinciplePriority = GuidingPrinciplePriority.MEDIUM
    owner_id: UUID | None = None


class GuidingPrincipleUpdate(BaseModel):
    """Full replace of every content field — rejected outright (409) by the
    router once the Guiding Principle's own current version is locked (past
    `PROPOSED` — see `service.GUIDING_PRINCIPLE_LOCKED_STATUSES`), exact
    mirror of `StrategyUpdate`/`FutureStateUpdate`."""

    name: str
    principle_statement: str
    rationale: str = ""
    priority: GuidingPrinciplePriority
    owner_id: UUID | None = None
    change_note: str = ""


class GuidingPrincipleOut(BaseModel):
    """Always built explicitly by the router (`guiding_principle_to_out`) —
    exact mirror of `StrategyOut`/`FutureStateOut`."""

    id: UUID
    scope: GuidingPrincipleScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    name: str
    principle_statement: str
    rationale: str
    priority: GuidingPrinciplePriority
    status: GuidingPrincipleStatus
    owner_id: UUID | None
    version_number: int
    is_locked: bool

    created_at: datetime
    updated_at: datetime


class GuidingPrincipleVersionOut(BaseModel):
    """One historical `GuidingPrincipleVersion` snapshot — exact mirror of
    `StrategyVersionOut`/`FutureStateVersionOut`."""

    model_config = {"from_attributes": True}

    id: UUID
    guiding_principle_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    principle_statement: str
    rationale: str
    priority: GuidingPrinciplePriority
    status: GuidingPrincipleStatus
    owner_id: UUID | None
    change_note: str
    created_by: UUID
    created_at: datetime


class GuidingPrincipleTransitionRequest(BaseModel):
    """Payload for every Guiding Principle lifecycle-transition endpoint
    (`propose`/`send-back`/`approve`/`activate`/`supersede`/`retire`) —
    exact mirror of `StrategyTransitionRequest`/`FutureStateTransitionRequest`."""

    comment: str | None = None


class GuidingPrincipleCommentCreate(BaseModel):
    body: str


class GuidingPrincipleCommentUpdate(BaseModel):
    body: str


class GuidingPrincipleCommentOut(BaseModel):
    """Built explicitly by the router — exact mirror of `StrategyCommentOut`."""

    id: UUID
    guiding_principle_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


# --- Open Questions (Phase 5) -------------------------------------------------


class OpenQuestionCreate(BaseModel):
    question: str
    context: str = ""
    evidence: str = ""
    priority: OpenQuestionPriority = OpenQuestionPriority.MEDIUM
    due_date: date | None = None


class OpenQuestionUpdate(BaseModel):
    """Full content update — rejected outright (409) by the router once the
    Open Question is in a `service.OPEN_QUESTION_LOCKED_STATUSES` terminal
    state. Manager-only (`_shared.require_open_question_manage_role`),
    exact mirror of `PainPointUpdate`'s creator-may-not-edit posture — the
    broad-creation model (§9.4) grants create/comment/evidence, not a
    standing edit right over a submitted question."""

    question: str
    context: str = ""
    evidence: str = ""
    priority: OpenQuestionPriority
    owner_id: UUID | None = None
    due_date: date | None = None


class OpenQuestionOut(BaseModel):
    id: UUID
    project_id: UUID
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    question: str
    context: str
    evidence: str
    priority: OpenQuestionPriority
    status: OpenQuestionStatus
    owner_id: UUID | None
    due_date: date | None
    is_locked: bool

    created_at: datetime
    updated_at: datetime


class OpenQuestionTransitionRequest(BaseModel):
    """Payload for every lifecycle-transition endpoint (`investigate`/
    `mark-ready-for-decision`/`withdraw`/`resolve`). `comment` is validated
    as mandatory specifically for `withdraw`, at the router layer, not here
    — mirrors `PainPointTransitionRequest`'s identical optional-here,
    enforced-at-the-router shape."""

    comment: str | None = None


class OpenQuestionCommentCreate(BaseModel):
    body: str


class OpenQuestionCommentUpdate(BaseModel):
    body: str


class OpenQuestionCommentOut(BaseModel):
    """Built explicitly by the router — exact mirror of `StrategyCommentOut`."""

    id: UUID
    open_question_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None


# --- Phase 6: cross-artefact relationships -----------------------------------


class ContextStrategyLinkOut(BaseModel):
    """A relationship touching one specific source artefact, from that
    artefact's own viewpoint — shared by every source artefact type's `GET
    .../relationships` and `POST .../relationships` endpoints (`router.py`/
    `project_router.py`). Mirrors `modules.decisions.schemas.DecisionLinkOut`'s
    shape and "built explicitly per request, from the viewpoint artefact"
    reasoning exactly, generalised to five possible source types instead of
    one.

    `other_display_code`/`other_display_name` are resolved best-effort: `None`
    for an `other_type` this module doesn't know how to resolve (in
    practice, only ever `"decision"` today — a Decision-target relationship
    is reserved, not yet created by any endpoint, but a future link of that
    shape reaching this schema, e.g. once Module 4's own Phase 7 starts
    writing rows this module can also read via `GET .../relationships`,
    still renders without erroring)."""

    id: UUID
    source_type: str
    source_id: UUID
    target_type: str
    target_id: UUID
    link_type_id: UUID | None
    direction: str
    display_name: str
    other_type: str
    other_id: UUID
    other_display_code: str | None
    other_display_name: str | None
    created_by: UUID
    created_at: datetime


class StrategyLinkCreate(BaseModel):
    kind: StrategyLinkKind
    target_id: UUID


class PainPointLinkCreate(BaseModel):
    kind: PainPointLinkKind
    target_id: UUID


class GuidingPrincipleLinkCreate(BaseModel):
    kind: GuidingPrincipleLinkKind
    target_id: UUID


class FutureStateLinkCreate(BaseModel):
    kind: FutureStateLinkKind
    target_id: UUID


class OpenQuestionLinkCreate(BaseModel):
    kind: OpenQuestionLinkKind
    target_id: UUID


class StrategySupersessionCreate(BaseModel):
    old_strategy_id: UUID
    comment: str | None = None


class FutureStateSupersessionCreate(BaseModel):
    old_future_state_id: UUID
    comment: str | None = None


class GuidingPrincipleSupersessionCreate(BaseModel):
    old_guiding_principle_id: UUID
    comment: str | None = None
    attachments: list[FileAssetOut] = []
