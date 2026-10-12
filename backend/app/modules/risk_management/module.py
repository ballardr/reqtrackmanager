"""
Module: modules.risk_management.module

Registers the Risk Management module into the modular feature system's registry
via `MODULE_DEFINITION` (docs/plans/module-03-risk-management-plan.md). Phases 1-2
deliver the Risk artefact, its type vocabulary, the `risk` scoring scheme, module
RBAC and the lifecycle.

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

Not yet registered, by design: the artefact summary provider and link-type seeds
(Phase 3, when a risk first becomes linkable from the UI), the frontend manifest
(Phase 5) and MCP tools (Phase 4). Bundle export/import hooks are not provided
either, matching Decision Management and Context & Strategy.

`default_enabled=False`: an organisation opts in explicitly, matching the other
new modules.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, ModuleSubComponentDefinition
from app.modules.risk_management._shared import RISK_ACCEPT_PERMISSION, RISK_MANAGE_PERMISSION
from app.modules.risk_management.scoring import RISK_SCORING_SCHEME
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    RISK_TYPES,
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
    sub_components=(ModuleSubComponentDefinition(key=RISK_SUBCOMPONENT_KEY, name="Risks", default_enabled=True),),
    scoring_schemes=(RISK_SCORING_SCHEME,),
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
