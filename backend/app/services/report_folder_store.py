"""
Module: services.report_folder_store

The folders of the Reports picker that a scope can choose from, and adding, renaming and deleting the ones it owns.

Responsibilities:
- `list_folders`: every folder a scope can file a report under: the folders it (and, for a project, its ancestors and
  the organisation) added, plus every folder some layout, pack or placement it can see already uses, with the levels
  above each. Each is flagged `own` when this scope can change what is in it.
- `add_folder`: record a folder so it exists before anything is filed in it.
- `rename_folder` / `delete_folder`: change a folder and everything this scope owns at or below it in one step.

Design decisions:
- **A folder is still a label** (`services.report_folders`); `ReportFolder` rows only keep a folder that nothing is filed
  in yet. The listing is the union of both, so a folder in use can never be missing.
- **Nesting is additive** (**Decided by: Agent**): a project sees its own folders, its ancestors' and the
  organisation's together, as it does layouts and packs. The action-type rule ("own rows, else the nearest ancestor's")
  would make a child's first folder hide every inherited one, which is wrong for a vocabulary of labels.
- **A scope changes only what it owns**: its own folder rows, layouts, packs and placements. A folder an ancestor or the
  organisation owns can be filed into but not renamed or deleted here (404 for an unchanged folder).
- **Delete never deletes a report** (**Decided by: User**): what was filed in the folder, and in its sub-folders, moves
  up one level (to the top level from a first-level folder) and the counts are returned. Rename keeps the parent and
  changes the last level, and refuses a name another folder already has.
- A change is one audit event with paths and counts, never record content.

Dependencies: `models.report_folder`, `services.report_folders`, `services.report_layout_scope`,
`services.report_pack_scope`, `services.report_placements`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_folder import ReportFolder
from app.models.report_layout import ReportLayout
from app.models.report_pack import ReportPack
from app.models.report_placement import ReportPlacement
from app.services import report_layout_scope, report_pack_scope, report_placements
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids
from app.services.report_folders import FOLDER_SEPARATOR, clean_folder


class FolderError(ValueError):
    """A folder that cannot be added, renamed or deleted (empty, invalid, a duplicate, or not this scope's)."""


class FolderExists(FolderError):
    """The scope already lists a folder with that path."""


class FolderNotOwned(FolderError):
    """The folder is not listed for the scope, or only an ancestor or the organisation owns what is in it."""


@dataclass
class FolderInfo:
    """One folder a scope can file under.

    Attributes:
        path: The folder path.
        own: Whether this scope owns something at or below it (a folder row, a layout, a pack or a placement), so it can
            rename or delete it.
    """

    path: str
    own: bool = False


@dataclass
class FolderChange:
    """What a rename or delete moved (paths of this scope's own rows only)."""

    layouts: int = 0
    packs: int = 0
    placements: int = 0
    folders: int = 0
    paths: dict[str, str] = field(default_factory=dict)


def parent_of(path: str) -> str:
    """The path one level up (`""` for a first-level folder)."""
    return path.rsplit(FOLDER_SEPARATOR, 1)[0] if FOLDER_SEPARATOR in path else ""


def _is_under(folder: str, path: str) -> bool:
    """Whether `folder` is `path` or inside it (case-insensitive)."""
    f, p = folder.lower(), path.lower()
    return f == p or f.startswith(p + FOLDER_SEPARATOR)


def _replace_prefix(folder: str, path: str, new_path: str) -> str:
    """`folder` with its leading `path` replaced by `new_path` (`""` collapses the separator)."""
    rest = folder[len(path):].lstrip(FOLDER_SEPARATOR)
    return FOLDER_SEPARATOR.join(part for part in (new_path, rest) if part)


def _with_ancestors(path: str) -> list[str]:
    levels = path.split(FOLDER_SEPARATOR)
    return [FOLDER_SEPARATOR.join(levels[: i + 1]) for i in range(len(levels))]


def _scope_rows(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None):
    """This scope's own layouts, packs, placements and folder rows."""
    def owned(model):
        return (model.project_id.is_(None) if project_id is None else model.project_id == project_id)

    layouts = list(db.scalars(select(ReportLayout).where(ReportLayout.organization_id == organization_id, owned(ReportLayout))))
    packs = list(db.scalars(select(ReportPack).where(ReportPack.organization_id == organization_id, owned(ReportPack))))
    placements = list(db.scalars(select(ReportPlacement).where(ReportPlacement.organization_id == organization_id, owned(ReportPlacement))))
    folders = list(db.scalars(select(ReportFolder).where(ReportFolder.organization_id == organization_id, owned(ReportFolder))))
    return layouts, packs, placements, folders


def _visible_paths(db: Session, organization_id: uuid.UUID, project: Project | None) -> list[str]:
    """Every folder path a scope can see, before tidying into a tree."""
    paths: list[str] = []
    if project is None:
        paths += [r.folder for r in report_layout_scope.list_org_layouts(db, organization_id)]
        paths += [r.folder for r in report_pack_scope.list_org_packs(db, organization_id)]
        paths += [r.folder for r in report_placements.resolve_for_organization(db, organization_id).values() if r.folder]
        paths += [f.path for f in db.scalars(select(ReportFolder).where(
            ReportFolder.organization_id == organization_id, ReportFolder.project_id.is_(None)))]
        return paths
    paths += [s.layout.folder for s in report_layout_scope.resolve_project_layouts(db, project)]
    paths += [s.pack.folder for s in report_pack_scope.resolve_project_packs(db, project)]
    paths += [r.folder for r in report_placements.resolve_for_project(db, project).values() if r.folder]
    chain = get_project_chain_ids(db, project.id)
    paths += [f.path for f in db.scalars(select(ReportFolder).where(
        ReportFolder.organization_id == organization_id,
        (ReportFolder.project_id.is_(None)) | (ReportFolder.project_id.in_(chain))))]
    return paths


def list_folders(db: Session, organization_id: uuid.UUID, project: Project | None) -> list[FolderInfo]:
    """The folders a scope can file under, sorted by path.

    Args:
        db: Active session.
        organization_id: The organisation.
        project: The project, or `None` for the organisation's own list.

    Returns:
        Each distinct folder (case-insensitively, the first spelling kept) and every level above it, with `own` set where
        this scope owns something at or below it.
    """
    layouts, packs, placements, folders = _scope_rows(db, organization_id, project.id if project else None)
    own_paths = [r.folder for r in layouts] + [r.folder for r in packs] + [r.folder or "" for r in placements] + [f.path for f in folders]
    seen: dict[str, str] = {}
    for raw in _visible_paths(db, organization_id, project):
        for path in _with_ancestors(raw) if raw else []:
            seen.setdefault(path.lower(), path)
    out = [
        FolderInfo(path=path, own=any(_is_under(own, path) for own in own_paths if own))
        for path in sorted(seen.values(), key=str.lower)
    ]
    return out


def _require_new_path(db: Session, organization_id: uuid.UUID, project: Project | None, path: str, *, ignore: str | None = None) -> None:
    taken = {f.path.lower() for f in list_folders(db, organization_id, project)}
    if ignore is not None:
        taken = {t for t in taken if not _is_under(t, ignore)}
    if path.lower() in taken:
        raise FolderExists("A folder with that name already exists here.")


def add_folder(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, path: str, actor_id: uuid.UUID | None,
) -> str:
    """Records a folder in this scope (changed, flushed, not committed).

    Args:
        db: Active session.
        organization_id: The organisation.
        project: The project, or `None` for the organisation's tier.
        path: The folder path to add (tidied here).
        actor_id: Who added it.

    Returns:
        The tidied path.

    Raises:
        FolderError: Empty, too deep or too long, or a folder the scope already lists.
    """
    try:
        tidy = clean_folder(path)
    except ValueError as exc:
        raise FolderError(str(exc)) from exc
    if not tidy:
        raise FolderError("Give the folder a name.")
    _require_new_path(db, organization_id, project, tidy)
    row = ReportFolder(organization_id=organization_id, project_id=project.id if project else None, path=tidy, created_by=actor_id)
    db.add(row)
    db.flush()
    log_event(
        db, entity_type="report_folder", entity_id=row.id, action="create", actor_id=actor_id,
        organization_id=organization_id, project_id=project.id if project else None, detail={"path": tidy},
    )
    return tidy


def _reshape(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, path: str, new_path: str | None, actor_id: uuid.UUID | None,
) -> FolderChange:
    """Moves everything this scope owns at or below `path` to `new_path` (`None` deletes the folder row itself)."""
    layouts, packs, placements, folder_rows = _scope_rows(db, organization_id, project.id if project else None)
    target = parent_of(path) if new_path is None else new_path
    change = FolderChange()
    for layout in layouts:
        if layout.folder and _is_under(layout.folder, path):
            layout.folder = _replace_prefix(layout.folder, path, target)
            change.layouts += 1
    for pack in packs:
        if pack.folder and _is_under(pack.folder, path):
            pack.folder = _replace_prefix(pack.folder, path, target)
            change.packs += 1
    for placement in placements:
        if placement.folder and _is_under(placement.folder, path):
            placement.folder = _replace_prefix(placement.folder, path, target)
            change.placements += 1
    kept: set[str] = set()
    for row in sorted(folder_rows, key=lambda r: len(r.path)):
        if not _is_under(row.path, path):
            kept.add(row.path.lower())
            continue
        moved = _replace_prefix(row.path, path, target)
        if (new_path is None and row.path.lower() == path.lower()) or not moved or moved.lower() in kept:
            db.delete(row)
        else:
            row.path = moved
            kept.add(moved.lower())
        change.folders += 1
    db.flush()
    return change


def rename_folder(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, path: str, name: str, actor_id: uuid.UUID | None,
) -> tuple[str, FolderChange]:
    """Renames the last level of a folder this scope owns, moving what is filed in it and below it.

    Args:
        db: Active session (changed, flushed, not committed).
        organization_id: The organisation.
        project: The project, or `None` for the organisation's tier.
        path: The folder to rename.
        name: Its new last-level name (no separator).
        actor_id: Who renamed it.

    Returns:
        The new path and what moved.

    Raises:
        FolderError: A folder this scope does not own, an unusable name, or a name a sibling already has.
    """
    old = next((f.path for f in list_folders(db, organization_id, project) if f.path.lower() == path.lower() and f.own), None)
    if old is None:
        raise FolderNotOwned("That folder is not one this scope can change.")
    if FOLDER_SEPARATOR in name:
        raise FolderError("A folder name cannot contain /.")
    try:
        new_path = clean_folder(FOLDER_SEPARATOR.join(p for p in (parent_of(old), name) if p))
    except ValueError as exc:
        raise FolderError(str(exc)) from exc
    if not name.strip():
        raise FolderError("Give the folder a name.")
    if new_path.lower() != old.lower():
        _require_new_path(db, organization_id, project, new_path, ignore=old)
    change = _reshape(db, organization_id=organization_id, project=project, path=old, new_path=new_path, actor_id=actor_id)
    log_event(
        db, entity_type="report_folder", entity_id=project.id if project else organization_id, action="rename", actor_id=actor_id,
        organization_id=organization_id, project_id=project.id if project else None,
        detail={"path": old, "new_path": new_path, "layouts": change.layouts, "packs": change.packs, "placements": change.placements},
    )
    return new_path, change


def delete_folder(
    db: Session, *, organization_id: uuid.UUID, project: Project | None, path: str, actor_id: uuid.UUID | None,
) -> FolderChange:
    """Deletes a folder this scope owns: what was filed at or below it moves up one level; no report is deleted.

    Args:
        db: Active session (changed, flushed, not committed).
        organization_id: The organisation.
        project: The project, or `None` for the organisation's tier.
        path: The folder to delete.
        actor_id: Who deleted it.

    Returns:
        What moved.

    Raises:
        FolderError: A folder this scope does not own.
    """
    old = next((f.path for f in list_folders(db, organization_id, project) if f.path.lower() == path.lower() and f.own), None)
    if old is None:
        raise FolderNotOwned("That folder is not one this scope can change.")
    change = _reshape(db, organization_id=organization_id, project=project, path=old, new_path=None, actor_id=actor_id)
    log_event(
        db, entity_type="report_folder", entity_id=project.id if project else organization_id, action="delete", actor_id=actor_id,
        organization_id=organization_id, project_id=project.id if project else None,
        detail={"path": old, "layouts": change.layouts, "packs": change.packs, "placements": change.placements},
    )
    return change
