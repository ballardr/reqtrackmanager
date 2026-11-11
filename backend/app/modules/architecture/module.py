"""
Module: modules.architecture.module

Registers the System Architecture module into the modular feature system's
registry via `MODULE_DEFINITION`. As built so far it delivers the element type and
connection type vocabularies: an organisation's defaults, a project's own rows, and
hiding and restoring a default in a project.

Registered contributions:
- Roles (not additions to `ProjectRole`): `architecture_admin` (project) changes a
  project's vocabularies and `architecture_org_admin` (organisation) changes the
  organisation's defaults.
- One sub-component, `architecture_type`, for the vocabularies.
- `on_org_created` seeds each new organisation's default types; the migration
  backfills existing organisations so a module switched on later has them.
- `org_bundle_hooks` / `project_bundle_hooks` (`export.py`); every project key is
  template configuration.
- No `frontend_manifest` yet: the module has no screen, so it adds no navigation entry.

`default_enabled=False`: an organisation opts in explicitly, as for the other
modules; a fresh install is switched on through the server default table.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.architecture import export as architecture_export
from app.modules.architecture._shared import ARCHITECTURE_ADMIN_ROLE, ARCHITECTURE_ORG_ADMIN_ROLE
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    TYPE_SUBCOMPONENT_KEY,
    seed_org_defaults,
)
from app.modules.registry import (
    ModuleDefinition,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
)


def get_router() -> APIRouter | None:
    """The org-scoped router (organisation default types); imported lazily to avoid an import cycle with this
    module's own registration."""
    from app.modules.architecture.router import router

    return router


def get_project_router() -> APIRouter | None:
    """The project-scoped router (a project's types); imported lazily like `get_router`."""
    from app.modules.architecture.project_router import router

    return router


def _seed_org_defaults(db: Session, organization_id) -> None:
    """`ModuleDefinition.on_org_created`: seeds the default element and connection types."""
    seed_org_defaults(db, organization_id)


MODULE_DEFINITION = ModuleDefinition(
    key=ARCHITECTURE_MODULE_KEY,
    name="System Architecture",
    description=(
        "Record the structure of the product: the elements it is made of (systems, services, boards), the typed "
        "connections between them (APIs, queues, buses) and diagrams of them, alongside the requirements."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    on_org_created=_seed_org_defaults,
    models_import_path="app.modules.architecture.models",
    migrations_dir="app/modules/architecture/migrations",
    activity_metadata_types={
        "architecture_element_type": "structure",
        "architecture_connection_type": "structure",
    },
    sub_components=(
        ModuleSubComponentDefinition(key=TYPE_SUBCOMPONENT_KEY, name="Element and connection types", default_enabled=True),
    ),
    org_bundle_hooks=ModuleOrgBundleHooks(
        export=architecture_export.export_org_data, import_=architecture_export.import_org_data,
    ),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=architecture_export.export_project_data, import_=architecture_export.import_project_data,
        template_configuration_keys=architecture_export.PROJECT_KEYS,
    ),
    roles=(
        ModuleRoleDefinition(
            role_key=ARCHITECTURE_ADMIN_ROLE, name="Architecture Admin",
            description="Manages the project's element types and connection types, and hides or restores the organisation's defaults there.",
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key=ARCHITECTURE_ORG_ADMIN_ROLE, name="Architecture Org Admin",
            description="Manages the organisation's default element types and connection types.",
            scope="org",
        ),
    ),
)
