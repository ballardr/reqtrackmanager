"""
Module: services.module_defaults

Server-wide default module states (`ServerModuleDefault`): listing them with their
provenance, changing one, applying them to every existing organisation, and seeding a
fresh install all-on.

Design decisions:
- The defaults are explicit-override-only and consulted live by
  `app.modules.registry` (no per-organisation rows are pre-created), so a later change
  reaches every organisation that never overrode the module.
- Changing a project default first freezes the current value into every row-less project of
  each affected organisation (`freeze_projects_module_default`), the same copy-before-change
  rule an organisation's own default follows: a default only affects projects created
  afterwards.
- Only a database with no `ServerSettings` row is "fresh": an upgrade has always had one, so
  it is never seeded and keeps its current effective states.
- Every function here leaves committing to the caller.

External dependencies: SQLAlchemy; the module registry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.module import OrganizationModuleEnablement, ServerModuleDefault
from app.models.organization import Organization, ServerSettings
from app.modules.registry import (
    freeze_projects_module_default,
    get_module_registry,
    is_module_entitled,
    resolve_default_project_enabled,
)
from app.services.branding import get_server_settings


@dataclass(frozen=True)
class ServerModuleDefaultState:
    """One module's effective server-wide default.

    Attributes:
        module_key: The module's registry key.
        org_enabled: Whether an organisation with no row of its own has it enabled.
        project_default_enabled: Whether such an organisation's projects get it on by default.
        has_override: Whether a `ServerModuleDefault` row decides these (else the registry's
            own `default_enabled` does).
    """

    module_key: str
    org_enabled: bool
    project_default_enabled: bool
    has_override: bool


def list_server_module_defaults(db: Session) -> list[ServerModuleDefaultState]:
    """Returns the effective server-wide default of every registered module.

    Args:
        db: An active database session.

    Returns:
        One state per registered module, in registry order.
    """
    rows = {row.module_key: row for row in db.scalars(select(ServerModuleDefault))}
    result: list[ServerModuleDefaultState] = []
    for definition in get_module_registry().values():
        row = rows.get(definition.key)
        result.append(
            ServerModuleDefaultState(
                module_key=definition.key,
                org_enabled=row.org_enabled if row else definition.default_enabled,
                project_default_enabled=row.project_default_enabled if row else definition.default_enabled,
                has_override=row is not None,
            )
        )
    return result


def _organizations_without_enablement_row(db: Session, module_key: str) -> list[uuid.UUID]:
    """Ids of organisations still reading the server default for `module_key`."""
    has_row = select(OrganizationModuleEnablement.organization_id).where(
        OrganizationModuleEnablement.module_key == module_key
    )
    return list(db.scalars(select(Organization.id).where(Organization.id.not_in(has_row))))


def set_server_module_default(
    db: Session, module_key: str, org_enabled: bool, project_default_enabled: bool, actor_id: uuid.UUID | None,
) -> ServerModuleDefault:
    """Sets the server-wide default of one registered module.

    A change of the project default is frozen into the existing projects of every organisation
    that has no row of its own first, so only projects created afterwards read the new value.

    Args:
        db: An active database session.
        module_key: A registered module's key (the caller validates it).
        org_enabled: Whether an organisation with no row of its own has the module enabled.
        project_default_enabled: Whether such an organisation's projects get it on by default.
        actor_id: The administrator making the change.

    Returns:
        The created or updated row.
    """
    row = db.scalar(select(ServerModuleDefault).where(ServerModuleDefault.module_key == module_key))
    current = next(state for state in list_server_module_defaults(db) if state.module_key == module_key)
    if project_default_enabled != current.project_default_enabled:
        for organization_id in _organizations_without_enablement_row(db, module_key):
            freeze_projects_module_default(db, organization_id, module_key)
        db.flush()
    if row is None:
        row = ServerModuleDefault(module_key=module_key)
        db.add(row)
    row.org_enabled = org_enabled
    row.project_default_enabled = project_default_enabled
    row.updated_by = actor_id
    db.flush()
    return row


def apply_server_defaults_to_organizations(
    db: Session, actor_id: uuid.UUID | None, module_key: str | None = None,
) -> tuple[int, int]:
    """Writes the server-wide default into every organisation's own enablement row, replacing
    whatever each organisation chose, for the modules it is entitled to (a non-entitled module
    gets no row: it cannot be used, and would read the same default if it became entitled).

    Existing projects keep their current state (the project default is frozen first).

    Args:
        db: An active database session.
        actor_id: The administrator applying the defaults.
        module_key: Limits the action to one registered module; every module when `None`.

    Returns:
        `(organisations changed, rows written)`.
    """
    defaults = {state.module_key: state for state in list_server_module_defaults(db)}
    keys = [module_key] if module_key else list(defaults)
    touched: set[uuid.UUID] = set()
    written = 0
    for organization_id in db.scalars(select(Organization.id)):
        for key in keys:
            if not is_module_entitled(db, organization_id, key):
                continue
            state = defaults[key]
            row = db.scalar(
                select(OrganizationModuleEnablement).where(
                    OrganizationModuleEnablement.organization_id == organization_id,
                    OrganizationModuleEnablement.module_key == key,
                )
            )
            if row is not None and (row.enabled, row.default_project_enabled) == (
                state.org_enabled, state.project_default_enabled,
            ):
                continue
            if resolve_default_project_enabled(db, organization_id, key) != state.project_default_enabled:
                freeze_projects_module_default(db, organization_id, key)
                db.flush()
            if row is None:
                row = OrganizationModuleEnablement(organization_id=organization_id, module_key=key)
                db.add(row)
            row.enabled = state.org_enabled
            row.default_project_enabled = state.project_default_enabled
            row.updated_by = actor_id
            touched.add(organization_id)
            written += 1
    db.flush()
    return len(touched), written


def effective_enabled_source(db: Session, organization_id: uuid.UUID, module_key: str) -> str:
    """Names the tier that decides whether `module_key` is enabled for an organisation.

    Args:
        db: An active database session.
        organization_id: The organisation.
        module_key: A registered module's key.

    Returns:
        `"organization"` when the organisation has its own row, `"server_default"` when a
        `ServerModuleDefault` row decides, else `"registry"`.
    """
    has_org_row = db.scalar(
        select(OrganizationModuleEnablement.id).where(
            OrganizationModuleEnablement.organization_id == organization_id,
            OrganizationModuleEnablement.module_key == module_key,
        )
    )
    if has_org_row is not None:
        return "organization"
    has_server_row = db.scalar(select(ServerModuleDefault.id).where(ServerModuleDefault.module_key == module_key))
    return "server_default" if has_server_row is not None else "registry"


def seed_fresh_install_defaults(db: Session) -> bool:
    """Seeds every registered module on/on as the server default for a fresh install, then
    creates the `ServerSettings` row that marks the install as no longer fresh. Does nothing on
    a database that already has server settings (an upgrade) or when
    `MODULES_DEFAULT_AVAILABLE` is off. Commits its own transaction.

    Args:
        db: An active database session.

    Returns:
        `True` if the defaults were seeded.
    """
    if not get_settings().modules_default_available:
        return False
    if db.scalar(select(ServerSettings.id)) is not None:
        return False
    for definition in get_module_registry().values():
        db.add(ServerModuleDefault(module_key=definition.key, org_enabled=True, project_default_enabled=True))
    db.flush()
    # Creating the settings row marks the install as non-fresh, so a restart never reseeds over an
    # administrator's changes; it commits the seeded rows in the same transaction.
    get_server_settings(db)
    return True
