"""
Module: routers.system.config

Deployment-wide configuration and build metadata: the running backend's
build identity, the server-wide public self-signup mode, and the
deployment-wide SMTP test-email action. `GET /signup-config` is
deliberately unauthenticated (the signup form's first call happens before
any session exists), same reasoning as `branding.get_branding`.

Split out of the former flat `routers/system.py` as a pure code-organization
refactor — see `routers/system/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.enums import SignupMode
from app.models.organization import Organization
from app.models.user import User
from app.schemas.email import TestEmailRequest
from app.schemas.signup import SelfSignupOrgOut, SignupConfigOut, SignupConfigUpdate
from app.services.audit import log_event
from app.services.branding import get_server_settings
from app.services.email import send_email
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email
from app.services.rbac import require_server_admin
from app.version import APP_VERSION, BUILD_DATE, GIT_SHA

router = APIRouter(tags=["system-config"])
settings = get_settings()


class VersionOut(BaseModel):
    """The running backend's own build identity — see `app.version`."""

    version: str
    git_sha: str
    build_date: str


@router.get("/version", response_model=VersionOut)
def get_version(current_user: User = Depends(get_current_user)) -> VersionOut:
    """Returns the running backend's semantic version, commit SHA, and
    build timestamp, for display alongside the frontend's own (bundled at
    build time) build identity — a way to confirm what's actually deployed
    without shell access. Any authenticated user may call this; it's build
    metadata, not data within an organisation, so no `require_server_admin`
    gate (same reasoning as `/health`, just requiring a session since this
    lives under `/api/v1` rather than being a bare infra probe).
    """
    return VersionOut(version=APP_VERSION, git_sha=GIT_SHA, build_date=BUILD_DATE)


@router.post("/test-email", status_code=status.HTTP_204_NO_CONTENT)
def send_system_test_email(
    payload: TestEmailRequest,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sends a test email through the deployment-wide SMTP configuration
    (`Settings.smtp_*`, `config.py`) — lets a server admin confirm outgoing
    mail (C-N-03) actually works without waiting for a real notification to
    trigger one. The organisation-scoped equivalent for an org with its own
    SMTP override is `routers/orgs.py::send_org_test_email`.

    Raises:
        HTTPException: 502 if the send itself fails (bad credentials,
            unreachable host, ...) — surfaced with the underlying error so
            the admin knows what to fix, since confirming deliverability is
            the entire point of this action.
    """
    to_email = payload.to_email or current_user.email
    branding = resolve_email_branding(db, organization_id=None)
    html_body, text_body = render_email(
        "test_email", branding=branding, source_description="ReqTrackManager's deployment-wide SMTP configuration",
        cta_url=settings.frontend_base_url,
    )
    inline_images = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
    try:
        send_email(to_email, "ReqTrackManager test email", text_body, html_body=html_body, inline_images=inline_images)
    except Exception as err:  # noqa: BLE001 - surfacing the underlying SMTP failure is the entire point of a test-email action
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to send test email: {err}") from err
    log_event(db, entity_type="system", entity_id="platform", action="test_email_sent",
              actor_id=current_user.id, detail={"to": to_email})
    db.commit()


# --- Public self-signup mode -------------------------------------------------


@router.get("/signup-config", response_model=SignupConfigOut)
def get_signup_config(db: Session = Depends(get_db)):
    """Public, unauthenticated (no `current_user` dependency at all — the
    signup form's first call happens before any session exists, same as
    `orgs.py::get_org_login_info`). Only lists organisation *names* open to
    `ORG_SPECIFIED` self-signup, never their configured email domain — see
    `SelfSignupOrgOut`'s docstring."""
    server_settings = get_server_settings(db)
    orgs: list[SelfSignupOrgOut] = []
    if server_settings.signup_mode == SignupMode.ORG_SPECIFIED:
        orgs = [
            SelfSignupOrgOut(id=org.id, name=org.name)
            for org in db.scalars(
                select(Organization).where(
                    Organization.allow_self_signup.is_(True), Organization.is_active.is_(True)
                )
            ).all()
        ]
    return SignupConfigOut(signup_mode=server_settings.signup_mode, self_signup_organizations=orgs)


@router.put("/signup-config", response_model=SignupConfigOut)
def update_signup_config(
    payload: SignupConfigUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sets the server-wide public self-signup mode (server-admin only)."""
    server_settings = get_server_settings(db)
    server_settings.signup_mode = payload.signup_mode
    log_event(db, entity_type="system", entity_id="platform", action="signup_mode_updated",
              actor_id=current_user.id, detail={"signup_mode": payload.signup_mode.value})
    db.commit()
    db.refresh(server_settings)
    return get_signup_config(db)
