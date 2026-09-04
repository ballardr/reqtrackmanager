"""
Module: models.module

Two-tier module gating tables for the modular feature system
(compliance-module-plan.md Phase 1): server-tier entitlement (the
licensing/plan lever) and org-tier enablement (the day-to-day on/off
switch an org admin controls among modules their organisation is entitled
to). See `app.modules.registry` for how these combine with the static
module registry to produce an effective enabled/disabled value, and
`app.models.server_role` for the sibling Phase 0 server-tier RBAC table
this phase builds on.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class OrganizationModuleEntitlement(UUIDPKMixin, TimestampMixin, Base):
    """Server-tier override of whether an organisation is entitled to use a
    given module — the licensing/plan lever, managed by `ServerRole.
    SERVER_ADMIN` or `ServerRole.MODULE_ADMINISTRATOR` (module system
    Phase 0/1).

    This is an **explicit-override-only** table, the same shape as
    `Organization.accent_color_hex` falling back to `ServerSettings`
    (`services/branding.py`): the *absence* of a row for a given
    `(organization_id, module_key)` pair is meaningful, not an incomplete
    state to be backfilled. When no row exists, effective entitlement falls
    back to the deployment-wide `ServerSettings.
    default_module_entitlement_policy` (see `app.modules.registry.
    is_module_entitled`) — so a fresh self-hosted deployment with the
    default `OPEN` policy needs zero rows in this table for every module to
    be entitled everywhere, while a commercial/SaaS posture can flip the
    default to `CLOSED` and grant entitlement to specific organisations by
    inserting rows here.

    An org admin cannot influence this table at all — it is one tier above
    `OrganizationModuleEnablement` (the org's own enable/disable switch)
    and gates it: a module an org is not entitled to can never be enabled
    by that org's own admin, regardless of what `OrganizationModuleEnablement`
    says (`app.modules.registry.is_module_enabled`'s AND logic).

    Attributes:
        organization_id: The organisation this entitlement override applies
            to.
        module_key: The module's registry key (`ModuleDefinition.key`) —
            deliberately a plain string, not a foreign key into a modules
            table, since modules are defined in code (the registry), not
            as database rows.
        entitled: Whether the organisation is explicitly entitled (`True`)
            or explicitly denied (`False`) — both are meaningful explicit
            states, distinct from "no row" (falls back to server policy).
        updated_by: The server admin / module administrator who last set
            this override, for audit attribution independent of
            `AuditEvent.actor_id` (which is also logged at the call site) —
            mirrors `UserServerRole.granted_by`'s same rationale.
    """

    __tablename__ = "organization_module_entitlements"
    __table_args__ = (UniqueConstraint("organization_id", "module_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    entitled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OrganizationModuleEnablement(UUIDPKMixin, TimestampMixin, Base):
    """Org-tier override of whether an org admin has enabled a given
    module for day-to-day use — the switch an `OrgRole.ORG_ADMIN` controls
    directly (module system Phase 1), among whichever modules the
    organisation is currently entitled to (see
    `OrganizationModuleEntitlement`).

    Like `OrganizationModuleEntitlement`, this is an **explicit-override-
    only** table: the absence of a row for a given `(organization_id,
    module_key)` pair means "use the module's own registry default"
    (`ModuleDefinition.default_enabled`), not "disabled." This lets a
    module ship `default_enabled=True` (e.g. Compliance, per its own
    requirements' "enabled by default") and be immediately usable in every
    entitled organisation with zero rows written here, while still letting
    any individual org admin turn it off without affecting any other
    organisation.

    Effective enablement additionally requires entitlement — see
    `app.modules.registry.is_module_enabled`'s "entitled AND (enabled row
    if present else registry default)" formula. A stale `enabled=True` row
    here for a module whose entitlement was later revoked is harmless and
    deliberately not cleaned up: the AND already makes it inert (see the
    comment at the entitlement-revoking endpoint in `routers/system.py`).

    Attributes:
        organization_id: The organisation this enablement override applies
            to.
        module_key: The module's registry key (`ModuleDefinition.key`),
            same convention as `OrganizationModuleEntitlement.module_key`.
        enabled: Whether the organisation's admin has explicitly enabled
            (`True`) or disabled (`False`) the module — both are meaningful
            explicit states, distinct from "no row" (falls back to the
            registry's `default_enabled`).
        updated_by: The org admin who last set this override, for audit
            attribution independent of `AuditEvent.actor_id`.
    """

    __tablename__ = "organization_modules"
    __table_args__ = (UniqueConstraint("organization_id", "module_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    module_key: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
