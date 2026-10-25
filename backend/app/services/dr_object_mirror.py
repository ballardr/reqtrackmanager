"""
Module: services.dr_object_mirror

An incremental, local mirror of the S3-compatible object store, so a backup set can hold the attachment
bytes the database rows point at without re-downloading the whole bucket every night.

Responsibilities:
- List the bucket (paged) and download only objects that are new or changed (by size and ETag), verifying
  each download against its size and, where the ETag is a plain MD5, its digest.
- Keep the mirror consistent with a database dump taken just before the sync: an object deleted from the
  store stays in the mirror through the next snapshot, then is dropped.
- Report the mirror's size and a digest of its content for the manifest.

Design decisions:
- The sync never deletes during a run (a failed run must not lose what an earlier one captured). An object
  that vanished from the store is flagged `missing` and removed at the start of the *next* run: the set
  taken in between may have a dump that still references it (deleted after the dump, before the sync), and
  that is the only set that needs it; later dumps cannot. Earlier snapshots already hold their own copy.
- State (size, ETag, SHA-256, missing flag) lives beside the mirror, not in it, so the snapshot holds only
  object bytes.
- Keys come from the application but are still treated as untrusted when mapped to a path: an absolute,
  traversing, empty-segment or directory-marker key is refused, and errors name a key by a digest prefix,
  never the key (storage keys are Confidential).

Dependencies: a boto3 S3 client (injected), the standard library.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024


class MirrorError(RuntimeError):
    """The mirror could not be brought up to date; the message never contains an object key."""


def key_label(key: str) -> str:
    """A short stable identifier for `key` that is safe to log (first 12 hex of its SHA-256)."""
    return hashlib.sha256(key.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _safe_path(root: Path, key: str) -> Path:
    """Maps an object key to a path under `root`.

    Raises:
        MirrorError: If the key is empty, absolute, contains a NUL, an empty or `.`/`..` segment, or ends
            in `/` (a directory marker).
    """
    parts = key.split("/")
    if not key or "\x00" in key or key.endswith("/") or any(p in ("", ".", "..") for p in parts):
        raise MirrorError(f"object key {key_label(key)} cannot be mirrored (unsafe path)")
    return root.joinpath(*parts)


@dataclass(frozen=True)
class MirrorResult:
    """Outcome of one sync.

    Attributes:
        count: Objects live in the store at sync time (all are in the mirror).
        bytes: Their total size.
        digest: SHA-256 over the sorted `key\\tsize\\tsha256` lines of those objects.
        downloaded: Objects fetched this run.
        removed: Objects dropped because they were already flagged missing by the previous run.
        flagged_missing: Objects newly found absent from the store (kept for this run's snapshot).
    """

    count: int
    bytes: int
    digest: str
    downloaded: int
    removed: int
    flagged_missing: int


class ObjectMirror:
    """Mirrors one bucket into a directory.

    Args:
        client: A boto3 S3 client.
        bucket: Bucket name.
        root: Directory holding the mirrored objects (created if absent).
        state_path: JSON file with per-object state (outside `root`).
    """

    def __init__(self, client: Any, bucket: str, root: Path, state_path: Path) -> None:
        self._client = client
        self._bucket = bucket
        self._root = root
        self._state_path = state_path

    def _load_state(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self._state_path.read_text())["objects"]
        except FileNotFoundError:
            return {}
        except (ValueError, KeyError) as exc:
            raise MirrorError("mirror state file is unreadable; remove it to force a full re-sync") from exc

    def _save_state(self, state: dict[str, dict[str, Any]]) -> None:
        """Writes state atomically (temp file + rename) so an interrupted run never leaves it half-written."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._state_path.parent, prefix=".mirror-state-")
        with os.fdopen(fd, "w") as handle:
            json.dump({"version": 1, "objects": state}, handle)
        os.replace(tmp, self._state_path)

    def _list(self) -> dict[str, tuple[int, str]]:
        """Lists every object in the bucket, following continuation tokens.

        Returns:
            `{key: (size, etag without quotes)}`.

        Raises:
            MirrorError: If listing fails (denied, unreachable): a partial listing would flag live objects as
                deleted, so it is never used.
        """
        live: dict[str, tuple[int, str]] = {}
        try:
            for page in self._client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket):
                for item in page.get("Contents", []):
                    live[item["Key"]] = (int(item["Size"]), str(item.get("ETag", "")).strip('"'))
        except Exception as exc:  # boto raises many types; none may leave a half-listing in use
            raise MirrorError(f"listing the bucket failed: {type(exc).__name__}") from exc
        return live

    def _download(self, key: str, size: int, etag: str) -> str:
        """Fetches one object into place and returns its SHA-256.

        Raises:
            MirrorError: On a transfer error or when the bytes do not match the listed size or MD5 ETag.
        """
        dest = _safe_path(self._root, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
        total = 0
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
        try:
            with os.fdopen(fd, "wb") as out:
                body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
                for chunk in body.iter_chunks(_CHUNK):
                    out.write(chunk)
                    sha.update(chunk)
                    md5.update(chunk)
                    total += len(chunk)
            if total != size:
                raise MirrorError(f"object {key_label(key)} changed size during download ({total} of {size} bytes)")
            if "-" not in etag and len(etag) == 32 and md5.hexdigest() != etag:
                raise MirrorError(f"object {key_label(key)} failed its MD5 check")
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, dest)
        except MirrorError:
            raise
        except Exception as exc:
            raise MirrorError(f"downloading object {key_label(key)} failed: {type(exc).__name__}") from exc
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return sha.hexdigest()

    def _remove(self, key: str) -> None:
        """Deletes a mirrored file and any directories it leaves empty."""
        path = _safe_path(self._root, key)
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self._root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def sync(self) -> MirrorResult:
        """Brings the mirror in line with the bucket (see the module docstring for the deletion rule).

        Returns:
            The sync's counts and content digest.

        Raises:
            MirrorError: On any listing, transfer, verification or path problem. State saved so far stays
                valid: objects already mirrored are not fetched again on a retry.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        state = self._load_state()

        removed = 0
        for key in [k for k, v in state.items() if v.get("missing")]:
            self._remove(key)
            del state[key]
            removed += 1

        live = self._list()
        downloaded = 0
        for key, (size, etag) in sorted(live.items()):
            known = state.get(key)
            path = _safe_path(self._root, key)
            if known and known["size"] == size and known["etag"] == etag and path.is_file() and path.stat().st_size == size:
                known["missing"] = False
                continue
            state[key] = {"size": size, "etag": etag, "sha256": self._download(key, size, etag), "missing": False}
            downloaded += 1
            self._save_state(state)

        flagged = 0
        for key, entry in state.items():
            if key not in live and not entry.get("missing"):
                entry["missing"] = True
                flagged += 1
        self._save_state(state)

        digest = hashlib.sha256()
        total_bytes = 0
        for key in sorted(live):
            entry = state[key]
            digest.update(f"{key}\t{entry['size']}\t{entry['sha256']}\n".encode("utf-8", "surrogateescape"))
            total_bytes += entry["size"]
        return MirrorResult(len(live), total_bytes, digest.hexdigest(), downloaded, removed, flagged)
