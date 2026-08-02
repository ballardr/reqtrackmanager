"""
Module: schemas.org

Request/response models for organisations, organisation users, and
organisation groups (C-U-01, C-U-04, C-U-05, C-U-08).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.enums import OrgRole


class OrganizationCreate(BaseModel):
    name: str


class OrganizationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    created_at: datetime
    logo_file_id: UUID | None = None
    default_template_project_id: UUID | None = None
    login_background_file_id: UUID | None = None
    slug: str | None = None


class DefaultTemplateUpdate(BaseModel):
    """Sets or clears the organisation's default template project (C-E-04)."""

    project_id: UUID | None


class SsoGroupMapping(BaseModel):
    """Maps one external SSO group name to a local org role (C-U-07, E-U-01)
    — consumed by `services/oidc_provisioning.sync_org_roles_from_claims` on
    every SSO login. Distinct from `Organization.oidc_required_group`, which
    gates *whether* a login is admitted at all, not which role it gets."""

    sso_group: str
    org_role: OrgRole


class OrgAdvancedSettingsOut(BaseModel):
    """Per-organisation SMTP override and SSO group-mapping settings — see
    `Organization` model docstring and docs/decisions.md."""

    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_use_tls: bool = True
    sso_group_mappings: list[SsoGroupMapping] = []


class OrgAdvancedSettingsUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    sso_group_mappings: list[SsoGroupMapping] = []


class OrgUserCreate(BaseModel):
    """Creates a brand-new user directly within an organisation."""

    email: EmailStr
    display_name: str
    password: str
    role: OrgRole = OrgRole.MEMBER


class OrgUserOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    is_active: bool
    is_archived: bool
    roles: list[OrgRole]
    display_name_locked: bool = False
    last_login_at: datetime | None = None
    is_2fa_enabled: bool = False


class OrgSsoConfigUpdate(BaseModel):
    """Per-organisation SSO/OIDC configuration (E-U-01, E-P-03)."""

    slug: str | None = None
    sso_enabled: bool = False
    sso_only: bool = False
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_required_group: str | None = None


class OrgSsoConfigOut(BaseModel):
    slug: str | None = None
    sso_enabled: bool
    sso_only: bool
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_required_group: str | None = None


class OrgLoginInfoOut(BaseModel):
    """Public, unauthenticated org-branded login page info (E-P-03) — no
    secrets, just enough to render the page and offer an SSO button."""

    name: str
    slug: str
    logo_file_id: UUID | None = None
    login_background_file_id: UUID | None = None
    sso_enabled: bool
    sso_only: bool


class ReportTemplateCreate(BaseModel):
    name: str
    accent_color_hex: str = "#2563eb"
    include_cover_page: bool = True
    include_logo: bool = True
    footer_text: str | None = None


class ReportTemplateOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    accent_color_hex: str
    include_cover_page: bool
    include_logo: bool
    footer_text: str | None = None


class DisplayNameLockUpdate(BaseModel):
    """Locks or unlocks a user's ability to change their own display name (C-U-16)."""

    display_name_locked: bool


class OrgRoleAssign(BaseModel):
    user_id: UUID
    role: OrgRole


class OrgGroupCreate(BaseModel):
    name: str


class OrgGroupMemberAdd(BaseModel):
    user_id: UUID


class OrgGroupOut(BaseModel):
    id: UUID
    name: str
    member_user_ids: list[UUID]
