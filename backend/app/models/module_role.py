"""
Module: models.module_role

Module-contributed RBAC tables for the modular feature system: a database mirror of the registry's
declared module roles (`ModuleRoleDefinitionRow`), and the grant tables recording which user
(`UserModuleRole`) or organisation group (`GroupModuleRole`) holds which module-contributed role at which
scope. Siblings of `app.models.server_role` and `app.models.module`.

`UserModuleRole` has no project-hierarchy inheritance, unlike `UserProjectRole` (resolved through
`parent_project_id` by `app.services.rbac`). Group grants are `GroupModuleRole`, mirroring
`app.models.project.OrgGroupProjectRole` (**Decided by: User**); `app.services.rbac._has_module_role_grant`
resolves them for a group's members, transitively through nested org groups.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ModuleRoleDefinitionRow(UUIDPKMixin, TimestampMixin, Base):
    """Database mirror of every module-contributed role the in-process registry declares or has declared
    (`app.modules.registry.ModuleRoleDefinition`), synchronised at every process start by
    `app.modules.registry.sync_module_role_definitions`.

    Rows are never deleted, so a `UserModuleRole` grant's display name and description stay resolvable
    after the declaring module leaves `INSTALLED_MODULES` (see `sync_module_role_definitions`). Which roles
    are currently offered as grantable (live registry membership and org enablement) is decided by
    `app.modules.registry.list_enabled_module_roles`, not by this table.

    Attributes:
        module_key: The declaring module's registry key (`ModuleDefinition.key`); a plain string, not a
            foreign key, because modules are defined in code (see `OrganizationModuleEntitlement.module_key`).
        role_key: The role's stable identifier within its module (`ModuleRoleDefinition.role_key`); a plain
            string with no foreign key from `UserModuleRole.role_key`, because this table is a
            stale-tolerant mirror of the code-defined role and a foreign key against it would contradict that.
        name: Display name, mirrored from the registry.
        description: Description, mirrored from the registry; `Text`, as other free-text description columns.
        scope: `"org"` or `"project"`, mirrored from the registry; selects which "available module roles"
            read endpoint lists the role.
    """

    __tablename__ = "module_role_definitions"
    __table_args__ = (UniqueConstraint("module_key", "role_key"),)

    module_key: Mapped[str] = mapped_column(String(100))
    role_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20))


class UserModuleRole(UUIDPKMixin, TimestampMixin, Base):
    """Grants a user a module-contributed role; direct grants only (no group or hierarchy inheritance, unlike
    `UserOrgRole`/`UserProjectRole`; see the module docstring).

    `organization_id` is always set, using the project's organisation for a project-scoped grant, so an
    organisation's whole roster of module-role grants can be queried by `organization_id` alone
    (`list_org_users`' `module_roles`). `project_id` is set only for a project-scoped grant
    (`ModuleRoleDefinition.scope == "project"`).

    `scope_entity_id` generalises `project_id` for a module-owned entity scope (a `ModuleRoleDefinition.scope`
    other than `"org"`/`"project"`, for example compliance's `"standard"`, one role per
    `ComplianceStandard`): the entity's id for such a grant, `NULL` otherwise. It is a bare `UUID`, not a
    foreign key, because the declaring module owns which table it points into.

    The `UniqueConstraint` is a backstop: Postgres treats `NULL` as distinct, so two org-scoped grants
    (both `project_id IS NULL`) for the same `(user_id, module_key, role_key, organization_id)` do not
    collide. Deduplication is the application-level existing-row check used by the sibling grant endpoints
    (`routers.orgs.assign_org_module_role`, `routers.projects.assign_project_module_role`).

    Attributes:
        user_id: The user being granted the role.
        module_key: The declaring module's registry key; a plain string, not a foreign key (see
            `ModuleRoleDefinitionRow.module_key`).
        role_key: The granted role's key within its module; not a foreign key into
            `ModuleRoleDefinitionRow`, which is a mirror.
        organization_id: The owning organisation; always set.
        project_id: The project of a project-scoped grant; `NULL` for an org-scoped one.
        granted_by: The user who made the grant (an org admin or project manager; see
            `app.services.rbac.require_module_role`), for audit attribution independent of
            `AuditEvent.actor_id`, as `UserServerRole.granted_by`.
        scope_entity_id: Set only for a module-owned entity-scoped grant.
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
    """Grants a module-contributed role to every transitive member of an organisation group; the group-level
    counterpart to `UserModuleRole` (see the module docstring).

    Structurally `UserModuleRole` with `org_group_id` in place of `user_id`: the same
    `module_key`/`role_key`/`organization_id`/`project_id`/`scope_entity_id` columns, the same
    plain-string (no foreign key) rationale for `module_key`/`role_key`, and the same application-level
    deduplication (the `UniqueConstraint` is a backstop because Postgres treats `NULL` as distinct).

    Resolved at read time, never materialised: `app.services.rbac._has_module_role_grant` checks this table
    after finding no direct `UserModuleRole`, expanding `org_group_id` to every group nested inside it
    (`_descendant_org_group_ids`, as `_direct_project_member_ids_base` does for `OrgGroupProjectRole`)
    before checking `OrgGroupMember` for the acting user.

    Attributes:
        org_group_id: The organisation group being granted the role; every transitive member holds it,
            resolved live.
        module_key: The declaring module's registry key (see `UserModuleRole.module_key`).
        role_key: The granted role's key within its module (see `UserModuleRole.role_key`).
        organization_id: The owning organisation; always set.
        project_id: Set only for a project-scoped grant; `NULL` for an org-scoped or entity-scoped one.
        granted_by: The user who made the grant, for audit attribution independent of
            `AuditEvent.actor_id`.
        scope_entity_id: Set only for a module-owned entity-scoped grant (see
            `UserModuleRole.scope_entity_id`).
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
