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


class DefaultTemplateUpdate(BaseModel):
    """Sets or clears the organisation's default template project (C-E-04)."""

    project_id: UUID | None


class SsoGroupMapping(BaseModel):
    """Maps one external SSO group name to a local org role. Storage-only —
    see `Organization.sso_group_mappings` for why nothing consumes this yet."""

    sso_group: str
    org_role: OrgRole


class OrgAdvancedSettingsOut(BaseModel):
    """Per-organisation SMTP override and SSO group-mapping settings.
    Storage-only seams for future integrations — see `Organization` model
    docstring and docs/decisions.md."""

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
