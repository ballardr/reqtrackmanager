"""
Module: routers.projects

Aggregates the `projects` package's per-concern routers into the single `/api/v1/projects` router
`main.py` mounts: `core` (CRUD, import, tree, favourites, files, export, terminology, changes, metrics),
`hierarchy` (ancestors/children, member sources, effective members, access-inheritance materialisation),
`lifecycle` (archive/unarchive), `stages`, `component_stages` (component phases), `stage_phase_plans`
(phase schedule), `taxonomy` (components/categories), `groups`, `roles` (direct/group/by-email project role
assignment, pending invites), `module_roles` and `scoring` (project overrides of the scoring-matrix
default model/bands).

Each concern is its own module so it can be read and changed independently. `core.py` also holds the shared
private helpers (`_accessible_project_ids`, `_project_out_with_redacted_parent`,
`_ensure_project_has_a_manager`, `_require_user_in_org`) the other bucket files import.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.projects import (
    baselines,
    component_stages,
    core,
    groups,
    hierarchy,
    lifecycle,
    module_roles,
    roles,
    scoring,
    stage_phase_plans,
    stages,
    taxonomy,
)

_PREFIX = "/api/v1/projects"

# The prefix is passed to each `include_router()` call, not set on `router`: `core.router` has a bare
# `POST ""` route, and FastAPI's `include_router` rejects a route whose own path is empty unless the call's
# `prefix` argument is non-empty.
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(hierarchy.router, prefix=_PREFIX)
router.include_router(lifecycle.router, prefix=_PREFIX)
router.include_router(stages.router, prefix=_PREFIX)
router.include_router(baselines.router, prefix=_PREFIX)
router.include_router(component_stages.router, prefix=_PREFIX)
router.include_router(stage_phase_plans.router, prefix=_PREFIX)
router.include_router(taxonomy.router, prefix=_PREFIX)
router.include_router(groups.router, prefix=_PREFIX)
router.include_router(roles.router, prefix=_PREFIX)
router.include_router(module_roles.router, prefix=_PREFIX)
router.include_router(scoring.router, prefix=_PREFIX)
