"""
Module: modules.architecture.module

Registers the System Architecture module through `MODULE_DEFINITION`: element and connection type vocabularies (an
organisation's defaults, a project's own rows, hiding and restoring a default), elements, ports and connections for
projects and the organisation, sharing (collections granted to projects and groups, read through `visibility`), the
symbol library, diagrams (views with placements, notes and toggles drawn as a server SVG) and state machine diagrams.

Registered contributions:
- Roles (not `ProjectRole` additions): `architect` (project; Fine-Grained Access Control `manage` atoms for element,
  connection, diagram and state machine diagram) creates and changes records and collections; `architecture_admin`
  (project) changes the project's vocabularies and symbols; `architecture_org_admin` (organisation) changes the
  organisation's defaults, its own elements and collections, and reads every organisation-owned element.
- Sub-components `architecture_type` (types and symbol library), `architecture_element`, `architecture_connection`,
  `architecture_diagram` and `architecture_state_machine`.
- `artefact_types` for element, connection, diagram, state machine diagram and state, with summary providers, search,
  report fields, record tables (the diagram types export only: `NOT_IMPORTABLE`), scaling probes, dataset generators and
  `LINK_TYPE_SEEDS`; all are taggable and placeable except the state (`not_placeable`).
- `baseline_snapshots` (element, connection, diagram, state machine diagram with their parts), `principal_references`
  (an element's owner, a collection grant's group), `overview_metrics` and the `allocation_coverage` widget.
- `on_org_created` seeds each new organisation's default types.
- `org_bundle_hooks` / `project_bundle_hooks` (`export.py`): vocabularies are template configuration, records are
  template records, dismissed allocations are excluded from templates.
- `frontend_manifest`: one "System Architecture" navigation entry with Elements, Connections and Diagrams tabs; pages,
  dialogs and settings panels are served by `frontend/src/modules/architecture/module.ts`.

`default_enabled=False`: an organisation opts in; a fresh install is switched on through the server default table.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import LinkFlow
from app.models.project import Project
from app.modules.architecture import allocation_export, records
from app.modules.architecture import export as architecture_export
from app.modules.architecture._shared import (
    ARCHITECT_ROLE,
    ARCHITECTURE_ADMIN_ROLE,
    ARCHITECTURE_ORG_ADMIN_ROLE,
    CONNECTION_MANAGE_PERMISSION,
    DIAGRAM_MANAGE_PERMISSION,
    ELEMENT_MANAGE_PERMISSION,
    STATE_MACHINE_MANAGE_PERMISSION,
)
from app.modules.architecture.allocation_metrics import OVERVIEW_METRICS
from app.modules.architecture.baseline_snapshot import SNAPSHOT_PROVIDERS
from app.modules.architecture.collections import COLLECTION_ENTITY_TYPE
from app.modules.architecture.comments import RECORD_COMMENTS
from app.modules.architecture.long_text import MARKDOWN_FIELDS, PLAIN_TEXT_FIELDS
from app.modules.architecture.mcp_tools import build_mcp_tools
from app.modules.architecture.models import (
    ArchitectureCollectionGrant,
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
)
from app.modules.architecture.perf_dataset import (
    generate_connections,
    generate_diagrams,
    generate_elements,
    generate_state_machines,
    generate_states,
)
from app.modules.architecture.record_attachments import NO_RECORD_ATTACHMENTS, RECORD_ATTACHMENTS
from app.modules.architecture.record_tables import NOT_IMPORTABLE, RECORD_TABLES
from app.modules.architecture.report_fields import REPORT_FIELDS
from app.modules.architecture.report_starters import REPORT_STARTER_SECTIONS
from app.modules.architecture.reports import REPORT_DEFINITIONS
from app.modules.architecture.scaling_probes import SCALING_PROBES
from app.modules.architecture.search import SEARCH_PROVIDERS
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    CONNECTION_CODE_PREFIX,
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_ARTEFACT_TYPE,
    DIAGRAM_CODE_PREFIX,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_ARTEFACT_TYPE,
    ELEMENT_CODE_PREFIX,
    ELEMENT_SUBCOMPONENT_KEY,
    STATE_ARTEFACT_TYPE,
    STATE_CODE_PREFIX,
    STATE_MACHINE_ARTEFACT_TYPE,
    STATE_MACHINE_CODE_PREFIX,
    STATE_MACHINE_SUBCOMPONENT_KEY,
    TYPE_SUBCOMPONENT_KEY,
    seed_org_defaults,
)
from app.modules.architecture.summaries import (
    CONNECTION_SUMMARY_PROVIDER,
    DIAGRAM_SUMMARY_PROVIDER,
    ELEMENT_SUMMARY_PROVIDER,
    STATE_MACHINE_SUMMARY_PROVIDER,
    STATE_SUMMARY_PROVIDER,
)
from app.modules.registry import (
    LinkTypeSeed,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
    OverviewWidgetType,
    PerfDatasetGenerator,
    PrincipalReference,
)
from app.services.report_framework import report_mcp_tools

_BOTH = (ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE)
_ALL = (*_BOTH, DIAGRAM_ARTEFACT_TYPE, STATE_MACHINE_ARTEFACT_TYPE, STATE_ARTEFACT_TYPE)

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


#: The project router's mount prefix, which the report tools' paths fall under.
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{ARCHITECTURE_MODULE_KEY}"

# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


def get_project_router() -> APIRouter | None:
    """The project-scoped router (a project's types); imported lazily like `get_router`."""
    from app.modules.architecture.project_router import router

    return router


def _seed_org_defaults(db: Session, organization_id) -> None:
    """`ModuleDefinition.on_org_created`: seeds the default element and connection types."""
    seed_org_defaults(db, organization_id)


def _artefact_ids_in_organization(db: Session, organization_id):
    """`ModuleDefinition.artefact_ids_in_organization`: every element, connection and diagram in the organisation's projects,
    for organisation deletion's polymorphic cleanup."""
    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    return (
        set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.project_id.in_(project_ids))))
        | set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.organization_id == organization_id)))
        | set(db.scalars(select(ArchitectureConnection.id).where(ArchitectureConnection.project_id.in_(project_ids))))
        | set(db.scalars(select(ArchitectureDiagram.id).where(ArchitectureDiagram.project_id.in_(project_ids))))
        | set(db.scalars(select(ArchitectureStateMachineDiagram.id).where(ArchitectureStateMachineDiagram.project_id.in_(project_ids))))
        | set(db.scalars(select(ArchitectureState.id).where(ArchitectureState.project_id.in_(project_ids))))
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
        "architecture_folder": "structure",
        "architecture_symbol": "structure",
        "architecture_domain": "structure",
    },
    artefact_types=_ALL,
    default_code_prefixes={
        ELEMENT_ARTEFACT_TYPE: ELEMENT_CODE_PREFIX, CONNECTION_ARTEFACT_TYPE: CONNECTION_CODE_PREFIX,
        DIAGRAM_ARTEFACT_TYPE: DIAGRAM_CODE_PREFIX, STATE_MACHINE_ARTEFACT_TYPE: STATE_MACHINE_CODE_PREFIX,
        STATE_ARTEFACT_TYPE: STATE_CODE_PREFIX,
    },
    artefact_type_labels={
        ELEMENT_ARTEFACT_TYPE: "Element", CONNECTION_ARTEFACT_TYPE: "Connection", DIAGRAM_ARTEFACT_TYPE: "Diagram",
        STATE_MACHINE_ARTEFACT_TYPE: "State machine diagram", STATE_ARTEFACT_TYPE: "State",
    },
    artefact_ids_in_organization=_artefact_ids_in_organization,
    artefact_summary_providers={
        ELEMENT_ARTEFACT_TYPE: ELEMENT_SUMMARY_PROVIDER, CONNECTION_ARTEFACT_TYPE: CONNECTION_SUMMARY_PROVIDER,
        DIAGRAM_ARTEFACT_TYPE: DIAGRAM_SUMMARY_PROVIDER, STATE_MACHINE_ARTEFACT_TYPE: STATE_MACHINE_SUMMARY_PROVIDER,
        STATE_ARTEFACT_TYPE: STATE_SUMMARY_PROVIDER,
    },
    search_providers=SEARCH_PROVIDERS,
    markdown_fields=MARKDOWN_FIELDS,
    plain_text_fields=PLAIN_TEXT_FIELDS,
    reports=REPORT_DEFINITIONS,
    mcp_tools=build_mcp_tools(_PROJECT_ROUTER_PREFIX)
    + report_mcp_tools(REPORT_DEFINITIONS, project_router_prefix=_PROJECT_ROUTER_PREFIX),
    mcp_guidance=_MCP_GUIDANCE,
    report_fields=REPORT_FIELDS,
    report_starter_sections=REPORT_STARTER_SECTIONS,
    record_attachments=RECORD_ATTACHMENTS,
    no_record_attachments=NO_RECORD_ATTACHMENTS,
    record_tables=RECORD_TABLES,
    record_comments=RECORD_COMMENTS,
    not_importable=NOT_IMPORTABLE,
    scaling_probes=SCALING_PROBES,
    perf_generators={
        ELEMENT_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_elements, order=190),
        CONNECTION_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_connections, order=195),
        DIAGRAM_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_diagrams, order=197),
        STATE_MACHINE_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_state_machines, order=198),
        STATE_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_states, order=199),
    },
    link_type_seeds=LINK_TYPE_SEEDS,
    baseline_snapshots=SNAPSHOT_PROVIDERS,
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
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="System Architecture",
        nav_path=f"/projects/{{project_id}}/modules/{ARCHITECTURE_MODULE_KEY}",
        nav_icon="network",
        # One page with the tabs Elements, Connections and Diagrams: it is offered while any of the three is on.
        nav_sub_components_any=(
            ELEMENT_SUBCOMPONENT_KEY, CONNECTION_SUBCOMPONENT_KEY, DIAGRAM_SUBCOMPONENT_KEY, STATE_MACHINE_SUBCOMPONENT_KEY,
        ),
    ),
    not_creatable_from_links={
        CONNECTION_ARTEFACT_TYPE: "A connection needs two elements, so it is created from the Architecture screens.",
        STATE_MACHINE_ARTEFACT_TYPE: (
            "A state machine diagram describes one element and is drawn in its editor, so it is created from the "
            "Architecture screens."
        ),
        STATE_ARTEFACT_TYPE: "A state exists only inside its state machine diagram, so it is created in that diagram's editor.",
    },
    not_placeable={
        STATE_ARTEFACT_TYPE: "A state exists only inside its state machine diagram, which is itself placed in the component tree.",
    },
    sub_components=(
        ModuleSubComponentDefinition(key=TYPE_SUBCOMPONENT_KEY, name="Types and symbols", default_enabled=True),
        ModuleSubComponentDefinition(key=ELEMENT_SUBCOMPONENT_KEY, name="Elements", default_enabled=True),
        ModuleSubComponentDefinition(key=CONNECTION_SUBCOMPONENT_KEY, name="Connections", default_enabled=True),
        ModuleSubComponentDefinition(key=DIAGRAM_SUBCOMPONENT_KEY, name="Diagrams", default_enabled=True),
        ModuleSubComponentDefinition(
            key=STATE_MACHINE_SUBCOMPONENT_KEY, name="State machine diagrams", default_enabled=True,
            artefact_types=(STATE_MACHINE_ARTEFACT_TYPE, STATE_ARTEFACT_TYPE),
        ),
    ),
    overview_metrics=OVERVIEW_METRICS,
    overview_widgets={
        "allocation_coverage": OverviewWidgetType(
            label="Allocation coverage",
            description=(
                "The share of requirements allocated to an element, the requirements not allocated and the suggested "
                "allocations awaiting a decision."
            ),
            width=12, height=2, in_default_layout=True,
        ),
    },
    org_bundle_hooks=ModuleOrgBundleHooks(
        export=architecture_export.export_org_data, import_=architecture_export.import_org_data,
        export_files=architecture_export.export_org_files, import_files=architecture_export.import_org_files,
    ),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=architecture_export.export_project_data, import_=architecture_export.import_project_data,
        template_configuration_keys=architecture_export.PROJECT_KEYS,
        template_record_keys=architecture_export.RECORD_KEYS,
        template_reset=architecture_export.reset_for_template,
        template_excluded={allocation_export.DISMISSALS_KEY: allocation_export.TEMPLATE_REASON},
    ),
    roles=(
        ModuleRoleDefinition(
            role_key=ARCHITECT_ROLE, name="Architect",
            description=(
                "Creates and changes the project's elements, ports, connections, diagrams and state machine diagrams, "
                "and their status."
            ),
            scope="project",
            permissions=(
                ELEMENT_MANAGE_PERMISSION, CONNECTION_MANAGE_PERMISSION, DIAGRAM_MANAGE_PERMISSION,
                STATE_MACHINE_MANAGE_PERMISSION,
            ),
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
