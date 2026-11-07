"""
Module: services.placements

Placing records of any registered artefact type in the project's component/category tree.

Responsibilities:
- Read a record's placements, singly or for a page of records in one query (`get_record_placements`,
  `placements_for_records`), and name them for exports and reports (`placement_text`).
- Replace a record's placements, validating that every component and category belongs to the record's
  project and that a category sits under its component (`set_record_placements`), and write the audit
  events the record's Activity tab reads.
- Answer "which records sit in these components or categories" for list endpoints (`PlacementFilter`).
- Keep the tree and the placements consistent when the tree changes: a deleted category's placements move to
  the replacement (`reassign_category`), and a component that records still sit in cannot be deleted
  (`component_placement_count`).

Design decisions:
- Requirements keep their single `component_id`/`category_id` columns because the component prefix forms the
  requirement code; they are never stored here (`COLUMN_PLACED_TYPES`), their own endpoints carry the field,
  and `can_place` is false for them. `pairs_for_records` presents the one resolved view for every type. A
  change request has no component of its own (only the `proposed_*` pair for a requirement it would add), so it
  is placed through the table like any other record.
- A record may hold any number of placements with no primary one; a filter matches a record if any
  placement matches.
- A component belongs to one project, so a record is placed only in its own project's tree. A child project
  does not fall back to an ancestor's tree: a placement is a reference to a row, not a definition table. A
  record owned by the organisation has no project and so no tree: it cannot be placed.
- A module may declare a type `not_placeable` (a record that exists only inside a structure of its own); the
  API refuses it and no placement column, filter or bundle entry is offered for it.
- Authority is the authority to tag the type (`services.tags.can_tag`): placement is metadata like a tag, so
  an approved requirement's lock does not apply, and the same roles that may edit the record may place it.

External dependencies: `models.placement`, `models.project`, `services.tags` (authority), `services.audit`,
`modules.registry` (types).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import HTTPException, Query, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.placement import ArtefactPlacement
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.modules.registry import RecordCellError, RecordColumn, RecordImportContext, get_not_placeable_types
from app.services.audit import log_event
from app.services.link_graph import ArtefactResolver

#: Types that keep their own component and category columns instead of rows in `artefact_placements`.
COLUMN_PLACED_TYPES = frozenset({"requirement"})
#: Most placements one record may hold.
MAX_PLACEMENTS_PER_RECORD = 50


@dataclass(frozen=True)
class PlacementPair:
    """One wanted placement: a component and, optionally, a category under it."""

    component_id: uuid.UUID
    category_id: uuid.UUID | None = None


def can_place(resolver: ArtefactResolver, artefact_type: str) -> bool:
    """Whether the user may change placements of `artefact_type` records in the request project.

    False for the types that keep their own columns and those a module declared `not_placeable`; otherwise the
    authority to tag the type."""
    from app.services.tags import can_tag  # tags composes this module's filter, so it cannot be imported at the top

    return (
        artefact_type not in COLUMN_PLACED_TYPES
        and artefact_type not in get_not_placeable_types()
        and can_tag(resolver, artefact_type)
    )


def require_place_authority(resolver: ArtefactResolver, artefact_type: str) -> None:
    """Raises 403 unless `can_place(resolver, artefact_type)`."""
    if not can_place(resolver, artefact_type):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to place this record.")


# --- reading ----------------------------------------------------------------------------------


def _ordered(query):
    """Orders a placement query by the tree's display order: component, then category."""
    return (
        query.join(ProjectComponent, ProjectComponent.id == ArtefactPlacement.component_id)
        .outerjoin(ProjectCategory, ProjectCategory.id == ArtefactPlacement.category_id)
        .order_by(ProjectComponent.sort_order, ProjectComponent.name, ProjectCategory.sort_order, ProjectCategory.name)
    )


def get_record_placements(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[ArtefactPlacement]:
    """The record's placements in tree order."""
    return list(
        db.scalars(
            _ordered(
                select(ArtefactPlacement).where(
                    ArtefactPlacement.artefact_type == artefact_type, ArtefactPlacement.artefact_id == artefact_id
                )
            )
        ).all()
    )


def placements_for_records(
    db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[ArtefactPlacement]]:
    """The placements of several records of one type in one query (`{record id: placements}`, absent = none)."""
    ids = list(artefact_ids)
    found: dict[uuid.UUID, list[ArtefactPlacement]] = defaultdict(list)
    if not ids:
        return found
    rows = db.scalars(
        _ordered(
            select(ArtefactPlacement).where(
                ArtefactPlacement.artefact_type == artefact_type, ArtefactPlacement.artefact_id.in_(ids)
            )
        )
    ).all()
    for row in rows:
        found[row.artefact_id].append(row)
    return found


def pairs_for_records(
    db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[PlacementPair]]:
    """One resolved view of where records sit, whatever the type stores: a requirement's own pair, the rows of
    `artefact_placements` for any other type. Absent = placed nowhere."""
    ids = list(artefact_ids)
    if artefact_type not in COLUMN_PLACED_TYPES:
        return {
            record_id: [PlacementPair(p.component_id, p.category_id) for p in rows]
            for record_id, rows in placements_for_records(db, artefact_type, ids).items()
        }
    if not ids:
        return {}
    return {
        row_id: [PlacementPair(component_id, category_id)]
        for row_id, component_id, category_id in db.execute(
            select(Requirement.id, Requirement.component_id, Requirement.category_id).where(Requirement.id.in_(ids))
        ).all()
    }


def placement_text(db: Session, placements: Sequence[ArtefactPlacement | PlacementPair]) -> list[str]:
    """Names for exports and reports: `Component` or `Component / Category`, in the order given."""
    if not placements:
        return []
    components = {
        c.id: c.name
        for c in db.scalars(select(ProjectComponent).where(ProjectComponent.id.in_({p.component_id for p in placements})))
    }
    category_ids = {p.category_id for p in placements if p.category_id is not None}
    categories = (
        {c.id: c.name for c in db.scalars(select(ProjectCategory).where(ProjectCategory.id.in_(category_ids)))}
        if category_ids
        else {}
    )
    return [
        components[p.component_id] if p.category_id is None else f"{components[p.component_id]} / {categories[p.category_id]}"
        for p in placements
    ]


#: The report and search key of the shared field, and what joins several placements in its printed text.
PLACEMENTS_FIELD_KEY = "placements"
PLACEMENT_TEXT_SEPARATOR = "; "


def placement_texts(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Where records sit as report text, `Component / Category; Component`, for a page of records in a few
    statements (a requirement through its own columns). Records placed nowhere are absent."""
    found = pairs_for_records(db, artefact_type, artefact_ids)
    flat = [(record_id, pair) for record_id, pairs in found.items() for pair in pairs]
    texts: dict[uuid.UUID, list[str]] = defaultdict(list)
    for (record_id, _), text in zip(flat, placement_text(db, [pair for _, pair in flat]), strict=True):
        texts[record_id].append(text)
    return {record_id: PLACEMENT_TEXT_SEPARATOR.join(parts) for record_id, parts in texts.items()}


# --- writing ----------------------------------------------------------------------------------


def _resolve_pairs(db: Session, project: Project, pairs: Sequence[PlacementPair]) -> list[PlacementPair]:
    """The wanted pairs with duplicates dropped, after checking every component and category.

    Raises:
        HTTPException: 422 for a component or category of another project, a category that is not under
            its component, or more than `MAX_PLACEMENTS_PER_RECORD` pairs.
    """
    unique = list(dict.fromkeys(pairs))
    if len(unique) > MAX_PLACEMENTS_PER_RECORD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"A record can sit in at most {MAX_PLACEMENTS_PER_RECORD} places."
        )
    component_ids = {p.component_id for p in unique}
    owned = (
        set(
            db.scalars(
                select(ProjectComponent.id).where(
                    ProjectComponent.id.in_(component_ids), ProjectComponent.project_id == project.id
                )
            ).all()
        )
        if component_ids
        else set()
    )
    if component_ids - owned:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A component does not belong to this project.")
    category_ids = {p.category_id for p in unique if p.category_id is not None}
    category_component: dict[uuid.UUID, uuid.UUID] = {}
    if category_ids:
        for category_id, component_id in db.execute(
            select(ProjectCategory.id, ProjectCategory.component_id).where(
                ProjectCategory.id.in_(category_ids), ProjectCategory.project_id == project.id
            )
        ).tuples():
            category_component[category_id] = component_id
    for pair in unique:
        if pair.category_id is not None and category_component.get(pair.category_id) != pair.component_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A category does not belong to the component it was placed with."
            )
    return unique


def _audit(
    db: Session, project: Project, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID,
    action: str, placement: ArtefactPlacement, text: str,
) -> None:
    """Writes a `placed`/`unplaced` event against the record."""
    log_event(
        db, entity_type=artefact_type, entity_id=artefact_id, action=action, actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail={"place": text},
    )


def set_record_placements(
    db: Session, *, project: Project, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID,
    pairs: Sequence[PlacementPair],
) -> tuple[list[ArtefactPlacement], list[ArtefactPlacement]]:
    """Makes the record sit in exactly `pairs`.

    Args:
        db: Active session; changes and audit events are added, not committed.
        project: The project owning the record (and the tree).
        actor_id: The acting user.
        artefact_type / artefact_id: The record; the caller has authorised it and checked the type is not one
            of `COLUMN_PLACED_TYPES`.
        pairs: The wanted placements.

    Returns:
        `(added, removed)` placement rows.

    Raises:
        HTTPException: 422 for an invalid pair (see `_resolve_pairs`).
    """
    wanted = _resolve_pairs(db, project, pairs)
    current = get_record_placements(db, artefact_type, artefact_id)
    have = {PlacementPair(p.component_id, p.category_id): p for p in current}
    removed = [row for key, row in have.items() if key not in set(wanted)]
    added = [
        ArtefactPlacement(
            project_id=project.id, artefact_type=artefact_type, artefact_id=artefact_id,
            component_id=pair.component_id, category_id=pair.category_id, created_by=actor_id,
        )
        for pair in wanted
        if pair not in have
    ]
    if removed:
        texts = placement_text(db, removed)
        for row, text in zip(removed, texts, strict=True):
            db.delete(row)
            _audit(db, project, actor_id, artefact_type, artefact_id, "unplaced", row, text)
    if added:
        db.add_all(added)
        db.flush()
        for row, text in zip(added, placement_text(db, added), strict=True):
            _audit(db, project, actor_id, artefact_type, artefact_id, "placed", row, text)
    db.flush()
    return added, removed


def forget_record_placements(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> None:
    """Drops every placement of a record that is being deleted for good (there is no foreign key, so the
    record's owner calls this)."""
    db.execute(
        delete(ArtefactPlacement).where(
            ArtefactPlacement.artefact_type == artefact_type, ArtefactPlacement.artefact_id == artefact_id
        )
    )


# --- keeping the tree consistent --------------------------------------------------------------


def reassign_category(db: Session, category_id: uuid.UUID, target: ProjectCategory) -> int:
    """Moves every placement in `category_id` to `target` (called before the category is deleted).

    A record that already sits in `target` keeps that one, and the placement being moved is dropped, so the
    unique index holds.

    Returns:
        How many placements were moved or dropped.
    """
    other = ArtefactPlacement.__table__.alias("other")
    already_there = (
        select(other.c.id)
        .where(
            other.c.artefact_type == ArtefactPlacement.artefact_type,
            other.c.artefact_id == ArtefactPlacement.artefact_id,
            other.c.component_id == target.component_id,
            other.c.category_id == target.id,
        )
        .exists()
    )
    dropped = db.execute(
        delete(ArtefactPlacement).where(ArtefactPlacement.category_id == category_id, already_there)
    ).rowcount
    moved = db.execute(
        update(ArtefactPlacement)
        .where(ArtefactPlacement.category_id == category_id)
        .values(category_id=target.id, component_id=target.component_id)
    ).rowcount
    return (dropped or 0) + (moved or 0)


def component_placement_count(db: Session, component_id: uuid.UUID) -> int:
    """How many placements name the component (with or without a category); a component with any cannot
    be deleted."""
    return db.scalar(
        select(func.count()).select_from(ArtefactPlacement).where(ArtefactPlacement.component_id == component_id)
    ) or 0


# --- export and import ------------------------------------------------------------------------

PLACEMENT_COLUMN_KEY = "placements"
_LIST_SEPARATOR = ";"
_PAIR_SEPARATOR = "/"


class PlacementCells:
    """The `placements` cell of a type's table: `SW`, or `SW/PERF` for a category, `;`-separated, by prefix (the
    form the requirement table already uses for its own component and category).

    Reads for every record of a page in one query: the engine registers the page's ids with `expect`, and the
    first cell read loads all of them.
    """

    def __init__(self, db: Session, project: Project, artefact_type: str) -> None:
        """Binds the cell reader to one project and record type."""
        self._db = db
        self._type = artefact_type
        self._components: dict[uuid.UUID, ProjectComponent] = {}
        self._categories: dict[uuid.UUID, ProjectCategory] = {}
        for component in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project.id)):
            self._components[component.id] = component
        for category in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project.id)):
            self._categories[category.id] = category
        self._wanted: set[uuid.UUID] = set()
        self._cells: dict[uuid.UUID, str] = {}

    @property
    def has_components(self) -> bool:
        """Whether the project has any component to place records in."""
        return bool(self._components)

    def expect(self, ids: Iterable[uuid.UUID]) -> None:
        """Registers the records whose cells will be read, so they load together."""
        self._wanted.update(ids)

    def text(self, record_id: uuid.UUID) -> str:
        """The record's cell text (empty when it is placed nowhere)."""
        if record_id not in self._cells:
            self._wanted.add(record_id)
            pending = [i for i in self._wanted if i not in self._cells]
            found = pairs_for_records(self._db, self._type, pending)
            for pending_id in pending:
                self._cells[pending_id] = self.format(found.get(pending_id, []))
        return self._cells[record_id]

    def format(self, pairs: Sequence[PlacementPair]) -> str:
        """The cell text for `pairs`, in the order given."""
        parts = []
        for pair in pairs:
            component = self._components.get(pair.component_id)
            if component is None:
                continue
            category = self._categories.get(pair.category_id) if pair.category_id else None
            parts.append(component.prefix if category is None else f"{component.prefix}{_PAIR_SEPARATOR}{category.prefix}")
        return _LIST_SEPARATOR.join(parts)

    def parse(self, text: str) -> list[PlacementPair]:
        """The pairs a cell names.

        Raises:
            RecordCellError: For a prefix the project does not have, or a category not under its component.
        """
        by_prefix = {c.prefix.upper(): c for c in self._components.values()}
        pairs: list[PlacementPair] = []
        for part in (p.strip() for p in text.split(_LIST_SEPARATOR)):
            if not part:
                continue
            component_prefix, _, category_prefix = (x.strip() for x in part.partition(_PAIR_SEPARATOR))
            component = by_prefix.get(component_prefix.upper())
            if component is None:
                raise RecordCellError(f"No component with the prefix {component_prefix} in this project.")
            category_id = None
            if category_prefix:
                category = next(
                    (
                        c for c in self._categories.values()
                        if c.component_id == component.id and c.prefix.upper() == category_prefix.upper()
                    ),
                    None,
                )
                if category is None:
                    raise RecordCellError(f"No category with the prefix {category_prefix} under component {component.prefix}.")
                category_id = category.id
            pair = PlacementPair(component.id, category_id)
            if pair not in pairs:
                pairs.append(pair)
        return pairs


def placement_column(
    db: Session, project: Project, artefact_type: str, *, may_place: bool, id_of: Callable[[Any], uuid.UUID],
) -> tuple[RecordColumn, PlacementCells] | None:
    """The shared `placements` column for a type's table, or `None` when the type keeps its own columns or the
    project has no components.

    Args:
        db: Active session (read only).
        project: The request project.
        artefact_type: The record type.
        may_place: Whether the caller may change placements; without it a non-blank cell is refused on import.
        id_of: Reads a record's id (the provider's `id_of`).

    Returns:
        The column and the reader whose `expect` the engine calls with the rows it will write.
    """
    if artefact_type in COLUMN_PLACED_TYPES or artefact_type in get_not_placeable_types():
        return None
    cells = PlacementCells(db, project, artefact_type)
    if not cells.has_components:
        return None

    def parse(ctx: RecordImportContext, text: str) -> list[PlacementPair]:
        pairs = cells.parse(text)
        if pairs and not may_place:
            raise RecordCellError("You do not have permission to place these records.")
        return pairs

    column = RecordColumn(
        PLACEMENT_COLUMN_KEY, "Component and category",
        lambda prepared, record: cells.text(id_of(record)), parse, kind="list",
    )
    return column, cells


def apply_imported_placements(
    ctx: RecordImportContext, artefact_type: str, record: Any, pairs: Sequence[PlacementPair],
) -> None:
    """Writes an import row's placements to the record the type's own create or update path produced.

    Raises:
        RecordCellError: For a record owned by the organisation, which has no project tree.
    """
    if getattr(record, "project_id", ctx.project.id) is None:
        raise RecordCellError("A record owned by the organisation cannot be placed in a project's components.")
    set_record_placements(
        ctx.db, project=ctx.project, actor_id=ctx.user.id, artefact_type=artefact_type, artefact_id=record.id, pairs=pairs,
    )


# --- project bundle ---------------------------------------------------------------------------


def _entries_for(db: Session, found: dict[uuid.UUID, list[PlacementPair]]) -> dict[uuid.UUID, list[dict[str, str | None]]]:
    """The bundle form of each record's placements: `{"component": prefix, "category": prefix or None}`, by prefix
    so an import needs no ids. The prefixes of every component and category named are read in two statements."""
    pairs = [p for row in found.values() for p in row]
    component_ids = {p.component_id for p in pairs}
    category_ids = {p.category_id for p in pairs if p.category_id is not None}
    components: dict[uuid.UUID, str] = {}
    categories: dict[uuid.UUID, str] = {}
    if component_ids:
        for component_id, prefix in db.execute(
            select(ProjectComponent.id, ProjectComponent.prefix).where(ProjectComponent.id.in_(component_ids))
        ).tuples():
            components[component_id] = prefix
    if category_ids:
        for category_id, prefix in db.execute(
            select(ProjectCategory.id, ProjectCategory.prefix).where(ProjectCategory.id.in_(category_ids))
        ).tuples():
            categories[category_id] = prefix
    return {
        record_id: [
            {"component": components[p.component_id], "category": categories[p.category_id] if p.category_id else None}
            for p in row
            if p.component_id in components
        ]
        for record_id, row in found.items()
    }


def prime_record_placements(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> None:
    """Reads the placements of many records of one type in one go, for `record_placements` to answer from.

    A bundle export calls `record_placements` once per record; calling this first with the records it will export
    makes that a few statements instead of a few per record. Like `services.tags.prime_record_tag_names` it only
    has an effect inside a `memoize_module_state()` block (an export); elsewhere it does nothing.
    """
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    if memo is None or artefact_type in COLUMN_PLACED_TYPES or artefact_type in get_not_placeable_types():
        return
    ids = list(artefact_ids)
    entries = _entries_for(db, pairs_for_records(db, artefact_type, ids))
    for record_id in ids:
        memo[("record_placements", artefact_type, record_id)] = entries.get(record_id, [])


def record_placements(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[dict[str, str | None]]:
    """A record's placements as bundle entries (from `prime_record_placements` when the export primed them).

    Empty for a type that keeps its own columns: its section carries the component and category itself."""
    from app.modules.registry import module_state_memo

    if artefact_type in COLUMN_PLACED_TYPES or artefact_type in get_not_placeable_types():
        return []
    memo = module_state_memo()
    if memo is not None and ("record_placements", artefact_type, artefact_id) in memo:
        return [dict(e) for e in memo[("record_placements", artefact_type, artefact_id)]]
    return _entries_for(db, pairs_for_records(db, artefact_type, [artefact_id])).get(artefact_id, [])


def restore_record_placements(
    db: Session, *, project_id: uuid.UUID | None, actor_id: uuid.UUID | None, artefact_type: str,
    artefact_id: uuid.UUID, entries: list[dict[str, Any]] | None,
) -> None:
    """Applies a bundle row's placements to its newly created record.

    A component or category the new project does not have is skipped, since the bundle's tree was imported first
    and a missing prefix means the tree itself was edited by hand. A record owned by the organisation has no
    project tree, so nothing is placed.

    Args:
        db: Active session; rows are added, not committed.
        project_id: The record's owning project, or `None` for a record the organisation owns.
        actor_id: The importing user.
        artefact_type / artefact_id: The new record.
        entries: The row's `record_placements` output (nothing to do when empty or absent).
    """
    if not entries or project_id is None:
        return
    project = db.get(Project, project_id)
    if project is None:
        return
    tree = db.info.setdefault("placement_tree", {})
    cached = tree.get(project_id)
    wanted = {(e.get("component"), e.get("category")) for e in entries}
    if cached is None or any(c not in cached[0] for c, _ in wanted):
        components = {c.prefix: c.id for c in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project_id))}
        categories = {
            (c.component_id, c.prefix): c.id
            for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project_id))
        }
        cached = tree[project_id] = (components, categories)
    components, categories = cached
    pairs: list[PlacementPair] = []
    for entry in entries:
        component_id = components.get(entry.get("component") or "")
        if component_id is None:
            continue
        category_prefix = entry.get("category")
        category_id = categories.get((component_id, category_prefix)) if category_prefix else None
        if category_prefix and category_id is None:
            continue
        pairs.append(PlacementPair(component_id, category_id))
    if pairs:
        set_record_placements(
            db, project=project, actor_id=actor_id, artefact_type=artefact_type, artefact_id=artefact_id, pairs=pairs,
        )


# --- list filter ------------------------------------------------------------------------------

_Row = TypeVar("_Row")


def placed_ids(
    db: Session, *, project_id: uuid.UUID, artefact_type: str, component_ids: Sequence[uuid.UUID],
    category_ids: Sequence[uuid.UUID],
) -> set[uuid.UUID]:
    """Ids of the project's records of `artefact_type` with a placement in any of the components or any of the
    categories (a requirement's own component and category, for a `COLUMN_PLACED_TYPES` type)."""
    conditions = []
    if component_ids:
        conditions.append(ArtefactPlacement.component_id.in_(component_ids))
    if category_ids:
        conditions.append(ArtefactPlacement.category_id.in_(category_ids))
    if not conditions:
        return set()
    if artefact_type in COLUMN_PLACED_TYPES:
        # A requirement keeps its one component and category on the record itself, so it matches through them.
        own = []
        if component_ids:
            own.append(Requirement.component_id.in_(component_ids))
        if category_ids:
            own.append(Requirement.category_id.in_(category_ids))
        return set(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id, or_(*own))).all())
    return set(
        db.scalars(
            select(ArtefactPlacement.artefact_id).where(
                ArtefactPlacement.project_id == project_id, ArtefactPlacement.artefact_type == artefact_type,
                or_(*conditions),
            )
        ).all()
    )


class PlacementFilter:
    """The `?component_id=…&category_id=…` list filter, as a FastAPI dependency
    (`placement_filter: PlacementFilter = Depends()`), so every list endpoint offers the same parameters.

    A record matches when it has a placement in any listed component or any listed category.

    Attributes:
        component_ids: The requested components.
        category_ids: The requested categories.
    """

    def __init__(
        self,
        component_id: list[uuid.UUID] = Query([], description="Only records placed in these components."),
        category_id: list[uuid.UUID] = Query([], description="Only records placed in these categories."),
    ) -> None:
        """Reads the `component_id` and `category_id` query parameters."""
        self.component_ids = list(component_id)
        self.category_ids = list(category_id)

    @property
    def active(self) -> bool:
        """Whether the caller asked to filter."""
        return bool(self.component_ids or self.category_ids)

    def ids(self, db: Session, project_id: uuid.UUID, artefact_type: str) -> set[uuid.UUID]:
        """Ids of the project's records of `artefact_type` that satisfy the filter."""
        return placed_ids(
            db, project_id=project_id, artefact_type=artefact_type, component_ids=self.component_ids,
            category_ids=self.category_ids,
        )

    def keep(
        self, db: Session, project_id: uuid.UUID, artefact_type: str, rows: Sequence[_Row], id_of=lambda row: row.id,
    ) -> list[_Row]:
        """`rows` narrowed to the matching records (unchanged when the filter is not active).

        Args:
            db: Active session (read only).
            project_id: The project the list is for.
            artefact_type: The listed record type.
            rows: The rows the endpoint would return.
            id_of: Reads a row's record id (default `row.id`).
        """
        if not self.active:
            return list(rows)
        wanted = self.ids(db, project_id, artefact_type)
        return [row for row in rows if id_of(row) in wanted]

