"""
Module: services.baseline

Implements stage-approval baselining (C-G-10) and the resulting
direct-edit lock on requirements (C-G-12): entering a locked phase approves
the project's requirements (with component phases on, a component's own locked
phase approves only that component's requirements for the stage), and an
approved requirement may only be modified through an approved change request.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import RequirementStatus
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.user import User
from app.services.component_stages import tracked_component_ids
from app.services.requirements import apply_new_version, get_current_version_for_update


def create_baseline_for_stage(
    db: Session, project: Project, stage: ProjectStage, actor: User, *, component_id: UUID | None = None,
) -> Baseline:
    """Snapshots non-archived requirements' current versions into a baseline.

    Args:
        db: An active database session (changes are flushed, not committed;
            the caller commits as part of the stage-transition transaction).
        project: The project whose requirements are being baselined.
        stage: The stage being approved.
        actor: The user performing the approval.
        component_id: When set (a component entering a locked phase), only that component's requirements
            that target `stage` are baselined and approved. When not set and component phases are on, the
            requirements of components that have their own track for `stage` are left to those tracks.

    Returns:
        The created Baseline.

    Approving a stage also approves any requirement still in draft/reviewed
    status, since baselining a stage is the formal act of turning scoped
    requirements into the project's approved requirement set.
    """
    label = f"{stage.name} baseline"
    query = (
        select(Requirement)
        .where(Requirement.project_id == project.id, Requirement.is_archived.is_(False))
        .order_by(Requirement.id)
    )
    if component_id is not None:
        component = db.get(ProjectComponent, component_id)
        label = f"{stage.name} / {component.name if component else 'component'} baseline"
        query = query.where(
            Requirement.component_id == component_id,
            Requirement.id.in_(
                select(RequirementVersion.requirement_id).where(
                    RequirementVersion.valid_to.is_(None), RequirementVersion.target_stage_id == stage.id
                )
            ),
        )
    else:
        tracked = tracked_component_ids(db, project, stage)
        if tracked:
            query = query.where(Requirement.component_id.not_in(tracked))
    baseline = Baseline(project_id=project.id, stage_id=stage.id, component_id=component_id, label=label, created_by=actor.id)
    db.add(baseline)
    db.flush()

    requirements = db.scalars(query).all()
    for requirement in requirements:
        current_version = db.scalar(
            select(RequirementVersion).where(
                RequirementVersion.requirement_id == requirement.id, RequirementVersion.valid_to.is_(None)
            )
        )
        if current_version is None:
            continue
        if current_version.status in (RequirementStatus.DRAFT, RequirementStatus.REVIEWED):
            # Only a requirement about to be approved is locked (in id order, so two baselines cannot
            # deadlock), and it is re-read under the lock: a concurrent edit may have moved it on.
            current_version = get_current_version_for_update(db, requirement.id)
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
