"""
Module: modules.decisions.project_router

Aggregates the Decision Management module's project-scoped router
package's per-concern routers — `decision_types` (project-scoped Decision
Type definition CRUD), `core` (Decision CRUD/archive/unarchive),
`workflow` (propose/submit-for-review/approve/reject lifecycle
transitions, including the AI-approval MCP gate), `relationships`
(supersession, Decision<->Requirement, Decision<->Decision links),
`comments` (comment CRUD/edit + comment-file attach/detach), and `files`
(direct Decision file attach/list/detach) — into the single
`/api/v1/projects/{project_id}/modules/decisions` router
`app.modules.decisions.module.get_project_router()` returns.

Split out from one ~960-line module (previously `modules/decisions/
project_router.py`) so each concern can be read and changed
independently, and so each bucket's endpoints carry their own specific
OpenAPI tag (`decisions-<bucket>`) instead of one flat `"decisions"`
tag; see `docs/decisions.md` for the decision record. `_shared.py` holds
the dependency factory, ownership-chain lookup, edit-role gate, and
content-lock check used by three or more of these bucket files.

Every route above already carries the full path (`core` declares empty-path
routes, which FastAPI refuses to mount under an empty prefix), so `router.prefix`
is only assigned afterwards: the report catalogue
(`services.report_framework.project_catalogue`) and MCP path verification read
it as the module's mount.

`reports` (core `services.report_framework`, declared in `reports.py`) is
included first, ahead of the dynamic `/{decision_id}/...` routes.

`decision_types` is included **before** `core`: `core.router` declares a
single-segment dynamic `GET /{decision_id}`, which would otherwise shadow
`decision_types`' literal `GET /decision-types` if `core` were registered
first — the same ordering the pre-split flat file already relied on
(decision-types routes were defined textually before the bare-CRUD
routes there too), preserved here rather than incidentally broken by
picking an alphabetical or arbitrary include order.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.decisions.project_router import comments, core, decision_types, files, relationships, workflow
from app.modules.decisions.reports import REPORT_ROUTERS

_PREFIX = "/api/v1/projects/{project_id}/modules/decisions"

router = APIRouter()
router.include_router(REPORT_ROUTERS.project, prefix=_PREFIX)
router.include_router(decision_types.router, prefix=_PREFIX)
router.include_router(core.router, prefix=_PREFIX)
router.include_router(workflow.router, prefix=_PREFIX)
router.include_router(relationships.router, prefix=_PREFIX)
router.include_router(comments.router, prefix=_PREFIX)
router.include_router(files.router, prefix=_PREFIX)
# Read by the report catalogue and MCP path verification; routes above already include it.
router.prefix = _PREFIX
