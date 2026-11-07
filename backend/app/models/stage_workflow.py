"""
Module: models.stage_workflow

Stage workflows: the named, ordered phases a project stage moves through.

Responsibilities:
- `StageWorkflow`: a workflow at the organisation tier (`project_id` NULL, offered to every
  project of the organisation) or the project tier (`project_id` set).
- `StageWorkflowPhase`: one phase, with a free-text name and a `StagePhaseKind` that carries
  the behaviour (baseline, edit lock, completion).

Design decisions:
- The first phase by `sort_order` is the starting phase, so a workflow can never have none
  or two (Decided by: Agent).
- Organisation workflows are additive: a project's effective set is its own (else its nearest
  ancestor's) plus the organisation's minus the ones it hid (`services.stage_workflows`).
- A stage keeps `workflow_id` and `phase_id` with no cascade, so a workflow or phase in use
  cannot be deleted from underneath it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import StagePhaseKind

#: Longest workflow or phase name.
MAX_WORKFLOW_NAME_LENGTH = 100


class StageWorkflow(UUIDPKMixin, TimestampMixin, Base):
    """A named workflow; organisation tier when `project_id` is NULL.

    Attributes:
        organization_id: Owning organisation (always set, so a project row can be reached from it).
        project_id: Owning project for the project tier, else NULL.
        name: Unique within its tier (per organisation, or per project).
        sort_order: Position within its tier.
    """

    __tablename__ = "stage_workflows"
    __table_args__ = (
        Index("uq_stage_workflows_org_name", "organization_id", "name", unique=True, postgresql_where=sa_text("project_id IS NULL")),
        Index("uq_stage_workflows_project_name", "project_id", "name", unique=True, postgresql_where=sa_text("project_id IS NOT NULL")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(MAX_WORKFLOW_NAME_LENGTH))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class StageWorkflowPhase(UUIDPKMixin, Base):
    """One phase of a workflow; the lowest `sort_order` is the starting phase."""

    __tablename__ = "stage_workflow_phases"
    __table_args__ = (UniqueConstraint("workflow_id", "name"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflows.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(MAX_WORKFLOW_NAME_LENGTH))
    kind: Mapped[StagePhaseKind] = mapped_column(str_enum(StagePhaseKind, 20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
