"""
Module: services.report_copy

Copies report configuration from one project to another project of the same organisation: report layouts, report
packs (with their saved variable sets), the project's own report folders and its placements of module reports,
and the caller's own favourites of the copied reports.

Responsibilities:
- `plan_copy`: what a copy would create, rename, skip or leave out, with a warning for everything that does not carry
  cleanly. Writes nothing.
- `apply_copy`: runs the plan in the caller's transaction (the caller commits) and writes one audit event.

Design decisions:
- **One serialiser, not a second copier.** A layout or pack is turned into its project-bundle entry
  (`report_layout_bundle.layout_entry`, `report_pack_bundle.pack_entry`) and created in the target by the bundle's own
  importer (`import_layout_entry`, `import_pack_entry`), which validates the tree again and goes through the normal
  create path. A field added to the bundle therefore reaches the copy with no change here.
- **Latest version only.** The copy is version 1 of a new, independent layout or pack; the source keeps its history. A
  layout or pack inherited from an ancestor or the organisation is copied as the target's own editable copy.
- **Never a silent replace.** A name the target project already owns is renamed "<name> (copy)", "(copy 2)", ... or
  skipped (the caller's choice); an existing folder or placement is left as it is. Replacing is not offered.
- **Pictures.** An organisation picture stays a reference; a project picture is copied into the target project's
  library (once, however many copied layouts use it), never referenced across the project boundary.
- **Packs follow the layouts they name.** A pack entry that names a copied layout is re-pointed at the copy's (possibly
  renamed) name; one that names a project-owned layout that is not part of the copy is reported as left out, since the
  target may have no layout of that name.
- **Carries configuration only.** Layout definitions, pack definitions, folder paths, placements, variable values and
  picture files; never record content. The audit event holds counts and ids, never layout text or names.
- Favourites are per person: only the caller's own are carried, by adding the copies' keys to their stored list.
- The caller's gates (read and manage the source, manage the target, one organisation) are checked by the route; this
  module trusts them and only checks that both projects belong to one organisation.

Dependencies: `services.report_layout_bundle`, `services.report_pack_bundle`, `services.report_layout_scope`,
`services.report_pack_scope`, `services.report_folder_store`, `services.report_placements`, `services.ui_preferences`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_folder import ReportFolder
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack
from app.models.report_placement import ReportPlacement
from app.models.user import User
from app.modules.registry import get_all_reports, report_enabled_for_project
from app.services import (
    report_folder_store,
    report_layout_bundle,
    report_layout_scope,
    report_layouts,
    report_pack_bundle,
    report_pack_scope,
    report_pack_sets,
    report_packs,
    report_placements,
)
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.files import read_file
from app.services.report_images import image_nodes
from app.services.report_layouts import MAX_NAME_CHARS
from app.services.report_variables import stale_value_warnings
from app.services.report_widgets import find_widget, widget_available
from app.services.ui_preferences import merge_ui_preferences

OnConflict = Literal["rename", "skip"]
Kind = Literal["layout", "pack", "folder", "placement"]
Action = Literal["create", "rename", "skip", "exists", "left_out"]

MAX_ITEMS = 100
FAVOURITES_KEY = "report_favourites"
MAX_FAVOURITES = 100


class CopyRefusedError(LookupError):
    """A selected item is not in the source project (or not one the copy may take); nothing is copied."""


@dataclass(frozen=True)
class CopySelection:
    """What to copy.

    Attributes:
        layout_ids: Layouts the source project can reach (its own, an ancestor's or the organisation's).
        pack_ids: Packs the source project can reach.
        folders: Folder paths the source project itself owns.
        placement_keys: Module or platform report keys (`report:<module>.<key>`) the source project itself places.
        favourites: Whether to carry the caller's own favourites of the copied layouts and packs.
    """

    layout_ids: tuple[uuid.UUID, ...] = ()
    pack_ids: tuple[uuid.UUID, ...] = ()
    folders: tuple[str, ...] = ()
    placement_keys: tuple[str, ...] = ()
    favourites: bool = True


@dataclass
class CopyItem:
    """One selected item and what the copy does with it.

    Attributes:
        kind: `layout`, `pack`, `folder` or `placement`.
        source_id: The layout or pack id, else the folder path or placement key.
        name: The item's name in the source (the path or key for a folder or placement).
        origin: `project`, `ancestor` or `organization` for a layout or pack; `project` otherwise.
        action: `create`, `rename` (created under `new_name`), `skip` (name taken and the caller chose skip), `exists`
            (a folder or placement the target already has) or `left_out` (cannot be carried).
        new_name: The name the copy gets.
        warnings: What does not carry cleanly.
        new_id: The created layout or pack, set once applied.
    """

    kind: Kind
    source_id: str
    name: str
    origin: str
    action: Action
    new_name: str
    warnings: list[str] = field(default_factory=list)
    new_id: uuid.UUID | None = None


@dataclass
class CopyPlan:
    """The outcome of a plan (or, once applied, of the copy).

    Attributes:
        items: One entry per selected item, in selection order (layouts, packs, folders, placements).
        warnings: Notes that belong to no single item.
        favourites_carried: How many of the caller's favourites were added for the copies (after `apply_copy`).
    """

    items: list[CopyItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    favourites_carried: int = 0

    def count(self, kind: Kind, *actions: Action) -> int:
        """How many items of `kind` ended in one of `actions`."""
        return sum(1 for i in self.items if i.kind == kind and i.action in actions)


def free_name(name: str, taken: set[str]) -> str:
    """`<name> (copy)`, `(copy 2)`, ... the first not in `taken` (lower-cased), trimmed to the name limit."""
    for n in range(1, 1000):
        suffix = " (copy)" if n == 1 else f" (copy {n})"
        candidate = f"{name[: MAX_NAME_CHARS - len(suffix)]}{suffix}"
        if candidate.casefold() not in taken:
            return candidate
    raise CopyRefusedError("No free name was found for the copy.")


def _widget_keys(node: Any) -> set[str]:
    """Every `widget` block's key in a tree (any depth)."""
    found: set[str] = set()
    if isinstance(node, dict):
        if node.get("type") == "widget" and isinstance(node.get("key"), str):
            found.add(node["key"])
        for value in node.values():
            found |= _widget_keys(value)
    elif isinstance(node, list):
        for value in node:
            found |= _widget_keys(value)
    return found


def _check_same_organisation(source: Project, target: Project) -> None:
    if source.organization_id != target.organization_id:
        raise CopyRefusedError("The source project is not in this organisation.")
    if source.id == target.id:
        raise ValueError("Choose a different project to copy into.")


def layout_warnings(db: Session, tree: dict[str, Any], target: Project, shadows: bool, *, pictures: bool = True) -> list[str]:
    """What does not carry cleanly for one layout tree (the target's modules, pictures, option sources, shadowing).

    Args:
        db: Active session (read only).
        tree: The layout tree being copied.
        target: The project the copy lands in.
        shadows: Whether the copy's name matches a report the target inherits.
        pictures: Whether to note the project-library pictures that are copied (a caller that reuses them says its own).

    Returns:
        One sentence per thing that does not carry cleanly; empty when it all does.
    """
    warnings: list[str] = []
    if shadows:
        warnings.append("It will shadow a report of the same name that the target project inherits.")
    off = sorted({
        w.module_name for key in _widget_keys(tree)
        if (w := find_widget(key)) is not None and not widget_available(db, target, w)
    })
    if off:
        warnings.append(
            f"It uses report parts of modules that are off in the target project: {', '.join(off)}. "
            "They stay in the layout and show nothing there."
        )
    own_pictures = [
        node for _, node in image_nodes(tree)
        if (asset := _asset(db, node.get("file"))) is not None and not asset.is_org_resource
    ]
    if own_pictures and pictures:
        warnings.append(f"{len(own_pictures)} picture(s) from a project library are copied into the target project's library.")
    declared = tree.get("variables")
    if isinstance(declared, list):
        sourced = [d for d in declared if isinstance(d, dict) and d.get("source") and d.get("default") is not None and "name" in d]
        defaults = {d["name"]: d["default"] for d in sourced}
        if defaults and (stale := stale_value_warnings(db, sourced, defaults, [target.id])):
            warnings.append(
                f"{len(stale)} variable default(s) are not among the target project's current options and may match nothing there."
            )
    return warnings


def _drain(notes: BundleImportWarnings) -> list[str]:
    """The importer's warnings so far, clearing them (so each item reports only its own)."""
    messages, notes.messages = notes.messages, []
    return messages


def _asset(db: Session, raw: Any) -> FileAsset | None:
    try:
        return db.get(FileAsset, uuid.UUID(str(raw)))
    except ValueError:
        return None


def _target_names(db: Session, model: type[ReportLayout] | type[ReportPack], project: Project) -> set[str]:
    return {n.casefold() for n in db.scalars(select(model.name).where(model.project_id == project.id))}


def plan_copy(
    db: Session, *, source: Project, target: Project, caller: User, selection: CopySelection, on_conflict: OnConflict,
) -> CopyPlan:
    """What copying `selection` from `source` into `target` would do. Writes nothing.

    Args:
        db: Active session (read only).
        source: The project copied from.
        target: The project copied into (same organisation).
        caller: The person copying (their favourites are the ones carried).
        selection: What to copy.
        on_conflict: `rename` or `skip` for a layout or pack whose name the target already owns.

    Returns:
        The plan; an item's `action` says what happens to it.

    Raises:
        CopyRefusedError: Different organisations, or an item the source does not have (a layout or pack it cannot
            reach or has hidden, a placement it does not hold).
        ValueError: The same project twice, or more than `MAX_ITEMS` items.
    """
    _check_same_organisation(source, target)
    if len(selection.layout_ids) + len(selection.pack_ids) + len(selection.folders) + len(selection.placement_keys) > MAX_ITEMS:
        raise ValueError(f"Copy at most {MAX_ITEMS} items at a time.")
    plan = CopyPlan()

    # Layouts
    source_layouts = {s.layout.id: s for s in report_layout_scope.resolve_project_layouts(db, source)}
    target_inherited = {
        s.layout.name.casefold() for s in report_layout_scope.resolve_project_layouts(db, target) if s.origin != "project"
    }
    taken = _target_names(db, ReportLayout, target)
    for layout_id in dict.fromkeys(selection.layout_ids):
        scoped = source_layouts.get(layout_id)
        if scoped is None or scoped.hidden:
            raise CopyRefusedError("A selected report layout is not available in the source project.")
        layout = scoped.layout
        item = CopyItem("layout", str(layout.id), layout.name, scoped.origin, "create", layout.name)
        if layout.name.casefold() in taken:
            if on_conflict == "skip":
                item.action = "skip"
                item.warnings.append("The target project already has a layout with this name.")
            else:
                item.action, item.new_name = "rename", free_name(layout.name, taken)
        if item.action in ("create", "rename"):
            taken.add(item.new_name.casefold())
            version = report_layouts.get_version(db, layout.id, layout.current_version)
            item.warnings = layout_warnings(
                db, version.tree if version else {}, target, item.new_name.casefold() in target_inherited,
            )
        plan.items.append(item)

    # Packs
    source_packs = {s.pack.id: s for s in report_pack_scope.resolve_project_packs(db, source)}
    taken = _target_names(db, ReportPack, target)
    copied_layout_ids = {uuid.UUID(i.source_id) for i in plan.items if i.kind == "layout" and i.action in ("create", "rename")}
    for pack_id in dict.fromkeys(selection.pack_ids):
        scoped_pack = source_packs.get(pack_id)
        if scoped_pack is None or scoped_pack.hidden:
            raise CopyRefusedError("A selected report pack is not available in the source project.")
        pack = scoped_pack.pack
        item = CopyItem("pack", str(pack.id), pack.name, scoped_pack.origin, "create", pack.name)
        if pack.name.casefold() in taken:
            if on_conflict == "skip":
                item.action = "skip"
                item.warnings.append("The target project already has a pack with this name.")
            else:
                item.action, item.new_name = "rename", free_name(pack.name, taken)
        if item.action in ("create", "rename"):
            taken.add(item.new_name.casefold())
            item.warnings = _pack_warnings(db, pack, source, target, source_layouts, copied_layout_ids)
        plan.items.append(item)

    # Folders and module-report placements the source project owns itself.
    own_folders = set(db.scalars(select(ReportFolder.path).where(ReportFolder.project_id == source.id)))
    target_folders = {f.path for f in report_folder_store.list_folders(db, target.organization_id, target)}
    for path in dict.fromkeys(selection.folders):
        if path not in own_folders:  # a name only reports are filed under: they carry it, so there is no folder to copy
            continue
        plan.items.append(CopyItem("folder", path, path, "project", "exists" if path in target_folders else "create", path))
    own_placements = {
        r.report_key: r for r in db.scalars(select(ReportPlacement).where(ReportPlacement.project_id == source.id))
    }
    target_placements = set(db.scalars(select(ReportPlacement.report_key).where(ReportPlacement.project_id == target.id)))
    for key in dict.fromkeys(selection.placement_keys):
        if not report_placements.is_hideable(key) or key not in own_placements:
            raise CopyRefusedError("A selected placement is not one the source project holds.")
        plan.items.append(CopyItem("placement", key, key, "project", "exists" if key in target_placements else "create", key))
    return plan


def _pack_warnings(
    db: Session, pack: ReportPack, source: Project, target: Project, source_layouts: dict[uuid.UUID, Any],
    copied_layout_ids: set[uuid.UUID],
) -> list[str]:
    """Pack entries that will not resolve in the target: a project-owned layout left behind, a module that is off there."""
    version = report_packs.current_version(db, pack)
    by_name = {s.layout.name.casefold(): s for s in source_layouts.values()}
    left_behind: list[str] = []
    off: set[str] = set()
    reports = {(mk, d.key): d for mk, d in get_all_reports()}
    for entry in version.definition.get("entries", []):
        if entry.get("kind") == "layout":
            scoped = by_name.get(str(entry.get("name", "")).casefold())
            if scoped is not None and scoped.origin != "organization" and scoped.layout.id not in copied_layout_ids:
                left_behind.append(scoped.layout.name)
        elif entry.get("kind") == "report":
            definition = reports.get((entry.get("module_key"), entry.get("report")))
            if definition is not None and not report_enabled_for_project(db, target.id, entry["module_key"], definition):
                off.add(str(entry["module_key"]))
    warnings: list[str] = []
    if left_behind:
        warnings.append(
            f"Entries use layouts that are not part of this copy: {', '.join(sorted(set(left_behind)))}. "
            "They run in the target only if it has a layout of that name."
        )
    if off:
        warnings.append(f"Entries use reports of modules that are off in the target project: {', '.join(sorted(off))}.")
    return warnings


def _effective_folder(db: Session, key: str, own: str, placed: dict[str, Any]) -> str:
    resolved = placed.get(key)
    return resolved.folder if resolved is not None and resolved.folder is not None else own


def apply_copy(
    db: Session, *, source: Project, target: Project, caller: User, selection: CopySelection, on_conflict: OnConflict,
) -> CopyPlan:
    """Plans, then performs the copy in the caller's transaction (flushed, not committed), with one audit event.

    Returns:
        The plan with `new_id` filled for each created layout or pack, an item that could not be created marked
        `left_out` (with the reason in `warnings`), and `favourites_carried`.

    Raises:
        CopyRefusedError: As `plan_copy`; nothing was written.
        ValueError: As `plan_copy`.
    """
    plan = plan_copy(db, source=source, target=target, caller=caller, selection=selection, on_conflict=on_conflict)
    placed = report_placements.resolve_for_project(db, source)
    org_id = target.organization_id
    notes = BundleImportWarnings()

    for item in plan.items:
        if item.kind == "folder" and item.action == "create":
            try:
                report_folder_store.add_folder(db, organization_id=org_id, project=target, path=item.source_id, actor_id=caller.id)
            except report_folder_store.FolderExists:
                item.action = "exists"
            except report_folder_store.FolderError as exc:
                item.action, item.warnings = "left_out", [str(exc)]

    # Layouts, then packs (which name them). `renamed` maps a copied layout's old name to its new one.
    images: dict[str, str] = {}
    renamed: dict[str, str] = {}
    key_map: dict[str, str] = {}
    source_layouts = {s.layout.id: s for s in report_layout_scope.resolve_project_layouts(db, source)}
    for item in plan.items:
        if item.kind != "layout" or item.action not in ("create", "rename"):
            continue
        layout = source_layouts[uuid.UUID(item.source_id)].layout
        entry = report_layout_bundle.layout_entry(db, layout, latest_only=True)
        entry["name"] = item.new_name
        entry["folder"] = _effective_folder(db, report_placements.layout_key(layout.id), layout.folder, placed)
        assets: dict[uuid.UUID, FileAsset] = {}
        fresh = [
            e for e in report_layout_bundle.image_entries(db, [entry], org_id, layout.project_id, assets)
            if e["id"] not in images
        ]
        images.update(report_layout_bundle.import_images(
            db, fresh, {e["file_ref"]: read_file(assets[uuid.UUID(e["id"])]) for e in fresh},
            organization_id=org_id, project_id=target.id, actor=caller, warnings=notes,
        ))
        new_id = report_layout_bundle.import_layout_entry(
            db, entry, organization_id=org_id, project_id=target.id, actor=caller, warnings=notes, images=images,
        )
        if new_id is None:
            item.action, item.warnings = "left_out", item.warnings + _drain(notes)
            continue
        item.new_id = new_id
        item.warnings += _drain(notes)
        renamed[layout.name.casefold()] = item.new_name
        key_map[report_placements.layout_key(layout.id)] = report_placements.layout_key(new_id)

    source_packs = {s.pack.id: s for s in report_pack_scope.resolve_project_packs(db, source)}
    for item in plan.items:
        if item.kind != "pack" or item.action not in ("create", "rename"):
            continue
        pack = source_packs[uuid.UUID(item.source_id)].pack
        sets = [(e.row.name, e.effective) for e in report_pack_sets.effective_sets(db, pack, source)]
        entry = report_pack_bundle.pack_entry(db, pack, latest_only=True, sets=sets)
        entry["name"] = item.new_name
        entry["folder"] = _effective_folder(db, report_placements.pack_key(pack.id), pack.folder, placed)
        for version in entry["versions"]:
            for e in version["definition"].get("entries", []):
                if e.get("kind") == "layout" and str(e.get("name", "")).casefold() in renamed:
                    e["name"] = renamed[str(e["name"]).casefold()]
        new_pack = report_pack_bundle.import_pack_entry(
            db, entry, organization_id=org_id, project_id=target.id, actor=caller, warnings=notes,
        )
        if new_pack is None:
            item.action, item.warnings = "left_out", item.warnings + _drain(notes)
            continue
        item.new_id = new_pack.id
        item.warnings += _drain(notes)
        key_map[report_placements.pack_key(pack.id)] = report_placements.pack_key(new_pack.id)

    for item in plan.items:
        if item.kind == "placement" and item.action == "create":
            row = db.scalars(select(ReportPlacement).where(
                ReportPlacement.project_id == source.id, ReportPlacement.report_key == item.source_id)).one()
            try:
                report_placements.set_placement(
                    db, organization_id=org_id, project_id=target.id, key=item.source_id, folder=row.folder, hidden=row.hidden,
                    valid_keys=None, actor_id=caller.id,
                )
            except report_placements.PlacementError as exc:
                item.action, item.warnings = "left_out", [str(exc)]

    if selection.favourites and key_map:
        plan.favourites_carried = _carry_favourites(db, caller, key_map, plan)

    log_event(
        db, entity_type="project", entity_id=target.id, action="reports_copied", actor_id=caller.id,
        organization_id=org_id, project_id=target.id,
        detail={
            "source_project_id": str(source.id),
            "layouts": plan.count("layout", "create", "rename"), "packs": plan.count("pack", "create", "rename"),
            "folders": plan.count("folder", "create"), "placements": plan.count("placement", "create"),
            "skipped": sum(1 for i in plan.items if i.action in ("skip", "exists", "left_out")),
            "favourites": plan.favourites_carried, "on_conflict": on_conflict,
        },
    )
    return plan


def _carry_favourites(db: Session, caller: User, key_map: dict[str, str], plan: CopyPlan) -> int:
    """Adds the copies' keys to the caller's favourites for each copied report they had starred; returns how many."""
    current = caller.ui_preferences.get(FAVOURITES_KEY)
    starred = [k for k in current if isinstance(k, str)] if isinstance(current, list) else []
    wanted = [new for old, new in key_map.items() if old in starred and new not in starred]
    if not wanted:
        return 0
    room = max(0, MAX_FAVOURITES - len(starred))
    if len(wanted) > room:
        plan.warnings.append("Some favourites were not carried: the list of favourites is full.")
        wanted = wanted[:room]
    if not wanted:
        return 0
    try:
        caller.ui_preferences = merge_ui_preferences(caller.ui_preferences, {FAVOURITES_KEY: [*starred, *wanted]})
    except ValueError:
        plan.warnings.append("Favourites were not carried: the stored preferences are full.")
        return 0
    db.flush()
    return len(wanted)


__all__ = [
    "MAX_ITEMS", "CopyItem", "CopyPlan", "CopyRefusedError", "CopySelection", "OnConflict", "apply_copy", "free_name", "layout_warnings",
    "plan_copy",
]
