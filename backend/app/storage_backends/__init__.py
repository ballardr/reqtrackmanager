"""Pluggable file storage backends (I-M-10): local filesystem or S3-compatible."""

from app.storage_backends.base import FileStorageBackend
from app.storage_backends.local import LocalFileStorageBackend
from app.storage_backends.s3 import S3CompatibleFileStorageBackend

__all__ = ["FileStorageBackend", "LocalFileStorageBackend", "S3CompatibleFileStorageBackend"]
