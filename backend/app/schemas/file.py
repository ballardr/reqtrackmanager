"""Module: schemas.file — response models for uploaded files (Pelion v2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FileAssetOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID
    is_org_resource: bool
    created_at: datetime


class LinkResourceRequest(BaseModel):
    file_id: UUID
