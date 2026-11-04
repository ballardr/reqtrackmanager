"""
Module: modules.product_feedback.schemas

Pydantic request/response schemas for Product Feedback's routers: request create / update / out,
version history, lifecycle transitions, comments and the project settings.

`RequestUpdate` is partial: only fields present in the request body change, so a nullable field
(the owner, the external reference) can be cleared by sending an explicit `null`. `status` is not
editable here (the transition endpoint owns it).

Scoring levels are a map of axis key to level id (`levels`), optional and clearable per axis (an axis sent as `null`
is cleared, one not mentioned is kept). A response carries them with the scores derived under each model scored
(`scores`; `score` / `scoring_model_key` are the primary one; null while an axis the model needs is unset), and
`derived_levels` for an axis read from the request's demand.

A request also reports its place in a merge (`merged_into`, `merged_count`), its demand
(`requester_count`, `weighted_demand`; see `demand.py`), the problems and work it is linked to (`pain_point_count`,
`requirement_count`; `relationships.py`) and how many requesters were told its outcome (`informed_count`,
`loop_open_count`; `loop.py`). All are derived, never written here.

`owner` is a principal: a user, an organisation group or a project group. Requests send a
`PrincipalRef` (`{type, id}`; null clears it) and responses return a resolved `PrincipalOut`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow


class RequestCreate(BaseModel):
    """Create payload; only `title` is required. `status` is not accepted (a request starts `NEW`)."""

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500)
    external_ref_key: str | None = Field(default=None, max_length=100)
    levels: dict[str, UUID | None] | None = Field(
        default=None, description="Scoring level id by axis key (`get scoring-scheme` lists them); null clears an axis."
    )


class RequestUpdate(BaseModel):
    """Partial update; see module docstring."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500)
    external_ref_key: str | None = Field(default=None, max_length=100)
    levels: dict[str, UUID | None] | None = Field(
        default=None, description="Scoring level id by axis key (`get scoring-scheme` lists them); null clears an axis."
    )
    change_note: str = ""


class RequestTransitionRequest(BaseModel):
    """A lifecycle move. `comment` is recorded as the new version's change note and, when declining, is the
    mandatory decline reason."""

    status: EnhancementRequestStatus
    comment: str = ""


class RequestMoveRequest(BaseModel):
    """Triage of an inbox request into the project `project_id` (a project of the same organisation)."""

    project_id: UUID


class RequestMergeRequest(BaseModel):
    """Merge of the request in the URL (the duplicate) into `canonical_id`, another request of the same owner."""

    canonical_id: UUID
    note: str = Field(default="", max_length=2000)


class RequestRefOut(BaseModel):
    """A short reference to another request."""

    id: UUID
    unique_code: str
    title: str


class RequestScoreOut(BaseModel):
    """A derived score (never stored). `label` / `tone` are the effective band; `normalised` is the raw score as a
    share of the model's best possible score."""

    scoring_model_key: str
    raw: float
    normalised: float
    label: str | None = None
    tone: str | None = None


class RequestOut(ProjectScopedRow):
    """A request merged with its current version. Built explicitly (identity row plus version), never via
    `from_attributes`."""

    id: UUID
    scope: EnhancementRequestScope
    organization_id: UUID | None = None
    project_id: UUID | None = None
    unique_code: str
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None = None
    archived_by: UUID | None = None
    title: str
    description: str
    status: EnhancementRequestStatus
    allowed_next_statuses: list[EnhancementRequestStatus]
    owner: PrincipalOut | None = None
    external_ref_url: str | None = None
    external_ref_key: str | None = None
    decline_reason: str
    levels: dict[str, UUID] = Field(default_factory=dict, description="The scoring levels chosen, by axis key.")
    derived_levels: dict[str, UUID] = Field(
        default_factory=dict, description="The level each derived axis (Demand) resolves to where none is chosen."
    )
    score: RequestScoreOut | None = None
    scoring_model_key: str
    scores: dict[str, RequestScoreOut | None] = Field(
        default_factory=dict, description="The score under each model scored (the enabled ones, or the chosen)."
    )
    version_number: int
    created_at: datetime
    updated_at: datetime
    merged_into: RequestRefOut | None = None
    merged_count: int = 0
    requester_count: int = 0
    weighted_demand: float = 0.0
    pain_point_count: int = Field(
        default=0, description="Pain Points the request addresses (its merged duplicates' included); 0 is flagged."
    )
    requirement_count: int = Field(default=0, description="Requirements that realise the request.")
    informed_count: int = Field(default=0, description="Requesters recorded as told the outcome.")
    loop_open_count: int = Field(
        default=0, description="Requesters still to be told; 0 unless the request is delivered or declined."
    )


class RequestVersionOut(BaseModel):
    """One historical version."""

    id: UUID
    request_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None = None
    title: str
    description: str
    status: EnhancementRequestStatus
    owner: PrincipalOut | None = None
    external_ref_url: str | None = None
    external_ref_key: str | None = None
    decline_reason: str
    levels: dict[str, UUID] = Field(default_factory=dict, description="The scoring levels chosen, by axis key.")
    change_note: str
    created_by: UUID
    created_at: datetime


class RequestCommentCreate(BaseModel):
    """A new comment."""

    body: str = Field(min_length=1)


class RequestCommentUpdate(BaseModel):
    """A comment's replacement text."""

    body: str = Field(min_length=1)


class RequestCommentOut(BaseModel):
    """A comment with its author's display name and attachments."""

    id: UUID
    request_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class FeedbackSettingsOut(BaseModel):
    """A project's Product Feedback settings."""

    submission_policy: SubmissionPolicy


class FeedbackSettingsUpdate(BaseModel):
    """Replacement settings."""

    submission_policy: SubmissionPolicy


class RequesterOut(BaseModel):
    """One distinct party behind a request. `label` and `weight` are null (and `hidden` true) for a party the
    caller may not view; it still counts toward the totals."""

    artefact_type: str
    id: UUID
    label: str | None = None
    weight: float | None = None
    effective_weight: float
    from_merge: bool
    via_engagement: bool
    hidden: bool = False


class DemandEngagementOut(BaseModel):
    """An Engagement the request was raised in; `label` is null when the caller may not view it."""

    id: UUID
    label: str | None = None
    hidden: bool = False


class DemandOut(BaseModel):
    """A request's demand: the distinct requesters (its own and those of requests merged into it), the
    engagements it was raised in, and the totals."""

    request_id: UUID
    requester_count: int
    weighted_demand: float
    requesters: list[RequesterOut]
    engagements: list[DemandEngagementOut]
    merged_duplicates: list[RequestRefOut]


class RequestMergeOut(BaseModel):
    """One merge in a request's history (as the canonical request or as the duplicate)."""

    id: UUID
    canonical: RequestRefOut
    duplicate: RequestRefOut
    prior_status: EnhancementRequestStatus
    merged_by: UUID
    merged_at: datetime
    unmerged_by: UUID | None = None
    unmerged_at: datetime | None = None
    active: bool


class PartyRef(BaseModel):
    """A requester record: a Stakeholder or Persona."""

    artefact_type: str = Field(max_length=64)
    id: UUID


class InformedUpdate(BaseModel):
    """Records (or withdraws) that requesters were told the outcome of a delivered or declined request. Every party
    must be a current requester (`GET .../demand` lists them)."""

    parties: list[PartyRef] = Field(min_length=1, max_length=500)
    informed: bool = True
    note: str = Field(default="", max_length=2000, description="How or by whom they were told; kept with a recorded row.")


class LoopRequesterOut(RequesterOut):
    """A requester with whether they were told the outcome."""

    informed: bool = False
    informed_at: datetime | None = None
    informed_by: UUID | None = None
    note: str = ""


class LinkedRecordOut(BaseModel):
    """A record linked to a request; `label` is null (and `hidden` true) when the caller may not view it."""

    id: UUID
    label: str | None = None
    hidden: bool = False


class RealisingRequirementOut(LinkedRecordOut):
    """A Requirement that realises a request, with its completion overlay (null while hidden)."""

    is_completed: bool | None = None


class CloseTheLoopOut(BaseModel):
    """What became of a request and who has been told.

    `suggest_delivered` is the prompt for marking an accepted request delivered: every requirement realising it is
    complete. It never changes the status.
    """

    request_id: UUID
    status: EnhancementRequestStatus
    decline_reason: str
    can_record: bool = Field(description="True when the request is delivered or declined, so telling requesters can be recorded.")
    requesters: list[LoopRequesterOut]
    informed_count: int
    open_count: int
    pain_points: list[LinkedRecordOut]
    realising_requirements: list[RealisingRequirementOut]
    all_requirements_complete: bool | None = Field(
        default=None, description="Whether every realising requirement is complete; null when there are none."
    )
    suggest_delivered: bool


class OpenLoopOut(BaseModel):
    """A delivered or declined request with requesters still to be told."""

    request: RequestRefOut
    status: EnhancementRequestStatus
    decline_reason: str
    requester_count: int
    open_count: int
    uninformed: list[RequesterOut]
