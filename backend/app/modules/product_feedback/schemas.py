"""
Module: modules.product_feedback.schemas

Pydantic request/response schemas for Product Feedback's routers: request create / update / out,
version history, lifecycle transitions, comments and the project settings.

`RequestUpdate` is partial: only fields present in the request body change, so a nullable field
(the owner) can be cleared by sending an explicit `null`. `status` is not
editable here (the transition endpoint owns it).

Scoring levels are a map of axis key to level id (`levels`), optional and clearable per axis (an axis sent as `null`
is cleared, one not mentioned is kept). A response carries them with the scores derived under each model scored
(`scores`; `score` / `scoring_model_key` are the primary one; null while an axis the model needs is unset), and
`derived_levels` for an axis read from the request's demand.

A request also reports its place in a merge (`merged_into`, `merged_count`), its demand
(`requester_count`, `weighted_demand`; see `demand.py`), the problems and work it is linked to (`pain_point_count`,
`requirement_count`; `relationships.py`) and how many requesters were told its outcome (`informed_count`,
`loop_open_count`; `loop.py`). All are derived, never written here.

External references are a list of their own (`ExternalRefIn` / `ExternalRefOut`): a create payload may carry the
initial ones, later changes use the reference endpoints and are not versions of the request. The single
`external_ref_url` / `external_ref_key` pair older clients send is still accepted on create and update, as a delivery
reference on the "Other" system, and is never returned.

`owner` is a principal: a user, an organisation group or a project group. Requests send a
`PrincipalRef` (`{type, id}`; null clears it) and responses return a resolved `PrincipalOut`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.modules.product_feedback.enums import (
    EnhancementRequestScope,
    EnhancementRequestStatus,
    ExternalRefRole,
    SubmissionPolicy,
)
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow


def check_web_url(value: str | None) -> str | None:
    """Accepts only an absolute `http` or `https` URL (or nothing). The reference is rendered as a link, and a
    `javascript:` or `data:` URL stored there would run in the viewer's browser or in an export.

    Raises:
        ValueError: If a non-empty value is not an http(s) URL with a host.
    """
    if not value:
        return value
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("A link must be an http or https URL.")
    return value.strip()


class ExternalRefIn(BaseModel):
    """A new external reference: the system (an id from the request's tier's external system list), the item's key
    and/or link, and its role."""

    system_id: UUID
    key: str = Field(default="", max_length=100)
    url: str | None = Field(default=None, max_length=500)
    role: ExternalRefRole = ExternalRefRole.DELIVERY

    _check_url = field_validator("url")(check_web_url)

    @model_validator(mode="after")
    def _needs_key_or_url(self) -> ExternalRefIn:
        if not self.key.strip() and not self.url:
            raise ValueError("A reference needs a key or a link.")
        return self


class ExternalRefUpdate(BaseModel):
    """Partial change of a reference: only fields present change (`url` null clears the link)."""

    system_id: UUID | None = None
    key: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=500)
    role: ExternalRefRole | None = None

    _check_url = field_validator("url")(check_web_url)


class ExternalRefOut(BaseModel):
    """A reference with its system's name. `system_id` is accepted back by the request's tier's system picker."""

    id: UUID
    request_id: UUID
    system_id: UUID
    system_name: str
    key: str
    url: str | None = None
    role: ExternalRefRole
    created_by: UUID
    created_at: datetime


class RequestCreate(BaseModel):
    """Create payload; only `title` is required. `status` is not accepted (a request starts `NEW`)."""

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500, description="Deprecated: use `references`.")
    external_ref_key: str | None = Field(default=None, max_length=100, description="Deprecated: use `references`.")
    references: list[ExternalRefIn] = Field(default_factory=list, max_length=50)
    levels: dict[str, UUID | None] | None = Field(
        default=None, description="Scoring level id by axis key (`get scoring-scheme` lists them); null clears an axis."
    )

    _check_url = field_validator("external_ref_url")(check_web_url)


class RequestUpdate(BaseModel):
    """Partial update; see module docstring."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500, description="Deprecated: use the reference endpoints.")
    external_ref_key: str | None = Field(default=None, max_length=100, description="Deprecated: use the reference endpoints.")
    levels: dict[str, UUID | None] | None = Field(
        default=None, description="Scoring level id by axis key (`get scoring-scheme` lists them); null clears an axis."
    )
    change_note: str = ""

    _check_url = field_validator("external_ref_url")(check_web_url)


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


class ScorePreviewIn(BaseModel):
    """The levels of a request being filled in, to be scored without saving anything."""

    levels: dict[str, UUID | None] = Field(
        default_factory=dict, description="Scoring level id by axis key; null or absent means the axis is not scored.",
    )
    request_id: UUID | None = Field(
        default=None, description="An existing request of this owner, whose weighted demand the derived Demand axis reads.",
    )


class ScorePreviewOut(BaseModel):
    """What the given levels would score: each enabled model's score (null = not scored), the level each derived axis
    resolves to where none was given, and the weighted demand that was used."""

    scores: dict[str, RequestScoreOut | None]
    derived_levels: dict[str, UUID]
    weighted_demand: float


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
    external_refs: list[ExternalRefOut] = Field(default_factory=list)
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
    request_page_sections: list[str] | None = Field(
        default=None, description="The project's default order of the request page's sections; null is the built-in order.",
    )


class FeedbackAccessOut(BaseModel):
    """What the caller may do with this tier's requests, so the UI offers only controls the server will accept."""

    can_submit: bool = Field(description="May create a request (any member, unless the project restricted it to triagers).")
    can_triage: bool = Field(description="May edit, decide, merge, move, archive and attach evidence to requests.")


#: Keys of the request page's sections are short lowercase identifiers; the page ignores ones it does not know.
SECTION_KEY_PATTERN = r"^[a-z][a-z_]{0,39}$"


class FeedbackSettingsUpdate(BaseModel):
    """Settings changes: only the fields sent are changed. `request_page_sections` null returns to the built-in order."""

    submission_policy: SubmissionPolicy | None = None
    request_page_sections: list[Annotated[str, StringConstraints(pattern=SECTION_KEY_PATTERN)]] | None = Field(
        default=None, max_length=20,
        description="The default order of the request page's sections (each key once); null clears it.",
    )

    @model_validator(mode="after")
    def _keys_are_unique(self) -> FeedbackSettingsUpdate:
        """Each section key may appear once."""
        sections = self.request_page_sections
        if sections is not None and len(set(sections)) != len(sections):
            raise ValueError("Each section may appear only once.")
        return self


class ChannelOut(BaseModel):
    """The channel a requester asked through: the project's channel row (an id the channel picker accepts) and name."""

    id: UUID
    name: str


class RequesterOut(BaseModel):
    """One distinct party behind a request. `label` and `weight` are null (and `hidden` true) for a party the
    caller may not view; it still counts toward the totals. `channel` is how they asked, null when none was
    recorded (a requester reached through an Engagement is shown as an Engagement instead)."""

    artefact_type: str
    id: UUID
    label: str | None = None
    weight: float | None = None
    weight_source: str = Field(default="", description="Where the weight comes from (influence, persona, project, ancestor_project, none).")
    effective_weight: float
    from_merge: bool
    via_engagement: bool
    hidden: bool = False
    channel: ChannelOut | None = None
    link_id: UUID | None = Field(
        default=None,
        description="The request's own 'Requested by' link to this party (remove it with the generic link delete); "
        "null when the party is reached only through an Engagement or a merged duplicate.",
    )


class DemandEngagementOut(BaseModel):
    """An Engagement the request was raised in; `label` is null when the caller may not view it. `link_id` is the
    request's own 'Requested by' link to it (null for one reached only through a merged duplicate)."""

    id: UUID
    label: str | None = None
    hidden: bool = False
    link_id: UUID | None = None


class DemandOut(BaseModel):
    """A request's demand: one page of the distinct requesters (its own and those of requests merged into it,
    heaviest first; `offset` and `limit` say which page), the engagements it was raised in, and the totals, which
    cover every requester and not only the page."""

    request_id: UUID
    requester_count: int
    weighted_demand: float
    offset: int = 0
    limit: int = 0
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
    note: str = ""
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


class ChannelUpdate(BaseModel):
    """Sets (or, with a null `channel_id`, clears) how requesters asked. Every party must be a current requester of
    the request (`GET .../demand` lists them); `channel_id` is an id from the project's channel list."""

    parties: list[PartyRef] = Field(min_length=1, max_length=500)
    channel_id: UUID | None = None


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
