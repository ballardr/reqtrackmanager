"""
Module: services.report_layouts

Storing and versioning custom report layouts.

Responsibilities:
- Create a layout with its first version, save further versions, rename or re-describe it, delete it.
- Read the current version, one version, or the version history.
- Keep the layout's shared draft (`ReportLayoutDraft`): write it on autosave, discard it, publish it as the next version.
- Validate every tree before it is stored (`report_layout_tree.assert_valid`) and write one audit
  event per change.

Design decisions:
- **Editing never changes a stored version.** A save appends a version; a run pins one by number, so
  provenance stays true (`ReportLayoutVersion` refuses updates).
- **Optimistic concurrency.** A save names the version it was based on; if the layout moved on, it is
  refused (`LayoutConflictError`) instead of silently overwriting a colleague's change. The layout row
  is locked while the next number is chosen, so two saves cannot take the same version.
- A save whose tree hashes the same as the current version stores nothing and returns the current one.
- **A draft is not a version.** It is one mutable row per layout the designer rewrites on autosave; it may be invalid (it is
  checked when published, as a save is), carries a `revision` so a concurrent writer is refused (`DraftConflictError`), and is
  never read by a run, copy or bundle. Writing it is not audited event by event (high-frequency working state that changes no
  run or output); discarding and publishing it are. A draft equal to the saved version is removed rather than stored.
- The audit event carries ids, the version number, the tree hash and counts, never the layout's text.
- Permission to manage layouts is decided by the caller (the endpoint); this module trusts it and
  only checks that a project belongs to the organisation named.

Dependencies: `models.report_layout`, `services.report_layout_tree`, `services.audit`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import LAYOUT_FAMILIES, ReportLayout, ReportLayoutDraft, ReportLayoutVersion
from app.models.report_placement import ReportPlacement
from app.services import definition_suppression
from app.services.audit import log_event
from app.services.report_folders import clean_folder
from app.services.report_images import image_problems
from app.services.report_layout_scope import LAYOUT_KIND
from app.services.report_layout_tree import (
    MAX_TREE_BYTES,
    TREE_SCHEMA_VERSION,
    InvalidLayoutError,
    TreeError,
    assert_valid,
    tree_hash,
    validate_tree,
)
from app.services.report_org_values import organization_colour_names

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


class DraftConflictError(ValueError):
    """A draft write or publish named a revision that is no longer the draft's.

    Attributes:
        draft: The draft as it now stands, or `None` when it was published or discarded meanwhile.
    """

    def __init__(self, draft: ReportLayoutDraft | None) -> None:
        self.draft = draft
        super().__init__("The draft was changed by someone else." if draft is not None else "The draft no longer exists.")


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
        ValueError: A bad name, description, folder, family, or a project outside it.
        InvalidLayoutError: The tree is not valid, or an image block names a picture the layout may not use.
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
    analysis = assert_valid(tree, family=family, organization_colours=_organization_colours(db, organization_id))
    if problems := image_problems(db, organization_id, project_id, tree):
        raise InvalidLayoutError(problems)
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


def _organization_colours(db: Session, organization_id: uuid.UUID) -> list[str]:
    """The names in the organisation's report colour scheme, which a layout's colour words may use."""
    organization = db.get(Organization, organization_id)
    return organization_colour_names(organization) if organization is not None else []


def save_version(
    db: Session,
    layout_id: uuid.UUID,
    tree: dict[str, Any],
    *,
    base_version: int,
    actor_id: uuid.UUID | None,
    comment: str = "",
) -> SavedLayout:
    """Saves `tree` as the layout's next version (any draft the layout has is left alone).

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
    layout = _lock_layout(db, layout_id)
    return _publish(db, layout, tree, base_version=base_version, actor_id=actor_id, comment=comment, from_draft=False)


def publish_draft(
    db: Session, layout_id: uuid.UUID, *, revision: int | None, actor_id: uuid.UUID | None, comment: str = "",
) -> SavedLayout:
    """Publishes the layout's draft as its next version and removes the draft, in the caller's transaction.

    The draft may have been written by someone else (it is shared); the new version's author is `actor_id`. A draft equal to the
    current version stores no version but is still removed. A failure leaves the draft in place.

    Args:
        db: Active session (flushed, not committed).
        layout_id: The layout.
        revision: The draft revision the publisher saw, or `None` to publish whatever the draft now holds.
        actor_id: The publisher.
        comment: A note on the new version.

    Raises:
        LookupError: No such layout, or it has no draft.
        DraftConflictError: The draft is no longer at `revision`.
        InvalidLayoutError: The draft is not valid.
        LayoutConflictError: The layout has moved on from the version the draft was based on.
    """
    _check_text(comment, MAX_COMMENT_CHARS, "comment")
    layout = _lock_layout(db, layout_id)
    draft = get_draft(db, layout.id)
    if draft is None:
        raise LookupError("The layout has no draft.")
    if revision is not None and revision != draft.revision:
        raise DraftConflictError(draft)
    saved = _publish(db, layout, draft.tree, base_version=draft.base_version, actor_id=actor_id, comment=comment, from_draft=True)
    db.delete(draft)
    db.flush()
    return saved


def _lock_layout(db: Session, layout_id: uuid.UUID) -> ReportLayout:
    """The layout row, locked for the rest of the transaction (so two saves cannot take the same version number)."""
    layout = db.scalar(select(ReportLayout).where(ReportLayout.id == layout_id).with_for_update())
    if layout is None:
        raise LookupError("No such layout.")
    return layout


def _publish(
    db: Session, layout: ReportLayout, tree: dict[str, Any], *, base_version: int, actor_id: uuid.UUID | None, comment: str,
    from_draft: bool,
) -> SavedLayout:
    """Validates `tree` and appends it as the next version unless it equals the current one."""
    analysis = assert_valid(tree, family=layout.family, organization_colours=_organization_colours(db, layout.organization_id))
    if problems := image_problems(db, layout.organization_id, layout.project_id, tree):
        raise InvalidLayoutError(problems)
    if layout.current_version != base_version:
        raise LayoutConflictError(layout.current_version)
    current = get_version(db, layout.id, layout.current_version)
    digest = tree_hash(tree)
    if current is not None and current.tree_hash == digest:
        return SavedLayout(layout, current, False)
    number = layout.current_version + 1
    version = _add_version(db, layout, number, tree, actor_id, comment)
    layout.current_version = number
    detail: dict[str, Any] = {"version": number, "tree_hash": digest, "blocks": analysis.node_count}
    if from_draft:
        detail["from_draft"] = True
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="version_saved", actor_id=actor_id,
        organization_id=layout.organization_id, project_id=layout.project_id, detail=detail,
    )
    db.flush()
    return SavedLayout(layout, version, True)


def get_draft(db: Session, layout_id: uuid.UUID) -> ReportLayoutDraft | None:
    """The layout's draft, or `None`."""
    return db.scalar(select(ReportLayoutDraft).where(ReportLayoutDraft.layout_id == layout_id))


def write_draft(
    db: Session, layout_id: uuid.UUID, tree: dict[str, Any], *, base_version: int, revision: int, actor_id: uuid.UUID | None,
) -> ReportLayoutDraft | None:
    """Autosaves `tree` into the layout's draft, creating it, replacing it, or removing it when the tree equals the saved version.

    The tree is stored as given, valid or not (`draft_problems` reports what is wrong); only its size is bounded. Writing a
    draft is not audited (see the module notes) and the tree is never logged.

    Args:
        db: Active session (flushed, not committed).
        layout_id: The layout.
        tree: The tree the editor holds.
        base_version: The layout version the editor's content is based on. A new draft must be based on the current version.
        revision: The revision of the draft the editor last saw or loaded, `0` when it saw none.

    Returns:
        The stored draft, or `None` when the tree equals the saved version and no draft is kept.

    Raises:
        LookupError: No such layout.
        ValueError: The tree is over `MAX_TREE_BYTES`, or `base_version` is not a version of the layout.
        DraftConflictError: The draft is not at `revision` (another editor wrote, published or discarded it).
        LayoutConflictError: A new draft was based on a version that is no longer the current one.
    """
    layout = _lock_layout(db, layout_id)
    draft = get_draft(db, layout.id)
    if (draft.revision if draft is not None else 0) != revision:
        raise DraftConflictError(draft)
    if not 1 <= base_version <= layout.current_version:
        raise ValueError(f"The base version is between 1 and {layout.current_version}.")
    if draft is None and base_version != layout.current_version:
        raise LayoutConflictError(layout.current_version)
    if len(json.dumps(tree, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > MAX_TREE_BYTES:
        raise ValueError(f"The layout is too large (the limit is {MAX_TREE_BYTES} bytes).")
    digest = tree_hash(tree)
    current = get_version(db, layout.id, layout.current_version)
    if base_version == layout.current_version and current is not None and current.tree_hash == digest:
        if draft is not None:
            db.delete(draft)
            db.flush()
        return None
    if draft is None:
        draft = ReportLayoutDraft(layout_id=layout.id, tree=tree, tree_hash=digest, base_version=base_version, revision=1)
        db.add(draft)
    else:
        draft.tree, draft.tree_hash, draft.base_version, draft.revision = tree, digest, base_version, draft.revision + 1
    draft.updated_by, draft.updated_at = actor_id, utcnow()
    db.flush()
    return draft


def discard_draft(db: Session, layout_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> None:
    """Deletes the layout's draft (the work in it is lost) and audits it, with no tree content.

    Raises:
        LookupError: No such layout, or it has no draft.
    """
    layout = _lock_layout(db, layout_id)
    draft = get_draft(db, layout.id)
    if draft is None:
        raise LookupError("The layout has no draft.")
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="draft_discarded", actor_id=actor_id,
        organization_id=layout.organization_id, project_id=layout.project_id,
        detail={"base_version": draft.base_version, "revision": draft.revision, "tree_hash": draft.tree_hash},
    )
    db.delete(draft)
    db.flush()


def draft_problems(db: Session, layout: ReportLayout, draft: ReportLayoutDraft) -> list[TreeError]:
    """Why the draft could not be published now (empty when it can): the tree's own problems, then its pictures."""
    errors = validate_tree(
        draft.tree, family=layout.family, organization_colours=_organization_colours(db, layout.organization_id),
    ).errors
    return errors or image_problems(db, layout.organization_id, layout.project_id, draft.tree)


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
    """Deletes a layout and every version of it, and every project's tombstone that hid it."""
    log_event(
        db, entity_type="report_layout", entity_id=layout.id, action="deleted", actor_id=actor_id,
        organization_id=layout.organization_id, project_id=layout.project_id,
        detail={"family": layout.family, "versions": layout.current_version},
    )
    definition_suppression.forget_definition(db, LAYOUT_KIND, layout.id)  # no foreign key holds a project's tombstone
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
    "DraftConflictError", "LayoutConflictError", "LayoutNameTakenError", "SavedLayout", "create_layout", "delete_layout",
    "discard_draft", "draft_problems", "get_draft", "get_version", "list_versions", "publish_draft", "save_version",
    "update_details", "write_draft",
]
