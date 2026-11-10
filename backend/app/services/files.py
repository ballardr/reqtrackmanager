"""
Module: services.files

File upload/download/delete built on top of the pluggable storage backend
(I-M-10). Generates a collision-proof storage key per file rather than
trusting the client-supplied filename, and records metadata in `FileAsset`
regardless of which backend actually holds the bytes.

`assert_uploads_allowed` is the one gate for every user-supplied file: the deployment-wide switch
(`ServerSettings.file_uploads_enabled`), the organisation's switch and its storage limit (`services.storage_usage`) stop
new files only, so reading and deleting existing files keep working.
`resolve_bundle_files` applies the same rule to the files embedded in an imported bundle. Generated report outputs
are written by `services/report_run_jobs.py` directly and are not uploads (see `docs/decisions.md`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.file import FileAsset
from app.models.organization import ServerSettings
from app.services import storage_usage
from app.storage_backends import FileStorageBackend, LocalFileStorageBackend, S3CompatibleFileStorageBackend

settings = get_settings()

_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")

UPLOADS_DISABLED_CODE = "uploads_disabled"
UPLOADS_DISABLED_MESSAGE = "File uploads are disabled on this deployment."


def _safe_key_component(filename: str) -> str:
    """Reduces a client-supplied filename to a fragment safe to embed in a
    storage key path.

    `upload_file` below builds a key as `f"{organization_id}/{uuid4()}_
    {filename}"`, intending the uuid prefix to make every key
    collision-proof and, per `storage_backends.local`'s original comment,
    "never taken directly from user input" — but the raw filename WAS still
    concatenated in directly. A filename containing `/` or `..` segments
    (e.g. `../../other-org-id/evil.txt`) reintroduces exactly the kind of
    attacker-controlled path component the uuid prefix was meant to rule
    out: the first `..` merges with the uuid prefix into one literal,
    harmless component (`<uuid>_..`), but any *additional* `../` segments
    in the filename remain real traversal operators, letting the resolved
    path pop back out of the uploading organisation's own key prefix and
    into another organisation's — a cross-tenant storage write, even though
    `LocalFileStorageBackend`'s own confinement check (staying
    inside the shared `storage_local_dir` root) still passes.

    Keeping only the final path segment (discarding directory components
    entirely, so no `..` can ever reach this function to begin with) and
    replacing every remaining non-alphanumeric character closes this: the
    resulting fragment can never contain a `/` or `.`-only component, so it
    can never be interpreted as a path separator or a traversal operator by
    any backend that resolves keys hierarchically.
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    safe = _UNSAFE_KEY_CHARS.sub("_", name).strip("_.")
    return safe or "file"


@lru_cache
def get_storage_backend() -> FileStorageBackend:
    """Returns the process-wide storage backend selected by `STORAGE_BACKEND`."""
    if settings.storage_backend == "s3":
        return S3CompatibleFileStorageBackend(
            bucket=settings.storage_s3_bucket,
            endpoint_url=settings.storage_s3_endpoint_url,
            access_key=settings.storage_s3_access_key,
            secret_key=settings.storage_s3_secret_key,
            region=settings.storage_s3_region,
        )
    return LocalFileStorageBackend(settings.storage_local_dir)


def upload_refusal(db: Session, organization_id: UUID | None, incoming_bytes: int = 0) -> dict[str, object] | None:
    """Decides whether new user files may be stored, under every rule in order.

    The rules are the deployment-wide switch, the organisation's switch, then the organisation's storage limit
    (`services.storage_usage.refusal`).

    Args:
        db: An active database session.
        organization_id: The organisation the file would belong to (None checks only the deployment-wide switch).
        incoming_bytes: The size about to be stored; 0 asks only whether storing is allowed at all.

    Returns:
        None when allowed; otherwise the 403 detail naming the rule that applied.
    """
    enabled = db.scalar(select(ServerSettings.file_uploads_enabled))
    if enabled is False:
        return {"code": UPLOADS_DISABLED_CODE, "message": UPLOADS_DISABLED_MESSAGE}
    if organization_id is None:
        return None
    return storage_usage.refusal(db, organization_id, incoming_bytes)


def uploads_allowed(db: Session, organization_id: UUID | None = None, incoming_bytes: int = 0) -> bool:
    """Whether `incoming_bytes` more may be stored; the boolean form of `upload_refusal`."""
    return upload_refusal(db, organization_id, incoming_bytes) is None


def assert_uploads_allowed(db: Session, organization_id: UUID | None = None, incoming_bytes: int = 0) -> None:
    """Refuses a new file while uploads are disabled or the organisation's storage limit would be exceeded.

    Args:
        db: An active database session.
        organization_id: The organisation the file would belong to.
        incoming_bytes: The size about to be stored.

    Raises:
        HTTPException: 403 with the rule's code in the detail (`uploads_disabled`, `organization_uploads_disabled` or
            `storage_quota_exceeded`).
    """
    detail = upload_refusal(db, organization_id, incoming_bytes)
    if detail is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def resolve_bundle_files(
    db: Session, organization_id: UUID | None, file_bytes_by_ref: dict[str, bytes], *, skip_files: bool, warn: Callable[[str], None],
) -> dict[str, bytes]:
    """Decides what happens to the files embedded in a bundle being imported.

    Files are imported whenever they can be stored, judged by the same rules as a single upload with the bundle's total
    size. When they cannot, the import either stops before any row is written, or (with `skip_files`) goes ahead without
    them and reports how many were left out. Every importer already skips a record file that has no bytes, so returning
    an empty map is the whole mechanism.

    Args:
        db: An active database session.
        organization_id: The organisation that would own the files.
        file_bytes_by_ref: The bundle's embedded files, by reference.
        skip_files: The person's choice to import without files; ignored while files can be stored.
        warn: Records one import warning (`BundleImportWarnings.add`).

    Returns:
        `file_bytes_by_ref` unchanged when files can be stored or there are none, else an empty map.

    Raises:
        HTTPException: 403 with the rule's code, the file count, the total size in bytes and (for a limit) the space left
            when files cannot be stored and `skip_files` is not set.
    """
    if not file_bytes_by_ref:
        return file_bytes_by_ref
    count = len(file_bytes_by_ref)
    total = sum(len(data) for data in file_bytes_by_ref.values())
    detail = upload_refusal(db, organization_id, total)
    if detail is None:
        return file_bytes_by_ref
    if not skip_files:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={**detail, "file_count": count, "file_bytes": total},
        )
    noun, verb = ("files", "were") if count != 1 else ("file", "was")
    reason = "there is not enough storage space" if detail["code"] == "storage_quota_exceeded" else "file uploads are disabled"
    warn(f"{count} {noun} in the bundle {verb} not imported because {reason}.")
    return {}


def upload_file(
    db: Session,
    *,
    organization_id: UUID | None,
    uploaded_by: UUID,
    filename: str,
    content_type: str,
    data: bytes,
    is_org_resource: bool = False,
    project_id: UUID | None = None,
) -> FileAsset:
    """Stores file bytes in the configured backend and records its metadata.

    Args:
        db: An active database session (the FileAsset row is added but not
            committed; the caller commits as part of its own transaction).
        organization_id: The owning organisation, used both for storage-key
            namespacing and access control; `None` stores a platform-owned file (only the deployment-wide switch and the
            size limit apply, and no organisation's usage counts it).
        uploaded_by: The user performing the upload.
        filename: The original filename, shown back to users.
        content_type: The file's MIME type.
        data: The raw file bytes.
        is_org_resource: True for an organisation shared resource (C-M-03).
        project_id: The project whose report-image library the file joins (`None` for any other file).

    Returns:
        The created FileAsset (not yet committed).

    Raises:
        HTTPException: 403 (`uploads_disabled`) while uploads are disabled; 413 when `data` is larger than
            `Settings.max_upload_bytes`.
    """
    assert_uploads_allowed(db, organization_id, len(data))
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is too large (limit {settings.max_upload_bytes // (1024 * 1024)} MB).",
        )
    if organization_id is not None:
        storage_usage.note_upload(db, organization_id, len(data))
    backend = get_storage_backend()
    key = f"{organization_id or 'platform'}/{uuid.uuid4()}_{_safe_key_component(filename)}"
    backend.save(key, data)

    file_asset = FileAsset(
        organization_id=organization_id,
        storage_backend=backend.name,
        storage_key=key,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        uploaded_by=uploaded_by,
        is_org_resource=is_org_resource,
        project_id=project_id,
    )
    db.add(file_asset)
    return file_asset


def read_file(file_asset: FileAsset) -> bytes:
    """Reads a file's bytes from its storage backend."""
    return get_storage_backend().read(file_asset.storage_key)


def delete_file(db: Session, file_asset: FileAsset) -> None:
    """Deletes a file's bytes from storage and removes its metadata row."""
    get_storage_backend().delete(file_asset.storage_key)
    db.delete(file_asset)
