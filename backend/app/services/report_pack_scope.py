"""
Module: services.report_pack_scope

Which report packs a project can see, and hiding or restoring the inherited ones.

Responsibilities:
- `resolve_project_packs`: the packs a project can reach, each with where it comes from.
- `hide_pack` / `restore_packs`: a project hides an inherited pack and brings it back.
- `list_org_packs`: an organisation's own packs.

Design decisions:
- **Visibility is additive.** A project sees its own packs, its ancestors' (nearest first) and the
  organisation's, de-duplicated by name (case-insensitively) with the nearest owner winning. The Action
  Types rule ("own rows, else the nearest ancestor's") would hide every inherited pack the moment a
  project made one of its own, so it is not used here. A name that a nearer pack shadows is not
  listed and cannot be hidden separately.
- **Hiding is a tombstone** (`ProjectDefinitionSuppression`, kind `report_pack`), per project and not
  inherited downwards, exactly as the other organisation defaults. Only an inherited pack can be
  hidden; a project removes its own by deleting it. A hidden pack keeps its name, so it does not let a
  farther pack of the same name show through.
- Unlike layouts, packs have no platform starter tier.

Dependencies: `models.report_pack`, `services.project_hierarchy`, `services.definition_suppression`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_pack import ReportPack
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

PACK_KIND = "report_pack"
"""The `ProjectDefinitionSuppression.definition_kind` of a hidden report pack."""

definition_suppression.register_definition_kind(PACK_KIND)

Origin = Literal["organization", "ancestor", "project"]


@dataclass(frozen=True)
class ScopedPack:
    """A pack as one project sees it.

    Attributes:
        pack: The pack row.
        origin: `project` (its own), `ancestor` (a parent project's) or `organization`.
        hidden: Whether this project has hidden it (never true for its own).
    """

    pack: ReportPack
    origin: Origin
    hidden: bool


def list_org_packs(db: Session, organization_id: uuid.UUID) -> list[ReportPack]:
    """The organisation-level packs of `organization_id`, by name."""
    return list(db.scalars(
        select(ReportPack)
        .where(ReportPack.organization_id == organization_id, ReportPack.project_id.is_(None))
        .order_by(ReportPack.name)
    ).all())


def resolve_project_packs(db: Session, project: Project) -> list[ScopedPack]:
    """Every pack `project` can reach, nearest owner first, hidden ones flagged.

    Args:
        db: Active session.
        project: The project.

    Returns:
        The de-duplicated packs: the project's own, then each ancestor's (nearest first), then the
        organisation's; within a tier by name. A farther pack whose name a nearer one already uses is
        left out.
    """
    chain = get_project_chain_ids(db, project.id)  # the project itself first, then its parent ... the root
    rows = list(db.scalars(
        select(ReportPack).where(
            ReportPack.organization_id == project.organization_id,
            (ReportPack.project_id.in_(chain)) | (ReportPack.project_id.is_(None)),
        )
    ).all())
    rank = {pid: i for i, pid in enumerate(chain)}
    rows.sort(key=lambda r: (rank.get(r.project_id, len(chain)) if r.project_id else len(chain), r.name.lower()))
    hidden_ids = definition_suppression.get_suppressed_ids(db, project.id, PACK_KIND)
    seen: set[str] = set()
    out: list[ScopedPack] = []
    for row in rows:
        key = row.name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        origin: Origin = "organization" if row.project_id is None else ("project" if row.project_id == project.id else "ancestor")
        out.append(ScopedPack(row, origin, hidden=origin != "project" and row.id in hidden_ids))
    return out


def reachable_pack(db: Session, project: Project, pack_id: uuid.UUID) -> ScopedPack | None:
    """`pack_id` as `project` sees it, or `None` when it is not reachable (another owner's, or shadowed)."""
    return next((s for s in resolve_project_packs(db, project) if s.pack.id == pack_id), None)


def hide_pack(db: Session, project: Project, pack_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> bool:
    """Hides an inherited pack in `project`. Idempotent.

    Raises:
        LookupError: The pack is not one the project inherits (unreachable, shadowed, or its own).
    """
    scoped = reachable_pack(db, project, pack_id)
    if scoped is None or scoped.origin == "project":
        raise LookupError("No such inherited pack.")
    created = definition_suppression.hide_definition(db, project.id, PACK_KIND, pack_id)
    if created:
        log_event(
            db, entity_type="report_pack", entity_id=pack_id, action="hidden", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return created


def restore_packs(
    db: Session, project: Project, pack_ids: set[uuid.UUID] | None, *, actor_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    """Shows hidden packs in `project` again.

    Args:
        pack_ids: The packs to restore, or `None` for every hidden one.

    Returns:
        The ids restored.
    """
    restored = definition_suppression.restore_definitions(db, project.id, PACK_KIND, pack_ids)
    for pack_id in sorted(restored, key=str):
        log_event(
            db, entity_type="report_pack", entity_id=pack_id, action="restored", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={},
        )
    return restored


__all__ = [
    "PACK_KIND", "Origin", "ScopedPack", "hide_pack", "list_org_packs", "reachable_pack",
    "resolve_project_packs", "restore_packs",
]
