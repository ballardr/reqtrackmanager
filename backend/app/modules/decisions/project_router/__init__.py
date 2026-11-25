"""
Module: modules.decisions.project_router

Aggregates the per-concern routers (`decision_types`, `core`, `workflow`,
`relationships`, `comments`, `files`) into the one
`/api/v1/projects/{project_id}/modules/decisions` router returned by
`module.get_project_router()`. Routes carry their full path, so `router.prefix`
is assigned afterwards. `decision_types` and `reports` come before `core`, whose
dynamic `GET /{decision_id}` would shadow their literal paths.
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
