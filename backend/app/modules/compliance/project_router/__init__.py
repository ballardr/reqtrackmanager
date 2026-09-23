"""
Module: modules.compliance.project_router

Aggregates the Compliance Module's project-scoped router package's per-
concern routers — `assignment` (a project's standard assignments, version
migration, and status/rollup GETs), `applicability` (per-requirement
applicability/assessment editing), `assessment_workflow` (submit/approve/
reject, history, evidence listing), `required_action_assessments`,
`evidence`, `reviews`, and `traceability_links` (links to core, non-
compliance requirements) — into the single `/api/v1/projects/{project_id}/
modules/compliance` router `app.modules.compliance.module.get_project_
router()` returns.

Split out from one ~2,000-line module (previously `modules/compliance/
project_router.py`) so each concern can be read and changed independently,
and so each bucket's endpoints carry their own specific OpenAPI tag
(`compliance-project-<bucket>`) instead of one flat `"compliance"` tag; see
`docs/decisions.md` for the decision record. `_shared.py` holds the
dependency factories and ownership-chain lookups used by two or more of
these bucket files.
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
    traceability_links,
)

_PREFIX = "/api/v1/projects/{project_id}/modules/compliance"

router = APIRouter()
router.include_router(assignment.router, prefix=_PREFIX)
router.include_router(applicability.router, prefix=_PREFIX)
router.include_router(assessment_workflow.router, prefix=_PREFIX)
router.include_router(required_action_assessments.router, prefix=_PREFIX)
router.include_router(evidence.router, prefix=_PREFIX)
router.include_router(reviews.router, prefix=_PREFIX)
router.include_router(traceability_links.router, prefix=_PREFIX)
