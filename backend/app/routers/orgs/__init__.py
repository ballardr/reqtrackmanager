"""
Module: routers.orgs

Aggregates the `orgs` package's per-concern routers into the single `/api/v1/orgs` router `main.py` mounts:
`core` (creation, import/export/merge, disable/enable/delete, listing, overview stats), `membership` (users,
pending invites, access summaries, org-role and module-role grants, leave/remove/deactivate/archive),
`groups`, `resources` (shared file resources), `files` (the organisation Files list), `records` (lookup by
qualified code), `branding`, `settings` (advanced settings, module enablement, SSO/OIDC, SCIM), `org_pats`
(org-admin PAT incident response), `service_users`, `taxonomies` (project statuses, requirement link
types), `custom_roles` (Fine-Grained Access Control vocabulary, `CustomRoleDefinition` CRUD and grants),
`scoring` (scoring-matrix levels, default model and bands) and `record_policy` (the personal-data policy
override for record export and import).

Each concern is its own module so it can be read and changed independently. `core.py` also holds the shared
`_now()` helper the other bucket files import.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.orgs import (
    branding,
    core,
    custom_roles,
    files,
    groups,
    imported_people,
    membership,
    org_pats,
    record_policy,
    records,
    resources,
    scoring,
    service_users,
    settings,
    storage,
    taxonomies,
)

_PREFIX = "/api/v1/orgs"

# The prefix is passed to each `include_router()` call, not set on `router`: `core.router` has bare
# `POST ""` and `GET ""` routes, and FastAPI's `include_router` rejects a route whose own path is empty
# unless the call's `prefix` argument is non-empty.
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(membership.router, prefix=_PREFIX)
router.include_router(groups.router, prefix=_PREFIX)
router.include_router(resources.router, prefix=_PREFIX)
router.include_router(files.router, prefix=_PREFIX)
router.include_router(records.router, prefix=_PREFIX)
router.include_router(branding.router, prefix=_PREFIX)
router.include_router(settings.router, prefix=_PREFIX)
router.include_router(storage.router, prefix=_PREFIX)
router.include_router(org_pats.router, prefix=_PREFIX)
router.include_router(taxonomies.router, prefix=_PREFIX)
router.include_router(custom_roles.router, prefix=_PREFIX)
router.include_router(scoring.router, prefix=_PREFIX)
router.include_router(record_policy.router, prefix=_PREFIX)
router.include_router(imported_people.router, prefix=_PREFIX)
router.include_router(service_users.router, prefix=_PREFIX)
