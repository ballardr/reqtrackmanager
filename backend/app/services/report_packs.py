"""
Module: services.report_packs

Storing and versioning report packs (`models.report_pack`).

Responsibilities:
- Create a pack with its first version, save further versions, rename or re-describe it, delete it.
- Read the current version, one version, or the version history.
- Validate every definition before it is stored (`report_pack_definition.assert_valid`) and write one audit
  event per change.

Design decisions:
- **Editing never changes a stored version.** A save appends a version; a run pins one by number, so provenance
  stays true (`ReportPackVersion` refuses updates).
- **Optimistic concurrency.** A save names the version it was based on; if the pack moved on it is refused
  (`PackConflictError`) rather than overwriting a colleague's change. The pack row is locked while the next number
  is chosen. A save whose definition hashes the same as the current version stores nothing.
- The audit event carries ids, the version number, the hash and counts, never the pack's text or any value.
- Permission to manage packs is decided by the caller (the endpoint, with the same permissions as layouts); this
  module trusts it and only checks that a project belongs to the organisation named.

Dependencies: `models.report_pack`, `services.report_pack_definition`, `services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_pack import ReportPack, ReportPackVersion
from app.models.report_placement import ReportPlacement
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.report_folders import clean_folder
from app.services.report_pack_definition import PACK_SCHEMA_VERSION, assert_valid, definition_hash
from app.services.report_pack_scope import PACK_KIND

MAX_NAME_CHARS = 200
MAX_DESCRIPTION_CHARS = 2000
MAX_COMMENT_CHARS = 500


class PackNameTakenError(ValueError):
    """Another pack of the same owner already has this name."""


class PackConflictError(ValueError):
    """A save was based on a version that is no longer the current one."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"The pack is now at version {current_version}; reload it and apply your change again.")


@dataclass(frozen=True)
class SavedPack:
    """A pack together with the version a call stored or returned.

    Attributes:
        pack: The pack row.
        version: The version stored (or, for an unchanged save, the current one).
        changed: Whether a new version was stored.
    """

    pack: ReportPack
    version: ReportPackVersion
    changed: bool


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > MAX_NAME_CHARS:
        raise ValueError(f"A pack name is 1 to {MAX_NAME_CHARS} characters.")
    return cleaned


def _check_text(value: str, limit: int, what: str) -> str:
    if len(value) > limit:
        raise ValueError(f"The {what} is at most {limit} characters.")
    return value


def _assert_name_free(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    """Raises `PackNameTakenError` when the owner already has a pack called `name` (case-insensitive)."""
    owner = [
        ReportPack.organization_id == organization_id,
        ReportPack.project_id.is_(None) if project_id is None else ReportPack.project_id == project_id,
    ]
    for existing_id, existing_name in db.execute(select(ReportPack.id, ReportPack.name).where(*owner)):
        if existing_name.casefold() == name.casefold() and existing_id != except_id:
            raise PackNameTakenError(f'A pack called "{name}" already exists here.')


def create_pack(
    db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str, description: str,
    definition: dict[str, Any], actor_id: uuid.UUID | None, comment: str = "", folder: str = "",
) -> SavedPack:
    """Creates a pack and its version 1.

    Args:
        db: Active session (added, flushed, not committed).
        organization_id: The owning organisation.
        project_id: The owning project, or `None` for an organisation-level pack.
        name / description: Display text.
        folder: The Reports picker folder (`""` for none).
        definition: The pack definition.
        actor_id: The author.
        comment: A note on this first version.

    Returns:
        The stored pack and version.

    Raises:
        ValueError: A bad name, description or folder, or a project outside the organisation.
        InvalidPackError: The definition is not valid.
        PackNameTakenError: The owner already has a pack of that name.
    """
    name = _clean_name(name)
    _check_text(description, MAX_DESCRIPTION_CHARS, "description")
    folder = clean_folder(folder)
    _check_text(comment, MAX_COMMENT_CHARS, "comment")
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or project.organization_id != organization_id:
            raise ValueError("The project does not belong to the organisation.")
    assert_valid(definition)
    _assert_name_free(db, organization_id, project_id, name)
    pack = ReportPack(
        organization_id=organization_id, project_id=project_id, name=name, description=description, folder=folder,
        current_version=1, created_by=actor_id,
    )
    try:
        with db.begin_nested():  # a savepoint, so a concurrent create of the same name leaves the caller's work intact
            db.add(pack)
            db.flush()
    except IntegrityError as exc:
        raise PackNameTakenError(f'A pack called "{name}" already exists here.') from exc
    version = _add_version(db, pack, 1, definition, actor_id, comment)
    log_event(
        db, entity_type="report_pack", entity_id=pack.id, action="created", actor_id=actor_id,
        organization_id=organization_id, project_id=project_id,
        detail={"version": 1, "definition_hash": version.definition_hash, "entries": len(definition["entries"])},
    )
    return SavedPack(pack, version, True)


def save_version(
    db: Session, pack_id: uuid.UUID, definition: dict[str, Any], *, base_version: int, actor_id: uuid.UUID | None,
    comment: str = "",
) -> SavedPack:
    """Saves `definition` as the pack's next version.

    Raises:
        LookupError: No such pack.
        InvalidPackError: The definition is not valid.
        PackConflictError: The pack is no longer at `base_version`.
    """
    _check_text(comment, MAX_COMMENT_CHARS, "comment")
    pack = db.scalar(select(ReportPack).where(ReportPack.id == pack_id).with_for_update())
    if pack is None:
        raise LookupError("No such pack.")
    assert_valid(definition)
    if pack.current_version != base_version:
        raise PackConflictError(pack.current_version)
    current = get_version(db, pack.id, pack.current_version)
    digest = definition_hash(definition)
    if current is not None and current.definition_hash == digest:
        return SavedPack(pack, current, False)
    number = pack.current_version + 1
    version = _add_version(db, pack, number, definition, actor_id, comment)
    pack.current_version = number
    log_event(
        db, entity_type="report_pack", entity_id=pack.id, action="version_saved", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=pack.project_id,
        detail={"version": number, "definition_hash": digest, "entries": len(definition["entries"])},
    )
    db.flush()
    return SavedPack(pack, version, True)


def update_details(
    db: Session, pack: ReportPack, *, name: str | None = None, description: str | None = None,
    folder: str | None = None, actor_id: uuid.UUID | None,
) -> ReportPack:
    """Renames, re-describes or re-files a pack (not a new version: the definition is unchanged).

    Raises:
        ValueError: A bad name, description or folder.
        PackNameTakenError: The new name is taken.
    """
    changed: list[str] = []
    if name is not None and (new_name := _clean_name(name)) != pack.name:
        _assert_name_free(db, pack.organization_id, pack.project_id, new_name, except_id=pack.id)
        pack.name = new_name
        changed.append("name")
    if description is not None and description != pack.description:
        pack.description = _check_text(description, MAX_DESCRIPTION_CHARS, "description")
        changed.append("description")
    if folder is not None and (new_folder := clean_folder(folder)) != pack.folder:
        pack.folder = new_folder
        changed.append("folder")
    if changed:
        db.flush()
        log_event(
            db, entity_type="report_pack", entity_id=pack.id, action="updated", actor_id=actor_id,
            organization_id=pack.organization_id, project_id=pack.project_id, detail={"fields": changed},
        )
    return pack


def delete_pack(db: Session, pack: ReportPack, *, actor_id: uuid.UUID | None) -> None:
    """Deletes a pack, every version of it and every project's tombstone that hid it."""
    log_event(
        db, entity_type="report_pack", entity_id=pack.id, action="deleted", actor_id=actor_id,
        organization_id=pack.organization_id, project_id=pack.project_id, detail={"versions": pack.current_version},
    )
    definition_suppression.forget_definition(db, PACK_KIND, pack.id)  # no foreign key holds a project's tombstone
    db.execute(delete(ReportPlacement).where(ReportPlacement.report_key == f"pack:{pack.id}"))  # nor a placement
    db.delete(pack)
    db.flush()


def get_version(db: Session, pack_id: uuid.UUID, version: int) -> ReportPackVersion | None:
    """One version of a pack, or `None`."""
    return db.scalar(
        select(ReportPackVersion).where(ReportPackVersion.pack_id == pack_id, ReportPackVersion.version == version)
    )


def current_version(db: Session, pack: ReportPack) -> ReportPackVersion:
    """The pack's current version (a pack always has it)."""
    version = get_version(db, pack.id, pack.current_version)
    assert version is not None
    return version


def list_versions(db: Session, pack_id: uuid.UUID) -> list[ReportPackVersion]:
    """Every version of a pack, newest first."""
    return list(db.scalars(
        select(ReportPackVersion).where(ReportPackVersion.pack_id == pack_id).order_by(ReportPackVersion.version.desc())
    ).all())


def _add_version(
    db: Session, pack: ReportPack, number: int, definition: dict[str, Any], actor_id: uuid.UUID | None, comment: str,
) -> ReportPackVersion:
    version = ReportPackVersion(
        pack_id=pack.id, version=number, schema_version=PACK_SCHEMA_VERSION, definition=definition,
        definition_hash=definition_hash(definition), comment=comment, created_by=actor_id,
    )
    db.add(version)
    db.flush()
    return version


__all__ = [
    "PackConflictError", "PackNameTakenError", "SavedPack", "create_pack", "current_version", "delete_pack", "get_version",
    "list_versions", "save_version", "update_details",
]
