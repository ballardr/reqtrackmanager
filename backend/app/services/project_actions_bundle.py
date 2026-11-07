"""
Module: services.project_actions_bundle

Requirement actions in a project bundle: the project's own action types, every action with its comments,
attachments, tags and component placements, and the links between actions and requirements.

Responsibilities:
- `export_project_actions`: the `action_types`, `actions` and `action_links` sections of `project.json`, collecting
  the attachments' `FileAsset`s so the bundle embeds their bytes.
- `import_project_actions`: recreates them in a new project, after its requirements exist.
- `import_project_action_types`: the action types a new project starts with (the bundle's own, else the defaults).

Design decisions (Decided by: Agent):
- An action keeps its `unique_code` (`ACT-003`), as a requirement does, so a link by code and a person's reference
  still mean the same record; the project's action counter is moved past the imported codes. A code that is missing,
  malformed or repeated is numbered afresh with a warning.
- Action types are exported by name, and an action refers to its type by name. A type the action uses but the bundle
  does not list as the project's own (a child project's action may use its parent's type) is created in the new
  project, which has no parent, so the action keeps a valid type.
- A bundle written before actions were carried has no `actions` section: it imports as before, with the default
  action types and no actions.
- Links reuse `services.bundle_links`: an end is an action (by code) or a requirement (by code). A link to a record
  of another module is carried by that module's own bundle, which does not know actions, so it is left out, as every
  cross-module link already is.
- Comments carry author, text and attachments; reactions are not carried (as for requirement comments).

External dependencies: `services.bundle_common` (users, files), `services.bundle_links`, `services.tags`,
`services.placements`, `services.actions` (code numbering), `services.definitions` (default types).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ReviewComment
from app.models.enums import ArtefactType, RequirementActionOutcome, ReviewTargetType
from app.models.file import CommentFile, FileAsset, RequirementActionFile
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.services.actions import generate_unique_code
from app.services.bundle_common import (
    BundleImportWarnings,
    UserResolver,
    export_file_links,
    import_bundled_file,
    import_file_links,
    prime_file_links,
)
from app.services.bundle_links import export_artefact_links, import_artefact_links
from app.services.definitions import seed_action_types
from app.services.placements import prime_record_placements, record_placements, restore_record_placements
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags

ACTION_ARTEFACT_TYPE = ArtefactType.REQUIREMENT_ACTION.value
_CODE = re.compile(r"^ACT-(\d+)$")


def _iso(value: datetime | date | None) -> str | None:
    """A date or instant as ISO 8601 text, or `None`."""
    return value.isoformat() if value is not None else None


def _instant(value: str | None) -> datetime | None:
    """An instant from its ISO 8601 text, or `None`."""
    return datetime.fromisoformat(value) if value else None


def export_project_actions(db: Session, project: Project, assets: dict[uuid.UUID, FileAsset]) -> dict[str, Any]:
    """The project's action types, actions and action links as bundle sections.

    Args:
        db: Active session (read only); an export reads each kind of thing once, not once per action.
        project: The project exported.
        assets: Filled with every attachment's `FileAsset`, by id, so the bundle embeds its bytes.

    Returns:
        `{"action_types": [...], "actions": [...], "action_links": [...]}`.
    """
    own_types = list(
        db.scalars(
            select(ActionTypeDefinition).where(ActionTypeDefinition.project_id == project.id)
            .order_by(ActionTypeDefinition.sort_order)
        )
    )
    actions = list(
        db.scalars(
            select(RequirementAction).where(RequirementAction.project_id == project.id).order_by(RequirementAction.unique_code)
        )
    )
    ids = [a.id for a in actions]
    type_names = {t.id: t.name for t in own_types}
    missing = {a.action_type_id for a in actions} - set(type_names)
    if missing:
        type_names.update({t.id: t.name for t in db.scalars(select(ActionTypeDefinition).where(ActionTypeDefinition.id.in_(missing)))})

    comments_by_action: dict[uuid.UUID, list[ReviewComment]] = {}
    attachments_by_comment: dict[uuid.UUID, list[dict[str, Any]]] = {}
    people = {a.creator_id for a in actions} | {a.completed_by for a in actions if a.completed_by} | {
        a.archived_by for a in actions if a.archived_by
    }
    if ids:
        for comment in db.scalars(
            select(ReviewComment).where(ReviewComment.target_type == ReviewTargetType.ACTION, ReviewComment.target_id.in_(ids))
            .order_by(ReviewComment.created_at)
        ):
            comments_by_action.setdefault(comment.target_id, []).append(comment)
            people.add(comment.author_id)
        comment_ids = [c.id for rows in comments_by_action.values() for c in rows]
        if comment_ids:
            for comment_file, asset, uploader in db.execute(
                select(CommentFile, FileAsset, User)
                .join(FileAsset, FileAsset.id == CommentFile.file_id)
                .join(User, User.id == CommentFile.uploaded_by)
                .where(CommentFile.comment_id.in_(comment_ids))
            ).all():
                assets[asset.id] = asset
                attachments_by_comment.setdefault(comment_file.comment_id, []).append({
                    "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
                    "content_type": asset.content_type, "uploaded_by_email": uploader.email,
                })
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(people)))} if people else {}

    prime_record_tag_names(db, ACTION_ARTEFACT_TYPE, ids)
    prime_record_placements(db, ACTION_ARTEFACT_TYPE, ids)
    prime_file_links(db, RequirementActionFile, "action_id", ids)

    def email(user_id: uuid.UUID | None) -> str | None:
        return emails.get(user_id) if user_id else None

    rows = [
        {
            "unique_code": a.unique_code, "title": a.title, "description": a.description,
            "action_type": type_names.get(a.action_type_id), "outcome_status": a.outcome_status.value,
            "assignee": principal_to_bundle(db, a.assignee_type, a.assignee_id), "due_date": _iso(a.due_date),
            "completed_at": _iso(a.completed_at), "completed_by_email": email(a.completed_by),
            "creator_email": email(a.creator_id), "created_at": _iso(a.created_at),
            "is_archived": a.is_archived, "archived_at": _iso(a.archived_at), "archived_by_email": email(a.archived_by),
            "attachments": export_file_links(db, RequirementActionFile, "action_id", a.id, assets),
            "comments": [
                {
                    "author_email": email(c.author_id), "body": c.body, "created_at": _iso(c.created_at),
                    "edited_at": _iso(c.edited_at), "attachments": attachments_by_comment.get(c.id, []),
                }
                for c in comments_by_action.get(a.id, [])
            ],
            "tags": record_tag_names(db, ACTION_ARTEFACT_TYPE, a.id),
            "placements": record_placements(db, ACTION_ARTEFACT_TYPE, a.id),
        }
        for a in actions
    ]
    return {
        "action_types": [{"name": t.name, "sort_order": t.sort_order} for t in own_types],
        "actions": rows,
        "action_links": export_artefact_links(db, project, {ACTION_ARTEFACT_TYPE: {a.id: a.unique_code for a in actions}}),
    }


def import_project_action_types(db: Session, project: Project, data: dict[str, Any]) -> None:
    """Gives a new project its action types: the bundle's own when it lists any, else the defaults a new
    project starts with (a bundle written before action types were carried lists none).

    Args:
        db: Active session; rows are added and flushed, not committed.
        project: The new project.
        data: The bundle's `project.json`.
    """
    listed = data.get("action_types") or []
    if not listed:
        seed_action_types(db, project.id)
        return
    for entry in listed:
        db.add(ActionTypeDefinition(project_id=project.id, name=entry["name"], sort_order=entry.get("sort_order", 0)))
    db.flush()


def import_project_actions(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the bundle's actions, their links to requirements and everything attached to them.

    Call after the project's requirements exist (links name them by code) and after
    `import_project_action_types`.

    Args:
        db: Active session; rows are added and flushed, not committed.
        project: The new project.
        data: The bundle's `project.json`.
        file_bytes_by_ref: Every embedded file's bytes, by `file_ref`.
        current_user: The importing user (creator or uploader when the original cannot be matched).
        users: The import's user resolver.
        warnings: Collects each thing that could not be recreated as it was.
    """
    entries = data.get("actions") or []
    if not entries:
        return
    types = {t.name: t.id for t in db.scalars(select(ActionTypeDefinition).where(ActionTypeDefinition.project_id == project.id))}
    ids_by_code: dict[str, uuid.UUID] = {}
    taken: set[str] = set()
    codes: list[str] = []
    highest = 0
    for entry in entries:
        type_name = entry.get("action_type") or "Review"
        if type_name not in types:
            created = ActionTypeDefinition(project_id=project.id, name=type_name[:100], sort_order=len(types))
            db.add(created)
            db.flush()
            types[type_name] = created.id
        code = entry.get("unique_code") or ""
        match = _CODE.match(code)
        if match is None or code in taken:
            code = ""
        else:
            highest = max(highest, int(match.group(1)))
            taken.add(code)
        codes.append(code)
    project.next_action_seq = max(project.next_action_seq, highest + 1)

    for entry, code in zip(entries, codes, strict=True):
        context = f"Action {entry.get('unique_code') or entry['title']!r}"
        if not code:
            code = generate_unique_code(project)
            warnings.add(f"{context}: its code was missing or repeated, so it was numbered afresh as {code}.")
        action = RequirementAction(
            project_id=project.id, unique_code=code, action_type_id=types[entry.get("action_type") or "Review"],
            title=entry["title"], description=entry.get("description", ""),
            outcome_status=RequirementActionOutcome(entry.get("outcome_status", RequirementActionOutcome.PENDING.value)),
            **principal_columns_from_bundle(
                db, entry, "assignee", organization_id=project.organization_id, project_id=project.id, users=users,
                warnings=warnings, context=f"{context} assignee", required=False,
            ),
            due_date=date.fromisoformat(entry["due_date"]) if entry.get("due_date") else None,
            completed_at=_instant(entry.get("completed_at")),
            completed_by=users.resolve(entry.get("completed_by_email"), required=False, context=f"{context} completer"),
            creator_id=users.resolve(entry.get("creator_email"), required=True, context=f"{context} creator"),
            is_archived=entry.get("is_archived", False), archived_at=_instant(entry.get("archived_at")),
            archived_by=users.resolve(entry.get("archived_by_email"), required=False, context=f"{context} archiver"),
        )
        created_at = _instant(entry.get("created_at"))
        if created_at is not None:
            action.created_at = created_at
        db.add(action)
        db.flush()
        ids_by_code[code] = action.id
        for comment_entry in entry.get("comments", []):
            comment = ReviewComment(
                target_type=ReviewTargetType.ACTION, target_id=action.id,
                author_id=users.resolve(comment_entry.get("author_email"), required=True, context=f"{context} comment author"),
                body=comment_entry["body"], edited_at=_instant(comment_entry.get("edited_at")),
            )
            db.add(comment)
            db.flush()
            for attachment in comment_entry.get("attachments", []):
                content = file_bytes_by_ref.get(attachment["file_ref"])
                if content is None:
                    continue
                uploader = users.resolve(attachment.get("uploaded_by_email"), required=False, context=f"{context} attachment uploader")
                asset = import_bundled_file(
                    db, organization_id=project.organization_id, uploaded_by=uploader or current_user.id,
                    filename=attachment["filename"], content_type=attachment.get("content_type") or "application/octet-stream",
                    data=content,
                )
                db.add(CommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=uploader or current_user.id))
        import_file_links(
            db, organization_id=project.organization_id, file_model=RequirementActionFile, fk="action_id", record_id=action.id,
            entries=entry.get("attachments", []), file_bytes_by_ref=file_bytes_by_ref, current_user=current_user,
            users=users, context=context,
        )
        restore_record_tags(
            db, organization_id=project.organization_id, record_project_id=project.id, actor_id=current_user.id,
            artefact_type=ACTION_ARTEFACT_TYPE, artefact_id=action.id, names=entry.get("tags"),
        )
        restore_record_placements(
            db, project_id=project.id, actor_id=current_user.id,
            artefact_type=ACTION_ARTEFACT_TYPE, artefact_id=action.id, entries=entry.get("placements"),
        )

    import_artefact_links(
        db, project, data.get("action_links") or [], {ACTION_ARTEFACT_TYPE: ids_by_code}, current_user, users, warnings,
        context="Actions",
    )
