"""
Module: models.stage_workflow

Stage workflows: the named, ordered phases a project stage moves through.

Responsibilities:
- `StageWorkflow`: a workflow at the organisation tier (`project_id` NULL, offered to every
  project of the organisation) or the project tier (`project_id` set).
- `StageWorkflowPhase`: one phase, with a free-text name and a `StagePhaseKind` that carries
  the behaviour (baseline, edit lock, completion).
- `ComponentStageState`: where one component stands in one project stage when component phases
  are on (its own workflow and phase, an optional owner, approval and completion stamps).
- `StagePhasePlan`: the expected completion range and the actual start and completion of one phase of a
  stage (`component_id` NULL) or of a component's track within it (`component_id` set).

Design decisions:
- The first phase by `sort_order` is the starting phase, so a workflow can never have none
  or two (Decided by: Agent).
- Organisation workflows are additive: a project's effective set is its own (else its nearest
  ancestor's) plus the organisation's minus the ones it hid (`services.stage_workflows`).
- A stage keeps `workflow_id` and `phase_id` with no cascade, so a workflow or phase in use
  cannot be deleted from underneath it; a component state does the same.
- A component with no state row for a stage follows the stage's workflow at its starting phase,
  so a row exists only once a component picks a workflow, a phase, an owner or "not applicable".
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import StagePhaseKind
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column

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


class ComponentStageState(UUIDPKMixin, TimestampMixin, Base):
    """A component's workflow position within one project stage (one row per component and stage).

    Attributes:
        project_id: The project, kept here so a project's states are read and exported in one query.
        component_id / stage_id: The track; unique together.
        workflow_id / phase_id: The workflow the component follows for the stage and its current phase;
            as with a stage, the phase's kind (never its name) drives approval and completion.
        not_applicable: The component takes no part in this stage; its phase is not advanced.
        owner_type / owner_id: Optional principal (a user or a group) who is reminded about the track and
            may move it, including into a locked phase.
        approved_at / approved_by: Set on entering a locked phase (the baseline is written then).
        completed_at / completed_by: Set on entering a closed phase.
    """

    __tablename__ = "component_stage_states"
    __table_args__ = (UniqueConstraint("component_id", "stage_id"), principal_check_constraint("owner", nullable=True))

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="CASCADE"))
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflows.id"), index=True)
    phase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflow_phases.id"), index=True)
    not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class StagePhasePlan(UUIDPKMixin, TimestampMixin, Base):
    """The schedule and actual dates of one phase in one stage, or in one component's track within it.

    A row exists only once a phase is given dates or entered, so a stage nobody scheduled has none.

    Attributes:
        project_id: The project, kept here so its plans are read and exported in one query.
        stage_id: The project stage.
        component_id: NULL for the stage's own phase, else the component whose track the phase belongs to.
        phase_id: The workflow phase; deleting the phase removes its plan.
        expected_from / expected_to: Calendar dates in the planner's own day (a date, never an instant);
            `expected_from <= expected_to` when both are set.
        started_at / completed_at: Past instants in UTC, set when the phase is entered and left forward (or
            entered while closed); moving back to a phase clears its `completed_at`.
        upcoming_notified_for / overdue_notified_for: The `expected_from` and `expected_to` last notified, so
            each date is reminded once and a rescheduled phase is reminded again. Derived, never exported.
    """

    __tablename__ = "stage_phase_plans"
    __table_args__ = (
        Index("uq_stage_phase_plans_stage", "stage_id", "phase_id", unique=True, postgresql_where=sa_text("component_id IS NULL")),
        Index(
            "uq_stage_phase_plans_component", "stage_id", "component_id", "phase_id", unique=True,
            postgresql_where=sa_text("component_id IS NOT NULL"),
        ),
        CheckConstraint("expected_from IS NULL OR expected_to IS NULL OR expected_from <= expected_to", name="ck_stage_phase_plans_range"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="CASCADE"))
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="CASCADE"), nullable=True
    )
    phase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stage_workflow_phases.id", ondelete="CASCADE"), index=True)
    expected_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upcoming_notified_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    overdue_notified_for: Mapped[date | None] = mapped_column(Date, nullable=True)
