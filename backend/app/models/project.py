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

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum, utcnow
from app.models.enums import (
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    StageReviewResponseChoice,
    StageStatus,
)


class Project(UUIDPKMixin, TimestampMixin, Base):
    """An engineering project that requirements and change requests belong to.

    Attributes:
        next_requirement_seq: Monotonically increasing counter used to
            generate unique requirement identifiers (C-G-06). Never reused,
            including for archived requirements.
        status_id: The project's current org-defined status (e.g.
            "Proposed", "Active" — see `ProjectStatusDefinition`). NOT NULL
            with no `ondelete` action (implicit RESTRICT): every project
            must always have a real status, and the app layer already
            refuses to delete an in-use status (409) or delete the last
            remaining status in an org (409) — see
            `ProjectStatusDefinition`'s own docstring for why the DB-level
            RESTRICT is kept as a second backstop rather than relied on
            alone.
        next_action_seq: Monotonically increasing counter used to generate
            unique `RequirementAction.unique_code` identifiers, mirroring
            `next_requirement_seq` exactly (see `services/actions.py`).
        parent_project_id: Optional parent in an unlimited-depth project
            tree. `ondelete="SET NULL"`: there is no single-project
            hard-delete endpoint today (only archive/unarchive), so the
            only way a project row disappears is `Organization` CASCADE,
            which takes its whole tree in one transaction anyway — SET NULL
            is the safe default if a hard delete is ever added later.
            Neither cycle prevention nor same-organisation enforcement has
            a DB-level constraint (Postgres can't express a transitive-
            closure CHECK, and a cross-row same-org check would need a
            trigger); both are application-level only, in
            `services.project_hierarchy`, mirroring the equivalent
            `OrgGroupMember.member_org_group_id` precedent.
        role_inheritance_mode / role_inheritance_filter_role: Forward
            (parent -> child) RBAC cascade, resolved in `services.rbac`;
            see `ProjectRoleInheritanceMode`. `role_inheritance_filter_role`
            must be `None` unless `role_inheritance_mode` is `MIRROR_ROLE`,
            in which case it must be one of `STAKEHOLDER`,
            `PROJECT_ADMINISTRATOR`, or `PROJECT_MANAGER` (not `MEMBER` —
            already covered, more broadly, by `MEMBER_ONLY`) — enforced at
            the schema/router layer, not a DB constraint. Authorized
            entirely by this project's own manager, since it's this
            project's access boundary that expands; see `ProjectMemberSource`
            for the reverse (child -> parent) mechanism, which is
            authorized the other way around on purpose.
        parent_required: Set automatically by the server at project-creation
            time — never client-settable. `True` only when the project was
            created via the relaxed "actor manages the intended parent, no
            org-level ORG_ADMIN/PROJECT_CREATOR role" authorization path
            (`routers.projects.create_project`); `False` for every project
            created via the existing org-level path, with or without a
            parent. The sole behavioural effect: clearing
            `parent_project_id` to `None` is rejected unless this is
            `False` or the current actor holds `ORG_ADMIN`/`PROJECT_CREATOR`
            in the project's organisation — closing off "create a child
            under the relaxed permission, then detach it into an
            unrestricted root project you were never allowed to create
            standalone" without restricting anything else about the
            project. See `docs/decisions.md`.
        can_be_parent: Whether this project may be selected as a parent —
            gates `parent_project_id` on *other* projects' create/update, not
            this project's own. Defaults to `False`: a project is not
            eligible to be a parent until its own manager deliberately opts
            in, so the "Parent project" picker isn't cluttered with every
            project in the org and a project's manager makes an explicit
            choice before taking on the responsibility. Enforced server-side
            (`routers.projects.create_project`/`update_project` 400 if the
            target parent has this `False`), not just a UI-side filter — see
            docs/decisions.md. Turning this back `False` on a project that
            already has children does not retroactively detach them, the
            same "changes apply going forward, not retroactively" principle
            `role_inheritance_mode` already follows; it only blocks *new*
            children from attaching.
    """

    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(2000), default="")
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
    # Whether this project can be used as a template for new projects (C-E-05).
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether every org member automatically gets baseline view access
    # (ProjectVisibility.ORG_WIDE) or only explicitly-assigned users/groups
    # (ONLY_SPECIFIED, the default — see services.rbac.get_effective_project_roles
    # for where the ORG_WIDE grant is actually applied).
    visibility: Mapped[ProjectVisibility] = mapped_column(str_enum(ProjectVisibility, 20), default=ProjectVisibility.ONLY_SPECIFIED)
    # Per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}.
    # Keys are restricted to a fixed, documented set (see schemas/project.py);
    # this is not a freeform key-value store.
    terminology: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Persisted report structure (mock's "Report Setup": Project Intro / Body
    # Chapters / Appendices), used as the default when a report is generated
    # without ad-hoc pre_markdown/post_markdown overrides (see
    # services/reports.py). Chapters/appendices are each an ordered list of
    # {"title": str, "body": str} objects.
    report_intro: Mapped[str] = mapped_column(Text, default="")
    report_chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    report_appendices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Pre-selected (not enforced) on the report generation page — a user can
    # still pick a different template, or none, for a specific generation.
    # ON DELETE SET NULL: deleting the referenced template must not break
    # the project row, just fall back to no default.
    default_report_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("report_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Massif (v3): default notification lead time (in days) before a
    # requirement's review_date, used when a requirement doesn't set its own
    # review_lead_days override (C-R-08).
    review_reminder_lead_days_default: Mapped[int] = mapped_column(Integer, default=7)


class ProjectStage(UUIDPKMixin, TimestampMixin, Base):
    """One lifecycle horizon of a project (C-G-08, C-G-10).

    Attributes:
        status: scoping -> review -> approved -> completed.
        sort_order: Display/sequence order among a project's stages.
        approved_at / approved_by: Set when the stage transitions to
            approved; this is also when a baseline snapshot is written
            (C-G-10) and requirement edits become change-request-only
            (C-G-12).
    """

    __tablename__ = "project_stages"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[StageStatus] = mapped_column(str_enum(StageStatus, 20), default=StageStatus.SCOPING)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Massif (v3): completion tracking (C-P-02) and review-deadline "assumed
    # approval" (C-R-05). completed_at/completed_by mirror the existing
    # approved_at/approved_by pattern. review_deadline is set by a project
    # manager while the stage is in REVIEW; the daily scheduler sweep
    # (services/stages.py) auto-approves the stage once it passes, unless a
    # stakeholder explicitly rejected via StageReviewResponse.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageReviewResponse(UUIDPKMixin, Base):
    """A stakeholder's response to a project stage's review deadline (C-R-05).

    One row per (stage, user) per review cycle; rows are cleared whenever a
    new `review_deadline` is set on the stage, so a later review cycle isn't
    contaminated by an earlier cycle's responses.
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
    """A named group that grants one of the four fixed project roles (C-U-11).

    Ossa (v1) uses a fixed role vocabulary (ProjectRole) rather than
    customisable permissions, so a group's purpose is simply to bulk-assign
    one of those roles to many users (and, via nested org groups, whole
    organisational teams, C-U-12).

    Every group is now an ordinary, user-created group (follow-up UX batch
    Phase C, 2026-08-31) — there is no longer a notion of a project
    automatically seeding "standard" groups on creation. Prior to this
    phase, `create_project`'s non-template path auto-created four groups
    per project (`is_default=True`) and the creator's initial
    `PROJECT_MANAGER` grant went through membership in one of them; that
    made bulk-group scaffolding, not a direct grant, the *only* way a fresh
    project ever got its first manager, and those four groups could never
    be deleted. The creator's initial manager role is now always a direct
    `UserProjectRole` grant instead (the same fallback the template-clone
    path already used when a cloned project ended up with no manager) — see
    `routers.projects.create_project` and docs/decisions.md's entry on this
    migration. `is_default` (and every group-count/deletability special
    case built on it) was removed entirely as part of the same change; a
    data migration (`alembic/versions/0019_...py`) converted every
    pre-existing `is_default=True` group's direct user members into direct
    grants and either deleted the group (if it had no other composition) or
    demoted it to an ordinary group (if it did — e.g. a nested org group or
    a cross-project member reference), so no group anywhere in the schema
    still carries any special protection based on how it was created.
    """

    __tablename__ = "project_groups"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))


class ProjectGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """A member of a project group: a user, a nested org group, or a
    reference to another project's own membership roster.

    Exactly one of user_id / org_group_id / source_project_id must be set.

    `source_project_id` ("members of project X") is resolved as that
    project's *direct* members only — one hop, deliberately non-recursive
    (never a source project's own forward-inherited, member-source-derived,
    or project-referenced members) — see `services.rbac.
    _direct_project_member_ids_base`'s docstring for why: two projects
    referencing each other's rosters must never be able to cause unbounded
    recursion, and this is the structural guarantee that prevents it, not
    just an optimisation. Same-organisation only (enforced at write time in
    `routers.projects.add_project_group_member`, and re-checked live at
    read time, mirroring `org_group_id`'s existing cross-tenant defense in
    depth). Authorized purely by `require_project_manage` on this group's
    *own* project — no consent required from the source project, matching
    `ProjectMemberSource`'s own documented rationale (source 6 is
    authorized entirely by the receiving side, not the source's). See
    docs/decisions.md for the security review performed when this was added.
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


class ProjectMemberSource(UUIDPKMixin, TimestampMixin, Base):
    """One entry in a project's own "consume members from this other
    project" list — the reverse (source -> receiving project) RBAC
    mechanism, deliberately shaped as an explicit list owned and authorized
    by the receiving project, not a flag on the source.

    An earlier draft of this mechanism was a boolean on the child
    (`share_members_with_parent`), gated by the child's own manage rights —
    that shape let a low-privileged actor who merely managed some child
    (with zero access to the parent) grant that child's entire membership
    read access into a potentially confidential parent, entirely without
    the parent's knowledge or consent. This table closes that off
    structurally: a source project has no code path that can add itself
    here — only someone who already holds `require_project_manage` on
    `project_id` (the receiving side) can create or delete a row, mirroring
    how `Project.visibility` is already the project's own unilateral
    choice. See `docs/decisions.md`.

    Originally restricted to `source_project_id` being a direct child of
    `project_id` (strict parent/child only) and always granting bare
    `MEMBER`. Generalized (see `docs/decisions.md`'s entry on this) to any
    project in the same organisation, with `mirror_mode`/
    `mirror_filter_role` controlling what gets mirrored — same shape and
    same validation as `Project.role_inheritance_mode`/
    `role_inheritance_filter_role`'s forward mechanism, just applied in the
    reverse direction. The authorization direction is unchanged by the
    generalization: still the receiving project's own manage rights only,
    never the source's — a source project's manager is never consulted or
    notified, matching the original parent/child design's rationale exactly
    (an actor who already manages "many settings, one direction" doesn't
    need the other side's permission to reference its public-within-the-
    org roster, the same way they wouldn't need permission to invite a
    known user by email).

    A row's existence alone is not sufficient to grant anything: resolution
    (`services.rbac`) additionally re-validates, live at read time, that
    `source_project.organization_id == project.organization_id` (same
    organisation only) and that `source_project_id != project_id` — so a
    row that becomes stale (e.g. the source project moved to a different
    organisation via some future cross-org transfer feature — not possible
    today, but the check costs nothing) is automatically inert without
    needing cleanup, the same deliberate-simplification rationale the
    original parent/child revalidation had.

    Both FKs `ondelete="CASCADE"`: this is pure join-table configuration
    with no independent meaning once either side is gone.

    Attributes:
        mirror_mode: What to mirror from `source_project_id`'s own direct
            roles — `MEMBER_ONLY` (default, preserves the original
            behavior exactly for any row created before this field
            existed), `MIRROR_ALL`, or `MIRROR_ROLE` (paired with
            `mirror_filter_role`). Resolved per-hop by
            `services.rbac._member_source_derived_roles`, reading only the
            source's *direct* roles (never its own inherited or
            member-sourced roles) — preserves the existing decoupling
            property between this mechanism and forward inheritance.
        mirror_filter_role: Required iff `mirror_mode == MIRROR_ROLE`,
            forbidden otherwise — same validation as `Project.
            role_inheritance_filter_role` (`STAKEHOLDER`/
            `PROJECT_ADMINISTRATOR`/`PROJECT_MANAGER` only, never `MEMBER`,
            already covered more broadly by `MEMBER_ONLY`).
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
