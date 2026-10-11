"""
Module: services.report_content_bundle

Carries the images report content references through organisation and project
export bundles (Phase 10 of docs/plans/platform-enhancements-2026-10-plan.md).

Report content embeds images as `![alt](attachment:<file id>)`, and the file is an
organisation shared resource. A bundle that carried the Markdown but not the
file would import with dangling references, and a bundle's ids mean nothing in
the target organisation, so:

- Export (`collect_content_images`): every referenced image that is an image
  shared resource of the exporting organisation is added to the bundle's
  `files/` entries, and a small `report_images` map records its filename and
  content type.
- Import (`ContentImageImporter`): each such file is re-uploaded as a shared
  resource of the target organisation and the `attachment:` references in the
  content are rewritten to the new ids. An identical file the organisation
  already holds is reused, so importing the same content twice (or into several
  projects) does not multiply resources.

Design decisions:
- A reference that does not resolve (not in the bundle, not an image, another
  organisation's) is left as written; rendering already skips an image it
  cannot resolve (`report_document.resolve_report_images`), so nothing breaks.
- Only the reference text and the files the bundle itself carries are used; an
  import never reads a file id from the bundle against the database.

Dependencies: `services.files`, `models.file`, `schemas.report`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.schemas.report import ReportContentEntry
from app.services.files import read_file, upload_file

_REF = re.compile(r"attachment:([0-9a-fA-F-]{36})")

__all__ = ["ContentImageImporter", "collect_content_images"]


def _texts(entries: Iterable[ReportContentEntry]) -> Iterable[str]:
    for entry in entries:
        yield entry.intro
        for chapter in (*entry.chapters, *entry.appendices):
            yield chapter.body


def collect_content_images(
    db: Session, organization_id: UUID, entries: Iterable[ReportContentEntry],
) -> tuple[dict[UUID, FileAsset], dict[str, dict[str, str]]]:
    """Finds the images `entries` reference that an export bundle must carry.

    Args:
        db: Database session.
        organization_id: The exporting organisation; only its own shared
            image resources are returned.
        entries: Content entries from any tiers of this organisation.

    Returns:
        `(assets by id, report_images)`: the files to add to the bundle, and the
        `{old id: {filename, content_type}}` map to store beside the content.
    """
    ids: set[UUID] = set()
    for text in _texts(entries):
        for match in _REF.finditer(text):
            try:
                ids.add(UUID(match.group(1)))
            except ValueError:
                continue
    if not ids:
        return {}, {}
    assets = db.scalars(select(FileAsset).where(
        FileAsset.id.in_(ids), FileAsset.organization_id == organization_id,
        FileAsset.is_org_resource.is_(True), FileAsset.content_type.startswith("image/"),
    )).all()
    return (
        {a.id: a for a in assets},
        {str(a.id): {"filename": a.filename, "content_type": a.content_type} for a in assets},
    )


class ContentImageImporter:
    """Re-creates a bundle's report images in the target organisation and
    rewrites content references to them.

    Args:
        db: Database session.
        organization_id: The target organisation.
        uploaded_by: The importing user (owner of the re-uploaded files).
        file_bytes_by_ref: The bundle's `files/` entries, keyed `"<old id>_<filename>"`.
        report_images: The bundle's `report_images` map (may be `None`/empty).
    """

    def __init__(
        self, db: Session, organization_id: UUID, uploaded_by: UUID, file_bytes_by_ref: Mapping[str, bytes],
        report_images: Mapping[str, Any] | None,
    ) -> None:
        self._db = db
        self._organization_id = organization_id
        self._uploaded_by = uploaded_by
        self._files = {ref.split("_", 1)[0]: (ref, data) for ref, data in file_bytes_by_ref.items() if "_" in ref}
        self._meta = report_images or {}
        self._new_ids: dict[str, UUID | None] = {}

    def _import_one(self, old_id: str) -> UUID | None:
        if old_id in self._new_ids:
            return self._new_ids[old_id]
        new_id: UUID | None = None
        meta = self._meta.get(old_id)
        found = self._files.get(old_id)
        if isinstance(meta, dict) and found is not None and str(meta.get("content_type", "")).startswith("image/"):
            data = found[1]
            filename = str(meta.get("filename") or found[0].split("_", 1)[1])
            candidates = self._db.scalars(select(FileAsset).where(
                FileAsset.organization_id == self._organization_id, FileAsset.is_org_resource.is_(True),
                FileAsset.filename == filename, FileAsset.size_bytes == len(data),
            )).all()
            reused = next((c for c in candidates if read_file(c) == data), None)
            if reused is not None:
                new_id = reused.id
            else:
                asset = upload_file(
                    self._db, organization_id=self._organization_id, uploaded_by=self._uploaded_by,
                    filename=filename, content_type=str(meta["content_type"]), data=data, is_org_resource=True,
                )
                self._db.flush()
                new_id = asset.id
        self._new_ids[old_id] = new_id
        return new_id

    def _rewrite(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            new_id = self._import_one(match.group(1).lower())
            return f"attachment:{new_id}" if new_id is not None else match.group(0)

        return _REF.sub(replace, text) if "attachment:" in text else text

    def remap(self, entries: Iterable[ReportContentEntry]) -> list[ReportContentEntry]:
        """Returns `entries` with every resolvable image reference rewritten to
        the target organisation's copy.

        Args:
            entries: Content entries read from a bundle.

        Returns:
            New entries (the inputs are not modified).
        """
        out: list[ReportContentEntry] = []
        for entry in entries:
            out.append(entry.model_copy(update={
                "intro": self._rewrite(entry.intro),
                "chapters": [c.model_copy(update={"body": self._rewrite(c.body)}) for c in entry.chapters],
                "appendices": [c.model_copy(update={"body": self._rewrite(c.body)}) for c in entry.appendices],
            }))
        return out
