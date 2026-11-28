"""
Module: modules.traceability.exception_schemas

Request and response schemas of the traceability exception API (`exception_router`).

Responsibilities:
- Bound every free-text field to the limit declared for its column (`exception_providers`).

Design decisions:
- An update is partial: a field left out is kept, and `approver`, `expires_on` and `review_date` set to `null` are cleared.
  The record and the rule are not updatable: they identify the exception, so a different pair is a new exception.
- The status changes only through the named action routes, never an update.

Dependencies: `schemas.principal`, `schemas.project_scope`, `enums`.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.traceability.enums import ExceptionNoCoverReason, ExceptionStatus
from app.modules.traceability.models import EXCEPTION_TITLE_MAX_LENGTH
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow
from app.services.long_text_core import NOTE_LIMIT


class ExceptionCreate(BaseModel):
    """A request for an exception.

    Attributes:
        artefact_type / artefact_id: The record to except.
        rule_id: The rule, one in effect for the project that applies to the record's type.
        title: Defaults to "Exception to <rule name>".
        requester: Defaults to the person raising the request.
        approver: A nominated approver, told of the request.
    """

    artefact_type: str = Field(max_length=64)
    artefact_id: UUID
    rule_id: UUID
    title: str | None = Field(default=None, max_length=EXCEPTION_TITLE_MAX_LENGTH)
    reason: str = Field(max_length=NOTE_LIMIT)
    requester: PrincipalRef | None = None
    approver: PrincipalRef | None = None
    expires_on: date | None = None
    review_date: date | None = None


class ExceptionUpdate(BaseModel):
    """A partial change to an exception."""

    title: str | None = Field(default=None, max_length=EXCEPTION_TITLE_MAX_LENGTH)
    reason: str | None = Field(default=None, max_length=NOTE_LIMIT)
    requester: PrincipalRef | None = None
    approver: PrincipalRef | None = None
    expires_on: date | None = None
    review_date: date | None = None


class ExceptionDecision(BaseModel):
    """The comment that goes with an action; required to reject or revoke."""

    comment: str = Field(default="", max_length=NOTE_LIMIT)


class ExceptionReviewCreate(BaseModel):
    """A periodic review of an exception.

    Attributes:
        next_review_date: When it is next to be reviewed, `null` for no further review.
        notes: Findings, recorded as a comment.
    """

    next_review_date: date | None
    notes: str = Field(default="", max_length=NOTE_LIMIT)


class ExceptionRecordOut(BaseModel):
    """The record an exception is about.

    Attributes:
        code / label: Empty when the record no longer exists.
        removed: The record is archived or no longer exists, so the exception has nothing to cover.
    """

    artefact_type: str
    artefact_type_label: str
    id: UUID
    code: str
    label: str
    removed: bool


class ExceptionOut(ProjectScopedRow):
    """A traceability exception.

    Attributes:
        rule_name: The rule's current name, or the name it had when the rule was removed.
        covers: Whether the record is excepted from the rule now.
        no_cover_reason: Why not, `null` when it covers.
        rule_changed: The rule's logic differs from what was approved.
        needs_organisation_approval: The rule belongs to an Enforced profile, so only an organisation-level approver may
            approve.
    """

    id: UUID
    project_id: UUID
    unique_code: str
    title: str
    status: ExceptionStatus
    record: ExceptionRecordOut
    rule_id: UUID | None
    rule_name: str
    reason: str
    requester: PrincipalOut | None
    approver: PrincipalOut | None
    expires_on: date | None
    review_date: date | None
    creator_id: UUID
    decided_by_id: UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_comment: str
    covers: bool
    no_cover_reason: ExceptionNoCoverReason | None
    expired: bool
    rule_changed: bool
    needs_organisation_approval: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ExceptionDetailOut(ExceptionOut):
    """One exception with what the caller may do to it.

    Attributes:
        actions: Of `edit`, `approve`, `reject`, `revoke`, `withdraw`, `resubmit`, `review`, `archive`, `unarchive`.
    """

    actions: list[str]


class ExceptionCommentCreate(BaseModel):
    """A new comment."""

    body: str = Field(min_length=1, max_length=NOTE_LIMIT)


class ExceptionCommentOut(BaseModel):
    """A comment with its author and attachments."""

    id: UUID
    exception_id: UUID
    author_id: UUID
    author_display_name: str
    body: str
    created_at: datetime
    edited_at: datetime | None
    attachments: list[FileAssetOut] = []
