"""
Module: services.dr_manifest

The versioned manifest every backup set carries (`manifest.json`): what the set contains, which build
produced it, and the `dr_stats` document the restore is verified against.

Responsibilities:
- Define the manifest shape (`BackupManifest`) and its JSON Schema, committed at
  `docs/schemas/backup-manifest.schema.json` so the shell-level backup and restore tools and a human can
  read the contract without importing Python.
- Parse and validate a manifest (`load_manifest`), refusing one written by a newer format.

Design decisions:
- Contains no secret: `secrets_mode` records only *whether* the set holds an `.env` snapshot, so a restore
  never has to guess, and component entries hold digests and sizes, never content.
- `alembic_revision` and `app_version` let a restore refuse an image older than the dump, since migrations
  only run forward.
- A newer `manifest_version` is refused rather than best-effort read; an older one is read as long as the
  fields the version-1 shape requires are present.

Dependencies: pydantic, `services.dr_stats`.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.dr_stats import DrStats

MANIFEST_VERSION = 1
"""Bumped when the manifest shape changes incompatibly."""

MANIFEST_FILENAME = "manifest.json"


class SecretsMode(str, Enum):
    """Whether the set holds the operator's `.env` (`config`) or no keys at all (`none`)."""

    CONFIG = "config"
    NONE = "none"


class ComponentKind(str, Enum):
    """The parts a set can hold; `local_files` only when `STORAGE_BACKEND=local`, `config` only in `config` mode."""

    DATABASE = "database"
    OBJECTS = "objects"
    LOCAL_FILES = "local_files"
    CONFIG = "config"


class ComponentEntry(BaseModel):
    """One stored component: where it sits in the set and its integrity digest.

    Attributes:
        path: Path within the set (relative, no `..`).
        sha256: Lowercase hex SHA-256 of the component (of the archive for a directory component).
        bytes: Size in bytes.
    """

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        """Rejects an absolute or traversing path, so a crafted manifest cannot point outside the set."""
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("component path must be relative to the backup set")
        return value


class ObjectsSummary(BaseModel):
    """The object-store mirror's size at backup time."""

    count: int = Field(ge=0)
    bytes: int = Field(ge=0)


class AppIdentity(BaseModel):
    """The build that produced the set (`app.version`), so a restore can pull the same image."""

    version: str
    git_sha: str
    image_tag: str | None = None


class BackupManifest(BaseModel):
    """The manifest of one backup set.

    Attributes:
        manifest_version: Format version (`MANIFEST_VERSION`).
        set_id: Unique, sortable id of the set (`20261024T020000Z`).
        created_at / finished_at: UTC instants the run began and ended (timezone-aware).
        tool_version: Version of the backup tool.
        app: The producing build.
        alembic_revision: The database's schema revision, repeated from `stats` for the restore's version guard.
        postgres_version: Server version of the dumped database (`16.4`).
        storage_backend: `s3` or `local`, the backend the file records point at.
        secrets_mode: Whether an `.env` snapshot is in the set.
        components: The stored parts, by kind, with digests.
        objects: Object-mirror size; null when `STORAGE_BACKEND=local`.
        stats: The `dr_stats` document taken in the dump's snapshot; a restore is verified against it.
    """

    manifest_version: int = MANIFEST_VERSION
    set_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    created_at: datetime
    finished_at: datetime
    tool_version: str
    app: AppIdentity
    alembic_revision: str | None
    postgres_version: str
    storage_backend: str
    secrets_mode: SecretsMode
    components: dict[ComponentKind, ComponentEntry]
    objects: ObjectsSummary | None = None
    stats: DrStats

    @field_validator("created_at", "finished_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        """Requires a timezone-aware instant: a past instant is stored in UTC, never a bare local time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return value


def manifest_json_schema() -> dict[str, Any]:
    """The manifest's JSON Schema (draft 2020-12), as committed at `docs/schemas/backup-manifest.schema.json`."""
    schema = BackupManifest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "ReqTrack backup set manifest"
    return schema


def dump_manifest(manifest: BackupManifest) -> str:
    """Serialises a manifest to the JSON written to `manifest.json` (stable key order, trailing newline)."""
    return json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"


def load_manifest(text: str) -> BackupManifest:
    """Parses and validates `manifest.json` text.

    Args:
        text: The file's content.

    Returns:
        The validated manifest.

    Raises:
        ValueError: If it is not JSON, was written by a newer manifest format than this tool reads, or
            fails validation (`pydantic.ValidationError` is a `ValueError`).
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {exc.msg}") from exc
    version = raw.get("manifest_version") if isinstance(raw, dict) else None
    if isinstance(version, int) and version > MANIFEST_VERSION:
        raise ValueError(f"manifest version {version} is newer than this tool reads ({MANIFEST_VERSION}); use a newer release")
    return BackupManifest.model_validate(raw)
