"""
Module: modules.stakeholders.models

Data model for the Stakeholders & Personas module (docs/plans/module-02-
stakeholders-and-personas-plan.md), Phase 1.1 (Persona):

- `Persona` / `PersonaVersion` — identity row plus temporal content
  snapshots, the same split `models.requirement.Requirement`/
  `RequirementVersion` and Context & Strategy's `GuidingPrinciple`/
  `GuidingPrincipleVersion` use (Phase 0 resolution 6: full history). One
  table with a `scope` discriminator and exactly one of `organization_id`/
  `project_id` set (resolution 2: an org-level persona is one live, shared
  record). Status and `weight` are versioned content: a lifecycle change or
  a re-weighting is a content change like any other.
- `PersonaTypeDefinition` / `ProjectPersonaType` — the two-tier type
  vocabulary (resolution 3), the same shape as Context & Strategy's
  `PainPointTypeDefinition`/`ProjectPainPointType`: an org base list plus
  per-project rename/reorder/disable/add. `PersonaVersion` references either
  an org type (org-scoped persona) or a project type row (project-scoped
  persona); both are nullable because a type is optional.
- `ProjectPersonaWeight` — a project's override of a persona's weight
  (resolution 5), resolved through the project hierarchy by
  `service.resolve_persona_weight`.
- `PersonaComment` / `PersonaCommentFile` / `PersonaFile` — module-local
  comment and attachment tables (resolution 8), since extending the core
  `ReviewTargetType` enum would be a per-module edit to a core file.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus


class PersonaTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base Persona type vocabulary (Primary/Secondary/
    Negative by default). `sort_order` keeps the name `services.ordering.
    move_ordered` expects.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique per organisation.
        sort_order: Display/picker order.
        is_active: Soft-disable — an inactive type drops out of every
            project's effective list without being deleted.
    """

    __tablename__ = "persona_type_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_persona_type_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectPersonaType(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the Persona type vocabulary: a local
    override of one org type, or a fully project-local type.

    Attributes:
        project_id: The owning project.
        org_type_id: The org type overridden, or `NULL` for a project-local
            type.
        name_override: Replaces the org type's name here; the type's only
            name when `org_type_id` is `NULL` (enforced by a CHECK).
        display_order_override: Replaces the org type's `sort_order` here.
        is_enabled: Whether the type is offered when creating a persona in
            this project.
    """

    __tablename__ = "project_persona_types"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_persona_types_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_persona_types_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persona_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Persona(UUIDPKMixin, TimestampMixin, Base):
    """A Persona's stable identity (organisation- or project-scoped).

    Attributes:
        scope: Which of `organization_id`/`project_id` is populated.
        organization_id: Set (and `project_id` null) for an org persona.
        project_id: Set (and `organization_id` null) for a project persona.
        creator_id: Who created the record.
        is_archived / archived_at / archived_by: Soft-delete.
    """

    __tablename__ = "personas"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)",
            name="ck_personas_scope_matches_owner",
        ),
    )

    scope: Mapped[PersonaScope] = mapped_column(str_enum(PersonaScope, 20))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    versions: Mapped[list[PersonaVersion]] = relationship(
        back_populates="persona", order_by="PersonaVersion.version_number"
    )


class PersonaVersion(UUIDPKMixin, Base):
    """One point-in-time snapshot of a Persona's content (temporal shape
    copied from `RequirementVersion`).

    Attributes:
        valid_from / valid_to: Effective interval; `valid_to` is null for
            the current version.
        name: Display name.
        description: Free-text summary.
        org_type_id / project_type_id: The persona's type — an org type for
            an org persona, a project type row for a project persona; both
            null when untyped (a CHECK forbids both being set).
        role_title: Job title/role the persona represents.
        goals, needs, behaviours, context_environment, skills_proficiency,
        frequency_of_use, constraints: The §10 persona descriptive fields,
            free text.
        weight: Importance for per-persona scoring (Module 1 Phase 11);
            null or positive. Null means "no opinion" and every persona is
            then weighted equally.
        status: Lifecycle state.
        owner_id: The user responsible for the record.
        champion_id: The colleague accountable for keeping the persona
            accurate (Phase 0 resolution 13); descriptive only, grants no
            permissions.
        change_note: Free-text reason for the change.
        created_by / created_at: Who made this snapshot, and when.
    """

    __tablename__ = "persona_versions"
    __table_args__ = (
        UniqueConstraint("persona_id", "version_number"),
        CheckConstraint("weight IS NULL OR weight > 0", name="ck_persona_versions_weight_positive"),
        CheckConstraint(
            "org_type_id IS NULL OR project_type_id IS NULL", name="ck_persona_versions_one_type_reference"
        ),
        Index("ix_persona_versions_current", "persona_id", unique=False, postgresql_where=sa_text("valid_to IS NULL")),
    )

    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("personas.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persona_type_definitions.id"), nullable=True
    )
    project_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_persona_types.id"), nullable=True
    )
    role_title: Mapped[str] = mapped_column(String(300), default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    needs: Mapped[str] = mapped_column(Text, default="")
    behaviours: Mapped[str] = mapped_column(Text, default="")
    context_environment: Mapped[str] = mapped_column(Text, default="")
    skills_proficiency: Mapped[str] = mapped_column(Text, default="")
    frequency_of_use: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[PersonaStatus] = mapped_column(str_enum(PersonaStatus, 20), default=PersonaStatus.DRAFT)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    champion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    persona: Mapped[Persona] = relationship(back_populates="versions")


class ProjectPersonaWeight(UUIDPKMixin, TimestampMixin, Base):
    """A project's override of one persona's weight (Phase 0 resolution 5).
    Override-only: a project with no row inherits from its nearest ancestor
    project's row, then `PersonaVersion.weight`, then equal weighting.

    Attributes:
        project_id: The overriding project.
        persona_id: The persona whose weight is overridden.
        weight: The overriding weight; positive.
    """

    __tablename__ = "project_persona_weights"
    __table_args__ = (
        UniqueConstraint("project_id", "persona_id", name="uq_project_persona_weights_project_persona"),
        CheckConstraint("weight > 0", name="ck_project_persona_weights_positive"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("personas.id", ondelete="CASCADE"))
    weight: Mapped[float] = mapped_column(Float)


class PersonaComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `Persona`.

    Attributes:
        persona_id: The commented-on persona.
        author_id: Who wrote it.
        body: Comment text.
        edited_at: Set only when the body changed after creation.
    """

    __tablename__ = "persona_comments"

    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("personas.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PersonaCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `PersonaComment`."""

    __tablename__ = "persona_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persona_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class PersonaFile(UUIDPKMixin, Base):
    """Links a directly uploaded file to a `Persona`. A project persona's
    files are project-authorized uploads (resolved by
    `service.resolve_persona_file_project_id`); an org persona's are org
    shared resources (`FileAsset.is_org_resource=True`)."""

    __tablename__ = "persona_files"
    __table_args__ = (UniqueConstraint("persona_id", "file_id"),)

    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("personas.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
