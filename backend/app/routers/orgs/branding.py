"""
Module: routers.orgs.branding

Organisation branding: logo/login-background image upload and revert
(U-C-02, E-P-03), accent colour/wordmark/email-footer branding, the default
template project (C-E-04), and the public branded-login-page lookup.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.user import User
from app.schemas.org import DefaultTemplateUpdate, OrganizationOut, OrgBrandingUpdate, OrgLoginInfoOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-branding"])


@router.post("/{organization_id}/branding-image", response_model=OrganizationOut)
async def upload_org_branding_image(
    organization_id: UUID,
    file: UploadFile = File(...),
    kind: Literal["logo", "login_background"] = Form(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Uploads this organisation's logo (U-C-02) or login-page background
    image (E-P-03) — merges the formerly-separate `POST /logo`/
    `POST /login-background` endpoints (2026-09-22, see docs/decisions.md)
    into one, dispatching on `kind`. Each branch preserves its original
    endpoint's exact file-handling/FK-field/audit-log-string logic."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    data = await file.read()
    default_filename = "logo" if kind == "logo" else "login-background"
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or default_filename,
        content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    if kind == "logo":
        org.logo_file_id = asset.id
        action = "logo_updated"
    else:
        org.login_background_file_id = asset.id
        action = "login_background_updated"
    log_event(db, entity_type="organization", entity_id=organization_id, action=action,
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(org)
    return org


@router.delete("/{organization_id}/branding-image", response_model=OrganizationOut)
def delete_org_branding_image(
    organization_id: UUID,
    kind: Literal["logo", "login_background"] = Query(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Reverts this organisation's logo or login-page background image back
    to the platform default by clearing the override (U-C-02/E-P-03's
    missing revert path) — merges the formerly-separate `DELETE /logo`/
    `DELETE /login-background` endpoints (2026-09-22, see docs/decisions.md)
    into one, dispatching on `kind`. A no-op, not a 404, when there's
    nothing set for the requested `kind` — this is a "make sure it's unset"
    action, not a delete of a specific known record."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    field = "logo_file_id" if kind == "logo" else "login_background_file_id"
    action = "logo_removed" if kind == "logo" else "login_background_removed"
    file_id = getattr(org, field)
    if file_id is not None:
        asset = db.get(FileAsset, file_id)
        setattr(org, field, None)
        db.flush()
        if asset is not None:
            delete_file(db, asset)
        log_event(db, entity_type="organization", entity_id=organization_id, action=action,
                  actor_id=current_user.id, organization_id=organization_id)
        db.commit()
        db.refresh(org)
    return org


@router.put("/{organization_id}/branding", response_model=OrganizationOut)
def update_org_branding(
    organization_id: UUID, payload: OrgBrandingUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets (or clears, with null values) this organisation's UI accent
    colour, header wordmark override (U-C-01 override), and outgoing-email
    footer identity. All fall back to the platform default
    (`GET /system/branding`) when null — this endpoint never needs to know
    what that default is, it just clears its own override."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.accent_color_hex = payload.accent_color_hex
    org.header_title = payload.header_title
    org.email_footer_company_name = payload.email_footer_company_name
    org.email_footer_website = payload.email_footer_website
    org.email_footer_address = payload.email_footer_address
    log_event(db, entity_type="organization", entity_id=organization_id, action="branding_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return org


@router.put("/{organization_id}/default-template", response_model=OrganizationOut)
def set_default_template(
    organization_id: UUID, payload: DefaultTemplateUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets (or clears, with `project_id: null`) the default template project used
    when creating a new project in this organisation (C-E-04)."""
    from app.models.project import Project

    org = db.get(Organization, organization_id)
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.organization_id != organization_id or not project.is_template:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id must be a template project in this organisation.")
    org.default_template_project_id = payload.project_id
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="default_template_updated",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"project_id": str(payload.project_id) if payload.project_id else None},
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("/by-slug/{slug}/login-info", response_model=OrgLoginInfoOut)
def get_org_login_info(slug: str, db: Session = Depends(get_db)):
    """Public, unauthenticated lookup used by the org-branded login page
    (`/login/{slug}` in the frontend) to render branding and decide whether
    to show a "Sign in with SSO" button. Returns no secrets."""
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgLoginInfoOut(
        name=org.name, slug=org.slug, logo_file_id=org.logo_file_id,
        login_background_file_id=org.login_background_file_id,
        sso_enabled=org.sso_enabled, sso_only=org.sso_only,
    )

