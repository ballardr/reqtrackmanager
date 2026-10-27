"""
Module: services.bundle_common

Shared helpers for the portable export/import bundle formats (project
bundles: `services.project_export`; organisation bundles:
`services.org_export`). A bundle references users by email (never by id,
which isn't portable across a different organisation/deployment) and
embeds file attachments by their original filename under a synthetic ref —
both concerns are the same regardless of which bundle kind is being built
or read, so they live here rather than being duplicated per bundle type.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.user import User
from app.services.files import upload_file

# Bounds a bundle/CSV import's memory footprint. No deployment-wide request
# body size limit exists yet (see docs/soc2/policies/information-security-
# policy.md's Known Gaps), and DEFLATE's ~1032:1 worst-case ratio means an
# unchecked zip well under any sane upload cap could still decompress to
# many gigabytes — these two limits are checked before any entry is read,
# not just before the whole request is accepted.
MAX_IMPORT_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


def enforce_upload_size_limit(data: bytes, *, what: str) -> None:
    """Rejects an uploaded file before it's parsed at all if its raw size
    alone already exceeds `MAX_IMPORT_UPLOAD_BYTES`."""
    if len(data) > MAX_IMPORT_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"{what} is too large ({len(data)} bytes; max {MAX_IMPORT_UPLOAD_BYTES} bytes).",
        )


def enforce_zip_uncompressed_size_limit(zf: zipfile.ZipFile) -> None:
    """Rejects a zip bundle whose entries' *declared* uncompressed size
    (`ZipInfo.file_size`, read from the central directory — cheap, no
    decompression) would exceed `MAX_BUNDLE_UNCOMPRESSED_BYTES` in total,
    before any entry is actually decompressed via `zf.read(...)`. A small
    compressed upload can still pass `enforce_upload_size_limit` while
    claiming an enormous uncompressed size (a classic zip-bomb shape); this
    catches that case independently of the raw upload's own size."""
    total = sum(zi.file_size for zi in zf.infolist())
    if total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Bundle's uncompressed contents ({total} bytes) exceed the maximum allowed ({MAX_BUNDLE_UNCOMPRESSED_BYTES} bytes).",
        )


class BundleImportWarnings:
    """Accumulates human-readable warnings during a bundle import — e.g. a
    user reference that didn't match anyone in the target deployment and
    was remapped to whoever performed the import. Surfaced to the caller so
    data loss during import is visible, never silent (same principle as
    `RequirementImportResult.errors` for CSV import)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def add(self, message: str) -> None:
        self.messages.append(message)


class UserResolver:
    """Resolves the `*_email` references inside a bundle back to real
    `User` ids in the target deployment, caching lookups within one import.

    A `User` is global (one row can hold roles in many organisations, see
    `models.user.User.email`'s uniqueness), so "does this email exist here"
    is a single deployment-wide lookup, independent of which org/project is
    being imported into.
    """

    def __init__(self, db: Session, importing_user: User, warnings: BundleImportWarnings) -> None:
        self._db = db
        self._importing_user = importing_user
        self._warnings = warnings
        self._cache: dict[str, UUID | None] = {}

    @property
    def importing_user_id(self) -> UUID:
        """The user performing the import, the fallback for an unmatched required reference."""
        return self._importing_user.id

    def _lookup(self, email: str) -> UUID | None:
        normalized = email.strip().lower()
        if not normalized:
            return None
        if normalized not in self._cache:
            user = self._db.scalar(select(User).where(User.email == normalized))
            self._cache[normalized] = user.id if user else None
        return self._cache[normalized]

    def resolve(self, email: str | None, *, required: bool, context: str) -> UUID | None:
        """Resolves an email to a user id.

        Args:
            email: The bundle's recorded email, or None/blank if the
                original field was itself null.
            required: Whether the target column is NOT NULL. A required
                reference that can't be matched falls back to the user
                performing the import (recorded as a warning); an optional
                one is simply left null.
            context: Short human-readable description of what this
                reference is for, used only in the warning message.

        Returns:
            A matched (or fallback) user id, or None for an unmatched
            optional reference.
        """
        if not email:
            return self._importing_user.id if required else None
        user_id = self._lookup(email)
        if user_id is not None:
            return user_id
        if required:
            self._warnings.add(f"{context}: no user found for '{email}' — attributed to the importing user instead.")
            return self._importing_user.id
        self._warnings.add(f"{context}: no user found for '{email}' — left unset.")
        return None


def import_bundled_file(
    db: Session, *, organization_id: UUID, uploaded_by: UUID,
    filename: str, content_type: str, data: bytes,
) -> FileAsset:
    """Re-uploads a file embedded in a bundle as a new `FileAsset` owned by
    the target organisation — storage keys aren't portable across
    deployments/backends, so every attachment gets a fresh key via the
    normal upload path rather than trying to preserve the original one.

    Flushed before returning so the asset's id is assigned: callers link it
    straight away (e.g. `RequirementFile(file_id=asset.id)`), and an
    unflushed asset gave those links a null `file_id` — a 500 merging any
    bundle with requirement attachments (found 2026-10-05).
    """
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=uploaded_by,
        filename=filename, content_type=content_type, data=data,
    )
    db.flush()
    return asset


def export_file_links(
    db: Session, file_model: type, fk: str, record_id: UUID, assets: dict[UUID, FileAsset],
) -> list[dict[str, Any]]:
    """A record's direct attachments as bundle entries, collecting the assets to embed.

    Args:
        db: Active session (read only).
        file_model: The module's file-link table (`file_id`, `linked_by`, and `fk`).
        fk: Name of the file-link column that points at the record.
        record_id: The record exported.
        assets: Filled with each attached `FileAsset`, by id, so the bundle embeds its bytes.

    Returns:
        One `{"file_ref", "filename", "content_type", "linked_by_email"}` entry per attachment.
    """
    primed = _primed_file_links(file_model, record_id)
    rows = primed if primed is not None else _file_link_rows(db, file_model, fk, [record_id]).get(record_id, [])
    out = []
    for asset, linked_by_email in rows:
        assets[asset.id] = asset
        out.append({
            "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
            "content_type": asset.content_type, "linked_by_email": linked_by_email,
        })
    return out


def _file_link_rows(db: Session, file_model: type, fk: str, record_ids: list[UUID]) -> dict[UUID, list[tuple[FileAsset, str]]]:
    """`{record id: [(asset, linker's email)]}` for the records, in one statement."""
    found: dict[UUID, list[tuple[FileAsset, str]]] = {}
    if not record_ids:
        return found
    column = getattr(file_model, fk)
    for record_id, asset, linked_by in db.execute(
        select(column, FileAsset, User).join(file_model, file_model.file_id == FileAsset.id)
        .join(User, User.id == file_model.linked_by).where(column.in_(record_ids))
    ).all():
        found.setdefault(record_id, []).append((asset, linked_by.email))
    return found


def _primed_file_links(file_model: type, record_id: UUID) -> list[tuple[FileAsset, str]] | None:
    """The attachments `prime_file_links` read for the record, or `None` when it did not prime them."""
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    return None if memo is None else memo.get(("file_links", file_model.__name__, record_id))


def prime_file_links(db: Session, file_model: type, fk: str, record_ids: list[UUID]) -> None:
    """Reads the direct attachments of many records in one statement, for `export_file_links` to answer from.

    Like `services.tags.prime_record_tag_names`: effective only inside a `memoize_module_state()` block (an export),
    and a no-op elsewhere.
    """
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    if memo is None:
        return
    found = _file_link_rows(db, file_model, fk, list(record_ids))
    for record_id in record_ids:
        memo[("file_links", file_model.__name__, record_id)] = found.get(record_id, [])


def import_file_links(
    db: Session, *, organization_id: UUID, file_model: type, fk: str, record_id: UUID, entries: list[dict[str, Any]],
    file_bytes_by_ref: dict[str, bytes], current_user: User, users: UserResolver, context: str,
) -> None:
    """Recreates a record's attachments from the bundle's embedded bytes; one whose bytes are missing is skipped.

    Args:
        db: Active session; rows are added, not committed.
        organization_id: The importing organisation (owns the new files).
        file_model / fk / record_id: The file-link table, its record column and the new record.
        entries: `export_file_links` output.
        file_bytes_by_ref: Every embedded file's bytes, by `file_ref`.
        current_user: Uploader when the original cannot be matched.
        users: The import's user resolver.
        context: Prefix for warnings.
    """
    now = datetime.now(UTC)
    for att in entries:
        att_bytes = file_bytes_by_ref.get(att["file_ref"])
        if att_bytes is None:
            continue
        uploader = users.resolve(att.get("linked_by_email"), required=False, context=f"{context} attachment uploader")
        asset = import_bundled_file(
            db, organization_id=organization_id, uploaded_by=uploader or current_user.id, filename=att["filename"],
            content_type=att.get("content_type") or "application/octet-stream", data=att_bytes,
        )
        db.add(file_model(**{fk: record_id}, file_id=asset.id, linked_by=uploader or current_user.id, created_at=now))
