"""
Module: models.policy

Policies: written documents (privacy policy, data policy, access policy, ...) published for readers.

Responsibilities:
- `PolicyDocument`: one policy with its working copy (title and body being edited) and its publication state.
- `PolicyDocumentVersion`: an append-only snapshot written each time a policy is published.

Design decisions:
- One table with a nullable owner, the shape `Announcement.organization_id` uses, so server and organisation
  policies share one service, one API shape and one editor.
- The working copy lives on `PolicyDocument`; readers get the content of `current_version`, so an edit never
  changes the published text until it is published again.
- `body` is a validated rich-text document (a ProseMirror tree limited to a fixed vocabulary, see
  `services.policy_body`), never markup, so no stored value is rendered as HTML.
- `key` names a built-in slot (`privacy`, `data`); other policies have no key. A slot is unique per owner.
- `effective_from` is a person's calendar date (a plain date, no timezone); `published_at` is a past instant in UTC.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum


class PolicyState(str, enum.Enum):
    """Whether a policy's current version is visible to readers."""

    DRAFT = "draft"
    PUBLISHED = "published"


class PolicyDocument(UUIDPKMixin, TimestampMixin, Base):
    """A policy and its working copy.

    Attributes:
        organization_id: Owning organisation; NULL for a server policy.
        key: Built-in slot (`privacy`, `data`), or NULL for any other policy.
        title: Working title (fixed to the slot title for a slot).
        body: Working body (validated rich-text document).
        state: `published` while `current_version` is visible to readers; `draft` otherwise.
        effective_from: Date the policy takes effect, shown as chosen; NULL when not stated.
        current_version: Number of the latest published version; 0 before the first publication.
        created_by: The author, kept for audit; never returned by a public endpoint.
    """

    __tablename__ = "policy_documents"
    __table_args__ = (
        Index("ix_policy_documents_organization_id", "organization_id"),
        Index(
            "uq_policy_documents_server_key", "key", unique=True,
            postgresql_where=text("organization_id IS NULL AND key IS NOT NULL"),
        ),
        Index(
            "uq_policy_documents_org_key", "organization_id", "key", unique=True,
            postgresql_where=text("organization_id IS NOT NULL AND key IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[PolicyState] = mapped_column(str_enum(PolicyState, 20), default=PolicyState.DRAFT)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PolicyDocumentVersion(UUIDPKMixin, Base):
    """One published snapshot of a policy; never changed after it is written.

    Attributes:
        policy_id: The policy.
        version: 1-based number, unique per policy.
        title / body / effective_from: The content as published.
        published_at: When it was published (UTC).
        published_by: The publisher, kept for audit; never returned by a public endpoint.
        change_note: Why it changed (plain text), shown to administrators only.
    """

    __tablename__ = "policy_document_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version", name="uq_policy_document_versions_policy_version"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    change_note: Mapped[str] = mapped_column(Text, default="")
