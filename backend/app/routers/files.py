"""
Module: routers.files

A single generic download endpoint for uploaded files (I-M-10), and `GET /{file_id}/details` (a picture's size and EXIF),
which follows exactly the same read rule. Upload and
delete are handled by context-specific endpoints elsewhere (org shared
resources and org logo in routers/orgs.py, requirement attachments in
routers/requirements.py, avatars in routers/auth.py) since each has a
different payload/validation shape — but downloading only ever needs the
file id, so it is unified here with context-sensitive authorization:
- Organisation/platform logos and login-page background images are public
  (no authentication required at all) — they're rendered on the pre-login
  pages (`/login`, `/login/{slug}`) before any session exists, as well as in
  authenticated UI chrome.
- Avatars are viewable by any authenticated user (shown in shared UI chrome
  regardless of org membership), but not anonymously.
- Organisation shared resources require membership in that organisation.
- Direct requirement attachments, requirement action attachments, and
  comment attachments (on either a requirement or a change request's
  discussion thread), require project view access to whichever project the
  attachment's requirement/action/change request belongs to.
- A module-owned attachment (e.g. Compliance evidence) is resolved to its owning project via `app.modules.
  registry.resolve_module_file_project_id` — a generic hook every module
  can implement, so this core, module-agnostic router never needs to
  import a specific module's own file-link table directly (the same
  "core code shouldn't need much modification per module" goal the rest
  of the modular feature system already serves for HTTP endpoints).
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user_header_or_query_optional
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


def _authorise_read(request: Request, db: Session, file_asset: FileAsset, current_user: User | None) -> UUID | None:
    """Raises unless the caller may read `file_asset`: the one access rule for downloading a file and for reading its details.

    Returns:
        The project that owns the file when it is a project attachment, else `None` (branding, avatar, organisation resource).

    Raises:
        HTTPException: 401 with no credential (anything but public branding), 403 without a role that reaches the file.
    """
    file_id = file_asset.id
    # No server-admin bypass (I-M-05): uploaded files are "data within
    # organisations". Logos and login-page background images are public,
    # served with no authentication at all, since they're rendered on the
    # pre-login pages (`/login`, `/login/{slug}`) before any session exists
    # — also deliberately exempt from the Personal Access Token org-scope
    # check below, for the same reason /auth/me and other personal,
    # cross-org endpoints are (see docs/decisions.md's "Personal Access
    # Tokens" section). The platform-wide defaults
    # (`ServerSettings.default_logo_file_id` /
    # `default_login_background_file_id`) belong in this same bucket for the
    # same reason, even though their `FileAsset` rows are nominally owned by
    # whichever organisation they happened to be stored against (see
    # `routers/system.py::upload_branding_image`) — that ownership is a
    # storage-key implementation detail, not an access rule.
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
        # Avatars are the one remaining category open to any authenticated
        # user regardless of org membership (shown in shared UI chrome), but
        # unlike the public-branding bucket above, not to anonymous callers.
        is_avatar = db.scalar(select(User).where(User.avatar_file_id == file_id)) is not None
        if not is_avatar:
            if file_asset.is_org_resource:
                # This endpoint resolves the current user via
                # get_current_user_header_or_query_optional rather than one
                # of services.rbac's require_* dependency factories (it
                # needs to accept a ?token= query param for <img src> use,
                # which those don't support) — so the Personal Access Token
                # org-scope restriction those factories apply isn't
                # automatic here and must be checked explicitly, in addition
                # to (not instead of) the real RBAC role check below.
                check_pat_scope(request, file_asset.organization_id)
                _require_org_active(db, file_asset.organization_id)
                if not get_effective_org_roles(db, current_user.id, file_asset.organization_id):
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
            else:
                # A picture in a project's report-image library belongs to that project directly.
                project_id = file_asset.project_id
                link = db.scalar(select(RequirementFile).where(RequirementFile.file_id == file_id)) if project_id is None else None
                if link is not None:
                    requirement = db.get(Requirement, link.requirement_id)
                    project_id = requirement.project_id if requirement is not None else None
                elif project_id is None:
                    # Not a requirement attachment — check whether it's a
                    # requirement action attachment instead
                    # (routers/actions.py::upload_action_attachment).
                    # Regression fix: this branch didn't exist before, so an
                    # action-attached file's project_id always stayed None
                    # here and fell through to the unconditional 403 below —
                    # action attachments could never actually be downloaded
                    # by anyone, including the uploader, even though
                    # upload/list/delete all worked. `RequirementAction` has
                    # its own direct `project_id` (unlike a requirement
                    # attachment, an action isn't owned by exactly one
                    # requirement — it can be linked to several via an
                    # untyped `ArtefactLink` row — so there's no single
                    # requirement to resolve through).
                    action_link = db.scalar(select(RequirementActionFile).where(RequirementActionFile.file_id == file_id))
                    if action_link is not None:
                        action = db.get(RequirementAction, action_link.action_id)
                        project_id = action.project_id if action is not None else None
                    else:
                        # Not an action attachment either — check whether
                        # it's a comment attachment instead
                        # (routers/requirements.py and
                        # routers/change_requests.py's
                        # upload_comment_attachment), which resolves to a
                        # project via whichever entity the comment itself is
                        # on.
                        comment_link = db.scalar(select(CommentFile).where(CommentFile.file_id == file_id))
                        comment = db.get(ReviewComment, comment_link.comment_id) if comment_link else None
                        if comment is not None and comment.target_type == ReviewTargetType.REQUIREMENT:
                            requirement = db.get(Requirement, comment.target_id)
                            project_id = requirement.project_id if requirement is not None else None
                        elif comment is not None and comment.target_type == ReviewTargetType.CHANGE_REQUEST:
                            cr = db.get(ChangeRequest, comment.target_id)
                            project_id = cr.project_id if cr is not None else None
                        if project_id is None:
                            # Not a core attachment type either — try every
                            # registered module's own file-ownership hook
                            # (e.g. Compliance evidence) before
                            # giving up. Generic by design: this router
                            # never imports a specific module's models.
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
    current_user: User | None = Depends(get_current_user_header_or_query_optional),
    db: Session = Depends(get_db),
) -> FileAsset:
    """Marks a file confidential (or clears the mark): a confidential file is never printed by a report.

    The mark affects only reports' record-image rules; who may open the file is unchanged. Allowed to the person who
    uploaded the file and to those who manage its project (an organisation resource: the organisation's admins). Anyone
    else who can read the file gets 403, so the mark cannot be removed by a reader. Audited with the file id and the new
    value, never the file name.

    Raises:
        HTTPException: 401 without a credential, 404 for an unknown file, 403 when the caller may not change the mark.
    """
    file_asset = db.get(FileAsset, file_id)
    if file_asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if current_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    project_id = _authorise_read(request, db, file_asset, current_user)
    project = db.get(Project, project_id) if project_id is not None else None
    allowed = file_asset.uploaded_by == current_user.id
    if not allowed and project is not None:
        allowed = can_manage_project_settings(db, current_user, project)
    if not allowed and file_asset.is_org_resource:
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
