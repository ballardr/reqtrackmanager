"""
Module: modules.architecture.folders

Folders: a tree per kind (elements, connections, diagrams) that organises a list. Navigation only.

A folder belongs to a project or to the organisation (`records.ElementOwner`); the organisation has element folders
only. A record is in one folder or none (the top level). A folder has no code, is not linkable and means nothing to the
roll-up, the resolver or a report.

Responsibilities:
- Create, rename, move and delete folders (no cycle, depth cap 12, a unique name among siblings, no `/` in a name).
- Check that a record's folder is its owner's folder of the right kind (`usable_folder`).
- Move records between folders in bulk, and give a record's folder as a path (`paths_for`, `resolve_path`) for the
  lists, the CSV and the bundles.
- Write one audit event per change holding ids, counts and field names, never a name.

Design decisions:
- Deleting a folder moves its records and sub-folders to its parent; nothing is deleted with it. A sub-folder whose
  name would clash in the parent stops the delete (rename it first) rather than being merged or renamed silently.
- Paths are read in bulk: every folder of the owners involved is read once, so a list's cost does not grow with its rows.
- A folder is per-project content, not a vocabulary, so a child project does not fall back to an ancestor's folders.

Dependencies: this module's models and `records` (owner, rule errors, the record update paths); core `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.architecture.enums import FolderKind
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitectureFolder,
)
from app.modules.architecture.records import ElementOwner, RuleError
from app.modules.architecture.schemas import FolderCreate, FolderOut, FolderUpdate
from app.services.audit import log_event

FOLDER_ENTITY_TYPE = "architecture_folder"
#: The deepest a folder tree goes (the same cap as an element tree).
MAX_DEPTH = 12
#: Separates a folder's names in a path; a name never contains it.
PATH_SEPARATOR = "/"

#: The record table each kind of folder organises.
RECORD_MODELS: dict[str, Any] = {
    FolderKind.ELEMENT.value: ArchitectureElement,
    FolderKind.CONNECTION.value: ArchitectureConnection,
    FolderKind.DIAGRAM.value: ArchitectureDiagram,
}


def _owner_filter(owner: ElementOwner) -> ColumnElement[bool]:
    """The condition selecting the owner's folders."""
    if owner.project is not None:
        return ArchitectureFolder.project_id == owner.project.id
    return ArchitectureFolder.organization_id == owner.organization_id


def _audit(db: Session, folder_id: uuid.UUID, action: str, actor: User, owner: ElementOwner, **detail: Any) -> None:
    """Writes the audit event for a change to a folder: ids, counts and field names only."""
    log_event(
        db, entity_type=FOLDER_ENTITY_TYPE, entity_id=folder_id, action=action, actor_id=actor.id,
        detail={k: v for k, v in detail.items() if v not in (None, [], "")} or None, **owner.place,
    )


def check_kind(owner: ElementOwner, kind: FolderKind | str) -> str:
    """The kind's value, after checking the owner may have folders of it (the organisation: elements only).

    Raises:
        RuleError: 400 for an organisation's connection or diagram folder.
    """
    value = kind.value if isinstance(kind, FolderKind) else kind
    if owner.project is None and value != FolderKind.ELEMENT.value:
        raise RuleError("An organisation has element folders only.", 400)
    return value


def get_folder(
    db: Session, owner: ElementOwner, folder_id: uuid.UUID, *, kind: str | None = None, lock: bool = False,
) -> ArchitectureFolder:
    """The folder the owner owns (of `kind`, when given); `lock` takes a row lock for a write.

    Raises:
        RuleError: 404 if it does not exist, another owner owns it or it is of another kind.
    """
    query = select(ArchitectureFolder).where(ArchitectureFolder.id == folder_id, _owner_filter(owner))
    if kind is not None:
        query = query.where(ArchitectureFolder.kind == kind)
    folder = db.scalar(query.with_for_update() if lock else query)
    if folder is None:
        raise RuleError("Folder not found.", 404)
    return folder


def usable_folder(db: Session, owner: ElementOwner, kind: FolderKind | str, folder_id: uuid.UUID) -> None:
    """Checks that a record of `kind` may be put in the folder: the owner's own folder of that kind.

    Raises:
        RuleError: 400 otherwise (another owner's folder looks the same as one that does not exist).
    """
    value = kind.value if isinstance(kind, FolderKind) else kind
    try:
        get_folder(db, owner, folder_id, kind=value)
    except RuleError as exc:
        raise RuleError("That folder is not available here.", 400) from exc


def list_folders(db: Session, owner: ElementOwner, kind: str | None = None) -> list[ArchitectureFolder]:
    """The owner's folders (of `kind`, when given), in tree order within each parent."""
    query = select(ArchitectureFolder).where(_owner_filter(owner))
    if kind is not None:
        query = query.where(ArchitectureFolder.kind == kind)
    return list(db.scalars(query.order_by(ArchitectureFolder.sort_order, func.lower(ArchitectureFolder.name))))


def _check_name(name: str) -> str:
    """The trimmed name.

    Raises:
        RuleError: 400 if it is blank or contains the path separator.
    """
    clean = name.strip()
    if not clean:
        raise RuleError("A folder needs a name.", 400)
    if PATH_SEPARATOR in clean:
        raise RuleError(f"A folder name cannot contain '{PATH_SEPARATOR}'.", 400)
    return clean


def _siblings_use(
    db: Session, owner: ElementOwner, kind: str, parent_id: uuid.UUID | None, name: str, exclude_id: uuid.UUID | None = None,
) -> bool:
    """Whether another folder of the same kind under the same parent already has `name` (ignoring case)."""
    query = select(ArchitectureFolder.id).where(
        _owner_filter(owner), ArchitectureFolder.kind == kind, func.lower(ArchitectureFolder.name) == name.lower(),
        ArchitectureFolder.parent_id.is_(None) if parent_id is None else ArchitectureFolder.parent_id == parent_id,
    )
    if exclude_id is not None:
        query = query.where(ArchitectureFolder.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def _tree(rows: Iterable[ArchitectureFolder]) -> tuple[dict[uuid.UUID, uuid.UUID | None], dict[uuid.UUID, list[uuid.UUID]]]:
    """`(parent of each folder, children of each folder)` for `rows`."""
    parents: dict[uuid.UUID, uuid.UUID | None] = {}
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for row in rows:
        parents[row.id] = row.parent_id
        if row.parent_id is not None:
            children[row.parent_id].append(row.id)
    return parents, children


def _depth(parents: dict[uuid.UUID, uuid.UUID | None], folder_id: uuid.UUID) -> int:
    """Levels from the top to the folder, counting the folder itself (a top-level folder is 1)."""
    depth, seen = 0, set()
    current: uuid.UUID | None = folder_id
    while current is not None and current not in seen:
        seen.add(current)
        depth += 1
        current = parents.get(current)
    return depth


def _height(children: dict[uuid.UUID, list[uuid.UUID]], folder_id: uuid.UUID) -> int:
    """Levels in the subtree under the folder, counting the folder itself."""
    deepest, frontier = 1, [folder_id]
    seen = {folder_id}
    while frontier:
        frontier = [c for f in frontier for c in children.get(f, ()) if c not in seen]
        seen.update(frontier)
        if frontier:
            deepest += 1
    return deepest


def _check_parent(db: Session, owner: ElementOwner, kind: str, folder: ArchitectureFolder | None, parent_id: uuid.UUID) -> None:
    """Checks `parent_id` may hold `folder` (a new folder when `None`): the owner's folder of the kind, no cycle and
    within the depth cap.

    Raises:
        RuleError: 400 otherwise.
    """
    try:
        get_folder(db, owner, parent_id, kind=kind)
    except RuleError as exc:
        raise RuleError("That parent folder is not available here.", 400) from exc
    parents, children = _tree(list_folders(db, owner, kind))
    if folder is not None:
        subtree, frontier = {folder.id}, [folder.id]
        while frontier:
            frontier = [c for f in frontier for c in children.get(f, ()) if c not in subtree]
            subtree.update(frontier)
        if parent_id in subtree:
            raise RuleError("A folder cannot be moved into itself or one of its sub-folders.", 400)
    below = _height(children, folder.id) if folder is not None else 1
    if _depth(parents, parent_id) + below > MAX_DEPTH:
        raise RuleError(f"Folders can be at most {MAX_DEPTH} levels deep.", 400)


def create_folder(
    db: Session, owner: ElementOwner, actor: User, kind: FolderKind, payload: FolderCreate,
) -> ArchitectureFolder:
    """Creates a folder of `kind`, last among its siblings. The caller commits.

    Raises:
        RuleError: 400 for an invalid name, kind or parent, or a name a sibling already uses.
    """
    kind_value = check_kind(owner, kind)
    name = _check_name(payload.name)
    if payload.parent_id is not None:
        _check_parent(db, owner, kind_value, None, payload.parent_id)
    if _siblings_use(db, owner, kind_value, payload.parent_id, name):
        raise RuleError("A folder with that name already exists here.", 400)
    last = db.scalar(
        select(func.max(ArchitectureFolder.sort_order)).where(
            _owner_filter(owner), ArchitectureFolder.kind == kind_value,
            ArchitectureFolder.parent_id.is_(None) if payload.parent_id is None else ArchitectureFolder.parent_id == payload.parent_id,
        )
    )
    folder = ArchitectureFolder(
        **owner.columns, kind=kind_value, name=name, parent_id=payload.parent_id,
        sort_order=0 if last is None else last + 1, creator_id=actor.id,
    )
    db.add(folder)
    db.flush()
    _audit(db, folder.id, "created", actor, owner, kind=kind_value)
    return folder


def update_folder(
    db: Session, owner: ElementOwner, actor: User, folder_id: uuid.UUID, payload: FolderUpdate,
) -> ArchitectureFolder:
    """Renames, moves or reorders a folder. The caller commits.

    Raises:
        RuleError: 404 if absent, 400 for an invalid name or parent (a cycle, too deep) or a clashing name.
    """
    folder = get_folder(db, owner, folder_id, lock=True)
    given = payload.model_fields_set
    changes: dict[str, Any] = {}
    if payload.name is not None and _check_name(payload.name) != folder.name:
        changes["name"] = _check_name(payload.name)
    if "parent_id" in given and payload.parent_id != folder.parent_id:
        if payload.parent_id is not None:
            _check_parent(db, owner, folder.kind, folder, payload.parent_id)
        changes["parent_id"] = payload.parent_id
    if payload.sort_order is not None and payload.sort_order != folder.sort_order:
        changes["sort_order"] = payload.sort_order
    if not changes:
        return folder
    name = changes.get("name", folder.name)
    parent_id = changes["parent_id"] if "parent_id" in changes else folder.parent_id
    if ("name" in changes or "parent_id" in changes) and _siblings_use(db, owner, folder.kind, parent_id, name, folder.id):
        raise RuleError("A folder with that name already exists here.", 400)
    for key, value in changes.items():
        setattr(folder, key, value)
    db.flush()
    _audit(db, folder.id, "moved" if sorted(changes) == ["parent_id"] else "updated", actor, owner, fields=sorted(changes))
    return folder


def delete_folder(db: Session, owner: ElementOwner, actor: User, folder_id: uuid.UUID) -> None:
    """Deletes a folder; its records and sub-folders move to its parent (nothing else is deleted). The caller commits.

    Raises:
        RuleError: 404 if absent, 400 if a sub-folder's name is already used in the parent.
    """
    folder = get_folder(db, owner, folder_id, lock=True)
    subfolders = list(db.scalars(select(ArchitectureFolder).where(ArchitectureFolder.parent_id == folder.id)))
    for child in subfolders:
        if _siblings_use(db, owner, folder.kind, folder.parent_id, child.name, folder.id):
            raise RuleError(
                f"A folder named '{child.name}' already exists in the parent folder; rename one of them first.", 400,
            )
    model = RECORD_MODELS[folder.kind]
    moved = db.execute(
        update(model).where(model.folder_id == folder.id).values(folder_id=folder.parent_id, version=model.version + 1)
        .execution_options(synchronize_session="fetch")
    ).rowcount
    for child in subfolders:
        child.parent_id = folder.parent_id
    db.flush()
    db.delete(folder)
    db.flush()
    _audit(db, folder.id, "deleted", actor, owner, kind=folder.kind, records_moved=moved, folders_moved=len(subfolders))


def move_records(
    db: Session, owner: ElementOwner, actor: User, kind: FolderKind, record_ids: Sequence[uuid.UUID], folder_id: uuid.UUID | None,
) -> int:
    """Puts the owner's records of `kind` in a folder (`None`: the top level), one audit event for the move. The caller
    commits. Returns how many records changed (one already there is not counted).

    Raises:
        RuleError: 400 for a folder that is not the owner's of that kind, 404 for a record that is not the owner's.
    """
    value = check_kind(owner, kind)
    if folder_id is not None:
        usable_folder(db, owner, value, folder_id)
    model = RECORD_MODELS[value]
    wanted = set(record_ids)
    rows = list(db.scalars(select(model).where(model.id.in_(wanted)).with_for_update()))
    owned = {r.id for r in rows if (r.project_id == owner.project_id if owner.project is not None else r.organization_id == owner.organization_id)}
    if owned != wanted:
        raise RuleError("A record to move was not found.", 404)
    changed = [r for r in rows if r.folder_id != folder_id]
    for row in changed:
        row.folder_id = folder_id
        row.version += 1
    db.flush()
    if changed:
        # One event for the move (the records' own History shows the folder through its field name).
        log_event(
            db, entity_type=FOLDER_ENTITY_TYPE, entity_id=folder_id or changed[0].id, action="records_moved", actor_id=actor.id,
            detail={"kind": value, "records": len(changed), "to_top_level": folder_id is None}, **owner.place,
        )
    return len(changed)


# --- Paths -----------------------------------------------------------------


def paths_for(db: Session, folder_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """The path (names from the top, joined by `/`) of each folder named; a bulk read: two statements however many.

    A folder that cannot be found is left out.
    """
    wanted = {f for f in folder_ids if f is not None}
    if not wanted:
        return {}
    seeds = list(db.execute(
        select(ArchitectureFolder.project_id, ArchitectureFolder.organization_id).where(ArchitectureFolder.id.in_(wanted)).distinct()
    ).tuples())
    project_ids = {p for p, _ in seeds if p is not None}
    organization_ids = {o for _, o in seeds if o is not None}
    conditions: list[ColumnElement[bool]] = []
    if project_ids:
        conditions.append(ArchitectureFolder.project_id.in_(project_ids))
    if organization_ids:
        conditions.append(ArchitectureFolder.organization_id.in_(organization_ids))
    if not conditions:
        return {}
    by_id = {f.id: f for f in db.scalars(select(ArchitectureFolder).where(or_(*conditions)))}
    return {folder_id: path_of(by_id, folder_id) for folder_id in wanted if folder_id in by_id}


def path_of(by_id: dict[uuid.UUID, ArchitectureFolder], folder_id: uuid.UUID) -> str:
    """The path of `folder_id` within `by_id` (cycle-safe, capped at the depth limit)."""
    names: list[str] = []
    current: uuid.UUID | None = folder_id
    while current is not None and current in by_id and len(names) < MAX_DEPTH:
        names.append(by_id[current].name)
        current = by_id[current].parent_id
    return PATH_SEPARATOR.join(reversed(names))


def resolve_path(db: Session, owner: ElementOwner, kind: str, path: str) -> uuid.UUID:
    """The owner's folder of `kind` at `path` (names matched ignoring case).

    Raises:
        RuleError: 400 if no such folder exists.
    """
    rows = list_folders(db, owner, kind)
    children: dict[uuid.UUID | None, dict[str, uuid.UUID]] = defaultdict(dict)
    for row in rows:
        children[row.parent_id][row.name.casefold()] = row.id
    current: uuid.UUID | None = None
    for part in (p.strip() for p in path.split(PATH_SEPARATOR)):
        found = children.get(current, {}).get(part.casefold())
        if found is None:
            raise RuleError(f"Folder '{path}' does not exist.", 400)
        current = found
    if current is None:
        raise RuleError("A folder path is empty.", 400)
    return current


def record_counts(db: Session, owner: ElementOwner, kind: str) -> dict[uuid.UUID, int]:
    """How many live records of `kind` sit directly in each folder."""
    model = RECORD_MODELS[kind]
    owner_column = model.project_id == owner.project.id if owner.project is not None else model.organization_id == owner.organization_id
    rows = db.execute(
        select(model.folder_id, func.count()).where(owner_column, model.folder_id.is_not(None), model.is_archived.is_(False))
        .group_by(model.folder_id)
    ).tuples()
    return {folder_id: count for folder_id, count in rows if folder_id is not None}


def folder_outs(db: Session, owner: ElementOwner, rows: Sequence[ArchitectureFolder]) -> list[FolderOut]:
    """API shapes for the owner's `rows`: paths and record counts are read in bulk."""
    by_id = {f.id: f for f in list_folders(db, owner)}
    counts: dict[uuid.UUID, int] = {}
    for kind in {r.kind for r in rows}:
        counts.update(record_counts(db, owner, kind))
    return [
        FolderOut(
            id=r.id, project_id=r.project_id, organization_id=r.organization_id, kind=FolderKind(r.kind), name=r.name,
            parent_id=r.parent_id, sort_order=r.sort_order, path=path_of(by_id, r.id), record_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


def path_index(db: Session, owner: ElementOwner, kind: str) -> dict[str, uuid.UUID]:
    """`{lower-case path: id}` of the owner's folders of `kind`, for matching a path a file names."""
    rows = list_folders(db, owner, kind)
    by_id = {r.id: r for r in rows}
    return {path_of(by_id, r.id).casefold(): r.id for r in rows}


def filter_ids(
    db: Session, owner: ElementOwner, kind: str, path: str | None, *, include_subfolders: bool,
) -> set[uuid.UUID] | None:
    """The folder ids a list filter keeps, or `None` for no folder filter. An unknown path keeps nothing (an empty set).

    `path` names the folder; `include_subfolders` adds everything below it.
    """
    if path is None or not path.strip():
        return None
    rows = list_folders(db, owner, kind)
    by_id = {r.id: r for r in rows}
    wanted = path.strip().casefold()
    top = next((r.id for r in rows if path_of(by_id, r.id).casefold() == wanted), None)
    if top is None:
        return set()
    if not include_subfolders:
        return {top}
    _parents, children = _tree(rows)
    found, frontier = {top}, [top]
    while frontier:
        frontier = [c for f in frontier for c in children.get(f, ()) if c not in found]
        found.update(frontier)
    return found


# --- Bundles ---------------------------------------------------------------


def export_entries(db: Session, owner: ElementOwner) -> list[dict[str, Any]]:
    """The owner's folders for a bundle: `{kind, path, sort_order}`, parents before children, so an import can create them in order."""
    rows = list_folders(db, owner)
    by_id = {r.id: r for r in rows}
    entries = [
        {"kind": r.kind, "path": path_of(by_id, r.id), "sort_order": r.sort_order} for r in rows
    ]
    return sorted(entries, key=lambda e: (e["kind"], e["path"].count(PATH_SEPARATOR), e["path"].casefold()))


class FolderImporter:
    """Creates the folders a bundle names, and finds or creates the folder at a path a record names.

    A folder that already exists at a path is reused (the same path always means the same folder), so importing into a
    project that has folders adds to them. A path that cannot be created (too deep, a blank name, a kind the owner may not
    have) is reported and the record is left at the top level; nothing is ever dropped with a record.

    Args:
        db: The session.
        owner: The owner the folders are created for.
        creator_id: Recorded as the creator of every folder created.
        warnings: Collects what could not be imported (an object with `add(message)`).
    """

    def __init__(self, db: Session, owner: ElementOwner, creator_id: uuid.UUID, warnings: Any) -> None:
        self.db = db
        self.owner = owner
        self.creator_id = creator_id
        self.warnings = warnings
        self._index: dict[tuple[str, str], uuid.UUID] = {}
        rows = list_folders(db, owner)
        by_id = {r.id: r for r in rows}
        for row in rows:
            self._index[(row.kind, path_of(by_id, row.id).casefold())] = row.id

    def ensure(self, kind: str, path: str | None, sort_order: int | None = None) -> uuid.UUID | None:
        """The id of the folder at `path` (created, with its ancestors, if missing), or `None` for the top level or a path that
        cannot be created."""
        if not path or not path.strip():
            return None
        try:
            check_kind(self.owner, kind)
            parts = [_check_name(p) for p in path.split(PATH_SEPARATOR)]
        except RuleError as exc:
            self.warnings.add(f"Folder '{path}' was not imported: {exc}")
            return None
        if len(parts) > MAX_DEPTH:
            self.warnings.add(f"Folder '{path}' was not imported: folders can be at most {MAX_DEPTH} levels deep.")
            return None
        parent_id: uuid.UUID | None = None
        for depth, name in enumerate(parts, start=1):
            key = (kind, PATH_SEPARATOR.join(parts[:depth]).casefold())
            found = self._index.get(key)
            if found is None:
                folder = ArchitectureFolder(
                    **self.owner.columns, kind=kind, name=name, parent_id=parent_id,
                    sort_order=sort_order if sort_order is not None and depth == len(parts) else 0, creator_id=self.creator_id,
                )
                self.db.add(folder)
                self.db.flush()
                found = folder.id
                self._index[key] = found
            parent_id = found
        return parent_id
