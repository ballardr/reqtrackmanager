"""
Module: models.module

Module gating tables for the modular feature system: server-tier entitlement (the licensing lever) and
org-tier enablement (the day-to-day switch an org admin controls among entitled modules). See
`app.modules.registry` for how these combine with the static registry into an effective state, and
`app.models.server_role` for the sibling server-tier RBAC table.

Also holds `ProjectModuleEnablement`, a project-tier override of whole-module enablement one level below
`OrganizationModuleEnablement` (`app.modules.registry.is_module_enabled_for_project` resolves entitlement,
project override, org default, registry default), and `OrganizationModuleSubComponentDefault` /
`ProjectModuleSubComponentEnablement`, finer-grained tiers for one sub-component of an enabled module (for
example Context & Strategy's "Strategy" vs "Pain Point"; see `is_module_subcomponent_enabled` and
`is_org_module_subcomponent_enabled`). A whole-module override cascades to its sub-components because
`is_module_subcomponent_enabled` checks `is_module_enabled_for_project` first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class OrganizationModuleEntitlement(UUIDPKMixin, TimestampMixin, Base):
    """Server-tier override of whether an organisation is entitled to use a module: the licensing lever,
    managed by `ServerRole.SERVER_ADMIN` or `ServerRole.MODULE_ADMINISTRATOR`.

    Explicit-override-only, like `Organization.accent_color_hex` falling back to `ServerSettings`
    (`services/branding.py`): an absent `(organization_id, module_key)` row is meaningful, not incomplete.
    Without a row, entitlement falls back to `ServerSettings.default_module_entitlement_policy`
    (`app.modules.registry.is_module_entitled`), so a self-hosted deployment with the default `OPEN` policy
    needs no rows, while a `CLOSED` posture grants entitlement by inserting rows.

    An org admin cannot influence this table. It gates `OrganizationModuleEnablement`: an unentitled module
    cannot be enabled by the org admin (`app.modules.registry.is_module_enabled`'s AND logic).

    Attributes:
        organization_id: The organisation this override applies to.
        module_key: The module's registry key (`ModuleDefinition.key`); a plain string, not a foreign key,
            because modules are defined in code.
        entitled: Explicitly entitled (`True`) or denied (`False`); both differ from "no row" (server policy).
        updated_by: The administrator who last set this override, for audit attribution independent of
            `AuditEvent.actor_id`, as `UserServerRole.granted_by`.
    """

    __tablename__ = "organization_module_entitlements"
    __table_args__ = (UniqueConstraint("organization_id", "module_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    entitled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ServerModuleDefault(UUIDPKMixin, TimestampMixin, Base):
    """Server-wide default state of one module, consulted by
    `app.modules.registry.is_module_enabled` and `resolve_default_project_enabled`
    for any organisation with no `OrganizationModuleEnablement` row of its own,
    before falling back to `ModuleDefinition.default_enabled`.

    Explicit-override-only, like `OrganizationModuleEntitlement`: no row means
    "use the registry's own default". A fresh install is seeded all-on
    (`services.module_defaults.seed_fresh_install_defaults`); an upgrade seeds
    nothing, so existing deployments keep their current effective states. No
    per-organisation rows are pre-created, so a later change here reaches every
    organisation that never overrode the module.

    Attributes:
        module_key: The module's registry key (a plain string, as elsewhere).
        org_enabled: Whether an organisation with no row of its own has the module
            enabled.
        project_default_enabled: Whether a project of such an organisation gets
            the module on by default, absent its own override.
        updated_by: The administrator who last set this default.
    """

    __tablename__ = "server_module_defaults"
    __table_args__ = (UniqueConstraint("module_key"),)

    module_key: Mapped[str] = mapped_column(String(100))
    org_enabled: Mapped[bool] = mapped_column(Boolean)
    project_default_enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OrganizationModuleEnablement(UUIDPKMixin, TimestampMixin, Base):
    """Org-tier override of whether an org admin has enabled a module for day-to-day use: the switch an
    `OrgRole.ORG_ADMIN` controls among the modules the organisation is entitled to
    (`OrganizationModuleEntitlement`).

    Explicit-override-only: an absent `(organization_id, module_key)` row means "use
    `ModuleDefinition.default_enabled`", not "disabled". A module with `default_enabled=True` (for example
    Compliance) is usable in every entitled organisation with no rows, and any org admin can turn it off.

    Effective enablement is "entitled AND (enabled row if present else registry default)"
    (`app.modules.registry.is_module_enabled`). A stale `enabled=True` row for a module whose entitlement
    was revoked is inert and not cleaned up (see the entitlement-revoking endpoint in `routers/system.py`).

    `default_project_enabled` (**Decided by: User**; docs/decisions.md) is a third, independent tier, used
    only when `enabled` is `True`: whether a project gets the module on or off by default, absent its own
    override. `enabled=False` is an absolute floor that no project can cross (`is_module_enabled_for_project`
    does not read `default_project_enabled` then), while `default_project_enabled` lets an org admin make a
    module available but opt-in per project.

    Attributes:
        organization_id: The organisation this override applies to.
        module_key: The module's registry key (`ModuleDefinition.key`), as
            `OrganizationModuleEntitlement.module_key`.
        enabled: Explicitly enabled (`True`) or disabled (`False`); both differ from "no row" (registry
            default). An absolute floor: `False` means no project of this organisation may use the module.
        default_project_enabled: Whether a project gets the module on or off by default, absent a
            `ProjectModuleEnablement` override (which wins in either direction); consulted only when
            `enabled` is `True`.
        updated_by: The org admin who last set this override, for audit attribution independent of
            `AuditEvent.actor_id`.
    """

    __tablename__ = "organization_modules"
    __table_args__ = (UniqueConstraint("organization_id", "module_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean)
    default_project_enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ProjectModuleEnablement(UUIDPKMixin, TimestampMixin, Base):
    """Project-tier override of whole-module enablement: a project admin's choice, taking precedence over
    `OrganizationModuleEnablement` for this project (`app.modules.registry.is_module_enabled_for_project`).

    Explicit-override-only, like `OrganizationModuleEnablement` and `ProjectModuleSubComponentEnablement`:
    an absent `(project_id, module_key)` row means "use the organisation's `default_project_enabled`, or the
    registry's `default_enabled` if the organisation has no row", not "disabled". Effective enablement still
    requires entitlement and the organisation's `enabled` flag (`app.modules.registry.is_module_enabled`),
    a floor this tier cannot cross: an unentitled or hard-disabled module stays disabled for every project.

    The override is symmetric against the organisation's `default_project_enabled` only (**Decided by:
    User**; docs/decisions.md): a project admin can enable a module the organisation defaults off for new
    projects (for example a specialist module) or disable one it defaults on, always within the
    organisation's `enabled=True` floor, so an organisation can hard-block a module with no project exception.

    Attributes:
        project_id: The project this override applies to.
        module_key: The module's registry key (`ModuleDefinition.key`), as
            `OrganizationModuleEnablement.module_key`.
        enabled: Explicitly enabled (`True`) or disabled (`False`); both differ from "no row" (the
            organisation's state).
        updated_by: The project admin who last set this override, for audit attribution independent of
            `AuditEvent.actor_id`.
    """

    __tablename__ = "project_module_enablements"
    __table_args__ = (UniqueConstraint("project_id", "module_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OrganizationModuleSubComponentDefault(UUIDPKMixin, TimestampMixin, Base):
    """Org-tier default enabled state for one sub-component of a module: the organisation-wide policy a
    project's `ProjectModuleSubComponentEnablement` may override and, for a sub-component of an org-scoped
    artefact with no project tier, the effective value
    (`app.modules.registry.is_org_module_subcomponent_enabled`).

    Explicit-override-only, as `OrganizationModuleEnablement`: an absent `(organization_id, module_key,
    subcomponent_key)` row means "use `ModuleSubComponentDefinition.default_enabled`", not "disabled". Only a
    pair the module declares in `ModuleDefinition.sub_components` is meaningful; a row for an undeclared or
    stale key is never consulted (`app.modules.registry._find_subcomponent_definition` returns `None` and
    both resolution functions treat that as disabled).

    Attributes:
        organization_id: The organisation this default applies to.
        module_key: The declaring module's registry key, as `OrganizationModuleEnablement.module_key`.
        subcomponent_key: The sub-component's key in `ModuleDefinition.sub_components`.
        enabled: Hard floor, as `OrganizationModuleEnablement.enabled`: `False` turns the sub-component off
            for the org-level artefact and every project.
        default_project_enabled: The value copied into a project when it is created
            (`app.modules.registry.snapshot_project_module_state`); changing it leaves existing projects
            alone (**Decided by: User**).
        updated_by: The org admin who last set this default, for audit attribution independent of
            `AuditEvent.actor_id`.
    """

    __tablename__ = "organization_module_subcomponent_defaults"
    __table_args__ = (UniqueConstraint("organization_id", "module_key", "subcomponent_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    subcomponent_key: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean)
    default_project_enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ProjectModuleSubComponentEnablement(UUIDPKMixin, TimestampMixin, Base):
    """Project-tier override of one sub-component's enabled state: a project admin's choice for their project,
    taking precedence over `OrganizationModuleSubComponentDefault`
    (`app.modules.registry.is_module_subcomponent_enabled`'s resolution order). It mirrors the org tier's
    split one level down; `ProjectModuleEnablement` is the whole-module override.

    Explicit-override-only: an absent `(project_id, module_key, subcomponent_key)` row means "use the
    organisation's default (or the registry default)", not "disabled". The whole module must also be
    enabled for the project (`app.modules.registry.is_module_enabled_for_project`), so a project admin
    cannot re-enable a sub-component of a module that is hard-disabled for the organisation or turned off
    by the project's own whole-module override (`is_module_subcomponent_enabled` checks the whole module first).

    It has a plain org default plus a symmetric project override, with no hard-floor tier of its own,
    unlike `OrganizationModuleEnablement`'s `enabled` vs `default_project_enabled` (**Decided by: Agent**;
    open to revision if a need arises): the whole-module hard floor already covers shutting every
    sub-component off, and a per-sub-component floor would be complexity nobody has asked for.

    Attributes:
        project_id: The project this override applies to.
        module_key: The declaring module's registry key, as
            `OrganizationModuleSubComponentDefault.module_key`.
        subcomponent_key: The sub-component's key, as `OrganizationModuleSubComponentDefault.subcomponent_key`.
        enabled: Explicitly enabled (`True`) or disabled (`False`); both differ from "no row" (the
            organisation's default).
        updated_by: The project admin who last set this override, for audit attribution independent of
            `AuditEvent.actor_id`.
    """

    __tablename__ = "project_module_subcomponent_enablements"
    __table_args__ = (UniqueConstraint("project_id", "module_key", "subcomponent_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    subcomponent_key: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
