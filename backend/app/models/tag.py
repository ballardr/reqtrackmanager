"""
Module: models.tag

Tags: short labels (a theme, a release, a regulation) attached to any record of any registered
artefact type, drawn from a governed vocabulary.

Responsibilities:
- `Tag`: one vocabulary entry, owned by a project (`project_id` set) or by the organisation
  (`project_id` NULL, for organisation-owned records such as personas and strategies).
- `ArtefactTag`: the attachment of a tag to a record.

Design decisions:
- `ArtefactTag.artefact_type` is a plain string validated against the module registry
  (`app.modules.registry.get_all_registered_artefact_types`), exactly as `ArtefactLink.source_type`
  is: a closed enum would need a per-module edit to this core file. `artefact_id` has no foreign
  key (the id points into a different table per type).
- `ArtefactTag.project_id` records the project that owns the tagged record (NULL for an
  organisation-owned record), so usage counts and filters need no per-type join and a project's
  attachments go with the project (`ON DELETE CASCADE`).
- Names are unique per vocabulary case-insensitively (`name_key` is the case-folded name); the
  name keeps the casing first used. Uniqueness is two partial indexes because Postgres treats
  NULLs in a unique constraint as distinct.
- Tags are not Restricted-classified data (docs/soc2/policies data classification).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, utcnow

#: Maximum tag name length in characters (after trimming).
MAX_TAG_NAME_LENGTH = 40


class Tag(UUIDPKMixin, TimestampMixin, Base):
    """One entry of a tag vocabulary.

    Attributes:
        organization_id: The owning organisation (always set).
        project_id: The owning project, or NULL for the organisation's own vocabulary.
        name: Display name, in the casing first used.
        name_key: Case-folded, whitespace-collapsed name; unique within the vocabulary.
        colour: Optional `#rrggbb` accent for the chip.
        created_by: The user who created it (kept NULL if the user is later removed).
    """

    __tablename__ = "tags"
    __table_args__ = (
        Index("ux_tags_project_key", "project_id", "name_key", unique=True, postgresql_where=sa_text("project_id IS NOT NULL")),
        Index("ux_tags_org_key", "organization_id", "name_key", unique=True, postgresql_where=sa_text("project_id IS NULL")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(MAX_TAG_NAME_LENGTH))
    name_key: Mapped[str] = mapped_column(String(MAX_TAG_NAME_LENGTH))
    colour: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ArtefactTag(Base):
    """A tag attached to one record.

    Attributes:
        tag_id: The tag (deleting it removes its attachments).
        artefact_type / artefact_id: The tagged record; the type is a registered artefact type.
        project_id: The project owning the record; NULL for an organisation-owned record.
        created_by: The user who attached it.
        created_at: When it was attached (UTC); "last used" in the usage tables.
    """

    __tablename__ = "artefact_tags"
    __table_args__ = (
        Index("ix_artefact_tags_record", "artefact_type", "artefact_id"),
        Index("ix_artefact_tags_project_type", "project_id", "artefact_type"),
    )

    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    artefact_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    artefact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
