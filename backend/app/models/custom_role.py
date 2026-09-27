"""
Module: models.custom_role

Fine-Grained Access Control (`docs/plans/core-fine-grained-access-control-
plan.md` Phase 1) — an organisation-definable role, composed from atomic
permissions, additive to the fixed `OrgRole`/`ProjectRole` enums and every
module-contributed `ModuleRoleDefinition` (never a replacement for either —
Design Principle 1 in that plan).

`CustomRoleDefinition` is this org's own named role; `CustomRolePermission`
is its permission-atom membership, one row per atom, mirroring this
codebase's established normalised-join-table convention (never a serialized
array/JSON blob for a set that needs per-row operations — see
`app.models.relationship.ArtefactLink`'s own precedent for the identical
choice, applied there to link types). `UserCustomRoleGrant`/
`GroupCustomRoleGrant` grant one such role to a user or an organisation
group, shaped exactly like `app.models.module_role.UserModuleRole`/
`GroupModuleRole` — the same grant-table family, one tier further down (a
custom role instead of a module-contributed one).

Tenant isolation (Design Principle 2): every table here carries its own
`organization_id`, and a `CustomRoleDefinition` is only ever resolvable
within the organisation that defined it — `app.services.rbac.
get_effective_permissions` (Phase 2) must never resolve a grant against a
role from a different organisation, the same constraint every other
cross-project mechanism in this codebase already enforces.

No self-escalation (Design Principle 4): only `ORG_ADMIN` may create, edit,
or delete a `CustomRoleDefinition` — enforced at the router layer (Phase 3),
not by anything in this module, the same "authorization is a router/service
concern, not a model concern" split `app.models.relationship`'s own
docstring already states for tenant-scoping checks.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class CustomRoleDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined role: a name plus a set of permission atoms
    (`CustomRolePermission`), grantable to a user or org group exactly like
    a fixed or module-contributed role.

    Attributes:
        organization_id: The owning organisation — a custom role is never
            referenceable from, or grantable within, another organisation
            (Design Principle 2).
        name: Display name, unique within the organisation.
        description: Human-readable description of what the role is for.
        scope: `"org"`, `"project"` — reuses `app.modules.registry.
            ModuleRoleDefinition.scope`'s own two core-recognised values as-
            is (Phase 0 Q2), determining whether this role is granted with
            `project_id` left `NULL` (`"org"`) or set (`"project"`) on
            `UserCustomRoleGrant`/`GroupCustomRoleGrant` — or any key present
            in `app.modules.registry.get_all_registered_entity_scopes()`
            (Phase 5), a module-owned entity scope (e.g. compliance's
            `"standard"`), determining that this role is granted with
            `scope_entity_id` set instead. Phase 1 originally restricted this
            to just `"org"`/`"project"`, reasoning that "an org-definable
            role has no module of its own to supply the matching
            `resolve_entity_organization_id` hook" — Phase 5 lifted that
            restriction by making the hook centrally, genuinely registrable
            (`EntityScopeDefinition`) rather than only reachable from inside
            `require_module_role`, so any current or future module-owned
            entity scope becomes usable by a custom role automatically, with
            no core-file edit required per module. Validated at the service
            layer (Phase 3/5), the same "authorization is a router/service
            concern" split this module's own docstring notes.
        created_by: The `ORG_ADMIN` (or server admin) who created this role,
            for audit attribution independent of `AuditEvent.actor_id`,
            mirroring `UserServerRole.granted_by`'s identical rationale.
    """

    __tablename__ = "custom_role_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class CustomRolePermission(UUIDPKMixin, TimestampMixin, Base):
    """One permission atom held by a `CustomRoleDefinition` — a row per
    atom, not a serialized set, so individual grants stay independently
    queryable/diffable (see module docstring).

    Attributes:
        custom_role_id: The role this permission atom belongs to.
        permission: The encoded permission-atom string
            (`app.services.permissions.encode_permission`, e.g.
            `"decision:approve_baseline:"` for the sub-type wildcard, or
            `"decision:approve_baseline:Architecture"` for a sub-type-scoped
            grant), or a bare administrative permission key (e.g.
            `"grant_roles"`). Validated against `app.services.permissions.
            get_all_permissions`/`validate_permission_key` at write time
            (Phase 3) — including, for an artefact-type permission with a
            sub-type, against that organisation's *current* rows from the
            owning module's registered provider (`app.modules.registry.
            get_subtypes`), mirroring how `ArtefactLink.source_type` is
            validated against the merged artefact-type registry today. Not
            a foreign key into any vocabulary table — like `ModuleRoleDefinition
            Row.role_key`, this records a grant against a derived, code-
            defined vocabulary, not a database row.
    """

    __tablename__ = "custom_role_permissions"
    __table_args__ = (UniqueConstraint("custom_role_id", "permission"),)

    custom_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_role_definitions.id", ondelete="CASCADE"), index=True
    )
    permission: Mapped[str] = mapped_column(String(200))


class UserCustomRoleGrant(UUIDPKMixin, TimestampMixin, Base):
    """Grants a user a `CustomRoleDefinition`, direct-grant-only — the
    custom-role analogue of `app.models.module_role.UserModuleRole`, same
    shape (Phase 0 Q7).

    Attributes:
        user_id: The user being granted the role.
        custom_role_id: The role being granted.
        organization_id: The owning organisation — always set, even for a
            project-scoped grant, mirroring `UserModuleRole.organization_id`'s
            identical rationale (lets the whole roster of an org's
            custom-role grants be queried by `organization_id` alone).
        project_id: Set only when the granted role's own `scope ==
            "project"`; `NULL` for an `"org"`-scoped grant.
        scope_entity_id: Set only when the granted role's own `scope` is a
            registered module-owned entity scope (Phase 5, e.g.
            `"standard"`); `NULL` otherwise. Deliberately a bare `UUID`
            column with no foreign key — mirrors `app.models.module_role.
            UserModuleRole.scope_entity_id`'s identical rationale: the
            column records a grant against a scope whose meaning (which
            table it points into) is owned by the declaring module, not this
            core table. Validated at grant time (Phase 5): the entity's
            resolved organisation (via `app.modules.registry.
            get_all_registered_entity_scopes()`) must equal this grant's own
            `organization_id` (Design Principle 2, tenant isolation).
        granted_by: The user who made the grant (an `ORG_ADMIN`, or a
            `grant_roles` holder per Phase 0 Q6), for audit attribution
            independent of `AuditEvent.actor_id`.
    """

    __tablename__ = "user_custom_role_grants"
    __table_args__ = (UniqueConstraint("user_id", "custom_role_id", "project_id", "scope_entity_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    custom_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_role_definitions.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class GroupCustomRoleGrant(UUIDPKMixin, TimestampMixin, Base):
    """Grants a `CustomRoleDefinition` to every (transitive) member of an
    organisation group — the group-level counterpart to
    `UserCustomRoleGrant`, structurally `app.models.module_role.
    GroupModuleRole` with `custom_role_id` in place of `(module_key,
    role_key)` (Phase 0 Q7).

    Attributes:
        org_group_id: The organisation group being granted the role — every
            transitive member is treated as holding the role, resolved live
            (see `GroupModuleRole`'s own docstring for the identical
            resolution shape this mirrors, one tier further down).
        custom_role_id: The role being granted.
        organization_id: The owning organisation — always set, same
            rationale as `UserCustomRoleGrant.organization_id`.
        project_id: Set only when the granted role's own `scope ==
            "project"`; `NULL` for an `"org"`-scoped grant.
        scope_entity_id: Set only when the granted role's own `scope` is a
            registered module-owned entity scope (Phase 5); `NULL`
            otherwise. Same rationale and validation as `UserCustomRoleGrant.
            scope_entity_id`.
        granted_by: The user who made the grant, for audit attribution
            independent of `AuditEvent.actor_id`.
    """

    __tablename__ = "group_custom_role_grants"
    __table_args__ = (UniqueConstraint("org_group_id", "custom_role_id", "project_id", "scope_entity_id"),)

    org_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"), index=True
    )
    custom_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_role_definitions.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    scope_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
