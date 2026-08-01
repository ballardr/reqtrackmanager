"""
Module: storage_backends.base

Defines the FileStorageBackend interface (I-M-10): file storage must be
implemented such that different backends can be used interchangeably. Every
uploaded file is addressed by an opaque `key` string chosen by the caller
(`app/services/files.py` generates it); a backend only needs to store and
retrieve bytes for that key.
"""

from __future__ import annotations

from typing import Protocol


class FileStorageBackend(Protocol):
    """Interface every file storage backend must implement."""

    name: str

    def save(self, key: str, data: bytes) -> None:
        """Stores `data` under `key`, creating/overwriting as needed."""
        ...

    def read(self, key: str) -> bytes:
        """Returns the bytes stored under `key`.

        Raises:
            FileNotFoundError: If no data is stored under `key`.
        """
        ...

    def delete(self, key: str) -> None:
        """Deletes the data stored under `key`, if present (no-op otherwise)."""
        ...
