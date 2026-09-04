"""
Module: models.module_role

Module-contributed RBAC tables for the modular feature system
(compliance-module-plan.md Phase 2): a database mirror of the registry's
declared module roles (`ModuleRoleDefinitionRow`), and the grant table
recording which user holds which module-contributed role, at which scope
(`UserModuleRole`). Sibling to `app.models.server_role` (Phase 0's
server-tier grant table) and `app.models.module` (Phase 1's two-tier
gating tables) — same shape family, one phase later in the same plan.

V1 is direct grants only: `UserModuleRole` carries no group-membership or
project-hierarchy inheritance concept, unlike `UserOrgRole`/`UserProjectRole`
(which resolve through `OrgGroup`/`ProjectGroup`/`parent_project_id` via
`app.services.rbac`'s effective-role resolution). This is a deliberate,
explicitly-flagged scope boundary for this plan, not an oversight — see
`app.services.rbac.require_module_role`'s own docstring for the runtime
composition this restriction implies.
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
    """

    __tablename__ = "user_module_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "module_key", "role_key", "organization_id", "project_id"),
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
