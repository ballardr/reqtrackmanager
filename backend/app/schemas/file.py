"""Module: schemas.file — response models for uploaded files (Pelion v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.project_scope import ProjectScopedRow


class FileAssetOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID
    is_org_resource: bool
    confidential: bool = False
    created_at: datetime


class FileConfidentialIn(BaseModel):
    """Body of `PATCH /files/{id}/confidential`."""

    confidential: bool


class LinkResourceRequest(BaseModel):
    file_id: UUID


class ProjectFileOut(ProjectScopedRow):
    """One file reachable from a project's requirements (`GET
    /projects/{id}/files`) — a direct requirement attachment, a requirement
    action attachment, or a file attached to a comment on one of the
    project's requirements. Distinct from a bare `FileAssetOut` in that it
    also carries the context needed to make sense of a flat, project-wide
    list: which requirement/action/comment the file came from and who
    uploaded it, so a caller isn't left with an array of filenames and no
    way to tell where any of them came from.

    `source` distinguishes the origin join-tables
    (`requirement_attachment`/`action_attachment`/`comment_attachment`) and the project's report image library
    (`report_image`, a picture attached to no record).
    `requirement_id`/`requirement_unique_code`/`requirement_name` are set
    for `requirement_attachment` and `comment_attachment` rows;
    `action_id`/`action_unique_code`/`action_title` (and, redundantly,
    `comment_id`) are set for `action_attachment`/`comment_attachment` rows
    respectively. An action attachment carries no `requirement_id` — an
    action may be linked to zero, one, or several requirements (via untyped
    `ArtefactLink` rows), so it has no single owning requirement to
    attribute the file to; it's attributed to the action itself instead.
    """

    file: FileAssetOut
    uploaded_by_display_name: str
    source: Literal["requirement_attachment", "action_attachment", "comment_attachment", "report_image"]
    requirement_id: UUID | None = None
    requirement_unique_code: str | None = None
    requirement_name: str | None = None
    action_id: UUID | None = None
    action_unique_code: str | None = None
    action_title: str | None = None
    comment_id: UUID | None = None


class ProjectFileSearchIn(BaseModel):
    """Body of `POST /projects/{id}/files/search`: the Files page's filters.

    The file name text is in the body, not the URL, so no access log records it. Every field is optional; the
    upload window is two UTC instants (inclusive start, exclusive end) the browser works out from the person's
    local days, and a time without a zone is refused.

    Attributes:
        search: A substring of the file name (case-insensitive).
        sources: Only these sources; empty keeps all.
        kind: Only this file type.
        uploaded_by: Only files this user uploaded.
        uploaded_from: Only files uploaded at or after this instant.
        uploaded_before: Only files uploaded before this instant.
    """

    search: str = Field("", max_length=255)
    sources: list[Literal["requirement_attachment", "action_attachment", "comment_attachment", "report_image"]] = []
    kind: Literal["image", "document", "other"] | None = None
    uploaded_by: UUID | None = None
    uploaded_from: AwareDatetime | None = None
    uploaded_before: AwareDatetime | None = None


class ProjectFileUploaderOut(ProjectScopedRow):
    """One person who uploaded a file in the project (a choice for the Files page's "Uploaded by" filter)."""

    id: UUID
    display_name: str


class FileDetailsOut(BaseModel):
    """What a picture file says about itself (`services.image_details.ImageDetails`): all fields empty for any other file.

    `taken` is the camera's own clock as written (EXIF holds no time zone), never converted.
    """

    width_px: int | None = None
    height_px: int | None = None
    taken: str | None = None
    camera: str | None = None
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class OrganizationFileSearchIn(ProjectFileSearchIn):
    """Body of `POST /orgs/{id}/files/search`: the project Files page's filters plus the projects covered.

    Attributes:
        project_ids: Only these projects (among those the caller may list); empty keeps all of them.
        include_archived: Also list the files of archived projects (default: leave them out).
    """

    project_ids: list[UUID] = Field(default_factory=list, max_length=250)
    include_archived: bool = False


class OrganizationFileProjectOut(BaseModel):
    """One project whose files the caller may list (a choice for the organisation Files page's "Project" filter)."""

    id: UUID
    name: str
    code: str
    is_archived: bool
