"""
Module: schemas.requirement

Request/response models for requirements, their version history, keywords,
traceability links, and discussion comments (C-G-02, C-G-09, C-M-01, C-R-01).

A requirement's `owner` and `reviewer` are principals (a user, an organisation
group or one of the project's groups): requests send a `PrincipalRef`
(`{type, id}`) and responses return a resolved `PrincipalOut`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import RequirementLevel, RequirementReviewOutcome, RequirementStatus, StagePhaseKind
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow


class RequirementAliasIn(BaseModel):
    """A further place (component and category) a requirement should sit in."""

    component_id: UUID
    category_id: UUID


class RequirementAliasOut(RequirementAliasIn):
    """A requirement's alias: the code of one further place it sits in."""

    id: UUID
    unique_code: str
    is_retired: bool = False


class RequirementCreate(BaseModel):
    name: str
    reasoning: str = ""
    clarification: str = ""
    description: str = ""
    component_id: UUID
    category_id: UUID
    owner: PrincipalRef | None = None
    # A requirement always has a target stage; when omitted the router defaults to the project's earliest
    # stage (as CSV import does), so an API caller need not look one up.
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    keywords: list[str] = []
    custom_fields: dict[str, Any] = {}
    creator_id: UUID | None = None  # PM-only override (C-A-11)
    review_date: date | None = None  # C-R-06
    review_lead_days: int | None = None  # C-R-08 per-requirement override
    reviewer: PrincipalRef | None = None  # C-R-10
    # Further places, each given a code of its own (needs the project's alias setting to be Allowed).
    additional_places: list[RequirementAliasIn] = Field(default=[], max_length=49)


class RequirementUpdate(BaseModel):
    """Direct edit payload. Rejected once the requirement is locked (C-G-12)."""

    name: str
    reasoning: str = ""
    clarification: str = ""
    description: str = ""
    component_id: UUID
    category_id: UUID
    owner: PrincipalRef
    status: RequirementStatus | None = None
    # Omitted means unchanged (the current value carries forward); a target can be retargeted but never cleared.
    target_stage_id: UUID | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    # Omitted leaves the requirement's tags as they are (a stale copy sent back would remove tags added since);
    # a list replaces them (`services.tags`).
    keywords: list[str] | None = None
    # Omitted leaves the further places as they are; a list makes the requirement sit in exactly these (an alias no
    # longer listed is retired, its code kept).
    additional_places: list[RequirementAliasIn] | None = Field(default=None, max_length=49)
    custom_fields: dict[str, Any] = {}
    change_note: str = ""
    review_date: date | None = None  # C-R-06 (blocked by is_locked() once approved, same as every other field here)
    review_lead_days: int | None = None
    reviewer: PrincipalRef | None = None


class RequirementOut(ProjectScopedRow):
    id: UUID
    project_id: UUID
    unique_code: str
    name: str
    reasoning: str
    clarification: str
    description: str = ""
    status: RequirementStatus
    owner: PrincipalOut
    component_id: UUID
    category_id: UUID
    target_stage_id: UUID
    # The phase that governs the requirement (its component's track when component phases are on, else its stage's);
    # set on the project list only, `None` when the component is marked not applicable to the stage.
    phase_name: str | None = None
    phase_kind: StagePhaseKind | None = None
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    sort_order: int
    creator_id: UUID
    is_archived: bool
    is_locked: bool
    # C-G-11 overlay marker, independent of `status` — see
    # `models.requirement.Requirement.is_completed`'s docstring.
    is_completed: bool = False
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    keywords: list[str]
    # The further places the requirement sits in, each with its own code (empty when it has none).
    aliases: list[RequirementAliasOut] = []
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    is_subscribed: bool = False
    review_date: date | None = None
    review_lead_days: int | None = None
    reviewer: PrincipalOut | None = None
    # Derived list-view indicators (mock's card "badges") — not stored data,
    # computed at read time from comments/change-requests/status.
    comment_count: int = 0
    has_open_change_request: bool = False
    requires_approval: bool = False


class RequirementVersionOut(BaseModel):
    version_number: int
    name: str
    reasoning: str
    clarification: str
    description: str = ""
    status: RequirementStatus
    owner: PrincipalOut
    target_stage_id: UUID
    level: RequirementLevel = RequirementLevel.REQUIREMENT
    change_note: str
    change_request_id: UUID | None
    custom_fields: dict[str, Any]
    created_by: UUID
    created_at: datetime
    valid_to: datetime | None


class RequirementLinkCreate(BaseModel):
    target_requirement_id: UUID
    link_type_id: UUID


class RequirementLinkOut(BaseModel):
    """A traceability link, from the perspective of whichever requirement it
    was fetched for (`GET /{requirement_id}/links`) — `direction`/
    `display_name`/`other_requirement_*` are resolved server-side per
    request rather than left for the frontend to infer, since only the
    server can cheaply tell whether the requirement being viewed is the
    link's source or target (see `routers.requirements.links::_links_to_out`).
    """

    id: UUID
    source_requirement_id: UUID
    target_requirement_id: UUID
    link_type_id: UUID
    direction: str  # "outgoing" (viewed requirement is the source) | "incoming" (is the target)
    display_name: str  # forward_name if outgoing, reverse_name if incoming
    other_requirement_id: UUID
    other_requirement_unique_code: str
    other_requirement_name: str


class CommentCreate(BaseModel):
    body: str


class CommentUpdate(BaseModel):
    """Author-only edit of a comment's body (attachments are managed via the
    separate files endpoints, not this payload)."""

    body: str


class CommentOut(BaseModel):
    id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    reaction_count: int = 0
    reacted_by_me: bool = False
    attachments: list[FileAssetOut] = []


class RequirementApproveRequest(BaseModel):
    """Optional body of `POST /requirements/{id}/approve`: what the approver checked.

    A blank or whitespace-only comment is treated as none. Stored as the audit event's `detail.comment`
    and in the new version's change note, the same key every other workflow step uses.
    """

    comment: str | None = None


class RequirementReviewCreate(BaseModel):
    outcome: RequirementReviewOutcome
    comment: str | None = None


class RequirementReviewOut(BaseModel):
    id: UUID
    requirement_id: UUID
    reviewed_by: UUID
    reviewed_at: datetime
    outcome: RequirementReviewOutcome
    comment: str | None = None


class RequirementDueForReviewOut(BaseModel):
    requirement_id: UUID
    project_id: UUID
    # Populated only by the cross-project `/me/reviews/due` listing; the project-scoped listing has the project in its URL.
    project_name: str | None = None
    # Qualifies `unique_code` in that cross-project listing (`services.codes`).
    project_code: str | None = None
    unique_code: str
    name: str
    review_date: date
    reviewer: PrincipalOut | None = None
    component_id: UUID
    component_name: str
