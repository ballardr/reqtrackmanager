"""
Module: modules.context_strategy.module

Registers the Context & Strategy module into the modular feature system's
registry (docs/plans/module-01-context-and-strategy-plan.md Phases 1–2)
via `MODULE_DEFINITION`, mirroring `app.modules.decisions.module`'s own
registration shape.

Four module-contributed roles are declared, not additions to `OrgRole`/
`ProjectRole`: `strategy_owner`/`strategy_approver` (project-scoped, for a
project-scoped Strategy) and `org_strategy_owner`/`org_strategy_approver`
(org-scoped, for an org-scoped Strategy) — Strategy is the first module in
this codebase whose own artefact is scoped at *either* level (Phase 0 Q2),
so it is also the first to need both an org- and a project-scoped flavour
of the same conceptual "owner"/"approver" role pair, rather than one or the
other the way every other module-with-roles so far has picked exactly one.
Phase 2 (Future State) adds the same four-role shape a second time —
`future_state_owner`/`future_state_approver` (project) and
`org_future_state_owner`/`org_future_state_approver` (org) — for the
standalone Future State artefact, per Phase 0 Q1's follow-on that Future
State's roles mirror Strategy's in full.

`get_router()` returns the org-scoped `router.py` (Decision Template-style
CRUD for organisation-scoped Strategies); `get_project_router()` returns
`project_router.py` (the project-scoped equivalent) — both real, working
HTTP surfaces from day one, since this phase (unlike Decision Management's
own Phase 1) combines what that module's plan split across its Phase 1
(data model) and Phase 4 (backend API) into one phase's scope.
`resolve_file_owner_project_id` tries Strategy's own resolution first, then
Future State's, returning whichever resolves non-`None` first — this
module now has two project-scoped artefact types whose files need owning-
project resolution through this one shared hook. See `service.
resolve_strategy_file_project_id`/`resolve_future_state_file_project_id`'s
own docstrings for why the org-scoped half of either artefact doesn't need
it (`is_org_resource=True` uploads instead).

`artefact_types=(STRATEGY_ARTEFACT_TYPE, FUTURE_STATE_ARTEFACT_TYPE,
PAIN_POINT_ARTEFACT_TYPE)` is registered now even though Phase 6
(cross-artefact relationship wiring) is out of this phase's scope — so
Phase 6 doesn't also need a core-file edit later, following Decision
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

Phase 3 (Pain Points) adds a third sub-component (`"pain_point"`), a
project-scoped `pain_point_manager` role (Pain Point has no org scope of
its own — source overview §6 — so, unlike Strategy/Future State, there is
no `org_pain_point_manager` counterpart), and an org-scoped `pain_point_
type_admin` role gating `PainPointTypeDefinition` CRUD only (mirroring
`modules.compliance`'s `compliance_manager` module-role-for-org-admin-
config pattern — checked before registering a new role, per this phase's
own brief, rather than reusing core `OrgRole.ORG_ADMIN` directly the way
`routers.orgs.taxonomies`' core-owned `RequirementLinkTypeDefinition`
CRUD does; `PainPointTypeDefinition` is module-owned, so its admin gate is
a module role too, composing with `OrgRole.ORG_ADMIN` automatically via
`user_satisfies_module_role` the same way `compliance_manager` does).
`resolve_file_owner_project_id` now tries all three artefact types'
resolvers in sequence (Strategy, then Future State, then Pain Point).
`on_org_created=_seed_org_defaults` seeds each new organisation's default
Market/User/Operator Pain Point types (§6.2) — added only in this phase,
since Phase 1/2 had no org-scoped default vocabulary of their own to seed;
mirrors `modules.compliance`'s own `_seed_org_defaults`/`on_org_created`
hook exactly (module boundary cleanup, 2026-09-08 — see that hook's own
docstring), not a direct import of `service.seed_default_pain_point_types`
from the core org-creation router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.context_strategy._shared import FUTURE_STATE_APPROVE_PERMISSION as _FUTURE_STATE_APPROVE_PERMISSION
from app.modules.context_strategy._shared import PAIN_POINT_DECIDE_PERMISSION as _PAIN_POINT_DECIDE_PERMISSION
from app.modules.context_strategy._shared import STRATEGY_APPROVE_PERMISSION as _STRATEGY_APPROVE_PERMISSION
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    PAIN_POINT_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
)
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
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook.
    Tries Strategy's own project-scoped resolution first, then Future
    State's, then Pain Point's, returning whichever resolves non-`None`
    first — this module now has three project-scoped artefact types whose
    files need owning-project resolution through this one hook (see
    `service.resolve_strategy_file_project_id`/`resolve_future_state_file_
    project_id`/`resolve_pain_point_file_project_id`'s own docstrings for
    why the org-scoped half of Strategy/Future State is never resolved
    here — Pain Point has no org-scoped half at all). Imported lazily for
    the same import-cycle reason as `get_router()`."""
    from app.modules.context_strategy.service import (
        resolve_future_state_file_project_id,
        resolve_pain_point_file_project_id,
        resolve_strategy_file_project_id,
    )

    project_id = resolve_strategy_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    project_id = resolve_future_state_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    return resolve_pain_point_file_project_id(db, file_id)


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """This module's `ModuleDefinition.on_org_created` hook (module
    boundary cleanup, 2026-09-08) — seeds this organisation's default
    Market/User/Operator Pain Point types (source overview §6.2), mirroring
    `modules.compliance._seed_org_defaults`'s identical hook exactly (see
    that function's own docstring). Imported lazily for the same
    import-cycle reason as `get_router()`."""
    from app.modules.context_strategy.service import seed_default_pain_point_types

    seed_default_pain_point_types(db, organization_id)


MODULE_DEFINITION = ModuleDefinition(
    key=CONTEXT_STRATEGY_MODULE_KEY,
    name="Context & Strategy",
    description=(
        "Record organisation and project Strategy — objective, current/desired future state, rationale, "
        "expected outcomes, constraints, and measures of success — plus a standalone Future State artefact "
        "(current state, desired state, target date, outcomes, success measures, constraints, assumptions) — "
        "both with a formal review/approval lifecycle. Also records project-scoped Pain Points (problems, "
        "deficiencies, and improvement opportunities) with a configurable, org-shared type vocabulary and a "
        "branching triage lifecycle."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    on_org_created=_seed_org_defaults,
    models_import_path="app.modules.context_strategy.models",
    migrations_dir="app/modules/context_strategy/migrations",
    artefact_types=(STRATEGY_ARTEFACT_TYPE, FUTURE_STATE_ARTEFACT_TYPE, PAIN_POINT_ARTEFACT_TYPE),
    # Module 0 (Platform Foundations) Phase 4: each of Context & Strategy's
    # eventual six artefacts declares its own sub-component key only once
    # its own phase lands (Phase 1 registered "strategy", Phase 2 "future_
    # state", this is Phase 3's own "pain_point") — the remaining two
    # (Guiding Principle, Open Question) still don't exist yet, so aren't
    # declared speculatively up front.
    sub_components=(
        ModuleSubComponentDefinition(key="strategy", name="Strategy", default_enabled=True),
        ModuleSubComponentDefinition(key="future_state", name="Future State", default_enabled=True),
        ModuleSubComponentDefinition(key="pain_point", name="Pain Points", default_enabled=True),
    ),
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
        ModuleRoleDefinition(
            role_key="future_state_owner",
            name="Future State Owner",
            description=(
                "Creates and manages project-scoped Future State records — the module's management-level role "
                "for a project Future State (docs/plans/module-01-context-and-strategy-plan.md Phase 2)."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="future_state_approver",
            name="Future State Approver",
            description="May approve, activate, supersede, and retire project-scoped Future State records.",
            scope="project",
            permissions=(_FUTURE_STATE_APPROVE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_future_state_owner",
            name="Organisation Future State Owner",
            description=(
                "Creates and manages organisation-scoped Future State records — the org-scoped equivalent "
                "of Future State Owner."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="org_future_state_approver",
            name="Organisation Future State Approver",
            description="May approve, activate, supersede, and retire organisation-scoped Future State records.",
            scope="org",
            permissions=(_FUTURE_STATE_APPROVE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="pain_point_manager",
            name="Pain Point Manager",
            description=(
                "Triages Pain Points, changes their classification/type, sets priority, assigns an owner, and "
                "rejects/accepts/closes them (docs/plans/module-01-context-and-strategy-plan.md Phase 3) — a "
                "single elevated role, unlike Strategy/Future State's owner+approver pair, since source overview "
                "§6.5 names one 'Pain Point Manager / Project Manager' role rather than a two-tier split. Also "
                "manages this project's own Pain Point type overrides/local types (§6.2). Project-scoped only — "
                "Pain Point itself has no organisation scope."
            ),
            scope="project",
            # Fine-Grained Access Control: a holder of this flat module role gets the equivalent unscoped
            # `(pain_point, approve_baseline)` permission atom via `get_effective_permissions`, mirroring
            # `strategy_approver`/`future_state_approver` above.
            permissions=(_PAIN_POINT_DECIDE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="pain_point_type_admin",
            name="Pain Point Type Admin",
            description=(
                "Manages this organisation's shared Pain Point type vocabulary (Market/User/Operator by default, "
                "plus any org-added types) — add/rename/disable/remove, per source overview §6.2. Organisation-"
                "scoped; does not by itself grant any project-level Pain Point Manager capability."
            ),
            scope="org",
        ),
    ),
)
