"""
Module: modules.stakeholders.schemas

Pydantic request/response schemas for the Stakeholders & Personas module's
org- and project-scoped routers (Persona, persona types, weight
overrides, comments; Stakeholder, its representation links and the
cadence hint: Stakeholder Need and its links: Stakeholder
Groups: Engagements and the research extras). Type-vocabulary and file schemas are shared by both artefacts.

`PersonaUpdate`/`StakeholderUpdate` are partial: only fields present in the
request body change, so a nullable field (weight, owner, champion, type,
cadence, levels) can be cleared by sending an explicit `null`.

`owner` and `champion` are principals: a user, an organisation group or (on a
project-scoped record) a project group. Requests send a `PrincipalRef`
(`{type, id}`); responses return a resolved `PrincipalOut` (`_principals.py`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.stakeholders.enums import (
    EngagementChannel,
    NeedStatus,
    PersonaScope,
    PersonaStatus,
    StakeholderScope,
    StakeholderStatus,
    TargetCadence,
)
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef

# A positive, finite importance weight (`inf` would poison a weighted roll-up).
Weight = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    persona_type_id: UUID | None = None
    role_title: str = Field(default="", max_length=300)
    goals: str = ""
    needs: str = ""
    behaviours: str = ""
    context_environment: str = ""
    skills_proficiency: str = ""
    frequency_of_use: str = ""
    constraints: str = ""
    weight: Weight | None = None
    owner: PrincipalRef | None = None
    champion: PrincipalRef | None = None


class PersonaUpdate(BaseModel):
    """Partial update; see module docstring. `status` is not editable here —
    use the lifecycle endpoints."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    persona_type_id: UUID | None = None
    role_title: str | None = Field(default=None, max_length=300)
    goals: str | None = None
    needs: str | None = None
    behaviours: str | None = None
    context_environment: str | None = None
    skills_proficiency: str | None = None
    frequency_of_use: str | None = None
    constraints: str | None = None
    weight: Weight | None = None
    owner: PrincipalRef | None = None
    champion: PrincipalRef | None = None
    change_note: str = ""


class PersonaOut(BaseModel):
    """A persona merged with its current version. `effective_weight` and
    `weight_override`/`weight_source` are populated only by the project router:
    the resolved weight for that project, the project's own override (if any),
    and the tier the resolved weight came from. `project_hidden`,
    `hidden_override` and `hidden_source` are likewise project-router-only, for an
    org persona: whether it is hidden from the project, the project's own
    override (`None` when it only inherits) and the tier the value came from."""

    id: UUID
    scope: PersonaScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    name: str
    description: str
    persona_type_id: UUID | None
    persona_type_name: str | None
    role_title: str
    goals: str
    needs: str
    behaviours: str
    context_environment: str
    skills_proficiency: str
    frequency_of_use: str
    constraints: str
    weight: float | None
    status: PersonaStatus
    owner: PrincipalOut | None
    champion: PrincipalOut | None
    version_number: int

    effective_weight: float | None = None
    weight_override: float | None = None
    weight_source: Literal["project", "ancestor_project", "persona", "none"] | None = None

    project_hidden: bool | None = None
    hidden_override: bool | None = None
    hidden_source: str | None = None

    created_at: datetime
    updated_at: datetime


class PersonaVersionOut(BaseModel):
    """One historical snapshot."""

    id: UUID
    persona_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    description: str
    org_type_id: UUID | None
    project_type_id: UUID | None
    role_title: str
    goals: str
    needs: str
    behaviours: str
    context_environment: str
    skills_proficiency: str
    frequency_of_use: str
    constraints: str
    weight: float | None
    status: PersonaStatus
    owner: PrincipalOut | None
    champion: PrincipalOut | None
    change_note: str
    created_by: UUID
    created_at: datetime


class PersonaTransitionRequest(BaseModel):
    comment: str | None = None


class PersonaWeightSet(BaseModel):
    weight: Weight


class PersonaCommentCreate(BaseModel):
    body: str = Field(min_length=1)


class PersonaCommentUpdate(BaseModel):
    body: str = Field(min_length=1)


class PersonaCommentOut(BaseModel):
    id: UUID
    persona_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


# --- Stakeholder --------------------------------------------------


class StakeholderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    stakeholder_type_id: UUID | None = None
    role: str = Field(default="", max_length=300)
    organisation_group: str = Field(default="", max_length=300)
    interests: str = ""
    responsibilities: str = ""
    goals_needs: str = ""
    priorities: str = ""
    constraints: str = ""
    workflows_scenarios: str = ""
    contact_info: str = ""
    target_cadence: TargetCadence | None = None
    availability_constraints: str = ""
    influence_level_id: UUID | None = None
    interest_level_id: UUID | None = None
    owner: PrincipalRef | None = None
    user_id: UUID | None = None


class StakeholderFromUserCreate(BaseModel):
    """"Create stakeholder from org user": name and contact
    info are prefilled from the user; the rest is optional."""

    user_id: UUID
    stakeholder_type_id: UUID | None = None
    role: str = Field(default="", max_length=300)
    organisation_group: str = Field(default="", max_length=300)
    target_cadence: TargetCadence | None = None


class StakeholderUpdate(BaseModel):
    """Partial update; `status` is not editable here — use the lifecycle endpoints."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    stakeholder_type_id: UUID | None = None
    role: str | None = Field(default=None, max_length=300)
    organisation_group: str | None = Field(default=None, max_length=300)
    interests: str | None = None
    responsibilities: str | None = None
    goals_needs: str | None = None
    priorities: str | None = None
    constraints: str | None = None
    workflows_scenarios: str | None = None
    contact_info: str | None = None
    target_cadence: TargetCadence | None = None
    availability_constraints: str | None = None
    influence_level_id: UUID | None = None
    interest_level_id: UUID | None = None
    owner: PrincipalRef | None = None
    user_id: UUID | None = None
    change_note: str = ""


class StakeholderGroupRefOut(BaseModel):
    """A group a stakeholder is directly in, as shown on the stakeholder."""

    id: UUID
    name: str
    scope: StakeholderScope
    parent_group_id: UUID | None


class StakeholderOut(BaseModel):
    """A stakeholder merged with its current version. `project_hidden` and
    `hidden_override` are populated only for an org stakeholder returned by the
    project router: whether it is hidden from that project, and the project's
    own override (`None` when it only inherits). `hidden_source` is the tier the
    effective value came from (`project`, `ancestor_project`) or `None`."""

    id: UUID
    scope: StakeholderScope
    organization_id: UUID | None
    project_id: UUID | None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    name: str
    description: str
    stakeholder_type_id: UUID | None
    stakeholder_type_name: str | None
    role: str
    organisation_group: str
    interests: str
    responsibilities: str
    goals_needs: str
    priorities: str
    constraints: str
    workflows_scenarios: str
    contact_info: str
    target_cadence: TargetCadence | None
    availability_constraints: str
    influence_level_id: UUID | None
    interest_level_id: UUID | None
    status: StakeholderStatus
    owner: PrincipalOut | None
    user_id: UUID | None
    version_number: int

    created_at: datetime
    updated_at: datetime

    project_hidden: bool | None = None
    hidden_override: bool | None = None
    hidden_source: str | None = None
    groups: list[StakeholderGroupRefOut] = Field(default_factory=list)
    # Project router only: the date of the project's latest engagement the stakeholder took part in.
    last_engaged: date | None = None


class VisibilitySet(BaseModel):
    """Body of a project's Persona/Stakeholder visibility override endpoint."""

    hidden: bool


class StakeholderVersionOut(BaseModel):
    """One historical snapshot (contact info is deliberately omitted from the
    history listing; it is Confidential and the current value is on the record)."""

    id: UUID
    stakeholder_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    description: str
    org_type_id: UUID | None
    project_type_id: UUID | None
    role: str
    organisation_group: str
    target_cadence: TargetCadence | None
    influence_level_id: UUID | None
    interest_level_id: UUID | None
    status: StakeholderStatus
    owner: PrincipalOut | None
    user_id: UUID | None
    change_note: str
    created_by: UUID
    created_at: datetime


class StakeholderCommentOut(BaseModel):
    id: UUID
    stakeholder_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class CadenceHintOut(BaseModel):
    """The power/interest read-out for a pair of levels:
    `quadrant` is `None` unless both levels are set; `suggested_cadence` is a
    hint only and never applied automatically."""

    quadrant: Literal["manage_closely", "keep_satisfied", "keep_informed", "monitor"] | None
    suggested_cadence: TargetCadence | None


class RepresentedPersonaOut(BaseModel):
    """One "represents" link, seen from either end: the linked record's id
    and display name, its scope, and the link's own id (for removal)."""

    link_id: UUID
    id: UUID
    name: str
    scope: Literal["organization", "project"]


class RepresentsCreate(BaseModel):
    persona_id: UUID


# These schemas are identical for every artefact in this module; Stakeholder
# reuses the Persona ones under its own names.

StakeholderTransitionRequest = PersonaTransitionRequest
StakeholderCommentCreate = PersonaCommentCreate
StakeholderCommentUpdate = PersonaCommentUpdate


# --- Stakeholder Need -----------------------------------------------


class NeedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    rationale: str = ""
    owner: PrincipalRef | None = None


class NeedUpdate(BaseModel):
    """Partial update; `status` is not editable here — use the lifecycle endpoints."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    rationale: str | None = None
    owner: PrincipalRef | None = None
    change_note: str = ""


class NeedOut(BaseModel):
    """A need merged with its current version."""

    id: UUID
    project_id: UUID
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None
    archived_by: UUID | None

    name: str
    description: str
    rationale: str
    status: NeedStatus
    owner: PrincipalOut | None
    version_number: int

    created_at: datetime
    updated_at: datetime


class NeedVersionOut(BaseModel):
    id: UUID
    need_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    description: str
    rationale: str
    status: NeedStatus
    owner: PrincipalOut | None
    change_note: str
    created_by: UUID
    created_at: datetime


class NeedCommentOut(BaseModel):
    id: UUID
    need_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class NeedHolderOut(BaseModel):
    """One "has need" link seen from the need: the Stakeholder or Persona that
    has it (`kind`), its id, display name and scope, and the link's own id."""

    link_id: UUID
    kind: Literal["stakeholder", "persona"]
    id: UUID
    name: str
    scope: Literal["organization", "project"]


class NeedHolderCreate(BaseModel):
    kind: Literal["stakeholder", "persona"]
    id: UUID


class HeldNeedOut(BaseModel):
    """One "has need" link seen from a Stakeholder or Persona: the need."""

    link_id: UUID
    id: UUID
    name: str
    status: NeedStatus


class NeedRequirementOut(BaseModel):
    """One "gives rise to" link: the Requirement (id, unique code, title)."""

    link_id: UUID
    id: UUID
    unique_code: str
    title: str


class NeedRequirementCreate(BaseModel):
    requirement_id: UUID


NeedTransitionRequest = PersonaTransitionRequest
NeedCommentCreate = PersonaCommentCreate
NeedCommentUpdate = PersonaCommentUpdate


# --- Relationships -------------------------------------------------


class RelationshipKindOut(BaseModel):
    """One declared relationship kind, including whether each target type can
    be linked to yet (a reserved kind has `available_target_types == []`)."""

    key: str
    forward: str
    reverse: str
    holder_types: list[str]
    target_types: list[str]
    available_target_types: list[str]


class RelationshipCreate(BaseModel):
    kind: str
    target_type: str
    target_id: UUID


class RelationshipOut(BaseModel):
    """One relationship seen from its Stakeholder/Persona: the kind and the target."""

    link_id: UUID
    kind: str
    forward: str
    target_type: str
    target_id: UUID
    label: str
    status: str | None = None
    is_archived: bool = False


class RelationshipTargetOut(BaseModel):
    """One record a relationship picker can offer."""

    id: UUID
    label: str
    status: str | None = None


class IncomingRelationshipOut(BaseModel):
    """One relationship seen from its target: the Stakeholder/Persona."""

    link_id: UUID
    kind: str
    reverse: str
    holder_type: Literal["stakeholder", "persona"]
    holder_id: UUID
    holder_name: str
    scope: str


# --- Stakeholder Groups --------------------------------------------


class StakeholderGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_group_id: UUID | None = None
    exclusive_children: bool = False


class StakeholderGroupUpdate(BaseModel):
    """Partial: an explicit `parent_group_id: null` moves the group to the top level."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    parent_group_id: UUID | None = None
    exclusive_children: bool | None = None


class StakeholderGroupOut(BaseModel):
    """A group with its direct member and child counts (members hidden from the viewing project are not counted)."""

    id: UUID
    scope: StakeholderScope
    organization_id: UUID | None
    project_id: UUID | None
    parent_group_id: UUID | None
    name: str
    description: str
    exclusive_children: bool
    sort_order: int
    member_count: int
    child_count: int


class StakeholderGroupMemberOut(BaseModel):
    """One stakeholder in a group; `direct` is false when it is only in a descendant."""

    stakeholder_id: UUID
    name: str
    scope: StakeholderScope
    direct: bool


class StakeholderGroupMemberCreate(BaseModel):
    stakeholder_id: UUID


class StakeholderGroupIdsSet(BaseModel):
    """Body of `PUT .../stakeholders/{id}/groups`: the full set of this tier's groups to be in."""

    group_ids: list[UUID]


class GroupTextProposalOut(BaseModel):
    """A distinct "organisation / group" text value that could become a group."""

    name: str
    stakeholder_count: int
    existing_group_id: UUID | None


class GroupFromTextCreate(BaseModel):
    names: list[str] = Field(min_length=1)


class GroupFromTextOut(BaseModel):
    root_group_id: UUID
    group_ids: list[UUID]
    memberships_added: int


# --- Engagements ------------------------------------------------------


class EngagementCreate(BaseModel):
    """Logs an engagement. `stakeholder_ids`, `persona_ids` and `group_ids` are optional shortcuts that
    add participants, covered personas and audience groups (each group expanded to its current
    members) in the same request, e.g. the "Log contact" quick-add."""

    title: str = Field(min_length=1, max_length=300)
    channel: EngagementChannel
    engagement_date: date
    facilitators: list[PrincipalRef] = Field(default_factory=list)
    purpose: str = ""
    summary: str = ""
    notes: str = ""
    consent_recorded: bool = False
    retain_until: date | None = None
    stakeholder_ids: list[UUID] = Field(default_factory=list)
    persona_ids: list[UUID] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)


class EngagementUpdate(BaseModel):
    """Partial update: only fields present in the request body change, so `retain_until` can be cleared with an
    explicit `null`. `facilitators`, when sent, replaces the whole list (`[]` or `null` removes everyone)."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    channel: EngagementChannel | None = None
    engagement_date: date | None = None
    facilitators: list[PrincipalRef] | None = None
    purpose: str | None = None
    summary: str | None = None
    notes: str | None = None
    consent_recorded: bool | None = None
    retain_until: date | None = None


class EngagementOut(BaseModel):
    """An engagement. `retention_due` is true once `retain_until` has been reached; the counts are of
    Stakeholder participants and (research extras) anonymous participants."""

    id: UUID
    project_id: UUID
    creator_id: UUID
    unique_code: str
    title: str
    channel: EngagementChannel
    engagement_date: date
    facilitators: list[PrincipalOut]
    purpose: str
    summary: str
    notes: str
    consent_recorded: bool
    retain_until: date | None
    retention_due: bool
    participant_count: int
    anonymous_participant_count: int

    created_at: datetime
    updated_at: datetime


class StakeholderEngagementOut(BaseModel):
    """One row of a Stakeholder's engagement timeline (no notes: open the engagement for those)."""

    id: UUID
    title: str
    channel: EngagementChannel
    engagement_date: date


class EngagementParticipantOut(BaseModel):
    """One Stakeholder participant: the link's own id, and the Stakeholder."""

    link_id: UUID
    stakeholder_id: UUID
    name: str
    scope: Literal["organization", "project"]


class EngagementParticipantCreate(BaseModel):
    stakeholder_id: UUID


class EngagementPersonaOut(BaseModel):
    """One Persona the engagement covered."""

    link_id: UUID
    persona_id: UUID
    name: str
    scope: Literal["organization", "project"]


class EngagementPersonaCreate(BaseModel):
    persona_id: UUID


class EngagementAudienceOut(BaseModel):
    """One Stakeholder group the engagement was aimed at."""

    link_id: UUID
    group_id: UUID
    name: str
    scope: Literal["organization", "project"]


class EngagementAudienceCreate(BaseModel):
    group_id: UUID


class EngagementAudienceAdded(BaseModel):
    """Result of adding an audience group: the audience link and the members it added as participants
    (a snapshot; `already_participating` members were left as they were)."""

    audience: EngagementAudienceOut
    participants_added: list[EngagementParticipantOut]
    already_participating: int


class OutcomeOut(BaseModel):
    """One "raised"/"answered" link from an engagement or finding to a Pain Point, Need or Open Question."""

    link_id: UUID
    kind: Literal["raised", "answered"]
    target_type: str
    target_id: UUID
    label: str


class OutcomeCreate(BaseModel):
    kind: Literal["raised", "answered"]
    target_type: str
    target_id: UUID


class EngagementCommentOut(BaseModel):
    id: UUID
    engagement_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


EngagementCommentCreate = PersonaCommentCreate
EngagementCommentUpdate = PersonaCommentUpdate


class PromptCreate(BaseModel):
    prompt: str = Field(min_length=1)
    response_notes: str = ""


class PromptUpdate(BaseModel):
    prompt: str | None = Field(default=None, min_length=1)
    response_notes: str | None = None


class PromptMove(BaseModel):
    direction: Literal["up", "down"]


class PromptOut(BaseModel):
    id: UUID
    engagement_id: UUID
    sort_order: int
    prompt: str
    response_notes: str


class AnonymousParticipantCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    persona_id: UUID | None = None


class AnonymousParticipantUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    persona_id: UUID | None = None


class AnonymousParticipantOut(BaseModel):
    id: UUID
    engagement_id: UUID
    label: str
    persona_id: UUID | None
    persona_name: str | None


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""


class FindingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None


class FindingOut(BaseModel):
    id: UUID
    project_id: UUID
    engagement_id: UUID
    creator_id: UUID
    unique_code: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
