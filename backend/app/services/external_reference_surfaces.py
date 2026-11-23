"""
Module: services.external_reference_surfaces

The places a record's external references appear besides its own panel: the list filter, the shared export
and import column, the page read behind a list column, report and search text, and the look-up of records by an
outside key (`services.external_references` holds the table, systems and single-record changes).

Responsibilities:
- `ReferenceFilter` / `reference_clause`: the list filter (`external_system`, `external_key`) as one SQL
  condition, so a list, its export and a record-list report narrow the same rows.
- `reference_column` / `ReferenceCells` / `apply_imported_references`: the shared `external_refs` column
  (`SYSTEM:KEY; SYSTEM:KEY`), read for a page in one go and written after the type's own create or update path.
- `reference_texts` (report field and search snippet) and `find_records_by_reference` (visible records with an
  outside key).

Design decisions:
- A type needs nothing to take part: the filter applies wherever `services.tags.TagFilter` does, and the
  record-table engine adds the column beside the placements column.
- Filter, cell and look-up name a system by display name, case-insensitively, since one system can be an
  organisation entry for one project and a project entry for another, and a name is what a person types. A key
  matches by substring in the filter and exactly in the look-up.
- A cell has no link, note or role: an import keeps those of a reference it leaves in place and adds new ones
  bare, so a spreadsheet round trip loses nothing. A semicolon or backslash inside a key is backslash-escaped.
- Authority is `services.tags.can_tag`: changing the cell without it is a row error.

Dependencies: `models.external_reference`, `services.external_references`, `services.link_graph`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.external_reference import ExternalReference, ExternalSystemDefinition, ProjectExternalSystem
from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import (
    RecordCellError,
    RecordColumn,
    RecordImportContext,
    get_all_registered_artefact_types,
    get_artefact_type_label,
)
from app.services import external_references as refs

if TYPE_CHECKING:
    from app.services.link_graph import ArtefactResolver



def _escape_like(term: str) -> str:
    """`term` with the `LIKE` wildcards escaped (the escape character is a backslash)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


#: What joins several references in a cell, a report field and a search snippet.
CELL_SEPARATOR = "; "
#: The CSV header and the report and search key of the shared field.
REFERENCES_COLUMN_KEY = "external_refs"
REFERENCES_FIELD_LABEL = "External references"
#: Most systems one filter names (a longer list is a mistake, not a use).
MAX_FILTER_SYSTEMS = 20
#: Most records one look-up returns.
MAX_FOUND_RECORDS = 100
#: Most records one page read answers about (a list's page is far smaller).
MAX_PAGE_RECORDS = 500


# --- the filter -------------------------------------------------------------------------------------


def _system_ids(db: Session, organization_id: uuid.UUID, names: Sequence[str]) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """`(organisation system ids, project system ids)` of the organisation's systems whose display name is one of
    `names` (case-insensitive): an organisation entry by its name, a project row by its own name or, without one, the
    entry it overrides."""
    wanted = {n.strip().lower() for n in names if n and n.strip()}
    if not wanted:
        return [], []
    org_ids = list(db.scalars(select(ExternalSystemDefinition.id).where(
        ExternalSystemDefinition.organization_id == organization_id, func.lower(ExternalSystemDefinition.name).in_(wanted),
    )))
    in_organisation = select(Project.id).where(Project.organization_id == organization_id)
    project_ids = list(db.scalars(select(ProjectExternalSystem.id).where(
        ProjectExternalSystem.project_id.in_(in_organisation),
        or_(
            func.lower(ProjectExternalSystem.name_override).in_(wanted),
            and_(ProjectExternalSystem.name_override.is_(None), ProjectExternalSystem.org_type_id.in_(org_ids or [uuid.UUID(int=0)])),
        ),
    )))
    return org_ids, project_ids


def _conditions(
    db: Session, model: Any, organization_id: uuid.UUID, artefact_type: str, systems: Sequence[str], key: str | None,
) -> list[ColumnElement[bool]] | None:
    """The conditions on `model` (the references table or an alias of it) for "a reference in one of `systems` whose
    key contains `key`", or `None` when the systems named exist nowhere in the organisation (nothing can match)."""
    where: list[ColumnElement[bool]] = [model.artefact_type == artefact_type, model.organization_id == organization_id]
    if any(s.strip() for s in systems):
        org_ids, project_ids = _system_ids(db, organization_id, systems)
        if not org_ids and not project_ids:
            return None
        where.append(or_(model.org_system_id.in_(org_ids), model.project_system_id.in_(project_ids)))
    if key and key.strip():
        where.append(func.lower(model.key).like(f"%{_escape_like(key.strip().lower())}%", escape="\\"))
    return where


def reference_clause(
    db: Session, organization_id: uuid.UUID, artefact_type: str, id_column: Any, systems: Sequence[str], key: str | None,
) -> ColumnElement[bool]:
    """The condition "the record carries a reference in one of `systems` (any, when none is given) whose key contains
    `key` (any, when none is given)", as an `EXISTS` on `id_column`.

    Args:
        db: Active session (read only; the system names are resolved once here).
        organization_id: The organisation whose systems the names refer to.
        artefact_type: The listed record type.
        id_column: The record id column the condition is about.
        systems: System display names (case-insensitive); any one matches.
        key: A fragment of the outside key (case-insensitive); `None` or blank for any key.
    """
    reference = aliased(ExternalReference)
    where = _conditions(db, reference, organization_id, artefact_type, systems, key)
    if where is None:
        return false()
    return select(reference.id).where(reference.artefact_id == id_column, *where).exists()


@dataclass(frozen=True)
class ReferenceFilter:
    """The `external_system` and `external_key` list parameters: only records with a reference in one of the systems
    whose key contains the text. Either alone is enough (a system alone: any reference in it; a key alone: that key in
    any system).

    Attributes:
        systems: System display names; any one matches.
        key: A fragment of the outside key, or `None`.
    """

    systems: tuple[str, ...] = ()
    key: str | None = None

    @classmethod
    def of(cls, systems: Iterable[str], key: str | None) -> ReferenceFilter:
        """A filter from raw parameters (blank names and a blank key are dropped; at most `MAX_FILTER_SYSTEMS` names)."""
        names = tuple(dict.fromkeys(s.strip() for s in systems if s and s.strip()))[:MAX_FILTER_SYSTEMS]
        return cls(names, key.strip() if key and key.strip() else None)

    @property
    def active(self) -> bool:
        """Whether the caller asked to filter."""
        return bool(self.systems) or self.key is not None

    @property
    def applied_keys(self) -> list[str]:
        """The parameters in force (`external_system`, `external_key`), for the export's audit event."""
        return [*(["external_system"] if self.systems else []), *(["external_key"] if self.key else [])]

    def ids(self, db: Session, organization_id: uuid.UUID, artefact_type: str) -> set[uuid.UUID]:
        """Ids of the organisation's records of `artefact_type` that carry a matching reference."""
        where = _conditions(db, ExternalReference, organization_id, artefact_type, self.systems, self.key)
        if where is None:
            return set()
        return set(db.scalars(select(ExternalReference.artefact_id).where(*where).distinct()))


# --- text -------------------------------------------------------------------------------------------


def _escape(text: str) -> str:
    """A key with the cell's two special characters escaped."""
    return text.replace("\\", "\\\\").replace(";", "\\;")


def _split_cell(text: str) -> list[str]:
    """The cell's `;`-separated parts, honouring a backslash escape (`\\;` and `\\\\`), blanks dropped."""
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char if char in ";\\" else "\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def reference_cell(entries: Iterable[tuple[str, str]]) -> str:
    """The cell text for `(system name, key)` pairs: `Jira:PROJ-1; DOORS:REQ-9`. A reference with only a link has an
    empty key and is written as the system name and a colon."""
    return CELL_SEPARATOR.join(f"{name}:{_escape(key)}" for name, key in entries)


def reference_texts(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The `Jira:PROJ-1; DOORS:REQ-9` text of many records in a fixed number of statements (the report field and the
    search snippet). A record with no reference is absent."""
    found = refs.references_for_records(db, artefact_type, artefact_ids)
    return {
        record_id: reference_cell((r.system_name, r.key) for r in rows) for record_id, rows in found.items() if rows
    }


# --- the shared table column ------------------------------------------------------------------------


class ReferenceCells:
    """The `external_refs` cell of a type's table. Reads every record of a page in one go (the engine registers the
    page's ids with `expect`, and the first cell read loads all of them), parses a cell against the systems the
    records' tier offers, and keeps what an import needs to apply it.

    Args:
        db: Active session (read only until an import applies a cell).
        organization_id: The organisation the table is for.
        project: The project the table is for, or `None` for the organisation's own records.
        artefact_type: The record type.
        may_edit: Whether the caller may change references (`services.tags.can_tag`).
    """

    def __init__(
        self, db: Session, organization_id: uuid.UUID, project: Project | None, artefact_type: str, *, may_edit: bool,
    ) -> None:
        self._db = db
        self._type = artefact_type
        self.organization_id = organization_id
        self.project = project
        self.may_edit = may_edit
        self._wanted: set[uuid.UUID] = set()
        self._cells: dict[uuid.UUID, str] = {}
        if project is None:
            offered = [(t.name, t.id) for t in refs.EXTERNAL_SYSTEMS.active_org_types(db, organization_id)]
        else:
            offered = [(e.name, e.id) for e in refs.EXTERNAL_SYSTEMS.resolve_effective(db, project.id, organization_id) if e.is_enabled]
        self._systems: dict[str, uuid.UUID] = {}
        for name, system_id in offered:
            self._systems.setdefault(name.lower(), system_id)

    def expect(self, ids: Iterable[uuid.UUID]) -> None:
        """Registers the records whose cells will be read, so they load together."""
        self._wanted.update(ids)

    def text(self, record_id: uuid.UUID) -> str:
        """The record's cell text (empty when it has no reference)."""
        if record_id not in self._cells:
            self._wanted.add(record_id)
            pending = [i for i in self._wanted if i not in self._cells]
            found = reference_texts(self._db, self._type, pending)
            for pending_id in pending:
                self._cells[pending_id] = found.get(pending_id, "")
        return self._cells[record_id]

    def parse(self, text: str) -> list[tuple[uuid.UUID, str]]:
        """The `(system id, key)` pairs a cell names, duplicates dropped.

        Raises:
            RecordCellError: For a part with no colon, a system the records' tier does not offer, a key longer than the
                column, an empty key, or more references than a record may carry.
        """
        wanted: list[tuple[uuid.UUID, str]] = []
        for part in _split_cell(text):
            name, colon, key = part.partition(":")
            # A system name may itself hold a colon: the longest offered name that the part starts with wins.
            for offered in sorted(self._systems, key=len, reverse=True):
                if part.lower().startswith(offered + ":"):
                    name, key = part[: len(offered)], part[len(offered) + 1:]
                    colon = ":"
                    break
            key = key.strip()
            if not colon or not name.strip():
                raise RecordCellError(f"{part!r} is not written SYSTEM:KEY.")
            system_id = self._systems.get(name.strip().lower())
            if system_id is None:
                raise RecordCellError(f"No external system called {name.strip()} is available for these records.")
            if not key:
                raise RecordCellError(f"The reference in {name.strip()} has no key.")
            if len(key) > refs.MAX_KEY_LENGTH:
                raise RecordCellError(f"A key may be at most {refs.MAX_KEY_LENGTH} characters.")
            if (system_id, key) not in wanted:
                wanted.append((system_id, key))
        if len(wanted) > refs.MAX_REFERENCES:
            raise RecordCellError(f"A record can have at most {refs.MAX_REFERENCES} references.")
        return wanted


def reference_column(
    db: Session, organization: Organization, project: Project | None, artefact_type: str, *, may_edit: bool,
    id_of: Callable[[Any], uuid.UUID],
) -> tuple[RecordColumn, ReferenceCells] | None:
    """The shared `external_refs` column for a type's table, or `None` while its module has references switched off.

    Args:
        db: Active session (read only).
        organization: The request organisation.
        project: The request project, or `None` for the organisation's own list.
        artefact_type: The record type.
        may_edit: Whether the caller may change references; without it a changed cell is refused on import.
        id_of: Reads a record's id (the provider's `id_of`).

    Returns:
        The column and the reader whose `expect` the engine calls with the rows it will write.
    """
    if not refs.references_enabled(db, artefact_type, organization_id=organization.id, project_id=project.id if project else None):
        return None
    cells = ReferenceCells(db, organization.id, project, artefact_type, may_edit=may_edit)

    def parse(ctx: RecordImportContext, text: str) -> list[tuple[uuid.UUID, str]]:
        return cells.parse(text)

    column = RecordColumn(
        REFERENCES_COLUMN_KEY, REFERENCES_FIELD_LABEL, lambda prepared, record: cells.text(id_of(record)), parse, kind="list",
    )
    return column, cells


def apply_imported_references(
    ctx: RecordImportContext, artefact_type: str, record: Any, wanted: Sequence[tuple[uuid.UUID, str]], cells: ReferenceCells,
) -> None:
    """Makes the record carry exactly `wanted` after an import row: a reference already there with the same system and
    key is kept as it is (its link, note and role stay), the others are removed, and the missing ones are added.

    Raises:
        RecordCellError: When the caller may not change references, or the record cannot take the system (a record the
            organisation owns, written from a project's list).
    """
    db, actor = ctx.db, ctx.user
    current = list(db.scalars(select(ExternalReference).where(
        ExternalReference.artefact_type == artefact_type, ExternalReference.artefact_id == record.id,
    ).order_by(ExternalReference.created_at, ExternalReference.id)))
    owner = db.get(Project, record.project_id) if getattr(record, "project_id", None) is not None else None
    try:
        resolved = [(refs.resolve_system(db, cells.organization_id, owner, system_id), key, system_id) for system_id, key in wanted]
    except ValueError as exc:
        raise RecordCellError(str(exc)) from exc
    have = {((r.org_system_id, r.project_system_id), r.key): r for r in current}
    wanted_keys = {(pair, key) for pair, key, _ in resolved}
    removed = [row for identity, row in have.items() if identity not in wanted_keys]
    added = [(key, system_id) for pair, key, system_id in resolved if (pair, key) not in have]
    if (removed or added) and not cells.may_edit:
        raise RecordCellError("You do not have permission to change the external references of these records.")
    for row in removed:
        refs.audit_reference(db, row, "reference_removed", actor.id)
        refs.remove_reference(db, row)
    for key, system_id in added:
        try:
            row = refs.add_reference(
                db, artefact_type=artefact_type, artefact_id=record.id, organization_id=cells.organization_id, project=owner,
                system_id=system_id, key=key, actor_id=actor.id,
            )
        except ValueError as exc:
            raise RecordCellError(str(exc)) from exc
        refs.audit_reference(db, row, "reference_added", actor.id)


# --- the page read ----------------------------------------------------------------------------------


def page_references(
    db: Session, project: Project, resolver: ArtefactResolver, artefact_type: str, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[refs.ExternalReferenceOut]]:
    """The references of the listed records of one type, for a list's column, in a few statements.

    A record the caller cannot open from this project (or in another project) is left out, never reported as having
    none, so the answer discloses nothing a list would not already show. Only records with a reference are present.

    Raises:
        HTTPException: 404 for an unregistered type.
    """
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    asked = list(dict.fromkeys(ids))[:MAX_PAGE_RECORDS]
    if not asked:
        return {}
    resolver.resolve({artefact_type: set(asked)})
    visible = [
        i for i in asked
        if (summary := resolver.visible((artefact_type, i))) is not None and summary.project_id in (project.id, None)
    ]
    found = refs.references_for_records(db, artefact_type, visible)
    return {record_id: rows for record_id, rows in found.items() if rows}


# --- look-up ----------------------------------------------------------------------------------------


@dataclass
class ReferencedRecord:
    """A visible record found by an outside key (`find_records_by_reference`), with the matching reference."""

    artefact_type: str
    type_label: str
    id: uuid.UUID
    label: str
    status: str | None
    is_archived: bool
    project_id: uuid.UUID | None
    project_name: str | None
    project_code: str | None
    reference: refs.ExternalReferenceOut


def find_records_by_reference(
    db: Session, *, project: Project, resolver: ArtefactResolver, key: str, system: str | None = None,
    artefact_type: str | None = None, limit: int = MAX_FOUND_RECORDS, project_ids: set[uuid.UUID] | None = None,
) -> tuple[list[ReferencedRecord], bool]:
    """Records of any type, visible to the caller, that carry the outside key `key` (exactly, ignoring case) in
    `system` (any system when `None`).

    A record the caller cannot open is omitted, never described, so the result and its size reveal nothing about
    hidden records.

    Args:
        db: Active session (read only).
        project: The request project.
        resolver: The caller's visibility rules.
        key: The outside key, e.g. `PROJ-123`; required.
        system: A system display name, or `None`.
        artefact_type: Restrict to one registered type.
        limit: Most records to return (capped at `MAX_FOUND_RECORDS`).
        project_ids: The projects to look in (`None`: the request project; organisation-owned records are always
            considered).

    Returns:
        `(records, truncated)`, newest reference first.

    Raises:
        HTTPException: 422 when `key` is blank; 404 for an unregistered `artefact_type`.
    """
    key = key.strip()
    if not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the key to look for.")
    if artefact_type is not None and artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact type not found.")
    scope = project_ids if project_ids is not None else {project.id}
    where: list[Any] = [
        ExternalReference.organization_id == project.organization_id, func.lower(ExternalReference.key) == key.lower(),
        or_(ExternalReference.project_id.in_(scope), ExternalReference.project_id.is_(None)),
    ]
    if artefact_type is not None:
        where.append(ExternalReference.artefact_type == artefact_type)
    if system and system.strip():
        org_ids, project_system_ids = _system_ids(db, project.organization_id, [system])
        if not org_ids and not project_system_ids:
            return [], False
        where.append(or_(ExternalReference.org_system_id.in_(org_ids), ExternalReference.project_system_id.in_(project_system_ids)))
    hits = list(db.scalars(
        select(ExternalReference).where(*where).order_by(ExternalReference.created_at.desc()).limit(MAX_FOUND_RECORDS * 5)
    ))
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for hit in hits:
        wanted[hit.artefact_type].add(hit.artefact_id)
    resolver.resolve(wanted)
    names, templates = refs._system_details(db, hits)
    cap = max(1, min(limit, MAX_FOUND_RECORDS))
    found: list[ReferencedRecord] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for hit in hits:
        identity = (hit.artefact_type, hit.artefact_id)
        summary = resolver.visible(identity)
        if identity in seen or summary is None or (summary.project_id is not None and summary.project_id not in scope):
            continue
        seen.add(identity)
        found.append(ReferencedRecord(
            hit.artefact_type, get_artefact_type_label(hit.artefact_type), hit.artefact_id, summary.label, summary.status,
            summary.is_archived, summary.project_id, resolver.project_name(summary.project_id),
            resolver.project_code(summary.project_id), refs.reference_out(hit, names, templates),
        ))
        if len(found) > cap:
            break
    return found[:cap], len(found) > cap
