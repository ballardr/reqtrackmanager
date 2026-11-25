"""
Module: modules.traceability.schemas

Request and response models of the governance profile API (`router` for the organisation, `project_router` for a
project), including a profile's lifecycle policy and the approval and review policy of a profile or a project.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import (
    EXEMPTION_REASON_MAX_LENGTH,
    PROFILE_DESCRIPTION_MAX_LENGTH,
    PROFILE_NAME_MAX_LENGTH,
)
from app.schemas.principal import PrincipalOut, PrincipalRef


class ProfileTargetIn(BaseModel):
    """A project a profile reaches.

    Attributes:
        project_id: The project.
        include_children: Whether its nested child projects are reached too.
    """

    project_id: UUID
    include_children: bool = False


class ProfileTargetOut(ProfileTargetIn):
    """A reached project with its name."""

    project_name: str


class ProfileCreate(BaseModel):
    """Creates a profile.

    Attributes:
        name: Unique within the organisation, ignoring case.
        description: A short summary.
        mode: `enforced`, `default` or `opt_in`.
        target_kind: `all_projects` or `selected_projects`.
        targets: The reached projects of a `selected_projects` profile.
    """

    name: str = Field(min_length=1, max_length=PROFILE_NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=PROFILE_DESCRIPTION_MAX_LENGTH)
    mode: ProfileMode
    target_kind: ProfileTargetKind = ProfileTargetKind.ALL_PROJECTS
    targets: list[ProfileTargetIn] = Field(default_factory=list, max_length=1000)


class ProfileUpdate(BaseModel):
    """Changes a profile's name, description or mode; a field left out is unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=PROFILE_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=PROFILE_DESCRIPTION_MAX_LENGTH)
    mode: ProfileMode | None = None


class ProfileTargetsSet(BaseModel):
    """Replaces the projects a profile reaches."""

    target_kind: ProfileTargetKind
    targets: list[ProfileTargetIn] = Field(default_factory=list, max_length=1000)


class ExemptionSet(BaseModel):
    """Exempts a project from an Enforced profile (or updates the exemption).

    Attributes:
        project_id: The exempt project.
        include_children: Whether its nested child projects are exempt too.
        reason: Why, kept for audit and review.
    """

    project_id: UUID
    include_children: bool = False
    reason: str = Field(default="", max_length=EXEMPTION_REASON_MAX_LENGTH)


class ProfileExemptionOut(BaseModel):
    """An exemption with the project's name."""

    project_id: UUID
    project_name: str
    include_children: bool
    reason: str


class ProfileContributionOut(BaseModel):
    """How many policy rows of one kind a profile holds.

    Attributes:
        key: The kind, namespaced as `<module_key>:<key>`.
        name: Its formal name.
        count: The profile's rows of that kind.
    """

    key: str
    name: str
    count: int


class ProfileOut(BaseModel):
    """A profile with what it reaches, who is exempt and what policy it holds."""

    id: UUID
    name: str
    description: str
    mode: ProfileMode
    target_kind: ProfileTargetKind
    targets: list[ProfileTargetOut]
    exemptions: list[ProfileExemptionOut]
    contributions: list[ProfileContributionOut]
    created_at: datetime
    updated_at: datetime


class ProfileProjectOut(BaseModel):
    """What a profile does for one project.

    Attributes:
        project_id: The project.
        project_name: Its name.
        outcome: The profile's `ProfileOutcome` for it.
        applies: Whether the profile's policy applies to the project.
        choice: The project's stored choice (`True` opted in, `False` opted out), or `None`.
    """

    project_id: UUID
    project_name: str
    outcome: ProfileOutcome
    applies: bool
    choice: bool | None


class ProfileDetailOut(ProfileOut):
    """A profile with its effect on every project of the organisation (projects it does not reach are left out)."""

    projects: list[ProfileProjectOut]


class ChoiceSet(BaseModel):
    """A project's choice about a profile.

    Attributes:
        opted_in: `False` to opt out of a Default profile, `True` to opt in to an Opt-in profile, `null` to clear the
            project's choice.
    """

    opted_in: bool | None


class ProjectProfileOut(BaseModel):
    """One profile as it concerns a project.

    Attributes:
        id: The profile.
        name: Its name.
        description: Its summary.
        mode: `enforced`, `default` or `opt_in`.
        outcome: What it does for the project.
        applies: Whether its policy applies to the project.
        choice: The project's stored choice, or `None`.
        can_choose: Whether the project may record a choice (a Default or Opt-in profile that reaches it).
    """

    id: UUID
    name: str
    description: str
    mode: ProfileMode
    outcome: ProfileOutcome
    applies: bool
    choice: bool | None
    can_choose: bool


class ProjectProfilesOut(BaseModel):
    """The profiles that reach a project.

    Attributes:
        can_manage: Whether the caller may record the project's choices.
        profiles: Every profile reaching the project, Enforced first, then by name.
    """

    can_manage: bool
    profiles: list[ProjectProfileOut]


class LifecycleStateOut(BaseModel):
    """One optional state of a lifecycle that a profile may require."""

    key: str
    label: str


class LifecycleTypePolicyOut(BaseModel):
    """A profile's requirement for one record type.

    Attributes:
        artefact_type: The registered record type.
        label: The type's singular name.
        module_key: The module that owns the type, empty for a core type.
        states: The optional states of the type, in path order.
        required: The states the profile requires.
    """

    artefact_type: str
    label: str
    module_key: str
    states: list[LifecycleStateOut]
    required: list[str]


class ProfileLifecycleOut(BaseModel):
    """A profile's lifecycle policy.

    Attributes:
        types: Every record type with optional states that the organisation can use.
        skip_forbidden: Whether the profile forbids skipping steps.
    """

    types: list[LifecycleTypePolicyOut]
    skip_forbidden: bool


class LifecycleRequiredSet(BaseModel):
    """The states a profile requires of one record type; an empty list removes the requirement."""

    required: list[str] = Field(default_factory=list, max_length=50)


class LifecycleSkipSet(BaseModel):
    """Whether a profile forbids skipping steps."""

    forbidden: bool


class ApproverRoleIn(BaseModel):
    """A role an approval policy names.

    Attributes:
        kind: `project` (a fixed project role), `module` (a role a module contributes) or `custom` (an organisation's
            custom role).
        key: The role within its kind: the project role value, `<module key>:<role key>`, or the custom role's id.
    """

    kind: Literal["project", "module", "custom"]
    key: str = Field(min_length=1, max_length=200)


class ApproverRoleOut(ApproverRoleIn):
    """A role with its display name (`label` is the key when the role is no longer offered)."""

    label: str


class ApproverRoleOptionOut(ApproverRoleOut):
    """A role a policy may name.

    Attributes:
        scope: `project` when the role is granted within a project, `org` when it is granted for the organisation.
    """

    scope: Literal["org", "project"]


class ApprovalRolesSet(BaseModel):
    """The roles a profile adds as approvers of one record type; an empty list removes the profile's policy for it."""

    roles: list[ApproverRoleIn] = Field(default_factory=list, max_length=100)


class ProjectApprovalRolesSet(BaseModel):
    """The roles a project adds as approvers of one record type.

    Attributes:
        roles: The roles; an empty list is a choice of no extra approvers (the nearest ancestor project's roles stop
            applying); `null` removes the project's row so it follows the nearest ancestor's.
    """

    roles: list[ApproverRoleIn] | None = Field(default=None, max_length=100)


class ApprovalTypeOut(BaseModel):
    """A record type with an approval gate.

    Attributes:
        artefact_type: The registered record type.
        label: The type's singular name.
        module_key: The module that owns the type, empty for a core type.
    """

    artefact_type: str
    label: str
    module_key: str


class ProfileApprovalTypeOut(ApprovalTypeOut):
    """A profile's roles for one record type."""

    roles: list[ApproverRoleOut]


class ProfileApprovalOut(BaseModel):
    """A profile's approval policy.

    Attributes:
        types: Every record type with an approval gate that the organisation can use.
        role_options: The roles the policy may name.
    """

    types: list[ProfileApprovalTypeOut]
    role_options: list[ApproverRoleOptionOut]


class RoleSourceOut(BaseModel):
    """An effective role with where it comes from.

    Attributes:
        role: The role.
        sources: Names of the profiles that give it, then `project` and `parent_project` when the project's own or the
            nearest ancestor's row does.
    """

    role: ApproverRoleOut
    sources: list[str]


class ProjectApprovalTypeOut(ApprovalTypeOut):
    """A project's approval policy for one record type.

    Attributes:
        own: The project's own roles, `null` when it has no row.
        inherited_from: Name of the ancestor project whose row applies, `null` when none does.
        effective: Every role that applies, with its sources.
    """

    own: list[ApproverRoleOut] | None
    inherited_from: str | None
    effective: list[RoleSourceOut]


class ProjectApprovalOut(BaseModel):
    """A project's approval policy.

    Attributes:
        can_manage: Whether the caller may change the project's own roles.
        types: Every record type with an approval gate that the project's organisation can use.
        role_options: The roles the policy may name.
    """

    can_manage: bool
    types: list[ProjectApprovalTypeOut]
    role_options: list[ApproverRoleOptionOut]


class ReviewSettingsIn(BaseModel):
    """The review settings of one record type; each is optional and an unset one changes nothing.

    Attributes:
        interval_days: The longest gap between reviews in days.
        lead_days: Days before the due date that the reminder is sent.
        default_owner: A user or a group reminded when a record has no reviewer (a project group only in a project's own
            policy).
    """

    interval_days: int | None = Field(default=None, ge=1, le=3650)
    lead_days: int | None = Field(default=None, ge=0, le=365)
    default_owner: PrincipalRef | None = None


class ReviewSettingsOut(BaseModel):
    """The review settings one owner gives a record type, with the default owner resolved for display."""

    interval_days: int | None
    lead_days: int | None
    default_owner: PrincipalOut | None


class ProjectReviewSettingsSet(BaseModel):
    """A project's review settings for one record type.

    Attributes:
        settings: The settings; one with nothing set is a choice of no review policy (the nearest ancestor project's
            stops applying); `null` removes the project's row so it follows the nearest ancestor's.
    """

    settings: ReviewSettingsIn | None = None


class ReviewTypeOut(BaseModel):
    """A record type with a review schedule.

    Attributes:
        artefact_type: The registered record type.
        label: The type's singular name.
        module_key: The module that owns the type, empty for a core type.
    """

    artefact_type: str
    label: str
    module_key: str


class ProfileReviewTypeOut(ReviewTypeOut):
    """A profile's review settings for one record type."""

    settings: ReviewSettingsOut


class ProfileReviewOut(BaseModel):
    """A profile's review policy.

    Attributes:
        types: Every record type with a review schedule that the organisation can use.
    """

    types: list[ProfileReviewTypeOut]


class EffectiveReviewOut(BaseModel):
    """What review policy applies to a record type in a project, with where each setting comes from.

    Attributes:
        interval_days: The shortest interval any source gives, `null` for none.
        interval_source: The source of the interval: a profile name, `project` or `parent_project`.
        lead_days: The longest reminder lead any source gives, `null` for none.
        lead_source: The source of the lead.
        default_owner: The first default owner in precedence order, `null` for none.
        owner_source: The source of the default owner.
    """

    interval_days: int | None
    interval_source: str | None
    lead_days: int | None
    lead_source: str | None
    default_owner: PrincipalOut | None
    owner_source: str | None


class ProjectReviewTypeOut(ReviewTypeOut):
    """A project's review policy for one record type.

    Attributes:
        own: The project's own settings, `null` when it has no row.
        inherited_from: Name of the ancestor project whose row applies, `null` when none does.
        effective: What applies, with its sources.
    """

    own: ReviewSettingsOut | None
    inherited_from: str | None
    effective: EffectiveReviewOut


class ProjectReviewOut(BaseModel):
    """A project's review policy.

    Attributes:
        can_manage: Whether the caller may change the project's own settings.
        types: Every record type with a review schedule that the project's organisation can use.
    """

    can_manage: bool
    types: list[ProjectReviewTypeOut]
