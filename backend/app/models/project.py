"""
Module: models.project

Defines projects and everything scoped to a single project: stages
(lifecycle horizons, C-G-08), components and categories (used as requirement
ID prefixes, C-G-07), project groups (C-U-11) which may nest organisation
groups (C-U-12), and direct per-user project role assignments.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.code_rules import ABSOLUTE_MAX_CODE_LENGTH
from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum, utcnow
from app.models.enums import (
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    StageReviewResponseChoice,
)
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column

#: Longest Project report name: the same as `Project.name`, so the short name is never stricter than the name it stands for
#: (how much fits in a header is the layout's concern, and wraps with the page size).
MAX_REPORT_NAME_LENGTH = 255


class Project(UUIDPKMixin, TimestampMixin, Base):
    """An engineering project that requirements and change requests belong to.

    Attributes:
        report_name: Optional short name reports may print instead of `name` (`{{project_report_name}}`); display only.
        next_requirement_seq: Monotonically increasing counter used to
            generate unique requirement identifiers (C-G-06). Never reused,
            including for archived requirements.
        code: Short upper-case code (letters and digits, no hyphen) that qualifies
            the project's record codes (`ACME-REQ-001`). Unique per organisation,
            shaped by `Organization.project_code_policy`, and distinct from the
            organisation's own code. Own code only: a child project does not
            inherit or concatenate its parent's. See `services.codes`.
        status_id: The project's org-defined status (for example "Proposed", "Active"; see
            `ProjectStatusDefinition`). NOT NULL with implicit RESTRICT: every project has a status, the
            application refuses (409) to delete an in-use status or an organisation's last status, and the
            database RESTRICT is a second backstop.
        next_action_seq: Counter for unique `RequirementAction.unique_code` identifiers, as
            `next_requirement_seq` (see `services/actions.py`).
        parent_project_id: Optional parent in an unlimited-depth project tree. `ondelete="SET NULL"`: no
            single-project hard-delete endpoint exists, and `Organization` CASCADE removes the whole tree in
            one transaction. Cycle prevention and same-organisation enforcement are application-level only
            (`services.project_hierarchy`), since Postgres cannot express a transitive-closure CHECK and a
            cross-row check would need a trigger (as `OrgGroupMember.member_org_group_id`).
        role_inheritance_mode / role_inheritance_filter_role: Forward (parent -> child) RBAC cascade,
            resolved in `services.rbac`; see `ProjectRoleInheritanceMode`. `role_inheritance_filter_role` is
            `None` unless the mode is `MIRROR_ROLE`, when it is `STAKEHOLDER`, `PROJECT_ADMINISTRATOR` or
            `PROJECT_MANAGER` (not `MEMBER`, covered by `MEMBER_ONLY`); the schema/router layer enforces
            this. Authorised by this project's own manager, because this project's access boundary expands;
            `ProjectMemberSource` is the reverse (child -> parent) mechanism, authorised the other way on
            purpose.
        parent_required: Set by the server at creation, never client-settable. `True` only when the project
            was created through the relaxed path (the actor manages the intended parent and holds no
            org-level ORG_ADMIN/PROJECT_CREATOR role; `routers.projects.create_project`). Clearing
            `parent_project_id` to `None` is rejected unless this is `False` or the actor holds
            `ORG_ADMIN`/`PROJECT_CREATOR` in the organisation, so a child created under the relaxed
            permission cannot be detached into a root project the actor could not create (docs/decisions.md).
        can_be_parent: Whether this project may be selected as a parent; it gates `parent_project_id` on
            other projects' create and update. Default `False`: a project's manager opts in deliberately,
            which also keeps the "Parent project" picker short. Enforced server-side
            (`routers.projects.create_project`/`update_project` return 400 when the target parent has it
            `False`; docs/decisions.md). Setting it `False` on a project with children does not detach them
            (changes apply going forward, as `role_inheritance_mode`); it blocks only new children.
    """

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(ABSOLUTE_MAX_CODE_LENGTH))
    summary: Mapped[str] = mapped_column(String(2000), default="")
    #: A short display name for reports only (`{{project_report_name}}`, falling back to `name`); `None` when unset. Not an
    #: identifier (the `code` is) and not inherited by a child project: a name identifies one project.
    report_name: Mapped[str | None] = mapped_column(String(MAX_REPORT_NAME_LENGTH), nullable=True)
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role_inheritance_mode: Mapped[ProjectRoleInheritanceMode] = mapped_column(
        str_enum(ProjectRoleInheritanceMode, 20), default=ProjectRoleInheritanceMode.NONE
    )
    role_inheritance_filter_role: Mapped[ProjectRole | None] = mapped_column(str_enum(ProjectRole), nullable=True)
    parent_required: Mapped[bool] = mapped_column(Boolean, default=False)
    can_be_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    next_requirement_seq: Mapped[int] = mapped_column(Integer, default=1)
    next_action_seq: Mapped[int] = mapped_column(Integer, default=1)
    status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_status_definitions.id"), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Whether project "members" may submit change requests (C-U-13); defaults
    # to enabled per the requirement's clarification.
    allow_member_change_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    # Opt-in: adding or removing a traceability `ArtefactLink` on an approved requirement goes through a
    # change request (`ChangeRequestKind.ADD_LINK`/`REMOVE_LINK`) instead of the direct endpoint; see
    # `services.requirements.requires_change_request_for_links` for the resolution (this field, or an
    # org-wide force, minus the project's exemption). Default `False`: traceability metadata is not C-G-12
    # content, and a permissive default (as `allow_member_change_requests`) breaks no existing project.
    require_change_request_for_approved_links: Mapped[bool] = mapped_column(Boolean, default=False)
    # Exemption from `Organization.force_require_change_request_for_approved_links`: an exempt project uses
    # its own `require_change_request_for_approved_links` while the force applies to every other project.
    # Consulted only when the org force is set. Default `False`, so a new project is subject to an active
    # force until its manager or an org admin opts it out.
    exempt_from_org_link_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether an AI assistant acting through the MCP server may perform an approval-type action in this
    # project (see `Organization.allow_ai_approvals`). It and the organisation's flag must both be true;
    # there is no exemption (unlike the link-lock pair), as this only narrows what is possible. Off by
    # default; a project manager or administrator acknowledges the accountability trade-off in the UI to
    # enable it.
    allow_ai_approvals: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether this project can be used as a template for new projects (C-E-05).
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether every org member gets baseline view access (ProjectVisibility.ORG_WIDE) or only assigned
    # users and groups (ONLY_SPECIFIED, default); see services.rbac.get_effective_project_roles.
    visibility: Mapped[ProjectVisibility] = mapped_column(str_enum(ProjectVisibility, 20), default=ProjectVisibility.ONLY_SPECIFIED)
    # Per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}; keys come from a fixed set
    # (schemas/project.py), not a freeform store.
    terminology: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Massif (v3): default notification lead time (in days) before a
    # requirement's review_date, used when a requirement doesn't set its own
    # review_lead_days override (C-R-08).
    review_reminder_lead_days_default: Mapped[int] = mapped_column(Integer, default=7)

    # How tags are applied in this project: "free" (anyone who may tag a record can coin a tag) or
    # "restricted" (only tags a project administrator listed). NULL inherits the nearest ancestor's
    # setting, else "free" (services.tags.resolve_tag_mode).
    tag_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)

    # Whether a requirement may be placed in further components (new aliases): "allowed" or "disabled". NULL
    # inherits the nearest ancestor's setting, else the organisation's (services.requirement_aliases.resolve_mode).
    requirement_aliases: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Whether each component follows its own workflow per stage: "on" or "off". NULL inherits the
    # nearest ancestor's setting, else "off" (services.component_stages.resolve_mode); off leaves the
    # project stage as the only phase.
    component_phases_mode: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Days before a phase's expected start that its "upcoming" reminder is sent; NULL inherits the nearest
    # ancestor's, else `services.stage_phase_plans.DEFAULT_LEAD_DAYS`.
    phase_reminder_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # This project's own navigation names, keyed by stable navigation key (`services.nav_labels`); a key
    # with no entry follows the nearest ancestor's name, then the organisation's, then the built-in one.
    nav_label_overrides: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # This project's own overview layout (`services.overview_widgets`): an object `{scope, widgets}`, the widgets an
    # ordered list of instances. SQL NULL (not JSON null) means none: the nearest ancestor's, then the
    # organisation's, then the built-in layout applies. An empty widget list is a layout with every widget removed.
    overview_widgets: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)


class ProjectStage(UUIDPKMixin, TimestampMixin, Base):
    """One lifecycle horizon of a project (C-G-08, C-G-10).

    Attributes:
        workflow_id / phase_id: The workflow the stage follows and its current phase; the
            phase's kind (not its name) drives the baseline, edit lock and completion.
        sort_order: Display/sequence order among a project's stages.
        approved_at / approved_by: Set when the stage transitions to
            approved; this is also when a baseline snapshot is written
            (C-G-10) and requirement edits become change-request-only
            (C-G-12).
    """

    __tablename__ = "project_stages"
    __table_args__ = (UniqueConstraint("project_id", "name"), principal_check_constraint("owner", nullable=True))

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflows.id"), index=True)
    phase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflow_phases.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional principal (a user or a group) reminded about the stage's phase schedule; with none, the project managers.
    owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Completion tracking (C-P-02) and review-deadline "assumed approval" (C-R-05). completed_at/
    # completed_by mirror approved_at/approved_by. A project manager sets review_deadline while the stage is
    # in REVIEW; the daily scheduler sweep (services/stages.py) approves the stage once it passes, unless a
    # stakeholder rejected it through StageReviewResponse.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageReviewResponse(UUIDPKMixin, Base):
    """A stakeholder's response to a project stage's review deadline (C-R-05).

    One row per (stage, user) in each deadline cycle; rows are cleared when a new `review_deadline` is set,
    so a cycle never carries an earlier cycle's responses.
    """

    __tablename__ = "stage_review_responses"
    __table_args__ = (UniqueConstraint("stage_id", "user_id"),)

    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    response: Mapped[StageReviewResponseChoice] = mapped_column(str_enum(StageReviewResponseChoice, 20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectComponent(UUIDPKMixin, TimestampMixin, Base):
    """A project component with a settable identifier prefix (C-G-07)."""

    __tablename__ = "project_components"
    __table_args__ = (UniqueConstraint("project_id", "prefix"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProjectCategory(UUIDPKMixin, TimestampMixin, Base):
    """A requirement category with a settable identifier prefix (C-G-07),
    nested under exactly one component — components and categories form a
    two-level tree (a component has many categories; a category belongs to
    one component), not two independent flat lists. `sort_order` is scoped
    per-component (siblings under the same parent), not per-project, to
    match: reordering categories under one component never touches another
    component's own category ordering.
    """

    __tablename__ = "project_categories"
    __table_args__ = (UniqueConstraint("component_id", "prefix"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProjectGroup(UUIDPKMixin, TimestampMixin, Base):
    """A named group that may hold zero, one, or several of the four fixed
    project roles (C-U-11), each an independent, revocable grant.

    Ossa (v1) uses a fixed role vocabulary (ProjectRole) rather than
    customisable permissions, so a group's purpose is simply to bulk-assign
    role(s) to many users (and, via nested org groups, whole organisational
    teams, C-U-12).

    A group's roles are `ProjectGroupRole` rows, one per role and each independently revocable, the shape
    `OrgGroupProjectRole` and `UserProjectRole` use (not an array or JSON column); a group holds zero, one
    or several roles. `services.rbac` resolves a group's `direct_group` provenance by joining that table,
    and every C-U-08 "must retain a manager" guard checks `ProjectGroupRole` (docs/decisions.md's
    identify/verify/remediate entry for the members/groups directory).

    Every group is an ordinary user-created group: project creation seeds no standard groups, and no group
    has special protection from deletion. The creator's initial manager role is a direct `UserProjectRole`
    grant (`routers.projects.create_project`; docs/decisions.md).
    """

    __tablename__ = "project_groups"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))


class ProjectGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """A member of a project group: a user, a nested org group, or a
    reference to another project's own membership roster.

    Exactly one of user_id / org_group_id / source_project_id must be set.

    `source_project_id` ("members of project X") resolves to that project's direct members only: one hop,
    non-recursive (never its inherited, member-source-derived or project-referenced members;
    `services.rbac._direct_project_member_ids_base`). Two projects referencing each other's rosters would
    otherwise recurse without bound, so this is a structural guarantee, not an optimisation.
    Same-organisation only, enforced at write time in `routers.projects.add_project_group_member` and
    re-checked at read time (defence in depth, as `org_group_id`). Authorised by `require_project_manage`
    on this group's own project, with no consent from the source project, as `ProjectMemberSource` (the
    receiving side authorises); see docs/decisions.md.
    """

    __tablename__ = "project_group_members"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (org_group_id IS NOT NULL)::int + (source_project_id IS NOT NULL)::int = 1",
            name="ck_project_group_member_exactly_one_target",
        ),
    )

    project_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_groups.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"), nullable=True
    )
    source_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )


class UserProjectRole(UUIDPKMixin, TimestampMixin, Base):
    """A direct (non-group) project role assignment for a single user."""

    __tablename__ = "user_project_roles"
    __table_args__ = (UniqueConstraint("user_id", "project_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))


class OrgGroupProjectRole(UUIDPKMixin, TimestampMixin, Base):
    """A direct (non-nested) project role assignment for an organisation group: the group-level counterpart
    to `UserProjectRole`, held by the group itself as an independently revocable record instead of by nesting
    it in a `ProjectGroup` (`ProjectGroupMember.org_group_id`, C-U-12).

    It is additive to nesting, which remains the way to bundle several groups or users under one named role.
    See docs/decisions.md's identify/verify/remediate entry for this table and `services.rbac`'s module
    docstring for how it resolves into effective project roles, including forward and member-source
    inheritance cascading it as a user's own direct role is.

    Both FKs are `ondelete="CASCADE"`: deleting an org group removes every grant that references it (as
    `ProjectGroupMember.org_group_id`), and deleting a project removes its grants (as
    `UserProjectRole.project_id`).
    """

    __tablename__ = "org_group_project_roles"
    __table_args__ = (UniqueConstraint("org_group_id", "project_id", "role"),)

    # `index=True` on both FKs matches the indexes migration 0021 creates, so `Base.metadata` and
    # Alembic's autogenerate diff agree (`test_schema_migrations_match_models.py`).
    org_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))


class ProjectGroupRole(UUIDPKMixin, TimestampMixin, Base):
    """One role a `ProjectGroup` holds: the project-group counterpart to `UserProjectRole` and
    `OrgGroupProjectRole`. A group holds zero, one or several independently revocable roles, one row per
    role, not an array column. It mirrors `OrgGroupProjectRole`, scoped to a `ProjectGroup`; no
    `project_id` is needed because a `ProjectGroup` belongs to exactly one project
    (`ProjectGroup.project_id`).

    `ondelete="CASCADE"`: a role grant has no meaning once its group is deleted (as
    `ProjectGroupMember.project_group_id`). See docs/decisions.md's identify/verify/remediate entry for this
    table, including every C-U-08 "must retain a manager" guard that checks it.
    """

    __tablename__ = "project_group_roles"
    __table_args__ = (UniqueConstraint("project_group_id", "role"),)

    project_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_groups.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))


class ProjectMemberSource(UUIDPKMixin, TimestampMixin, Base):
    """One entry in a project's "consume members from this other project" list: the reverse (source ->
    receiving project) RBAC mechanism, an explicit list owned and authorised by the receiving project, not
    a flag on the source.

    A boolean on the child gated by the child's own manage rights would let someone who merely manages a
    child (with no access to the parent) grant that child's members read access into a confidential parent
    without its consent. Here a source project has no code path to add itself: only someone holding
    `require_project_manage` on `project_id` (the receiving side) can create or delete a row, as
    `Project.visibility` is the project's own unilateral choice (docs/decisions.md).

    `source_project_id` may be any project in the same organisation, with `mirror_mode`/`mirror_filter_role`
    selecting what is mirrored (the same shape and validation as `Project.role_inheritance_mode`/
    `role_inheritance_filter_role`, in the reverse direction). Authorisation is the receiving project's
    manage rights only; the source's manager is not consulted or notified (docs/decisions.md).

    A row alone grants nothing: `services.rbac` re-validates at read time that
    `source_project.organization_id == project.organization_id` and `source_project_id != project_id`, so a
    stale row is inert without cleanup.

    Both FKs are `ondelete="CASCADE"`: the table is join configuration with no meaning once either side is gone.

    Attributes:
        mirror_mode: What to mirror from `source_project_id`'s direct roles: `MEMBER_ONLY` (default),
            `MIRROR_ALL`, or `MIRROR_ROLE` (with `mirror_filter_role`). Resolved per hop by
            `services.rbac._member_source_derived_roles` from the source's direct roles only (never its
            inherited or member-sourced roles), which keeps this mechanism decoupled from forward inheritance.
        mirror_filter_role: Required iff `mirror_mode == MIRROR_ROLE`, forbidden otherwise; the same
            validation as `Project.role_inheritance_filter_role` (`STAKEHOLDER`, `PROJECT_ADMINISTRATOR` or
            `PROJECT_MANAGER`, never `MEMBER`, which `MEMBER_ONLY` covers).
    """

    __tablename__ = "project_member_sources"
    __table_args__ = (UniqueConstraint("project_id", "source_project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    mirror_mode: Mapped[ProjectRoleInheritanceMode] = mapped_column(
        str_enum(ProjectRoleInheritanceMode, 20), default=ProjectRoleInheritanceMode.MEMBER_ONLY
    )
    mirror_filter_role: Mapped[ProjectRole | None] = mapped_column(str_enum(ProjectRole), nullable=True)


class FavoriteProject(UUIDPKMixin, Base):
    """A user's favourited project, shown at the top of their project list (U-U-03)."""

    __tablename__ = "favorite_projects"
    __table_args__ = (UniqueConstraint("user_id", "project_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
