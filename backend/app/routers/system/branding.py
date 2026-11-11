"""
Module: routers.system.branding

Platform-wide UI branding defaults: the accent colour/header title/email
footer/org-label overrides used on any page without a resolvable
organisation context (and as the fallback for orgs without their own
override), plus the platform-wide logo/login-background image upload and
removal. The
GET is deliberately unauthenticated — the plain `/login` page needs it
before any session exists.

Split out of the former flat `routers/system.py` as a pure code-organization
refactor — see `routers/system/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.user import User
from app.schemas.branding import ServerSettingsOut, ServerSettingsUpdate
from app.services.audit import log_event
from app.services.branding import get_server_settings
from app.services.files import delete_file, upload_file
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
    """Sets the platform-wide default accent colour, header title and email footer details, used on any page without a
    single resolvable organisation context, and as the fallback for any org that hasn't set its own override. Also sets
    the deployment-wide organisation label override (`org_label_singular`/`org_label_plural`), which has no per-org
    override to fall back from.

    A partial update: only the fields in the request body change, so the Server details and Branding pages cannot
    overwrite each other. The audit event names the fields changed, never their values.
    """
    settings = get_server_settings(db)
    sent = payload.model_fields_set
    for field in sorted(sent):
        setattr(settings, field, getattr(payload, field))
    log_event(db, entity_type="system", entity_id="platform", action="branding_updated", actor_id=current_user.id,
              detail={"fields": sorted(sent)})
    db.commit()
    db.refresh(settings)
    return settings


def _platform_image_field(kind: str) -> str:
    """Returns the `ServerSettings` column holding the platform file of `kind`."""
    return "default_logo_file_id" if kind == "logo" else "default_login_background_file_id"


@router.post("/branding/image", response_model=ServerSettingsOut)
async def upload_branding_image(
    file: UploadFile = File(...),
    kind: Literal["logo", "login_background"] = Form(...),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Uploads the platform-wide default logo or login-page background image, replacing (and deleting) the previous one.

    The file is platform-owned (`FileAsset.organization_id` is NULL), so no organisation's deletion, storage limit or upload
    switch can remove or refuse it; only the deployment-wide upload switch applies. It is served to anyone through the
    public-branding bypass in `routers/files.py::download_file`, not by organisation membership.

    Raises:
        HTTPException: 403 while uploads are disabled deployment-wide, 413 for a file over the size limit.
    """
    data = await file.read()
    default_filename = "logo" if kind == "logo" else "login-background"
    asset = upload_file(
        db, organization_id=None, uploaded_by=current_user.id,
        filename=file.filename or default_filename,
        content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    settings = get_server_settings(db)
    field = _platform_image_field(kind)
    previous_id = getattr(settings, field)
    setattr(settings, field, asset.id)
    db.flush()
    previous = db.get(FileAsset, previous_id) if previous_id is not None else None
    if previous is not None:
        delete_file(db, previous)
    log_event(db, entity_type="system", entity_id="platform",
              action="branding_logo_updated" if kind == "logo" else "branding_login_background_updated",
              actor_id=current_user.id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(settings)
    return settings


@router.delete("/branding/image", response_model=ServerSettingsOut)
def delete_branding_image(
    kind: Literal["logo", "login_background"] = Query(...),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Reverts the platform logo or login-page background to the built-in picture by removing the uploaded file.

    A no-op, not a 404, when nothing is set for `kind`: the request means "make sure it is unset".
    """
    settings = get_server_settings(db)
    field = _platform_image_field(kind)
    file_id = getattr(settings, field)
    if file_id is not None:
        asset = db.get(FileAsset, file_id)
        setattr(settings, field, None)
        db.flush()
        if asset is not None:
            delete_file(db, asset)
        log_event(db, entity_type="system", entity_id="platform",
                  action="branding_logo_removed" if kind == "logo" else "branding_login_background_removed",
                  actor_id=current_user.id)
        db.commit()
        db.refresh(settings)
    return settings
