"""
Module: modules.stakeholders._attachments

Comment-thread and file-attachment operations shared by every artefact in this
module (Persona, Stakeholder). Each artefact has its own module-local tables
(Phase 0 resolution 8), so the operations are parameterised by an
`AttachmentKit` naming those tables rather than copied per artefact.

All operations are scope-agnostic: an artefact is "org-scoped" exactly when its
`organization_id` is set, which decides whether uploads are org shared
resources. Callers pass the audit scope (`project_id=` / `organization_id=`) as
`**scope_ids`, and are responsible for resolving/authorising the artefact and
for any manage-role check on direct files.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.user import User
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file


@dataclass(frozen=True)
class AttachmentKit:
    """The per-artefact pieces the shared comment/file operations need.

    Attributes:
        artefact_type: Registered artefact type, used as the audit
            `entity_type` and in 404 messages' noun via `label`.
        label: Singular display noun, e.g. "Persona".
        comment_model: The artefact's comment table.
        comment_file_model: The artefact's comment-attachment table.
        file_model: The artefact's direct-attachment table.
        fk: Name of the artefact foreign-key attribute on all three tables
            (e.g. "persona_id").
        comment_out: The comment response schema; constructed with `id`, `fk`,
            `author_id`, `author_display_name`, `body`, `created_at`,
            `edited_at` and `attachments`.
        log_filenames: Whether audit events carry the uploaded filename. Off
            for artefacts about identifiable people, where a filename can
            itself be personal data that erasure would otherwise leave behind.
    """

    artefact_type: str
    label: str
    comment_model: Any
    comment_file_model: Any
    file_model: Any
    fk: str
    comment_out: Any
    log_filenames: bool = True

    def file_detail(self, asset: FileAsset) -> dict[str, str]:
        """Audit `detail` for a file event on `asset`."""
        return {"filename": asset.filename} if self.log_filenames else {"file_id": str(asset.id)}


def comment_to_out(db: Session, kit: AttachmentKit, comment: Any):
    """API shape for a comment, with author display name and attachments."""
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset).join(kit.comment_file_model, kit.comment_file_model.file_id == FileAsset.id)
        .where(kit.comment_file_model.comment_id == comment.id)
    ).all()
    return kit.comment_out(**{
        "id": comment.id, kit.fk: getattr(comment, kit.fk), "author_id": comment.author_id,
        "author_display_name": author.display_name if author is not None else "Unknown user",
        "body": comment.body, "created_at": comment.created_at, "edited_at": comment.edited_at,
        "attachments": [FileAssetOut.model_validate(a) for a in attachments],
    })


def get_own_comment(db: Session, kit: AttachmentKit, artefact: Any, comment_id: uuid.UUID, user: User, *, verb: str):
    """Loads a comment on `artefact` that `user` authored.

    Raises:
        HTTPException: 404 if absent, 403 if authored by someone else.
    """
    comment = db.get(kit.comment_model, comment_id)
    if comment is None or getattr(comment, kit.fk) != artefact.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only the comment's author may {verb}.")
    return comment


def add_comment(db: Session, kit: AttachmentKit, artefact: Any, user: User, body: str, **scope_ids):
    """Adds and audit-logs a comment."""
    comment = kit.comment_model(**{kit.fk: artefact.id, "author_id": user.id, "body": body})
    db.add(comment)
    db.flush()
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="comment_added",
              actor_id=user.id, detail={"comment_id": str(comment.id)}, **scope_ids)
    db.commit()
    db.refresh(comment)
    return comment_to_out(db, kit, comment)


def list_comments(db: Session, kit: AttachmentKit, artefact: Any) -> list:
    """Comments on an artefact, oldest first."""
    comments = db.scalars(
        select(kit.comment_model).where(getattr(kit.comment_model, kit.fk) == artefact.id)
        .order_by(kit.comment_model.created_at)
    ).all()
    return [comment_to_out(db, kit, c) for c in comments]


def edit_comment(db: Session, kit: AttachmentKit, artefact: Any, comment_id: uuid.UUID, user: User, body: str, **scope_ids):
    """Author-only edit; audit-logged."""
    comment = get_own_comment(db, kit, artefact, comment_id, user, verb="edit it")
    comment.body = body
    comment.edited_at = datetime.now(UTC)
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="comment_edited",
              actor_id=user.id, detail={"comment_id": str(comment.id)}, **scope_ids)
    db.commit()
    db.refresh(comment)
    return comment_to_out(db, kit, comment)


async def attach_to_comment(
    db: Session, kit: AttachmentKit, artefact: Any, comment_id: uuid.UUID, user: User, file: UploadFile, *,
    organization_id: uuid.UUID, **scope_ids,
) -> FileAsset:
    """Author-only comment attachment. Always an ordinary org upload; a
    project artefact's comment files authorise through the module's
    file-owner hook, an org artefact's through org membership."""
    comment = get_own_comment(db, kit, artefact, comment_id, user, verb="attach a file to it")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=user.id, filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream", data=data,
        is_org_resource=artefact.organization_id is not None,
    )
    db.flush()
    db.add(kit.comment_file_model(comment_id=comment.id, file_id=asset.id, uploaded_by=user.id))
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="comment_file_attached",
              actor_id=user.id, detail=kit.file_detail(asset), **scope_ids)
    db.commit()
    db.refresh(asset)
    return asset


def remove_comment_attachment(
    db: Session, kit: AttachmentKit, artefact: Any, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids
) -> None:
    """Author-only removal of a comment attachment (deletes the file); audit-logged."""
    comment = get_own_comment(db, kit, artefact, comment_id, user, verb="remove its attachments")
    link = db.scalar(
        select(kit.comment_file_model).where(
            kit.comment_file_model.comment_id == comment.id, kit.comment_file_model.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="comment_file_removed",
              actor_id=user.id, detail={"file_id": str(file_id)}, **scope_ids)
    db.commit()


async def attach_file(
    db: Session, kit: AttachmentKit, artefact: Any, user: User, file: UploadFile, *, organization_id: uuid.UUID,
    **scope_ids,
) -> FileAsset:
    """Uploads and links a file to an artefact (caller has checked manage)."""
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=user.id, filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream", data=data,
        is_org_resource=artefact.organization_id is not None,
    )
    db.flush()
    db.add(kit.file_model(**{kit.fk: artefact.id, "file_id": asset.id, "linked_by": user.id, "created_at": asset.created_at}))
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="file_attached",
              actor_id=user.id, detail=kit.file_detail(asset), **scope_ids)
    db.commit()
    db.refresh(asset)
    return asset


def list_files(db: Session, kit: AttachmentKit, artefact: Any) -> list[FileAsset]:
    """Files directly attached to an artefact."""
    return list(db.scalars(
        select(FileAsset).join(kit.file_model, kit.file_model.file_id == FileAsset.id)
        .where(getattr(kit.file_model, kit.fk) == artefact.id)
    ).all())


def unlink_file(db: Session, kit: AttachmentKit, artefact: Any, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    link = db.scalar(
        select(kit.file_model).where(getattr(kit.file_model, kit.fk) == artefact.id, kit.file_model.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File not attached to this {kit.label}.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=kit.artefact_type, entity_id=artefact.id, action="file_unlinked",
              actor_id=user.id, detail={"file_id": str(file_id)}, **scope_ids)
    db.commit()


def resolve_file_project_id(db: Session, kit: AttachmentKit, artefact_model: Any, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project of the **project-scoped**
    artefact it is attached to (directly or via a comment). Org artefacts'
    files are org shared resources and never resolved here."""
    direct = db.scalar(select(kit.file_model).where(kit.file_model.file_id == file_id))
    if direct is not None:
        artefact = db.get(artefact_model, getattr(direct, kit.fk))
        return artefact.project_id if artefact is not None else None
    via_comment = db.scalar(select(kit.comment_file_model).where(kit.comment_file_model.file_id == file_id))
    if via_comment is not None:
        comment = db.get(kit.comment_model, via_comment.comment_id)
        artefact = db.get(artefact_model, getattr(comment, kit.fk)) if comment is not None else None
        return artefact.project_id if artefact is not None else None
    return None
