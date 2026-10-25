"""
Module: modules.risk_management.module

Registers the Risk Management module into the modular feature system's registry
via `MODULE_DEFINITION`. It
delivers the Risk artefact, its type vocabulary, the `risk` scoring scheme, module
RBAC, the lifecycle, treatment relationships, reviews with reassessment
scheduling, and MCP tools.

Registered contributions:
- Roles (not additions to core enums): `risk_manager` (project; carries the FGAC
  `(risk, manage)` atom) gates edit/archive/evidence/project types/lifecycle
  moves, `risk_acceptor` (project; carries `(risk, approve_baseline)`) gates the
  move to Accepted, and `risk_type_admin` (org; also administers the `risk`
  scoring scheme's levels, bands and cell ratings) gates the org type
  vocabulary. Any project member may propose a risk.
- `artefact_types=("risk",)`, so a risk is a valid `ArtefactLink` endpoint, gets
  FGAC atoms and unique codes (`RSK-001`).
- `scoring_schemes`: the Likelihood/Consequence/Detectability `risk` scheme
  (`scoring.py`).
- `on_org_created` seeds each new organisation's default Risk types; the
  migration backfills existing organisations.
- One sub-component, `risk`, so a project can switch it off without disabling the
  whole module.
- `artefact_summary_providers` (`summaries.py`), so a risk is shown and followed
  from any link, and `link_type_seeds` (`LINK_TYPE_SEEDS`): "Treated by"
  (risk -> action), "Impacts" (risk -> requirement/design), and a Risk target for
  the Decision module's "Addresses". "Mitigates", "Verified by" and "Related to"
  are core defaults and need no seed. Relationships are made with the generic
  link endpoints; `treatment.py` adds the verdict on each treatment link.

- `notification_types` (review due, review overdue, treatment needs
  reassessment) so core's closed `NotificationType` enum is untouched;
  `scheduled_jobs` (the daily review sweep); `on_artefact_changed`, which moves
  effective treatment verdicts to `needs_reassessment` when the requirement or
  design behind them changes; and `mcp_tools` with `mcp_guidance`.

- `frontend_manifest` (Tier A; `frontend/src/modules/risk_management/
  module.ts` serves the register and detail routes and the admin sections).

- `reports` (four project-level reports, `reports.py`; the framework
  generates their routes, catalogue entries and `get_<slug>_report` MCP tools).
- Users and groups on parity: `principal_references` declares the risk owner, so
  an in-use group cannot be deleted without reassigning or clearing it.
- `org_bundle_hooks`/`project_bundle_hooks` (`export.py`): Risk types,
  and each Risk's current content, attachments, reviews and requirement
  treatment links with their verdicts.

`default_enabled=False`: an organisation opts in explicitly, matching the other
new modules.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import LinkFlow
from app.modules.registry import (
    ArtefactChange,
    LinkTypeSeed,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleScheduledJob,
    ModuleSubComponentDefinition,
    PrincipalReference,
)
from app.modules.risk_management import export as risk_export
from app.modules.risk_management._shared import RISK_ACCEPT_PERMISSION, RISK_MANAGE_PERMISSION
from app.modules.risk_management.alerts import NOTIFICATION_TYPES
from app.modules.risk_management.mcp_tools import build_mcp_tools
from app.modules.risk_management.models import RiskVersion
from app.modules.risk_management.record_tables import RECORD_TABLES
from app.modules.risk_management.report_fields import REPORT_FIELDS
from app.modules.risk_management.reports import REPORT_DEFINITIONS
from app.modules.risk_management.scoring import RISK_SCORING_SCHEME
from app.modules.risk_management.search import SEARCH_PROVIDERS
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    RISK_TYPES,
)
from app.modules.risk_management.summaries import RISK_SUMMARY_PROVIDER
from app.modules.risk_management.treatment import (
    IMPACTS_FORWARD,
    IMPACTS_REVERSE,
    TREATED_BY_FORWARD,
    TREATED_BY_REVERSE,
)

# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")

# "Design" and "System Element" are listed so the link types accept them
# the day those modules register; until then they are simply not offered.
LINK_TYPE_SEEDS: tuple[LinkTypeSeed, ...] = (
    LinkTypeSeed(
        TREATED_BY_FORWARD, TREATED_BY_REVERSE, LinkFlow.NONE,
        allowed_source_types=(RISK_ARTEFACT_TYPE,), allowed_target_types=("requirement_action",),
    ),
    LinkTypeSeed(
        IMPACTS_FORWARD, IMPACTS_REVERSE, LinkFlow.NONE,
        allowed_source_types=(RISK_ARTEFACT_TYPE,), allowed_target_types=("requirement", "design", "system_element"),
    ),
    # Merges into Decision Management's "Addresses" (decision -> pain point): a Decision may address a Risk.
    LinkTypeSeed(
        "Addresses", "Is addressed by", LinkFlow.NONE,
        allowed_source_types=("decision",), allowed_target_types=(RISK_ARTEFACT_TYPE,),
    ),
)


def _principal_references() -> tuple[PrincipalReference, ...]:
    """The owner field, which may name a user or a group (`services.principals`). It is optional and lives
    on version rows, so only the current version is counted or reassigned (`live_filter`) and the audit
    event is about the risk (`record_id_field`)."""
    return (
        PrincipalReference(
            model=RiskVersion, field="owner", label="risk owners", audit_entity_type=RISK_ARTEFACT_TYPE,
            live_filter=lambda: RiskVersion.valid_to.is_(None), record_id_field="risk_id",
        ),
    )


def get_router() -> APIRouter | None:
    """The org-scoped router (Risk type vocabulary); imported lazily to avoid
    import cycles with this module's own registration."""
    from app.modules.risk_management.router import router

    return router


def get_project_router() -> APIRouter | None:
    """The project-scoped router (Risk CRUD, types, comments, files); imported
    lazily like `get_router`."""
    from app.modules.risk_management.project_router import router

    return router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """`ModuleDefinition.resolve_file_owner_project_id`: the project owning a
    file attached to a risk (or its comment), else `None`."""
    from app.modules.risk_management.service import resolve_risk_file_project_id

    return resolve_risk_file_project_id(db, file_id)


def _run_review_notifications(db: Session) -> None:
    """`ModuleScheduledJob.run`: the daily review-due/overdue sweep; imported
    lazily like `get_router`."""
    from app.modules.risk_management.alerts import send_review_notifications

    send_review_notifications(db)


def _on_artefact_changed(db: Session, change: ArtefactChange) -> None:
    """`ModuleDefinition.on_artefact_changed`: flags treatment verdicts resting on
    the changed artefact for reassessment; imported lazily like `get_router`."""
    from app.modules.risk_management.alerts import on_artefact_changed

    on_artefact_changed(db, change)


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """`ModuleDefinition.on_org_created`: seeds the default Risk types."""
    RISK_TYPES.seed_defaults(db, organization_id)


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every risk in the
    organisation's projects, for org deletion's polymorphic cleanup."""
    from app.models.project import Project
    from app.modules.risk_management.models import Risk

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    return set(db.scalars(select(Risk.id).where(Risk.project_id.in_(project_ids))).all())


MODULE_DEFINITION = ModuleDefinition(
    key=RISK_MODULE_KEY,
    name="Risk Management",
    description=(
        "Record project Risks — statement, cause, risk event, consequence, owner, treatment strategy and "
        "acceptance criteria — with a configurable, org-shared type vocabulary and a configurable "
        "Likelihood × Consequence (optionally × Detectability) scoring matrix that derives each risk's inherent "
        "and residual rating. Every edit is a new version, so a risk's history is retained."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    on_org_created=_seed_org_defaults,
    models_import_path="app.modules.risk_management.models",
    migrations_dir="app/modules/risk_management/migrations",
    artefact_types=(RISK_ARTEFACT_TYPE,),
    artefact_type_labels={RISK_ARTEFACT_TYPE: "Risk"},
    artefact_ids_in_organization=_artefact_ids_in_organization,
    artefact_summary_providers={RISK_ARTEFACT_TYPE: RISK_SUMMARY_PROVIDER},
    search_providers=SEARCH_PROVIDERS,
    report_fields=REPORT_FIELDS,
    record_tables=RECORD_TABLES,
    link_type_seeds=LINK_TYPE_SEEDS,
    sub_components=(ModuleSubComponentDefinition(key=RISK_SUBCOMPONENT_KEY, name="Risks", default_enabled=True),),
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Risks",
        nav_path=f"/projects/{{project_id}}/modules/{RISK_MODULE_KEY}/risks",
        nav_icon="shield-alert",
        nav_sub_component=RISK_SUBCOMPONENT_KEY,
    ),
    scoring_schemes=(RISK_SCORING_SCHEME,),
    reports=REPORT_DEFINITIONS,
    org_bundle_hooks=ModuleOrgBundleHooks(export=risk_export.export_org_data, import_=risk_export.import_org_data),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=risk_export.export_project_data, import_=risk_export.import_project_data,
    ),
    notification_types=NOTIFICATION_TYPES,
    on_artefact_changed=_on_artefact_changed,
    scheduled_jobs=(ModuleScheduledJob(job_id="review_reminders", hour=3, minute=0, run=_run_review_notifications),),
    principal_references=_principal_references(),
    mcp_tools=build_mcp_tools(),
    mcp_guidance=_MCP_GUIDANCE,
    roles=(
        ModuleRoleDefinition(
            role_key="risk_manager", name="Risk Manager",
            description=(
                "Edits, archives and attaches evidence to the project's Risks, and manages the project's Risk types. "
                "Any project member may propose a Risk."
            ),
            scope="project", permissions=(RISK_MANAGE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="risk_acceptor", name="Risk Acceptor",
            description=(
                "Accepts a Risk's residual risk (moves it to Accepted). Distinct from Risk Manager: accepting is a "
                "separate sign-off from managing the risk."
            ),
            scope="project", permissions=(RISK_ACCEPT_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="risk_type_admin", name="Risk Type Admin",
            description=(
                "Manages the organisation's shared Risk type vocabulary and the Likelihood/Consequence/Detectability "
                "scoring levels, default model, rating bands and cell ratings."
            ),
            scope="org",
        ),
    ),
)
