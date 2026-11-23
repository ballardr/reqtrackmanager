"""
Module: routers.system

Aggregates the `system` package's per-concern routers into the single `/api/v1/system` router `main.py`
mounts: `access` (the caller's own server-tier roles and the sections they unlock), `users` (server admin and
server-tier role grant/revoke, the system-wide user access-review directory, the orphaned-user status
endpoint, platform-wide PAT bulk revocation), `branding` (platform-wide branding get/put and image upload),
`modules` (module entitlement policy, registry listing, per-organisation entitlements, module-contributed
MCP tool listing), `config` (build version, public signup config, deployment-wide test email),
`record_policy` (the server default for personal data in record export and import) and `report_fonts` (the
extra report fonts the administrator mounts).

Each concern is its own module so it can be read and changed independently.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.system import access, branding, config, modules, record_policy, report_fonts, users

_PREFIX = "/api/v1/system"

# The prefix is passed to each `include_router()` call, not set on `router`, as in the
# `orgs`/`projects`/`requirements`/`compliance` packages; none of this package's routers has a bare
# `""`-path route that would force it, so this is for consistency.
router = APIRouter()
router.include_router(access.router, prefix=_PREFIX)
router.include_router(users.router, prefix=_PREFIX)
router.include_router(branding.router, prefix=_PREFIX)
router.include_router(modules.router, prefix=_PREFIX)
router.include_router(config.router, prefix=_PREFIX)
router.include_router(record_policy.router, prefix=_PREFIX)
router.include_router(report_fonts.router, prefix=_PREFIX)
