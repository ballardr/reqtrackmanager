"""
Module: routers.requirements

Aggregates the `requirements` package's per-concern routers — `core`
(CRUD, import/export, history, activity, move), `workflow` (review/
approval/completion lifecycle), `links` (requirement-to-requirement
traceability), `comments` (discussion threads and their attachments),
`subscriptions` (per-requirement follow), `files` (direct/shared-resource
attachments), and `actions` (requirement<->action linking) — into the
single `/api/v1/projects/{project_id}/requirements` router `main.py`
mounts.

Split out from one ~1,500-line module (previously `routers/requirements.py`)
so each concern can be read and changed independently; see `docs/decisions.md`
for the decision record. `core.py` also holds the shared private helpers
(`_get_requirement_in_project`, `_require_edit_role`, `_to_out`) the other
bucket files import from it rather than duplicating.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.requirements import actions, comments, core, files, links, subscriptions, workflow

_PREFIX = "/api/v1/projects/{project_id}/requirements"

# The prefix is passed to each `include_router()` call, not set on `router`
# itself: `core.router` has a bare `POST ""` route (create), and FastAPI's
# `include_router` rejects a route whose *own* path is empty unless the
# call's `prefix` argument (not the target router's already-configured
# prefix) is non-empty.
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(workflow.router, prefix=_PREFIX)
router.include_router(links.router, prefix=_PREFIX)
router.include_router(comments.router, prefix=_PREFIX)
router.include_router(subscriptions.router, prefix=_PREFIX)
router.include_router(files.router, prefix=_PREFIX)
router.include_router(actions.router, prefix=_PREFIX)
