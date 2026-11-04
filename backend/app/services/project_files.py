"""
Module: services.project_files

The rows of a project's Files page (`GET/POST /projects/{id}/files`) and the filters that narrow them.

Responsibilities:
- Gather the files a project owns from each place they hang: requirement attachments, action attachments, comment
  attachments on a requirement, and the project's report image library.
- Apply the page's filters (file name, source, file type, uploader, upload window) in SQL, so a narrowed list never
  loads the rest of the project's files.
- Classify a file by its content type into the page's coarse file types (`image`, `document`, `other`).

Design decisions:
- **One project at a time.** `rows_for` reads exactly one project's joins, each filtering on that project's own id,
  so a file of another project can never appear; widening to related projects is `ProjectScope.collect`'s job.
- **Library pictures belong to the project through `FileAsset.project_id`**, are listed once each, and carry no
  record. The confidential mark does not hide them from the project's members: it only stops a report printing
  them (`models.file`), the same rule the library itself applies.
- **The file name typed in the search is customer text.** It reaches this module as a parameter of a POST body and is
  used only as a bound `ILIKE` pattern (wildcards escaped); it is never logged, audited or put in an exception.
- **The upload window is a pair of UTC instants** (`uploaded_from` inclusive, `uploaded_before` exclusive) that the
  browser derives from the person's local days, because the server cannot know the person's timezone from the
  calendar day alone.

Dependencies: SQLAlchemy models for the attachment link tables and `schemas.file` for the row shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, and_, not_, or_, select
from sqlalchemy.orm import Session

from app.models.change_request import ReviewComment
from app.models.enums import ReviewTargetType
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.file import FileAssetOut, ProjectFileOut

FileSource = Literal["requirement_attachment", "action_attachment", "comment_attachment", "report_image"]
FileKind = Literal["image", "document", "other"]

#: Every source, in the order the page offers them.
FILE_SOURCES: tuple[FileSource, ...] = ("requirement_attachment", "action_attachment", "comment_attachment", "report_image")

#: Content types (besides `text/*` and the Office and OpenDocument families) the page calls a document.
_DOCUMENT_TYPES = ("application/pdf", "application/msword", "application/rtf", "application/vnd.ms-excel", "application/vnd.ms-powerpoint")
_DOCUMENT_PREFIXES = (
    "text/", "application/vnd.openxmlformats-officedocument.", "application/vnd.oasis.opendocument.",
)


@dataclass(frozen=True)
class FileFilters:
    """What narrows the Files page. Every field is optional; the default keeps everything.

    Attributes:
        search: A substring of the file name (case-insensitive). Customer text: never logged.
        sources: Only these sources; empty keeps all of them.
        kind: Only this file type, or `None` for all.
        uploaded_by: Only files this user uploaded.
        uploaded_from: Only files uploaded at or after this instant.
        uploaded_before: Only files uploaded before this instant.
    """

    search: str = ""
    sources: frozenset[str] = field(default_factory=frozenset)
    kind: FileKind | None = None
    uploaded_by: uuid.UUID | None = None
    uploaded_from: datetime | None = None
    uploaded_before: datetime | None = None

    def wants(self, source: str) -> bool:
        """Whether a source is listed under this filter."""
        return not self.sources or source in self.sources


def _is_document() -> ColumnElement[bool]:
    return or_(
        FileAsset.content_type.in_(_DOCUMENT_TYPES),
        *(FileAsset.content_type.like(f"{prefix}%") for prefix in _DOCUMENT_PREFIXES),
    )


def _is_image() -> ColumnElement[bool]:
    return FileAsset.content_type.like("image/%")


def _file_conditions(filters: FileFilters) -> list[ColumnElement[bool]]:
    """The `FileAsset` conditions of a filter (the source is chosen by which query runs)."""
    conditions: list[ColumnElement[bool]] = []
    needle = filters.search.strip()
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(FileAsset.filename.ilike(f"%{escaped}%", escape="\\"))
    if filters.kind == "image":
        conditions.append(_is_image())
    elif filters.kind == "document":
        conditions.append(and_(not_(_is_image()), _is_document()))
    elif filters.kind == "other":
        conditions.append(and_(not_(_is_image()), not_(_is_document())))
    if filters.uploaded_by is not None:
        conditions.append(FileAsset.uploaded_by == filters.uploaded_by)
    if filters.uploaded_from is not None:
        conditions.append(FileAsset.created_at >= filters.uploaded_from)
    if filters.uploaded_before is not None:
        conditions.append(FileAsset.created_at < filters.uploaded_before)
    return conditions


def project_file_rows(db: Session, project_id: uuid.UUID, filters: FileFilters | None = None) -> list[ProjectFileOut]:
    """One project's files, newest first.

    Args:
        db: Active session (read only).
        project_id: The project; only files hanging from its own records or its own library are returned.
        filters: What narrows the list (default: nothing).

    Returns:
        One row per file per place it hangs (a file linked to two requirements is two rows), newest link first.
    """
    filters = filters or FileFilters()
    conditions = _file_conditions(filters)
    entries: list[dict] = []

    if filters.wants("requirement_attachment"):
        for asset, linked_at, req_id, req_code, req_name in db.execute(
            select(FileAsset, RequirementFile.created_at, Requirement.id, Requirement.unique_code, RequirementVersion.name)
            .join(RequirementFile, RequirementFile.file_id == FileAsset.id)
            .join(Requirement, Requirement.id == RequirementFile.requirement_id)
            .join(
                RequirementVersion,
                (RequirementVersion.requirement_id == Requirement.id) & (RequirementVersion.valid_to.is_(None)),
            )
            .where(Requirement.project_id == project_id, *conditions)
        ).all():
            entries.append({
                "file": asset, "linked_at": linked_at, "source": "requirement_attachment",
                "requirement_id": req_id, "requirement_unique_code": req_code, "requirement_name": req_name,
            })

    # Joined directly on RequirementAction.project_id rather than via a linked requirement: an action may be linked
    # to zero, one, or several requirements (via untyped `ArtefactLink` rows), so it has no single owning requirement.
    if filters.wants("action_attachment"):
        for asset, linked_at, action_id, action_code, action_title in db.execute(
            select(FileAsset, RequirementActionFile.created_at, RequirementAction.id, RequirementAction.unique_code, RequirementAction.title)
            .join(RequirementActionFile, RequirementActionFile.file_id == FileAsset.id)
            .join(RequirementAction, RequirementAction.id == RequirementActionFile.action_id)
            .where(RequirementAction.project_id == project_id, *conditions)
        ).all():
            entries.append({
                "file": asset, "linked_at": linked_at, "source": "action_attachment",
                "action_id": action_id, "action_unique_code": action_code, "action_title": action_title,
            })

    if filters.wants("comment_attachment"):
        for asset, uploaded_at, comment_id, req_id, req_code, req_name in db.execute(
            select(FileAsset, CommentFile.created_at, ReviewComment.id, Requirement.id, Requirement.unique_code, RequirementVersion.name)
            .join(CommentFile, CommentFile.file_id == FileAsset.id)
            .join(ReviewComment, ReviewComment.id == CommentFile.comment_id)
            .join(
                Requirement,
                (Requirement.id == ReviewComment.target_id) & (ReviewComment.target_type == ReviewTargetType.REQUIREMENT),
            )
            .join(
                RequirementVersion,
                (RequirementVersion.requirement_id == Requirement.id) & (RequirementVersion.valid_to.is_(None)),
            )
            .where(Requirement.project_id == project_id, *conditions)
        ).all():
            entries.append({
                "file": asset, "linked_at": uploaded_at, "source": "comment_attachment",
                "requirement_id": req_id, "requirement_unique_code": req_code, "requirement_name": req_name,
                "comment_id": comment_id,
            })

    # The project's report image library: pictures owned by the project itself, attached to no record.
    if filters.wants("report_image"):
        for asset in db.scalars(
            select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.is_org_resource.is_(False), *conditions)
        ):
            entries.append({"file": asset, "linked_at": asset.created_at, "source": "report_image"})

    entries.sort(key=lambda e: e["linked_at"], reverse=True)

    uploader_ids = {e["file"].uploaded_by for e in entries}
    uploader_names: dict[uuid.UUID, str] = (
        {uid: name for uid, name in db.execute(select(User.id, User.display_name).where(User.id.in_(uploader_ids)))}
        if uploader_ids else {}
    )
    return [
        ProjectFileOut(
            file=FileAssetOut.model_validate(e["file"]),
            uploaded_by_display_name=uploader_names.get(e["file"].uploaded_by, ""),
            source=e["source"],
            requirement_id=e.get("requirement_id"),
            requirement_unique_code=e.get("requirement_unique_code"),
            requirement_name=e.get("requirement_name"),
            action_id=e.get("action_id"),
            action_unique_code=e.get("action_unique_code"),
            action_title=e.get("action_title"),
            comment_id=e.get("comment_id"),
        )
        for e in entries
    ]


def row_identity(row: ProjectFileOut) -> tuple:
    """A row's identity across a widened list: a file may hang from several records, so its origin is part of it."""
    return (row.file.id, row.source, row.requirement_id, row.action_id, row.comment_id)


def project_uploaders(db: Session, project_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """The people who uploaded any file in the project, for the page's "Uploaded by" choices.

    Args:
        db: Active session (read only).
        project_id: The project.

    Returns:
        `(user id, display name)` pairs, sorted by name (case-insensitive).
    """
    seen: dict[uuid.UUID, str] = {}
    for row in project_file_rows(db, project_id):
        seen.setdefault(row.file.uploaded_by, row.uploaded_by_display_name)
    return sorted(seen.items(), key=lambda pair: pair[1].lower())
