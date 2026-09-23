"""
Module: modules.compliance.router

Aggregates the Compliance Module's org-scoped router package's per-concern
routers — `settings` (org compliance settings), `standards` (standard CRUD/
lifecycle/export/import/applicability-default/exclusions/project-summary/
history), `standard_access` (standard member/group role grants — a
deliberately separate, RBAC-adjacent bucket), `standard_versions` (version
create/list/get/update/publish/retire), `version_requirements` (a version's
hierarchical requirements), `version_required_actions` (required actions
nested under a requirement), `action_types`, `mapping_relationship_types`,
`requirement_mappings`, `org_dashboard` (project-compliance assignment plus
the org-wide rollup GETs), and `standard_reviews` — into the single
`/api/v1/orgs/{organization_id}/modules/compliance` router
`app.modules.compliance.module.get_router()` returns.

Split out from one ~2,800-line module (previously `modules/compliance/
router.py`) so each concern can be read and changed independently, and so
each bucket's endpoints carry their own specific OpenAPI tag
(`compliance-org-<bucket>`) instead of one flat `"compliance"` tag; see
`docs/decisions.md` for the decision record. `_shared.py` holds the
dependency factories, standard-scoped role gates, and cross-org ownership-
chain lookups used by three or more of these bucket files.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.compliance.router import (
    action_types,
    mapping_relationship_types,
    org_dashboard,
    requirement_mappings,
    settings,
    standard_access,
    standard_reviews,
    standard_versions,
    standards,
    version_required_actions,
    version_requirements,
)

_PREFIX = "/api/v1/orgs/{organization_id}/modules/compliance"

router = APIRouter()
router.include_router(settings.router, prefix=_PREFIX)
router.include_router(standards.router, prefix=_PREFIX)
router.include_router(standard_access.router, prefix=_PREFIX)
router.include_router(standard_versions.router, prefix=_PREFIX)
router.include_router(version_requirements.router, prefix=_PREFIX)
router.include_router(version_required_actions.router, prefix=_PREFIX)
router.include_router(action_types.router, prefix=_PREFIX)
router.include_router(mapping_relationship_types.router, prefix=_PREFIX)
router.include_router(requirement_mappings.router, prefix=_PREFIX)
router.include_router(org_dashboard.router, prefix=_PREFIX)
router.include_router(standard_reviews.router, prefix=_PREFIX)
