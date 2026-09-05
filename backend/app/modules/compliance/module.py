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

Phase 5 contributes no HTTP endpoints and no MCP tools yet — `get_router()`
returns `None` and `mcp_tools` is left at its default empty tuple. Both land
in Phase 6 (Standards Management API), which mounts a real `APIRouter` here
and declares this module's first read-only MCP tools.

External dependencies: none beyond `app.modules.registry`'s own dataclasses.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.registry import ModuleDefinition, ModuleRoleDefinition

COMPLIANCE_MODULE_KEY = "compliance"


def get_router() -> APIRouter | None:
    """Returns this module's `APIRouter`, or `None` if it has none yet.

    Phase 5 is data model only — no endpoints exist yet, so this returns
    `None` rather than a dummy empty router (per `ModuleDefinition.
    get_router`'s own docstring, this is exactly the case that's for).
    Phase 6 replaces this with a real router.
    """
    return None


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
)
