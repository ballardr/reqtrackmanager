"""
Module: modules.decisions.module

Registers the Decision Management module into the modular feature
system's registry via `MODULE_DEFINITION`, mirroring `app.modules.compliance.
module`'s own registration shape.

`decision_owner` (project-scoped) and `decision_approver` (project-scoped,
the "simple placeholder role") are declared here as module-contributed roles,
not additions to `ProjectRole`.

`on_project_created` seeds this project's default `DecisionTypeDefinition`
rows for a *root* project (not gated on module enablement, mirroring
Compliance's own `on_org_created` seeding). A project with a parent is
deliberately left unseeded (2026-09-22): Decision Types have the same
hierarchical fallback `ActionTypeDefinition` already has
(`service.resolve_effective_decision_types`), and a child needs to start
empty for that fallback to have anything to do — exact mirror of
`routers.projects.create_project`'s own root-only `seed_action_types` gate.
`org_creation_choices` / `on_org_created_with_choices` are this module's use
of the org-creation-choices extension point (`app.modules.registry`) — the
three seeded ADR template packs, opted into per-organisation rather than
always seeded.

`get_router()` returns the org-scoped `router.py` (Decision Template CRUD),
and `get_project_router()` returns `project_router.py` (Decision CRUD,
lifecycle transitions, relationships, comments, files, Decision Type
management) — mirroring `app.modules.compliance.module`'s own
`get_router()`/`get_project_router()` split shape, including the lazy,
inside-the-function imports (avoids any import-cycle risk with this module's
own registration, same reasoning as every other module).
`resolve_file_owner_project_id` is registered for the same reason as
Compliance's: so the core, module-agnostic `GET /api/v1/files/{id}` download
endpoint can authorize a `DecisionFile`/`DecisionCommentFile` attachment
without importing anything from this module directly.

`implemented=True`; `default_enabled` stays `False`: an organisation must opt
in explicitly (**Decided by: Agent**). `frontend_manifest` (Tier A —
`frontend/src/modules/decisions/module.ts` registers the matching route/nav
entry, `ProjectDecisionsPage`) gives the project nav rail a "Decisions" entry
once an organisation enables this module. `nav_path` mirrors Compliance's own
`"{project_id}"` placeholder convention, interpolated server-side before being
sent to the frontend (`routers/projects.py::list_project_enabled_modules`).

MCP tools (**Decided by: User**, 2026-09-21): seven read-only (`GET`) tools —
`list_decision_types`, `list_decisions`, `get_decision`,
`list_decision_relationships`, `list_decision_comments`,
`list_decision_files` (all project-scoped, `_PROJECT_ROUTER_PREFIX`), and
`list_decision_templates` (org-scoped, `_ROUTER_PREFIX`).

2026-09-22 — approve/reject given the same generalized AI-approval gate as
Compliance (**Decided by: User** — explicit confirmation, "Yes, apply the
same treatment," in direct response to being asked, following on from
docs/decisions.md's "Compliance MCP write tools + generalized AI approval
gate" entry, which had left this module's `approve_decision`/`reject_decision`
as the one architecturally-identical case still excluded). Two more tools are
declared below — `approve_decision`/`reject_decision`: reached through MCP,
each additionally requires `require_ai_approvals_enabled` (this project's and
its organisation's `allow_ai_approvals` both true), exactly mirroring
`modules.compliance.project_router.approve_requirement`/`reject_requirement`.
See `project_router.py`'s `approve_decision_endpoint`/
`reject_decision_endpoint` docstrings and docs/decisions.md's "Decision
Management MCP approval gate" entry for the full account.
create/propose/submit-for-review/supersede/comment/attach-file remain
undeclared — the first two don't decide anything (mirroring Compliance's own
`submit-for-approval` treatment) and the rest are ordinary CRUD/collaboration
actions, not approval-type actions this gate concerns.

`reports=REPORT_DEFINITIONS` declares four project-level reports
(`reports.py`); the framework generates their routes (mounted by
`project_router`), catalogue entries and read-only `get_<slug>_report` MCP
tools.

`subtype_providers={DECISION_ARTEFACT_TYPE: _decision_subtypes}` is the first
(and, so far, only) population of that `ModuleDefinition` field — see
`_decision_subtypes`'s own docstring and
`service.list_decision_type_names_for_organization` for what it returns. It
answers the request that motivated Fine-Grained Access Control ("certain
people only do some types of decisions"): approval is expressed as a
`require_permission(decision, approve_baseline, subtype=<type>)` check rather
than a bespoke field on `DecisionTypeDefinition`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.decisions import export as bundle_export
from app.modules.decisions.models import Decision
from app.modules.decisions.reports import REPORT_DEFINITIONS
from app.modules.decisions.search import SEARCH_PROVIDERS
from app.modules.decisions.service import (
    DECISION_APPROVE_PERMISSION,
    DECISION_ARTEFACT_TYPE,
    DECISION_TEMPLATE_PACKS,
    LINK_TYPE_SEEDS,
)
from app.modules.registry import (
    ArtefactSummary,
    ArtefactSummaryProvider,
    BrowseLevel,
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    OrgCreationChoiceOption,
    PrincipalReference,
)
from app.services.report_framework import report_mcp_tools

DECISIONS_MODULE_KEY = "decisions"
_ROUTER_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{DECISIONS_MODULE_KEY}"
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{DECISIONS_MODULE_KEY}"


def get_router() -> APIRouter | None:
    """This module's org-scoped `APIRouter` (Decision Template
    CRUD). Imported inside the function body, not at module top-level, to
    avoid any import-cycle risk with this module's own registration (see
    this module's own docstring)."""
    from app.modules.decisions.router import router as decisions_router

    return decisions_router


def get_project_router() -> APIRouter | None:
    """This module's project-scoped `APIRouter` (Decision CRUD,
    lifecycle transitions, relationships, comments, files, Decision Type
    management). Imported inside the function body for the same import-
    cycle reason as `get_router()`."""
    from app.modules.decisions.project_router import router as decisions_project_router

    return decisions_project_router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook
 — imported lazily for the same import-cycle reason as
    `get_router()`."""
    from app.modules.decisions.service import resolve_decision_file_project_id

    return resolve_decision_file_project_id(db, file_id)


def _decision_subtypes(db: Session, organization_id: uuid.UUID) -> list[str]:
    """This module's `ModuleDefinition.subtype_providers[DECISION_ARTEFACT_
    TYPE]` hook — Fine-Grained Access Control's "real consumer on day one". Imported lazily for the same import-
    cycle reason as this module's other hook functions."""
    from app.modules.decisions.service import list_decision_type_names_for_organization

    return list_decision_type_names_for_organization(db, organization_id)


def _seed_new_project(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """This module's `ModuleDefinition.on_project_created` hook. Imported
    lazily for the same import-cycle reason `app.modules.compliance.
    module`'s own hook functions are.

    Only seeds a *root* project (`parent_project_id is None`)
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


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every Decision in the
    organisation's projects, for org deletion's polymorphic cleanup."""
    from sqlalchemy import select

    from app.modules.decisions.models import Decision

    return set(db.scalars(
        select(Decision.id).join(Project, Project.id == Decision.project_id)
        .where(Project.organization_id == organization_id)
    ).all())


def _decision_summaries(db: Session, decisions) -> list[ArtefactSummary]:
    """Summaries for `decisions`, resolving each one's decision type name (the finder's
    `decision_type` facet) in one query."""
    from sqlalchemy import select

    from app.modules.decisions.models import DecisionTypeDefinition

    type_ids = {d.decision_type_id for d in decisions}
    names = (
        dict(db.execute(select(DecisionTypeDefinition.id, DecisionTypeDefinition.name).where(
            DecisionTypeDefinition.id.in_(type_ids)
        )).all())
        if type_ids else {}
    )
    return [
        ArtefactSummary(
            id=d.id, project_id=d.project_id, label=f"{d.unique_code} {d.title}", status=d.status.value,
            is_archived=d.is_archived,
            facets={"decision_type": (str(d.decision_type_id), names.get(d.decision_type_id, ""))},
        )
        for d in decisions
    ]


def _get_decision_summary(db: Session, decision_id: UUID) -> ArtefactSummary | None:
    """`ArtefactSummaryProvider.get` for Decisions."""
    from app.modules.decisions.models import Decision

    decision = db.get(Decision, decision_id)
    return None if decision is None else _decision_summaries(db, [decision])[0]


def _get_many_decision_summaries_in_project(
    db: Session, project_id: UUID, decision_ids: Sequence[UUID]
) -> list[ArtefactSummary]:
    """`ArtefactSummaryProvider.get_many_in_project` for Decisions: the given
    decisions that belong to `project_id`, in one query."""
    from sqlalchemy import select

    from app.modules.decisions.models import Decision

    rows = db.scalars(select(Decision).where(Decision.id.in_(decision_ids), Decision.project_id == project_id)).all()
    return _decision_summaries(db, rows)


def _list_decision_summaries(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    """`ArtefactSummaryProvider.list_for_project` for Decisions (unarchived, by code)."""
    from sqlalchemy import select

    from app.modules.decisions.models import Decision

    rows = db.scalars(
        select(Decision).where(Decision.project_id == project_id, Decision.is_archived.is_(False))
        .order_by(Decision.unique_code)
    ).all()
    return _decision_summaries(db, rows)


# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


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
    org_bundle_hooks=ModuleOrgBundleHooks(export=bundle_export.export_org_data, import_=bundle_export.import_org_data),
    project_bundle_hooks=ModuleProjectBundleHooks(
        export=bundle_export.export_project_data, import_=bundle_export.import_project_data,
    ),
    org_creation_choices=_ORG_CREATION_CHOICES,
    on_org_created_with_choices=_seed_org_templates,
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Decisions",
        nav_path=f"/projects/{{project_id}}/modules/{DECISIONS_MODULE_KEY}",
        nav_icon="scale",
    ),
    artefact_types=(DECISION_ARTEFACT_TYPE,),
    artefact_ids_in_organization=_artefact_ids_in_organization,
    artefact_summary_providers={
        DECISION_ARTEFACT_TYPE: ArtefactSummaryProvider(
            get=_get_decision_summary, list_for_project=_list_decision_summaries,
            get_many_in_project=_get_many_decision_summaries_in_project,
            browse_levels=(BrowseLevel("decision_type", "Decision type"),),
        ),
    },
    search_providers=SEARCH_PROVIDERS,
    artefact_type_labels={DECISION_ARTEFACT_TYPE: "Decision"},
    link_type_seeds=LINK_TYPE_SEEDS,
    roles=(
        ModuleRoleDefinition(
            role_key="decision_owner",
            name="Decision Owner",
            description=(
                "Creates and manages Decision records and this project's Decision Types — the module's "
                "management-level role."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="decision_approver",
            name="Decision Approver",
            description=(
                "May approve, reject, and supersede Decisions in this project — the "
                "'simple placeholder role' for approval authority, expected to be superseded by a future "
                "Governance-module policy mechanism rather than this module building its own."
            ),
            scope="project",
            # Fine-Grained Access Control: a holder of this flat module role
            # gets the equivalent unscoped `(decision, approve_baseline)` permission atom via
            # `get_effective_permissions`, so `project_router.workflow`'s migration to
            # `require_permission` is a zero-behaviour-change swap for every existing
            # holder of this role.
            permissions=(DECISION_APPROVE_PERMISSION,),
        ),
    ),
    # The owner (mandatory) and decision maker (optional) may be a user or a group, so deleting a
    # group is blocked or reassigned while a Decision still names it (services.principals).
    principal_references=(
        PrincipalReference(
            model=Decision, field="owner", label="decision owners", audit_entity_type=DECISION_ARTEFACT_TYPE,
            mandatory=True,
        ),
        PrincipalReference(
            model=Decision, field="decision_maker", label="decision makers", audit_entity_type=DECISION_ARTEFACT_TYPE,
        ),
    ),
    mcp_guidance=_MCP_GUIDANCE,
    reports=REPORT_DEFINITIONS,
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
    )
    + report_mcp_tools(REPORT_DEFINITIONS, project_router_prefix=_PROJECT_ROUTER_PREFIX),
)
