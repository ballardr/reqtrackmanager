"""
Module: schemas.branding

Request/response models for platform-wide UI branding defaults
(`ServerSettings`) — the accent colour, logo, and header wordmark used on
pages with no single resolvable organisation context.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.org import _HEX_COLOR_PATTERN


class ServerSettingsOut(BaseModel):
    model_config = {"from_attributes": True}

    accent_color_hex: str
    #: The chosen logo band colour; `None` follows the application top bar colour.
    logo_band_color_hex: str | None = None
    #: The chosen title colour on the band; `None` is black or white by contrast with the band.
    logo_band_text_color_hex: str | None = None
    default_logo_file_id: UUID | None = None
    default_header_title: str | None = None
    default_login_background_file_id: UUID | None = None
    email_footer_company_name: str | None = None
    email_footer_website: str | None = None
    email_footer_address: str | None = None
    footer_prefix: str | None = None
    company_id_label: str | None = None
    company_id: str | None = None
    org_label_singular: str | None = None
    org_label_plural: str | None = None
    #: Whether the deployment accepts new user files; read by every upload control.
    file_uploads_enabled: bool = True


class FileUploadsConfig(BaseModel):
    """The deployment-wide file upload switch (`PUT /system/file-uploads`)."""

    file_uploads_enabled: bool


class DefaultStorageQuota(BaseModel):
    """The storage limit of an organisation that has none of its own (`/system/default-storage-quota`).

    Attributes:
        default_storage_quota_bytes: The limit in bytes, or None for no limit.
    """

    default_storage_quota_bytes: int | None = Field(default=None, ge=0)


class ServerSettingsUpdate(BaseModel):
    """A partial update of the platform branding (`PUT /system/branding`): only the fields sent are changed.

    The Server details and Branding pages each send their own fields, so neither can overwrite the other's. An empty
    text field is sent as `null`, which clears the value; the accent colour has no empty state, so `null` for it is refused.
    """

    accent_color_hex: str | None = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    #: `null` removes the setting (the band follows the top bar colour).
    logo_band_color_hex: str | None = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    logo_band_text_color_hex: str | None = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    default_header_title: str | None = Field(default=None, max_length=100)
    email_footer_company_name: str | None = Field(default=None, max_length=255)
    email_footer_website: str | None = Field(default=None, max_length=500)
    email_footer_address: str | None = Field(default=None, max_length=2000)
    footer_prefix: str | None = Field(default=None, max_length=50)
    company_id_label: str | None = Field(default=None, max_length=50)
    company_id: str | None = Field(default=None, max_length=100)
    org_label_singular: str | None = Field(default=None, max_length=50)
    org_label_plural: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _accent_is_not_cleared(self) -> ServerSettingsUpdate:
        if "accent_color_hex" in self.model_fields_set and self.accent_color_hex is None:
            raise ValueError("The accent colour cannot be cleared.")
        return self
