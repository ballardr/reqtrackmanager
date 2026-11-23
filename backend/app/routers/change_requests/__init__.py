"""
Module: routers.change_requests

Aggregates the package's per-concern routers (`core`: create/list/get/activity, `workflow`:
submit/withdraw/decide, `tasks`, `votes`, `comments`: comments, reactions and comment files, and
`subscriptions`) into the single `/api/v1/projects/{project_id}/change-requests` router `main.py` mounts.

The formal change management workflow (C-G-03, C-G-12): submitting a change request, reviewing and
discussing it, and a project manager approving or rejecting it. Approval applies the proposed change to
the target requirement (or creates a new one) through the versioning mechanism used for direct
scoping-stage edits, so both paths share one audit trail. Each concern is its own module so it can be
read and changed independently.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.change_requests import comments, core, subscriptions, tasks, votes, workflow

_PREFIX = "/api/v1/projects/{project_id}/change-requests"

# The prefix is passed to each `include_router()` call, not set on `router`: `core.router` has bare
# `POST ""` and `GET ""` routes, and FastAPI's `include_router` rejects a route whose own path is empty
# unless the call's `prefix` argument is non-empty (as in the `orgs`/`projects`/`requirements` packages).
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(workflow.router, prefix=_PREFIX)
router.include_router(tasks.router, prefix=_PREFIX)
router.include_router(votes.router, prefix=_PREFIX)
router.include_router(comments.router, prefix=_PREFIX)
router.include_router(subscriptions.router, prefix=_PREFIX)
