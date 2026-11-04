"""
Module: modules.product_feedback.module

Registers the Product Feedback module into the modular feature system's registry via `MODULE_DEFINITION`.

Product Feedback captures enhancement requests: proposed solutions asked for by stakeholders, staff or support.
A request is a versioned record owned by a project or, where the organisation allows it, by the organisation
(its inbox). Delivery tracking stays in the organisation's own delivery tool; a request carries an external
reference to it.

- Roles: `feedback_triager` (project) and `org_feedback_triager` (organisation) edit, move, archive and attach
  evidence to requests; each carries the matching `(enhancement_request, manage)` permission atom. Submitting
  needs no role (a project administrator can restrict it to triagers).
- Sub-components: `enhancement_request` gates the project list; `organization_requests` gates the
  organisation's inbox, so an organisation administrator switches the inbox off without touching its projects.
- `default_enabled` stays `False`: an organisation opts in explicitly (**Decided by: Agent**).
- Link type: "Requested by" (request -> Stakeholder, Persona or Engagement), authored with the generic link tools;
  `demand.py` turns those links into demand through the registry's `demand_party_providers` hook.
- Merging: a duplicate is merged into a canonical request, reversibly (`merge.py`); demand is the union.
- MCP tools: write-enabled (`mcp_tools.py`).

No `frontend_manifest` yet: the nav entry and pages arrive with the module's UI, so no nav item points at a page that
does not exist. Reports, scoring and the remaining relationships arrive in later changes through the same
registration.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.product_feedback import export as bundle_export
from app.modules.product_feedback._shared import REQUEST_MANAGE_PERMISSION
from app.modules.product_feedback.demand import REQUESTED_BY_SEED
from app.modules.product_feedback.mcp_tools import build_mcp_tools
from app.modules.product_feedback.models import EnhancementRequestVersion
from app.modules.product_feedback.perf_dataset import generate_requests
from app.modules.product_feedback.record_attachments import NO_RECORD_ATTACHMENTS, RECORD_ATTACHMENTS
from app.modules.product_feedback.record_tables import RECORD_TABLES
from app.modules.product_feedback.report_fields import REPORT_FIELDS
from app.modules.product_feedback.scaling_probes import SCALING_PROBES
from app.modules.product_feedback.search import SEARCH_PROVIDERS
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
)
from app.modules.product_feedback.summaries import REQUEST_SUMMARY_PROVIDER
from app.modules.registry import (
    ModuleDefinition,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
    PerfDatasetGenerator,
    PrincipalReference,
)

# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


def get_router() -> APIRouter | None:
    """The org-scoped router (the inbox); imported lazily to avoid import cycles with this module's registration."""
    from app.modules.product_feedback.router import router

    return router


def get_project_router() -> APIRouter | None:
    """The project-scoped router (requests, settings, comments, files); imported lazily like `get_router`."""
    from app.modules.product_feedback.project_router import router

    return router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """`ModuleDefinition.resolve_file_owner_project_id`: the project owning a file attached to a project request
    (or its comment), else `None`."""
    from app.modules.product_feedback.service import resolve_request_file_project_id

    return resolve_request_file_project_id(db, file_id)


def _principal_references() -> tuple[PrincipalReference, ...]:
    """The owner field, which may name a user or a group (`services.principals`). It is optional and lives on
    version rows, so only the current version is counted or reassigned (`live_filter`) and the audit event is about
    the request (`record_id_field`)."""
    return (
        PrincipalReference(
            model=EnhancementRequestVersion, field="owner", label="enhancement request owners",
            audit_entity_type=REQUEST_ARTEFACT_TYPE, live_filter=lambda: EnhancementRequestVersion.valid_to.is_(None),
            record_id_field="request_id",
        ),
    )


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every request in the organisation's projects and its own
    inbox, for org deletion's polymorphic cleanup."""
    from app.models.project import Project
    from app.modules.product_feedback.models import EnhancementRequest

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    return set(db.scalars(select(EnhancementRequest.id).where(
        (EnhancementRequest.project_id.in_(project_ids)) | (EnhancementRequest.organization_id == organization_id)
    )).all())


MODULE_DEFINITION = ModuleDefinition(
    key=PRODUCT_FEEDBACK_MODULE_KEY,
    name="Product Feedback",
    description=(
        "Capture enhancement requests (proposed solutions) from stakeholders, staff and support in one place: "
        "versioned records with a triage lifecycle, an owner and an external reference to the delivery tool, held "
        "per project or in an optional organisation-level inbox."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    models_import_path="app.modules.product_feedback.models",
    migrations_dir="app/modules/product_feedback/migrations",
    artefact_types=(REQUEST_ARTEFACT_TYPE,),
    link_type_seeds=(REQUESTED_BY_SEED,),
    artefact_type_labels={REQUEST_ARTEFACT_TYPE: "Enhancement request"},
    artefact_ids_in_organization=_artefact_ids_in_organization,
    artefact_summary_providers={REQUEST_ARTEFACT_TYPE: REQUEST_SUMMARY_PROVIDER},
    search_providers=SEARCH_PROVIDERS,
    report_fields=REPORT_FIELDS,
    record_attachments=RECORD_ATTACHMENTS,
    no_record_attachments=NO_RECORD_ATTACHMENTS,
    record_tables=RECORD_TABLES,
    scaling_probes=SCALING_PROBES,
    perf_generators={REQUEST_ARTEFACT_TYPE: PerfDatasetGenerator(generate=generate_requests, order=166)},
    sub_components=(
        ModuleSubComponentDefinition(key=REQUEST_SUBCOMPONENT_KEY, name="Enhancement requests", default_enabled=True),
        ModuleSubComponentDefinition(
            key=ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY, name="Organisation-level request inbox", default_enabled=True,
        ),
    ),
    org_bundle_hooks=ModuleOrgBundleHooks(export=bundle_export.export_org_data, import_=bundle_export.import_org_data),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=bundle_export.export_project_data, import_=bundle_export.import_project_data,
        import_late=bundle_export.import_late_project_data,
    ),
    principal_references=_principal_references(),
    mcp_tools=build_mcp_tools(),
    mcp_guidance=_MCP_GUIDANCE,
    roles=(
        ModuleRoleDefinition(
            role_key="feedback_triager", name="Feedback Triager",
            description=(
                "Edits, moves, archives and attaches evidence to the project's enhancement requests. Any project "
                "member may submit one (unless the project restricted submission to triagers)."
            ),
            scope="project", permissions=(REQUEST_MANAGE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_feedback_triager", name="Organisation Feedback Triager",
            description="Edits, moves, archives and attaches evidence to the organisation's inbox requests.",
            scope="org", permissions=(REQUEST_MANAGE_PERMISSION,),
        ),
    ),
)
