"""
Module: services.baseline

Implements stage-approval baselining (C-G-10) and the resulting
direct-edit lock on requirements (C-G-12): once a project has any stage that
has reached APPROVED (or COMPLETED), its requirements may only be modified
through an approved change request.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import RequirementStatus, StageStatus
from app.models.project import Project, ProjectStage
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.user import User
from app.services.requirements import apply_new_version


def project_is_locked(db: Session, project_id) -> bool:
    """Returns True if the project has ever approved a stage (C-G-12)."""
    locked_stage = db.scalar(
        select(ProjectStage).where(
            ProjectStage.project_id == project_id,
            ProjectStage.status.in_([StageStatus.APPROVED, StageStatus.COMPLETED]),
        )
    )
    return locked_stage is not None


def create_baseline_for_stage(db: Session, project: Project, stage: ProjectStage, actor: User) -> Baseline:
    """Snapshots every non-archived requirement's current version into a baseline.

    Args:
        db: An active database session (changes are flushed, not committed;
            the caller commits as part of the stage-transition transaction).
        project: The project whose requirements are being baselined.
        stage: The stage being approved.
        actor: The user performing the approval.

    Returns:
        The created Baseline.

    Approving a stage also approves any requirement still in draft/reviewed
    status, since baselining a stage is the formal act of turning scoped
    requirements into the project's approved requirement set.
    """
    baseline = Baseline(project_id=project.id, stage_id=stage.id, label=f"{stage.name} baseline", created_by=actor.id)
    db.add(baseline)
    db.flush()

    requirements = db.scalars(
        select(Requirement).where(Requirement.project_id == project.id, Requirement.is_archived.is_(False))
    ).all()
    for requirement in requirements:
        current_version = db.scalar(
            select(RequirementVersion).where(
                RequirementVersion.requirement_id == requirement.id, RequirementVersion.valid_to.is_(None)
            )
        )
        if current_version is None:
            continue
        if current_version.status in (RequirementStatus.DRAFT, RequirementStatus.REVIEWED):
            current_version = apply_new_version(
                db, requirement, current_version, actor,
                status_value=RequirementStatus.APPROVED,
                change_note=f"Approved as part of '{stage.name}' stage baseline.",
            )
            db.flush()
        db.add(
            BaselineItem(
                baseline_id=baseline.id,
                requirement_id=requirement.id,
                requirement_version_id=current_version.id,
            )
        )
    return baseline
