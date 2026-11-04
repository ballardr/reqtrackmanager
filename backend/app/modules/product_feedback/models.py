"""
Module: modules.product_feedback.models

Product Feedback's data model:

- `EnhancementRequest` — the identity row. One table with a `scope` discriminator and exactly
  one of `organization_id` / `project_id` set (a CHECK constraint), so a request can sit in a
  project or in the organisation's inbox. Holds only stable identity fields; every mutable
  field lives on the version.
- `EnhancementRequestVersion` — one point-in-time content snapshot (temporal shape copied from
  `RiskVersion`). `status` lives here, so a lifecycle move is versioned like any other change.
- `EnhancementRequestComment` / `EnhancementRequestCommentFile` / `EnhancementRequestFile` —
  module-local comment-thread and attachment tables (the shared `services.module_attachments`
  kit works over them).
- `EnhancementRequestMerge` — the recorded history of merging a duplicate into a canonical request; what
  makes a merge reversible and what demand is unioned over.
- `ProjectFeedbackSettings` — one optional row per project holding who may submit. Absence
  means the default policy (`SubmissionPolicy.MEMBERS`).

`unique_code` comes from `services.sequences.generate_unique_code` with this module's own
`"enhancement_request"` artefact-type string: numbered per owner (project or organisation).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy


class EnhancementRequest(UUIDPKMixin, TimestampMixin, Base):
    """An enhancement request's stable identity (organisation- or project-owned).

    Attributes:
        scope: `ORGANIZATION` or `PROJECT` — which of `organization_id` / `project_id` is set.
        organization_id: Set (and `project_id` null) for an organisation-owned request.
        project_id: Set (and `organization_id` null) for a project-owned request.
        unique_code: Human-readable code (e.g. `"ENH-003"`), numbered per owner and never reused.
        creator_id: Who created the record.
        is_archived / archived_at / archived_by: Soft-delete.
    """

    __tablename__ = "enhancement_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code", name="uq_enhancement_requests_project_unique_code"),
        UniqueConstraint("organization_id", "unique_code", name="uq_enhancement_requests_organization_unique_code"),
        CheckConstraint(
            "(scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)",
            name="ck_enhancement_requests_scope_matches_owner",
        ),
    )

    scope: Mapped[EnhancementRequestScope] = mapped_column(str_enum(EnhancementRequestScope, 20))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    versions: Mapped[list[EnhancementRequestVersion]] = relationship(
        back_populates="request", order_by="EnhancementRequestVersion.version_number"
    )


class EnhancementRequestVersion(UUIDPKMixin, Base):
    """One point-in-time snapshot of a request's content.

    Attributes:
        valid_from / valid_to: Effective interval; `valid_to` is null for the current version.
        title: Short display name.
        description: The proposed solution, in the requester's terms.
        status: Lifecycle state.
        owner_type / owner_id: The principal (a user, an organisation group or a project group —
            `models.principal`) looking after the request; both null when unowned. No foreign
            key; `services.principals.validate_principal` checks it on write and `module.py`'s
            `principal_references` guard group deletion.
        external_ref_url / external_ref_key: A pointer to the same item in a delivery tool (a URL
            and its key, e.g. a Jira issue); both optional.
        decline_reason: Why the request was declined (mandatory when the status is `DECLINED`).
        change_note: Free-text reason for the change.
        created_by / created_at: Who made this snapshot, and when.
    """

    __tablename__ = "enhancement_request_versions"
    __table_args__ = (
        UniqueConstraint("request_id", "version_number"),
        principal_check_constraint("owner", nullable=True),
        Index(
            "ix_enhancement_request_versions_current", "request_id", unique=False,
            postgresql_where=sa_text("valid_to IS NULL"),
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[EnhancementRequestStatus] = mapped_column(
        str_enum(EnhancementRequestStatus, 20), default=EnhancementRequestStatus.NEW
    )
    owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    external_ref_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_ref_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decline_reason: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    request: Mapped[EnhancementRequest] = relationship(back_populates="versions")


class EnhancementRequestComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on an `EnhancementRequest`.

    Attributes:
        request_id: The commented-on request.
        author_id: Who wrote it.
        body: Comment text.
        edited_at: Set only when the body changed after creation.
    """

    __tablename__ = "enhancement_request_comments"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EnhancementRequestCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to an `EnhancementRequestComment`."""

    __tablename__ = "enhancement_request_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_request_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class EnhancementRequestFile(UUIDPKMixin, Base):
    """Links a directly uploaded file (evidence) to an `EnhancementRequest`. A project request's
    files are project-authorised (`service.resolve_request_file_project_id`); an organisation
    request's are organisation shared resources."""

    __tablename__ = "enhancement_request_files"
    __table_args__ = (UniqueConstraint("request_id", "file_id"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnhancementRequestMerge(UUIDPKMixin, TimestampMixin, Base):
    """One merge of a duplicate request into a canonical request; active until `unmerged_at` is set.

    The canonical request's demand is the union of its own requesters and those of every request with an
    active merge into it; unmerging ends the row, which removes the duplicate's requesters from that union
    without any link having been copied or deleted.

    Attributes:
        canonical_id: The request that stays (not itself a duplicate).
        duplicate_id: The request marked `DUPLICATE` by this merge (at most one active merge per duplicate).
        prior_status: The duplicate's status before the merge, restored by unmerging.
        merged_by / merged_at: Who merged, and when (UTC).
        unmerged_by / unmerged_at: Who reversed it, and when; both null while the merge is active.
    """

    __tablename__ = "enhancement_request_merges"
    __table_args__ = (
        CheckConstraint("canonical_id <> duplicate_id", name="ck_enhancement_request_merges_distinct"),
        Index(
            "ux_enhancement_request_merges_active_duplicate", "duplicate_id", unique=True,
            postgresql_where=sa_text("unmerged_at IS NULL"),
        ),
        Index(
            "ix_enhancement_request_merges_canonical", "canonical_id",
            postgresql_where=sa_text("unmerged_at IS NULL"),
        ),
    )

    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    duplicate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    prior_status: Mapped[EnhancementRequestStatus] = mapped_column(str_enum(EnhancementRequestStatus, 20))
    merged_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    unmerged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    unmerged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectFeedbackSettings(UUIDPKMixin, TimestampMixin, Base):
    """A project's Product Feedback settings (a row exists only once a project administrator has set one).

    Attributes:
        project_id: The project (one row at most).
        submission_policy: Who may submit a request; see `SubmissionPolicy`.
    """

    __tablename__ = "project_feedback_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    submission_policy: Mapped[SubmissionPolicy] = mapped_column(
        str_enum(SubmissionPolicy, 20), default=SubmissionPolicy.MEMBERS
    )
