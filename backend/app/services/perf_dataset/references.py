"""
Module: perf_dataset.references

External references for generated records: a few per record in the organisation's systems, written the way the
application writes them (a project's own pass-through row of each organisation system, `reference_added` audit
events), so the list column, the filter, the export and the bundle read them at realistic volume.

Responsibilities:
- `write_references`: references for one batch of records of any type (`RecordBatch` types and requirements).
- Nothing for a profile whose `references_per_record` is 0, or an organisation with no active system.

Design decisions: the keys are `<prefix>-<number>` drawn from a small range, so the key filter and the look-up find
several records, as a real tracker's keys do; the pass-through rows are written once per project.

Dependencies: SQLAlchemy models, `perf_dataset.context`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.external_reference import (
    ExternalReference,
    ExternalReferenceRole,
    ExternalSystemDefinition,
    ProjectExternalSystem,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.context import poisson as _poisson

if TYPE_CHECKING:
    from app.services.perf_dataset.core import AuditBuffer

#: The key prefixes a generated reference uses, by position in the organisation's system list.
_KEY_PREFIXES = ("PROJ", "REQ", "INC", "WI", "ISSUE", "TASK")


def _project_systems(ctx: PerfProjectContext) -> list[tuple[uuid.UUID, str]]:
    """`(the project's pass-through row id, system name)` for each active system of the organisation, creating the
    rows on first use (cached on the context's organisation state)."""
    cache = ctx.org_state.setdefault("_reference_systems", {})
    if ctx.project.id in cache:
        return cache[ctx.project.id]
    org_systems = list(ctx.db.execute(
        select(ExternalSystemDefinition.id, ExternalSystemDefinition.name)
        .where(ExternalSystemDefinition.organization_id == ctx.organization_uuid, ExternalSystemDefinition.is_active.is_(True))
        .order_by(ExternalSystemDefinition.sort_order, ExternalSystemDefinition.name)
    ).tuples())
    rows = [
        {"id": uuid_from(ctx.rng), "project_id": ctx.project_uuid, "org_type_id": system_id, "is_enabled": True}
        for system_id, _name in org_systems
    ]
    ctx.add_count("project_external_systems", insert_rows(ctx.db, ProjectExternalSystem, rows))
    cache[ctx.project.id] = [(row["id"], name) for row, (_id, name) in zip(rows, org_systems, strict=True)]
    return cache[ctx.project.id]


def write_references(
    ctx: PerfProjectContext, artefact_type: str, ids: list[uuid.UUID], created: list[datetime], audit: AuditBuffer,
) -> None:
    """Gives records external references (`ratios.references_per_record` on average) with the audit events the
    application writes.

    Args:
        ctx: The project's context.
        artefact_type: The records' registered type.
        ids: The record ids.
        created: Each record's creation instant, parallel to `ids`.
        audit: The batch's audit buffer (flushed here).
    """
    rng = ctx.rng
    mean = ctx.spec.ratios.references_per_record
    if mean <= 0 or not ids:
        return
    systems = _project_systems(ctx)
    if not systems:
        return
    rows = []
    for index, record_id in enumerate(ids):
        for _ in range(min(_poisson(rng, mean), len(systems))):
            at = created[index] + timedelta(hours=2)
            position = rng.randrange(len(systems))
            system_id, _name = systems[position]
            row_id = uuid_from(rng)
            key = f"{_KEY_PREFIXES[position % len(_KEY_PREFIXES)]}-{rng.randint(1, 400)}"
            # About a third carry an explicit link, a fifth a note and a third a role, as people use them.
            role = rng.choice((ExternalReferenceRole.ORIGIN, ExternalReferenceRole.DELIVERY)) if rng.random() < 0.33 else None
            url = f"https://tracker.example/browse/{key}" if rng.random() < 0.33 else None
            note = textgen.sentences(rng, 1) if rng.random() < 0.2 else ""
            rows.append({
                "id": row_id, "artefact_type": artefact_type, "artefact_id": record_id, "organization_id": ctx.organization_uuid,
                "project_id": ctx.project_uuid, "org_system_id": None, "project_system_id": system_id,
                "key": key, "url": url, "note": note, "role": role, "created_by": ctx.user_ids[0], "created_at": at, "updated_at": at,
            })
            audit.add(
                artefact_type, record_id, "reference_added", ctx.user_ids[0], at,
                detail={"reference_id": str(row_id), "role": role.value if role else None, "has_url": url is not None},
                organization_id=ctx.organization_uuid,
            )
    ctx.add_count(ExternalReference.__tablename__, insert_rows(ctx.db, ExternalReference, rows))
    audit.flush()
