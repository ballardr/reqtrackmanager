"""
Module: modules.compliance.global_router

The two Compliance endpoints with no single `organization_id` or `project_id` to key a path off, mounted through
`ModuleDefinition.get_global_router` under the bare `/api/v1/compliance` prefix:

- `GET /api/v1/compliance/nav-visibility`: whether the caller sees the top-level "Compliance Standards" nav tab. It
  aggregates across every organisation the caller belongs to.
- `GET /api/v1/compliance/standards/{standard_id}`: resolves a standard to its owning organisation from its id alone,
  as `app.routers.projects.get_project` does for a project, so the frontend `/standards/:standardId` workspace can
  learn the `organization_id` its org-scoped nested calls need.

Responsibilities: authorise internally, since no path parameter exists for a `require_org_module_enabled` dependency.
`nav-visibility` iterates every organisation where the caller holds a `UserOrgRole` and applies "compliance effectively
enabled AND (caller is `compliance_manager`, organisation admin or server admin, OR the organisation has at least one
non-archived standard)" using `service.get_effective_compliance_managers`. `get_standard_by_id` looks the standard up,
then calls `app.services.rbac.require_org_access_and_module_enabled`, giving the 404-not-403 posture of every compliance
endpoint, so a standard of an invisible organisation looks absent. Both endpoints only read, so neither writes an audit
event.

External dependencies: `app.services.rbac`, `modules.compliance.service`, `models` and `schemas` (`ComplianceStandardOut`
as `router.py`; `ComplianceNavVisibilityOut` for the nav result).
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
from app.modules.compliance.service import get_effective_compliance_managers, standard_to_out
from app.modules.registry import is_module_enabled
from app.services.rbac import require_org_access_and_module_enabled

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

_MODULE_KEY = "compliance"


@router.get("/nav-visibility", response_model=ComplianceNavVisibilityOut)
def get_nav_visibility(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComplianceNavVisibilityOut:
    """Whether the caller should see the "Compliance Standards" nav-rail tab.

    `True` if, for any organisation the caller directly belongs to (a `UserOrgRole` row, not `is_server_admin`'s
    server-wide bypass), compliance is effectively enabled (`app.modules.registry.is_module_enabled`) AND either the
    caller is a server admin or that organisation's effective compliance manager
    (`service.get_effective_compliance_managers`), or the organisation has at least one non-archived
    `ComplianceStandard`. A caller with no organisation membership gets `False`.

    `status_organization_ids` lists the compliance-enabled organisations where the caller may read the organisation-wide
    status views (the Compliance Manager gate: a manager, organisation administrator or server administrator); the
    Standards page offers its By standard and Outstanding tabs and its Organisation filter from it.

    This is a UI-gating signal, not an authorization boundary: the `/standards` endpoints enforce their own access.
    """
    org_ids = db.scalars(
        select(UserOrgRole.organization_id).distinct().where(UserOrgRole.user_id == current_user.id)
    ).all()

    visible = False
    status_organization_ids: list[UUID] = []
    for organization_id in org_ids:
        if not is_module_enabled(db, organization_id, _MODULE_KEY):
            continue
        if current_user.is_server_admin or current_user.id in get_effective_compliance_managers(db, organization_id):
            visible = True
            status_organization_ids.append(organization_id)
            continue
        if visible:
            continue
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
        visible = visible or has_standard

    return ComplianceNavVisibilityOut(visible=visible, status_organization_ids=status_organization_ids)


@router.get("/standards/{standard_id}", response_model=ComplianceStandardOut)
def get_standard_by_id(
    standard_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ComplianceStandardOut:
    """Resolves a compliance standard by id alone, with no `organization_id` in the path, so the frontend
    `/standards/:standardId` workspace can learn the owning organisation before its org-scoped nested calls.

    The standard is looked up first, then the usual membership and module-enabled checks run against its
    `organization_id` (`require_org_access_and_module_enabled`, 404-not-403, so existence is not disclosed).

    Raises:
        HTTPException: 404 if no standard has this id, the caller has no role in its organisation, or compliance is not
            effectively enabled there.
    """
    standard = db.get(ComplianceStandard, standard_id)
    if standard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard not found.")

    require_org_access_and_module_enabled(db, current_user, standard.organization_id, _MODULE_KEY)

    return standard_to_out(db, standard)
