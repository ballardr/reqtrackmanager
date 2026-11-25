"""
Module: routers.files

The generic download endpoint for uploaded files (I-M-10) and `GET /{file_id}/details` (a picture's size and
EXIF), which follows the same read rule. Upload and delete are context-specific endpoints elsewhere (each has its
own payload and validation); downloading needs only the file id, so authorisation is context-sensitive here:
- Organisation/platform logos and login-page backgrounds are public: they render on the pre-login pages.
- Avatars are viewable by any authenticated user (shared UI chrome), not anonymously.
- Organisation shared resources require membership in that organisation.
- Requirement, action and comment attachments (on a requirement or change request) require project view
  access to the owning project.
- A module-owned attachment (e.g. Compliance evidence) resolves to its project via
  `app.modules.registry.resolve_module_file_project_id`, a generic hook, so this router never imports a
  specific module's file-link table.
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_user_header_or_query_optional
from app.models.change_request import ChangeRequest, ReviewComment
from app.models.enums import ReviewTargetType
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.organization import Organization, ServerSettings
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.modules.registry import resolve_module_file_project_id
from app.schemas.file import FileAssetOut, FileConfidentialIn, FileDetailsOut
from app.services.audit import log_event
from app.services.downloads import content_disposition
from app.services.files import read_file
from app.services.image_details import image_details
from app.services.rbac import (
    _project_organization_id,
    _require_org_active,
    can_manage_project_settings,
    check_pat_scope,
    check_pat_scope_for_project,
    get_effective_org_roles,
    get_effective_project_roles,
    is_org_admin,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])

# Content types safe to render inline in a browser tab; everything else is forced to download. `content_type`
# is whatever the uploader's client claimed (never validated against the bytes), so serving an arbitrary
# claimed type inline would let an uploader (any project editor, or any user for their own avatar) store
# `text/html` or `image/svg+xml` that runs as a same-origin page when a more privileged user opens it,
# reading the `?token=` query parameter this endpoint accepts and `localStorage` (stored XSS to account
# takeover). SVG is excluded though it is an image format, since it can embed script and event handlers.
_INLINE_SAFE_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/x-icon", "application/pdf",
}


def _authorise_read(request: Request, db: Session, file_asset: FileAsset, current_user: User | None) -> UUID | None:
    """Raises unless the caller may read `file_asset`: the one access rule for downloading a file and for reading its details.

    Returns:
        The project that owns the file when it is a project attachment, else `None` (branding, avatar, organisation resource).

    Raises:
        HTTPException: 401 with no credential (anything but public branding), 403 without a role that reaches the file.
    """
    file_id = file_asset.id
    # No server-admin bypass (I-M-05): uploaded files are data within organisations. Logos and login-page
    # backgrounds are public (no authentication) because they render on the pre-login pages, and are exempt
    # from the Personal Access Token org-scope check below as /auth/me and other personal cross-org endpoints
    # are (docs/decisions.md's "Personal Access Tokens" section). The platform-wide defaults
    # (`ServerSettings.default_logo_file_id` / `default_login_background_file_id`) belong here too; their
    # `FileAsset` rows are platform-owned (no organisation).
    is_public_branding = (
        db.scalar(select(Organization).where(Organization.logo_file_id == file_id)) is not None
        or db.scalar(select(Organization).where(Organization.login_background_file_id == file_id)) is not None
        or db.scalar(select(ServerSettings).where(ServerSettings.default_logo_file_id == file_id)) is not None
        or db.scalar(select(ServerSettings).where(ServerSettings.default_login_background_file_id == file_id)) is not None
    )
    project_id: UUID | None = None
    if not is_public_branding:
        if current_user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
        # A platform-owned file that is no longer the platform logo or login background (replaced or removed) has no
        # organisation whose members could read it.
        if file_asset.organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
        owner_org_id = file_asset.organization_id
        # Avatars are the one remaining category open to any authenticated
        # user regardless of org membership (shown in shared UI chrome), but
        # unlike the public-branding bucket above, not to anonymous callers.
        is_avatar = db.scalar(select(User).where(User.avatar_file_id == file_id)) is not None
        if not is_avatar:
            if file_asset.is_org_resource:
                # The user is resolved through get_current_user_header_or_query_optional, not a
                # services.rbac `require_*` factory (it must accept a `?token=` query parameter for
                # `<img src>`), so the Personal Access Token org-scope restriction those factories apply is
                # not automatic and is checked explicitly, in addition to the RBAC role check below.
                check_pat_scope(request, owner_org_id)
                _require_org_active(db, owner_org_id)
                if not get_effective_org_roles(db, current_user.id, owner_org_id):
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
            else:
                # A picture in a project's report-image library belongs to that project directly.
                project_id = file_asset.project_id
                link = db.scalar(select(RequirementFile).where(RequirementFile.file_id == file_id)) if project_id is None else None
                if link is not None:
                    requirement = db.get(Requirement, link.requirement_id)
                    project_id = requirement.project_id if requirement is not None else None
                elif project_id is None:
                    # Not a requirement attachment: check for a requirement action attachment
                    # (routers/actions.py::upload_action_attachment). `RequirementAction` has its own
                    # `project_id`: an action can be linked to several requirements via untyped
                    # `ArtefactLink` rows, so there is no single requirement to resolve through.
                    action_link = db.scalar(select(RequirementActionFile).where(RequirementActionFile.file_id == file_id))
                    if action_link is not None:
                        action = db.get(RequirementAction, action_link.action_id)
                        project_id = action.project_id if action is not None else None
                    else:
                        # Not an action attachment either: check for a comment attachment
                        # (`upload_comment_attachment` in routers/requirements.py and routers/change_requests),
                        # which resolves to a project through the entity the comment is on.
                        comment_link = db.scalar(select(CommentFile).where(CommentFile.file_id == file_id))
                        comment = db.get(ReviewComment, comment_link.comment_id) if comment_link else None
                        if comment is not None and comment.target_type == ReviewTargetType.REQUIREMENT:
                            requirement = db.get(Requirement, comment.target_id)
                            project_id = requirement.project_id if requirement is not None else None
                        elif comment is not None and comment.target_type == ReviewTargetType.CHANGE_REQUEST:
                            cr = db.get(ChangeRequest, comment.target_id)
                            project_id = cr.project_id if cr is not None else None
                        if project_id is None:
                            # Not a core attachment type: try every registered module's file-ownership hook
                            # (e.g. Compliance evidence). Generic by design: this router never imports a
                            # specific module's models.
                            project_id = resolve_module_file_project_id(db, file_id)
                if project_id is not None:
                    check_pat_scope_for_project(request, db, project_id)
                    organization_id = _project_organization_id(db, project_id)
                    if organization_id is not None:
                        _require_org_active(db, organization_id)
                has_access = project_id is not None and get_effective_project_roles(db, current_user.id, project_id)
                if not has_access:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this file.")
    return project_id


@router.get("/{file_id}")
def download_file(
    file_id: UUID,
    request: Request,
    current_user: User | None = Depends(get_current_user_header_or_query_optional),
    db: Session = Depends(get_db),
):
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    _authorise_read(request, db, file_asset, current_user)

    data = read_file(file_asset)
    disposition = "inline" if file_asset.content_type in _INLINE_SAFE_CONTENT_TYPES else "attachment"
    return Response(
        content=data, media_type=file_asset.content_type,
        headers={
            "Content-Disposition": content_disposition(disposition, file_asset.filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{file_id}/details", response_model=FileDetailsOut)
def file_details(
    file_id: UUID,
    request: Request,
    current_user: User | None = Depends(get_current_user_header_or_query_optional),
    db: Session = Depends(get_db),
) -> FileDetailsOut:
    """What a picture file says about itself (pixel size and any EXIF: when taken, camera, description, position).

    Open to exactly the people who may download the file (`_authorise_read`), and never to an anonymous caller even for a
    public logo. A file that is not a raster picture answers with every field empty. The text is the file's own, shown as
    text only; nothing is logged.
    """
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if current_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    _authorise_read(request, db, file_asset, current_user)
    return FileDetailsOut(**asdict(image_details(read_file(file_asset))))


@router.patch("/{file_id}/confidential", response_model=FileAssetOut)
def set_file_confidential(
    file_id: UUID,
    body: FileConfidentialIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileAsset:
    """Marks a file confidential (or clears the mark): a confidential file is never printed by a report.

    The mark affects only reports' record-image rules; who may open the file is unchanged. Allowed to the
    uploader and to those who manage its project (an organisation resource: the organisation's admins); any
    other reader gets 403, so a reader cannot remove the mark. Audited with the file id and new value, never
    the file name.

    A write: it takes the bearer header only, never the URL media token (which only loads files into the
    page), and so also passes the policy acknowledgement gate.

    Raises:
        HTTPException: 401 without a credential, 404 for an unknown file, 403 when the caller may not change the mark.
    """
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    project_id = _authorise_read(request, db, file_asset, current_user)
    project = db.get(Project, project_id) if project_id is not None else None
    allowed = file_asset.uploaded_by == current_user.id
    if not allowed and project is not None:
        allowed = can_manage_project_settings(db, current_user, project)
    if not allowed and file_asset.is_org_resource and file_asset.organization_id is not None:
        allowed = is_org_admin(db, current_user.id, file_asset.organization_id)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the uploader or a project manager can change this.")
    if file_asset.confidential != body.confidential:
        file_asset.confidential = body.confidential
        log_event(
            db, entity_type="file", entity_id=file_asset.id, action="confidential_set" if body.confidential else "confidential_cleared",
            actor_id=current_user.id, organization_id=file_asset.organization_id, project_id=project_id,
            detail={"confidential": body.confidential},
        )
        db.commit()
        db.refresh(file_asset)
    return file_asset
