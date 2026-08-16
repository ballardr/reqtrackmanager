"""
Module: models.file

File storage models (Pelion v2): a single `FileAsset` row per uploaded file,
regardless of which storage backend actually holds its bytes (I-M-10), and
a link table connecting files to requirements — used both for direct
requirement attachments (C-M-02) and for linking an organisation's shared
resource file to a requirement (C-M-04, `is_org_resource=True` files).
Avatars (C-U-18) and organisation logos (U-C-02) reference `FileAsset`
directly from `User`/`Organization` rather than through this link table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class FileAsset(UUIDPKMixin, TimestampMixin, Base):
    """Metadata for one uploaded file; the bytes live in a storage backend.

    Attributes:
        storage_backend: Which `FileStorageBackend` implementation holds the
            bytes ("local" or "s3"), so a deployment can migrate backends
            without losing track of where existing files are (I-M-10).
        storage_key: Backend-specific key/path used to fetch the bytes.
        is_org_resource: True for files uploaded as an organisation shared
            resource (C-M-03); False for files uploaded directly as a
            requirement attachment, avatar, or organisation logo.
    """

    __tablename__ = "file_assets"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    storage_backend: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_org_resource: Mapped[bool] = mapped_column(Boolean, default=False)


class RequirementFile(UUIDPKMixin, Base):
    """Links a file (direct upload or org shared resource) to a requirement."""

    __tablename__ = "requirement_files"
    __table_args__ = (UniqueConstraint("requirement_id", "file_id"),)

    requirement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file directly uploaded as an attachment to a `ReviewComment` — the
    one place a user may still attach a file to a requirement outside of
    creation or a change request (C-G-12 governs the requirement's own
    fields and its direct-attachment endpoint, not its discussion thread)."""

    __tablename__ = "comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("review_comments.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
