"""
Module: routers.projects

Aggregates the `projects` package's per-concern routers — `core` (CRUD,
import, tree, favourites, files, export, terminology, changes, metrics),
`hierarchy` (ancestors/children, member sources, effective members,
access-inheritance materialization), `report_config`, `lifecycle`
(archive/unarchive), `stages`, `taxonomy` (components/categories),
`groups`, `roles` (direct/group/by-email project role assignment,
pending invites), and `module_roles` — into the single `/api/v1/projects`
router `main.py` mounts.

Split out from one ~3,500-line module (previously `routers/projects.py`)
so each concern can be read and changed independently; see
`docs/decisions.md` for the decision record. `core.py` also holds the
shared private helpers (`_accessible_project_ids`,
`_project_out_with_redacted_parent`, `_ensure_project_has_a_manager`,
`_require_user_in_org`) the other bucket files import from it rather than
duplicating.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.projects import core, groups, hierarchy, lifecycle, module_roles, report_config, roles, stages, taxonomy

_PREFIX = "/api/v1/projects"

# The prefix is passed to each `include_router()` call, not set on `router`
# itself: `core.router` has a bare `POST ""` route (create), and FastAPI's
# `include_router` rejects a route whose *own* path is empty unless the
# call's `prefix` argument (not the target router's already-configured
# prefix) is non-empty.
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(hierarchy.router, prefix=_PREFIX)
router.include_router(report_config.router, prefix=_PREFIX)
router.include_router(lifecycle.router, prefix=_PREFIX)
router.include_router(stages.router, prefix=_PREFIX)
router.include_router(taxonomy.router, prefix=_PREFIX)
router.include_router(groups.router, prefix=_PREFIX)
router.include_router(roles.router, prefix=_PREFIX)
router.include_router(module_roles.router, prefix=_PREFIX)
