"""
Module: routers.files

A single generic download endpoint for uploaded files (I-M-10). Upload and
delete are handled by context-specific endpoints elsewhere (org shared
resources and org logo in routers/orgs.py, requirement attachments in
routers/requirements.py, avatars in routers/auth.py) since each has a
different payload/validation shape — but downloading only ever needs the
file id, so it is unified here with context-sensitive authorization:
- Avatars and organisation logos are viewable by any authenticated user
  (they're shown in shared UI chrome regardless of org membership).
- Organisation shared resources require membership in that organisation.
- Direct requirement attachments require project view access.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user_header_or_query
from app.models.file import FileAsset, RequirementFile
from app.models.organization import Organization
from app.models.requirement import Requirement
from app.models.user import User
from app.services.files import read_file
from app.services.rbac import get_effective_org_roles, get_effective_project_roles

router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.get("/{file_id}")
def download_file(
    file_id: UUID, current_user: User = Depends(get_current_user_header_or_query), db: Session = Depends(get_db)
):
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")

    if not current_user.is_server_admin:
        is_avatar_or_logo = (
            db.scalar(select(User).where(User.avatar_file_id == file_id)) is not None
            or db.scalar(select(Organization).where(Organization.logo_file_id == file_id)) is not None
        )
        if not is_avatar_or_logo:
            if file_asset.is_org_resource:
                if not get_effective_org_roles(db, current_user.id, file_asset.organization_id):
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
            else:
                link = db.scalar(select(RequirementFile).where(RequirementFile.file_id == file_id))
                requirement = db.get(Requirement, link.requirement_id) if link else None
                has_access = requirement is not None and get_effective_project_roles(
                    db, current_user.id, requirement.project_id
                )
                if not has_access:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this file.")

    data = read_file(file_asset)
    return Response(
        content=data, media_type=file_asset.content_type,
        headers={"Content-Disposition": f'inline; filename="{file_asset.filename}"'},
    )
