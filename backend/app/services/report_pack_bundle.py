"""
Module: services.report_pack_bundle

Report packs, their saved variable sets and per-project overrides in the project and organisation export bundles.

Responsibilities:
- Export a project's own packs (every version, with their sets), the inherited packs it hides, the sets it added to
  inherited packs and the overrides it holds; export an organisation's own packs with their sets.
- Import them: validate every definition again, number versions afresh, re-apply hides, added sets and overrides by name.

Design decisions:
- **A bundle is untrusted input.** Each version is validated against this deployment (`report_packs.create_pack` /
  `save_version`): a version that fails is dropped with a warning, and a pack with no valid version is skipped.
  Versions are renumbered 1..n so history stays gap-free. A set whose values no longer fit the imported pack is
  skipped with a warning (never stored half-valid).
- **Everything travels by name.** A pack is named; a hide, an added set and an override name the inherited pack (and
  the set) they apply to, resolved against the target project's inherited packs after the organisation's packs are
  imported (organisation bundle) or against the organisation it joins (project bundle). A name with nothing to apply
  to is reported, not guessed. An override travels in the *project's* section (it is that project's data), a set saved
  with an organisation pack in the organisation's.
- **Authors and times are not restored**, as for layouts: the importer becomes the author; the version comment travels.
- **A taken name is never overwritten** (organisation merge): the pack imports as "<name> (imported)", or is skipped
  with a warning when that is also taken.
- Variable values are configuration and travel as written; they are not logged.

Dependencies: `services.report_packs`, `services.report_pack_sets`, `services.report_pack_scope`, `services.bundle_common`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_pack import ReportPack, ReportPackSetOverride, ReportPackVariableSet
from app.models.user import User
from app.services import report_pack_scope, report_pack_sets, report_packs
from app.services.bundle_common import BundleImportWarnings
from app.services.report_folders import imported_folder
from app.services.report_pack_definition import InvalidPackError
from app.services.report_variables import VariableValueError

PROJECT_KEY = "report_packs"
HIDDEN_KEY = "report_packs_hidden"
ADDED_SETS_KEY = "report_pack_sets_added"
OVERRIDES_KEY = "report_pack_set_overrides"
ORG_KEY = "report_packs"


def pack_entry(
    db: Session, pack: ReportPack, *, latest_only: bool = False, sets: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """One pack with every version (oldest first) and the sets saved with it. Author email and time are information only.

    `latest_only` keeps just the current version, noted "Copied from <name>, version n". `sets` replaces the
    pack-defined sets with the given `(name, values)` pairs (a copy carries the sets as one project sees them).
    """
    versions = report_packs.list_versions(db, pack.id)
    if latest_only:
        versions = [v for v in versions if v.version == pack.current_version]
    emails = {
        u.id: u.email for u in db.scalars(select(User).where(User.id.in_({v.created_by for v in versions if v.created_by})))
    } if any(v.created_by for v in versions) else {}
    pack_sets = db.scalars(
        select(ReportPackVariableSet).where(ReportPackVariableSet.pack_id == pack.id, ReportPackVariableSet.project_id.is_(None))
        .order_by(ReportPackVariableSet.name)
    ).all()
    return {
        "name": pack.name, "description": pack.description, "folder": pack.folder,
        "versions": [
            {
                "version": v.version, "schema_version": v.schema_version, "definition": v.definition,
                "comment": f"Copied from {pack.name}, version {v.version}"[: report_packs.MAX_COMMENT_CHARS] if latest_only else v.comment,
                "created_by_email": emails.get(v.created_by) if v.created_by else None, "created_at": v.created_at.isoformat(),
            }
            for v in reversed(versions)
        ],
        "sets": (
            [{"name": n, "values": v} for n, v in sets] if sets is not None
            else [{"name": s.name, "values": s.variable_values} for s in pack_sets]
        ),
    }


def export_project_packs(db: Session, project: Project) -> dict[str, Any]:
    """The project's own packs, the inherited packs it hides, the sets it added and the overrides it holds (all by name)."""
    own = db.scalars(select(ReportPack).where(ReportPack.project_id == project.id).order_by(ReportPack.name)).all()
    scoped = report_pack_scope.resolve_project_packs(db, project)
    hidden = [{"name": s.pack.name, "origin": s.origin} for s in scoped if s.hidden]
    added: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    for item in scoped:
        if item.origin == "project":
            continue
        for row in db.scalars(select(ReportPackVariableSet).where(
            ReportPackVariableSet.pack_id == item.pack.id, ReportPackVariableSet.project_id == project.id,
        ).order_by(ReportPackVariableSet.name)):
            added.append({"pack": item.pack.name, "name": row.name, "values": row.variable_values})
        for ov, set_row in db.execute(
            select(ReportPackSetOverride, ReportPackVariableSet)
            .join(ReportPackVariableSet, ReportPackVariableSet.id == ReportPackSetOverride.set_id)
            .where(ReportPackVariableSet.pack_id == item.pack.id, ReportPackSetOverride.project_id == project.id)
            .order_by(ReportPackVariableSet.name)
        ):
            overrides.append({"pack": item.pack.name, "set": set_row.name, "values": ov.variable_values})
    return {
        PROJECT_KEY: [pack_entry(db, pack) for pack in own], HIDDEN_KEY: hidden, ADDED_SETS_KEY: added,
        OVERRIDES_KEY: overrides,
    }


def export_org_packs(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The organisation's own packs (with their sets) as an `org.json` section."""
    return {ORG_KEY: [pack_entry(db, pack) for pack in report_pack_scope.list_org_packs(db, organization_id)]}


def _import_sets(
    db: Session, pack: ReportPack, entry: dict[str, Any], actor: User, warnings: BundleImportWarnings, name: str,
) -> None:
    version = report_packs.current_version(db, pack)
    for item in entry.get("sets", []):
        if not isinstance(item, dict) or not isinstance(item.get("values"), dict):
            continue
        try:
            report_pack_sets.create_set(
                db, pack, version, project_id=None, name=str(item.get("name", "")), variable_values=item["values"],
                actor_id=actor.id,
            )
        except (ValueError, VariableValueError):
            warnings.add(f'Saved set "{item.get("name", "")}" of report pack "{name}" was skipped: it is not valid for this pack.')


def import_pack_entry(
    db: Session, entry: dict[str, Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None, actor: User,
    warnings: BundleImportWarnings, existing_names: set[str] | None = None,
) -> ReportPack | None:
    """Creates one pack (with its sets) from its bundle entry. Returns the new pack, or `None` when none was stored."""
    name = str(entry.get("name", "")).strip()
    versions = sorted(
        (v for v in entry.get("versions", []) if isinstance(v, dict) and isinstance(v.get("definition"), dict)),
        key=lambda v: v.get("version", 0),
    )
    if existing_names is not None and name.casefold() in existing_names:
        name = f"{name} (imported)"
    pack: ReportPack | None = None
    stored = 0
    dropped = 0
    for v in versions:
        comment = str(v.get("comment", ""))[: report_packs.MAX_COMMENT_CHARS]
        v = {**v, "definition": {k: val for k, val in v["definition"].items() if k != "template"}}  # an older pack named a branding template
        try:
            if pack is None:
                saved = report_packs.create_pack(
                    db, organization_id=organization_id, project_id=project_id, name=name,
                    description=str(entry.get("description", "")), folder=imported_folder(entry.get("folder")), definition=v["definition"],
                    actor_id=actor.id, comment=comment,
                )
                pack = saved.pack
            else:
                saved = report_packs.save_version(db, pack.id, v["definition"], base_version=stored, actor_id=actor.id, comment=comment)
        except report_packs.PackNameTakenError:
            warnings.add(f'Report pack "{name}" was skipped: a pack with that name already exists.')
            return None
        except (InvalidPackError, ValueError):
            dropped += 1
            continue
        stored = saved.pack.current_version
    if pack is None:
        warnings.add(f'Report pack "{name}" was skipped: none of its versions is valid in this installation.')
        return None
    if dropped:
        warnings.add(f'Report pack "{name}": {dropped} version(s) that are not valid in this installation were left out.')
    _import_sets(db, pack, entry, actor, warnings, name)
    return pack


def import_org_packs(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings, *, merge: bool,
) -> int:
    """Imports the `org.json` packs. `merge` is true when the organisation already exists.

    Returns:
        How many packs were stored.
    """
    existing = (
        {n.casefold() for n in db.scalars(select(ReportPack.name).where(
            ReportPack.organization_id == organization_id, ReportPack.project_id.is_(None)))}
        if merge else None
    )
    return sum(
        import_pack_entry(
            db, entry, organization_id=organization_id, project_id=None, actor=actor, warnings=warnings, existing_names=existing,
        ) is not None
        for entry in data.get(ORG_KEY, []) if isinstance(entry, dict)
    )


def import_project_packs(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports a `project.json`'s own packs, then re-applies the hides, added sets and overrides to the packs it inherits."""
    for entry in data.get(PROJECT_KEY, []):
        if isinstance(entry, dict):
            import_pack_entry(db, entry, organization_id=project.organization_id, project_id=project.id, actor=actor, warnings=warnings)
    hidden = [h for h in data.get(HIDDEN_KEY, []) if isinstance(h, dict)]
    added = [a for a in data.get(ADDED_SETS_KEY, []) if isinstance(a, dict)]
    overrides = [o for o in data.get(OVERRIDES_KEY, []) if isinstance(o, dict)]
    if not (hidden or added or overrides):
        return
    inherited = {
        s.pack.name.casefold(): s.pack for s in report_pack_scope.resolve_project_packs(db, project) if s.origin != "project"
    }
    for item in hidden:
        pack = inherited.get(str(item.get("name", "")).casefold())
        if pack is None:
            warnings.add(f'Hidden report pack "{item.get("name", "")}" was not applied: this project inherits no pack of that name.')
            continue
        report_pack_scope.hide_pack(db, project, pack.id, actor_id=actor.id)
    for item in added:
        pack = inherited.get(str(item.get("pack", "")).casefold())
        if pack is None or not isinstance(item.get("values"), dict):
            warnings.add(f'Saved set "{item.get("name", "")}" was not imported: this project inherits no report pack "{item.get("pack", "")}".')
            continue
        try:
            report_pack_sets.create_set(
                db, pack, report_packs.current_version(db, pack), project_id=project.id, name=str(item.get("name", "")),
                variable_values=item["values"], actor_id=actor.id,
            )
        except (ValueError, VariableValueError):
            warnings.add(f'Saved set "{item.get("name", "")}" of report pack "{pack.name}" was skipped: it is not valid for this pack.')
    for item in overrides:
        pack = inherited.get(str(item.get("pack", "")).casefold())
        row = None
        if pack is not None:
            row = db.scalar(select(ReportPackVariableSet).where(
                ReportPackVariableSet.pack_id == pack.id, ReportPackVariableSet.project_id.is_(None),
                ReportPackVariableSet.name == str(item.get("set", "")),
            ))
        if pack is None or row is None or not isinstance(item.get("values"), dict):
            warnings.add(f'An override of set "{item.get("set", "")}" was not applied: this project inherits no such report pack set.')
            continue
        try:
            report_pack_sets.put_override(
                db, pack, report_packs.current_version(db, pack), row, project, variable_values=item["values"], actor_id=actor.id,
            )
        except (ValueError, VariableValueError):
            warnings.add(f'An override of set "{row.name}" was skipped: its values are not valid for the pack.')


__all__ = [
    "export_org_packs", "export_project_packs", "import_org_packs", "import_pack_entry", "import_project_packs", "pack_entry",
]
