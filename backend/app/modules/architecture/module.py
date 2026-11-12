"""
Module: modules.architecture.module

Registers the System Architecture module into the modular feature system's
registry via `MODULE_DEFINITION`. As built so far it delivers the element type and
connection type vocabularies (an organisation's defaults, a project's own rows, and
hiding and restoring a default in a project), the project's and the organisation's elements, ports and
connections, and sharing: collections of elements granted to projects and groups, read through
`visibility`.

Registered contributions:
- Roles (not additions to `ProjectRole`): `architect` (project; carries the
  Fine-Grained Access Control `(architecture_element, manage)` and
  `(architecture_connection, manage)` atoms) creates and changes elements, ports,
  connections and collections; `architecture_admin` (project) changes a project's vocabularies and
  `architecture_org_admin` (organisation) changes the organisation's defaults, its own elements and its
  collections, and reads every organisation-owned element.
- Sub-components `architecture_type`, `architecture_element` and `architecture_connection`.
- `artefact_types` for the element and the connection, with their summary providers,
  search, report fields, record tables (export and import), scaling probes, dataset
  generators and the link types the module adds (`LINK_TYPE_SEEDS`). Both are placeable
  and taggable through the shared tables, so they declare nothing for either.
- `principal_references` for an element's owner and for the group a collection grant names.
- `on_org_created` seeds each new organisation's default types; the migration
  backfills existing organisations so a module switched on later has them.
- `org_bundle_hooks` / `project_bundle_hooks` (`export.py`); the vocabularies are
  template configuration and the records are template records.
- No `frontend_manifest` yet: the module has no screen, so it adds no navigation entry.

`default_enabled=False`: an organisation opts in explicitly, as for the other
modules; a fresh install is switched on through the server default table.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import LinkFlow
from app.models.project import Project
from app.modules.architecture import export as architecture_export
from app.modules.architecture import records
from app.modules.architecture._shared import (
    ARCHITECT_ROLE,
    ARCHITECTURE_ADMIN_ROLE,
    ARCHITECTURE_ORG_ADMIN_ROLE,
    CONNECTION_MANAGE_PERMISSION,
    ELEMENT_MANAGE_PERMISSION,
)
from app.modules.architecture.collections import COLLECTION_ENTITY_TYPE
from app.modules.architecture.models import ArchitectureCollectionGrant, ArchitectureConnection, ArchitectureElement
from app.modules.architecture.perf_dataset import generate_connections, generate_elements
from app.modules.architecture.record_attachments import NO_RECORD_ATTACHMENTS, RECORD_ATTACHMENTS
from app.modules.architecture.record_tables import RECORD_TABLES
from app.modules.architecture.report_fields import REPORT_FIELDS
from app.modules.architecture.scaling_probes import SCALING_PROBES
from app.modules.architecture.search import SEARCH_PROVIDERS
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_SUBCOMPONENT_KEY,
    TYPE_SUBCOMPONENT_KEY,
    seed_org_defaults,
)
from app.modules.architecture.summaries import CONNECTION_SUMMARY_PROVIDER, ELEMENT_SUMMARY_PROVIDER
from app.modules.registry import (
    LinkTypeSeed,
    ModuleDefinition,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
    PerfDatasetGenerator,
    PrincipalReference,
)

_BOTH = (ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE)

records.register_usage_checks()

# "Allocated to" (a requirement to an element) and "Verified by" (an element or connection to an action) are
# core defaults and need no seed. Seeds name types that may not be registered yet ("design"); until then they
# are simply not offered.
LINK_TYPE_SEEDS: tuple[LinkTypeSeed, ...] = (
    LinkTypeSeed(
        "Constrains", "Constrained by", LinkFlow.NONE,
        allowed_source_types=("requirement",), allowed_target_types=(CONNECTION_ARTEFACT_TYPE,),
    ),
    LinkTypeSeed("Affected by", "Affects", LinkFlow.NONE, allowed_source_types=_BOTH, allowed_target_types=("risk",)),
    LinkTypeSeed("Concerns", "Concerned by", LinkFlow.NONE, allowed_source_types=("decision",), allowed_target_types=_BOTH),
    LinkTypeSeed("Describes", "Described by", LinkFlow.NONE, allowed_source_types=("design",), allowed_target_types=_BOTH),
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


def _artefact_ids_in_organization(db: Session, organization_id):
    """`ModuleDefinition.artefact_ids_in_organization`: every element and connection in the organisation's projects,
    for organisation deletion's polymorphic cleanup."""
    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    return (
        set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.project_id.in_(project_ids))))
        | set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.organization_id == organization_id)))
        | set(db.scalars(select(ArchitectureConnection.id).where(ArchitectureConnection.project_id.in_(project_ids))))
    )


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
        "architecture_collection": "structure",
    },
    artefact_types=_BOTH,
    artefact_type_labels={ELEMENT_ARTEFACT_TYPE: "Element", CONNECTION_ARTEFACT_TYPE: "Connection"},
    artefact_ids_in_organization=_artefact_ids_in_organization,
    artefact_summary_providers={
        ELEMENT_ARTEFACT_TYPE: ELEMENT_SUMMARY_PROVIDER, CONNECTION_ARTEFACT_TYPE: CONNECTION_SUMMARY_PROVIDER,
    },
    search_providers=SEARCH_PROVIDERS,
    report_fields=REPORT_FIELDS,
    record_attachments=RECORD_ATTACHMENTS,
    no_record_attachments=NO_RECORD_ATTACHMENTS,
    record_tables=RECORD_TABLES,
    scaling_probes=SCALING_PROBES,
    perf_generators={
        ELEMENT_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_elements, order=190),
        CONNECTION_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_connections, order=195),
    },
    link_type_seeds=LINK_TYPE_SEEDS,
    principal_references=(
        PrincipalReference(
            model=ArchitectureElement, field="owner", label="element owners", audit_entity_type=ELEMENT_ARTEFACT_TYPE,
        ),
        # Deleting a group removes its grants (the access only narrows), so the field is not mandatory.
        PrincipalReference(
            model=ArchitectureCollectionGrant, field="group", label="architecture collection grants",
            audit_entity_type=COLLECTION_ENTITY_TYPE, multi_valued=True, record_id_field="collection_id",
        ),
    ),
    not_creatable_from_links={
        ELEMENT_ARTEFACT_TYPE: "Elements are created from the Architecture screens, which add the Links panel creator.",
        CONNECTION_ARTEFACT_TYPE: "A connection needs two elements, so it is created from the Architecture screens.",
    },
    sub_components=(
        ModuleSubComponentDefinition(key=TYPE_SUBCOMPONENT_KEY, name="Element and connection types", default_enabled=True),
        ModuleSubComponentDefinition(key=ELEMENT_SUBCOMPONENT_KEY, name="Elements", default_enabled=True),
        ModuleSubComponentDefinition(key=CONNECTION_SUBCOMPONENT_KEY, name="Connections", default_enabled=True),
    ),
    org_bundle_hooks=ModuleOrgBundleHooks(
        export=architecture_export.export_org_data, import_=architecture_export.import_org_data,
    ),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=architecture_export.export_project_data, import_=architecture_export.import_project_data,
        template_configuration_keys=architecture_export.PROJECT_KEYS,
        template_record_keys=architecture_export.RECORD_KEYS,
        template_reset=architecture_export.reset_for_template,
    ),
    roles=(
        ModuleRoleDefinition(
            role_key=ARCHITECT_ROLE, name="Architect",
            description="Creates and changes the project's elements, ports and connections, and their status.",
            scope="project", permissions=(ELEMENT_MANAGE_PERMISSION, CONNECTION_MANAGE_PERMISSION),
        ),
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
