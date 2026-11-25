"""
Module: modules.compliance.project_router

Aggregates the per-concern routers of the project-scoped package: `assignment` (standard assignments, version
migration, status and rollup reads), `applicability` (per-requirement applicability and assessment editing),
`assessment_workflow` (submit, approve, reject, history, evidence listing), `required_action_assessments`, `evidence`
and `reviews`, into the one `/api/v1/projects/{project_id}/modules/compliance` router returned by
`app.modules.compliance.module.get_project_router()`.

Each bucket carries its own OpenAPI tag (`compliance-project-<bucket>`) so a concern can be read and changed
independently (see `docs/decisions.md`). `_shared.py` holds the dependency factories and ownership-chain lookups used by
two or more buckets.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.compliance.project_router import (
    applicability,
    assessment_workflow,
    assignment,
    evidence,
    required_action_assessments,
    reviews,
)

_PREFIX = "/api/v1/projects/{project_id}/modules/compliance"

router = APIRouter()
router.include_router(assignment.router, prefix=_PREFIX)
router.include_router(applicability.router, prefix=_PREFIX)
router.include_router(assessment_workflow.router, prefix=_PREFIX)
router.include_router(required_action_assessments.router, prefix=_PREFIX)
router.include_router(evidence.router, prefix=_PREFIX)
router.include_router(reviews.router, prefix=_PREFIX)
