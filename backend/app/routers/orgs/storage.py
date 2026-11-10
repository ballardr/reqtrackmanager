"""
Module: routers.orgs.storage

An organisation's storage rules and usage: the organisation's own upload switch and storage limit, set by the platform
operator, and the usage the limit is measured against.

Responsibilities:
- `GET /{organization_id}/storage`: the rules and usage, for the organisation's administrators, Platform subscription
  managers and server administrators (counts only, never file names or content).
- `PUT /{organization_id}/storage`: change the rules; Platform subscription manager or server administrator only, so an
  organisation administrator cannot lift their own limit.

Design decisions: the rules are the operator's policy for a tenant and are not in the organisation bundle; the audit event
records the old and new values and the role used, never any file data. External dependencies: `services.storage_usage`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ServerRole
from app.models.organization import Organization, ServerSettings
from app.models.user import User
from app.schemas.org import OrgStorageOut, OrgStorageUpdate
from app.services import storage_usage
from app.services.audit import log_event
from app.services.rbac import (
    get_effective_org_roles,
    get_granted_server_roles,
    require_server_role,
    server_role_used,
)

router = APIRouter(tags=["organizations-storage"])


def _is_operator(db: Session, user: User) -> bool:
    """Whether `user` is a server administrator or a Platform subscription manager.

    Args:
        db: Database session.
        user: The caller.

    Returns:
        True when the caller may change an organisation's storage rules.
    """
    return user.is_server_admin or ServerRole.SUBSCRIPTION_MANAGER in get_granted_server_roles(db, user)


def _organization(db: Session, organization_id: UUID) -> Organization:
    """Loads an organisation or raises 404.

    Args:
        db: Database session.
        organization_id: The organisation.

    Returns:
        The organisation.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _out(db: Session, org: Organization, can_edit: bool) -> OrgStorageOut:
    """Builds the response for an organisation.

    Args:
        db: Database session.
        org: The organisation.
        can_edit: Whether the caller may change the rules.

    Returns:
        The rules and usage.
    """
    quota = storage_usage.effective_quota(db, org)
    used = storage_usage.used_bytes(db, org.id)
    return OrgStorageOut(
        file_uploads_enabled=org.file_uploads_enabled,
        deployment_uploads_enabled=db.scalar(select(ServerSettings.file_uploads_enabled)) is not False,
        storage_quota_bytes=org.storage_quota_bytes,
        default_storage_quota_bytes=db.scalar(select(ServerSettings.default_storage_quota_bytes)),
        effective_quota_bytes=quota.bytes,
        quota_source=quota.source,
        used_bytes=used,
        file_count=storage_usage.file_count(db, org.id),
        warning=bool(quota.bytes and used >= quota.bytes * storage_usage.WARNING_PERCENT // 100),
        can_edit=can_edit,
    )


@router.get("/{organization_id}/storage", response_model=OrgStorageOut)
def get_org_storage(
    organization_id: UUID, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> OrgStorageOut:
    """Reads an organisation's storage rules and usage.

    Allowed for a server administrator, a Platform subscription manager and an administrator of the organisation. A
    personal access token reads only an organisation it is scoped to and never uses a server role.

    Raises:
        HTTPException: 403 for anyone else; 404 when the organisation does not exist.
    """
    pat_orgs = getattr(request.state, "pat_allowed_org_ids", None)
    operator = pat_orgs is None and _is_operator(db, current_user)
    if not operator:
        if pat_orgs is not None and organization_id not in pat_orgs:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
        if OrgRole.ORG_ADMIN not in get_effective_org_roles(db, current_user.id, organization_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
    return _out(db, _organization(db, organization_id), can_edit=operator)


@router.put("/{organization_id}/storage", response_model=OrgStorageOut)
def update_org_storage(
    organization_id: UUID, payload: OrgStorageUpdate,
    current_user: User = Depends(require_server_role(ServerRole.SUBSCRIPTION_MANAGER)),
    db: Session = Depends(get_db),
) -> OrgStorageOut:
    """Sets an organisation's upload switch and storage limit (Platform subscription manager or server administrator).

    Lowering the limit below current usage only blocks new files; existing files stay readable and deletable. A changed
    limit clears the "nearly full" notice flag so the notice can be sent again for the new limit.

    Raises:
        HTTPException: 403 without the role; 404 when the organisation does not exist.
    """
    org = _organization(db, organization_id)
    before = {"file_uploads_enabled": org.file_uploads_enabled, "storage_quota_bytes": org.storage_quota_bytes}
    org.file_uploads_enabled = payload.file_uploads_enabled
    if org.storage_quota_bytes != payload.storage_quota_bytes:
        org.storage_warned = False
    org.storage_quota_bytes = payload.storage_quota_bytes
    log_event(
        db, entity_type="organization", entity_id=org.id, action="storage_rules_updated", actor_id=current_user.id,
        organization_id=org.id,
        detail={
            "role_used": server_role_used(db, current_user, ServerRole.SUBSCRIPTION_MANAGER),
            "before": before,
            "after": {"file_uploads_enabled": org.file_uploads_enabled, "storage_quota_bytes": org.storage_quota_bytes},
        },
    )
    db.commit()
    db.refresh(org)
    return _out(db, org, can_edit=True)
