"""
Module: services.stage_workflow_bundle

Project and organisation bundle sections for stage workflows.

Responsibilities:
- Export a tier's workflows (name and ordered phases with kinds), a project's hidden organisation
  workflows (by name), and each stage's workflow and phase (by name).
- Import them again, resolving by name, never by id.

Design decisions:
- An imported stage in a locked or closed phase starts at its workflow's first phase instead, with
  a warning: entering those phases writes a baseline and records an approval, which an import
  must not do on someone's behalf (an imported approval state never bypasses the approval gate).
- The organisation import adds the bundle's workflows and then seeds Standard only if the
  organisation still has none, so a customised Standard is not replaced by the default.
- A merge into an existing organisation adds workflows missing by name and leaves existing ones alone.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import StagePhaseKind
from app.models.project import Project, ProjectStage
from app.models.stage_workflow import StageWorkflow, StageWorkflowPhase
from app.services import definition_suppression
from app.services.bundle_common import BundleImportWarnings
from app.services.stage_workflows import (
    WORKFLOW_KIND,
    PhaseInput,
    WorkflowConflict,
    effective_workflows,
    phases_by_workflow,
    seed_stage_workflow,
    start_phase,
    write_workflow,
)

ORG_KEY = "stage_workflows"
PROJECT_KEY = "stage_workflows"
HIDDEN_KEY = "hidden_stage_workflows"
#: Kinds an import never lands a stage in (see the module docstring).
_NOT_IMPORTED_KINDS = frozenset({StagePhaseKind.LOCKED, StagePhaseKind.CLOSED})


def _tier(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list[StageWorkflow]:
    where = StageWorkflow.project_id.is_(None) if project_id is None else StageWorkflow.project_id == project_id
    return list(
        db.scalars(
            select(StageWorkflow).where(StageWorkflow.organization_id == organization_id, where).order_by(StageWorkflow.sort_order)
        ).all()
    )


def export_workflows(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """One tier's workflows as `{name, phases: [{name, kind}]}` in order."""
    workflows = _tier(db, organization_id, project_id)
    phases = phases_by_workflow(db, [w.id for w in workflows])
    return [
        {"name": w.name, "phases": [{"name": p.name, "kind": p.kind.value} for p in phases[w.id]]} for w in workflows
    ]


def export_org_stage_workflows(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The organisation's workflows as an `org.json` section."""
    return {ORG_KEY: export_workflows(db, organization_id, None)}


def export_project_stage_workflows(db: Session, project: Project) -> dict[str, Any]:
    """A project's own workflows and the organisation workflows it hid, as `project.json` sections."""
    hidden = definition_suppression.get_suppressed_ids(db, project.id, WORKFLOW_KIND)
    hidden_names = sorted(
        name for name in db.scalars(select(StageWorkflow.name).where(StageWorkflow.id.in_(hidden))).all()
    ) if hidden else []
    return {PROJECT_KEY: export_workflows(db, project.organization_id, project.id), HIDDEN_KEY: hidden_names}


def export_stage_phases(db: Session, stages: list[ProjectStage]) -> dict[uuid.UUID, dict[str, str]]:
    """Each stage's `{workflow, phase}` names, in two queries."""
    if not stages:
        return {}
    workflows = {w.id: w for w in db.scalars(select(StageWorkflow).where(StageWorkflow.id.in_({s.workflow_id for s in stages}))).all()}
    phases = {p.id: p for p in db.scalars(select(StageWorkflowPhase).where(StageWorkflowPhase.id.in_({s.phase_id for s in stages}))).all()}
    return {
        s.id: {
            "workflow": workflows[s.workflow_id].name,
            "workflow_scope": "project" if workflows[s.workflow_id].project_id else "organisation",
            "phase": phases[s.phase_id].name,
        }
        for s in stages
    }


def import_workflows(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, entries: Any, warnings: BundleImportWarnings,
) -> None:
    """Adds the bundle's workflows to a tier, skipping a name the tier already has and any malformed entry."""
    existing = {w.name.casefold() for w in _tier(db, organization_id, project_id)}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or entry["name"].casefold() in existing:
            continue
        try:
            phases = [PhaseInput(name=str(p["name"]), kind=StagePhaseKind(p["kind"])) for p in entry.get("phases") or []]
            write_workflow(db, organization_id=organization_id, project_id=project_id, name=entry["name"], phases=phases)
        except (ValueError, KeyError, TypeError, WorkflowConflict) as exc:
            warnings.add(f"Stage workflow {entry['name']!r} was not imported: {exc}")
            continue
        existing.add(entry["name"].casefold())


def import_org_stage_workflows(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], warnings: BundleImportWarnings, *, seed_if_empty: bool,
) -> None:
    """Imports an organisation's workflows; with `seed_if_empty`, adds Standard when it still has none."""
    import_workflows(db, organization_id, None, data.get(ORG_KEY), warnings)
    if seed_if_empty and not _tier(db, organization_id, None):
        seed_stage_workflow(db, organization_id)


def import_project_stage_workflows(db: Session, project: Project, data: dict[str, Any], warnings: BundleImportWarnings) -> None:
    """Imports a project's own workflows and re-hides the organisation workflows it had hidden (by name)."""
    import_workflows(db, project.organization_id, project.id, data.get(PROJECT_KEY), warnings)
    names = {n.casefold() for n in data.get(HIDDEN_KEY) or [] if isinstance(n, str)}
    if not names:
        return
    for workflow in _tier(db, project.organization_id, None):
        if workflow.name.casefold() in names:
            definition_suppression.hide_definition(db, project.id, WORKFLOW_KIND, workflow.id)


def import_stage(
    db: Session, project: Project, name: str, sort_order: int, is_current: bool, entry: dict[str, Any],
    warnings: BundleImportWarnings,
) -> ProjectStage:
    """Creates an imported stage in the workflow and phase the bundle names, else the default workflow's start.

    A workflow the bundle names that this project cannot use, or a phase that is gone, falls back to the
    default workflow's (or the workflow's) starting phase; a locked or closed phase is never entered (see
    the module docstring). Each fallback is reported as a warning.
    """
    from app.services.stage_workflows import default_workflow, new_stage

    workflow = None
    wanted = entry.get("workflow")
    if isinstance(wanted, str):
        workflow = next((w for w in effective_workflows(db, project) if w.name.casefold() == wanted.casefold()), None)
        if workflow is None:
            warnings.add(f"Stage {name!r}: workflow {wanted!r} is not available here; the default workflow was used.")
    workflow = workflow or default_workflow(db, project)
    stage = new_stage(db, project, name, sort_order, is_current=is_current, workflow=workflow)
    wanted_phase = entry.get("phase")
    if isinstance(wanted_phase, str):
        phases = phases_by_workflow(db, [workflow.id])[workflow.id]
        phase = next((p for p in phases if p.name.casefold() == wanted_phase.casefold()), None)
        if phase is None:
            warnings.add(f"Stage {name!r}: phase {wanted_phase!r} does not exist; the starting phase was used.")
        elif phase.kind in _NOT_IMPORTED_KINDS:
            warnings.add(
                f"Stage {name!r} was in the {phase.kind.value} phase {phase.name!r}; it starts in "
                f"{start_phase(db, workflow.id).name!r} so the approval is made again here."
            )
        else:
            stage.phase_id = phase.id
    return stage
