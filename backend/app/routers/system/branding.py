"""
Module: routers.system.branding

Platform-wide UI branding defaults: the accent colour/header title/email
footer/org-label overrides used on any page without a resolvable
organisation context (and as the fallback for orgs without their own
override), plus the platform-wide logo/login-background image upload. The
GET is deliberately unauthenticated — the plain `/login` page needs it
before any session exists.

Split out of the former flat `routers/system.py` as a pure code-organization
refactor — see `routers/system/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.schemas.branding import ServerSettingsOut, ServerSettingsUpdate
from app.services.audit import log_event
from app.services.branding import get_server_settings
from app.services.files import upload_file
from app.services.rbac import require_server_admin

router = APIRouter(tags=["system-branding"])


@router.get("/branding", response_model=ServerSettingsOut)
def get_branding(db: Session = Depends(get_db)):
    """Public, unauthenticated (no `current_user` dependency at all) —
    contains no sensitive fields, and is needed by the plain `/login` page
    to render its background image and header title before any session
    exists, in addition to the authenticated app shell's own chrome. Same
    reasoning as `orgs.py::get_org_login_info`, and why org/platform logos
    and login backgrounds are readable by anyone regardless of
    authentication (see `routers/files.py`)."""
    return get_server_settings(db)


@router.put("/branding", response_model=ServerSettingsOut)
def update_branding(
    payload: ServerSettingsUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sets the platform-wide default accent colour and header title, used
    on any page without a single resolvable organisation context, and as
    the fallback for any org that hasn't set its own override. Also sets the
    deployment-wide organisation label override (`org_label_singular`/
    `org_label_plural`) — unlike the rest of this endpoint's fields, that one
    has no per-org override to fall back from; it's platform-wide only."""
    settings = get_server_settings(db)
    settings.accent_color_hex = payload.accent_color_hex
    settings.default_header_title = payload.default_header_title
    settings.email_footer_company_name = payload.email_footer_company_name
    settings.email_footer_website = payload.email_footer_website
    settings.email_footer_address = payload.email_footer_address
    settings.org_label_singular = payload.org_label_singular
    settings.org_label_plural = payload.org_label_plural
    log_event(db, entity_type="system", entity_id="platform", action="branding_updated", actor_id=current_user.id)
    db.commit()
    db.refresh(settings)
    return settings


@router.post("/branding/image", response_model=ServerSettingsOut)
async def upload_branding_image(
    file: UploadFile = File(...),
    kind: Literal["logo", "login_background"] = Form(...),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Uploads the platform-wide default logo or login-page background
    image — merges the formerly-separate `POST /branding/logo`/
    `POST /branding/login-background` endpoints (2026-09-22, see
    docs/decisions.md) into one, dispatching on `kind`. Each branch
    preserves its original endpoint's exact file-handling/FK-field/
    audit-log-string logic. `FileAsset.organization_id` is a required
    column (files are normally organisation-scoped for storage-key
    namespacing and access control), but a platform-wide asset has no
    owning organisation — it's stored against whichever organisation
    happens to exist first, purely for that namespacing, and served to any
    authenticated user via the same "avatar or logo" bypass already used
    for org logos and user avatars (`routers/files.py::download_file`), not
    by organisation membership.

    Note: there is no system-level revert-to-default for either `kind` —
    unlike the org-level `DELETE /orgs/{id}/branding-image`, the platform
    tier has nothing to fall back to. Pre-existing asymmetry, not
    introduced by this merge.
    """
    any_org = db.scalar(select(Organization))
    if any_org is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No organisation exists yet to store this file against.")
    data = await file.read()
    default_filename = "logo" if kind == "logo" else "login-background"
    asset = upload_file(
        db, organization_id=any_org.id, uploaded_by=current_user.id,
        filename=file.filename or default_filename,
        content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    settings = get_server_settings(db)
    if kind == "logo":
        settings.default_logo_file_id = asset.id
        action = "branding_logo_updated"
    else:
        settings.default_login_background_file_id = asset.id
        action = "branding_login_background_updated"
    log_event(db, entity_type="system", entity_id="platform", action=action,
              actor_id=current_user.id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(settings)
    return settings
