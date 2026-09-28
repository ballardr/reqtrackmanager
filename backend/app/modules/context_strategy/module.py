"""
Module: modules.context_strategy.module

Registers the Context & Strategy module into the modular feature system's
registry (docs/plans/module-01-context-and-strategy-plan.md Phase 1) via
`MODULE_DEFINITION`, mirroring `app.modules.decisions.module`'s own
registration shape.

Four module-contributed roles are declared, not additions to `OrgRole`/
`ProjectRole`: `strategy_owner`/`strategy_approver` (project-scoped, for a
project-scoped Strategy) and `org_strategy_owner`/`org_strategy_approver`
(org-scoped, for an org-scoped Strategy) — Strategy is the first module in
this codebase whose own artefact is scoped at *either* level (Phase 0 Q2),
so it is also the first to need both an org- and a project-scoped flavour
of the same conceptual "owner"/"approver" role pair, rather than one or the
other the way every other module-with-roles so far has picked exactly one.

`get_router()` returns the org-scoped `router.py` (Decision Template-style
CRUD for organisation-scoped Strategies); `get_project_router()` returns
`project_router.py` (the project-scoped equivalent) — both real, working
HTTP surfaces from day one, since this phase (unlike Decision Management's
own Phase 1) combines what that module's plan split across its Phase 1
(data model) and Phase 4 (backend API) into one phase's scope.
`resolve_file_owner_project_id` is wired for the project-scoped half of
this module's file attachments only — see `service.
resolve_strategy_file_project_id`'s own docstring for why the org-scoped
half doesn't need it (`is_org_resource=True` uploads instead).

`artefact_types=(STRATEGY_ARTEFACT_TYPE,)` is registered now even though
Phase 6 (cross-artefact relationship wiring) is out of this phase's scope
— so Phase 6 doesn't also need a core-file edit later, following Decision
Management's own precedent (`DECISION_ARTEFACT_TYPE`) exactly.

`implemented=True` — Phase 1's own testing bar (full backend suite green,
`ruff check` clean, endpoint coverage) is met, and a real, working API
exists, even though no frontend does yet (Phase 7). `default_enabled`
stays `False`: an organisation must opt in explicitly until a UI exists to
actually use it, matching Decision Management's own Phase 4 posture.

No MCP tools are declared this phase — that is explicitly Phase 6's job
per this module's own plan (declared alongside the relationship endpoints,
once the full REST surface across all six of this module's eventual
artefact types is complete), not a per-phase addition the way some other
modules' MCP tools were.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.context_strategy._shared import STRATEGY_APPROVE_PERMISSION as _STRATEGY_APPROVE_PERMISSION
from app.modules.context_strategy.service import STRATEGY_ARTEFACT_TYPE
from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, ModuleSubComponentDefinition

CONTEXT_STRATEGY_MODULE_KEY = "context_strategy"


def get_router() -> APIRouter | None:
    """This module's org-scoped `APIRouter` (organisation-scoped Strategy
    CRUD/lifecycle/comments/files). Imported inside the function body, not
    at module top-level, to avoid any import-cycle risk with this module's
    own registration (mirrors every other module's identical convention)."""
    from app.modules.context_strategy.router import router as context_strategy_router

    return context_strategy_router


def get_project_router() -> APIRouter | None:
    """This module's project-scoped `APIRouter` (project-scoped Strategy
    CRUD/lifecycle/comments/files). Imported lazily for the same reason as
    `get_router()`."""
    from app.modules.context_strategy.project_router import router as context_strategy_project_router

    return context_strategy_project_router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook
    — only ever resolves a project-scoped Strategy's attachments (see
    `service.resolve_strategy_file_project_id`'s own docstring). Imported
    lazily for the same import-cycle reason as `get_router()`."""
    from app.modules.context_strategy.service import resolve_strategy_file_project_id

    return resolve_strategy_file_project_id(db, file_id)


MODULE_DEFINITION = ModuleDefinition(
    key=CONTEXT_STRATEGY_MODULE_KEY,
    name="Context & Strategy",
    description=(
        "Record organisation and project Strategy — objective, current/desired future state, rationale, "
        "expected outcomes, constraints, and measures of success — with a formal review/approval lifecycle."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    models_import_path="app.modules.context_strategy.models",
    migrations_dir="app/modules/context_strategy/migrations",
    artefact_types=(STRATEGY_ARTEFACT_TYPE,),
    # Module 0 (Platform Foundations) Phase 4: registers now, using the
    # first sub-component this module actually ships — the other four
    # Context & Strategy artefacts (Future State, Pain Point, Guiding
    # Principle, Open Question) don't exist yet, so each declares its own
    # key here only once its own phase lands, the same way this one does
    # now, rather than all five being declared speculatively up front.
    sub_components=(ModuleSubComponentDefinition(key="strategy", name="Strategy", default_enabled=True),),
    roles=(
        ModuleRoleDefinition(
            role_key="strategy_owner",
            name="Strategy Owner",
            description=(
                "Creates and manages project-scoped Strategy records — the module's management-level role "
                "for a project Strategy (docs/plans/module-01-context-and-strategy-plan.md Phase 1)."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="strategy_approver",
            name="Strategy Approver",
            description="May approve, activate, supersede, and retire project-scoped Strategy records.",
            scope="project",
            # Fine-Grained Access Control: a holder of this flat module role gets the equivalent
            # unscoped `(strategy, approve_baseline)` permission atom via `get_effective_permissions`,
            # mirroring Decision Management's `decision_approver` role exactly.
            permissions=(_STRATEGY_APPROVE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_strategy_owner",
            name="Organisation Strategy Owner",
            description="Creates and manages organisation-scoped Strategy records — the org-scoped equivalent of Strategy Owner.",
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="org_strategy_approver",
            name="Organisation Strategy Approver",
            description="May approve, activate, supersede, and retire organisation-scoped Strategy records.",
            scope="org",
            permissions=(_STRATEGY_APPROVE_PERMISSION,),
        ),
    ),
)
