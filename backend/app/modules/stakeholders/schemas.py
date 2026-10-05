"""
Module: modules.stakeholders.schemas

Pydantic request/response schemas for the Stakeholders & Personas module's
org- and project-scoped routers (Phase 1.1: Persona, persona types, weight
overrides, comments; Phase 1.2: Stakeholder, its representation links and the
cadence hint; Phase 2: Stakeholder Need and its links). Type-vocabulary and file schemas are shared by both artefacts.

`PersonaUpdate`/`StakeholderUpdate` are partial: only fields present in the
request body change, so a nullable field (weight, owner, champion, type,
cadence, levels) can be cleared by sending an explicit `null`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.stakeholders.enums import (
    NeedStatus,
    PersonaScope,
    PersonaStatus,
    StakeholderScope,
    StakeholderStatus,
    TargetCadence,
)
from app.schemas.file import FileAssetOut

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
    owner_id: UUID | None = None
    champion_id: UUID | None = None


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
    owner_id: UUID | None = None
    champion_id: UUID | None = None
    change_note: str = ""


class PersonaOut(BaseModel):
    """A persona merged with its current version. `effective_weight` and
    `weight_override`/`weight_source` are populated only by the project router:
    the resolved weight for that project, the project's own override (if any),
    and the tier the resolved weight came from."""

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
    owner_id: UUID | None
    champion_id: UUID | None
    version_number: int

    effective_weight: float | None = None
    weight_override: float | None = None
    weight_source: Literal["project", "ancestor_project", "persona", "none"] | None = None

    created_at: datetime
    updated_at: datetime


class PersonaVersionOut(BaseModel):
    """One historical snapshot."""

    model_config = {"from_attributes": True}

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
    owner_id: UUID | None
    champion_id: UUID | None
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


class PersonaTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PersonaTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class PersonaTypeOut(BaseModel):
    """An org-scoped `PersonaTypeDefinition` row."""

    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool


class EffectiveTypeOut(BaseModel):
    """One row of a project's merged type list (`type_vocabulary.EffectiveType`)."""

    model_config = {"from_attributes": True}

    id: UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


class ProjectTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_order: int | None = None


class ProjectTypeOverrideUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    display_order: int | None = None
    is_enabled: bool | None = None


class ProjectTypeOut(BaseModel):
    """A raw project type row (override or project-local)."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    org_type_id: UUID | None
    name_override: str | None
    display_order_override: int | None
    is_enabled: bool


# --- Stakeholder (Phase 1.2) --------------------------------------------------


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
    owner_id: UUID | None = None
    user_id: UUID | None = None


class StakeholderFromUserCreate(BaseModel):
    """"Create stakeholder from org user" (resolution 13): name and contact
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
    owner_id: UUID | None = None
    user_id: UUID | None = None
    change_note: str = ""


class StakeholderOut(BaseModel):
    """A stakeholder merged with its current version."""

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
    owner_id: UUID | None
    user_id: UUID | None
    version_number: int

    created_at: datetime
    updated_at: datetime


class StakeholderVersionOut(BaseModel):
    """One historical snapshot (contact info is deliberately omitted from the
    history listing; it is Confidential and the current value is on the record)."""

    model_config = {"from_attributes": True}

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
    owner_id: UUID | None
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
    """The power/interest read-out for a pair of levels (resolution 21):
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
StakeholderTypeCreate = PersonaTypeCreate
StakeholderTypeUpdate = PersonaTypeUpdate
StakeholderTypeOut = PersonaTypeOut

StakeholderTransitionRequest = PersonaTransitionRequest
StakeholderCommentCreate = PersonaCommentCreate
StakeholderCommentUpdate = PersonaCommentUpdate


# --- Stakeholder Need (Phase 2) -----------------------------------------------


class NeedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    rationale: str = ""
    owner_id: UUID | None = None


class NeedUpdate(BaseModel):
    """Partial update; `status` is not editable here — use the lifecycle endpoints."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    rationale: str | None = None
    owner_id: UUID | None = None
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
    owner_id: UUID | None
    version_number: int

    created_at: datetime
    updated_at: datetime


class NeedVersionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    need_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None
    name: str
    description: str
    rationale: str
    status: NeedStatus
    owner_id: UUID | None
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
