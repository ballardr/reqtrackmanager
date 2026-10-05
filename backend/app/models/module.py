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

Also holds `ProjectModuleEnablement` (Module 0 — Platform Foundations —
Phase 5): a project-tier override of whole-module enablement itself,
mirroring `OrganizationModuleEnablement`'s own shape one level down. See
`app.modules.registry.is_module_enabled_for_project` for the resolution
formula (entitlement -> project override -> org default -> registry
default).

Also holds `OrganizationModuleSubComponentDefault`/`ProjectModuleSubComponentEnablement`
(Module 0 — Platform Foundations — Phase 4): a second, finer-grained pair
of gating tables one tier *below* whole-module enablement, for toggling an
individual sub-component of an already-enabled module (e.g. Context &
Strategy's "Strategy" vs. "Pain Point" vs. "Future State"). See
`app.modules.registry.is_module_subcomponent_enabled`/`is_org_module_
subcomponent_enabled` for the full two/one-tier resolution formula each
combines with `ModuleDefinition.sub_components` to produce — Phase 5's own
`is_module_enabled_for_project` is what `is_module_subcomponent_enabled`'s
own first (whole-module) check now calls, so a project-level whole-module
override correctly cascades to disable/enable that module's sub-components
too.
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

    `default_project_enabled` (added migration 0055, Module 0 Phase 5
    correction, **Decided by: User, 2026-09-29** — see `docs/decisions.md`'s
    dated entry) is a third, independent tier, only meaningful when
    `enabled` is `True`: does a project get this module on or off *by
    default*, absent an override of its own? This is deliberately separate
    from `enabled` itself — `enabled=False` remains an absolute floor no
    project can cross regardless of `default_project_enabled` or any
    `ProjectModuleEnablement` row (`is_module_enabled_for_project`'s own
    "hard floor" check never even looks at this column when `enabled` is
    `False`) — while `default_project_enabled` lets an org admin ship a
    module "available, but opt-in per project" (e.g. a specialist module
    most projects don't need, but any project manager may still turn on
    for their own project) without that opt-in being indistinguishable
    from the module being unavailable outright.

    Attributes:
        organization_id: The organisation this enablement override applies
            to.
        module_key: The module's registry key (`ModuleDefinition.key`),
            same convention as `OrganizationModuleEntitlement.module_key`.
        enabled: Whether the organisation's admin has explicitly enabled
            (`True`) or disabled (`False`) the module — both are meaningful
            explicit states, distinct from "no row" (falls back to the
            registry's `default_enabled`). An absolute floor: `False` means
            no project of this organisation may use this module at all, no
            override possible in either direction.
        default_project_enabled: Whether a project of this organisation
            gets this module on or off *by default*, absent a
            `ProjectModuleEnablement` override of its own — only consulted
            when `enabled` is `True`. A project's own override is
            symmetric against this value (either direction), matching
            `ProjectModuleEnablement`'s own docstring.
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
    default_project_enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ProjectModuleEnablement(UUIDPKMixin, TimestampMixin, Base):
    """Project-tier override of whole-module enablement (Module 0 —
    Platform Foundations — Phase 5, added immediately after Phase 4's own
    sub-component layer) — a project admin's own choice, taking precedence
    over the organisation's own `OrganizationModuleEnablement` above it for
    this project only (`app.modules.registry.is_module_enabled_for_project`).

    Mirrors `OrganizationModuleEnablement`'s own explicit-override-only
    shape one tier down, the same way `ProjectModuleSubComponentEnablement`
    already does for sub-components: the absence of a row for a given
    `(project_id, module_key)` pair means "use the organisation's own
    `OrganizationModuleEnablement.default_project_enabled` value, or the
    registry's `default_enabled` if the organisation has no row at all" —
    not "disabled." Effective enablement still additionally requires
    entitlement *and* the organisation's own `enabled` flag both being
    `True` (`app.modules.registry.is_module_enabled`) — both are an
    absolute floor this project-level tier cannot cross upward regardless
    of what it sets: an org not entitled to a module, or one that has hard-
    disabled it outright, stays disabled for every one of its projects no
    matter what any override says.

    The override is **symmetric against the organisation's
    `default_project_enabled` value specifically** (Decided by: User,
    2026-09-28, reaffirmed with this corrected scope 2026-09-29 — see
    `docs/decisions.md`'s dated entry for the full reasoning): a project
    admin's own choice always wins over that *default* in either direction
    — enabling a module the organisation defaults off for new projects
    (e.g. a specialist module most projects don't need, but any project
    manager may still opt in for their own), or disabling one the
    organisation defaults on — but this symmetry only ever operates
    *within* the organisation's own `enabled=True` floor, never past it.
    An initial, broader "symmetric against `enabled` itself, in either
    direction, no floor at all" design shipped 2026-09-28 and was reversed
    the next day once a real need surfaced for the org to hard-block a
    module with no project-level exception possible — see
    `docs/plans/module-00-platform-foundations-plan.md`'s Phase 5
    correction note.

    Attributes:
        project_id: The project this override applies to.
        module_key: The module's registry key (`ModuleDefinition.key`),
            same convention as `OrganizationModuleEnablement.module_key`.
        enabled: Whether the project admin has explicitly enabled (`True`)
            or disabled (`False`) the module for this project — both
            meaningful explicit states, distinct from "no row" (falls back
            to the organisation's own enablement state).
        updated_by: The project admin who last set this override, for
            audit attribution independent of `AuditEvent.actor_id`.
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
    """Org-tier default enable/disable state for one sub-component of a
    module (Module 0 — Platform Foundations — Phase 4) — the organisation-
    wide policy lever a project's own `ProjectModuleSubComponentEnablement`
    (below) may override, and, for a sub-component of an org-scoped
    artefact with no project tier above it at all, the effective value
    outright (`app.modules.registry.is_org_module_subcomponent_enabled`).

    Same **explicit-override-only** shape as `OrganizationModuleEnablement`
    one tier up: the absence of a row for a given `(organization_id,
    module_key, subcomponent_key)` triple means "use the registry's own
    `ModuleSubComponentDefinition.default_enabled`," not "disabled." Only
    meaningful for a `(module_key, subcomponent_key)` pair the module
    actually declares in its own `ModuleDefinition.sub_components` — a row
    for an undeclared/stale key is simply never consulted (`app.modules.
    registry._find_subcomponent_definition` returns `None` for it, and
    both resolution functions treat that the same as "disabled").

    Attributes:
        organization_id: The organisation this default applies to.
        module_key: The declaring module's registry key, same convention
            as `OrganizationModuleEnablement.module_key`.
        subcomponent_key: The sub-component's key, as declared in that
            module's own `ModuleDefinition.sub_components`.
        enabled: Hard floor, same meaning as `OrganizationModuleEnablement.
            enabled`: `False` turns this sub-component off for the org-level
            artefact and every project, no project override possible.
        default_project_enabled: The value copied into a project when it is
            created (`app.modules.registry.snapshot_project_module_state`).
            Changing it does not alter existing projects (added migration
            0056, Decided by: User, 2026-10-04).
        updated_by: The org admin who last set this default, for audit
            attribution independent of `AuditEvent.actor_id`.
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
    """Project-tier override of one sub-component's enabled state (Module
    0 — Platform Foundations — Phase 4) — a project admin's own choice for
    their project only, taking precedence over the organisation's own
    `OrganizationModuleSubComponentDefault` above it
    (`app.modules.registry.is_module_subcomponent_enabled`'s resolution
    order). This mirrors the org tier's own split
    (`OrganizationModuleEntitlement`/`OrganizationModuleEnablement`) one
    level down; whole-module enablement gained an equivalent project-level
    override of its own in Phase 5 (`ProjectModuleEnablement`, added
    immediately after this table), so this is no longer the *only*
    project-level override in this module — it remains, however, the only
    one with no separate hard-floor tier of its own (see below).

    Same **explicit-override-only** shape as its siblings: the absence of
    a row for a given `(project_id, module_key, subcomponent_key)` triple
    means "use the organisation's own default (or the registry default if
    the organisation has none either)," not "disabled." Effective
    enablement additionally requires the *whole module* to be effectively
    enabled for this project (`app.modules.registry.
    is_module_enabled_for_project`) — a project admin cannot re-enable a
    sub-component of a module their organisation has hard-disabled
    entirely, or that this project's own whole-module override has turned
    off (`is_module_subcomponent_enabled`'s "whole-module disabled always
    wins first" rule).

    **Deliberately kept simple — plain org default + symmetric project
    override, with no separate hard-floor tier of its own, unlike
    `OrganizationModuleEnablement`'s `enabled` vs. `default_project_enabled`
    split above it (Decided by: Agent, 2026-09-29, flagged for the user to
    reconsider if a real need surfaces).** The whole-module tier's own hard
    floor already fully covers "the org needs to shut this off entirely,
    no exceptions" for every one of its sub-components too, since a
    hard-disabled module already blocks all of them regardless of their
    own org-default/override state. Adding a second, independent hard-floor
    concept one tier down — "hard-block just this one sub-component, no
    per-project exception possible, even though the rest of the module
    stays on" — would be speculative complexity for a capability nobody
    has asked for at this granularity yet.

    Attributes:
        project_id: The project this override applies to.
        module_key: The declaring module's registry key, same convention
            as `OrganizationModuleSubComponentDefault.module_key`.
        subcomponent_key: The sub-component's key, same convention as
            `OrganizationModuleSubComponentDefault.subcomponent_key`.
        enabled: Whether the project admin has explicitly enabled (`True`)
            or disabled (`False`) this sub-component for this project —
            both meaningful explicit states, distinct from "no row" (falls
            back to the organisation's default).
        updated_by: The project admin who last set this override, for
            audit attribution independent of `AuditEvent.actor_id`.
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
