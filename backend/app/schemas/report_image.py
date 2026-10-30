"""
Module: schemas.report_image

Response model for the report-image library (`routers.report_images`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ReportImageOut(BaseModel):
    """One picture a layout may embed.

    Attributes:
        id: The file id an image block stores.
        filename: As uploaded.
        content_type: `image/png`, `image/jpeg`, `image/gif`, `image/webp` or `image/svg+xml`.
        size_bytes: Stored size.
        tier: `organisation` (every project's layouts may use it) or `project`.
        owned: Whether the library being listed owns it, that is, whether its manager may delete it.
        used_by: Names of the layouts whose current version uses it.
        in_older_versions: True when no layout's current version uses it but an older saved version does.
        created_at: Upload time (UTC).
    """

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    tier: Literal["organisation", "project"]
    owned: bool
    used_by: list[str]
    in_older_versions: bool = False
    created_at: datetime


class ReportImageLibraryOut(BaseModel):
    """A library listing: the pictures and the largest one an upload may be (a deployment setting)."""

    images: list[ReportImageOut]
    max_image_bytes: int
