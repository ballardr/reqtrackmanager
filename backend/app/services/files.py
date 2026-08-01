"""
Module: services.files

File upload/download/delete built on top of the pluggable storage backend
(I-M-10). Generates a collision-proof storage key per file rather than
trusting the client-supplied filename, and records metadata in `FileAsset`
regardless of which backend actually holds the bytes.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.file import FileAsset
from app.storage_backends import FileStorageBackend, LocalFileStorageBackend, S3CompatibleFileStorageBackend

settings = get_settings()


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
    key = f"{organization_id}/{uuid.uuid4()}_{filename}"
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
