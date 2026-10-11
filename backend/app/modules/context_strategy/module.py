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
once the full REST surface across all five of this module's eventual
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

Phase 4 (Guiding Principles) adds a fourth sub-component (`"guiding_
principle"`) and a fourth four-role pair — `guiding_principle_owner`/
`guiding_principle_approver` (project) and `org_guiding_principle_owner`/
`org_guiding_principle_approver` (org) — back to the Strategy/Future State
owner+approver shape (Guiding Principle is org/project dual-scoped, unlike
Pain Point). `resolve_file_owner_project_id` now tries all four artefact
types' resolvers in sequence (Strategy, Future State, Pain Point, then
Guiding Principle).

Phase 5 (Open Questions) adds a fifth sub-component (`"open_question"`) and
**two** project-scoped-only roles — `open_question_owner` (assign/
prioritise/change-status/close, §9.4's "Question Owner / Project Manager"
tier) and `open_question_resolver` (the `resolve` transition only, §9.4's
separate "Decision Maker" tier) — a genuinely different shape from both of
this module's existing precedents: not Pain Point's single-role model
(`pain_point_manager` gates every decide-tier action), and not Strategy/
Future State/Guiding Principle's dual-scope owner+approver pair (Open
Question has no organisation scope at all — see `models.OpenQuestion`'s own
docstring). Source overview §9.4 names three distinct permission tiers
(project members; "Question Owner / Project Manager"; "Decision Maker"),
unlike Pain Point's §6.5 two-tier split, which is why this phase adds two
roles rather than reusing Pain Point's one-role-plus-FGAC-fallback shape for
its own "decide"-tier action — **Decided by: Agent**, the specific judgment
call this phase's own brief flagged; see `docs/decisions.md`'s dated entry
for this phase for the full reasoning. `resolve_file_owner_project_id` now
tries all five artefact types' resolvers in sequence (Strategy, Future
State, Pain Point, Guiding Principle, then Open Question).

Phase 6 (Cross-artefact relationships) adds `mcp_tools` — this module's
first MCP tool declarations, per this plan's own text: the whole-module
list/get read tools it named as candidates back in Phase 1-5, plus (per the
2026-09-22 write-enabled-MCP decision — `docs/decisions.md`'s "Compliance
MCP write tools + generalized AI approval gate" entry, extended to this
module the same way) create/update tools for all five artefact types,
create-relationship/list-relationship tools, the three supersession-
creation tools, every non-decisive lifecycle-transition tool (propose/
submit-for-review/send-back/supersede/retire/activate, Pain Point's
triage/reject/mark-duplicate/accept/address/close, Open Question's
investigate/mark-ready-for-decision/withdraw), and five approve/decide-tier
tools (`approve_strategy`/`approve_future_state`/`activate_guiding_
principle`/`retire_guiding_principle`/`resolve_open_question`) gated by
`app.services.rbac.require_ai_approvals_enabled` when reached through MCP
— see `service.py`'s own Phase 6 docstring section ("MCP tools and the
`require_ai_approvals_enabled` gate") for the full reasoning, especially
why Guiding Principle's own gated pair is `activate`/`retire` rather than
`approve`. File-upload and comment endpoints are not declared — comments/
attachments are collaboration actions this module's own MCP scope has
never asked to expand (mirroring Decision Management's own `mcp_tools`
posture toward its comment/file endpoints), and file upload specifically
cannot be declared through this mechanism at all (`multipart/form-data`,
same mechanical constraint `modules.compliance.module`'s own docstring
documents for `upload_evidence_attachment`). Org-scoped Strategy/Future
State/Guiding Principle endpoints (`router.py`) are also not declared —
`get_router()`'s own prefix uses `{organization_id}`, not `{project_id}`,
and `require_ai_approvals_enabled` needs a `Project` to check, so an
org-scoped approve/activate/retire action has no MCP-safe way to satisfy
that gate; rather than special-case an org-only variant of the gate this
phase's own scope never asked for, this phase's MCP surface stays
project-scoped only throughout, matching Decision Management's own
project-only MCP tool set (Decision itself has no org scope either).

Phase 10 (Reporting extension) adds `scoring_schemes` — the `pain_point`
scheme (`scoring.py`) registered into core's generic scoring-matrix
mechanism, and widens `pain_point_type_admin` to cover its org-level
configuration.

Phase 12 (Reports) adds the org-scoped `org_reports_viewer` role (gating the
organisation-wide reports; org admins hold it by default) and nine read-only
`get_<slug>_report` MCP tools. Phase 12b moves the module-neutral half to
core: `reports.REPORT_DEFINITIONS` is declared on `ModuleDefinition.reports`,
the routes and MCP tools are generated by `services.report_framework`, and
the report routers are mounted on the existing org and project routers, so
`get_router()`/`get_project_router()` are unchanged. Organisation-wide
report endpoints are not MCP tools, for the same reason as the other
org-scoped endpoints above.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.context_strategy._shared import FUTURE_STATE_APPROVE_PERMISSION as _FUTURE_STATE_APPROVE_PERMISSION
from app.modules.context_strategy._shared import (
    GUIDING_PRINCIPLE_APPROVE_PERMISSION as _GUIDING_PRINCIPLE_APPROVE_PERMISSION,
)
from app.modules.context_strategy._shared import OPEN_QUESTION_RESOLVE_PERMISSION as _OPEN_QUESTION_RESOLVE_PERMISSION
from app.modules.context_strategy._shared import PAIN_POINT_DECIDE_PERMISSION as _PAIN_POINT_DECIDE_PERMISSION
from app.modules.context_strategy._shared import STRATEGY_APPROVE_PERMISSION as _STRATEGY_APPROVE_PERMISSION
from app.modules.context_strategy.reports import REPORT_DEFINITIONS
from app.modules.context_strategy.scoring import PAIN_POINT_SCORING_SCHEME
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    LINK_TYPE_SEEDS,
    OPEN_QUESTION_ARTEFACT_TYPE,
    PAIN_POINT_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
)
from app.modules.context_strategy.summaries import ARTEFACT_SUMMARY_PROVIDERS, ARTEFACT_TYPE_LABELS
from app.modules.registry import (
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleNavEntry,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
)
from app.services.report_framework import report_mcp_tools

CONTEXT_STRATEGY_MODULE_KEY = "context_strategy"
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}"

# Path-parameter dicts reused across many `McpToolDefinition`s below — every
# tool needs `project_id`; most need one artefact's own id too.
_PROJECT_ID_PARAM = {
    "name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The owning project.",
}


def _id_param(artefact_name: str, description: str) -> dict:
    return {"name": f"{artefact_name}_id", "type": "uuid", "required": True, "in": "path", "description": description}


def _comment_param(description: str, *, required: bool = False) -> dict:
    return {"name": "comment", "type": "string", "required": required, "in": "body", "description": description}


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
    State's, then Pain Point's, then Guiding Principle's, then Open
    Question's, returning whichever resolves non-`None` first — this module
    now has five project-scoped artefact types whose files need owning-
    project resolution through this one hook (see `service.resolve_
    strategy_file_project_id`/`resolve_future_state_file_project_id`/
    `resolve_pain_point_file_project_id`/`resolve_guiding_principle_file_
    project_id`/`resolve_open_question_file_project_id`'s own docstrings for
    why the org-scoped half of Strategy/Future State/Guiding Principle is
    never resolved here — Pain Point and Open Question have no org-scoped
    half at all). Imported lazily for the same import-cycle reason as
    `get_router()`."""
    from app.modules.context_strategy.service import (
        resolve_future_state_file_project_id,
        resolve_guiding_principle_file_project_id,
        resolve_open_question_file_project_id,
        resolve_pain_point_file_project_id,
        resolve_strategy_file_project_id,
    )

    project_id = resolve_strategy_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    project_id = resolve_future_state_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    project_id = resolve_pain_point_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    project_id = resolve_guiding_principle_file_project_id(db, file_id)
    if project_id is not None:
        return project_id
    return resolve_open_question_file_project_id(db, file_id)


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """This module's `ModuleDefinition.on_org_created` hook (module
    boundary cleanup, 2026-09-08) — seeds this organisation's default
    Market/User/Operator Pain Point types (source overview §6.2), mirroring
    `modules.compliance._seed_org_defaults`'s identical hook exactly (see
    that function's own docstring). Imported lazily for the same
    import-cycle reason as `get_router()`."""
    from app.modules.context_strategy.service import seed_default_pain_point_types

    seed_default_pain_point_types(db, organization_id)


# Maps a `_id_param`-style artefact name to its actual URL plural segment —
# not a mechanical `f"{artefact_name}s"` (that would produce "strategys",
# "future_states", "pain_points", "guiding_principles", "open_questions",
# none of which match this module's real hyphenated route segments).
_URL_SEGMENT: dict[str, str] = {
    "strategy": "strategies",
    "future_state": "future-states",
    "pain_point": "pain-points",
    "guiding_principle": "guiding-principles",
    "open_question": "open-questions",
}


def _lifecycle_tool(
    name: str, description: str, artefact_name: str, action: str, id_description: str, *,
    comment_required: bool = False, comment_description: str = "Optional comment recorded on this transition.",
) -> McpToolDefinition:
    """Builds one plain (non-approval-gated) lifecycle-transition tool —
    every such endpoint in this module takes the same `{project_id,
    <artefact>_id, comment?}` shape, so this factors out the repetition
    fourteen call sites below would otherwise duplicate."""
    return McpToolDefinition(
        name=name, description=description, method="POST",
        path_template=f"{_PROJECT_ROUTER_PREFIX}/{_URL_SEGMENT[artefact_name]}/{{{artefact_name}_id}}/{action}",
        params=[_PROJECT_ID_PARAM, _id_param(artefact_name, id_description), _comment_param(comment_description, required=comment_required)],
    )


_STRATEGY_CREATE_UPDATE_PARAMS = [
    {"name": "title", "type": "string", "required": True, "in": "body", "description": "Short display title."},
    {"name": "objective", "type": "string", "required": True, "in": "body", "description": "The Strategy's objective/strategic theme."},
    {"name": "current_state", "type": "string", "required": False, "in": "body", "description": "Short current-state text."},
    {"name": "desired_future_state", "type": "string", "required": False, "in": "body", "description": "Short desired-future-state text."},
    {"name": "rationale", "type": "string", "required": False, "in": "body", "description": "Why this Strategy exists."},
    {"name": "expected_outcomes", "type": "string", "required": False, "in": "body", "description": "Expected outcomes."},
    {"name": "constraints", "type": "string", "required": False, "in": "body", "description": "Known constraints."},
    {"name": "measures_of_success", "type": "string", "required": False, "in": "body", "description": "How success will be measured."},
    {"name": "priority", "type": "string", "required": False, "in": "body", "description": "One of: low, medium, high."},
    {"name": "time_horizon", "type": "string", "required": False, "in": "body", "description": "One of: short_term, medium_term, long_term."},
]

_FUTURE_STATE_CREATE_UPDATE_PARAMS = [
    {"name": "title", "type": "string", "required": True, "in": "body", "description": "Short display title."},
    {"name": "current_state", "type": "string", "required": False, "in": "body", "description": "Current state text."},
    {"name": "desired_state", "type": "string", "required": False, "in": "body", "description": "Desired state text."},
    {"name": "target_date", "type": "string", "required": False, "in": "body", "description": "ISO date this Future State targets, if known."},
    {"name": "outcomes", "type": "string", "required": False, "in": "body", "description": "Expected outcomes."},
    {"name": "success_measures", "type": "string", "required": False, "in": "body", "description": "How success will be measured."},
    {"name": "constraints", "type": "string", "required": False, "in": "body", "description": "Known constraints."},
    {"name": "assumptions", "type": "string", "required": False, "in": "body", "description": "Assumptions this Future State relies on."},
]

_PAIN_POINT_CREATE_PARAMS = [
    {"name": "pain_point_type_id", "type": "uuid", "required": True, "in": "body",
     "description": "An effective Pain Point type id for this project (GET .../pain-point-types)."},
    {"name": "title", "type": "string", "required": True, "in": "body", "description": "Short display title."},
    {"name": "description", "type": "string", "required": False, "in": "body", "description": "Description of the problem."},
    {"name": "source", "type": "string", "required": False, "in": "body", "description": "Where this Pain Point came from."},
    {"name": "impact", "type": "string", "required": False, "in": "body", "description": "Its impact."},
    {"name": "evidence", "type": "string", "required": False, "in": "body", "description": "Supporting evidence."},
    {"name": "priority", "type": "string", "required": False, "in": "body", "description": "One of: low, medium, high."},
    {"name": "date_identified", "type": "string", "required": False, "in": "body",
     "description": "ISO date identified; defaults to today if omitted."},
    {"name": "is_intentional", "type": "boolean", "required": False, "in": "body",
     "description": "True for a deliberate limitation (e.g. a lower-tier restriction that drives upgrades); "
                    "scored but excluded from fix rankings by default. On update, omit to leave unchanged."},
]

_PAIN_POINT_SCORING_QUERY_PARAMS = [
    {"name": "model_key", "type": "string", "required": False, "in": "query",
     "description": "Scoring model: sxf (Severity x Frequency), sxc (Severity x Confidence) or sxfxc; "
                    "defaults to the project's configured default."},
    {"name": "rollup", "type": "string", "required": False, "in": "query",
     "description": "How per-persona scores combine: weighted_average (default), worst_case or average."},
]

_PAIN_POINT_UPDATE_PARAMS = [
    p for p in _PAIN_POINT_CREATE_PARAMS if p["name"] != "date_identified"
] + [{"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this Pain Point."}]

_GUIDING_PRINCIPLE_CREATE_UPDATE_PARAMS = [
    {"name": "name", "type": "string", "required": True, "in": "body", "description": "Short display name."},
    {"name": "principle_statement", "type": "string", "required": True, "in": "body", "description": "The principle itself."},
    {"name": "rationale", "type": "string", "required": False, "in": "body", "description": "Why this principle exists."},
    {"name": "priority", "type": "string", "required": False, "in": "body", "description": "One of: low, medium, high."},
    {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this Guiding Principle."},
]

_OPEN_QUESTION_CREATE_UPDATE_PARAMS = [
    {"name": "question", "type": "string", "required": True, "in": "body", "description": "The question itself."},
    {"name": "context", "type": "string", "required": False, "in": "body", "description": "Background context."},
    {"name": "evidence", "type": "string", "required": False, "in": "body", "description": "Supporting evidence."},
    {"name": "priority", "type": "string", "required": False, "in": "body", "description": "One of: low, medium, high."},
    {"name": "due_date", "type": "string", "required": False, "in": "body", "description": "ISO date this question is due for resolution."},
]


def _build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Builds this module's full `mcp_tools` tuple (Phase 6) — a plain
    function (called once, at import time, below) rather than a literal
    tuple, so the repetitive per-artefact shapes above can be assembled
    with ordinary Python rather than duplicated by hand five times over.
    See `module.py`'s own docstring for the categories this covers and
    `service.py`'s "MCP tools and the `require_ai_approvals_enabled` gate"
    section for the five specially-gated tools at the end."""
    tools: list[McpToolDefinition] = [
        # --- Reads: list/get for all five artefact types ---------------
        McpToolDefinition(
            name="list_strategies", description="Lists a project's Strategies.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_strategy", description="Fetches a single Strategy.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies/{{strategy_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("strategy", "The Strategy to fetch.")],
        ),
        McpToolDefinition(
            name="list_future_states", description="Lists a project's Future States.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_future_state", description="Fetches a single Future State.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states/{{future_state_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("future_state", "The Future State to fetch.")],
        ),
        McpToolDefinition(
            name="list_pain_points", description="Lists a project's Pain Points.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_pain_point", description="Fetches a single Pain Point.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point to fetch.")],
        ),
        McpToolDefinition(
            name="list_guiding_principles", description="Lists a project's Guiding Principles.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_guiding_principle", description="Fetches a single Guiding Principle.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles/{{guiding_principle_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("guiding_principle", "The Guiding Principle to fetch.")],
        ),
        McpToolDefinition(
            name="list_open_questions", description="Lists a project's Open Questions.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_open_question", description="Fetches a single Open Question.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions/{{open_question_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("open_question", "The Open Question to fetch.")],
        ),
        # --- Reads: relationships ---------------------------------------
        McpToolDefinition(
            name="list_strategy_relationships", description="Lists a Strategy's relationship links.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies/{{strategy_id}}/relationships",
            params=[_PROJECT_ID_PARAM, _id_param("strategy", "The Strategy whose relationships to list.")],
        ),
        McpToolDefinition(
            name="list_future_state_relationships", description="Lists a Future State's relationship links.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states/{{future_state_id}}/relationships",
            params=[_PROJECT_ID_PARAM, _id_param("future_state", "The Future State whose relationships to list.")],
        ),
        McpToolDefinition(
            name="list_pain_point_relationships", description="Lists a Pain Point's relationship links.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}/relationships",
            params=[_PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point whose relationships to list.")],
        ),
        McpToolDefinition(
            name="list_guiding_principle_relationships", description="Lists a Guiding Principle's relationship links.",
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles/{{guiding_principle_id}}/relationships",
            params=[_PROJECT_ID_PARAM, _id_param("guiding_principle", "The Guiding Principle whose relationships to list.")],
        ),
        McpToolDefinition(
            name="list_open_question_relationships", description="Lists an Open Question's relationship links.",
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions/{{open_question_id}}/relationships",
            params=[_PROJECT_ID_PARAM, _id_param("open_question", "The Open Question whose relationships to list.")],
        ),
        # --- Writes: create/update -----------------------------------------
        McpToolDefinition(
            name="create_strategy", description="Creates a new Strategy in Draft status.", method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies",
            params=[_PROJECT_ID_PARAM, *_STRATEGY_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="update_strategy", description="Replaces a Strategy's content, creating a new version.", method="PUT",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies/{{strategy_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("strategy", "The Strategy to update."), *_STRATEGY_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="create_future_state", description="Creates a new Future State in Draft status.", method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states",
            params=[_PROJECT_ID_PARAM, *_FUTURE_STATE_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="update_future_state", description="Replaces a Future State's content, creating a new version.",
            method="PUT", path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states/{{future_state_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("future_state", "The Future State to update."), *_FUTURE_STATE_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="create_pain_point", description="Submits a new Pain Point (any project member may do this).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points",
            params=[_PROJECT_ID_PARAM, *_PAIN_POINT_CREATE_PARAMS],
        ),
        McpToolDefinition(
            name="update_pain_point", description="Updates a Pain Point's content.", method="PUT",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point to update."), *_PAIN_POINT_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="list_pain_point_scores",
            description="Lists every Pain Point's persona-rolled-up score and Blocker flag under a scoring model.",
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-point-scores",
            params=[_PROJECT_ID_PARAM, *_PAIN_POINT_SCORING_QUERY_PARAMS],
        ),
        McpToolDefinition(
            name="get_pain_point_scores",
            description="Fetches a Pain Point's per-persona scores, roll-up and the personas it can be scored against.",
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}/scores",
            params=[_PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point to read scores for."),
                    *_PAIN_POINT_SCORING_QUERY_PARAMS],
        ),
        McpToolDefinition(
            name="set_pain_point_scores",
            description=(
                "Replaces a Pain Point's scores. Each entry is {target_id (a persona id, or null for all "
                "personas), severity_level_id, frequency_level_id, confidence_level_id}; level ids come from "
                "the project's pain_point scoring scheme. Use all-personas OR per-persona entries, not both."
            ),
            method="PUT", path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}/scores",
            params=[
                _PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point to score."),
                {"name": "scores", "type": "array", "required": True, "in": "body",
                 "description": "The full replacement list of score entries (empty clears all scores)."},
            ],
        ),
        McpToolDefinition(
            name="create_guiding_principle", description="Creates a new Guiding Principle in Draft status.",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles",
            params=[_PROJECT_ID_PARAM, *_GUIDING_PRINCIPLE_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="update_guiding_principle", description="Replaces a Guiding Principle's content, creating a new version.",
            method="PUT", path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles/{{guiding_principle_id}}",
            params=[_PROJECT_ID_PARAM, _id_param("guiding_principle", "The Guiding Principle to update."), *_GUIDING_PRINCIPLE_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="create_open_question", description="Submits a new Open Question (any project member may do this).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions",
            params=[_PROJECT_ID_PARAM, *_OPEN_QUESTION_CREATE_UPDATE_PARAMS],
        ),
        McpToolDefinition(
            name="update_open_question", description="Updates an Open Question's content.", method="PUT",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions/{{open_question_id}}",
            params=[
                _PROJECT_ID_PARAM, _id_param("open_question", "The Open Question to update."),
                *_OPEN_QUESTION_CREATE_UPDATE_PARAMS,
                {"name": "owner_id", "type": "uuid", "required": False, "in": "body", "description": "User who owns this Open Question."},
            ],
        ),
        # --- Writes: relationships and supersessions ------------------------
        McpToolDefinition(
            name="create_strategy_relationship",
            description="Creates a typed relationship from a Strategy to another artefact (kind determines the target type).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies/{{strategy_id}}/relationships",
            params=[
                _PROJECT_ID_PARAM, _id_param("strategy", "The Strategy that is the relationship's source."),
                {"name": "kind", "type": "string", "required": True, "in": "body",
                 "description": "One of: drives_requirement, defines_future_state, requires_resolution_of_open_question, contributes_to_strategy."},
                {"name": "target_id", "type": "uuid", "required": True, "in": "body", "description": "The target artefact's id."},
            ],
        ),
        McpToolDefinition(
            name="create_strategy_supersession",
            description="Records that this Strategy supersedes another (in the same organisation), transitioning the old one to Superseded.",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/strategies/{{strategy_id}}/supersessions",
            params=[
                _PROJECT_ID_PARAM, _id_param("strategy", "The new (superseding) Strategy."),
                {"name": "old_strategy_id", "type": "uuid", "required": True, "in": "body", "description": "The Strategy being superseded."},
                _comment_param("Optional comment recorded on the superseded Strategy's transition."),
            ],
        ),
        McpToolDefinition(
            name="create_future_state_relationship",
            description="Creates an untyped 'related to' relationship from a Future State to another artefact (kind determines the target type).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states/{{future_state_id}}/relationships",
            params=[
                _PROJECT_ID_PARAM, _id_param("future_state", "The Future State that is the relationship's source."),
                {"name": "kind", "type": "string", "required": True, "in": "body",
                 "description": "One of: related_to_pain_point, related_to_requirement, related_to_guiding_principle."},
                {"name": "target_id", "type": "uuid", "required": True, "in": "body", "description": "The target artefact's id."},
            ],
        ),
        McpToolDefinition(
            name="create_future_state_supersession",
            description="Records that this Future State supersedes another (in the same organisation), transitioning the old one to Superseded.",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/future-states/{{future_state_id}}/supersessions",
            params=[
                _PROJECT_ID_PARAM, _id_param("future_state", "The new (superseding) Future State."),
                {"name": "old_future_state_id", "type": "uuid", "required": True, "in": "body", "description": "The Future State being superseded."},
                _comment_param("Optional comment recorded on the superseded Future State's transition."),
            ],
        ),
        McpToolDefinition(
            name="create_pain_point_relationship",
            description="Creates a typed relationship from a Pain Point to another artefact (kind determines the target type).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/pain-points/{{pain_point_id}}/relationships",
            params=[
                _PROJECT_ID_PARAM, _id_param("pain_point", "The Pain Point that is the relationship's source."),
                {"name": "kind", "type": "string", "required": True, "in": "body",
                 "description": "One of: drives_strategy, motivates_requirement, raises_open_question, related_to_future_state, duplicate_of."},
                {"name": "target_id", "type": "uuid", "required": True, "in": "body", "description": "The target artefact's id."},
            ],
        ),
        McpToolDefinition(
            name="create_guiding_principle_relationship",
            description="Creates a typed relationship from a Guiding Principle to another artefact (kind determines the target type).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles/{{guiding_principle_id}}/relationships",
            params=[
                _PROJECT_ID_PARAM, _id_param("guiding_principle", "The Guiding Principle that is the relationship's source."),
                {"name": "kind", "type": "string", "required": True, "in": "body",
                 "description": "One of: supports_strategy, informs_requirement."},
                {"name": "target_id", "type": "uuid", "required": True, "in": "body", "description": "The target artefact's id."},
            ],
        ),
        McpToolDefinition(
            name="create_guiding_principle_supersession",
            description="Records that this Guiding Principle supersedes another (in the same organisation), transitioning the old one to Superseded.",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/guiding-principles/{{guiding_principle_id}}/supersessions",
            params=[
                _PROJECT_ID_PARAM, _id_param("guiding_principle", "The new (superseding) Guiding Principle."),
                {"name": "old_guiding_principle_id", "type": "uuid", "required": True, "in": "body",
                 "description": "The Guiding Principle being superseded."},
                _comment_param("Optional comment recorded on the superseded Guiding Principle's transition."),
            ],
        ),
        McpToolDefinition(
            name="create_open_question_relationship",
            description="Creates an untyped 'related to' relationship from an Open Question to another artefact (kind determines the target type).",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/open-questions/{{open_question_id}}/relationships",
            params=[
                _PROJECT_ID_PARAM, _id_param("open_question", "The Open Question that is the relationship's source."),
                {"name": "kind", "type": "string", "required": True, "in": "body",
                 "description": "One of: related_to_strategy, related_to_requirement."},
                {"name": "target_id", "type": "uuid", "required": True, "in": "body", "description": "The target artefact's id."},
            ],
        ),
        # --- Writes: plain (non-gated) lifecycle transitions ----------------
        _lifecycle_tool(
            "propose_strategy", "Moves a Strategy from Draft to Proposed.", "strategy", "propose",
            "The Strategy to propose.",
        ),
        _lifecycle_tool(
            "submit_strategy_for_review", "Moves a Strategy from Proposed to Under Review.", "strategy",
            "submit-for-review", "The Strategy to submit.",
        ),
        _lifecycle_tool(
            "send_strategy_back", "Sends a Strategy back to Draft for rework.", "strategy", "send-back",
            "The Strategy to send back.", comment_required=True,
            comment_description="Required: why this Strategy is being sent back.",
        ),
        _lifecycle_tool(
            "supersede_strategy",
            "Marks a Strategy Superseded (plain status transition, no relationship recorded — use "
            "create_strategy_supersession to also record which Strategy replaces it).",
            "strategy", "supersede", "The Strategy to supersede.",
        ),
        _lifecycle_tool("retire_strategy", "Retires a Strategy.", "strategy", "retire", "The Strategy to retire."),
        _lifecycle_tool(
            "activate_strategy", "Activates an approved Strategy.", "strategy", "activate",
            "The Strategy to activate.",
        ),
        _lifecycle_tool(
            "propose_future_state", "Moves a Future State from Draft to Proposed.", "future_state", "propose",
            "The Future State to propose.",
        ),
        _lifecycle_tool(
            "submit_future_state_for_review", "Moves a Future State from Proposed to Under Review.",
            "future_state", "submit-for-review", "The Future State to submit.",
        ),
        _lifecycle_tool(
            "send_future_state_back", "Sends a Future State back to Draft for rework.", "future_state",
            "send-back", "The Future State to send back.", comment_required=True,
            comment_description="Required: why this Future State is being sent back.",
        ),
        _lifecycle_tool(
            "supersede_future_state",
            "Marks a Future State Superseded (plain status transition — use create_future_state_supersession "
            "to also record which Future State replaces it).",
            "future_state", "supersede", "The Future State to supersede.",
        ),
        _lifecycle_tool(
            "retire_future_state", "Retires a Future State.", "future_state", "retire",
            "The Future State to retire.",
        ),
        _lifecycle_tool(
            "activate_future_state", "Activates an approved Future State.", "future_state", "activate",
            "The Future State to activate.",
        ),
        _lifecycle_tool(
            "propose_guiding_principle", "Moves a Guiding Principle from Draft to Proposed.",
            "guiding_principle", "propose", "The Guiding Principle to propose.",
        ),
        _lifecycle_tool(
            "send_guiding_principle_back", "Sends a Guiding Principle back to Draft for rework.",
            "guiding_principle", "send-back", "The Guiding Principle to send back.", comment_required=True,
            comment_description="Required: why this Guiding Principle is being sent back.",
        ),
        _lifecycle_tool(
            "approve_guiding_principle", "Approves a proposed Guiding Principle (Proposed -> Approved).",
            "guiding_principle", "approve", "The Guiding Principle to approve.",
        ),
        _lifecycle_tool(
            "triage_pain_point", "Moves a Pain Point from Submitted to Triaged.", "pain_point", "triage",
            "The Pain Point to triage.",
        ),
        _lifecycle_tool(
            "reject_pain_point", "Rejects a Pain Point.", "pain_point", "reject", "The Pain Point to reject.",
            comment_required=True, comment_description="Required: why this Pain Point is being rejected.",
        ),
        _lifecycle_tool(
            "mark_pain_point_duplicate", "Marks a Pain Point a duplicate of another.", "pain_point",
            "mark-duplicate", "The Pain Point to mark duplicate.", comment_required=True,
            comment_description="Required: which Pain Point this duplicates.",
        ),
        _lifecycle_tool(
            "accept_pain_point", "Accepts a triaged Pain Point.", "pain_point", "accept",
            "The Pain Point to accept.",
        ),
        _lifecycle_tool(
            "address_pain_point", "Marks an accepted Pain Point as addressed.", "pain_point", "address",
            "The Pain Point to mark addressed.",
        ),
        _lifecycle_tool("close_pain_point", "Closes an addressed Pain Point.", "pain_point", "close", "The Pain Point to close."),
        _lifecycle_tool(
            "investigate_open_question", "Moves an Open Question from Open to Investigating.", "open_question",
            "investigate", "The Open Question to investigate.",
        ),
        _lifecycle_tool(
            "mark_open_question_ready_for_decision", "Moves an Open Question to Ready for Decision.",
            "open_question", "mark-ready-for-decision", "The Open Question to mark ready.",
        ),
        _lifecycle_tool(
            "withdraw_open_question", "Withdraws an Open Question.", "open_question", "withdraw",
            "The Open Question to withdraw.", comment_required=True,
            comment_description="Required: why this Open Question is being withdrawn.",
        ),
        # --- Writes: approve/decide-tier tools, gated by require_ai_approvals_enabled when reached via MCP ---
        _lifecycle_tool(
            "approve_strategy", "Formally approves a Strategy (Under Review -> Approved).", "strategy",
            "approve", "The Strategy to approve.",
        ),
        _lifecycle_tool(
            "approve_future_state", "Formally approves a Future State (Under Review -> Approved).",
            "future_state", "approve", "The Future State to approve.",
        ),
        _lifecycle_tool(
            "activate_guiding_principle", "Activates an approved Guiding Principle.", "guiding_principle",
            "activate", "The Guiding Principle to activate.",
        ),
        _lifecycle_tool(
            "retire_guiding_principle", "Retires a Guiding Principle.", "guiding_principle", "retire",
            "The Guiding Principle to retire.",
        ),
        _lifecycle_tool(
            "resolve_open_question", "Marks an Open Question Resolved (Ready for Decision -> Resolved).",
            "open_question", "resolve", "The Open Question to resolve.",
        ),
    ]
    # --- Reports R1–R9 (Phases 12/12b): read-only JSON, generated from `REPORT_DEFINITIONS`. The
    # organisation-wide variants are not declared (org-scoped endpoints have no MCP-safe path, as for
    # the org-scoped artefact endpoints above).
    tools += report_mcp_tools(REPORT_DEFINITIONS, project_router_prefix=_PROJECT_ROUTER_PREFIX)
    return tuple(tools)


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every Strategy,
    Future State, Pain Point, Guiding Principle and Open Question in the
    organisation, org-scoped or in one of its projects, for org deletion's
    polymorphic cleanup."""
    from sqlalchemy import or_, select

    from app.models.project import Project
    from app.modules.context_strategy.models import FutureState, GuidingPrinciple, OpenQuestion, PainPoint, Strategy

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    ids: set[UUID] = set()
    for model in (Strategy, FutureState, GuidingPrinciple):
        ids.update(db.scalars(select(model.id).where(
            or_(model.organization_id == organization_id, model.project_id.in_(project_ids))
        )).all())
    for model in (PainPoint, OpenQuestion):
        ids.update(db.scalars(select(model.id).where(model.project_id.in_(project_ids))).all())
    return ids


# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


MODULE_DEFINITION = ModuleDefinition(
    key=CONTEXT_STRATEGY_MODULE_KEY,
    name="Context & Strategy",
    description=(
        "Record organisation and project Strategy — objective, current/desired future state, rationale, "
        "expected outcomes, constraints, and measures of success — plus a standalone Future State artefact "
        "(current state, desired state, target date, outcomes, success measures, constraints, assumptions) — "
        "both with a formal review/approval lifecycle. Also records project-scoped Pain Points (problems, "
        "deficiencies, and improvement opportunities) with a configurable, org-shared type vocabulary and a "
        "branching triage lifecycle, and organisation- or project-scoped Guiding Principles (name, principle "
        "statement, rationale, priority, owner) with their own review/approval lifecycle and full version "
        "history, so future Decisions can be checked against them. Also records project-scoped Open Questions "
        "(question, context, owner, priority, due/review date, evidence) with a branching investigation "
        "lifecycle (Open -> Investigating -> {Withdrawn | Ready for Decision -> {Resolved | Withdrawn}}), "
        "reserving (but not yet wiring) the eventual 'resolved by' relationship to a Decision Management "
        "Decision."
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
    # Phase 7.1 (Strategy frontend, 2026-09-29): this module's first
    # frontend_manifest — only the Strategy nav entry existed at first. Phase
    # 0 Q7 (docs/plans/module-01-context-and-strategy-plan.md) requires five
    # separate top-level nav-rail entries, one per artefact type, not one
    # grouped entry with tabs — `ModuleFrontendManifest.additional_nav_
    # entries` (the generic multi-entry extension point built as part of
    # Phase 7.1, see docs/decisions.md) is where Phase 7.2-7.5 each append
    # their own artefact type's entry as its own frontend ships. Phase 7.2
    # (Future State, 2026-09-29) added the second entry below; Phase 7.3
    # (Pain Point, 2026-09-29) added the third; Phase 7.4 (Guiding Principle,
    # 2026-09-29) added the fourth; Phase 7.5 (Open Question, 2026-09-29)
    # appends the fifth and last. `nav_path` uses each artefact's own sub-route naming
    # (matching `router.py`/`project_router.py`), not the bare module mount
    # point, since each entry needs its own distinct sub-path alongside the
    # others. Pain Point's own type-vocabulary admin surfaces (Phase 0 Q3)
    # are not nav-rail entries at all — they render on Org/Project Admin via
    # `orgAdminSections`/`projectAdminSections` (`frontend/src/modules/
    # context_strategy/module.ts`), which this manifest mechanism doesn't
    # cover.
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Strategy",
        nav_path=f"/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}/strategies",
        nav_icon="compass",
        additional_nav_entries=(
            ModuleNavEntry(
                nav_label="Future State",
                nav_path=f"/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}/future-states",
                nav_icon="telescope",
            ),
            ModuleNavEntry(
                nav_label="Pain Point",
                nav_path=f"/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}/pain-points",
                nav_icon="alert-triangle",
            ),
            ModuleNavEntry(
                nav_label="Guiding Principle",
                nav_path=f"/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}/guiding-principles",
                nav_icon="anchor",
            ),
            ModuleNavEntry(
                nav_label="Open Question",
                nav_path=f"/projects/{{project_id}}/modules/{CONTEXT_STRATEGY_MODULE_KEY}/open-questions",
                nav_icon="circle-help",
            ),
        ),
    ),
    artefact_types=(
        STRATEGY_ARTEFACT_TYPE, FUTURE_STATE_ARTEFACT_TYPE, PAIN_POINT_ARTEFACT_TYPE, GUIDING_PRINCIPLE_ARTEFACT_TYPE,
        OPEN_QUESTION_ARTEFACT_TYPE,
    ),
    artefact_ids_in_organization=_artefact_ids_in_organization,
    reports=REPORT_DEFINITIONS,
    artefact_summary_providers=ARTEFACT_SUMMARY_PROVIDERS,
    artefact_type_labels=ARTEFACT_TYPE_LABELS,
    link_type_seeds=LINK_TYPE_SEEDS,
    # Module 0 (Platform Foundations) Phase 4: each of Context & Strategy's
    # five artefacts declares its own sub-component key only once its own
    # phase lands (Phase 1 registered "strategy", Phase 2 "future_state",
    # Phase 3 "pain_point", Phase 4 "guiding_principle", this is Phase 5's
    # own "open_question" — the last of the five).
    sub_components=(
        ModuleSubComponentDefinition(key="strategy", name="Strategy", default_enabled=True),
        ModuleSubComponentDefinition(key="future_state", name="Future State", default_enabled=True),
        ModuleSubComponentDefinition(key="pain_point", name="Pain Points", default_enabled=True),
        ModuleSubComponentDefinition(key="guiding_principle", name="Guiding Principles", default_enabled=True),
        ModuleSubComponentDefinition(key="open_question", name="Open Questions", default_enabled=True),
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
                "plus any org-added types) — add/rename/disable/remove, per source overview §6.2 — and its Pain "
                "Point scoring configuration (Severity/Frequency/Confidence levels, default model, rating bands). "
                "Organisation-scoped; does not by itself grant any project-level Pain Point Manager capability."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="org_reports_viewer",
            name="Organisation Reports Viewer",
            description=(
                "May run the organisation-wide Context & Strategy reports (Pain Point prioritisation, coverage, "
                "Open Question register, summary pack, upgrade drivers). Org admins hold it by default. It does "
                "not widen project access: a report still covers only projects the caller can already read."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="guiding_principle_owner",
            name="Guiding Principle Owner",
            description=(
                "Creates and manages project-scoped Guiding Principle records — the module's management-level "
                "role for a project Guiding Principle (docs/plans/module-01-context-and-strategy-plan.md Phase 4)."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="guiding_principle_approver",
            name="Guiding Principle Approver",
            description="May approve, activate, supersede, and retire project-scoped Guiding Principle records.",
            scope="project",
            # Fine-Grained Access Control: a holder of this flat module role gets the equivalent
            # unscoped `(guiding_principle, approve_baseline)` permission atom via `get_effective_permissions`,
            # mirroring `strategy_approver`/`future_state_approver` above.
            permissions=(_GUIDING_PRINCIPLE_APPROVE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_guiding_principle_owner",
            name="Organisation Guiding Principle Owner",
            description=(
                "Creates and manages organisation-scoped Guiding Principle records — the org-scoped equivalent "
                "of Guiding Principle Owner."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="org_guiding_principle_approver",
            name="Organisation Guiding Principle Approver",
            description="May approve, activate, supersede, and retire organisation-scoped Guiding Principle records.",
            scope="org",
            permissions=(_GUIDING_PRINCIPLE_APPROVE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="open_question_owner",
            name="Open Question Owner",
            description=(
                "Assigns, prioritises, edits, and changes the status of Open Questions — including withdrawing "
                "them — but does not itself resolve one through a Decision (docs/plans/module-01-context-and-"
                "strategy-plan.md Phase 5) — source overview §9.4's 'Question Owner / Project Manager' tier. "
                "Project-scoped only; Open Question has no organisation scope."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="open_question_resolver",
            name="Open Question Resolver",
            description=(
                "May mark an Open Question Resolved (§9.4's 'Decision Maker: Resolve through a Decision' tier) — "
                "deliberately a separate role from Open Question Owner, since source overview §9.4 names this as "
                "its own distinct persona rather than folding it into the Owner/Project Manager tier the way Pain "
                "Point's single-role model does. Project-scoped only."
            ),
            scope="project",
            # Fine-Grained Access Control: a holder of this flat module role gets the equivalent unscoped
            # `(open_question, approve_baseline)` permission atom via `get_effective_permissions`, mirroring
            # `pain_point_manager`/`strategy_approver` above.
            permissions=(_OPEN_QUESTION_RESOLVE_PERMISSION,),
        ),
    ),
    mcp_guidance=_MCP_GUIDANCE,
    mcp_tools=_build_mcp_tools(),
    scoring_schemes=(PAIN_POINT_SCORING_SCHEME,),
)
