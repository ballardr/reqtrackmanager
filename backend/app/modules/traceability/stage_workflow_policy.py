"""
Module: modules.traceability.stage_workflow_policy

The stage workflow policy of governance profiles: the organisation workflow a profile requires of the projects it applies
to, and whether it only makes that workflow the one new stages start in or also limits the project to it. Registered with
the `lifecycle_policies` part as a policy resolver (`GovernanceSeam.STAGE_WORKFLOW`) and a profile contributor.

Responsibilities:
- Write and clear a profile's requirement (`set_requirement`, `clear_requirement`), validating the workflow and the mode and
  recording one audit event each (the workflow id and the mode, never a name).
- Read it for the organisation's profile screens (`profile_policy`).
- Answer the core seam for one project (`resolve_project_policy`): the workflow new stages start in, the workflows that are
  required and by which profiles, and the profiles that restrict the project to them.
- Say which profiles require an organisation workflow (`references`), so the workflow cannot be deleted while one does.
- Count, export and import a profile's row for the profile list and the organisation bundle (`count_rows`, `export_rows`,
  `import_rows`).

Design decisions:
- Which profiles apply to a project (Enforced, Default not opted out, opted-in; exempt projects skipped) is decided by
  `profile_resolution`; this file only reads the rows of those profiles.
- Merge rule: the workflow of the first profile in precedence order (Enforced, then Default, then opted-in; by name within
  a tier) is the default for new stages; every workflow any profile names is required (available and not hideable); a
  project is restricted when any one profile restricts it, and then to the union of the workflows the profiles name, so the
  default is always one it may use. A profile therefore only adds to what binds a project.
- A profile requires an organisation workflow only: a project's own workflow belongs to one project. Existing stages are
  never moved by a policy; it changes which workflow a stage can be created in or changed to.
- The nested-project fallback of workflows is untouched: a restriction leaves a project only the required organisation
  workflows, so its own and its ancestor's workflows are not offered while it is restricted.
- A workflow is exported by name, as the organisation bundle carries workflows by name; an import that cannot find the name
  reports it and skips the row.

Dependencies: `profile_resolution`, `models.stage_workflow`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.stage_workflow import StageWorkflow
from app.modules.seams import StageWorkflowPolicy
from app.modules.traceability.enums import StageWorkflowMode
from app.modules.traceability.models import GovernanceProfile, GovernanceStageWorkflowPolicy
from app.modules.traceability.profile_resolution import applicable_profiles
from app.services.audit import log_event

AUDIT_ENTITY_TYPE = "governance_profile"
KIND_STAGE_WORKFLOW = "stage_workflow"


@dataclass(frozen=True)
class WorkflowOption:
    """An organisation workflow a profile may require.

    Attributes:
        id: The workflow.
        name: Its name.
    """

    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class ProfileWorkflowPolicy:
    """A profile's stage workflow policy as the organisation sees it.

    Attributes:
        workflow_id: The workflow the profile requires, `None` for none.
        workflow_name: Its name.
        mode: How it binds (`default` when none is set).
        options: The organisation's workflows, to choose from, in display order.
    """

    workflow_id: uuid.UUID | None
    workflow_name: str | None
    mode: StageWorkflowMode
    options: list[WorkflowOption]


def organization_workflows(db: Session, organization_id: uuid.UUID) -> list[StageWorkflow]:
    """The organisation's own workflows (not a project's) in display order."""
    return list(db.scalars(
        select(StageWorkflow)
        .where(StageWorkflow.organization_id == organization_id, StageWorkflow.project_id.is_(None))
        .order_by(StageWorkflow.sort_order, StageWorkflow.name)
    ))


def _row(db: Session, profile_id: uuid.UUID) -> GovernanceStageWorkflowPolicy | None:
    return db.scalar(select(GovernanceStageWorkflowPolicy).where(GovernanceStageWorkflowPolicy.profile_id == profile_id))


def profile_policy(db: Session, profile: GovernanceProfile) -> ProfileWorkflowPolicy:
    """The profile's requirement and the workflows it can choose from.

    Args:
        db: Active session (read only).
        profile: The profile.

    Returns:
        The required workflow and mode, and the organisation's workflows.
    """
    workflows = organization_workflows(db, profile.organization_id)
    row = _row(db, profile.id)
    names = {w.id: w.name for w in workflows}
    return ProfileWorkflowPolicy(
        workflow_id=None if row is None else row.workflow_id,
        workflow_name=None if row is None else names.get(row.workflow_id),
        mode=StageWorkflowMode.DEFAULT if row is None else StageWorkflowMode(row.mode),
        options=[WorkflowOption(w.id, w.name) for w in workflows],
    )


def set_requirement(
    db: Session, *, profile: GovernanceProfile, workflow_id: uuid.UUID, mode: StageWorkflowMode, actor_id: uuid.UUID,
) -> None:
    """Makes the profile require an organisation workflow.

    Args:
        db: Active session (not committed).
        profile: The profile.
        workflow_id: One of the profile's organisation's own workflows.
        mode: `default` or `restrict`.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 when the workflow is not one of the organisation's.
    """
    workflow = db.get(StageWorkflow, workflow_id)
    if workflow is None or workflow.organization_id != profile.organization_id or workflow.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    _write(db, profile.id, workflow.id, mode)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="stage_workflow_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail={"workflow_id": str(workflow.id), "mode": mode.value},
    )


def clear_requirement(db: Session, *, profile: GovernanceProfile, actor_id: uuid.UUID) -> None:
    """Removes the profile's workflow requirement (audited, not committed)."""
    row = _row(db, profile.id)
    if row is None:
        return
    db.delete(row)
    db.flush()
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="stage_workflow_cleared", actor_id=actor_id,
        organization_id=profile.organization_id, detail={},
    )


def _write(db: Session, profile_id: uuid.UUID, workflow_id: uuid.UUID, mode: StageWorkflowMode) -> None:
    """Makes the profile's row hold exactly the workflow and mode (flushed, not audited)."""
    row = _row(db, profile_id)
    if row is None:
        db.add(GovernanceStageWorkflowPolicy(profile_id=profile_id, workflow_id=workflow_id, mode=mode.value))
    else:
        row.workflow_id = workflow_id
        row.mode = mode.value
    db.flush()


# --- the seam ------------------------------------------------------------------------------------


def resolve_project_policy(db: Session, project_id: uuid.UUID) -> StageWorkflowPolicy | None:
    """`PolicyResolver.resolve_project` for `GovernanceSeam.STAGE_WORKFLOW`: what the profiles that apply to the project ask
    of its stage workflows.

    Args:
        db: Active session (read only).
        project_id: The project.

    Returns:
        The default workflow, the required workflows with the names of the profiles requiring each, and the profiles that
        restrict the project; `None` when no applicable profile requires a workflow.
    """
    applied = applicable_profiles(db, project_id)
    if not applied:
        return None
    position = {a.profile_id: i for i, a in enumerate(applied)}
    names = {a.profile_id: a.name for a in applied}
    rows = sorted(
        db.scalars(select(GovernanceStageWorkflowPolicy).where(GovernanceStageWorkflowPolicy.profile_id.in_(position))),
        key=lambda r: position[r.profile_id],
    )
    if not rows:
        return None
    required: dict[uuid.UUID, list[str]] = {}
    for row in rows:
        required.setdefault(row.workflow_id, []).append(names[row.profile_id])
    return StageWorkflowPolicy(
        default_workflow_id=rows[0].workflow_id,
        required={workflow_id: tuple(profile_names) for workflow_id, profile_names in required.items()},
        restricted_by=tuple(names[r.profile_id] for r in rows if r.mode == StageWorkflowMode.RESTRICT.value),
    )


def references(db: Session, workflow_id: uuid.UUID) -> list[str]:
    """`ModuleDefinition.stage_workflow_references`: the names of the governance profiles that require the workflow."""
    return list(db.scalars(
        select(GovernanceProfile.name)
        .join(GovernanceStageWorkflowPolicy, GovernanceStageWorkflowPolicy.profile_id == GovernanceProfile.id)
        .where(GovernanceStageWorkflowPolicy.workflow_id == workflow_id)
        .order_by(GovernanceProfile.name)
    ))


# --- the profile contributor ---------------------------------------------------------------------


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: one for each profile that requires a workflow."""
    return {
        profile_id: count
        for profile_id, count in db.execute(
            select(GovernanceStageWorkflowPolicy.profile_id, func.count())
            .where(GovernanceStageWorkflowPolicy.profile_id.in_(profile_ids))
            .group_by(GovernanceStageWorkflowPolicy.profile_id)
        ).tuples()
    }


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one `stage_workflow` entry naming the workflow and the mode, when the profile
    requires one."""
    row = _row(db, profile_id)
    workflow = None if row is None else db.get(StageWorkflow, row.workflow_id)
    if row is None or workflow is None:
        return []
    return [{"kind": KIND_STAGE_WORKFLOW, "workflow": workflow.name, "mode": row.mode}]


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes the bundle's `stage_workflow` entry into the profile. A workflow that is not
    in the organisation, a mode that is not offered and an unknown entry are reported through `warn` and skipped."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return
    for entry in rows:
        if entry.get("kind") != KIND_STAGE_WORKFLOW:
            warn("A stage workflow policy entry of an unknown kind was not imported.")
            continue
        name = str(entry.get("workflow", ""))
        workflow = next((w for w in organization_workflows(db, profile.organization_id) if w.name == name), None)
        if workflow is None:
            warn(f"The required stage workflow {name or 'with no name'} was not imported: the organisation has no such workflow.")
            continue
        try:
            mode = StageWorkflowMode(str(entry.get("mode", StageWorkflowMode.DEFAULT.value)))
        except ValueError:
            warn(f"The mode of the required stage workflow {name} is not offered and was set to the default.")
            mode = StageWorkflowMode.DEFAULT
        _write(db, profile_id, workflow.id, mode)
