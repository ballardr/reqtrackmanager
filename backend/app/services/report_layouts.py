"""
Module: services.report_layouts

Storing and versioning custom report layouts.

Responsibilities:
- Create a layout with its first version, save further versions, rename or re-describe it, delete it.
- Read the current version, one version, or the version history.
- Validate every tree before it is stored (`report_layout_tree.assert_valid`) and write one audit
  event per change.

Design decisions:
- **Editing never changes a stored version.** A save appends a version; a run pins one by number, so
  provenance stays true (`ReportLayoutVersion` refuses updates).
- **Optimistic concurrency.** A save names the version it was based on; if the layout moved on, it is
  refused (`LayoutConflictError`) instead of silently overwriting a colleague's change. The layout row
  is locked while the next number is chosen, so two saves cannot take the same version.
- A save whose tree hashes the same as the current version stores nothing and returns the current one.
- The audit event carries ids, the version number, the tree hash and counts, never the layout's text.
- Permission to manage layouts is decided by the caller (the endpoint); this module trusts it and
  only checks that a project belongs to the organisation named.

Dependencies: `models.report_layout`, `services.report_layout_tree`, `services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_layout import LAYOUT_FAMILIES, ReportLayout, ReportLayoutVersion
from app.models.report_placement import ReportPlacement
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.report_content import delete_layout_content
from app.services.report_folders import clean_folder
from app.services.report_layout_scope import LAYOUT_KIND
from app.services.report_layout_tree import TREE_SCHEMA_VERSION, assert_valid, tree_hash

MAX_NAME_CHARS = 200
MAX_DESCRIPTION_CHARS = 2000
MAX_COMMENT_CHARS = 500


class LayoutNameTakenError(ValueError):
    """Another layout of the same owner already has this name."""


class LayoutConflictError(ValueError):
    """A save was based on a version that is no longer the current one."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"The layout is now at version {current_version}; reload it and apply your change again.")


@dataclass(frozen=True)
class SavedLayout:
    """A layout together with the version a call stored or returned.

    Attributes:
        layout: The layout row.
        version: The version stored (or, for an unchanged save, the current one).
        changed: Whether a new version was stored.
    """

    layout: ReportLayout
    version: ReportLayoutVersion
    changed: bool


def _clean_name(name: str) -> str:
    """The trimmed name.

    Raises:
        ValueError: Empty or over `MAX_NAME_CHARS`.
    """
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > MAX_NAME_CHARS:
        raise ValueError(f"A layout name is 1 to {MAX_NAME_CHARS} characters.")
    return cleaned


def _check_text(value: str, limit: int, what: str) -> str:
    if len(value) > limit:
        raise ValueError(f"The {what} is at most {limit} characters.")
    return value


def _assert_name_free(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    """Raises `LayoutNameTakenError` when the owner already has a layout called `name` (case-insensitive)."""
    owner = [
        ReportLayout.organization_id == organization_id,
        ReportLayout.project_id.is_(None) if project_id is None else ReportLayout.project_id == project_id,
    ]
    for existing_id, existing_name in db.execute(select(ReportLayout.id, ReportLayout.name).where(*owner)):
        if existing_name.casefold() == name.casefold() and existing_id != except_id:
            raise LayoutNameTakenError(f'A layout called "{name}" already exists here.')


def create_layout(
    db: Session,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    name: str,
    description: str,
    family: str,
    tree: dict[str, Any],
    actor_id: uuid.UUID | None,
    comment: str = "",
    folder: str = "",
) -> SavedLayout:
    """Creates a layout and its version 1.

    Args:
        db: Active session (added, flushed, not committed).
        organization_id: The owning organisation.
        project_id: The owning project, or `None` for an organisation-level layout.
        name / description: Display text.
        folder: The Reports picker folder (`""` for none).
        family: `document` or `table`; fixed for the layout's life.
        tree: The layout tree.
        actor_id: The author.
        comment: A note on this first version.

    Returns:
        The stored layout and version.

    Raises:
        ValueError: A bad name, description, folder, family, or a project outside the organisation.
        InvalidLayoutError: The tree is not valid.
        LayoutNameTakenError: The owner already has a layout of that name.
    """
    name = _clean_name(name)
    _check_text(description, MAX_DESCRIPTION_CHARS, "description")
    folder = clean_folder(folder)
    _check_text(comment, MAX_COMMENT_CHARS, "comment")
    if family not in LAYOUT_FAMILIES:
        raise ValueError(f"The family is one of: {', '.join(LAYOUT_FAMILIES)}.")
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or project.organization_id != organization_id:
            raise ValueError("The project does not belong to the organisation.")
    analysis = assert_valid(tree, family=family)
    _assert_name_free(db, organization_id, project_id, name)

    layout = ReportLayout(
        organization_id=organization_id, project_id=project_id, name=name, description=description, folder=folder,
        family=family, current_version=1, created_by=actor_id,
    )
    try:
        with db.begin_nested():  # a savepoint, so a concurrent create of the same name leaves the caller's work intact
            db.add(layout)
            db.flush()
    except IntegrityError as exc:
        raise LayoutNameTakenError(f'A layout called "{name}" already exists here.') from exc
    version = _add_version(db, layout, 1, tree, actor_id, comment)
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="created", actor_id=actor_id,
        organization_id=organization_id, project_id=project_id,
        detail={"family": family, "version": 1, "tree_hash": version.tree_hash, "blocks": analysis.node_count},
    )
    return SavedLayout(layout, version, True)


def save_version(
    db: Session,
    layout_id: uuid.UUID,
    tree: dict[str, Any],
    *,
    base_version: int,
    actor_id: uuid.UUID | None,
    comment: str = "",
) -> SavedLayout:
    """Saves `tree` as the layout's next version.

    Args:
        db: Active session (flushed, not committed).
        layout_id: The layout.
        tree: The new tree; must be valid and of the layout's family.
        base_version: The version the author started from.
        actor_id: The author.
        comment: A note on this change.

    Returns:
        The stored version, or the current one (`changed` false) when the tree is identical to it.

    Raises:
        LookupError: No such layout.
        InvalidLayoutError: The tree is not valid.
        LayoutConflictError: The layout is no longer at `base_version`.
    """
    _check_text(comment, MAX_COMMENT_CHARS, "comment")
    layout = db.scalar(select(ReportLayout).where(ReportLayout.id == layout_id).with_for_update())
    if layout is None:
        raise LookupError("No such layout.")
    analysis = assert_valid(tree, family=layout.family)
    if layout.current_version != base_version:
        raise LayoutConflictError(layout.current_version)
    current = get_version(db, layout.id, layout.current_version)
    digest = tree_hash(tree)
    if current is not None and current.tree_hash == digest:
        return SavedLayout(layout, current, False)
    number = layout.current_version + 1
    version = _add_version(db, layout, number, tree, actor_id, comment)
    layout.current_version = number
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="version_saved", actor_id=actor_id,
        organization_id=layout.organization_id, project_id=layout.project_id,
        detail={"version": number, "tree_hash": digest, "blocks": analysis.node_count},
    )
    db.flush()
    return SavedLayout(layout, version, True)


def update_details(
    db: Session, layout: ReportLayout, *, name: str | None = None, description: str | None = None,
    folder: str | None = None, actor_id: uuid.UUID | None,
) -> ReportLayout:
    """Renames, re-describes or re-files a layout (not a new version: the tree is unchanged).

    Raises:
        ValueError: A bad name, description or folder.
        LayoutNameTakenError: The new name is taken.
    """
    changed: list[str] = []
    if name is not None and (new_name := _clean_name(name)) != layout.name:
        _assert_name_free(db, layout.organization_id, layout.project_id, new_name, except_id=layout.id)
        layout.name = new_name
        changed.append("name")
    if description is not None and description != layout.description:
        layout.description = _check_text(description, MAX_DESCRIPTION_CHARS, "description")
        changed.append("description")
    if folder is not None and (new_folder := clean_folder(folder)) != layout.folder:
        layout.folder = new_folder
        changed.append("folder")
    if changed:
        db.flush()
        log_event(
            db, entity_type="report_layout", entity_id=layout.id, action="updated", actor_id=actor_id,
            organization_id=layout.organization_id, project_id=layout.project_id, detail={"fields": changed},
        )
    return layout


def delete_layout(db: Session, layout: ReportLayout, *, actor_id: uuid.UUID | None) -> None:
    """Deletes a layout and every version of it, every project's tombstone that hid it and the report content written for it."""
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="deleted", actor_id=actor_id,
        organization_id=layout.organization_id, project_id=layout.project_id,
        detail={"family": layout.family, "versions": layout.current_version},
    )
    definition_suppression.forget_definition(db, LAYOUT_KIND, layout.id)  # no foreign key holds a project's tombstone
    delete_layout_content(db, layout.id)  # nor does the content (introduction, chapters, appendices) written for it
    db.execute(delete(ReportPlacement).where(ReportPlacement.report_key == f"layout:{layout.id}"))  # nor a placement
    db.delete(layout)
    db.flush()


def get_version(db: Session, layout_id: uuid.UUID, version: int) -> ReportLayoutVersion | None:
    """One version of a layout, or `None`."""
    return db.scalar(
        select(ReportLayoutVersion).where(ReportLayoutVersion.layout_id == layout_id, ReportLayoutVersion.version == version)
    )


def list_versions(db: Session, layout_id: uuid.UUID) -> list[ReportLayoutVersion]:
    """Every version of a layout, newest first."""
    return list(db.scalars(
        select(ReportLayoutVersion).where(ReportLayoutVersion.layout_id == layout_id).order_by(ReportLayoutVersion.version.desc())
    ).all())


def _add_version(
    db: Session, layout: ReportLayout, number: int, tree: dict[str, Any], actor_id: uuid.UUID | None, comment: str,
) -> ReportLayoutVersion:
    version = ReportLayoutVersion(
        layout_id=layout.id, version=number, schema_version=TREE_SCHEMA_VERSION, tree=tree,
        tree_hash=tree_hash(tree), comment=comment, created_by=actor_id,
    )
    db.add(version)
    db.flush()
    return version


__all__ = [
    "LayoutConflictError", "LayoutNameTakenError", "SavedLayout", "create_layout", "delete_layout", "get_version",
    "list_versions", "save_version", "update_details",
]
