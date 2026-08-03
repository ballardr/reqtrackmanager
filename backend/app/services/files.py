"""
Module: services.files

File upload/download/delete built on top of the pluggable storage backend
(I-M-10). Generates a collision-proof storage key per file rather than
trusting the client-supplied filename, and records metadata in `FileAsset`
regardless of which backend actually holds the bytes.
"""

from __future__ import annotations

import re
import uuid
from functools import lru_cache
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.file import FileAsset
from app.storage_backends import FileStorageBackend, LocalFileStorageBackend, S3CompatibleFileStorageBackend

settings = get_settings()

_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


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
    `LocalFileStorageBackend._path_for`'s own confinement check (staying
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


def upload_file(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by: UUID,
    filename: str,
    content_type: str,
    data: bytes,
    is_org_resource: bool = False,
) -> FileAsset:
    """Stores file bytes in the configured backend and records its metadata.

    Args:
        db: An active database session (the FileAsset row is added but not
            committed; the caller commits as part of its own transaction).
        organization_id: The owning organisation, used both for storage-key
            namespacing and access control.
        uploaded_by: The user performing the upload.
        filename: The original filename, shown back to users.
        content_type: The file's MIME type.
        data: The raw file bytes.
        is_org_resource: True for an organisation shared resource (C-M-03).

    Returns:
        The created FileAsset (not yet committed).
    """
    backend = get_storage_backend()
    key = f"{organization_id}/{uuid.uuid4()}_{_safe_key_component(filename)}"
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
