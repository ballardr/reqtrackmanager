"""
Module: routers.orgs

Aggregates the `orgs` package's per-concern routers — `core` (creation,
import/export/merge, disable/enable/delete, listing, overview stats),
`membership` (users, pending invites, access summaries, org-role and
module-role grants, leave/remove/deactivate/archive), `groups`,
`resources` (shared file resources), `branding` (logo/login-background,
accent/wordmark/email-footer, default template, public login-info),
`settings` (advanced settings, module enablement, SSO/OIDC, SCIM),
`reports` (report templates and org-level report defaults), `org_pats`
(org-admin PAT incident-response actions), `taxonomies` (project
statuses, requirement link types), and `custom_roles` (Fine-Grained Access
Control's permission vocabulary, `CustomRoleDefinition` CRUD, and its
user/group grant endpoints — `docs/plans/core-fine-grained-access-control-
plan.md` Phase 3) — into the single `/api/v1/orgs` router `main.py` mounts.

Split out from one ~3,200-line module (previously `routers/orgs.py`) so
each concern can be read and changed independently; see
`docs/decisions.md` for the decision record. `core.py` also holds the
shared `_now()` helper the other bucket files import from it rather than
duplicating.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.orgs import (
    branding,
    core,
    custom_roles,
    groups,
    membership,
    org_pats,
    reports,
    resources,
    settings,
    taxonomies,
)

_PREFIX = "/api/v1/orgs"

# The prefix is passed to each `include_router()` call, not set on `router`
# itself: `core.router` has a bare `POST ""` route (create) and a bare
# `GET ""` route (list), and FastAPI's `include_router` rejects a route
# whose *own* path is empty unless the call's `prefix` argument (not the
# target router's already-configured prefix) is non-empty.
router = APIRouter()
router.include_router(core.router, prefix=_PREFIX)
router.include_router(membership.router, prefix=_PREFIX)
router.include_router(groups.router, prefix=_PREFIX)
router.include_router(resources.router, prefix=_PREFIX)
router.include_router(branding.router, prefix=_PREFIX)
router.include_router(settings.router, prefix=_PREFIX)
router.include_router(reports.router, prefix=_PREFIX)
router.include_router(org_pats.router, prefix=_PREFIX)
router.include_router(taxonomies.router, prefix=_PREFIX)
router.include_router(custom_roles.router, prefix=_PREFIX)
