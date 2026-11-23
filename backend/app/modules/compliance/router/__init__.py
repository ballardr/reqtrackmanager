"""
Module: modules.compliance.router

Aggregates the per-concern routers of the organisation-scoped package: `settings`, `standards` (CRUD, lifecycle,
export, import, applicability default, exclusions, project summary, history), `standard_access` (standard member and
group role grants, a separate RBAC-adjacent bucket), `standard_versions`, `version_requirements`,
`version_required_actions`, `action_types`, `mapping_relationship_types`, `requirement_mappings`, `org_dashboard`
(project-compliance assignment and the organisation-wide rollup reads) and `standard_reviews`, into the one
`/api/v1/orgs/{organization_id}/modules/compliance` router returned by `app.modules.compliance.module.get_router()`.

Each bucket carries its own OpenAPI tag (`compliance-org-<bucket>`) so a concern can be read and changed independently
(see `docs/decisions.md`). `_shared.py` holds the dependency factories, standard-scoped role gates and cross-organisation
ownership-chain lookups used by three or more buckets.
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
