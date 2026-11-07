"""
Module: services.stage_workflows

Stage workflows: the phases a project stage moves through, and what each phase kind does.

Responsibilities:
- Resolve a project's effective workflow set (own, else nearest ancestor's, plus the
  organisation's minus the ones the project hid) and seed the organisation's "Standard" one.
- Validate and write a workflow with its ordered phases.
- Move a stage between phases, applying the behaviour of the phase kind: baseline and approval
  on entering a locked phase, completion on entering a closed one.
- Answer the questions other code asks of a phase kind: may requirements be reordered.

Design decisions:
- Behaviour is read from `StagePhaseKind`, never from a phase name (Decided by: User).
- Moves are free in either direction; entering or leaving a locked phase needs the project
  manager role, because leaving one silently unlocks requirements outside the change-request
  process (Decided by: Agent; the entering rule is the user's, the leaving rule closes the
  bypass it would otherwise leave).
- Nested projects: own workflows, else the nearest ancestor's, always plus the additive
  organisation tier (Decided by: Agent, the `resolve_effective_action_types` shape).
- A workflow in use cannot be deleted, and a phase in use can be renamed but not removed or
  given another kind, so a stage can never be silently unlocked by an edit to its workflow.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole, StagePhaseKind
from app.models.project import Project, ProjectStage
from app.models.stage_workflow import MAX_WORKFLOW_NAME_LENGTH, StageWorkflow, StageWorkflowPhase
from app.models.user import User
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

#: Registered `definition_suppression` kind for hiding an organisation workflow in a project.
WORKFLOW_KIND = "stage_workflow"
definition_suppression.register_definition_kind(WORKFLOW_KIND)

#: Name and phases of the workflow every organisation starts with (the five states stages had before
#: workflows were customisable).
STANDARD_WORKFLOW_NAME = "Standard"
STANDARD_PHASES: tuple[tuple[str, StagePhaseKind], ...] = (
    ("Scoping", StagePhaseKind.OPEN),
    ("Review", StagePhaseKind.REVIEW),
    ("Approved", StagePhaseKind.LOCKED),
    ("Completed", StagePhaseKind.CLOSED),
    ("Archived", StagePhaseKind.ON_HOLD),
)


class WorkflowConflict(ValueError):
    """A request that is valid in shape but not in the current state (HTTP 409)."""


@dataclass(frozen=True)
class PhaseInput:
    """One phase of a workflow being written; `id` is set for an existing phase."""

    name: str
    kind: StagePhaseKind
    id: uuid.UUID | None = None


def seed_stage_workflow(db: Session, organization_id: uuid.UUID) -> StageWorkflow:
    """Adds the organisation's "Standard" workflow (not committed; the caller owns the transaction)."""
    workflow = StageWorkflow(organization_id=organization_id, project_id=None, name=STANDARD_WORKFLOW_NAME, sort_order=0)
    db.add(workflow)
    db.flush()
    for i, (name, kind) in enumerate(STANDARD_PHASES):
        db.add(StageWorkflowPhase(workflow_id=workflow.id, name=name, kind=kind, sort_order=i))
    db.flush()
    return workflow


def phases_of(db: Session, workflow_id: uuid.UUID) -> list[StageWorkflowPhase]:
    """The workflow's phases in order (the first is the starting phase)."""
    return list(
        db.scalars(
            select(StageWorkflowPhase).where(StageWorkflowPhase.workflow_id == workflow_id).order_by(StageWorkflowPhase.sort_order)
        ).all()
    )


def phases_by_workflow(db: Session, workflow_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[StageWorkflowPhase]]:
    """Phases of several workflows in one query, each list in order."""
    result: dict[uuid.UUID, list[StageWorkflowPhase]] = {wid: [] for wid in workflow_ids}
    if not workflow_ids:
        return result
    for phase in db.scalars(
        select(StageWorkflowPhase).where(StageWorkflowPhase.workflow_id.in_(workflow_ids)).order_by(StageWorkflowPhase.sort_order)
    ):
        result[phase.workflow_id].append(phase)
    return result


def start_phase(db: Session, workflow_id: uuid.UUID) -> StageWorkflowPhase:
    """The workflow's starting phase (lowest `sort_order`).

    Raises:
        ValueError: If the workflow has no phases (it cannot be written that way).
    """
    phase = db.scalar(
        select(StageWorkflowPhase).where(StageWorkflowPhase.workflow_id == workflow_id).order_by(StageWorkflowPhase.sort_order).limit(1)
    )
    if phase is None:
        raise ValueError("The workflow has no phases.")
    return phase


def effective_workflows(db: Session, project: Project) -> list[StageWorkflow]:
    """The workflows a project may use: the organisation's (minus the ones it hid) first, then the
    project's own, or the nearest ancestor's when it has none."""
    org_rows = db.scalars(
        select(StageWorkflow)
        .where(StageWorkflow.organization_id == project.organization_id, StageWorkflow.project_id.is_(None))
        .order_by(StageWorkflow.sort_order, StageWorkflow.name)
    ).all()
    hidden = definition_suppression.get_suppressed_ids(db, project.id, WORKFLOW_KIND)
    result = [w for w in org_rows if w.id not in hidden]
    for pid in get_project_chain_ids(db, project.id):
        own = db.scalars(
            select(StageWorkflow).where(StageWorkflow.project_id == pid).order_by(StageWorkflow.sort_order, StageWorkflow.name)
        ).all()
        if own:
            result.extend(own)
            break
    return result


def default_workflow(db: Session, project: Project) -> StageWorkflow:
    """The workflow a new stage starts in: the first effective one. An organisation with none at all
    (its Standard workflow was removed and the project has no workflow of its own) gets Standard
    again, so a stage can always be created."""
    effective = effective_workflows(db, project)
    if effective:
        return effective[0]
    existing = db.scalar(
        select(StageWorkflow).where(
            StageWorkflow.organization_id == project.organization_id, StageWorkflow.project_id.is_(None)
        ).order_by(StageWorkflow.sort_order).limit(1)
    )
    return existing if existing is not None else seed_stage_workflow(db, project.organization_id)


def new_stage(db: Session, project: Project, name: str, sort_order: int, *, is_current: bool = False,
              workflow: StageWorkflow | None = None) -> ProjectStage:
    """Creates a stage at the start of `workflow` (default: the project's default workflow); flushed, not committed."""
    chosen = workflow or default_workflow(db, project)
    stage = ProjectStage(
        project_id=project.id, name=name, sort_order=sort_order, is_current=is_current,
        workflow_id=chosen.id, phase_id=start_phase(db, chosen.id).id,
    )
    db.add(stage)
    db.flush()
    return stage


def phase_index(db: Session, phase_ids: set[uuid.UUID]) -> dict[uuid.UUID, StageWorkflowPhase]:
    """The given phases by id, in one query."""
    if not phase_ids:
        return {}
    return {p.id: p for p in db.scalars(select(StageWorkflowPhase).where(StageWorkflowPhase.id.in_(phase_ids))).all()}


def phase_kind_of(db: Session, stage: ProjectStage) -> StagePhaseKind:
    """The kind of the stage's current phase."""
    kind = db.scalar(select(StageWorkflowPhase.kind).where(StageWorkflowPhase.id == stage.phase_id))
    if kind is None:
        raise ValueError("The stage's phase no longer exists.")
    return kind


def current_stage_kind(db: Session, project_id: uuid.UUID) -> StagePhaseKind | None:
    """The kind of the project's current stage's phase, or None when it has no current stage."""
    return db.scalar(
        select(StageWorkflowPhase.kind)
        .join(ProjectStage, ProjectStage.phase_id == StageWorkflowPhase.id)
        .where(ProjectStage.project_id == project_id, ProjectStage.is_current.is_(True))
    )


def workflow_in_use(db: Session, workflow_id: uuid.UUID) -> bool:
    """True when any stage follows the workflow."""
    return db.scalar(select(ProjectStage.id).where(ProjectStage.workflow_id == workflow_id).limit(1)) is not None


def _phase_in_use(db: Session, phase_id: uuid.UUID) -> bool:
    return db.scalar(select(ProjectStage.id).where(ProjectStage.phase_id == phase_id).limit(1)) is not None


def _clean_name(name: str, what: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError(f"A {what} needs a name.")
    if len(cleaned) > MAX_WORKFLOW_NAME_LENGTH:
        raise ValueError(f"A {what} name can have at most {MAX_WORKFLOW_NAME_LENGTH} characters.")
    return cleaned


def _validate_phases(phases: Sequence[PhaseInput]) -> list[PhaseInput]:
    if not phases:
        raise ValueError("A workflow needs at least one phase.")
    cleaned = [PhaseInput(name=_clean_name(p.name, "phase"), kind=p.kind, id=p.id) for p in phases]
    names = [p.name.casefold() for p in cleaned]
    if len(set(names)) != len(names):
        raise ValueError("Phase names must be unique within a workflow.")
    return cleaned


def write_workflow(
    db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str, phases: Sequence[PhaseInput],
    workflow: StageWorkflow | None = None, actor_id: uuid.UUID | None = None,
) -> StageWorkflow:
    """Creates a workflow, or replaces `workflow`'s name and phases, in one step (flushed, not committed).

    Phases are written in the order given. An existing phase is matched by `id`; one left out is
    deleted, which is refused while a stage is in it, and a phase in use cannot change kind.

    Raises:
        ValueError: A blank, over-long or duplicate name, or no phases.
        WorkflowConflict: The name is taken in this tier, or an edit would remove or re-kind a phase in use.
    """
    cleaned = _validate_phases(phases)
    clean_name = _clean_name(name, "workflow")
    scope = [StageWorkflow.organization_id == organization_id]
    scope.append(StageWorkflow.project_id.is_(None) if project_id is None else StageWorkflow.project_id == project_id)
    clash = select(StageWorkflow.id).where(*scope, func.lower(StageWorkflow.name) == clean_name.casefold())
    if workflow is not None:
        clash = clash.where(StageWorkflow.id != workflow.id)
    if db.scalar(clash) is not None:
        raise WorkflowConflict(f"A workflow named {clean_name!r} already exists here.")

    created = workflow is None
    if workflow is None:
        count = db.scalar(select(func.count(StageWorkflow.id)).where(*scope)) or 0
        workflow = StageWorkflow(organization_id=organization_id, project_id=project_id, name=clean_name, sort_order=count)
        db.add(workflow)
        db.flush()
    else:
        workflow.name = clean_name

    existing = {p.id: p for p in phases_of(db, workflow.id)}
    kept: set[uuid.UUID] = set()
    for p in cleaned:
        if p.id is not None and p.id not in existing:
            raise ValueError("A phase does not belong to this workflow.")
        if p.id is not None:
            if p.id in kept:
                raise ValueError("A phase appears twice.")
            kept.add(p.id)
    for phase_id, phase in existing.items():
        if phase_id not in kept and _phase_in_use(db, phase_id):
            raise WorkflowConflict(f"The phase {phase.name!r} is in use by a stage and cannot be removed.")
    for phase_id, phase in existing.items():
        if phase_id not in kept:
            db.delete(phase)
    db.flush()  # frees names before they are reused
    for i, p in enumerate(cleaned):
        if p.id is not None:
            row = existing[p.id]
            if row.kind != p.kind and _phase_in_use(db, row.id):
                raise WorkflowConflict(f"The phase {row.name!r} is in use by a stage, so its kind cannot change.")
            row.name = p.name
            row.kind = p.kind
            row.sort_order = i
        else:
            db.add(StageWorkflowPhase(workflow_id=workflow.id, name=p.name, kind=p.kind, sort_order=i))
    db.flush()
    log_event(
        db, entity_type="stage_workflow", entity_id=workflow.id, action="created" if created else "updated",
        actor_id=actor_id, project_id=project_id, organization_id=organization_id, detail={"name": clean_name},
    )
    return workflow


def delete_workflow(db: Session, workflow: StageWorkflow, actor_id: uuid.UUID | None = None) -> None:
    """Deletes a workflow and its phases.

    Raises:
        WorkflowConflict: A stage follows it, or it is a project's last usable workflow.
    """
    if workflow_in_use(db, workflow.id):
        raise WorkflowConflict("A stage follows this workflow, so it cannot be deleted.")
    if workflow.project_id is None:
        definition_suppression.forget_definition(db, WORKFLOW_KIND, workflow.id)
    log_event(
        db, entity_type="stage_workflow", entity_id=workflow.id, action="deleted", actor_id=actor_id,
        project_id=workflow.project_id, organization_id=workflow.organization_id, detail={"name": workflow.name},
    )
    db.delete(workflow)
    db.flush()


def first_phase_of_kind(phases: Sequence[StageWorkflowPhase], kind: StagePhaseKind, after_order: int = -1) -> StageWorkflowPhase | None:
    """The first phase of `kind` after position `after_order`, else the first of that kind anywhere."""
    matching = [p for p in phases if p.kind == kind]
    later = [p for p in matching if p.sort_order > after_order]
    chosen = later or matching
    return chosen[0] if chosen else None


def move_stage(
    db: Session, project: Project, stage: ProjectStage, phase: StageWorkflowPhase, actor: User, *,
    actor_roles: frozenset[ProjectRole] | set[ProjectRole], cascade_to_requirements: bool = False,
    reason: str | None = None,
) -> None:
    """Moves a stage to another phase of its own workflow and applies the new kind's behaviour.

    Entering a locked phase writes the baseline and records the approval; entering a closed phase records
    completion (and cascades to approved requirements if asked); leaving them clears the record. Entering or
    leaving a locked phase needs the project manager role. Flushed, not committed.

    Raises:
        ValueError: `phase` is not in the stage's workflow.
        PermissionError: A locked phase is entered or left without the project manager role.
        WorkflowConflict: `phase` is the current phase.
    """
    from app.services.baseline import create_baseline_for_stage  # deferred: baseline imports this module's callers
    from app.services.stages import complete_stage

    if phase.workflow_id != stage.workflow_id:
        raise ValueError("The phase is not part of the stage's workflow.")
    old_kind = phase_kind_of(db, stage)
    if (phase.kind == StagePhaseKind.LOCKED or old_kind == StagePhaseKind.LOCKED) and ProjectRole.PROJECT_MANAGER not in actor_roles:
        raise PermissionError("Only a project manager can move a stage into or out of a locked phase.")
    if phase.id == stage.phase_id:
        raise WorkflowConflict("The stage is already in this phase.")

    stage.phase_id = phase.id
    detail: dict[str, str | None] = {"phase": phase.name, "kind": phase.kind.value}
    if reason:
        detail["reason"] = reason
    if old_kind == StagePhaseKind.CLOSED and phase.kind != StagePhaseKind.CLOSED:
        stage.completed_at = None
        stage.completed_by = None
    if old_kind == StagePhaseKind.LOCKED and phase.kind != StagePhaseKind.LOCKED:
        stage.approved_at = None
        stage.approved_by = None
    if phase.kind == StagePhaseKind.LOCKED:
        stage.approved_at = datetime.now(UTC)
        stage.approved_by = actor.id
        create_baseline_for_stage(db, project, stage, actor)
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="approved", actor_id=actor.id,
                  project_id=project.id, detail=detail)
    elif phase.kind == StagePhaseKind.CLOSED:
        complete_stage(db, project, stage, actor, cascade_to_requirements=cascade_to_requirements)
    else:
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="status_changed", actor_id=actor.id,
                  project_id=project.id, detail=detail)
