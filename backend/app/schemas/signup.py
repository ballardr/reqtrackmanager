"""
Module: schemas.signup

Request/response models for the server-wide public self-signup setting
(`ServerSettings.signup_mode`) and the public, unauthenticated view of it
the signup form itself needs before a session exists.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.enums import SignupMode


class SelfSignupOrgOut(BaseModel):
    """A minimal, non-sensitive view of an org open to `ORG_SPECIFIED`
    self-signup — deliberately omits `auto_accept_email_domain`, since this
    is served on the public, unauthenticated signup form and a domain isn't
    otherwise public information."""

    id: UUID
    name: str


class SignupConfigOut(BaseModel):
    """Public, unauthenticated view of signup availability — the signup
    page's first call, before any session exists."""

    signup_mode: SignupMode
    self_signup_organizations: list[SelfSignupOrgOut] = []


class SignupConfigUpdate(BaseModel):
    """Server-admin-only update of the signup mode."""

    signup_mode: SignupMode
