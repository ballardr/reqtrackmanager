"""
Module: services.email_branding

Resolves the branding an outgoing HTML email should use — logo, header
title, accent/CTA colour, and footer legal identity — reusing the exact
org-overrides-platform-default resolution `Organization.accent_color_hex`/
`header_title` already have for UI chrome (`frontend/src/context/
BrandingContext.tsx`), mirrored here since email rendering happens
server-side. See `services/branding.py` for the platform-wide singleton
(`ServerSettings`) and the shared `contrast_text_hex` helper this module
also uses for CTA button text.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.services.branding import contrast_text_hex, get_server_settings
from app.services.files import read_file

DEFAULT_PRODUCT_NAME = "ReqTrackManager"


@dataclass
class EmailBranding:
    """Resolved branding for one outgoing email — either scoped to a
    specific organisation (its own overrides, falling back per-field to
    the platform default) or platform-only. See `resolve_email_branding`.

    Attributes:
        logo_bytes / logo_content_type: The resolved logo's raw bytes and
            MIME type, for embedding as a `cid:` inline attachment
            (`services/email.py`) — `None` when no logo is configured
            anywhere, in which case the header banner renders as
            `header_title` alone on its black background.
        footer_company_name: Never empty — falls back to the built-in
            product name, same as `header_title`.
        footer_website / footer_address: `None` when not configured at
            either level, in which case that line is simply omitted from
            the footer rather than shown blank.
    """

    header_title: str
    accent_color_hex: str
    accent_text_hex: str
    logo_bytes: bytes | None
    logo_content_type: str | None
    footer_company_name: str
    footer_website: str | None
    footer_address: str | None


def _resolve_logo(db: Session, file_id: UUID | None) -> tuple[bytes | None, str | None]:
    if file_id is None:
        return None, None
    asset = db.get(FileAsset, file_id)
    if asset is None:
        return None, None
    return read_file(asset), asset.content_type


def resolve_email_branding(db: Session, organization_id: UUID | None = None) -> EmailBranding:
    """Resolves the branding to use for one outgoing email.

    Args:
        db: An active database session.
        organization_id: The organisation this email is about (e.g. an
            instant notification for one of that org's projects, or that
            org's own "send test email" action). `None` for emails with no
            single org context (the daily digest, the deployment-wide test
            email, the disk-usage alert — see `services/email_templates.py`
            for why these always use the platform defaults directly rather
            than guessing an org).

    Returns:
        The resolved `EmailBranding` to render the email with.
    """
    platform = get_server_settings(db)
    org = db.get(Organization, organization_id) if organization_id else None

    header_title = (org.header_title if org else None) or platform.default_header_title or DEFAULT_PRODUCT_NAME
    accent_color_hex = (org.accent_color_hex if org else None) or platform.accent_color_hex
    logo_file_id = (org.logo_file_id if org else None) or platform.default_logo_file_id
    logo_bytes, logo_content_type = _resolve_logo(db, logo_file_id)

    footer_company_name = (
        (org.email_footer_company_name if org else None) or platform.email_footer_company_name or DEFAULT_PRODUCT_NAME
    )
    footer_website = (org.email_footer_website if org else None) or platform.email_footer_website
    footer_address = (org.email_footer_address if org else None) or platform.email_footer_address

    return EmailBranding(
        header_title=header_title,
        accent_color_hex=accent_color_hex,
        accent_text_hex=contrast_text_hex(accent_color_hex),
        logo_bytes=logo_bytes,
        logo_content_type=logo_content_type,
        footer_company_name=footer_company_name,
        footer_website=footer_website,
        footer_address=footer_address,
    )
