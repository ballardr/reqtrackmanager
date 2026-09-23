"""
Module: routers.system

Aggregates the `system` package's per-concern routers — `users` (server
admin grant/revoke, server-tier role grant/revoke, the system-wide user
access-review directory, the merged orphaned-user status endpoint,
platform-wide PAT bulk revocation), `branding` (platform-wide branding
get/put, the merged branding-image upload endpoint), `modules` (module
entitlement policy get/put, module registry listing, per-organisation
module entitlements, module-contributed MCP tool listing), and `config`
(build version, public signup config, deployment-wide test email) — into
the single `/api/v1/system` router `main.py` mounts.

Split out from one ~960-line module (previously `routers/system.py`) so
each concern can be read and changed independently; see
`docs/decisions.md` for the decision record.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.system import branding, config, modules, users

_PREFIX = "/api/v1/system"

# The prefix is passed to each `include_router()` call, not set on `router`
# itself — same convention as the `orgs`/`projects`/`requirements`/
# `compliance` package splits, kept for consistency even though none of
# this package's own bucket routers happens to have a bare `""`-path route
# that would force the workaround.
router = APIRouter()
router.include_router(users.router, prefix=_PREFIX)
router.include_router(branding.router, prefix=_PREFIX)
router.include_router(modules.router, prefix=_PREFIX)
router.include_router(config.router, prefix=_PREFIX)
