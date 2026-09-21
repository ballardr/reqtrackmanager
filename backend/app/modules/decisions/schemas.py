"""
Module: modules.decisions.schemas

Pydantic request/response models for Decision Management's Phase 4 backend
API (docs/plans/module-04-decision-management-plan.md Phase 4) — sits
alongside `models.py` (the ORM shapes these expose over HTTP),
`project_router.py` (the project-scoped Decision/comment/file/relationship
endpoints), and `router.py` (the org-scoped Decision Template endpoints).

Conventions, matching `app.modules.compliance.schemas`' own established
shape for this codebase's module schemas:
- Every `*Out` schema that maps 1:1 onto an ORM row sets
  `model_config = {"from_attributes": True}`.
- `DecisionOut` is the one exception: `is_locked` (Phase 4's own
  content-lock-after-approval rule, enforced at the router layer — see
  `project_router.py`'s module docstring) is a computed field, not a
  column, so `DecisionOut` is always built explicitly by the router from a
  `Decision` row, the same "computed field -> build explicitly" pattern
  `ProjectComplianceRequirementOut`/`ComplianceEvidenceOut` already use.
- `DecisionLinkOut` is this module's own presentation shape over the
  generic, polymorphic `ArtefactLink` (`app.models.relationship`) —
  deliberately not reusing `RequirementLinkOut`
  (`app.schemas.requirement`), since that schema is hard-coded to a
  requirement-to-requirement link (`source_requirement_id`/
  `target_requirement_id`/`other_requirement_*`) and no generic link-
  presentation schema exists in `app.schemas` to reuse instead (checked
  before writing this one, per this module's own Phase 4 build
  instructions) — a Decision's own links can point at either another
  Decision or a Requirement, so the shape needs to stay polymorphic rather
  than assume one target type. **Decided by: Agent.**
- `DecisionCommentOut` mirrors `app.schemas.requirement.CommentOut`'s
  shape minus the reaction fields (`reaction_count`/`reacted_by_me`) — a
  `DecisionComment` has no reaction mechanism (not asked for by this
  phase's scope, and the module-local `DecisionComment` table has no
  `CommentReaction`-equivalent join table), so those two fields are simply
  omitted rather than carried over unused. **Decided by: Agent.**
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.service import DecisionDecisionLinkKind, DecisionRequirementLinkKind
from app.schemas.file import FileAssetOut

# --- Decision Types (project-scoped) ----------------------------------------


class DecisionTypeCreate(BaseModel):
    name: str


class DecisionTypeUpdate(BaseModel):
    """Rename payload — see `services.definitions`' module docstring:
    renaming never disturbs any Decision currently of this type, since
    every reference points at the row's id, never its name."""

    name: str


class DecisionTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    name: str
    sort_order: int


# --- Decision Templates (org-scoped) ----------------------------------------


class DecisionTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    context_prompt: str | None = None
    options_considered_prompt: str | None = None
    chosen_option_prompt: str | None = None
    rationale_prompt: str | None = None
    consequences_prompt: str | None = None
    assumptions_prompt: str | None = None
    constraints_prompt: str | None = None


class DecisionTemplateUpdate(DecisionTemplateCreate):
    """Same shape as create — a template has no field that's immutable
    after creation (unlike e.g. a Compliance standard's `reference`), so
    there's no reason for a narrower update payload."""


class DecisionTemplateOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    context_prompt: str | None
    options_considered_prompt: str | None
    chosen_option_prompt: str | None
    rationale_prompt: str | None
    consequences_prompt: str | None
    assumptions_prompt: str | None
    constraints_prompt: str | None
    sort_order: int


# --- Decisions ---------------------------------------------------------------


class DecisionCreate(BaseModel):
    """`owner_id` defaults to the creating user when omitted (mirrors
    `ComplianceStandardCreate.owner_id`'s own default-to-creator
    convention) — a Decision always needs an owner, but there's no reason
    to force the caller to name themselves explicitly."""

    title: str
    decision_statement: str
    decision_type_id: UUID
    decision_date: date | None = None
    decision_maker_id: UUID | None = None
    owner_id: UUID | None = None
    context: str | None = None
    options_considered: str | None = None
    chosen_option: str | None = None
    rationale: str | None = None
    consequences: str | None = None
    assumptions: str | None = None
    constraints: str | None = None


class DecisionUpdate(BaseModel):
    """Full replace of every content field — rejected outright (409) by
    `project_router.py::update_decision` once the Decision's own `status`
    is `APPROVED`/`SUPERSEDED` (source overview §13/10.6's "approved
    decisions should not normally be edited in-place"), mirroring
    `services.requirements.is_locked`'s router-layer enforcement pattern
    exactly (see that router's own module docstring)."""

    title: str
    decision_statement: str
    decision_type_id: UUID
    decision_date: date | None = None
    decision_maker_id: UUID | None = None
    owner_id: UUID
    context: str | None = None
    options_considered: str | None = None
    chosen_option: str | None = None
    rationale: str | None = None
    consequences: str | None = None
    assumptions: str | None = None
    constraints: str | None = None


class DecisionOut(BaseModel):
    """Always built explicitly by the router (`_decision_to_out`), never
    `from_attributes` alone — `is_locked` is computed, not a column (see
    this module's own docstring)."""

    id: UUID
    project_id: UUID
    unique_code: str
    title: str
    decision_statement: str
    decision_type_id: UUID
    status: DecisionStatus
    decision_date: date | None
    decision_maker_id: UUID | None
    owner_id: UUID
    context: str | None
    options_considered: str | None
    chosen_option: str | None
    rationale: str | None
    consequences: str | None
    assumptions: str | None
    constraints: str | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None
    is_locked: bool
    created_at: datetime
    updated_at: datetime


class DecisionTransitionRequest(BaseModel):
    """Payload for `approve`/`reject` (Phase 2's `service.approve_decision`/
    `reject_decision` own optional `comment` parameter). `comment` is
    validated as mandatory specifically for `reject`, at the router layer,
    not here — mirrors `record_review_outcome`'s identical mandatory-
    comment-on-failure rule (`routers.requirements.py`,
    `RequirementReviewOutcome.FAILED`) rather than making it unconditionally
    required and breaking `approve`, which the plan explicitly allows to
    carry an *optional* comment."""

    comment: str | None = None


# --- Comments ------------------------------------------------------------


class DecisionCommentCreate(BaseModel):
    body: str


class DecisionCommentUpdate(BaseModel):
    """Author-only edit of a comment's body — see `project_router.py::
    edit_decision_comment`."""

    body: str


class DecisionCommentOut(BaseModel):
    """Built explicitly by the router (`_comment_to_out`) — the author's
    display name isn't a column on `DecisionComment` itself, same reason
    `CommentOut`/`engagement.comment_to_out` build theirs explicitly."""

    id: UUID
    decision_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


# --- Relationships ---------------------------------------------------------


class DecisionSupersessionCreate(BaseModel):
    old_decision_id: UUID


class DecisionRequirementLinkCreate(BaseModel):
    requirement_id: UUID
    kind: DecisionRequirementLinkKind


class DecisionDecisionLinkCreate(BaseModel):
    target_decision_id: UUID
    kind: DecisionDecisionLinkKind


class DecisionLinkOut(BaseModel):
    """A relationship touching one specific Decision, from that Decision's
    own point of view (`direction`/`display_name` resolved server-side,
    mirroring `RequirementLinkOut`'s identical reasoning) — see this
    module's own docstring for why this isn't just `RequirementLinkOut`
    reused. `other_display_code`/`other_display_name` are best-effort:
    populated when `other_type` is one this module knows how to resolve
    (`"decision"` or the core `"requirement"`), `None` otherwise (a
    Phase 6 reserved relationship target with no rows to resolve yet)."""

    id: UUID
    source_type: str
    source_id: UUID
    target_type: str
    target_id: UUID
    link_type_id: UUID | None
    direction: str  # "outgoing" (viewed Decision is the source) | "incoming" (is the target)
    display_name: str  # forward_name if outgoing, reverse_name if incoming
    other_type: str
    other_id: UUID
    other_display_code: str | None = None
    other_display_name: str | None = None
    created_by: UUID
    created_at: datetime
