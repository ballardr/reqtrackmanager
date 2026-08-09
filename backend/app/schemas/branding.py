"""
Module: schemas.branding

Request/response models for platform-wide UI branding defaults
(`ServerSettings`) — the accent colour, logo, and header wordmark used on
pages with no single resolvable organisation context.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.org import _HEX_COLOR_PATTERN


class ServerSettingsOut(BaseModel):
    model_config = {"from_attributes": True}

    accent_color_hex: str
    default_logo_file_id: UUID | None = None
    default_header_title: str | None = None
    default_login_background_file_id: UUID | None = None


class ServerSettingsUpdate(BaseModel):
    accent_color_hex: str = Field(pattern=_HEX_COLOR_PATTERN)
    default_header_title: str | None = Field(default=None, max_length=100)
