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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user_header_or_query
from app.models.file import FileAsset, RequirementFile
from app.models.organization import Organization, ServerSettings
from app.models.requirement import Requirement
from app.models.user import User
from app.services.files import read_file
from app.services.rbac import (
    _project_organization_id,
    _require_org_active,
    check_pat_scope,
    check_pat_scope_for_project,
    get_effective_org_roles,
    get_effective_project_roles,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])

# Content types safe to render inline in a browser tab. Everything else is
# forced to download as an attachment instead — `content_type` is whatever
# the uploader's client claimed at upload time (never validated against the
# actual bytes), so serving an arbitrary claimed type "inline" would let any
# user with upload rights (a low bar: any project editor, or any user at all
# for their own avatar) store e.g. `text/html` or `image/svg+xml` content
# and have it execute as a same-origin page when a more privileged user
# opens the link — including reading the `?token=` query parameter this
# same endpoint accepts (see `get_current_user_header_or_query`) and
# `localStorage`, i.e. a stored-XSS-to-account-takeover path. SVG is
# deliberately excluded even though it's an image format, since it can
# embed `<script>`/event-handler payloads the same way HTML can.
_INLINE_SAFE_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/x-icon", "application/pdf",
}


@router.get("/{file_id}")
def download_file(
    file_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user_header_or_query),
    db: Session = Depends(get_db),
):
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")

    # No server-admin bypass (I-M-05): uploaded files are "data within
    # organisations". Avatars/logos are the one category that's genuinely
    # open to any authenticated user regardless of org membership, since
    # they're shown in shared UI chrome — also deliberately exempt from the
    # Personal Access Token org-scope check below, for the same reason
    # /auth/me and other personal, cross-org endpoints are (see
    # docs/decisions.md's "Personal Access Tokens" section). The platform-wide
    # default logo (`ServerSettings.default_logo_file_id`) belongs in this
    # same bucket for the same reason, even though its `FileAsset` row is
    # nominally owned by whichever organisation it happened to be stored
    # against (see `routers/system.py::upload_branding_logo`) — that
    # ownership is a storage-key implementation detail, not an access rule.
    is_avatar_or_logo = (
        db.scalar(select(User).where(User.avatar_file_id == file_id)) is not None
        or db.scalar(select(Organization).where(Organization.logo_file_id == file_id)) is not None
        or db.scalar(select(ServerSettings).where(ServerSettings.default_logo_file_id == file_id)) is not None
    )
    if not is_avatar_or_logo:
        if file_asset.is_org_resource:
            # This endpoint resolves the current user via
            # get_current_user_header_or_query rather than one of
            # services.rbac's require_* dependency factories (it needs to
            # accept a ?token= query param for <img src> use, which those
            # don't support) — so the Personal Access Token org-scope
            # restriction those factories apply isn't automatic here and
            # must be checked explicitly, in addition to (not instead of)
            # the real RBAC role check below.
            check_pat_scope(request, file_asset.organization_id)
            _require_org_active(db, file_asset.organization_id)
            if not get_effective_org_roles(db, current_user.id, file_asset.organization_id):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
        else:
            link = db.scalar(select(RequirementFile).where(RequirementFile.file_id == file_id))
            requirement = db.get(Requirement, link.requirement_id) if link else None
            if requirement is not None:
                check_pat_scope_for_project(request, db, requirement.project_id)
                organization_id = _project_organization_id(db, requirement.project_id)
                if organization_id is not None:
                    _require_org_active(db, organization_id)
            has_access = requirement is not None and get_effective_project_roles(
                db, current_user.id, requirement.project_id
            )
            if not has_access:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this file.")

    data = read_file(file_asset)
    disposition = "inline" if file_asset.content_type in _INLINE_SAFE_CONTENT_TYPES else "attachment"
    return Response(
        content=data, media_type=file_asset.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{file_asset.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
