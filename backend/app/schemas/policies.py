"""
Module: schemas.policies

Request and response shapes for policies (`routers.policies`).

The public shapes carry only what a reader needs: never the author, the working copy, the change note or an
owning organisation's id.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.policy import PolicyState
from app.services.policies import MAX_NOTE_LENGTH, MAX_TITLE_LENGTH


class PolicyIn(BaseModel):
    """The editable fields of a policy (create and replace).

    Attributes:
        key: Built-in slot to create (`privacy` or `data`); omitted for any other policy.
        title: Heading, one line; ignored for a slot, which keeps its fixed title.
        body: Rich-text document (validated against the allowed vocabulary).
        effective_from: Date the policy takes effect, as chosen by the author; `None` when not stated.
    """

    key: Literal["privacy", "data"] | None = None
    title: str = Field(default="", max_length=MAX_TITLE_LENGTH)
    body: dict[str, Any] = Field(default_factory=dict)
    effective_from: date | None = None


class PolicyPublishIn(BaseModel):
    """Publishing a policy.

    Attributes:
        change_note: Why this version differs from the last (plain text), shown to administrators only.
    """

    change_note: str = Field(default="", max_length=MAX_NOTE_LENGTH)


class PolicySummaryOut(BaseModel):
    """One row of the administration list; a built-in slot with no policy yet has `id` of `None`.

    Attributes:
        has_unpublished_changes: Whether the working copy differs from the published version.
    """

    id: UUID | None
    key: str | None
    title: str
    state: PolicyState
    effective_from: date | None
    current_version: int
    has_unpublished_changes: bool
    updated_at: datetime | None


class PolicyVersionOut(BaseModel):
    """A published version as administrators see it (without the body)."""

    version: int
    title: str
    effective_from: date | None
    published_at: datetime
    change_note: str


class PolicyVersionBodyOut(PolicyVersionOut):
    """A published version with its body."""

    body: dict[str, Any]


class PolicyOut(PolicySummaryOut):
    """A policy with its working copy and version history, as administrators see it."""

    body: dict[str, Any]
    versions: list[PolicyVersionOut]


class PublicPolicySummaryOut(BaseModel):
    """A published policy in the public list.

    Attributes:
        version: Current published version number.
        published_at: When that version was published (UTC).
    """

    id: UUID
    key: str | None
    title: str
    effective_from: date | None
    version: int
    published_at: datetime


class PublicPolicyOut(PublicPolicySummaryOut):
    """A published policy with its text."""

    body: dict[str, Any]
