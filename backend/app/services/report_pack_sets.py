"""
Module: services.report_pack_sets

Saved variable sets of a report pack, and the per-project overrides of them.

Responsibilities:
- Create, rename, change and delete a set; set, change and reset a project's override of a pack-defined set.
- Resolve what a project sees: each set with its base values, the project's own override, and the effective values
  (`effective_sets`).
- `set_values_for`: the values a run takes from a chosen set, for a project, with remarks for anything ignored.
- `stale_warnings`: sets naming a value that is no longer one of the variable's options.

Design decisions:
- **Two kinds of set.** A *pack-defined* set (`project_id` null) is saved with the pack by its owner. A
  *project-added* set belongs to one project (and is visible to its descendants) and sits beside the pack's own.
  A project cannot change a pack-defined set; it overrides it.
- **Override is per variable, nearest first.** The effective value of a variable is the first override found walking
  from the running project up through its ancestors (`project_hierarchy.get_project_chain_ids`), else the base value.
  A variable an override does not list falls back; deleting the override resets to the base. A project's override is
  not inherited by anything but its descendants.
- **Values are checked against the pack's declared variables when saved** (`report_variables.check_values`), so a set
  cannot hold a value of the wrong type. A later pack version can drop or retype a variable; the stored value is then
  ignored at run with a remark (never an error), because people's saved choices should survive an edit of the pack.
- **A name is unique where it can be seen**: among a pack's own sets, and among the project-added sets of a project
  and its ancestors plus the pack's own, so a person picking by name always gets one set.
- Values are configuration: stored with the set, recorded in the manifest and provenance, and never written to a log
  line or an audit event (events carry ids, names and counts).

Dependencies: `models.report_pack`, `services.report_variables`, `services.project_hierarchy`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_pack import ReportPack, ReportPackSetOverride, ReportPackVariableSet, ReportPackVersion
from app.services.audit import log_event
from app.services.client_date import effective_today
from app.services.project_hierarchy import get_project_chain_ids
from app.services.report_variables import check_values, stale_value_warnings

MAX_NAME_CHARS = 200
MAX_SETS_PER_PACK = 50


class SetNameTakenError(ValueError):
    """A set with this name is already visible where the new one would be."""


class TooManySetsError(ValueError):
    """The pack already has `MAX_SETS_PER_PACK` sets."""


@dataclass
class EffectiveSet:
    """A set as one project (or the organisation, when `project` is `None`) sees it.

    Attributes:
        row: The set.
        origin: `pack` (saved with the pack) or `project` (added by a project).
        base: The set's own values.
        own_override: The viewing project's own override values, `None` when it has none.
        overridden_by: The nearest project whose override changes at least one value, `None` when none does.
        effective: The values a run for this project takes (base overlaid by the overrides, nearest first).
    """

    row: ReportPackVariableSet
    origin: str
    base: dict[str, Any]
    own_override: dict[str, Any] | None = None
    overridden_by: uuid.UUID | None = None
    effective: dict[str, Any] = field(default_factory=dict)


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > MAX_NAME_CHARS:
        raise ValueError(f"A set name is 1 to {MAX_NAME_CHARS} characters.")
    return cleaned


def _declarations(version: ReportPackVersion) -> list[dict[str, Any]]:
    return list(version.definition.get("variables") or [])


def _checked(version: ReportPackVersion, values: Mapping[str, Any]) -> dict[str, Any]:
    """`values` checked against the pack's variables.

    Raises:
        VariableValueError: A value is not acceptable (every problem is listed).
    """
    return check_values(_declarations(version), values, today=effective_today())


def _visible_names(db: Session, pack: ReportPack, project_id: uuid.UUID | None) -> dict[str, uuid.UUID]:
    """`{lower-cased name: set id}` of the sets a project (or the pack's owner, `None`) sees for this pack."""
    chain = get_project_chain_ids(db, project_id) if project_id is not None else []
    rows = db.scalars(select(ReportPackVariableSet).where(
        ReportPackVariableSet.pack_id == pack.id,
        (ReportPackVariableSet.project_id.is_(None)) | (ReportPackVariableSet.project_id.in_(chain)),
    )).all()
    return {r.name.casefold(): r.id for r in rows}


def _assert_name_free(
    db: Session, pack: ReportPack, project_id: uuid.UUID | None, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    taken = _visible_names(db, pack, project_id).get(name.casefold())
    if taken is not None and taken != except_id:
        raise SetNameTakenError(f'A set called "{name}" already exists for this pack.')


def get_set(db: Session, pack: ReportPack, set_id: uuid.UUID) -> ReportPackVariableSet | None:
    """The set `set_id` when it belongs to `pack`, else `None`."""
    row = db.get(ReportPackVariableSet, set_id)
    return row if row is not None and row.pack_id == pack.id else None


def create_set(
    db: Session, pack: ReportPack, version: ReportPackVersion, *, project_id: uuid.UUID | None, name: str,
    variable_values: Mapping[str, Any], actor_id: uuid.UUID | None,
) -> ReportPackVariableSet:
    """Creates a set: pack-defined when `project_id` is `None`, else added by that project.

    Raises:
        ValueError: A bad name, or `MAX_SETS_PER_PACK` reached (`TooManySetsError`).
        SetNameTakenError: The name is already visible there.
        VariableValueError: A value is not acceptable.
    """
    name = _clean_name(name)
    checked = _checked(version, variable_values)
    count = len(db.scalars(select(ReportPackVariableSet.id).where(ReportPackVariableSet.pack_id == pack.id)).all())
    if count >= MAX_SETS_PER_PACK:
        raise TooManySetsError(f"A pack has at most {MAX_SETS_PER_PACK} saved sets.")
    _assert_name_free(db, pack, project_id, name)
    row = ReportPackVariableSet(
        pack_id=pack.id, project_id=project_id, name=name, variable_values=checked, created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise SetNameTakenError(f'A set called "{name}" already exists for this pack.') from exc
    log_event(
        db, entity_type="report_pack_set", entity_id=row.id, action="created", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=project_id if project_id is not None else pack.project_id,
        detail={"pack_id": str(pack.id), "variables": len(checked)},
    )
    return row


def update_set(
    db: Session, pack: ReportPack, version: ReportPackVersion, row: ReportPackVariableSet, *, name: str | None,
    variable_values: Mapping[str, Any] | None, actor_id: uuid.UUID | None,
) -> ReportPackVariableSet:
    """Renames a set and/or replaces its values.

    Raises:
        ValueError / SetNameTakenError / VariableValueError: As `create_set`.
    """
    changed: list[str] = []
    if name is not None and (new_name := _clean_name(name)) != row.name:
        _assert_name_free(db, pack, row.project_id, new_name, except_id=row.id)
        row.name = new_name
        changed.append("name")
    if variable_values is not None:
        row.variable_values = _checked(version, variable_values)
        changed.append("values")
    if changed:
        db.flush()
        log_event(
            db, entity_type="report_pack_set", entity_id=row.id, action="updated", actor_id=actor_id,
            organization_id=pack.organization_id, project_id=row.project_id if row.project_id is not None else pack.project_id,
            detail={"pack_id": str(pack.id), "fields": changed},
        )
    return row


def delete_set(db: Session, pack: ReportPack, row: ReportPackVariableSet, *, actor_id: uuid.UUID | None) -> None:
    """Deletes a set and every project's override of it."""
    log_event(
        db, entity_type="report_pack_set", entity_id=row.id, action="deleted", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=row.project_id if row.project_id is not None else pack.project_id,
        detail={"pack_id": str(pack.id)},
    )
    db.delete(row)
    db.flush()


def put_override(
    db: Session, pack: ReportPack, version: ReportPackVersion, row: ReportPackVariableSet, project: Project, *,
    variable_values: Mapping[str, Any], actor_id: uuid.UUID | None,
) -> ReportPackSetOverride | None:
    """Sets a project's override of a pack-defined set (replacing it); no values removes it.

    Raises:
        ValueError: `row` is not a pack-defined set.
        VariableValueError: A value is not acceptable.
    """
    if row.project_id is not None:
        raise ValueError("Only a set saved with the pack can be overridden; change a project's own set directly.")
    checked = _checked(version, variable_values)
    existing = db.scalar(select(ReportPackSetOverride).where(
        ReportPackSetOverride.set_id == row.id, ReportPackSetOverride.project_id == project.id))
    if not checked:
        if existing is not None:
            reset_override(db, pack, row, project, actor_id=actor_id)
        return None
    if existing is None:
        existing = ReportPackSetOverride(set_id=row.id, project_id=project.id, variable_values=checked)
        db.add(existing)
    else:
        existing.variable_values = checked
    db.flush()
    log_event(
        db, entity_type="report_pack_set", entity_id=row.id, action="override_saved", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=project.id,
        detail={"pack_id": str(pack.id), "variables": len(checked)},
    )
    return existing


def reset_override(
    db: Session, pack: ReportPack, row: ReportPackVariableSet, project: Project, *, actor_id: uuid.UUID | None,
) -> bool:
    """Removes a project's override so the set's own values apply again. Returns whether one existed."""
    existing = db.scalar(select(ReportPackSetOverride).where(
        ReportPackSetOverride.set_id == row.id, ReportPackSetOverride.project_id == project.id))
    if existing is None:
        return False
    db.delete(existing)
    db.flush()
    log_event(
        db, entity_type="report_pack_set", entity_id=row.id, action="override_reset", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=project.id, detail={"pack_id": str(pack.id)},
    )
    return True


def _effective(row: ReportPackVariableSet, chain: Sequence[uuid.UUID], overrides: Mapping[uuid.UUID, Mapping[str, Any]]) -> EffectiveSet:
    """`row` with the overrides of `chain` (nearest first) applied per variable."""
    values = dict(row.variable_values)
    decided: set[str] = set()
    nearest: uuid.UUID | None = None
    for project_id in chain:
        found = overrides.get(project_id)
        if not found:
            continue
        for name, value in found.items():
            if name not in decided:
                decided.add(name)
                values[name] = value
                nearest = nearest or project_id
    own = overrides.get(chain[0]) if chain else None
    return EffectiveSet(
        row, "pack" if row.project_id is None else "project", dict(row.variable_values),
        dict(own) if own else None, nearest, values,
    )


def effective_sets(db: Session, pack: ReportPack, project: Project | None) -> list[EffectiveSet]:
    """The pack's sets as `project` sees them (the organisation's view when `project` is `None`), by name.

    Pack-defined sets carry the overrides of the project and its ancestors. Project-added sets are those of the
    project and its ancestors; a nearer set shadows a farther one of the same name.
    """
    chain = get_project_chain_ids(db, project.id) if project is not None else []
    rows = list(db.scalars(select(ReportPackVariableSet).where(
        ReportPackVariableSet.pack_id == pack.id,
        (ReportPackVariableSet.project_id.is_(None)) | (ReportPackVariableSet.project_id.in_(chain)),
    )).all())
    pack_set_ids = [r.id for r in rows if r.project_id is None]
    by_set: dict[uuid.UUID, dict[uuid.UUID, Mapping[str, Any]]] = {}
    if pack_set_ids and chain:
        for ov in db.scalars(select(ReportPackSetOverride).where(
            ReportPackSetOverride.set_id.in_(pack_set_ids), ReportPackSetOverride.project_id.in_(chain),
        )):
            by_set.setdefault(ov.set_id, {})[ov.project_id] = ov.variable_values
    rank = {pid: i for i, pid in enumerate(chain)}
    rows.sort(key=lambda r: (-1 if r.project_id is None else rank.get(r.project_id, len(chain)), r.name.casefold()))
    seen: set[str] = set()
    out: list[EffectiveSet] = []
    for row in rows:
        key = row.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(_effective(row, chain, by_set.get(row.id, {})))
    return sorted(out, key=lambda e: e.row.name.casefold())


def set_values_for(
    db: Session, pack: ReportPack, version: ReportPackVersion, set_id: uuid.UUID, project: Project | None,
) -> tuple[dict[str, Any], list[str], str]:
    """The values a run takes from set `set_id` as `project` sees it.

    Args:
        db: Active session (read only).
        pack: The pack being run.
        version: Its pinned version (its variables decide which stored names still apply).
        set_id: The chosen set.
        project: The project of a project-level run; `None` for the organisation's own view (base values).

    Returns:
        `(values, remarks, set name)`; names the pack no longer declares are dropped and remarked.

    Raises:
        LookupError: The set is not one this project (or the organisation) can use.
    """
    found = next((e for e in effective_sets(db, pack, project) if e.row.id == set_id), None)
    if found is None:
        raise LookupError("No such saved set.")
    declared = {d["name"] for d in _declarations(version)}
    values = {n: v for n, v in found.effective.items() if n in declared}
    dropped = len(found.effective) - len(values)
    remarks = (
        [f'The set "{found.row.name}" names {dropped} variable(s) this version of the pack no longer declares; they were ignored.']
        if dropped else []
    )
    return values, remarks, found.row.name


def stale_warnings(
    db: Session, version: ReportPackVersion, values: Mapping[str, Any], project_ids: Sequence[uuid.UUID],
) -> list[str]:
    """Remarks for set values that are no longer among their variable's options (names the variable, never the value)."""
    declarations = _declarations(version)
    present = {n: v for n, v in values.items() if any(d["name"] == n for d in declarations)}
    subset = [d for d in declarations if d["name"] in present]
    return stale_value_warnings(db, subset, present, project_ids)


__all__ = [
    "MAX_SETS_PER_PACK", "EffectiveSet", "SetNameTakenError", "TooManySetsError", "create_set", "delete_set",
    "effective_sets", "get_set", "put_override", "reset_override", "set_values_for", "stale_warnings", "update_set",
]
