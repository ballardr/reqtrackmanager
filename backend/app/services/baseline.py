"""
Module: services.baseline

Implements stage-approval baselining (C-G-10) and the resulting
direct-edit lock on requirements (C-G-12): entering a locked phase approves
the project's requirements (with component phases on, a component's own locked
phase approves only that component's requirements for the stage), and an
approved requirement may only be modified through an approved change request.

A baseline also holds the records of every module that registered a
`BaselineSnapshotProvider` (a JSON copy per record, so it outlives the record), and a manual baseline can be taken
at any time without a stage and without approving or locking anything. Design decisions: requirements keep their
version rows; a module's records are captured only through its provider and only where the module is on for the
project; a manual baseline captures only the types the person may snapshot.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import BaselineKind, RequirementStatus
from app.models.project import Project, ProjectComponent, ProjectStage
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.user import User
from app.modules.registry import (
    BaselineSnapshotContext,
    BaselineSnapshotProvider,
    get_baseline_snapshot_providers,
    is_module_enabled_for_project,
)
from app.services.component_stages import tracked_component_ids
from app.services.rbac import can_manage_project_settings, get_effective_permissions, permission_satisfied
from app.services.requirements import apply_new_version, get_current_version_for_update

REQUIREMENT_ITEM_TYPE = "requirement"


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
    baseline = Baseline(
        project_id=project.id, kind=BaselineKind.STAGE, stage_id=stage.id, component_id=component_id, label=label,
        created_by=actor.id,
    )
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
                item_type=REQUIREMENT_ITEM_TYPE,
                item_id=requirement.id,
                requirement_id=requirement.id,
                requirement_version_id=current_version.id,
            )
        )
    context = BaselineSnapshotContext(
        kind=BaselineKind.STAGE.value, stage_id=stage.id, component_id=component_id, actor_id=actor.id
    )
    add_module_items(db, baseline, project, context, enabled_snapshot_providers(db, project))
    return baseline


def enabled_snapshot_providers(db: Session, project: Project) -> dict[str, BaselineSnapshotProvider]:
    """The snapshot providers of the modules that are on for the project, by artefact type.

    Args:
        db: An active database session.
        project: The project being baselined.

    Returns:
        `{artefact type: provider}`; empty when no module that registered one is on for the project.
    """
    return {
        artefact_type: provider
        for artefact_type, (module_key, provider) in sorted(get_baseline_snapshot_providers().items())
        if is_module_enabled_for_project(db, project.id, module_key)
    }


def add_module_items(
    db: Session,
    baseline: Baseline,
    project: Project,
    context: BaselineSnapshotContext,
    providers: dict[str, BaselineSnapshotProvider],
) -> dict[str, int]:
    """Runs the given providers and stores what they capture as items of the baseline.

    Args:
        db: An active database session (rows are added and flushed, never committed).
        baseline: The baseline being written (already flushed, so it has an id).
        project: The project being baselined.
        context: What is being baselined and for whom.
        providers: `{artefact type: provider}`, from `enabled_snapshot_providers`.

    Returns:
        The number of items stored per artefact type.
    """
    counts: dict[str, int] = {}
    for artefact_type, provider in providers.items():
        records = provider.snapshot(db, project, context)
        for record in records:
            db.add(BaselineItem(
                baseline_id=baseline.id, item_type=artefact_type, item_id=record.item_id, snapshot=record.content,
            ))
        counts[artefact_type] = len(records)
    db.flush()
    return counts


def manual_baseline_types(db: Session, project: Project, actor: User) -> list[str]:
    """The item types the person may put in a manual baseline of the project.

    Args:
        db: An active database session.
        project: The project.
        actor: The person taking the baseline.

    Returns:
        `requirement` when they manage the project, then each enabled module type whose snapshot permission they
        hold. A server administrator gets no extra: this is customer content.
    """
    types = [REQUIREMENT_ITEM_TYPE] if can_manage_project_settings(db, actor, project) else []
    providers = enabled_snapshot_providers(db, project)
    if providers:
        held = get_effective_permissions(db, actor.id, organization_id=project.organization_id, project_id=project.id)
        types.extend(t for t, p in providers.items() if permission_satisfied(held, p.permission))
    return types


def create_manual_baseline(
    db: Session, project: Project, actor: User, label: str, item_types: list[str],
) -> tuple[Baseline, dict[str, int]]:
    """Takes a manual baseline: a snapshot of the chosen types as they stand, with no stage, no approval and no lock.

    Args:
        db: An active database session (changes are flushed; the caller audits and commits).
        project: The project to baseline.
        actor: The person taking it.
        label: The baseline's name.
        item_types: The types to capture, already checked against `manual_baseline_types`.

    Returns:
        The baseline and the number of items captured per type.
    """
    baseline = Baseline(project_id=project.id, kind=BaselineKind.MANUAL, label=label, created_by=actor.id)
    db.add(baseline)
    db.flush()
    counts: dict[str, int] = {}
    if REQUIREMENT_ITEM_TYPE in item_types:
        rows = db.execute(
            select(Requirement.id, RequirementVersion.id)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(
                Requirement.project_id == project.id, Requirement.is_archived.is_(False),
                RequirementVersion.valid_to.is_(None),
            )
            .order_by(Requirement.id)
        ).all()
        for requirement_id, version_id in rows:
            db.add(BaselineItem(
                baseline_id=baseline.id, item_type=REQUIREMENT_ITEM_TYPE, item_id=requirement_id,
                requirement_id=requirement_id, requirement_version_id=version_id,
            ))
        counts[REQUIREMENT_ITEM_TYPE] = len(rows)
    context = BaselineSnapshotContext(kind=BaselineKind.MANUAL.value, stage_id=None, component_id=None, actor_id=actor.id)
    providers = {t: p for t, p in enabled_snapshot_providers(db, project).items() if t in item_types}
    counts.update(add_module_items(db, baseline, project, context, providers))
    db.flush()
    return baseline, counts
