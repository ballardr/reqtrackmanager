"""
Module: modules.architecture.interchange

JSON interchange for a project's architecture: one self-describing, versioned file holding the project's element and
connection types, folders, elements (ports, tags, places), connections (realisations), diagrams (boxes, notes, anchors,
toggles and their rules, boundary boxes, symbol references) and state machine diagrams with their states and transitions.

Responsibilities:
- `export_document`: the file for a project, as the caller may read it.
- `validate_document`: refuses a file that is too large, too deep, of an unknown major version or of the wrong shape,
  before anything is written.
- `preview_import` / `apply_import`: the same import, the first rolled back, returning what was (or would be) created and
  what could not be resolved.

Design decisions (all Decided by: Agent unless stated):
- **One section, two envelopes.** The file is the module's project bundle section (`export.export_project_data` and
  `import_project_data`) inside a version envelope, so the portable keys, the cross-references, the numbering afresh and
  the round trip are the bundle's, with one place to maintain. A record keeps its code as information only; an import
  numbers records afresh and codes key the references inside the file.
- **What the file leaves out, and why.** Comments and their pins, the person behind each record's creator and archiver
  (`*_email` keys), an element's owner, requirement links, collections, allocation dismissals and uploaded symbol files
  are not written: a shareable file must not carry discussion, personal data (the record exports hold an owner column to
  the organisation's personal-data policy, which a file any member can download would bypass), grants, or records the file
  does not hold. A reference to a symbol travels by tier and name, and an import that cannot match it reports it.
- **Visibility is applied on export.** A connection end or state machine element another owner shares is written as an
  external reference only when the caller may read it; otherwise the reference is emptied, so the file does not disclose a
  code the caller cannot see. An import drops a connection whose end cannot be resolved and reports it.
- **Import writes through the bundle path** inside one transaction, so a failure leaves nothing behind; it creates
  vocabulary rows when a type is missing, so it needs the Architect and the Architecture Admin roles (the router checks).
- **Preview is the import, rolled back.** It shows what an apply would do from the same code, so the two cannot differ.
- **Limits.** 10 MiB, 20 000 entries in one list, nesting of 40 levels; a file beyond them is rejected whole. The version
  is `major.minor`; a different major is refused, a higher minor of the same major is read (unknown keys are ignored).

Dependencies: `export` (the bundle section), `visibility`, `app.services.bundle_common`, this module's models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.architecture import export as bundle
from app.modules.architecture.models import (
    ArchitectureConnection,
    ArchitectureConnectionType,
    ArchitectureDiagram,
    ArchitectureElement,
    ArchitectureElementType,
    ArchitectureState,
    ArchitectureStateMachineDiagram,
    ArchitectureTransition,
)
from app.modules.architecture.visibility import Viewer, visible_element_ids
from app.services.bundle_common import BundleImportWarnings, UserResolver

FORMAT = "reqtrack-architecture"
VERSION = "1.0"
SUPPORTED_MAJOR = 1
MAX_BYTES = 10 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_DEPTH = 40

#: The sections a file may hold, in the order they are written.
SECTIONS: tuple[str, ...] = (
    bundle.PROJECT_ELEMENT_TYPES_KEY, bundle.PROJECT_CONNECTION_TYPES_KEY, bundle.HIDDEN_ELEMENT_TYPES_KEY,
    bundle.HIDDEN_CONNECTION_TYPES_KEY, bundle.HIDDEN_SYMBOLS_KEY, bundle.FOLDERS_KEY, bundle.ELEMENTS_KEY,
    bundle.CONNECTIONS_KEY, bundle.DIAGRAMS_KEY, bundle.STATE_MACHINES_KEY,
)
#: Sections whose entries must be objects with a `name` (types, elements, diagrams); connections need only a code.
_NAMED = frozenset(SECTIONS) - {bundle.HIDDEN_ELEMENT_TYPES_KEY, bundle.HIDDEN_CONNECTION_TYPES_KEY, bundle.HIDDEN_SYMBOLS_KEY,
                                bundle.FOLDERS_KEY, bundle.CONNECTIONS_KEY}
_NAME_LISTS = frozenset({bundle.HIDDEN_ELEMENT_TYPES_KEY, bundle.HIDDEN_CONNECTION_TYPES_KEY, bundle.HIDDEN_SYMBOLS_KEY})
_DROPPED_KEYS = frozenset({"comments", "comment_pins"})


class InterchangeError(Exception):
    """A file that cannot be read; `status_code` is the HTTP status to answer with (413 for size, 422 otherwise)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ImportReport:
    """What an import did (or, for a preview, would do).

    Attributes:
        created: New rows by kind (`elements`, `connections`, `diagrams`, `state_machine_diagrams`, `states`,
            `transitions`, `element_types`, `connection_types`).
        warnings: What could not be resolved or was skipped, in plain words.
    """

    created: dict[str, int]
    warnings: list[str]


def _kept(key: str, item: Any) -> bool:
    """Whether an exported key stays in the file: not a comment, not an `*_email`, and an `owner` only when it is the
    owner kind of a reference (`project` or `organization`, a string), never an element's person or group object."""
    if key in _DROPPED_KEYS or key.endswith("_email"):
        return False
    return isinstance(item, str) if key == "owner" else True


def scrub(value: Any) -> Any:
    """A copy of exported data without comments, element owners and `*_email` keys (the personal data a bundle carries)."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if _kept(key, item)}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def empty_hidden_refs(db: Session, viewer: Viewer, project: Project, data: dict[str, Any]) -> dict[str, Any]:
    """Empties every external reference to an element the viewer cannot read (a connection end, a diagram scope, a box)."""
    own = ArchitectureConnection.project_id == project.id
    candidates: set[UUID] = set(db.scalars(select(ArchitectureConnection.source_element_id).where(own)))
    candidates.update(db.scalars(select(ArchitectureConnection.target_element_id).where(own)))
    candidates.update(db.scalars(select(ArchitectureStateMachineDiagram.element_id).where(
        ArchitectureStateMachineDiagram.project_id == project.id
    )))
    candidates.update(
        scope for scope in db.scalars(select(ArchitectureDiagram.scope_element_id).where(ArchitectureDiagram.project_id == project.id))
        if scope is not None
    )
    owned = set(db.scalars(select(ArchitectureElement.id).where(ArchitectureElement.project_id == project.id)))
    foreign = candidates - owned
    hidden = foreign - visible_element_ids(db, viewer, foreign)
    refs = list(bundle.foreign_refs(db, hidden).values())
    if not refs:
        return data

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {} if value in refs else {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(data)


def export_document(db: Session, project: Project, user: User) -> dict[str, Any]:
    """The project's interchange file.

    Args:
        db: Database session (read only).
        project: The project exported.
        user: The person exporting; what they may not read is not named (see the module note).

    Returns:
        The JSON-serialisable document: `format`, `version`, `exported_at`, `source` (the project and organisation codes)
        and `data` (the sections of `SECTIONS`).
    """
    exported, _assets = bundle.export_project_data(db, project)
    data = scrub({key: exported.get(key, []) for key in SECTIONS})
    data = empty_hidden_refs(db, Viewer.of_user(user, project), project, data)
    organization = db.get(Organization, project.organization_id)
    return {
        "format": FORMAT, "version": VERSION, "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": {"project_code": project.code, "organization_code": organization.code if organization else None}, "data": data,
    }


def _depth(value: Any, limit: int) -> int:
    """Nesting depth of parsed JSON, stopping once it passes `limit`."""
    deepest, stack = 1, [(value, 1)]
    while stack:
        item, level = stack.pop()
        deepest = max(deepest, level)
        if deepest > limit:
            return deepest
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        stack.extend((child, level + 1) for child in children)
    return deepest


def parse_document(raw: bytes) -> dict[str, Any]:
    """Parses and validates an interchange file.

    Args:
        raw: The uploaded bytes.

    Returns:
        The document, with `data` restricted to the known sections.

    Raises:
        InterchangeError: 413 when over `MAX_BYTES`; 422 when it is not JSON, is nested deeper than `MAX_DEPTH`, is not
            this format, has an unsupported major version, or a section is not a list of well-formed entries.
    """
    if len(raw) > MAX_BYTES:
        raise InterchangeError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", 413)
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise InterchangeError("The file is not valid JSON.") from exc
    if _depth(document, MAX_DEPTH) > MAX_DEPTH:
        raise InterchangeError(f"The file is nested more than {MAX_DEPTH} levels deep.")
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise InterchangeError("This is not a System Architecture interchange file.")
    version = str(document.get("version", ""))
    major, _, minor = version.partition(".")
    if not major.isdigit() or not (minor == "" or minor.isdigit()) or int(major) != SUPPORTED_MAJOR:
        raise InterchangeError(f"Version {version or '(none)'} is not supported; this server reads version {SUPPORTED_MAJOR}.x.")
    data = document.get("data")
    if not isinstance(data, dict):
        raise InterchangeError("The file has no data section.")
    clean: dict[str, Any] = {}
    for key in SECTIONS:
        entries = data.get(key, [])
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise InterchangeError(f"Section {key} must be a list of at most {MAX_ENTRIES} entries.")
        if key in _NAME_LISTS:
            if not all(isinstance(e, str) for e in entries):
                raise InterchangeError(f"Section {key} must list names.")
        elif not all(isinstance(e, dict) for e in entries):
            raise InterchangeError(f"Section {key} must list objects.")
        elif key in _NAMED and not all(isinstance(e.get("name"), str) and e["name"].strip() for e in entries):
            raise InterchangeError(f"Every entry of {key} needs a name.")
        elif key in (bundle.ELEMENTS_KEY, bundle.CONNECTIONS_KEY, bundle.DIAGRAMS_KEY, bundle.STATE_MACHINES_KEY) and not all(
            isinstance(e.get("unique_code"), str) and e["unique_code"] for e in entries
        ):
            raise InterchangeError(f"Every entry of {key} needs a code to be referred to by.")
        clean[key] = entries
    return {**document, "data": clean}


_COUNTED: dict[str, tuple[Any, Any]] = {
    "elements": (ArchitectureElement, ArchitectureElement.project_id),
    "connections": (ArchitectureConnection, ArchitectureConnection.project_id),
    "diagrams": (ArchitectureDiagram, ArchitectureDiagram.project_id),
    "state_machine_diagrams": (ArchitectureStateMachineDiagram, ArchitectureStateMachineDiagram.project_id),
    "states": (ArchitectureState, ArchitectureState.project_id),
    "element_types": (ArchitectureElementType, ArchitectureElementType.project_id),
    "connection_types": (ArchitectureConnectionType, ArchitectureConnectionType.project_id),
}


def _counts(db: Session, project: Project) -> dict[str, int]:
    """Row counts per kind for the project (transitions through their diagrams)."""
    counts = {kind: db.scalar(select(func.count()).select_from(model).where(column == project.id)) or 0 for kind, (model, column) in _COUNTED.items()}
    counts["transitions"] = db.scalar(
        select(func.count()).select_from(ArchitectureTransition).join(
            ArchitectureStateMachineDiagram, ArchitectureStateMachineDiagram.id == ArchitectureTransition.state_machine_diagram_id,
        ).where(ArchitectureStateMachineDiagram.project_id == project.id)
    ) or 0
    return counts


def _run_import(db: Session, project: Project, document: dict[str, Any], user: User) -> ImportReport:
    """Imports `document` into `project` (nothing committed) and reports the rows added."""
    warnings = BundleImportWarnings()
    before = _counts(db, project)
    users = UserResolver(db, user, warnings, organization_id=project.organization_id, data=document["data"])
    try:
        bundle.import_project_data(db, project, document["data"], {}, user, users, warnings)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise InterchangeError("The file is not a well-formed architecture file; nothing was imported.") from exc
    after = _counts(db, project)
    return ImportReport({kind: after[kind] - before[kind] for kind in after}, warnings.messages)


def preview_import(db: Session, project: Project, document: dict[str, Any], user: User) -> ImportReport:
    """What an import would create and report, with nothing stored (the import runs in a savepoint that is rolled back).

    Raises:
        InterchangeError: If the file is not well formed.
    """
    savepoint = db.begin_nested()
    try:
        return _run_import(db, project, document, user)
    finally:
        savepoint.rollback()


def apply_import(db: Session, project: Project, document: dict[str, Any], user: User) -> ImportReport:
    """Imports the file into the project; the caller commits.

    Raises:
        InterchangeError: If the file is not well formed (the savepoint is rolled back, so nothing is stored).
    """
    savepoint = db.begin_nested()
    try:
        report = _run_import(db, project, document, user)
    except InterchangeError:
        savepoint.rollback()
        raise
    savepoint.commit()
    return report


__all__ = [
    "FORMAT", "VERSION", "ImportReport", "InterchangeError", "apply_import", "export_document", "parse_document", "preview_import",
]
