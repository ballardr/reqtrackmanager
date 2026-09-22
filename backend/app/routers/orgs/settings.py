"""
Module: routers.orgs.settings

Organisation-level settings: advanced settings (SMTP override, security/
self-signup flags), module system Phase 1 enablement + Phase 3 frame-token
minting, the SMTP-override test-send action, SSO/OIDC configuration, and
SCIM token lifecycle.

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.enums import OrgRole
from app.models.module import OrganizationModuleEnablement
from app.models.organization import Organization
from app.models.user import User
from app.modules.registry import get_frontend_manifest, get_module_registry, is_module_enabled, is_module_entitled
from app.schemas.email import TestEmailRequest
from app.schemas.org import (
    ModuleFrameTokenOut,
    ModuleFrontendManifestOut,
    OrgAdvancedSettingsOut,
    OrgAdvancedSettingsUpdate,
    OrgModuleEnablementUpdate,
    OrgModuleOut,
    OrgSsoConfigOut,
    OrgSsoConfigUpdate,
    ScimTokenCreatedOut,
    ScimTokenStatusOut,
)
from app.security import create_module_frame_token, generate_scim_token
from app.services.audit import log_event
from app.services.email import SmtpOverride, send_email
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email
from app.services.rbac import require_org_module_enabled_dynamic, require_org_role

router = APIRouter(tags=["organizations-settings"])
settings = get_settings()


@router.get("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def get_advanced_settings(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Per-organisation SMTP override and security/self-signup settings.

    `smtp_*` remain storage-only (see `Organization` model docstring). The
    stored `smtp_password` is never echoed back (write-only), matching how
    the bootstrap/native-auth password is handled elsewhere. SSO group→role
    mapping used to live here (`sso_group_mappings`) — it's now managed per
    `OrgGroup` instead (`GET .../groups`, item 522).
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls,
        pat_max_lifetime_days=org.pat_max_lifetime_days, require_2fa=org.require_2fa,
        allow_self_signup=org.allow_self_signup, auto_accept_email_domain=org.auto_accept_email_domain,
        external_user_policy=org.external_user_policy,
        allow_relaxed_child_project_creation=org.allow_relaxed_child_project_creation,
        force_require_change_request_for_approved_links=org.force_require_change_request_for_approved_links,
        allow_ai_approvals=org.allow_ai_approvals,
    )


@router.put("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def update_advanced_settings(
    organization_id: UUID, payload: OrgAdvancedSettingsUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.allow_self_signup and org.sso_only:
        # Self-signup is anonymous and un-gated by an admin, unlike every
        # other native-account-creation path (create_org_user, an admin-
        # sent invite) — letting it hand out a native password credential
        # to an sso_only org would create an account that can never log in
        # (NativeAuthBackend rejects native login when every one of a
        # user's orgs is sso_only). See docs/decisions.md.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Self-signup cannot be enabled for an SSO-only organisation."
        )
    org.smtp_host = payload.smtp_host
    org.smtp_port = payload.smtp_port
    org.smtp_username = payload.smtp_username
    if payload.smtp_password:
        # Blank means "leave unchanged" — the field is never returned by GET,
        # so a client re-submitting the form has no value to send back.
        org.smtp_password = payload.smtp_password
    org.smtp_use_tls = payload.smtp_use_tls
    org.pat_max_lifetime_days = payload.pat_max_lifetime_days
    org.require_2fa = payload.require_2fa
    org.allow_self_signup = payload.allow_self_signup
    org.auto_accept_email_domain = payload.auto_accept_email_domain.lower() if payload.auto_accept_email_domain else None
    org.external_user_policy = payload.external_user_policy
    # Hierarchical projects (decision 13 in docs/decisions.md): lets an org
    # admin opt back into the stricter "all project creation needs
    # ORG_ADMIN/PROJECT_CREATOR" behaviour, including for children, turning
    # off routers.projects.create_project's relaxed parent-manage-only path.
    org.allow_relaxed_child_project_creation = payload.allow_relaxed_child_project_creation
    # Platform review 2026-09, Phase 8: org-wide force of the traceability-
    # link change-request requirement — see `services.requirements.
    # requires_change_request_for_links` and `Organization.
    # force_require_change_request_for_approved_links`'s docstring.
    org.force_require_change_request_for_approved_links = payload.force_require_change_request_for_approved_links
    # AI approval via MCP (docs/decisions.md): org half of the two-level
    # opt-in gate. The frontend requires an explicit acknowledgment dialog
    # before ever sending `allow_ai_approvals=true` here — this endpoint
    # trusts that already happened (same "form-level guardrail, not
    # server-enforced" pattern as every other advanced-settings checkbox on
    # this endpoint), since the decision is a human's, not something to
    # validate server-side.
    org.allow_ai_approvals = payload.allow_ai_approvals
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="advanced_settings_updated",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()
    db.refresh(org)
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls,
        pat_max_lifetime_days=org.pat_max_lifetime_days, require_2fa=org.require_2fa,
        allow_self_signup=org.allow_self_signup, auto_accept_email_domain=org.auto_accept_email_domain,
        external_user_policy=org.external_user_policy,
        allow_relaxed_child_project_creation=org.allow_relaxed_child_project_creation,
        force_require_change_request_for_approved_links=org.force_require_change_request_for_approved_links,
        allow_ai_approvals=org.allow_ai_approvals,
    )


@router.get("/{organization_id}/modules", response_model=list[OrgModuleOut])
def list_org_modules(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Lists every registered module with this organisation's effective
    entitlement/enablement state (module system Phase 1).

    Non-entitled modules are included, not filtered out: the Modules admin
    UI shows them greyed out with an explanatory note rather than hiding
    them entirely (visibility helps future upsell; the toggle itself stays
    disabled) — the frontend does the graying, this endpoint just reports
    the truth.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    result: list[OrgModuleOut] = []
    for definition in get_module_registry().values():
        entitled = is_module_entitled(db, organization_id, definition.key)
        enabled = is_module_enabled(db, organization_id, definition.key)
        manifest = get_frontend_manifest(definition.key)
        result.append(
            OrgModuleOut(
                module_key=definition.key, name=definition.name, description=definition.description,
                version=definition.version, implemented=definition.implemented,
                entitled=entitled, enabled=enabled, default_enabled=definition.default_enabled,
                frontend_manifest=ModuleFrontendManifestOut(**vars(manifest)) if manifest else None,
            )
        )
    return result


@router.put("/{organization_id}/modules/{module_key}", response_model=OrgModuleOut)
def update_org_module_enablement(
    organization_id: UUID, module_key: str, payload: OrgModuleEnablementUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets this organisation's own explicit enable/disable choice for one
    module (module system Phase 1) — the org-tier "day-to-day switch"
    among modules the organisation is entitled to.

    404s on an unregistered `module_key`, matching how every other
    org-scoped resource lookup in this router responds to a bogus id.
    403s with a clear message if the organisation isn't entitled to the
    module at all: an org admin cannot self-enable a non-entitled module
    by toggling this endpoint — entitlement is a server-tier lever
    (`PUT /system/orgs/{organization_id}/module-entitlements/{module_key}`),
    strictly above what this endpoint can touch.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    definition = get_module_registry().get(module_key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found.")
    if not is_module_entitled(db, organization_id, module_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This module is not entitled for this organisation.")

    row = db.scalar(
        select(OrganizationModuleEnablement).where(
            OrganizationModuleEnablement.organization_id == organization_id,
            OrganizationModuleEnablement.module_key == module_key,
        )
    )
    if row is None:
        row = OrganizationModuleEnablement(organization_id=organization_id, module_key=module_key)
        db.add(row)
    row.enabled = payload.enabled
    row.updated_by = current_user.id
    log_event(
        db, entity_type="organization_module", entity_id=f"{organization_id}:{module_key}",
        action="module.enablement_updated", actor_id=current_user.id, organization_id=organization_id,
        detail={"module_key": module_key, "enabled": payload.enabled},
    )
    db.commit()
    db.refresh(row)
    manifest = get_frontend_manifest(definition.key)
    return OrgModuleOut(
        module_key=definition.key, name=definition.name, description=definition.description,
        version=definition.version, implemented=definition.implemented,
        entitled=True, enabled=row.enabled, default_enabled=definition.default_enabled,
        frontend_manifest=ModuleFrontendManifestOut(**vars(manifest)) if manifest else None,
    )


@router.post("/{organization_id}/modules/{module_key}/frame-token", response_model=ModuleFrameTokenOut)
def create_org_module_frame_token(
    organization_id: UUID,
    module_key: str,
    current_user: User = Depends(require_org_module_enabled_dynamic),
) -> ModuleFrameTokenOut:
    """Mints a short-lived Tier B `<ModuleFrame>` token scoped to
    `(module_key, organization_id, current_user)` (module system Phase 3).

    Requires `module_key` to be a real, currently-*enabled* module for this
    organisation (`require_org_module_enabled_dynamic` — 404 otherwise,
    matching every other module-gated endpoint's "disabled/non-entitled is
    indistinguishable from not existing" behaviour) and a real session/PAT
    (never another module-frame token — see that dependency's docstring).
    The returned token is what the frontend's Host UI Bridge hands to the
    module's own sandboxed iframe via the `init` message, in place of the
    caller's real session token — see `app.security.create_module_frame_
    token`'s docstring for exactly what it can and cannot be used for.
    """
    token = create_module_frame_token(
        module_key=module_key, organization_id=str(organization_id), user_id=str(current_user.id)
    )
    return ModuleFrameTokenOut(token=token, expires_in_minutes=15)


@router.post("/{organization_id}/test-email", status_code=status.HTTP_204_NO_CONTENT)
def send_org_test_email(
    organization_id: UUID, payload: TestEmailRequest,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sends a test email through this organisation's own configured SMTP
    relay (`Organization.smtp_*`, set via `update_advanced_settings` above)
    rather than the deployment-wide one, so an org admin can confirm their
    override actually works before relying on it — this is currently the
    only thing that reads `Organization.smtp_*` at all; see
    `services/email.py`'s module docstring and docs/decisions.md's "SMTP/SSO
    organisation settings are a storage-only seam" entry for why ordinary
    notification email still doesn't.

    Raises:
        HTTPException: 404 if the organisation doesn't exist; 400 if it has
            no SMTP host configured yet; 502 if the send itself fails (bad
            credentials, unreachable host, ...) — surfaced with the
            underlying error so the admin knows what to fix, since
            confirming deliverability is the entire point of this action.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if not org.smtp_host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation has no SMTP host configured.")
    to_email = payload.to_email or current_user.email
    branding = resolve_email_branding(db, organization_id=organization_id)
    html_body, text_body = render_email(
        "test_email", branding=branding, source_description=f"{org.name}'s configured SMTP settings",
        cta_url=settings.frontend_base_url,
    )
    inline_images = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
    try:
        send_email(
            to_email, f"Test email from {org.name}", text_body, html_body=html_body, inline_images=inline_images,
            smtp_override=SmtpOverride(
                host=org.smtp_host, port=org.smtp_port, username=org.smtp_username,
                password=org.smtp_password, use_tls=org.smtp_use_tls,
            ),
        )
    except Exception as err:  # noqa: BLE001 - surfacing the underlying SMTP failure is the entire point of a test-email action
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to send test email: {err}") from err
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="test_email_sent",
        actor_id=current_user.id, organization_id=organization_id, detail={"to": to_email},
    )
    db.commit()


@router.get("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def get_sso_config(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.put("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def update_sso_config(
    organization_id: UUID, payload: OrgSsoConfigUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Configures an organisation's OIDC SSO login (E-U-01) and its
    slug-resolved branded login page (E-P-03).

    `oidc_client_secret` is encrypted at rest at the application layer
    (`EncryptedString`, SOC 2 hardening pass) — see `models.organization`
    for details.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.slug is not None:
        existing = db.scalar(select(Organization).where(Organization.slug == payload.slug))
        if existing is not None and existing.id != org.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "This slug is already in use.")
        org.slug = payload.slug
    if payload.sso_enabled and not org.slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set a slug before enabling SSO (needed for the login page URL).")
    if payload.sso_only and not payload.sso_enabled:
        # sso_only now has real backend teeth (NativeAuthBackend blocks
        # native login for a user whose every org is sso_only) — allowing it
        # to be set without sso_enabled would be a self-inflicted lockout
        # with no way to sign in at all.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enable SSO before making it the only sign-in method.")
    if payload.sso_only and org.allow_self_signup:
        # Same mutual-exclusion as update_advanced_settings, enforced from
        # this side too since either endpoint can flip the two flags.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Disable self-signup before making this organisation SSO-only."
        )
    org.sso_enabled = payload.sso_enabled
    org.sso_only = payload.sso_only
    org.oidc_issuer_url = payload.oidc_issuer_url
    org.oidc_client_id = payload.oidc_client_id
    if payload.oidc_client_secret:
        # Blank means "leave unchanged" — same pattern as smtp_password above.
        org.oidc_client_secret = payload.oidc_client_secret
    org.oidc_required_group = payload.oidc_required_group
    log_event(db, entity_type="organization", entity_id=organization_id, action="sso_config_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.get("/{organization_id}/scim-token", response_model=ScimTokenStatusOut)
def get_scim_token_status(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Whether SCIM 2.0 provisioning (`routers/scim.py`) is enabled for
    this org, and its current token's non-secret prefix — never the token
    itself, which is only ever shown once, at (re)generation."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return ScimTokenStatusOut(enabled=org.scim_token_hash is not None, token_prefix=org.scim_token_prefix)


@router.post("/{organization_id}/scim-token", response_model=ScimTokenCreatedOut)
def regenerate_scim_token(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """(Re)generates this org's SCIM bearer token — immediately invalidates
    any previous one (a single active token per org, same as this codebase's
    Personal Access Tokens are per-user-per-token rather than allowing
    silent parallel validity). The raw secret is returned exactly once."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    raw_token, token_hash, token_prefix = generate_scim_token()
    org.scim_token_hash = token_hash
    org.scim_token_prefix = token_prefix
    log_event(db, entity_type="organization", entity_id=organization_id, action="scim_token_regenerated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return ScimTokenCreatedOut(token=raw_token, token_prefix=token_prefix)


@router.delete("/{organization_id}/scim-token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_scim_token(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Disables SCIM provisioning for this org by clearing its token —
    every subsequent SCIM request against this org 401s immediately."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.scim_token_hash = None
    org.scim_token_prefix = None
    log_event(db, entity_type="organization", entity_id=organization_id, action="scim_token_revoked",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()

