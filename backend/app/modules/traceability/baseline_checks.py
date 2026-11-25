"""
Module: modules.traceability.baseline_checks

The two baseline checks governance provides, registered as `BaselineCheckProvider`s of the `baseline_policies` part:
required fields and required approvals. Other modules register their own checks through the same hook; whether a check
runs is the project's baseline policy (`baseline_policy`).

Responsibilities:
- `required_fields`: every record of a type the policy names fields for has each of them filled.
- `required_approvals`: a stage baseline can approve every requirement it holds that is still a draft, and a manual
  baseline holds only requirements that are already approved.

Design decisions:
- A field is one of the type's list columns (`RecordColumn`), read through the type's own record table with the person who
  triggers the baseline, so every type a baseline can hold is covered with no per-type code. A record the person cannot
  list is not part of what the baseline captures and is not judged. A failure names the field's label, never its value.
- A stage baseline is itself the approval act for a draft, so "required approvals" cannot demand approval before the baseline
  that grants it (the stage baseline of a requirement checks the approver instead): the person taking the baseline must be
  allowed to approve requirements, which a project manager or a holder of a role the project's approval policy names is, and
  the approval separation rule must let them approve each draft they created. The baseline refuses the first violation of
  the separation rule on its own; this check lists every one.
- Only the requirement has an approval gate and a snapshot provider at once, so it is the only type this check judges; a
  type that gains both needs its own entry here (`backend/tests/test_governance_baseline_checks.py` fails until it has).
- A check only reads and never commits.

Dependencies: `baseline_policy` (the fields to require), `modules.registry` (record tables), `services.approval_policy`
and `services.approval_separation` (who may approve), `models.requirement`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole, RequirementStatus
from app.models.project import Project
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.modules import registry
from app.modules.registry import RecordFilters
from app.modules.seams import BaselineCheckContext, BaselineCheckFailure
from app.modules.traceability import baseline_policy
from app.services import approval_policy, approval_separation
from app.services.rbac import get_effective_project_roles

REQUIRED_FIELDS_KEY = "required_fields"
REQUIRED_APPROVALS_KEY = "required_approvals"
#: Record types whose approval `required_approvals` judges.
APPROVAL_CHECKED_TYPES = ("requirement",)


def check_required_fields(
    db: Session, context: BaselineCheckContext, record_ids: dict[str, Sequence[uuid.UUID]],
) -> list[BaselineCheckFailure]:
    """`BaselineCheckProvider.check` for the required-fields check.

    Args:
        db: Active session (read only).
        context: The baseline being written; `actor_id` is the person whose view of each type's list is read.
        record_ids: The baseline's records by type.

    Returns:
        One failure per record and blank required field, in type and code order; empty when the policy names no field, when
        the baseline has no actor, or when every field is filled. A field the project's type has no column for is skipped.
    """
    wanted = baseline_policy.required_fields(db, context.project_id, context.kind)
    project = db.get(Project, context.project_id)
    actor = None if context.actor_id is None else db.get(User, context.actor_id)
    if not wanted or project is None or actor is None:
        return []
    providers = registry.get_record_table_providers()
    failures: list[BaselineCheckFailure] = []
    for artefact_type, keys in sorted(wanted.items()):
        provider = providers.get(artefact_type)
        ids = set(record_ids.get(artefact_type, ()))
        if provider is None or not ids:
            continue
        columns = {c.key: c for c in provider.columns(db, project)}
        chosen = [columns[k] for k in keys if k in columns]
        if not chosen:
            continue
        records = [r for r in provider.list_records(db, actor, project.id, RecordFilters()) if provider.id_of(r) in ids]
        prepared = provider.prepare(db, project, records) if provider.prepare is not None else None
        for record in sorted(records, key=provider.code_of):
            for column in chosen:
                if not column.get(prepared, record).strip():
                    failures.append(BaselineCheckFailure(
                        artefact_type=artefact_type, artefact_id=provider.id_of(record), check_key=REQUIRED_FIELDS_KEY,
                        message=f"The field {column.label} is required and is blank.", code=provider.code_of(record),
                    ))
    return failures


def check_required_approvals(
    db: Session, context: BaselineCheckContext, record_ids: dict[str, Sequence[uuid.UUID]],
) -> list[BaselineCheckFailure]:
    """`BaselineCheckProvider.check` for the required-approvals check.

    Args:
        db: Active session (read only).
        context: The baseline being written.
        record_ids: The baseline's records by type; only requirements are judged.

    Returns:
        For a stage baseline, one failure per draft or reviewed requirement the person taking the baseline may not approve (a
        person who may not approve requirements at all, or one the separation rule bars from approving what they created);
        for a manual baseline, one failure per requirement that is not approved. Empty when all pass.
    """
    ids = list(record_ids.get("requirement", ()))
    project = db.get(Project, context.project_id)
    if not ids or project is None:
        return []
    rows = db.execute(
        select(Requirement.id, Requirement.unique_code, Requirement.creator_id, RequirementVersion.status)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(Requirement.id.in_(ids), RequirementVersion.valid_to.is_(None))
        .order_by(Requirement.unique_code)
    ).tuples().all()

    def failure(requirement_id: uuid.UUID, code: str, message: str) -> BaselineCheckFailure:
        return BaselineCheckFailure(
            artefact_type="requirement", artefact_id=requirement_id, check_key=REQUIRED_APPROVALS_KEY, message=message, code=code,
        )

    if context.kind == "manual":
        return [
            failure(i, code, f"The requirement is not approved (status {status.value.replace('_', ' ')}).")
            for i, code, _, status in rows if status != RequirementStatus.APPROVED
        ]
    pending = [(i, code, creator) for i, code, creator, status in rows if status in (RequirementStatus.DRAFT, RequirementStatus.REVIEWED)]
    if not pending:
        return []
    actor = None if context.actor_id is None else db.get(User, context.actor_id)
    may = actor is not None and approval_policy.may_approve(
        db, actor, artefact_type="requirement", organization_id=project.organization_id, project_id=project.id,
        default=ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, actor.id, project.id),
    )
    if not may:
        return [failure(i, code, "The person taking the baseline may not approve requirements.") for i, code, _ in pending]
    separation = approval_separation.resolve_separation(
        db, artefact_type="requirement", organization_id=project.organization_id, project_id=project.id,
    )
    if not separation.separate or actor is None:
        return []
    return [
        failure(i, code, "A separate approver is required and the person taking the baseline created the requirement.")
        for i, code, creator in pending if creator == actor.id
    ]
