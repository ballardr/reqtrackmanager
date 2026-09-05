"""
Module: modules.compliance.module

Registers the Compliance Module into the modular feature system's registry
(docs/compliance-module-plan.md Phase 5) via `MODULE_DEFINITION` — the same
module-level attribute name `app.modules.registry._discover_path_modules`
looks for on a third-party module directory, kept consistent here even
though this is a first-party module appended directly to `INSTALLED_MODULES`
(`app.modules.registry`), not path-discovered.

`compliance_manager` (org-scoped) and `compliance_officer` (project-scoped)
are declared here as module-contributed roles (module system Phase 2) —
per §3/§26's explicit requirement that Compliance's own roles be separate
from `OrgRole`/`ProjectRole`, not new enum members on either.

Phase 6 (Standards Management API, docs/compliance-module-plan.md) adds this
module's first HTTP endpoints — `get_router()` now returns a real
`APIRouter` (`app.modules.compliance.router`) mounted at
`/api/v1/orgs/{organization_id}/modules/compliance` — and its first three
MCP tools, all read-only: `compliance_list_standards`, `compliance_
get_standard_version`, `compliance_list_requirements`. No mutating tool is
declared for publish/retire — Phase 6's spec deliberately keeps the MCP
surface read-only for this module so far, mirroring `docs/mcp-server.md`'s
existing cautious default of adding write tools narrowly and deliberately
rather than by default.

Phase 7 (Project Compliance Assignment & Assessment) adds this module's
first *project*-scoped router — `get_project_router()`, a new
`ModuleDefinition` field (`app.modules.registry`) mounted at `/api/v1/
projects/{project_id}/modules/compliance` — alongside two more read-only
MCP tools whose path_templates fall under that router's own prefix instead
of `get_router()`'s: `compliance_get_project_status(project_id)` and
`compliance_list_non_compliant_requirements(project_id)`. Neither tool
takes `organization_id` — deliberately, mirroring hand-written tools like
`get_project(project_id)` — which is exactly why these two live on a
second router rather than being nested under the org-scoped one; see
`app.modules.registry`'s own docstring on `get_project_router` and
`project_router.py`'s module docstring for the full reasoning.

Phase 8 (Evidence, §13-§15) adds this module's evidence endpoints to the
same project router, one more read-only MCP tool
(`compliance_list_expiring_evidence(project_id)`), and this module's
`resolve_file_owner_project_id` hook (`app.modules.registry`) — resolving
a `ComplianceEvidenceFile`-attached file to its owning project, so the
core, module-agnostic `GET /api/v1/files/{id}` download endpoint
(`app.routers.files.download_file`) can authorize a Compliance evidence
attachment without importing anything from this module directly.

Phase 9 (Approval/Sign-off, §12, §16, §27) adds one more read-only MCP tool,
`compliance_list_pending_approvals(project_id)`, mirroring `compliance_
list_non_compliant_requirements`'s exact shape. The three real workflow
actions this phase adds — `submit-for-approval`, `approve`, `reject` — are
**deliberately never declared here**: `project_router.py` marks `approve`/
`reject` with `app.modules.registry.APPROVAL_ACTION_ROUTE_EXTRA`, which
would exclude them from the manifest even if a future session mistakenly
added tool declarations for them, but the first line of defence is simply
that no `McpToolDefinition` for any of the three exists in this file at
all — mirroring `docs/mcp-server.md`'s existing, explicit rule that
ReqTrackManager's core approval workflow is excluded from the tool surface
on principle (accountable-human-decision, not an RBAC question).

Phase 10 (Scheduled Reviews + Notifications, §17, §18, §28) adds one more
read-only MCP tool, `compliance_list_reviews_due(project_id)`, and this
module's first `scheduled_jobs` — four APScheduler jobs (`app.modules.
registry.ModuleScheduledJob`), one per date-driven sweep `scheduler.py`
defines. No mutating tool is declared for the review CRUD/complete
endpoints this phase adds (`router.py`/`project_router.py`) — Phase 10's
own plan spec asks only for the read-only "reviews due" listing, mirroring
this module's existing cautious default of adding MCP tools narrowly.

External dependencies: `app.modules.registry`'s own dataclasses;
`app.modules.compliance.router`/`.project_router`/`.service`/`.scheduler`
(each imported lazily, inside `get_router()`/`get_project_router()`/
`resolve_file_owner_project_id`/the `scheduled_jobs` callables, to avoid any
import-cycle risk with this module's own registration -- mirroring how
Phase 5's own notes already document resolving the `MODULE_DEFINITION`/
registry import cycle via `app/modules/__init__.py`).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.modules.registry import McpToolDefinition, ModuleDefinition, ModuleRoleDefinition, ModuleScheduledJob

COMPLIANCE_MODULE_KEY = "compliance"

_ROUTER_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{COMPLIANCE_MODULE_KEY}"
_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{COMPLIANCE_MODULE_KEY}"


def get_router() -> APIRouter | None:
    """Returns this module's org-scoped `APIRouter` (Phase 6 — Standards
    Management API; Phase 7 adds standard-to-project assignment endpoints
    to this same router). Imported inside the function body, not at module
    top-level, to avoid any import-cycle risk with this module's own
    registration (see this module's own docstring)."""
    from app.modules.compliance.router import router as compliance_router

    return compliance_router


def get_project_router() -> APIRouter | None:
    """Returns this module's project-scoped `APIRouter` (Phase 7 — Project
    Compliance Assignment & Assessment). Imported inside the function
    body for the same import-cycle reason as `get_router()`."""
    from app.modules.compliance.project_router import router as compliance_project_router

    return compliance_project_router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """This module's `ModuleDefinition.resolve_file_owner_project_id` hook
    (Phase 8) — imported lazily for the same import-cycle reason as
    `get_router()`/`get_project_router()`."""
    from app.modules.compliance.service import resolve_evidence_file_project_id

    return resolve_evidence_file_project_id(db, file_id)


def _run_evidence_expiry_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_evidence_expiry_notifications

    send_evidence_expiry_notifications(db)


def _run_review_due_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_review_due_notifications

    send_review_due_notifications(db)


def _run_required_action_due_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_required_action_due_notifications

    send_required_action_due_notifications(db)


def _run_target_date_notifications(db: Session) -> None:
    from app.modules.compliance.scheduler import send_target_date_notifications

    send_target_date_notifications(db)


MODULE_DEFINITION = ModuleDefinition(
    key=COMPLIANCE_MODULE_KEY,
    name="Compliance",
    description=(
        "Manage compliance standards, requirements, and required actions, and assess project "
        "compliance against them."
    ),
    version="0.1.0",
    default_enabled=True,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    models_import_path="app.modules.compliance.models",
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    scheduled_jobs=(
        ModuleScheduledJob(
            job_id="evidence_expiry_reminders", hour=2, minute=0, run=_run_evidence_expiry_notifications
        ),
        ModuleScheduledJob(job_id="review_due_reminders", hour=2, minute=15, run=_run_review_due_notifications),
        ModuleScheduledJob(
            job_id="required_action_due_reminders", hour=2, minute=30, run=_run_required_action_due_notifications
        ),
        ModuleScheduledJob(job_id="target_date_reminders", hour=2, minute=45, run=_run_target_date_notifications),
    ),
    roles=(
        ModuleRoleDefinition(
            role_key="compliance_manager",
            name="Compliance Manager",
            description=(
                "Creates and manages compliance standards, versions, requirements, and required "
                "actions; assigns standards to projects; views compliance across projects (§3)."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="compliance_officer",
            name="Compliance Officer",
            description=(
                "Modifies compliance assessments, applicability, and evidence, and performs "
                "authorised approval/sign-off for the projects they are assigned to (§11/§26)."
            ),
            scope="project",
        ),
    ),
    mcp_tools=(
        McpToolDefinition(
            name="list_standards",
            description="Lists an organisation's compliance standards.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation whose compliance standards to list."},
            ],
        ),
        McpToolDefinition(
            name="get_standard_version",
            description="Fetches a single version of a compliance standard.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The specific version of the standard."},
            ],
        ),
        McpToolDefinition(
            name="list_requirements",
            description="Lists the requirements defined in one version of a compliance standard.",
            method="GET",
            path_template=f"{_ROUTER_PREFIX}/standards/{{standard_id}}/versions/{{version_id}}/requirements",
            params=[
                {"name": "organization_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The organisation that owns the standard."},
                {"name": "standard_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The compliance standard."},
                {"name": "version_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The specific version of the standard whose requirements to list."},
            ],
        ),
        McpToolDefinition(
            name="get_project_status",
            description=(
                "Gets a project's overall compliance status (§20) against each of its currently "
                "assigned, active compliance standards — total/applicable/non-applicable requirement "
                "counts, a per-status breakdown, the calculated compliance percentage, and the "
                "overall compliance/approval state."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/status",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose compliance status to get."},
            ],
        ),
        McpToolDefinition(
            name="list_non_compliant_requirements",
            description=(
                "Lists every applicable, Non-Compliant requirement across a project's active "
                "compliance standard assignments."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/non-compliant-requirements",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose non-compliant requirements to list."},
            ],
        ),
        McpToolDefinition(
            name="list_expiring_evidence",
            description=(
                "Lists a project's non-archived supporting evidence that is approaching or has "
                "already passed its expiry date."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/expiring-evidence",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose expiring/expired evidence to list."},
            ],
        ),
        McpToolDefinition(
            name="list_pending_approvals",
            description=(
                "Lists every requirement currently awaiting formal approval/sign-off across a "
                "project's active compliance standard assignments."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/pending-approvals",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose pending compliance approvals to list."},
            ],
        ),
        McpToolDefinition(
            name="list_reviews_due",
            description=(
                "Lists every scheduled compliance review, standard-level or project-level, that is "
                "currently due or overdue for a project — its own project-level reviews plus any "
                "review of a standard it is assigned to."
            ),
            method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/reviews-due",
            params=[
                {"name": "project_id", "type": "uuid", "required": True, "in": "path",
                 "description": "The project whose due/overdue compliance reviews to list."},
            ],
        ),
    ),
)
