"""
Module: modules.compliance.global_router

The Compliance Module's Phase 18 "Compliance Standards as a first-class,
cross-org, project-like nav entity" endpoints
(docs/compliance-module-plan.md Phase 18) — the two HTTP surfaces that
genuinely have no single `organization_id`/`project_id` to key a path off,
unlike everything else this module has needed so far (`router.py`'s
org-scoped endpoints, `project_router.py`'s project-scoped ones):

- `GET /api/v1/compliance/nav-visibility` — whether the caller should see
  the new top-level "Compliance Standards" nav-rail tab at all. This
  necessarily aggregates *across every org the caller belongs to*, so it
  cannot be expressed as an org-scoped route.
- `GET /api/v1/compliance/standards/{standard_id}` — resolves a standard to
  its owning `organization_id` from the standard's own id alone, mirroring
  exactly how a project's own id already resolves to its org today
  (`app.routers.projects.get_project`) with no `organization_id` segment in
  its path. The frontend's `/standards/:standardId` workspace uses this to
  learn which org a standard belongs to before making every other,
  already-existing org-scoped nested call (versions, requirements) — those
  calls are unchanged, this just supplies the `organization_id` they need.

Both endpoints are mounted via `ModuleDefinition.get_global_router` — a new,
third, optional router kind (`app.modules.registry`'s own docstring on that
field explains why `get_router`/`get_project_router` don't fit) added
specifically for this phase rather than bolting either endpoint onto
`router.py`'s org-prefixed router or `project_router.py`'s project-prefixed
one, where neither would have a real path parameter to hang off.

Responsibilities:
- Mount both endpoints under the bare `/api/v1/compliance` prefix — no
  org/project id segment at all.
- Perform authorization *internally*, per endpoint, since there is no path
  parameter for a `require_org_module_enabled`-style dependency factory to
  bind to:
  - `nav-visibility` iterates every org the caller holds a direct
    `UserOrgRole` in and applies compliance-module-plan.md Phase 18's exact
    formula ("compliance effectively enabled AND (caller is
    `compliance_manager`/org admin/server admin, OR that org has ≥1
    non-archived standard)"), reusing `service.py::
    get_effective_compliance_managers` (already computes "org admin union
    direct `compliance_manager` grant" for this exact org) rather than
    reimplementing that union.
  - `get_standard_by_id` looks the standard up first, then calls
    `app.services.rbac.require_org_access_and_module_enabled` — the
    non-dependency-factory sibling of `require_org_module_enabled` built for
    exactly this "resolve org from something else, not from a path
    parameter" shape — to get the same 404-not-403 posture every other
    compliance endpoint gives for "not a member of this org at all" /
    "member but module disabled," so a standard belonging to an org the
    caller cannot see is indistinguishable from a standard that doesn't
    exist.
- Neither endpoint mutates anything, so neither calls `services.audit.
  log_event` — this repo's CLAUDE.md audit-logging rule applies to mutating
  actions; these are both plain reads (mirrors this module's own `router.py`
  GET endpoints, none of which log either).

External dependencies: `app.services.rbac` (membership/module-enabled
resolution), `app.modules.compliance.service` (the existing "effective
compliance managers" helper), `app.modules.compliance.models`/`schemas`
(the same `ComplianceStandard` ORM model and `ComplianceStandardOut` schema
`router.py` already uses — this file introduces no new schema for the
standard-by-id response, only `ComplianceNavVisibilityOut` for the boolean
nav-visibility result).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.organization import UserOrgRole
from app.models.user import User
from app.modules.compliance.models import ComplianceStandard
from app.modules.compliance.schemas import ComplianceNavVisibilityOut, ComplianceStandardOut
from app.modules.compliance.service import get_effective_compliance_managers
from app.modules.registry import is_module_enabled
from app.services.rbac import require_org_access_and_module_enabled

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

_MODULE_KEY = "compliance"


@router.get("/nav-visibility", response_model=ComplianceNavVisibilityOut)
def get_nav_visibility(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComplianceNavVisibilityOut:
    """Whether the caller should see the "Compliance Standards" nav-rail tab
    (compliance-module-plan.md Phase 18).

    `True` if, for *any* org the caller directly belongs to (a
    `UserOrgRole` row — the same membership source `require_org_module_
    enabled` itself checks, not `is_server_admin`'s server-wide bypass),
    compliance is effectively enabled there (`app.modules.registry.
    is_module_enabled`) AND either:
    - the caller is a server admin, or is that org's effective compliance
      manager (`service.py::get_effective_compliance_managers` — org admin
      union direct `compliance_manager` grant), or
    - that org has at least one non-archived `ComplianceStandard`.

    A caller with no org memberships at all gets `False` — there is no org
    to find a `True` condition in, regardless of server-admin status,
    matching how every other module-gated surface in this codebase treats
    "not a member of any relevant scope."

    Deliberately never raises for "no visibility" — this is a UI-gating
    signal, not an authorization boundary in itself (the actual `/standards`
    listing and `/standards/{id}` endpoints each enforce their own real
    per-org access checks independently of what this returns).
    """
    org_ids = db.scalars(
        select(UserOrgRole.organization_id).distinct().where(UserOrgRole.user_id == current_user.id)
    ).all()

    for organization_id in org_ids:
        if not is_module_enabled(db, organization_id, _MODULE_KEY):
            continue
        if current_user.is_server_admin:
            return ComplianceNavVisibilityOut(visible=True)
        if current_user.id in get_effective_compliance_managers(db, organization_id):
            return ComplianceNavVisibilityOut(visible=True)
        has_standard = (
            db.scalar(
                select(ComplianceStandard.id)
                .where(
                    ComplianceStandard.organization_id == organization_id,
                    ComplianceStandard.is_archived.is_(False),
                )
                .limit(1)
            )
            is not None
        )
        if has_standard:
            return ComplianceNavVisibilityOut(visible=True)

    return ComplianceNavVisibilityOut(visible=False)


@router.get("/standards/{standard_id}", response_model=ComplianceStandardOut)
def get_standard_by_id(
    standard_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComplianceStandard:
    """Resolves a compliance standard by id alone, with no `organization_id`
    in the path — the entry point the frontend's `/standards/:standardId`
    workspace uses to learn a standard's owning org before threading that id
    through every existing org-scoped nested call (versions, requirements),
    mirroring how `app.routers.projects.get_project` already resolves a
    project's own org the same way.

    Looks the standard up first (never confirms/denies existence to a
    caller with no access to its org — see `require_org_access_and_module_
    enabled`'s own 404-not-403 docstring), then applies the identical
    membership/module-enabled checks every other compliance endpoint
    applies, just resolved from the standard's own `organization_id` column
    instead of a path parameter.

    Raises:
        HTTPException: 404 if no standard with this id exists, if the
            caller has no role in its owning org, or if compliance isn't
            effectively enabled for that org.
    """
    standard = db.get(ComplianceStandard, standard_id)
    if standard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard not found.")

    require_org_access_and_module_enabled(db, current_user, standard.organization_id, _MODULE_KEY)

    return standard
