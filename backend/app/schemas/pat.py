"""
Module: schemas.pat

Request/response shapes for Personal Access Tokens — self-service creation/
listing/revocation (routers/pats.py) and the org-admin/server-admin
incident-response bulk and per-token actions (routers/orgs.py,
routers/system.py). See models/pat.py and docs/decisions.md for the design.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PersonalAccessTokenCreate(BaseModel):
    name: str
    allowed_organization_ids: list[UUID]
    allowed_project_ids: list[UUID] = []
    requested_expires_at: datetime | None = None


class PersonalAccessTokenOrgRef(BaseModel):
    id: UUID
    name: str


class PersonalAccessTokenProjectRef(BaseModel):
    id: UUID
    name: str


class PersonalAccessTokenCreateOut(BaseModel):
    """Returned exactly once, at creation — the only response in the whole
    system that ever contains the raw token secret."""

    id: UUID
    name: str
    token: str
    token_prefix: str
    allowed_organizations: list[PersonalAccessTokenOrgRef]
    allowed_projects: list[PersonalAccessTokenProjectRef]
    expires_at: datetime
    created_at: datetime


class PersonalAccessTokenOut(BaseModel):
    """A caller's own token, as listed by `GET /me/pats` — never the secret
    or its hash."""

    id: UUID
    name: str
    token_prefix: str
    allowed_organizations: list[PersonalAccessTokenOrgRef]
    allowed_projects: list[PersonalAccessTokenProjectRef]
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class OrgPersonalAccessTokenOut(BaseModel):
    """A token touching an org, as listed for that org's admin
    (`GET /orgs/{id}/pats`). Deliberately omits which *other* orgs a
    multi-org token also reaches — see docs/decisions.md's confidentiality
    design note — surfacing only `other_org_count`."""

    id: UUID
    user_id: UUID
    user_email: str
    user_display_name: str
    name: str
    token_prefix: str
    expires_at: datetime
    other_org_count: int
    last_used_at: datetime | None
    created_at: datetime


class BulkRevokeResult(BaseModel):
    revoked_count: int
