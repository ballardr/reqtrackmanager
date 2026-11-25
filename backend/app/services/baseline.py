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

Before anything is approved or captured, the checks the project's baseline policy enables run over the records the
baseline would hold (`check_baseline`). One failing check refuses the whole baseline with every failure listed
(`BaselineRefused`); nothing is approved, locked or stored. The checks are the `BaselineCheckProvider`s modules register,
chosen by the `GovernanceSeam.BASELINE` policy; with none enabled the baseline is written exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
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
    BaselineSnapshotRecord,
    get_baseline_snapshot_providers,
    is_module_enabled_for_project,
)
from app.modules.seams import BaselineCheckContext, BaselineCheckProvider, BaselinePolicy, GovernanceSeam
from app.services import approval_separation, governance_seams
from app.services.component_stages import tracked_component_ids
from app.services.rbac import can_manage_project_settings, get_effective_permissions, permission_satisfied
from app.services.requirements import apply_new_version, get_current_version_for_update

REQUIREMENT_ITEM_TYPE = "requirement"

BaselineKindName = Literal["stage", "manual"]


@dataclass(frozen=True)
class BaselineFailure:
    """One reason a baseline is refused, with the check that found it.

    Attributes:
        check_key: The namespaced check key (`<module key>:<check key>`).
        check_name: The check's display name.
        artefact_type: The failing record's registered type.
        artefact_id: The failing record's id.
        code: The record's own code, empty when it has none.
        message: Formal sentence naming what is missing.
    """

    check_key: str
    check_name: str
    artefact_type: str
    artefact_id: UUID
    code: str
    message: str


class BaselineRefused(Exception):
    """A check of the project's baseline policy failed, so no baseline was written and nothing was approved.

    Attributes:
        failures: Every failure of every enabled check, ordered by check, type and code.
    """

    def __init__(self, failures: Sequence[BaselineFailure]) -> None:
        super().__init__(refusal_message(failures))
        self.failures = list(failures)


def refusal_message(failures: Sequence[BaselineFailure]) -> str:
    """The sentence that opens a refusal: how many records fail how many checks."""
    records = len({(f.artefact_type, f.artefact_id) for f in failures})
    checks = len({f.check_key for f in failures})
    return (
        f"The baseline was refused: {records} record{'s' if records != 1 else ''} failed "
        f"{checks} baseline check{'s' if checks != 1 else ''}. Nothing was approved or stored."
    )


def refusal_detail(refused: BaselineRefused) -> dict[str, object]:
    """The structured body of the 409 response to a refused baseline: the opening sentence and every failure."""
    return {
        "message": str(refused),
        "failures": [
            {
                "check_key": f.check_key, "check_name": f.check_name, "artefact_type": f.artefact_type,
                "artefact_id": str(f.artefact_id), "code": f.code, "message": f.message,
            }
            for f in refused.failures
        ],
    }


def active_checks(db: Session, project: Project, kind: BaselineKindName) -> list[tuple[str, BaselineCheckProvider]]:
    """The checks that run before a baseline of `kind` in the project.

    Args:
        db: An active database session.
        project: The project being baselined.
        kind: `stage` or `manual`.

    Returns:
        `(namespaced key, provider)` for each check the project's baseline policy enables for `kind` whose provider is in
        effect, in registry order; empty when no policy applies, so no check runs by default.
    """
    policy = governance_seams.resolve_project_policy(db, project.id, GovernanceSeam.BASELINE)
    if not isinstance(policy, BaselinePolicy):
        return []
    wanted = set(policy.checks_for(kind))
    return [(key, provider) for key, provider in governance_seams.baseline_checks_for_project(db, project.id) if key in wanted]


def check_baseline(
    db: Session, project: Project, kind: BaselineKindName, actor_id: UUID | None, records: Mapping[str, Sequence[UUID]],
    *, checks: Sequence[tuple[str, BaselineCheckProvider]] | None = None,
) -> list[BaselineFailure]:
    """Runs the enabled checks over the records a baseline would hold.

    Args:
        db: An active database session (read only here).
        project: The project being baselined.
        kind: `stage` or `manual`.
        actor_id: The person who triggers the baseline.
        records: The ids the baseline would hold, by registered artefact type.
        checks: The checks to run; `active_checks` when omitted.

    Returns:
        Every failure of every check, ordered by check key, type and code; empty when all pass or none is enabled. A check
        whose types the baseline holds none of is not run.
    """
    chosen = active_checks(db, project, kind) if checks is None else checks
    context = BaselineCheckContext(project_id=project.id, kind=kind, actor_id=actor_id)
    failures: list[BaselineFailure] = []
    for key, provider in chosen:
        wanted = provider.artefact_types or tuple(records)
        inputs = {t: records[t] for t in wanted if records.get(t)}
        if not inputs:
            continue
        failures.extend(
            BaselineFailure(key, provider.name, f.artefact_type, f.artefact_id, f.code, f.message)
            for f in provider.check(db, context, inputs)
        )
    return sorted(failures, key=lambda f: (f.check_key, f.artefact_type, f.code, str(f.artefact_id)))


def _stage_scope(db: Session, project: Project, stage: ProjectStage, component_id: UUID | None) -> tuple[str, list[Requirement]]:
    """The label and the requirements a stage baseline covers (the baseline's own scope rule, shared by `preview_checks`)."""
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
    return label, list(db.scalars(query).all())


def _capture_module_records(
    db: Session, project: Project, context: BaselineSnapshotContext, providers: dict[str, BaselineSnapshotProvider],
) -> dict[str, list[BaselineSnapshotRecord]]:
    """What each provider captures now, so the checks and the baseline read the same records."""
    return {artefact_type: provider.snapshot(db, project, context) for artefact_type, provider in providers.items()}


def _record_ids(
    requirement_ids: Sequence[UUID], captured: Mapping[str, Sequence[BaselineSnapshotRecord]],
) -> dict[str, list[UUID]]:
    """The ids a baseline would hold, by type, for the checks."""
    ids: dict[str, list[UUID]] = {REQUIREMENT_ITEM_TYPE: list(requirement_ids)}
    ids.update({t: [r.item_id for r in records] for t, records in captured.items()})
    return ids


def preview_checks(
    db: Session, project: Project, actor: User, kind: BaselineKindName, *, stage_id: UUID | None = None,
    component_id: UUID | None = None,
) -> tuple[list[tuple[str, BaselineCheckProvider]], list[BaselineFailure]]:
    """Runs the enabled checks against what a baseline would hold now, writing nothing.

    Args:
        db: An active database session (read only).
        project: The project.
        actor: The person who would trigger the baseline; the checks that depend on who acts read it.
        kind: `stage` (needs `stage_id`) or `manual` (every type `actor` may snapshot).
        stage_id: The stage whose baseline is previewed.
        component_id: A component's own baseline of the stage.

    Returns:
        The checks that apply and their failures; the same list `create_baseline_for_stage` or `create_manual_baseline`
        would refuse with.

    Raises:
        ValueError: A `stage` preview names no stage of the project.
    """
    checks = active_checks(db, project, kind)
    if not checks:
        return [], []
    if kind == "stage":
        stage = db.get(ProjectStage, stage_id) if stage_id is not None else None
        if stage is None or stage.project_id != project.id:
            raise ValueError("A stage of the project is required.")
        _, requirements = _stage_scope(db, project, stage, component_id)
        context = BaselineSnapshotContext(kind="stage", stage_id=stage.id, component_id=component_id, actor_id=actor.id)
        providers = enabled_snapshot_providers(db, project)
        requirement_ids = [r.id for r in requirements]
    else:
        types = manual_baseline_types(db, project, actor)
        context = BaselineSnapshotContext(kind="manual", stage_id=None, component_id=None, actor_id=actor.id)
        providers = {t: p for t, p in enabled_snapshot_providers(db, project).items() if t in types}
        requirement_ids = _manual_requirement_rows(db, project)[0] if REQUIREMENT_ITEM_TYPE in types else []
    captured = _capture_module_records(db, project, context, providers)
    return checks, check_baseline(db, project, kind, actor.id, _record_ids(requirement_ids, captured), checks=checks)


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
    label, requirements = _stage_scope(db, project, stage, component_id)
    context = BaselineSnapshotContext(
        kind=BaselineKind.STAGE.value, stage_id=stage.id, component_id=component_id, actor_id=actor.id
    )
    providers = enabled_snapshot_providers(db, project)
    captured: dict[str, list[BaselineSnapshotRecord]] | None = None
    checks = active_checks(db, project, "stage")
    if checks:
        captured = _capture_module_records(db, project, context, providers)
        failures = check_baseline(
            db, project, "stage", actor.id, _record_ids([r.id for r in requirements], captured), checks=checks,
        )
        if failures:
            raise BaselineRefused(failures)
    baseline = Baseline(
        project_id=project.id, kind=BaselineKind.STAGE, stage_id=stage.id, component_id=component_id, label=label,
        created_by=actor.id,
    )
    db.add(baseline)
    db.flush()

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
            approval_separation.enforce_approval(
                db, user=actor, artefact_type="requirement", record_id=requirement.id,
                creator_id=requirement.creator_id, organization_id=project.organization_id, project_id=project.id,
                comment=label,
            )
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
    add_module_items(db, baseline, project, context, providers, captured)
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
    captured: Mapping[str, Sequence[BaselineSnapshotRecord]] | None = None,
) -> dict[str, int]:
    """Runs the given providers and stores what they capture as items of the baseline.

    Args:
        db: An active database session (rows are added and flushed, never committed).
        baseline: The baseline being written (already flushed, so it has an id).
        project: The project being baselined.
        context: What is being baselined and for whom.
        providers: `{artefact type: provider}`, from `enabled_snapshot_providers`.
        captured: What the providers already captured for the checks (`_capture_module_records`), stored as it is so the
            checks and the baseline hold the same records; `None` captures now.

    Returns:
        The number of items stored per artefact type.
    """
    counts: dict[str, int] = {}
    for artefact_type, provider in providers.items():
        records = captured[artefact_type] if captured is not None else provider.snapshot(db, project, context)
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


def _manual_requirement_rows(db: Session, project: Project) -> tuple[list[UUID], list[tuple[UUID, UUID]]]:
    """The requirement ids and `(requirement id, current version id)` pairs a manual baseline of requirements holds."""
    rows = [
        (requirement_id, version_id)
        for requirement_id, version_id in db.execute(
            select(Requirement.id, RequirementVersion.id)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(
                Requirement.project_id == project.id, Requirement.is_archived.is_(False),
                RequirementVersion.valid_to.is_(None),
            )
            .order_by(Requirement.id)
        ).tuples()
    ]
    return [requirement_id for requirement_id, _ in rows], rows


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
    context = BaselineSnapshotContext(kind=BaselineKind.MANUAL.value, stage_id=None, component_id=None, actor_id=actor.id)
    providers = {t: p for t, p in enabled_snapshot_providers(db, project).items() if t in item_types}
    requirement_ids, rows = _manual_requirement_rows(db, project) if REQUIREMENT_ITEM_TYPE in item_types else ([], [])
    captured: dict[str, list[BaselineSnapshotRecord]] | None = None
    checks = active_checks(db, project, "manual")
    if checks:
        captured = _capture_module_records(db, project, context, providers)
        failures = check_baseline(db, project, "manual", actor.id, _record_ids(requirement_ids, captured), checks=checks)
        if failures:
            raise BaselineRefused(failures)
    baseline = Baseline(project_id=project.id, kind=BaselineKind.MANUAL, label=label, created_by=actor.id)
    db.add(baseline)
    db.flush()
    counts: dict[str, int] = {}
    if REQUIREMENT_ITEM_TYPE in item_types:
        for requirement_id, version_id in rows:
            db.add(BaselineItem(
                baseline_id=baseline.id, item_type=REQUIREMENT_ITEM_TYPE, item_id=requirement_id,
                requirement_id=requirement_id, requirement_version_id=version_id,
            ))
        counts[REQUIREMENT_ITEM_TYPE] = len(rows)
    counts.update(add_module_items(db, baseline, project, context, providers, captured))
    db.flush()
    return baseline, counts
