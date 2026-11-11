"""
Module: routers.orgs.resources

Organisation shared resources (C-M-03): upload/list/delete a file asset
that belongs to the organisation rather than to any one project.

Access: every member lists; upload and delete need the `manage_org_resources` permission, which organisation
administrators hold and a custom role can give to a user or an organisation group. `GET .../access` tells the page
whether to show the controls, so it never infers that from a role name.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.file import FileAsset, RequirementFile
from app.models.user import User
from app.schemas.file import FileAssetOut, OrgResourceAccessOut, OrgResourceOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.rbac import (
    MANAGE_ORG_RESOURCES,
    get_effective_permissions,
    permission_satisfied,
    require_org_role,
    require_permission,
)

router = APIRouter(tags=["organizations-resources"])


@router.post("/{organization_id}/resources", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_resource(
    organization_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(MANAGE_ORG_RESOURCES)),
    db: Session = Depends(get_db),
):
    """Uploads a file as an organisation shared resource (C-M-03)."""
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream",
        data=data, is_org_resource=True,
    )
    log_event(db, entity_type="file_asset", entity_id=asset.id, action="uploaded",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{organization_id}/resources", response_model=list[OrgResourceOut])
def list_org_resources(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists the organisation's shared resources with each uploader's name and its number of linking records (two bulk reads)."""
    assets = db.scalars(
        select(FileAsset)
        .where(FileAsset.organization_id == organization_id, FileAsset.is_org_resource.is_(True))
        .order_by(FileAsset.created_at.desc())
    ).all()
    links: dict[UUID, int] = {}
    uploaders: dict[UUID, str] = {}
    if assets:
        rows = db.execute(
            select(RequirementFile.file_id, func.count())
            .where(RequirementFile.file_id.in_([a.id for a in assets]))
            .group_by(RequirementFile.file_id)
        )
        links = {file_id: count for file_id, count in rows}
        users = db.scalars(select(User).where(User.id.in_({a.uploaded_by for a in assets})))
        uploaders = {u.id: u.display_name for u in users}
    return [
        OrgResourceOut.model_validate(a).model_copy(
            update={"uploaded_by_display_name": uploaders.get(a.uploaded_by, ""), "link_count": links.get(a.id, 0)}
        )
        for a in assets
    ]


@router.get("/{organization_id}/resources/access", response_model=OrgResourceAccessOut)
def org_resources_access(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Whether the caller may upload and delete shared resources (the permission `POST` and `DELETE` require)."""
    held = get_effective_permissions(db, current_user.id, organization_id=organization_id)
    return OrgResourceAccessOut(can_manage=permission_satisfied(held, MANAGE_ORG_RESOURCES))


@router.delete("/{organization_id}/resources/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_resource(
    organization_id: UUID, file_id: UUID,
    current_user: User = Depends(require_permission(MANAGE_ORG_RESOURCES)),
    db: Session = Depends(get_db),
):
    asset = db.get(FileAsset, file_id)
    if asset is None or asset.organization_id != organization_id or not asset.is_org_resource:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
    db.execute(delete(RequirementFile).where(RequirementFile.file_id == file_id))
    delete_file(db, asset)
    log_event(db, entity_type="file_asset", entity_id=file_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()

