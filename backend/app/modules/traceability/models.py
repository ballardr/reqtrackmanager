"""
Module: modules.traceability.models

Tables of the Traceability & Governance module: governance profiles (organisation-owned named policy sets), the projects
a profile targets, the projects exempt from an Enforced profile, each project's opt-in or opt-out and the lifecycle policy
rows a profile owns (the states it requires and whether it forbids skipping steps).

Design decisions:
- A profile holds no policy itself. Each policy table carries a `profile_id` (a `modules.seams.ProfileContributor`),
  so the profile mechanism needs no per-table code.
- A profile's required lifecycle state is one row per `(profile, type, state)`, as an organisation's requirement is
  (`models.lifecycle`); its ban on skipping steps is one row per profile. Both go with the profile when it is deleted.
- `mode` and `target_kind` are plain strings validated against `modules.traceability.enums`, not database enums.
- Targets, exemptions and choices are one row per `(profile, project)`; a project's deletion removes its rows. A target
  or exemption may cover the project's nested children (`include_children`).
- A choice records `opted_in` explicitly. Only an opt-out of a Default profile and an opt-in to an Opt-in profile have
  an effect; a row left from before the profile's mode changed is ignored when policy is resolved and is kept so
  that changing the mode back restores it.
- Choices do not fall back to an ancestor project: reach down the project tree is the organisation's decision
  (`include_children` on a target), and a manager of a parent project must not decide for children they may not manage.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin

PROFILE_NAME_MAX_LENGTH = 200
PROFILE_DESCRIPTION_MAX_LENGTH = 500
EXEMPTION_REASON_MAX_LENGTH = 500


class GovernanceProfile(UUIDPKMixin, TimestampMixin, Base):
    """A named set of governance policy an organisation applies to projects.

    Attributes:
        organization_id: The owning organisation.
        name: Unique within the organisation, ignoring case.
        description: A short summary of what the profile is for.
        mode: A `ProfileMode` value.
        target_kind: A `ProfileTargetKind` value; `selected_projects` uses `GovernanceProfileTarget` rows.
    """

    __tablename__ = "governance_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_governance_profiles_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(PROFILE_NAME_MAX_LENGTH))
    description: Mapped[str] = mapped_column(String(PROFILE_DESCRIPTION_MAX_LENGTH), default="")
    mode: Mapped[str] = mapped_column(String(16))
    target_kind: Mapped[str] = mapped_column(String(24))


class GovernanceProfileTarget(UUIDPKMixin, TimestampMixin, Base):
    """A project a `selected_projects` profile reaches.

    Attributes:
        profile_id: The profile.
        project_id: The targeted project.
        include_children: Whether the project's nested child projects are reached too.
    """

    __tablename__ = "governance_profile_targets"
    __table_args__ = (UniqueConstraint("profile_id", "project_id", name="uq_governance_profile_targets"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    include_children: Mapped[bool] = mapped_column(Boolean, default=False)


class GovernanceProfileExemption(UUIDPKMixin, TimestampMixin, Base):
    """A project an Enforced profile does not bind.

    Attributes:
        profile_id: The profile.
        project_id: The exempt project.
        include_children: Whether the project's nested child projects are exempt too.
        reason: Why the project is exempt, kept for audit and review.
    """

    __tablename__ = "governance_profile_exemptions"
    __table_args__ = (UniqueConstraint("profile_id", "project_id", name="uq_governance_profile_exemptions"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    include_children: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(EXEMPTION_REASON_MAX_LENGTH), default="")


class GovernanceProfileChoice(UUIDPKMixin, TimestampMixin, Base):
    """A project's own choice about a profile: an opt-out of a Default profile or an opt-in to an Opt-in profile.

    Attributes:
        profile_id: The profile.
        project_id: The choosing project.
        opted_in: `True` to apply an Opt-in profile, `False` to leave a Default profile.
    """

    __tablename__ = "governance_profile_choices"
    __table_args__ = (UniqueConstraint("profile_id", "project_id", name="uq_governance_profile_choices"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    opted_in: Mapped[bool] = mapped_column(Boolean)


class GovernanceLifecycleRequirement(UUIDPKMixin, TimestampMixin, Base):
    """A lifecycle state a profile requires every project it applies to to keep on.

    Attributes:
        profile_id: The profile.
        artefact_type: The registered record type.
        state: The required state key (an optional state of the type).
    """

    __tablename__ = "governance_lifecycle_requirements"
    __table_args__ = (UniqueConstraint("profile_id", "artefact_type", "state", name="uq_governance_lifecycle_requirements"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(64))


class GovernanceLifecycleSkipPolicy(UUIDPKMixin, TimestampMixin, Base):
    """Whether a profile forbids skipping steps of a record's lifecycle in the projects it applies to.

    Attributes:
        profile_id: The profile (one row at most).
        forbidden: Whether skipping is forbidden.
    """

    __tablename__ = "governance_lifecycle_skip_policies"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_governance_lifecycle_skip_policies"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    forbidden: Mapped[bool] = mapped_column(Boolean, default=False)
