"""
Module: schemas.service_user

Request and response shapes for service users (`routers/orgs/service_users.py`, `services.service_users`).

A response never carries a token secret except `ServiceUserTokenCreateOut`, which is returned once at issue.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import OrgRole
from app.schemas.pat import PersonalAccessTokenProjectRef
from app.schemas.principal import PrincipalOut, PrincipalRef

ServiceUserFlagName = Literal["no_responsible", "administrator"]


class ServiceUserCreate(BaseModel):
    """Creates a service user. `email` is optional: blank gives a generated address that receives no email."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=500)
    email: EmailStr | None = None
    responsible: PrincipalRef | None = None


class ServiceUserUpdate(BaseModel):
    """Changes a service user; only the fields sent change (`email: null` returns to a generated address,
    `responsible: null` clears it)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    responsible: PrincipalRef | None = None


class ServiceUserOut(BaseModel):
    """A service user as listed to an organisation administrator.

    Attributes:
        email: The supplied address, or `None` when the account has only a generated one.
        has_deliverable_email: Whether notifications can reach it (a supplied address).
        flags: What the access review flags (`no_responsible`, `administrator`).
        active_token_count: Tokens neither revoked nor past their effective expiry.
        last_used_at: The latest use of any of its tokens.
    """

    user_id: UUID
    name: str
    description: str
    email: str | None
    has_deliverable_email: bool
    is_active: bool
    is_archived: bool
    responsible: PrincipalOut | None
    roles: list[OrgRole]
    flags: list[ServiceUserFlagName]
    active_token_count: int
    last_used_at: datetime | None
    created_at: datetime
    created_by_display_name: str | None


class ServiceUserTokenCreate(BaseModel):
    """Issues a token for a service user. The organisation is always the service user's own."""

    name: str = Field(min_length=1, max_length=255)
    allowed_project_ids: list[UUID] = []
    requested_expires_at: datetime | None = None


class ServiceUserTokenOut(BaseModel):
    """One token of a service user (never the secret or its hash)."""

    id: UUID
    name: str
    token_prefix: str
    allowed_projects: list[PersonalAccessTokenProjectRef]
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    created_by_display_name: str | None


class ServiceUserTokenCreateOut(ServiceUserTokenOut):
    """Returned once, at issue: the only response that carries the secret.

    Attributes:
        token: The secret. It is not stored, so it cannot be shown again.
        notice: States that, for the person reading the response.
    """

    token: str
    notice: str = "This token is shown once. Copy it now: it cannot be retrieved again."
