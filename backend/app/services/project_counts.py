"""
Module: services.project_counts

The counts behind the project overview's core metrics: live requirements (and how many are completed, by
status), change requests by outcome and distinct requirement attachments, for one project.

Responsibilities:
- Report each stage's completion (`project_stage_progress`): a stage that has been baselined shows completion
  across the requirements captured in that baseline; a stage not yet approved has no baseline, so it shows the
  project's current requirement count at 0% complete.
- Compute each figure as a database aggregate in a fixed number of statements, so the cost does not grow with the
  number of requirements (no id list is read back or sent in an `IN (...)`).

Design decisions:
- Shared by the project metrics endpoint and the overview widget metrics (`services.overview_metrics`), so a
  figure has one definition wherever it is shown.
- Completion is `Requirement.is_completed`, an overlay marker independent of `RequirementVersion.status`, so it is
  read off the identity row, not the version.

Dependencies: the requirement, change request, file and stage models, `services.stage_workflows`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.enums import BaselineKind, ChangeRequestStatus, StagePhaseKind
from app.models.file import RequirementFile
from app.models.project import ProjectStage
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.services.stage_workflows import phase_index


@dataclass
class ProjectCounts:
    """One project's overview counts (`id` is the project, which is what `ProjectScope.collect` keys rows on).

    Attributes:
        id: The project.
        requirements: Live (not archived) requirements.
        completed: Of those, how many are marked completed.
        proposed: Change requests submitted or in review.
        approved: Change requests approved.
        rejected: Change requests rejected.
        files: Distinct files attached to live requirements.
        by_status: Live requirements by current-version status value.
    """

    id: UUID
    requirements: int = 0
    completed: int = 0
    proposed: int = 0
    approved: int = 0
    rejected: int = 0
    files: int = 0
    by_status: dict[str, int] = field(default_factory=dict)


def project_counts(db: Session, pid: UUID) -> ProjectCounts:
    """The overview counts of one project: live requirements (and how many are completed, by status), change
    requests by outcome, and distinct requirement attachments.

    Args:
        db: Active session (read only).
        pid: The project.

    Returns:
        The counts; every figure is zero for an empty project.
    """
    counts = ProjectCounts(id=pid)
    live = (Requirement.project_id == pid, Requirement.is_archived.is_(False))
    counts.requirements, completed = db.execute(
        select(func.count(), func.count().filter(Requirement.is_completed.is_(True))).where(*live)
    ).one()
    counts.completed = completed
    if counts.requirements:
        for status_value, total in db.execute(
            select(RequirementVersion.status, func.count())
            .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
            .where(*live, RequirementVersion.valid_to.is_(None))
            .group_by(RequirementVersion.status)
        ).all():
            counts.by_status[status_value.value] = total
        counts.files = db.scalar(
            select(func.count(RequirementFile.file_id.distinct()))
            .join(Requirement, Requirement.id == RequirementFile.requirement_id)
            .where(*live)
        ) or 0
    by_outcome = {outcome: total for outcome, total in db.execute(
        select(ChangeRequest.status, func.count()).where(ChangeRequest.project_id == pid).group_by(ChangeRequest.status)
    ).all()}
    counts.proposed = by_outcome.get(ChangeRequestStatus.SUBMITTED, 0) + by_outcome.get(ChangeRequestStatus.IN_REVIEW, 0)
    counts.approved = by_outcome.get(ChangeRequestStatus.APPROVED, 0)
    counts.rejected = by_outcome.get(ChangeRequestStatus.REJECTED, 0)
    return counts


@dataclass(frozen=True)
class StageProgress:
    """One stage's completion.

    Attributes:
        stage_id: The stage.
        name: Stage name.
        phase_name: Name of the stage's current phase.
        phase_kind: Kind of that phase.
        requirement_count: Requirements the percentage is over.
        completed_percent: Share of them completed, one decimal.
    """

    stage_id: UUID
    name: str
    phase_name: str
    phase_kind: StagePhaseKind
    requirement_count: int
    completed_percent: float


def project_stage_progress(db: Session, project_id: UUID, own_requirement_count: int) -> list[StageProgress]:
    """Each stage's completion, in stage order.

    Args:
        db: Active session (read only).
        project_id: The project (its own stages; never a related project's).
        own_requirement_count: The project's own live requirement count, shown for a stage with no baseline.

    Returns:
        One row per stage.
    """
    stages = db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()
    stage_phases = phase_index(db, {s.phase_id for s in stages})
    # One query for every baselined stage: items captured and how many of them are now completed (the
    # oldest baseline of a stage when it somehow has several). A component's own baseline (component phases)
    # holds that component's requirements only, so the oldest one per component is added to its stage's.
    baselined: dict[UUID, tuple[int, int]] = {}
    seen_component_baselines: set[tuple[UUID, UUID | None]] = set()
    for stage_id, component_id, total, done in db.execute(
        select(Baseline.stage_id, Baseline.component_id, func.count(BaselineItem.requirement_id),
               func.count(Requirement.id).filter(Requirement.is_completed.is_(True)))
        .select_from(Baseline)
        .outerjoin(BaselineItem, BaselineItem.baseline_id == Baseline.id)
        .outerjoin(Requirement, Requirement.id == BaselineItem.requirement_id)
        .where(Baseline.project_id == project_id, Baseline.kind == BaselineKind.STAGE)
        .group_by(Baseline.id, Baseline.stage_id, Baseline.component_id, Baseline.created_at)
        .order_by(Baseline.created_at, Baseline.id)
    ).all():
        if (stage_id, component_id) in seen_component_baselines:
            continue
        seen_component_baselines.add((stage_id, component_id))
        previous_total, previous_done = baselined.get(stage_id, (0, 0))
        baselined[stage_id] = (previous_total + total, previous_done + done)
    rows: list[StageProgress] = []
    for stage in stages:
        if stage.id in baselined:
            stage_requirement_count, stage_completed = baselined[stage.id]
            stage_percent = (stage_completed / stage_requirement_count * 100.0) if stage_requirement_count else 0.0
        else:
            stage_requirement_count = own_requirement_count
            stage_percent = 0.0
        rows.append(StageProgress(
            stage_id=stage.id, name=stage.name, phase_name=stage_phases[stage.phase_id].name,
            phase_kind=stage_phases[stage.phase_id].kind, requirement_count=stage_requirement_count,
            completed_percent=round(stage_percent, 1),
        ))
    return rows
