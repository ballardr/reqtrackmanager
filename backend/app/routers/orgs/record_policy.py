"""
Module: routers.orgs.record_policy

Organisation administration of the personal-data policy for record export and import: the organisation's
override per sensitivity tag, shown beside the server default it overrides (`services.record_policy`).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.user import User
from app.schemas.record_policy import OrgSensitivityOut, OrgSensitivityUpdate
from app.services.rbac import require_org_role
from app.services.record_policy import TagPolicy, organization_policy, set_organization_override

router = APIRouter(tags=["org-record-policy"])


def _out(item: TagPolicy) -> OrgSensitivityOut:
    return OrgSensitivityOut(
        tag=item.tag, server_allowed=item.server_allowed, override=item.override, effective=item.effective,
    )


@router.get("/{organization_id}/record-sensitivity-policy", response_model=list[OrgSensitivityOut])
def list_org_sensitivity_policy(
    organization_id: UUID, current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
) -> list[OrgSensitivityOut]:
    """Every sensitivity tag with the server default, the organisation's override (if any) and the effective value."""
    return [_out(item) for item in organization_policy(db, organization_id)]


@router.put("/{organization_id}/record-sensitivity-policy/{tag}", response_model=OrgSensitivityOut)
def update_org_sensitivity_policy(
    organization_id: UUID, tag: str, payload: OrgSensitivityUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
) -> OrgSensitivityOut:
    """Sets the organisation's override for one tag, or clears it (`allowed: null`) to follow the server again.

    Raises:
        HTTPException: 404 for an unknown tag.
    """
    try:
        set_organization_override(db, organization_id, tag, payload.allowed, current_user.id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sensitivity tag.") from None
    db.commit()
    return _out(next(item for item in organization_policy(db, organization_id) if item.tag == tag))
