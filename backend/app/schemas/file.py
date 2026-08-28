"""Module: schemas.file — response models for uploaded files (Pelion v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
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


class ProjectFileOut(BaseModel):
    """One file reachable from a project's requirements (`GET
    /projects/{id}/files`) — a direct requirement attachment, a requirement
    action attachment, or a file attached to a comment on one of the
    project's requirements. Distinct from a bare `FileAssetOut` in that it
    also carries the context needed to make sense of a flat, project-wide
    list: which requirement/action/comment the file came from and who
    uploaded it, so a caller isn't left with an array of filenames and no
    way to tell where any of them came from.

    `source` distinguishes the three origin join-tables
    (`requirement_attachment`/`action_attachment`/`comment_attachment`).
    `requirement_id`/`requirement_unique_code`/`requirement_name` are set
    for `requirement_attachment` and `comment_attachment` rows;
    `action_id`/`action_unique_code`/`action_title` (and, redundantly,
    `comment_id`) are set for `action_attachment`/`comment_attachment` rows
    respectively. An action attachment carries no `requirement_id` — an
    action may be linked to zero, one, or several requirements
    (`RequirementActionLink`), so it has no single owning requirement to
    attribute the file to; it's attributed to the action itself instead.
    """

    file: FileAssetOut
    uploaded_by_display_name: str
    source: Literal["requirement_attachment", "action_attachment", "comment_attachment"]
    requirement_id: UUID | None = None
    requirement_unique_code: str | None = None
    requirement_name: str | None = None
    action_id: UUID | None = None
    action_unique_code: str | None = None
    action_title: str | None = None
    comment_id: UUID | None = None
