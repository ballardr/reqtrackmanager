"""
Module: modules.compliance.router.settings

This organisation's compliance settings (Phase 22): currently just the
fallback org group used as a standard's default Standards Manager when
it has no member/group role grant of its own.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import OrgGroup
from app.models.user import User
from app.modules.compliance.models import ComplianceOrgSettings
from app.modules.compliance.router._shared import _require_manage, _require_view
from app.modules.compliance.schemas import ComplianceOrgSettingsOut, ComplianceOrgSettingsUpdate
from app.services.audit import log_event

router = APIRouter(tags=["compliance-org-settings"])


# --- Phase 22: org-level compliance settings (default fallback group) ------


@router.get("/settings", response_model=ComplianceOrgSettingsOut)
def get_compliance_org_settings(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This organisation's own Compliance-module settings (Phase 22) — just
    the designated fallback compliance-managers group so far. View-gated:
    any org member with the module enabled may see which group (if any) is
    designated, the same "the option itself isn't sensitive" reasoning
    `list_org_module_roles` already applies. Returns the all-`None` default
    when no settings row exists yet for this organisation (see
    `ComplianceOrgSettings`'s own docstring on lazy row creation)."""
    settings = db.scalar(select(ComplianceOrgSettings).where(ComplianceOrgSettings.organization_id == organization_id))
    if settings is None:
        return ComplianceOrgSettingsOut()
    return ComplianceOrgSettingsOut(default_standards_manager_group_id=settings.default_standards_manager_group_id)


@router.put("/settings", response_model=ComplianceOrgSettingsOut)
def update_compliance_org_settings(
    organization_id: UUID, payload: ComplianceOrgSettingsUpdate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Sets (or clears) this organisation's designated fallback compliance-
    managers group (Phase 22) — org-wide `compliance_manager`-or-higher
    only, since this is an org-level setting, not scoped to any one
    standard. 400s if `default_standards_manager_group_id` doesn't name a
    real `OrgGroup` belonging to this same organisation."""
    if payload.default_standards_manager_group_id is not None:
        group = db.get(OrgGroup, payload.default_standards_manager_group_id)
        if group is None or group.organization_id != organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a group in this organisation.")
    settings = db.scalar(select(ComplianceOrgSettings).where(ComplianceOrgSettings.organization_id == organization_id))
    if settings is None:
        settings = ComplianceOrgSettings(organization_id=organization_id)
        db.add(settings)
    previous = settings.default_standards_manager_group_id
    settings.default_standards_manager_group_id = payload.default_standards_manager_group_id
    log_event(
        db, entity_type="compliance_org_settings", entity_id=organization_id, action="updated",
        actor_id=current_user.id, organization_id=organization_id,
        detail={
            "previous_group_id": str(previous) if previous else None,
            "new_group_id": str(settings.default_standards_manager_group_id)
            if settings.default_standards_manager_group_id else None,
        },
    )
    db.commit()
    return ComplianceOrgSettingsOut(default_standards_manager_group_id=settings.default_standards_manager_group_id)
