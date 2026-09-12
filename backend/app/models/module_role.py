"""
Module: models.module_role

Module-contributed RBAC tables for the modular feature system
(compliance-module-plan.md Phase 2): a database mirror of the registry's
declared module roles (`ModuleRoleDefinitionRow`), and the grant table
recording which user holds which module-contributed role, at which scope
(`UserModuleRole`). Sibling to `app.models.server_role` (Phase 0's
server-tier grant table) and `app.models.module` (Phase 1's two-tier
gating tables) — same shape family, one phase later in the same plan.

`UserModuleRole` is direct-grant-only: no project-hierarchy inheritance
concept, unlike `UserProjectRole` (which resolves through
`parent_project_id` via `app.services.rbac`'s effective-role resolution).
Originally this also excluded group-membership grants entirely (module
system Phase 2's own V1 scope boundary) — **reversed by Phase 30, Decided
by: User**: the human-review round that shipped Phase 22's Standards
Manager/Contributor picker found the exclusion undesirable, not merely
unbuilt, and asked for the real mechanism. `GroupModuleRole` (below) is
that mechanism, mirroring `app.models.project.OrgGroupProjectRole`'s own
already-shipped precedent for core `ProjectRole` group grants — see that
model's docstring, and `app.services.rbac._has_module_role_grant`'s own
group-grant branch for how a `GroupModuleRole` row resolves into an
effective grant for a group's members (transitively, via nested org
groups).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ModuleRoleDefinitionRow(UUIDPKMixin, TimestampMixin, Base):
    """Database mirror of every module-contributed role currently or
    formerly declared by the in-process registry
    (`app.modules.registry.ModuleRoleDefinition`), kept in sync by
    `app.modules.registry.sync_module_role_definitions` at every process
    startup.

    This table exists so a `UserModuleRole` grant's display name and
    description stay resolvable even if the module that declared the role
    is later removed from `INSTALLED_MODULES` (a deployment downgrade, an
    uninstalled third-party module, ...) — see `sync_module_role_
    definitions`'s own docstring for the full "append-only, never deleted"
    rationale. Deciding which roles are currently *offered* as grantable
    (live registry membership AND current org enablement) is a separate
    concern, handled by `app.modules.registry.list_enabled_module_roles`,
    not by this table's own contents.

    Attributes:
        module_key: The declaring module's registry key
            (`ModuleDefinition.key`) — deliberately a plain string, not a
            foreign key into a modules table, for the same reason
            `OrganizationModuleEntitlement.module_key`'s own docstring
            already gives: modules are defined in code (the registry), not
            as database rows.
        role_key: The role's own stable identifier within its module
            (`ModuleRoleDefinition.role_key`) — likewise deliberately a
            plain string, not a foreign key from `UserModuleRole.role_key`
            back to this table: the role is defined in code (the module's
            own `ModuleDefinition.roles`), and this table is only ever a
            best-effort *mirror* of that, kept intentionally stale-tolerant
            (rows are never deleted) rather than authoritative — an FK
            enforcing referential integrity against a table that is
            deliberately allowed to drift from the live registry would be
            self-contradictory.
        name: Human-readable display name, mirrored from the registry.
        description: Human-readable description, mirrored from the
            registry. `Text`, not a bounded `String`, matching this
            codebase's existing convention for free-text description
            columns (e.g. `RequirementAction.description`,
            `ChangeRequestTask.description`) rather than picking an
            arbitrary cap.
        scope: `"org"` or `"project"`, mirrored from the registry —
            determines which of the two "available module roles" read
            endpoints lists this role.
    """

    __tablename__ = "module_role_definitions"
    __table_args__ = (UniqueConstraint("module_key", "role_key"),)

    module_key: Mapped[str] = mapped_column(String(100))
    role_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20))


class UserModuleRole(UUIDPKMixin, TimestampMixin, Base):
    """Grants a user a module-contributed role, direct-grant-only (module
    system Phase 2 — see this module's own docstring for why there is
    deliberately no group/hierarchy inheritance here, unlike
    `UserOrgRole`/`UserProjectRole`).

    `organization_id` is always set, even for a project-scoped grant — via
    the project's own organisation — so the whole roster of a given org's
    module-role grants (both org- and project-scoped) can be queried
    directly by `organization_id` alone, the same way `list_org_users`
    needs to for its `module_roles` field, without a join through
    `projects` for the org-scoped rows. `project_id` is set only for a
    project-scoped grant (`ModuleRoleDefinition.scope == "project"`) and
    left `NULL` for an org-scoped one.

    `scope_entity_id` (module system Phase 22) is the generalised sibling
    of `project_id` for a module-owned entity scope (any `ModuleRoleDefinition.
    scope` value other than `"org"`/`"project"` — e.g. compliance's own
    `"standard"` scope, one role per `ComplianceStandard` row): set to that
    entity's own id for such a grant, `NULL` for every `"org"`/`"project"`
    grant. Deliberately a bare `UUID` column, not a foreign key — like
    `module_key`/`role_key`, this table records a grant against a
    code-defined scope whose *meaning* (which table `scope_entity_id`
    points into) is owned entirely by the declaring module, not by this
    core table (see `ModuleRoleDefinition.scope`'s own docstring on why a
    module is free to declare its own scope name at all).

    The `UniqueConstraint` below is a backstop, not the actual dedup
    mechanism — Postgres treats `NULL` as distinct from every other value
    in a unique constraint, so two org-scoped grants (both with
    `project_id IS NULL`) for the same `(user_id, module_key, role_key,
    organization_id)` would not actually collide at the database level.
    The real dedup is the same app-level `existing = db.scalar(select(...));
    if existing is None:` check every sibling grant endpoint in this
    codebase already uses (`assign_org_role`/`assign_project_role`/`grant_
    server_role`) — see `routers.orgs.assign_org_module_role`/`routers.
    projects.assign_project_module_role`.

    Attributes:
        user_id: The user being granted the role.
        module_key: The declaring module's registry key — deliberately a
            plain string, not a foreign key (see `ModuleRoleDefinitionRow.
            module_key`'s docstring for the identical rationale, which
            applies here too: this table records a grant against a
            code-defined role, not a database row).
        role_key: The granted role's own key within its module — likewise
            deliberately not a foreign key into `ModuleRoleDefinitionRow`,
            for the same reason that table's own `role_key` isn't one
            either (a mirror table, not the source of truth).
        organization_id: The owning organisation — always set (see class
            docstring).
        project_id: The project this grant applies to, for a
            project-scoped role only; `NULL` for an org-scoped role.
        granted_by: The user who made the grant (an org admin or project
            manager — see `app.services.rbac.require_module_role`'s
            composition), for audit attribution independent of
            `AuditEvent.actor_id`, mirroring `UserServerRole.granted_by`'s
            identical rationale.
        scope_entity_id: See this class's own docstring above — set only
            for a module-owned entity-scoped grant.
    """

    __tablename__ = "user_module_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "module_key", "role_key", "organization_id", "project_id", "scope_entity_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    role_key: Mapped[str] = mapped_column(String(100))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)


class GroupModuleRole(UUIDPKMixin, TimestampMixin, Base):
    """Grants a module-contributed role to every (transitive) member of an
    organisation group — the group-level counterpart to `UserModuleRole`,
    added by module system Phase 30 to reverse that table's own originally-
    documented "direct grants only" boundary (see this module's own
    docstring for why).

    Structurally `UserModuleRole` with `org_group_id` in place of `user_id`,
    otherwise identical: same `module_key`/`role_key`/`organization_id`/
    `project_id`/`scope_entity_id` columns, the same "plain string, not a
    foreign key" rationale for `module_key`/`role_key` (a grant against a
    code-defined role, not a database row), and the same app-level dedup
    convention (`UniqueConstraint` below is a backstop, not the real
    mechanism, since Postgres treats `NULL` as distinct from every other
    value — see `UserModuleRole`'s own docstring for the identical note).

    Resolved at read time, never materialised: `app.services.rbac.
    _has_module_role_grant` checks this table only after finding no direct
    `UserModuleRole` match, expanding `org_group_id` to include every group
    transitively nested inside it (`_descendant_org_group_ids`, the same
    downward expansion `_direct_project_member_ids_base` already performs
    for `OrgGroupProjectRole`) before checking `OrgGroupMember` for the
    acting user — mirroring that existing core-`ProjectRole` precedent
    exactly, one layer further down for module-contributed roles.

    Attributes:
        org_group_id: The organisation group being granted the role — every
            transitive member (direct `OrgGroupMember.user_id`, or a member
            of a group nested inside this one) is treated as holding the
            role, resolved live.
        module_key: The declaring module's registry key — see
            `UserModuleRole.module_key`'s docstring for the identical
            not-a-foreign-key rationale.
        role_key: The granted role's own key within its module — see
            `UserModuleRole.role_key`'s docstring.
        organization_id: The owning organisation — always set, same
            rationale as `UserModuleRole.organization_id`.
        project_id: Set only for a project-scoped role grant; `NULL` for an
            org-scoped or module-owned-entity-scoped one.
        granted_by: The user who made the grant, for audit attribution
            independent of `AuditEvent.actor_id`.
        scope_entity_id: Set only for a module-owned entity-scoped grant
            (e.g. compliance's own per-`ComplianceStandard` scope) — see
            `UserModuleRole.scope_entity_id`'s own docstring.
    """

    __tablename__ = "group_module_roles"
    __table_args__ = (
        UniqueConstraint(
            "org_group_id", "module_key", "role_key", "organization_id", "project_id", "scope_entity_id"
        ),
    )

    org_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    role_key: Mapped[str] = mapped_column(String(100))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
