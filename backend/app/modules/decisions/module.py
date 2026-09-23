"""
Module: modules.decisions.module

Registers the Decision Management module into the modular feature
system's registry (docs/plans/module-04-decision-management-plan.md
Phase 1) via `MODULE_DEFINITION`, mirroring `app.modules.compliance.
module`'s own registration shape.

`decision_owner` (project-scoped) and `decision_approver` (project-scoped,
the Phase 0 addendum Q2/2a "simple placeholder role") are declared here as
module-contributed roles, not additions to `ProjectRole`.

Phase 1 was data model only: `get_router()` returned `None` (no HTTP
endpoints yet), `implemented=False` and `default_enabled=False` reflected
that nothing was usable by an end user yet.

`on_project_created` seeds this project's default `DecisionTypeDefinition`
rows for a *root* project (not gated on module enablement, mirroring
Compliance's own `on_org_created` seeding). A project with a parent is
deliberately left unseeded as of Phase 9 (2026-09-22): Decision Types now
have the same hierarchical fallback `ActionTypeDefinition` already has
(`service.resolve_effective_decision_types`), and a child needs to start
empty for that fallback to have anything to do — exact mirror of
`routers.projects.create_project`'s own root-only `seed_action_types` gate.
`org_creation_choices` / `on_org_created_with_choices` are this module's
first use of the org-creation-choices extension point
(`app.modules.registry`) — the three seeded ADR template packs, opted into
per-organisation rather than always seeded (Phase 0 addendum Q1).

Phase 4 (docs/plans/module-04-decision-management-plan.md — Backend API +
audit logging) adds this module's first real HTTP surface: `get_router()`
now returns the org-scoped `router.py` (Decision Template CRUD), and
`get_project_router()` (a new field this phase is the first to populate)
returns `project_router.py` (Decision CRUD, lifecycle transitions,
relationships, comments, files, Decision Type management) — mirroring
`app.modules.compliance.module`'s own `get_router()`/`get_project_router()`
split shape, including the lazy, inside-the-function imports (avoids any
import-cycle risk with this module's own registration, same reasoning as
every other module). `resolve_file_owner_project_id` is also added, for
the same reason Compliance's own Phase 8 added one: so the core, module-
agnostic `GET /api/v1/files/{id}` download endpoint can authorize a
`DecisionFile`/`DecisionCommentFile` attachment without importing anything
from this module directly.

`implemented` flips to `True` this phase — Phase 4's own testing bar
(full backend suite green, `ruff check` clean, new endpoint coverage) is
met (see the plan's "Phase 4 notes" section) and a real, working API now
exists, even though no frontend does yet (Phase 5). `default_enabled`
stays `False`: an organisation must still opt in explicitly until Phase 5
ships a UI to actually use it. **Decided by: Agent** — see Phase 4 notes.
No MCP tools are declared this phase either — nothing in this phase's own
scope calls for one, and this module's mutating actions (create/approve/
reject/supersede) are exactly the kind of accountable-human governance
actions Compliance's own module.py has repeatedly kept off the MCP tool
surface by default (see that module's Phase 9 notes); a future phase can
add narrow, read-only tools the same deliberate way Compliance did, if a
real need for one arises.

Phase 5 (docs/plans/module-04-decision-management-plan.md — Frontend) adds
`frontend_manifest` (Tier A — `frontend/src/modules/decisions/module.ts`
registers the matching route/nav entry, `ProjectDecisionsPage`), so the
project nav rail actually gets a "Decisions" entry once an organisation
enables this module. `default_enabled` stays `False`; an organisation still
opts in explicitly. `nav_path` mirrors Compliance's own `"{project_id}"`
placeholder convention, interpolated server-side before being sent to the
frontend (`routers/projects.py::list_project_enabled_modules`).

Phase 4 addendum (2026-09-21): Phase 4's original text above ("No MCP tools
are declared this phase either...") is reversed — the user explicitly asked,
this session, for this module to get MCP tools (**Decided by: User**). What
was actually added is narrower than a full reversal, though: seven
read-only (`GET`) tools — `list_decision_types`, `list_decisions`,
`get_decision`, `list_decision_relationships`, `list_decision_comments`,
`list_decision_files` (all project-scoped, `_PROJECT_ROUTER_PREFIX`), and
`list_decision_templates` (org-scoped, `_ROUTER_PREFIX`) — with zero
mutating tools. `project_router.py`'s `approve_decision_endpoint`/`reject_
decision_endpoint` were marked `APPROVAL_ACTION_ROUTE_EXTRA`
(`app.modules.registry`) at this point, as defense-in-depth against a
future tool declaration resolving to either route.

2026-09-22 — approve/reject given the same generalized AI-approval gate as
Compliance (**Decided by: User** — explicit confirmation, "Yes, apply the
same treatment," in direct response to being asked, following on from
docs/decisions.md's "Compliance MCP write tools + generalized AI approval
gate" entry, which had left this module's `approve_decision`/`reject_
decision` as the one architecturally-identical case still excluded). Two
more tools are now declared below — `approve_decision`/`reject_decision` —
and `APPROVAL_ACTION_ROUTE_EXTRA` was removed from both routes: reached
through MCP, each now additionally requires `require_ai_approvals_enabled`
(this project's and its organisation's `allow_ai_approvals` both true),
exactly mirroring `modules.compliance.project_router.approve_requirement`/
`reject_requirement`. See `project_router.py`'s `approve_decision_endpoint`/
`reject_decision_endpoint` docstrings and docs/decisions.md's "Decision
Management MCP approval gate" entry for the full account. This closes the
inconsistency the compliance entry flagged; create/propose/submit-for-
review/supersede/comment/attach-file remain undeclared — the first two
don't decide anything (mirroring Compliance's own `submit-for-approval`
treatment) and the rest are ordinary CRUD/collaboration actions this
addendum never asked to expand, not approval-type actions this gate
concerns.

Fine-Grained Access Control Phase 1 (2026-09-23, `docs/plans/core-fine-
grained-access-control-plan.md`): registers `subtype_providers={
DECISION_ARTEFACT_TYPE: _decision_subtypes}`, the first (and, as of this
phase, only) module to populate that new `ModuleDefinition` field — see
`_decision_subtypes`'s own docstring and `service.list_decision_type_
names_for_organization` for what it returns. This is Phase 0 Q3's
resolution of the request that originally motivated the whole plan
("certain people only do some types of decisions"): Phase 5 will express
that as a `require_permission(decision, approve_baseline, subtype=<type>)`
check rather than a bespoke field on `DecisionTypeDefinition` — no change
to this module's own approval logic lands until then.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE, DECISION_TEMPLATE_PACKS
from app.modules.registry import (
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleRoleDefinition,
    OrgCreationChoiceOption,
)

DECISIONS_MODULE_KEY = "decisions"
_ROUTER_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{DECISIONS_MODULE_KEY}"
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{DECISIONS_MODULE_KEY}"


def get_router() -> APIRouter | None:
    """This module's org-scoped `APIRouter` (Phase 4 — Decision Template
    CRUD). Imported inside the function body, not at module top-level, to
    avoid any import-cycle risk with this module's own registration (see
    this module's own docstring)."""
    from app.modules.decisions.router import router as decisions_router

    return decisions_router


def get_project_router() -> APIRouter | None:
    """This module's project-scoped `APIRouter` (Phase 4 — Decision CRUD,
    lifecycle transitions, relationships, comments, files, Decision Type
    management). Imported inside the function body for the same import-
    cycle reason as `get_router()`."""
    from app.modules.decisions.project_router import router as decisions_project_router

    return decisions_project_router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook
    (Phase 4) — imported lazily for the same import-cycle reason as
    `get_router()`."""
    from app.modules.decisions.service import resolve_decision_file_project_id

    return resolve_decision_file_project_id(db, file_id)


def _decision_subtypes(db: Session, organization_id: uuid.UUID) -> list[str]:
    """This module's `ModuleDefinition.subtype_providers[DECISION_ARTEFACT_
    TYPE]` hook — Fine-Grained Access Control (`docs/plans/core-fine-
    grained-access-control-plan.md` Phase 1's "one piece of this phase that
    has a real consumer on day one"). Imported lazily for the same import-
    cycle reason as this module's other hook functions."""
    from app.modules.decisions.service import list_decision_type_names_for_organization

    return list_decision_type_names_for_organization(db, organization_id)


def _seed_new_project(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """This module's `ModuleDefinition.on_project_created` hook. Imported
    lazily for the same import-cycle reason `app.modules.compliance.
    module`'s own hook functions are.

    Only seeds a *root* project (`parent_project_id is None`) — Phase 9
    (2026-09-22): now that Decision Types have the same hierarchical
    fallback `ActionTypeDefinition` already has (`service.resolve_
    effective_decision_types`), a child project must start with none of
    its own so the fallback actually has something to do, exact mirror of
    `routers.projects.create_project`'s own `if payload.parent_project_id
    is None: seed_action_types(...)` gate."""
    if project.parent_project_id is not None:
        return
    from app.modules.decisions.service import seed_decision_types

    seed_decision_types(db, project.id)


def _seed_org_templates(db: Session, organization_id: uuid.UUID, selected_keys: frozenset[str]) -> None:
    """This module's `ModuleDefinition.on_org_created_with_choices` hook.
    Imported lazily for the same import-cycle reason as `_seed_new_project`."""
    from app.modules.decisions.service import seed_decision_templates

    seed_decision_templates(db, organization_id, selected_keys)


_ORG_CREATION_CHOICES = tuple(
    OrgCreationChoiceOption(
        key=pack.choice_key,
        group_label="Decision Templates",
        label=pack.name,
        description=pack.description,
        default_selected=True,
    )
    for pack in DECISION_TEMPLATE_PACKS
)


MODULE_DEFINITION = ModuleDefinition(
    key=DECISIONS_MODULE_KEY,
    name="Decision Management",
    description=(
        "Record, approve, and supersede formal decisions made during a project's lifecycle — architecture, "
        "design, engineering, strategy, and operational."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    subtype_providers={DECISION_ARTEFACT_TYPE: _decision_subtypes},
    models_import_path="app.modules.decisions.models",
    migrations_dir="app/modules/decisions/migrations",
    on_project_created=_seed_new_project,
    org_creation_choices=_ORG_CREATION_CHOICES,
    on_org_created_with_choices=_seed_org_templates,
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Decisions",
        nav_path=f"/projects/{{project_id}}/modules/{DECISIONS_MODULE_KEY}",
    ),
    artefact_types=(DECISION_ARTEFACT_TYPE,),
    roles=(
        ModuleRoleDefinition(
            role_key="decision_owner",
            name="Decision Owner",
            description=(
                "Creates and manages Decision records and this project's Decision Types — the module's "
                "management-level role (docs/plans/module-04-decision-management-plan.md Phase 1)."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="decision_approver",
            name="Decision Approver",
            description=(
                "May approve, reject, and supersede Decisions in this project — the Phase 0 addendum's "
                "'simple placeholder role' for approval authority, expected to be superseded by a future "
                "Governance-module policy mechanism rather than this module building its own."
            ),
            scope="project",
        ),
    ),
    mcp_tools=(
        McpToolDefinition(
            name="list_decision_types",
            description="Lists the Decision Types configured for a project (e.g. Architecture, Design, Strategy).",
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/decision-types",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose Decision Types to list."},
            ],
        ),
        McpToolDefinition(
            name="list_decisions",
            description="Lists the Decision records in a project.",
            method="GET",
            path_template=_PROJECT_ROUTER_PREFIX,
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose Decisions to list."},
            ],
        ),
        McpToolDefinition(
            name="get_decision",
            description="Fetches a single Decision record, including its current status and content.",
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision to fetch."},
            ],
        ),
        McpToolDefinition(
            name="list_decision_relationships",
            description=(
                "Lists a Decision's relationship links — supersession, Decision<->Requirement "
                "(Implements/Affects), and Decision<->Decision (Depends on/Supersedes/Conflicts with)."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}/relationships",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision whose relationships to list."},
            ],
        ),
        McpToolDefinition(
            name="list_decision_comments",
            description="Lists the comments on a Decision.",
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}/comments",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision whose comments to list."},
            ],
        ),
        McpToolDefinition(
            name="list_decision_files",
            description="Lists the files directly attached to a Decision (not comment attachments).",
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}/files",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision whose attached files to list."},
            ],
        ),
        McpToolDefinition(
            name="list_decision_templates",
            description=(
                "Lists an organisation's Decision Templates (e.g. Nygard/MADR/Y-Statement ADR packs) "
                "available for use when creating a Decision."
            ),
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/templates",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation whose Decision Templates to list."},
            ],
        ),
        # --- 2026-09-22: approve/reject given the same generalized AI-approval
        # gate as Compliance's `approve_requirement`/`reject_requirement` — see
        # this module's own docstring's "2026-09-22" section. Reached through
        # MCP, each resolves to a route gated by `require_ai_approvals_enabled`
        # (declaring them here does not bypass that gate).
        McpToolDefinition(
            name="approve_decision",
            description=(
                "Formally approves a Decision (moves it from Under Review to Approved). Reached through MCP "
                "only when this project's and its organisation's AI-approval opt-in are both enabled."
            ),
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}/approve",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision to approve."},
                {"name": "comment", "type": "string", "required": False, "in": "body",
                 "description": "Optional comment explaining the approval."},
            ],
        ),
        McpToolDefinition(
            name="reject_decision",
            description=(
                "Formally rejects a Decision (a comment is required). Reached through MCP only when this "
                "project's and its organisation's AI-approval opt-in are both enabled."
            ),
            method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/{{decision_id}}/reject",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project that owns the Decision."},
                {"name": "decision_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The Decision to reject."},
                {"name": "comment", "type": "string", "required": True, "in": "body",
                 "description": "Comment explaining the rejection; the endpoint 400s if left blank."},
            ],
        ),
    ),
)
