"""
Module: modules.traceability.models

Tables of the Traceability & Governance module: governance profiles (organisation-owned named policy sets), the projects
a profile targets, the projects exempt from an Enforced profile, each project's opt-in or opt-out and the lifecycle policy
rows a profile owns (the states it requires and whether it forbids skipping steps), the approval policy rows a
profile or a project owns (the roles that may also approve a record type) and the review policy rows a profile or a
project owns (the review interval, reminder lead and default owner of a record type) and the baseline policy rows a
profile or a project owns (which checks run before a baseline, and which fields a record must have filled).

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
- An approval policy is one row per `(owner, record type)` with child rows for its roles. The owner is a profile or a
  project (a check constraint admits exactly one), so the organisation tier and a project's own choice share a table and
  a type's resolution reads one shape. A project's row with no roles is a choice: it stops the nearest ancestor's roles
  applying. A role that is a custom role also carries a foreign key, so deleting the custom role removes it from every
  policy with no code in the custom-role module.
- A review policy is one row per `(owner, record type)` with the same owner rule as an approval policy. Its three settings
  are each optional; a row with none set is a choice that stops the nearest ancestor's row applying. The default owner is a
  principal (`models.principal`), declared as a `PrincipalReference` so deleting the group clears it.
- A baseline policy is one row per owner (a profile or a project) with child rows for its enabled checks and its required
  fields, because a baseline is a whole-project act and not one per record type. The two `applies_to` flags choose whether
  the owner's checks run before a stage baseline, a manual baseline or both; they stay with the owner's checks, so a profile
  that asks for a stage check never makes a project's manual check run before stage baselines. A project's row with no
  checks is a choice that stops the nearest ancestor's applying.
- A traceability rule is one row per rule, owned by a profile or a project (a check constraint admits exactly one), with its
  scope and requirement trees as validated JSON documents (`rule_tree`) because a tree has no fixed shape to normalise. Types
  and link types are named by key and id inside the document; a record type, a sub-type name, a link type id are not foreign
  keys, so a rename or removal is found when the rule is read and reported as a problem, never as a failed query.
- A stage workflow policy is one row per profile (a profile requires at most one workflow) naming an organisation workflow
  and a mode; a project does not own one, because it already chooses its own workflows.
- Governance health keeps three small tables: the organisation's default mode (`governance_health_defaults`), a project's
  own mode, interval and check runner (`governance_health_settings`, a null mode or interval meaning "follow the
  organisation") and the project's latest snapshot (`governance_health_snapshots`, one row, derived data). A snapshot holds
  counts only, never a record's code or content, so one row can serve every viewer once their own rights are applied. The
  check runner and the person who ran the stored check results are users whose deletion clears the reference.
- Choices do not fall back to an ancestor project: reach down the project tree is the organisation's decision
  (`include_children` on a target), and a manager of a parent project must not decide for children they may not manage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column

PROFILE_NAME_MAX_LENGTH = 200
PROFILE_DESCRIPTION_MAX_LENGTH = 500
EXEMPTION_REASON_MAX_LENGTH = 500
RULE_NAME_MAX_LENGTH = 200
RULE_DESCRIPTION_MAX_LENGTH = 500


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


class GovernanceApprovalPolicy(UUIDPKMixin, TimestampMixin, Base):
    """The roles that may also approve one record type, set by a profile or by a project.

    Attributes:
        profile_id: The owning profile, or `None` for a project's own policy.
        project_id: The owning project, or `None` for a profile's policy.
        artefact_type: The registered record type (one with an approval gate).
    """

    __tablename__ = "governance_approval_policies"
    __table_args__ = (
        CheckConstraint("(profile_id IS NULL) <> (project_id IS NULL)", name="ck_governance_approval_policies_one_owner"),
        UniqueConstraint("profile_id", "artefact_type", name="uq_governance_approval_policies_profile"),
        UniqueConstraint("project_id", "artefact_type", name="uq_governance_approval_policies_project"),
    )

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))


class GovernanceApprovalPolicyRole(UUIDPKMixin, TimestampMixin, Base):
    """One role an approval policy names.

    Attributes:
        policy_id: The policy.
        role_kind: `project`, `module` or `custom` (`modules.seams.ApproverRole.kind`).
        role_key: The role within its kind: a project role value, `<module key>:<role key>`, or the custom role's id.
        custom_role_id: Set for a `custom` role: a foreign key that removes the row with the custom role.
    """

    __tablename__ = "governance_approval_policy_roles"
    __table_args__ = (UniqueConstraint("policy_id", "role_kind", "role_key", name="uq_governance_approval_policy_roles"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_approval_policies.id", ondelete="CASCADE"), index=True
    )
    role_kind: Mapped[str] = mapped_column(String(16))
    role_key: Mapped[str] = mapped_column(String(200))
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_role_definitions.id", ondelete="CASCADE"), index=True, nullable=True
    )


class GovernanceReviewPolicy(UUIDPKMixin, TimestampMixin, Base):
    """How often one record type is reviewed and who is reminded, set by a profile or by a project.

    Attributes:
        profile_id: The owning profile, or `None` for a project's own policy.
        project_id: The owning project, or `None` for a profile's policy.
        artefact_type: The registered record type (one with a review adapter).
        interval_days: The longest gap between reviews in days, or `None` for no interval.
        lead_days: Days before the due date that the reminder is sent, or `None` to keep the project's default.
        default_owner_type, default_owner_id: Who is reminded when a record has no reviewer (`models.principal`), both
            `None` for the project managers.
    """

    __tablename__ = "governance_review_policies"
    __table_args__ = (
        CheckConstraint("(profile_id IS NULL) <> (project_id IS NULL)", name="ck_governance_review_policies_one_owner"),
        CheckConstraint("interval_days IS NULL OR interval_days BETWEEN 1 AND 3650", name="ck_governance_review_policies_interval"),
        CheckConstraint("lead_days IS NULL OR lead_days BETWEEN 0 AND 365", name="ck_governance_review_policies_lead"),
        principal_check_constraint("default_owner", nullable=True),
        UniqueConstraint("profile_id", "artefact_type", name="uq_governance_review_policies_profile"),
        UniqueConstraint("project_id", "artefact_type", name="uq_governance_review_policies_project"),
    )

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    default_owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)


class GovernanceStageWorkflowPolicy(UUIDPKMixin, TimestampMixin, Base):
    """The organisation stage workflow a profile requires of the projects it applies to.

    Attributes:
        profile_id: The profile (one row at most).
        workflow_id: The organisation workflow; deleting it is refused while a profile requires it, and the row goes with
            it as a safety net.
        mode: `default` (new stages start in it, other workflows stay usable) or `restrict` (the project may use only the
            workflows its profiles name), validated against `enums.StageWorkflowMode`.
    """

    __tablename__ = "governance_stage_workflow_policies"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_governance_stage_workflow_policies"),
        CheckConstraint("mode IN ('default', 'restrict')", name="ck_governance_stage_workflow_policies_mode"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stage_workflows.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(16))


class GovernanceBaselinePolicy(UUIDPKMixin, TimestampMixin, Base):
    """Which checks run before a project's baselines, set by a profile or by a project.

    Attributes:
        profile_id: The owning profile, or `None` for a project's own policy.
        project_id: The owning project, or `None` for a profile's policy.
        applies_to_stage: Whether the checks run before a stage baseline (a stage entering a locked phase).
        applies_to_manual: Whether the checks run before a manual baseline.
        approval_checks: An `ApprovalCheckMode` value: which approvals the checks also run before.
        notify_managers: Whether the project's managers are told when the automatic approval of a stage is refused by a check.
    """

    __tablename__ = "governance_baseline_policies"
    __table_args__ = (
        CheckConstraint("(profile_id IS NULL) <> (project_id IS NULL)", name="ck_governance_baseline_policies_one_owner"),
        CheckConstraint(
            "applies_to_stage OR applies_to_manual OR approval_checks <> 'off'", name="ck_governance_baseline_policies_applies",
        ),
        UniqueConstraint("profile_id", name="uq_governance_baseline_policies_profile"),
        UniqueConstraint("project_id", name="uq_governance_baseline_policies_project"),
    )

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    applies_to_stage: Mapped[bool] = mapped_column(Boolean, default=True)
    applies_to_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_checks: Mapped[str] = mapped_column(String(24), default="off")
    notify_managers: Mapped[bool] = mapped_column(Boolean, default=True)


class GovernanceBaselineCheck(UUIDPKMixin, TimestampMixin, Base):
    """One check a baseline policy enables.

    Attributes:
        policy_id: The policy.
        check_key: The namespaced check key (`<module key>:<check key>`, `modules.seams.BaselineCheckProvider`). A key whose
            provider is no longer registered is kept and runs nothing.
    """

    __tablename__ = "governance_baseline_checks"
    __table_args__ = (UniqueConstraint("policy_id", "check_key", name="uq_governance_baseline_checks"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_baseline_policies.id", ondelete="CASCADE"), index=True
    )
    check_key: Mapped[str] = mapped_column(String(200))


class GovernanceBaselineRequiredField(UUIDPKMixin, TimestampMixin, Base):
    """A field a record of one type must have filled for the required-fields check to pass.

    Attributes:
        policy_id: The policy.
        artefact_type: The registered record type.
        field_key: The key of one of the type's list columns (`RecordColumn.key`), including a project's custom fields
            (`cf_<name>`); a key the project's type has no column for is skipped when the check runs.
    """

    __tablename__ = "governance_baseline_required_fields"
    __table_args__ = (
        UniqueConstraint("policy_id", "artefact_type", "field_key", name="uq_governance_baseline_required_fields"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_baseline_policies.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    field_key: Mapped[str] = mapped_column(String(100))


class GovernanceTraceabilityRule(UUIDPKMixin, TimestampMixin, Base):
    """One traceability rule: which links a record of one type is expected to carry, set by a profile or by a project.

    Attributes:
        profile_id: The owning profile, or `None` for a project's own rule.
        project_id: The owning project, or `None` for a profile's rule.
        name: Unique among the owner's rules, ignoring case.
        description: A short summary of what the rule is for.
        source_type: The registered record type the rule applies to.
        source_subtype: A sub-type of that type (`record_subtypes`) the rule is limited to, or `None` for every record.
        level: A `RuleLevel` value.
        enabled: Whether the rule is evaluated; a disabled rule is kept.
        sort_order: Position among the owner's rules (display order).
        applies_when: The scope tree (`rule_tree`), or `None` for every record of the source type.
        requires: The requirement tree (`rule_tree`).
        schema_version: The version of the tree document format (`rule_tree.SCHEMA_VERSION`).
    """

    __tablename__ = "governance_traceability_rules"
    __table_args__ = (
        CheckConstraint("(profile_id IS NULL) <> (project_id IS NULL)", name="ck_governance_traceability_rules_one_owner"),
        CheckConstraint(
            "level IN ('informational', 'warning', 'required')", name="ck_governance_traceability_rules_level",
        ),
        UniqueConstraint("profile_id", "name", name="uq_governance_traceability_rules_profile"),
        UniqueConstraint("project_id", "name", name="uq_governance_traceability_rules_project"),
    )

    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(RULE_NAME_MAX_LENGTH))
    description: Mapped[str] = mapped_column(String(RULE_DESCRIPTION_MAX_LENGTH), default="")
    source_type: Mapped[str] = mapped_column(String(64))
    source_subtype: Mapped[str | None] = mapped_column(String(200), nullable=True)
    level: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    applies_when: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    requires: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class GovernanceHealthDefault(UUIDPKMixin, TimestampMixin, Base):
    """The organisation's default way of keeping governance health, followed by every project that sets none of its own.

    Attributes:
        organization_id: The organisation (one row at most).
        mode: A `HealthMode` value.
        interval_hours: The refresh interval of `snapshot_interval`, one of `HEALTH_INTERVAL_HOURS`.
    """

    __tablename__ = "governance_health_defaults"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_governance_health_defaults_org"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(24))
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)


class GovernanceHealthSettings(UUIDPKMixin, TimestampMixin, Base):
    """A project's own choices about its governance health; an unset value follows the organisation's default.

    Attributes:
        project_id: The project (one row at most).
        mode: A `HealthMode` value, or `None` to follow the organisation's default.
        interval_hours: The interval of `snapshot_interval`, or `None` to follow the organisation's default.
        checks_runner_id: The person whose view the baseline checks of a snapshot are run as, or `None` when only a person who
            presses Refresh now runs them. Cleared when the user is deleted.
    """

    __tablename__ = "governance_health_settings"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_governance_health_settings_project"),
        CheckConstraint("interval_hours IS NULL OR interval_hours >= 1", name="ck_governance_health_settings_interval"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checks_runner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class GovernanceHealthSnapshot(UUIDPKMixin, TimestampMixin, Base):
    """The project's latest stored governance health.

    Attributes:
        project_id: The project (one row at most).
        computed_at: The UTC instant the figures were read; taken before reading, so a change made while it ran leaves the
            snapshot stale.
        payload: The figures (`health.HealthSnapshotData`) as counts only.
        refreshed_by_id: The person who pressed Refresh now, or `None` for a refresh the system made.
        checks_run_by_id: The person the baseline check results were run as, or `None` when none were run or the person was deleted.
        checks_run_at: The UTC instant those results were computed; older than `computed_at` when they were carried forward.
    """

    __tablename__ = "governance_health_snapshots"
    __table_args__ = (UniqueConstraint("project_id", name="uq_governance_health_snapshots_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    refreshed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checks_run_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checks_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
