"""
Module: modules.traceability.schemas

Request and response models of the governance profile API (`router` for the organisation, `project_router` for a
project).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import (
    EXEMPTION_REASON_MAX_LENGTH,
    PROFILE_DESCRIPTION_MAX_LENGTH,
    PROFILE_NAME_MAX_LENGTH,
)


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
