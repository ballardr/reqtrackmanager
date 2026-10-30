"""
Module: services.report_duplicate

Duplicates one report layout or pack as an editable basis for a new one: a layout or pack the caller can reach (their
own, an ancestor's or the organisation's) or one of the built-in starter layouts, copied to the caller's own tier or up
to the organisation.

Responsibilities:
- `duplicate`: plans (`dry_run`) or performs one duplicate and writes one audit event; the plan names the final
  name, whether it shadows an inherited report, what does not carry cleanly and any project picture that blocks a copy up.
- `starter_sources`: the built-in starter definitions, listed for the "New from a starter" choice.

Design decisions:
- **One serialiser, not a second copier.** A layout or pack becomes its project-bundle entry and is created by the
  bundle's own importer (as the cross-project copy does), so validation, the create path and any field added later are
  shared. Only the latest version is copied, as version 1 of an independent report; history, favourites, hide and
  placement state, pack membership and saved sets stay with the source.
- **Built-in starters are a source of their own.** The organisation's seeded starter is an ordinary layout that may have
  been edited or deleted; the definitions in `report_starters` still give "start from the BRD".
- **Pictures.** An organisation picture stays a reference. A project picture is reused when the copy lands in the same
  project, copied into the destination project's library when it lands in another, and *refuses* a copy up to the
  organisation: publishing a project's picture to every member is the person's decision, not a side effect.
- **Folders.** The copy is filed beside the source when the destination can use that folder, else at the top level.
- **Names.** A free name is suggested ("<name> (copy)", "(copy 2)" ...) among the destination's own reports and what the
  project inherits; a name the destination already owns is refused, one that matches an inherited report is allowed and
  warned about (it shadows it, as any project report does).
- **Packs** copy their definition (entries still name the same layouts, resolved by name where the copy lands) and no
  saved sets, which belong to the pack they were saved against.
- Gates are the route's: read and manage the source, manage the destination tier (project permission or the
  organisation's, groups included).

Dependencies: `services.report_layout_bundle`, `services.report_pack_bundle`, `services.report_layout_scope`,
`services.report_pack_scope`, `services.report_starters`, `services.report_folder_store`, `services.report_placements`,
`services.report_copy`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_layout import FAMILY_DOCUMENT, ReportLayout
from app.models.report_pack import ReportPack
from app.models.user import User
from app.modules.registry import get_all_reports, report_enabled_for_project
from app.services import (
    report_copy,
    report_folder_store,
    report_layout_bundle,
    report_layout_scope,
    report_layouts,
    report_pack_bundle,
    report_pack_scope,
    report_packs,
    report_placements,
    report_starters,
)
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.files import read_file
from app.services.report_images import usable_by_layout
from app.services.report_layout_tree import TREE_SCHEMA_VERSION

Kind = Literal["layout", "pack", "starter"]
Tier = Literal["project", "organization"]


class DuplicateRefusedError(LookupError):
    """The source is not one the caller's scope can reach (or the starter key is unknown)."""


class DuplicateBlockedError(ValueError):
    """The copy cannot be made as asked; `images` names the project pictures that block a copy up to the organisation."""

    def __init__(self, message: str, images: list[str]) -> None:
        super().__init__(message)
        self.images = images


@dataclass
class DuplicatePlan:
    """What a duplicate does, or (once applied) did.

    Attributes:
        kind: `layout`, `pack` or `starter`.
        source_name: The source's name.
        origin: `project`, `ancestor`, `organization` or `starter` (the built-in definition).
        name: The name the copy gets (the requested one, else the suggestion).
        suggested_name: The first free "<name> (copy)" style name.
        name_taken: The destination tier already owns a report of `name` (an apply is refused).
        shadows: `name` matches a report the destination project inherits.
        folder: The folder the copy is filed in (`""` = top level).
        warnings: What does not carry cleanly.
        blocked_images: Filenames of project pictures that stop a copy up to the organisation.
        new_id: The created layout or pack, set once applied.
    """

    kind: Kind
    source_name: str
    origin: str
    name: str
    suggested_name: str
    name_taken: bool = False
    shadows: bool = False
    folder: str = ""
    warnings: list[str] = field(default_factory=list)
    blocked_images: list[str] = field(default_factory=list)
    new_id: uuid.UUID | None = None


@dataclass(frozen=True)
class _Source:
    kind: Kind
    name: str
    origin: str
    description: str
    folder: str
    layout: ReportLayout | None = None
    pack: ReportPack | None = None
    starter_key: str | None = None


def starter_sources() -> list[report_starters.StarterLayout]:
    """The built-in starter definitions, in the order the platform ships them."""
    return list(report_starters.STARTERS)


def _find_source(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, kind: Kind, source_id: uuid.UUID | None, starter_key: str | None,
) -> _Source:
    """The source as the caller's scope sees it.

    Raises:
        DuplicateRefusedError: Unknown or unreachable (another owner's, shadowed, another organisation's).
    """
    if kind == "starter":
        starter = next((s for s in report_starters.STARTERS if s.key == starter_key), None)
        if starter is None:
            raise DuplicateRefusedError("Starter not found.")
        return _Source("starter", starter.name, "starter", starter.description, "", starter_key=starter.key)
    if source_id is None:
        raise DuplicateRefusedError("Name the report to duplicate.")
    if kind == "layout":
        if project is not None:
            scoped = report_layout_scope.reachable_layout(db, project, source_id)
            if scoped is None:
                raise DuplicateRefusedError("Layout not found.")
            layout, origin = scoped.layout, scoped.origin
            placed = report_placements.resolve_for_project(db, project).get(report_placements.layout_key(layout.id))
            folder = placed.folder if placed is not None and placed.folder is not None else layout.folder
        else:
            org_layout = db.get(ReportLayout, source_id)
            if org_layout is None or org_layout.organization_id != organization_id or org_layout.project_id is not None:
                raise DuplicateRefusedError("Layout not found.")
            layout, origin, folder = org_layout, "organization", org_layout.folder
        return _Source("layout", layout.name, origin, layout.description, folder, layout=layout)
    if project is not None:
        scoped_pack = report_pack_scope.reachable_pack(db, project, source_id)
        if scoped_pack is None:
            raise DuplicateRefusedError("Pack not found.")
        pack, origin = scoped_pack.pack, scoped_pack.origin
        placed = report_placements.resolve_for_project(db, project).get(report_placements.pack_key(pack.id))
        folder = placed.folder if placed is not None and placed.folder is not None else pack.folder
    else:
        org_pack = db.get(ReportPack, source_id)
        if org_pack is None or org_pack.organization_id != organization_id or org_pack.project_id is not None:
            raise DuplicateRefusedError("Pack not found.")
        pack, origin, folder = org_pack, "organization", org_pack.folder
    return _Source("pack", pack.name, origin, pack.description, folder, pack=pack)


def _names(db: Session, kind: Kind, organization_id: uuid.UUID, dest: Project | None) -> tuple[set[str], set[str]]:
    """`(own, inherited)` lower-cased names at the destination: what it owns, and what a project also sees from above."""
    model: type[ReportLayout] | type[ReportPack] = ReportPack if kind == "pack" else ReportLayout
    owner = model.project_id.is_(None) if dest is None else model.project_id == dest.id
    own = {n.casefold() for n in db.scalars(select(model.name).where(model.organization_id == organization_id, owner))}
    inherited: set[str] = set()
    if dest is not None:
        if kind == "pack":
            inherited = {s.pack.name.casefold() for s in report_pack_scope.resolve_project_packs(db, dest) if s.origin != "project"}
        else:
            inherited = {s.layout.name.casefold() for s in report_layout_scope.resolve_project_layouts(db, dest) if s.origin != "project"}
    return own, inherited


def _source_entry(db: Session, source: _Source) -> dict[str, Any]:
    """The source's bundle entry (latest version only)."""
    if source.layout is not None:
        return report_layout_bundle.layout_entry(db, source.layout, latest_only=True)
    if source.pack is not None:
        return report_pack_bundle.pack_entry(db, source.pack, latest_only=True, sets=[])
    starter = next(s for s in report_starters.STARTERS if s.key == source.starter_key)
    return {
        "name": starter.name, "description": starter.description, "folder": "", "family": FAMILY_DOCUMENT, "report_template": None,
        "versions": [{
            "version": 1, "schema_version": TREE_SCHEMA_VERSION, "tree": starter.tree,
            "comment": f"Copied from the built-in starter {starter.name}"[: report_layouts.MAX_COMMENT_CHARS],
        }],
    }


def _pack_warnings(db: Session, entry: dict[str, Any], organization_id: uuid.UUID, dest: Project | None) -> list[str]:
    """Pack entries that will not resolve where the copy lands: a layout of that name that is not there, a module that is off."""
    version = entry["versions"][-1]["definition"] if entry["versions"] else {}
    if dest is None:
        layout_names = {layout.name.casefold() for layout in report_layout_scope.list_org_layouts(db, organization_id)}
    else:
        layout_names = {s.layout.name.casefold() for s in report_layout_scope.resolve_project_layouts(db, dest)}
    missing: set[str] = set()
    off: set[str] = set()
    reports = {(mk, d.key): d for mk, d in get_all_reports()}
    for item in version.get("entries", []):
        if item.get("kind") == "layout" and str(item.get("name", "")).casefold() not in layout_names:
            missing.add(str(item.get("name", "")))
        elif item.get("kind") == "report" and dest is not None:
            definition = reports.get((item.get("module_key"), item.get("report")))
            if definition is not None and not report_enabled_for_project(db, dest.id, item["module_key"], definition):
                off.add(str(item["module_key"]))
    warnings: list[str] = []
    if missing:
        where = "the organisation" if dest is None else "this project"
        warnings.append(
            f"Entries use layouts that {where} does not have: {', '.join(sorted(missing))}. They run only if a layout of that name exists."
        )
    if off:
        warnings.append(f"Entries use reports of modules that are off in this project: {', '.join(sorted(off))}.")
    return warnings


def _pictures(
    db: Session, entry: dict[str, Any], organization_id: uuid.UUID, source_project_id: uuid.UUID | None, dest_project_id: uuid.UUID | None,
) -> tuple[list[dict[str, Any]], dict[uuid.UUID, FileAsset]]:
    """The bundle picture entries the destination cannot already use, with their files (reuse needs no copy)."""
    assets: dict[uuid.UUID, FileAsset] = {}
    used = report_layout_bundle.image_entries(db, [entry], organization_id, source_project_id, assets)
    return [e for e in used if not usable_by_layout(assets[uuid.UUID(e["id"])], organization_id, dest_project_id)], assets


def duplicate(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, kind: Kind, source_id: uuid.UUID | None = None,
    starter_key: str | None = None, target: Tier, name: str | None, caller: User, dry_run: bool,
) -> DuplicatePlan:
    """Plans, or performs in the caller's transaction (flushed, not committed), the duplicate of one report.

    Args:
        db: Active session.
        organization_id: The caller's organisation.
        project: The project the caller works in, or `None` for the organisation's own page.
        kind: `layout`, `pack` or a built-in `starter` layout.
        source_id: The layout or pack (reachable from `project`, else owned by the organisation); unused for a starter.
        starter_key: The starter's key (`report_starters.StarterLayout.key`).
        target: `project` (the caller's project; needs `project`) or `organization` (copy up, or an organisation page's copy).
        name: The copy's name; the suggestion when empty.
        caller: The person duplicating (the gates are the route's).
        dry_run: Plan only; nothing is written.

    Returns:
        The plan; on apply `new_id` is the created report.

    Raises:
        DuplicateRefusedError: The source is unknown or not reachable.
        DuplicateBlockedError: A project picture blocks a copy up to the organisation (apply only; the plan lists them).
        LayoutNameTakenError / PackNameTakenError: The destination already owns the name (apply only).
        ValueError: A bad name, a `project` target with no project, or a copy the importer rejects (an invalid tree).
    """
    if target == "project" and project is None:
        raise ValueError("Choose the project to copy into.")
    dest = project if target == "project" else None
    source = _find_source(db, organization_id=organization_id, project=project, kind=kind, source_id=source_id, starter_key=starter_key)
    own, inherited = _names(db, "pack" if kind == "pack" else "layout", organization_id, dest)
    suggested = source.name if source.kind == "starter" and source.name.casefold() not in own | inherited else report_copy.free_name(
        source.name, own | inherited,
    )
    clean = (name or "").strip() or suggested
    if len(clean) > report_layouts.MAX_NAME_CHARS:
        raise ValueError(f"A name is 1 to {report_layouts.MAX_NAME_CHARS} characters.")
    plan = DuplicatePlan(
        kind=kind, source_name=source.name, origin=source.origin, name=clean, suggested_name=suggested,
        name_taken=clean.casefold() in own, shadows=clean.casefold() in inherited,
    )
    if plan.shadows:
        plan.warnings.append("The copy will shadow a report of the same name that this project inherits.")
    folders = {f.path.casefold() for f in report_folder_store.list_folders(db, organization_id, dest)}
    if source.folder and source.folder.casefold() not in folders:
        plan.warnings.append(f'The folder "{source.folder}" does not exist here, so the copy is filed at the top level.')
    else:
        plan.folder = source.folder
    entry = _source_entry(db, source)
    entry["name"], entry["folder"] = clean, plan.folder

    needed: list[dict[str, Any]] = []
    assets: dict[uuid.UUID, FileAsset] = {}
    if source.kind != "pack":
        tree = entry["versions"][-1]["tree"] if entry["versions"] else {}
        if dest is not None:
            plan.warnings += report_copy.layout_warnings(db, tree, dest, False, pictures=False)
        needed, assets = _pictures(db, entry, organization_id, source.layout.project_id if source.layout else None, dest.id if dest else None)
        if dest is None:
            plan.blocked_images = sorted({e["filename"] for e in needed})
        elif needed:
            plan.warnings.append(f"{len(needed)} picture(s) from another project's library are copied into this project's library.")
    else:
        plan.warnings += _pack_warnings(db, entry, organization_id, dest)

    if dry_run:
        return plan
    if plan.name_taken:
        raise (report_packs.PackNameTakenError if kind == "pack" else report_layouts.LayoutNameTakenError)(
            f'A {"pack" if kind == "pack" else "layout"} called "{clean}" already exists here.'
        )
    if plan.blocked_images:
        raise DuplicateBlockedError(
            "A picture from a project library cannot be shared with the whole organisation. Replace it in the layout first.",
            plan.blocked_images,
        )
    notes = BundleImportWarnings()
    dest_project_id = dest.id if dest else None
    if source.kind == "pack":
        created = report_pack_bundle.import_pack_entry(
            db, entry, organization_id=organization_id, project_id=dest_project_id, actor=caller, warnings=notes,
        )
        new_id = created.id if created else None
    else:
        mapping = report_layout_bundle.import_images(
            db, needed, {e["file_ref"]: read_file(assets[uuid.UUID(e["id"])]) for e in needed},
            organization_id=organization_id, project_id=dest_project_id, actor=caller, warnings=notes,
        )
        new_id = report_layout_bundle.import_layout_entry(
            db, entry, organization_id=organization_id, project_id=dest_project_id, actor=caller, warnings=notes, images=mapping,
        )
    if new_id is None:
        raise ValueError(" ".join(notes.messages) or "The copy could not be created.")
    plan.warnings += notes.messages
    plan.new_id = new_id
    log_event(
        db, entity_type="report_pack" if kind == "pack" else "report_layout", entity_id=new_id, action="duplicated", actor_id=caller.id,
        organization_id=organization_id, project_id=dest_project_id,
        detail={
            "source_kind": kind, "source_id": str(source_id) if source_id else None, "starter": starter_key,
            "tier": target, "source_project_id": str(project.id) if project else None,
        },
    )
    return plan


__all__ = [
    "DuplicateBlockedError", "DuplicatePlan", "DuplicateRefusedError", "Kind", "Tier", "duplicate", "starter_sources",
]
