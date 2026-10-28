"""
Module: services.report_placement_bundle

Report placements (where each report appears in the Reports picker, and which module reports are hidden) in the project
and organisation export bundles.

Responsibilities:
- Export a scope's own placements, each naming its report portably: a module report by its module and report key, a
  layout or pack by its name (ids differ between installations).
- Import them after the layouts and packs they refer to: resolve each name against what the target scope can reach,
  tidy the folder again and store the row; one that names nothing here is reported, not guessed.

Design decisions:
- **A bundle is untrusted input.** A folder goes through `clean_folder` again (an invalid one is dropped); a hide of a
  layout or pack is ignored (those are hidden from their own lists); a module report this installation does not
  register is skipped with a warning.
- Placements are configuration: no author or time is restored and nothing is logged beyond the audit event of the
  store.

Dependencies: `services.report_placements`, `services.report_layout_scope`, `services.report_pack_scope`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack
from app.models.report_placement import ReportPlacement
from app.models.user import User
from app.modules.registry import get_all_reports
from app.services import report_layout_scope, report_pack_scope, report_placements
from app.services.bundle_common import BundleImportWarnings
from app.services.record_list_report import REPORT_KEY as RECORD_LIST_KEY
from app.services.report_folders import imported_folder

PROJECT_KEY = "report_placements"
ORG_KEY = "report_placements"
_PLATFORM_KEYS = {report_placements.report_key("platform", RECORD_LIST_KEY), report_placements.REQUIREMENTS_REPORT_KEY}


def _portable(db: Session, row: ReportPlacement) -> dict[str, Any] | None:
    """One placement in bundle form, or `None` when what it names is gone."""
    entry: dict[str, Any] = {"folder": row.folder, "hidden": row.hidden}
    key = row.report_key
    if key.startswith("report:"):
        entry["report"] = key[len("report:"):]
    elif key.startswith("layout:"):
        layout = db.get(ReportLayout, uuid.UUID(key[len("layout:"):]))
        if layout is None:
            return None
        entry["layout"] = layout.name
    elif key.startswith("pack:"):
        pack = db.get(ReportPack, uuid.UUID(key[len("pack:"):]))
        if pack is None:
            return None
        entry["pack"] = pack.name
    else:
        return None
    return entry


def _export(db: Session, rows: list[ReportPlacement]) -> list[dict[str, Any]]:
    return [e for row in rows if (e := _portable(db, row)) is not None]


def export_project_placements(db: Session, project: Project) -> dict[str, Any]:
    """The project's own placements as a `project.json` section."""
    rows = db.scalars(
        select(ReportPlacement).where(ReportPlacement.project_id == project.id).order_by(ReportPlacement.report_key)
    ).all()
    return {PROJECT_KEY: _export(db, list(rows))}


def export_org_placements(db: Session, organization_id: uuid.UUID) -> dict[str, Any]:
    """The organisation's own placements as an `org.json` section."""
    rows = db.scalars(
        select(ReportPlacement)
        .where(ReportPlacement.organization_id == organization_id, ReportPlacement.project_id.is_(None))
        .order_by(ReportPlacement.report_key)
    ).all()
    return {ORG_KEY: _export(db, list(rows))}


def _known_report_keys() -> set[str]:
    return {report_placements.report_key(module_key, d.key) for module_key, d in get_all_reports()} | _PLATFORM_KEYS


def _import(
    db: Session, entries: list[Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    layouts: dict[str, uuid.UUID], packs: dict[str, uuid.UUID], actor: User, warnings: BundleImportWarnings,
) -> None:
    known = _known_report_keys()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key: str | None = None
        if isinstance(entry.get("report"), str):
            candidate = f"report:{entry['report']}"
            key = candidate if candidate in known else None
        elif isinstance(entry.get("layout"), str) and (layout_id := layouts.get(entry["layout"].casefold())):
            key = report_placements.layout_key(layout_id)
        elif isinstance(entry.get("pack"), str) and (pack_id := packs.get(entry["pack"].casefold())):
            key = report_placements.pack_key(pack_id)
        if key is None:
            warnings.add("A report placement was not applied: the report it names is not available here.")
            continue
        folder = entry.get("folder")
        hidden = entry.get("hidden") if isinstance(entry.get("hidden"), bool) and report_placements.is_hideable(key) else None
        try:
            report_placements.set_placement(
                db, organization_id=organization_id, project_id=project_id, key=key,
                folder=imported_folder(folder) if isinstance(folder, str) else None, hidden=hidden, valid_keys=None,
                actor_id=actor.id,
            )
        except report_placements.PlacementError:
            warnings.add("A report placement was not applied: it is not valid here.")


def import_org_placements(
    db: Session, organization_id: uuid.UUID, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports an `org.json`'s placements (after its layouts and packs)."""
    entries = data.get(ORG_KEY, [])
    if not isinstance(entries, list) or not entries:
        return
    layouts = {layout.name.casefold(): layout.id for layout in report_layout_scope.list_org_layouts(db, organization_id)}
    packs = {pack.name.casefold(): pack.id for pack in report_pack_scope.list_org_packs(db, organization_id)}
    _import(db, entries, organization_id=organization_id, project_id=None, layouts=layouts, packs=packs, actor=actor, warnings=warnings)


def import_project_placements(
    db: Session, project: Project, data: dict[str, Any], actor: User, warnings: BundleImportWarnings,
) -> None:
    """Imports a `project.json`'s placements (after its layouts and packs), resolving names nearest owner first."""
    entries = data.get(PROJECT_KEY, [])
    if not isinstance(entries, list) or not entries:
        return
    layouts: dict[str, uuid.UUID] = {}
    for scoped_layout in report_layout_scope.resolve_project_layouts(db, project):
        layouts.setdefault(scoped_layout.layout.name.casefold(), scoped_layout.layout.id)
    packs: dict[str, uuid.UUID] = {}
    for scoped_pack in report_pack_scope.resolve_project_packs(db, project):
        packs.setdefault(scoped_pack.pack.name.casefold(), scoped_pack.pack.id)
    _import(
        db, entries, organization_id=project.organization_id, project_id=project.id, layouts=layouts, packs=packs,
        actor=actor, warnings=warnings,
    )
