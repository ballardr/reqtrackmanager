"""
Module: services.markdown_images

The pictures inside a record's Markdown text: `![alt](attachment:<file id>)`, an attachment of the same record.

Responsibilities:
- `attached_file_ids` / `require_attached`: decide which referenced files really are attachments of the record whose
  field holds the reference (the one integrity rule of a picture), through the type's `RecordAttachmentProvider`.
- `importing_images` / `ImageImport`: carry a reference through a project bundle import. The bundle's text names the
  *source* file ids; an import creates new files, so the references are rewritten to the new ids once the records and
  their attachments exist, and a picture whose file did not arrive becomes its alternative text.

Design decisions:
- A picture is never an outside address and never another record's file: reading a record makes no request to another
  site, the confidential mark and the record's access rules decide who sees a file, and a bundle already carries the
  record's attachments.
- The check runs in the Markdown write hook (`services.markdown_fields`), so every path that stores a field (endpoint,
  file import, MCP tool, seed) is held to it. A record that does not exist yet has no attachments, so it can hold no
  picture; pictures are added when a record is edited.
- An import cannot be checked at write time (the records are written before their attachments), so the hook defers the
  check to `ImageImport.finish`, which maps each source id to the new file with the same name and bytes that is attached
  to the same record, rewrites the text, and then lets the ordinary check run. A source file that is not in the bundle
  (or a project imported without files) leaves the picture's alternative text in its place, never a dangling reference.
- Matching on name and bytes (not on a per-call-site id) means no attachment import path needs to know about pictures.

Dependencies: `modules.registry` (the declarations and attachment providers), `models.file`, SQLAlchemy.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.registry import MarkdownField, MarkdownImages, get_record_attachment_providers
from app.services.markdown_text import ATTACHMENT_SCHEME, image_references

_ContentKey = tuple[str, str]

_active: ContextVar[ImageImport | None] = ContextVar("markdown_image_import", default=None)


def attached_file_ids(db: Session, images: MarkdownImages, record_id: uuid.UUID | None, file_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """
    The files among `file_ids` that are attached to the record.

    Args:
        db: Active session (read only; autoflush is off for the read, so it is safe inside a flush hook).
        images: The field's declaration (the record's type).
        record_id: The record's id, `None` for a record that is not stored yet (it has no attachments).
        file_ids: The referenced files.

    Returns:
        The subset that has a row in the type's attachment table for this record.
    """
    wanted = set(file_ids)
    if record_id is None or not wanted:
        return set()
    provider = get_record_attachment_providers()[images.artefact_type]
    with db.no_autoflush:
        return set(db.scalars(
            select(provider.link.file_id).where(provider.record_column == record_id, provider.link.file_id.in_(wanted)),
        ))


def require_attached(
    db: Session, field_declaration: MarkdownField, instance: Any, text: str, *, name: str, unchanged: str = "",
) -> None:
    """
    Refuses a text whose pictures are not all attachments of the record that holds it.

    Args:
        db: Active session.
        field_declaration: The Markdown field (must carry `images`).
        instance: The ORM row that holds the text.
        text: The value being stored.
        name: The field's display name, for the message.
        unchanged: The value before this edit; a picture already in it is not checked again, so a file removed from the
            record does not stop an edit of the rest of the text.

    Raises:
        HTTPException: 422 when a picture names a file that is not attached to the record.
    """
    images = field_declaration.images
    if images is None:
        return
    refs = {ref.file_id for ref in image_references(text)} - {ref.file_id for ref in image_references(unchanged)}
    if not refs:
        return
    record_id = images.record_of(instance)
    missing = refs - attached_file_ids(db, images, record_id, refs)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{name} has a picture that is not an attachment of this record. Attach the file to the record first.",
        )


def _content_key(filename: str, data: bytes) -> _ContentKey:
    """What identifies a bundled file across an import: its name and the hash of its bytes."""
    return filename, hashlib.sha256(data).hexdigest()


@dataclass
class ImageImport:
    """One bundle import's picture bookkeeping (see the module docstring).

    Attributes:
        sources: Source file id → content key, for every file the bundle embeds.
        created: Content key → the new files created from it, in order.
        pending: The `(row, attribute, declaration)` of every stored text that holds a picture.
        finished: Set by `finish`; from then on the hook checks normally.
    """

    sources: dict[uuid.UUID, _ContentKey] = field(default_factory=dict)
    created: dict[_ContentKey, list[uuid.UUID]] = field(default_factory=dict)
    pending: list[tuple[Any, str, MarkdownField]] = field(default_factory=list)
    finished: bool = False

    def note_file(self, filename: str, data: bytes, new_id: uuid.UUID) -> None:
        """Records that the bundle file with this name and content now exists as `new_id`."""
        self.created.setdefault(_content_key(filename, data), []).append(new_id)

    def defer(self, instance: Any, name: str, declaration: MarkdownField) -> None:
        """Holds a stored text's check until its attachments exist."""
        self.pending.append((instance, name, declaration))

    def finish(self, db: Session) -> None:
        """Rewrites every deferred text to the new file ids (or the picture's alternative text) and checks it.

        Args:
            db: The import's session; flushed (so the records and their attachment links exist) before reading them.
        """
        db.flush()
        self.finished = True
        for instance, name, declaration in self.pending:
            assert declaration.images is not None
            text = getattr(instance, name) or ""
            refs = {ref.file_id for ref in image_references(text)}
            record_id = declaration.images.record_of(instance)
            options = {
                old: self.created.get(self.sources.get(old, ("", "")), []) for old in refs
            }
            attached = attached_file_ids(db, declaration.images, record_id, [n for ids in options.values() for n in ids])
            for old in refs:
                new = next((candidate for candidate in options[old] if candidate in attached), None)
                text = _replace_picture(text, old, new)
            setattr(instance, name, text)
        self.pending.clear()
        db.flush()


def _replace_picture(text: str, old: uuid.UUID, new: uuid.UUID | None) -> str:
    """`text` with the pictures of file `old` pointing at `new`, or (no `new`) replaced by their alternative text."""
    pattern = re.compile(
        r"!\[((?:[^\]\\]|\\.)*)\]\(\s*" + re.escape(ATTACHMENT_SCHEME + str(old)) + r"(?:\s+\"(?:[^\"\\]|\\.)*\")?\s*\)",
    )
    if new is None:
        return pattern.sub(lambda match: match.group(1), text)
    return pattern.sub(lambda match: match.group(0).replace(str(old), str(new)), text)


@contextmanager
def importing_images(file_bytes_by_ref: Mapping[str, bytes]) -> Iterator[ImageImport]:
    """
    Runs a bundle import so the pictures in its Markdown text are carried over.

    Args:
        file_bytes_by_ref: Every embedded file's bytes by `file_ref` (`"<source file id>_<filename>"`).

    Yields:
        The `ImageImport`; the caller calls `finish(db)` once the records and their attachments are written.
    """
    state = ImageImport()
    for ref, data in file_bytes_by_ref.items():
        try:
            source = uuid.UUID(ref[:36])
        except ValueError:
            continue
        state.sources[source] = _content_key(ref[37:], data)
    token = _active.set(state)
    try:
        yield state
    finally:
        _active.reset(token)


def active_import() -> ImageImport | None:
    """The bundle import in progress that has not yet finished, or `None`."""
    state = _active.get()
    return None if state is None or state.finished else state


def note_imported_file(filename: str, data: bytes, new_id: uuid.UUID) -> None:
    """Called for every file a bundle import creates; a no-op outside an import."""
    state = active_import()
    if state is not None:
        state.note_file(filename, data, new_id)
