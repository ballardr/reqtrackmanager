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

External dependencies: `app.modules.registry`'s own dataclasses;
`app.modules.compliance.router`/`.project_router` (each imported lazily,
inside `get_router()`/`get_project_router()`, to avoid any import-cycle
risk with this module's own registration -- mirroring how Phase 5's own
notes already document resolving the `MODULE_DEFINITION`/registry import
cycle via `app/modules/__init__.py`).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.registry import McpToolDefinition, ModuleDefinition, ModuleRoleDefinition

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
    ),
)
