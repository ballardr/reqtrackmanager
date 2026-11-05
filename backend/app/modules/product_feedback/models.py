"""
Module: modules.product_feedback.models

Product Feedback's data model:

- `EnhancementRequest` — the identity row. One table with a `scope` discriminator and exactly
  one of `organization_id` / `project_id` set (a CHECK constraint), so a request can sit in a
  project or in the organisation's inbox. Holds only stable identity fields; every mutable
  field lives on the version.
- `EnhancementRequestVersion` — one point-in-time content snapshot (temporal shape copied from
  `RiskVersion`). `status` lives here, so a lifecycle move is versioned like any other change.
- `EnhancementRequestVersionScore` — one scoring level a version holds on one axis of the `enhancement_request`
  scoring scheme (one row per axis, so a scheme axis added later needs no schema change).
- `EnhancementRequestComment` / `EnhancementRequestCommentFile` / `EnhancementRequestFile` —
  module-local comment-thread and attachment tables (the shared `services.module_attachments`
  kit works over them).
- `EnhancementRequestMerge` — the recorded history of merging a duplicate into a canonical request; what
  makes a merge reversible and what demand is unioned over.
- `EnhancementRequestInformed` — a record that one requester (a Stakeholder or Persona) has been told the outcome
  of a delivered or declined request; what the close-the-loop list is built from.
- `ExternalSystemDefinition` / `ProjectExternalSystem` and `RequestChannelDefinition` / `ProjectRequestChannel` — the
  two-tier vocabularies (organisation base, project overrides, additions and hidden defaults) a request's external
  references and its requesters' channels are chosen from (`vocabularies.py`).
- `EnhancementRequestExternalRef` — one pointer to an item in an outside tool (a Jira epic, a ServiceNow ticket) with
  its role; not versioned with the request.
- `EnhancementRequestRequesterChannel` — how one requester asked (the channel per ask), matched to the current
  requesters on read like `EnhancementRequestInformed`.
- `ProjectFeedbackSettings` — one optional row per project holding who may submit. Absence
  means the default policy (`SubmissionPolicy.MEMBERS`).

`unique_code` comes from `services.sequences.generate_unique_code` with this module's own
`"enhancement_request"` artefact-type string: numbered per owner (project or organisation).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column
from app.modules.product_feedback.enums import (
    EnhancementRequestScope,
    EnhancementRequestStatus,
    ExternalRefRole,
    SubmissionPolicy,
)


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
        decline_reason: Why the request was declined (mandatory when the status is `DECLINED`).
        A version's scoring levels are `EnhancementRequestVersionScore` rows, one per axis it has a level on
            (`scoring.py`); an axis with no row is unscored. A score is derived from them on every read under
            the model chosen when viewing, never stored.
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
    decline_reason: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    request: Mapped[EnhancementRequest] = relationship(back_populates="versions")


class EnhancementRequestVersionScore(UUIDPKMixin, Base):
    """The level a request version holds on one axis of the `enhancement_request` scoring scheme.

    Attributes:
        version_id: The version it belongs to (removed with it).
        axis_key: The scheme axis (`scoring.py`); unique per version.
        level_id: The organisation's level on that axis. Deleting a level removes the row (core makes an in-use
            level be reassigned first, so only history loses it).
    """

    __tablename__ = "enhancement_request_version_scores"
    __table_args__ = (
        UniqueConstraint("version_id", "axis_key", name="uq_enhancement_request_version_scores_axis"),
        Index("ix_enhancement_request_version_scores_level", "level_id"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_request_versions.id", ondelete="CASCADE")
    )
    axis_key: Mapped[str] = mapped_column(String(64))
    level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="CASCADE"))


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
        note: Why the two are the same ask, as written by whoever merged (empty when none was given).
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
    note: Mapped[str] = mapped_column(Text, default="")
    unmerged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    unmerged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EnhancementRequestInformed(UUIDPKMixin, TimestampMixin, Base):
    """A requester told the outcome of a request.

    The party is a Stakeholder or Persona of another module, so it is a `(party_type, party_id)` pair with no
    foreign key (as `ArtefactLink` does); it is matched against the request's current requesters on every read,
    so a row for a party that has stopped being one (a link removed, a merge ended) is ignored, and returns to
    counting if the party comes back.

    Attributes:
        request_id: The request (the canonical one when the party asked through a merged duplicate).
        party_type / party_id: The requester record.
        informed_by / informed_at: Who recorded it, and when (UTC).
        note: Optional free text (how or by whom they were told).
    """

    __tablename__ = "enhancement_request_informed"
    __table_args__ = (UniqueConstraint("request_id", "party_type", "party_id", name="uq_enhancement_request_informed_party"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE"), index=True
    )
    party_type: Mapped[str] = mapped_column(String(64))
    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    informed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    informed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")


class ExternalSystemDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base list of outside systems a request can point into (Jira, ServiceNow, ...).
    `sort_order` is the name `services.ordering.move_ordered` expects.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique per organisation.
        sort_order: Display / picker order.
        is_active: Soft-disable; an inactive system drops out of every project's list without being deleted.
    """

    __tablename__ = "external_system_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_external_system_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectExternalSystem(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the external system list: an override of one organisation system, or a system of
    its own (`org_type_id` null, named by `name_override`; enforced by a CHECK). Same shape as every typed
    vocabulary (`services.type_vocabulary.TypeVocabulary`)."""

    __tablename__ = "project_external_systems"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_external_systems_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_external_systems_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_system_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RequestChannelDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base list of the channels a requester can have asked through (Support ticket, Call,
    Email, ...). Shape as `ExternalSystemDefinition`."""

    __tablename__ = "request_channel_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_request_channel_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectRequestChannel(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the channel list; shape as `ProjectExternalSystem`."""

    __tablename__ = "project_request_channels"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_request_channels_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_request_channels_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_channel_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class EnhancementRequestExternalRef(UUIDPKMixin, TimestampMixin, Base):
    """A pointer from a request to an item in an outside tool. Several per request, added and removed on their own
    (each with an audit event), so a change here does not create a content version.

    Exactly one of `org_system_id` (an inbox request: the organisation's system) and `project_system_id` (a
    project request: the project's row for the system) is set (a CHECK), as for any typed record.

    Attributes:
        request_id: The request (removed with it).
        org_system_id / project_system_id: The system, from the list of the request's tier.
        key: The item's key in that system (e.g. `PROJ-123`).
        url: Optional link to the item; only an absolute http(s) URL is accepted (`schemas.check_web_url`).
        role: `ORIGIN` (it came from there) or `DELIVERY` (it is built there).
        created_by: Who added it.
    """

    __tablename__ = "enhancement_request_external_refs"
    __table_args__ = (
        CheckConstraint(
            "(org_system_id IS NOT NULL) <> (project_system_id IS NOT NULL)",
            name="ck_enhancement_request_external_refs_one_system",
        ),
        Index("ix_enhancement_request_external_refs_request", "request_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE")
    )
    org_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_system_definitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_external_systems.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(100), default="")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[ExternalRefRole] = mapped_column(str_enum(ExternalRefRole, 20), default=ExternalRefRole.DELIVERY)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class EnhancementRequestRequesterChannel(UUIDPKMixin, TimestampMixin, Base):
    """The channel a requester asked through. The party is a Stakeholder or Persona of another module, so it is a
    `(party_type, party_id)` pair with no foreign key; the row is matched against the request's current requesters
    on every read (as `EnhancementRequestInformed` is), so one for a party that stopped being a requester is
    ignored. A requester reached through an Engagement has no row and is shown as an Engagement.

    Attributes:
        request_id: The request the channel was recorded on (the canonical one, or a merged duplicate the party
            asked through; the canonical's own row wins when both exist).
        party_type / party_id: The requester record.
        channel_id: The project's channel row.
        set_by: Who recorded it.
    """

    __tablename__ = "enhancement_request_requester_channel"
    __table_args__ = (
        UniqueConstraint("request_id", "party_type", "party_id", name="uq_enhancement_request_requester_channel_party"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enhancement_requests.id", ondelete="CASCADE"), index=True
    )
    party_type: Mapped[str] = mapped_column(String(64))
    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_request_channels.id", ondelete="CASCADE"), index=True
    )
    set_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ProjectFeedbackSettings(UUIDPKMixin, TimestampMixin, Base):
    """A project's Product Feedback settings (a row exists only once a project administrator has set one).

    Attributes:
        project_id: The project (one row at most).
        submission_policy: Who may submit a request; see `SubmissionPolicy`.
        request_page_sections: The project's default order of the sections on a request's page (keys the page
            understands; ones it does not know are ignored and ones left out follow in the built-in order), or `None`
            for the built-in order. A person's own order overrides it.
    """

    __tablename__ = "project_feedback_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    submission_policy: Mapped[SubmissionPolicy] = mapped_column(
        str_enum(SubmissionPolicy, 20), default=SubmissionPolicy.MEMBERS
    )
    request_page_sections: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
