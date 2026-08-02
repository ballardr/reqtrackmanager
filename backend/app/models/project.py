"""
Module: models.project

Defines projects and everything scoped to a single project: stages
(lifecycle horizons, C-G-08), components and categories (used as requirement
ID prefixes, C-G-07), project groups (C-U-11) which may nest organisation
groups (C-U-12), and direct per-user project role assignments.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum, utcnow
from app.models.enums import ProjectRole, StageReviewResponseChoice, StageStatus


class Project(UUIDPKMixin, TimestampMixin, Base):
    """An engineering project that requirements and change requests belong to.

    Attributes:
        next_requirement_seq: Monotonically increasing counter used to
            generate unique requirement identifiers (C-G-06). Never reused,
            including for archived requirements.
    """

    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(2000), default="")
    next_requirement_seq: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Whether project "members" may submit change requests (C-U-13); defaults
    # to enabled per the requirement's clarification.
    allow_member_change_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether this project can be used as a template for new projects (C-E-05).
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}.
    # Keys are restricted to a fixed, documented set (see schemas/project.py);
    # this is not a freeform key-value store.
    terminology: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Persisted report structure (mock's "Report Setup": Project Intro / Body
    # Chapters / Appendices), used as the default when a report is generated
    # without ad-hoc pre_markdown/post_markdown overrides (see
    # services/reports.py). Chapters/appendices are each an ordered list of
    # {"title": str, "body": str} objects.
    report_intro: Mapped[str] = mapped_column(Text, default="")
    report_chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    report_appendices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Massif (v3): default notification lead time (in days) before a
    # requirement's review_date, used when a requirement doesn't set its own
    # review_lead_days override (C-R-08).
    review_reminder_lead_days_default: Mapped[int] = mapped_column(Integer, default=7)


class ProjectStage(UUIDPKMixin, TimestampMixin, Base):
    """One lifecycle horizon of a project (C-G-08, C-G-10).

    Attributes:
        status: scoping -> review -> approved -> completed.
        sort_order: Display/sequence order among a project's stages.
        approved_at / approved_by: Set when the stage transitions to
            approved; this is also when a baseline snapshot is written
            (C-G-10) and requirement edits become change-request-only
            (C-G-12).
    """

    __tablename__ = "project_stages"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[StageStatus] = mapped_column(str_enum(StageStatus, 20), default=StageStatus.SCOPING)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Massif (v3): completion tracking (C-P-02) and review-deadline "assumed
    # approval" (C-R-05). completed_at/completed_by mirror the existing
    # approved_at/approved_by pattern. review_deadline is set by a project
    # manager while the stage is in REVIEW; the daily scheduler sweep
    # (services/stages.py) auto-approves the stage once it passes, unless a
    # stakeholder explicitly rejected via StageReviewResponse.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageReviewResponse(UUIDPKMixin, Base):
    """A stakeholder's response to a project stage's review deadline (C-R-05).

    One row per (stage, user) per review cycle; rows are cleared whenever a
    new `review_deadline` is set on the stage, so a later review cycle isn't
    contaminated by an earlier cycle's responses.
    """

    __tablename__ = "stage_review_responses"
    __table_args__ = (UniqueConstraint("stage_id", "user_id"),)

    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_stages.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    response: Mapped[StageReviewResponseChoice] = mapped_column(str_enum(StageReviewResponseChoice, 20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectComponent(UUIDPKMixin, TimestampMixin, Base):
    """A project component with a settable identifier prefix (C-G-07)."""

    __tablename__ = "project_components"
    __table_args__ = (UniqueConstraint("project_id", "prefix"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProjectCategory(UUIDPKMixin, TimestampMixin, Base):
    """A requirement category with a settable identifier prefix (C-G-07)."""

    __tablename__ = "project_categories"
    __table_args__ = (UniqueConstraint("project_id", "prefix"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProjectGroup(UUIDPKMixin, TimestampMixin, Base):
    """A named group that grants one of the four fixed project roles (C-U-11).

    Ossa (v1) uses a fixed role vocabulary (ProjectRole) rather than
    customisable permissions, so a group's purpose is simply to bulk-assign
    one of those roles to many users (and, via nested org groups, whole
    organisational teams, C-U-12).
    """

    __tablename__ = "project_groups"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectGroupMember(UUIDPKMixin, TimestampMixin, Base):
    """A member of a project group: either a user or a nested org group.

    Exactly one of user_id / org_group_id must be set.
    """

    __tablename__ = "project_group_members"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (org_group_id IS NOT NULL)::int = 1",
            name="ck_project_group_member_exactly_one_target",
        ),
    )

    project_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_groups.id")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    org_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id"), nullable=True
    )


class UserProjectRole(UUIDPKMixin, TimestampMixin, Base):
    """A direct (non-group) project role assignment for a single user."""

    __tablename__ = "user_project_roles"
    __table_args__ = (UniqueConstraint("user_id", "project_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole))


class FavoriteProject(UUIDPKMixin, Base):
    """A user's favourited project, shown at the top of their project list (U-U-03)."""

    __tablename__ = "favorite_projects"
    __table_args__ = (UniqueConstraint("user_id", "project_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
