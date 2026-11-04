"""
Module: modules.product_feedback.schemas

Pydantic request/response schemas for Product Feedback's routers: request create / update / out,
version history, lifecycle transitions, comments and the project settings.

`RequestUpdate` is partial: only fields present in the request body change, so a nullable field
(the owner, the external reference) can be cleared by sending an explicit `null`. `status` is not
editable here (the transition endpoint owns it).

`owner` is a principal: a user, an organisation group or a project group. Requests send a
`PrincipalRef` (`{type, id}`; null clears it) and responses return a resolved `PrincipalOut`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow


class RequestCreate(BaseModel):
    """Create payload; only `title` is required. `status` is not accepted (a request starts `NEW`)."""

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500)
    external_ref_key: str | None = Field(default=None, max_length=100)


class RequestUpdate(BaseModel):
    """Partial update; see module docstring."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    owner: PrincipalRef | None = None
    external_ref_url: str | None = Field(default=None, max_length=500)
    external_ref_key: str | None = Field(default=None, max_length=100)
    change_note: str = ""


class RequestTransitionRequest(BaseModel):
    """A lifecycle move. `comment` is recorded as the new version's change note and, when declining, is the
    mandatory decline reason."""

    status: EnhancementRequestStatus
    comment: str = ""


class RequestOut(ProjectScopedRow):
    """A request merged with its current version. Built explicitly (identity row plus version), never via
    `from_attributes`."""

    id: UUID
    scope: EnhancementRequestScope
    organization_id: UUID | None = None
    project_id: UUID | None = None
    unique_code: str
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None = None
    archived_by: UUID | None = None
    title: str
    description: str
    status: EnhancementRequestStatus
    allowed_next_statuses: list[EnhancementRequestStatus]
    owner: PrincipalOut | None = None
    external_ref_url: str | None = None
    external_ref_key: str | None = None
    decline_reason: str
    version_number: int
    created_at: datetime
    updated_at: datetime


class RequestVersionOut(BaseModel):
    """One historical version."""

    id: UUID
    request_id: UUID
    version_number: int
    valid_from: datetime
    valid_to: datetime | None = None
    title: str
    description: str
    status: EnhancementRequestStatus
    owner: PrincipalOut | None = None
    external_ref_url: str | None = None
    external_ref_key: str | None = None
    decline_reason: str
    change_note: str
    created_by: UUID
    created_at: datetime


class RequestCommentCreate(BaseModel):
    """A new comment."""

    body: str = Field(min_length=1)


class RequestCommentUpdate(BaseModel):
    """A comment's replacement text."""

    body: str = Field(min_length=1)


class RequestCommentOut(BaseModel):
    """A comment with its author's display name and attachments."""

    id: UUID
    request_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    attachments: list[FileAssetOut] = []


class FeedbackSettingsOut(BaseModel):
    """A project's Product Feedback settings."""

    submission_policy: SubmissionPolicy


class FeedbackSettingsUpdate(BaseModel):
    """Replacement settings."""

    submission_policy: SubmissionPolicy
