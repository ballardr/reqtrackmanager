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

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import IO, Any, Literal, overload
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import UserOrgRole
from app.models.user import User
from app.services import imported_people
from app.services.files import upload_file

# Bounds a bundle/CSV import's memory footprint. DEFLATE's ~1032:1 worst-case ratio means an unchecked zip well
# under the upload cap could still decompress to many gigabytes, so the declared sizes, the entry count and the
# compression ratio are checked from the central directory before any entry is read, and every read is capped at
# the entry's own limit (a stored size can lie).
MAX_IMPORT_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 50_000
MAX_BUNDLE_ENTRY_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_JSON_BYTES = 256 * 1024 * 1024
#: Entries over 1 MiB that compress better than this are refused (a legitimate JSON document compresses about 20:1).
MAX_BUNDLE_RATIO = 250

#: Keys older bundles carried report introductions, chapters, appendices and a default branding template under.
#: They are no longer imported; a bundle that holds any gets one warning.
LEGACY_REPORT_CONTENT_KEYS: tuple[str, ...] = (
    "report_content", "report_images", "report_intro", "report_chapters", "report_appendices",
    "default_report_template_name",
)


#: A built bundle stays in memory up to this size and spills to a temporary file beyond it.
BUNDLE_SPOOL_BYTES = 4 * 1024 * 1024
#: The size of one piece of a bundle sent to the client.
BUNDLE_CHUNK_BYTES = 1024 * 1024


def new_bundle_file() -> IO[bytes]:
    """An empty spooled file to build a bundle zip into: memory for a small bundle, a temporary file for a large one,
    so a big export never holds its whole zip (and then a copy of it) in the worker's memory."""
    return tempfile.SpooledTemporaryFile(max_size=BUNDLE_SPOOL_BYTES)


def write_json_entry(zf: zipfile.ZipFile, name: str, data: Any) -> None:
    """Writes `data` as a pretty-printed JSON entry of the zip, a piece at a time, so the whole document is never one
    string in memory (the previous `json.dumps` held the text, and its encoded bytes, beside the data itself)."""
    with zf.open(name, "w") as entry, io.TextIOWrapper(entry, encoding="utf-8") as text:
        json.dump(data, text, indent=2)


def iter_bundle_file(bundle: IO[bytes]) -> Iterator[bytes]:
    """The chunks of a finished bundle file from its start, closing (and so deleting) it at the end or on a failure."""
    try:
        bundle.seek(0)
        while chunk := bundle.read(BUNDLE_CHUNK_BYTES):
            yield chunk
    finally:
        bundle.close()


def bundle_size(bundle: IO[bytes]) -> int:
    """The size in bytes of a finished bundle file."""
    bundle.seek(0, io.SEEK_END)
    size = bundle.tell()
    bundle.seek(0)
    return size


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


def open_bundle_zip(zip_bytes: bytes, *, what: str = "Bundle upload") -> zipfile.ZipFile:
    """Opens an uploaded bundle after the size, entry-count, duplicate-name and compression-ratio checks.

    Raises:
        HTTPException: 413 when the upload, its declared contents or its entry count are too large, or an entry
            compresses suspiciously well; 400 when it is not a zip or repeats an entry name.
    """
    enforce_upload_size_limit(zip_bytes, what=what)
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.") from None
    infos = zf.infolist()
    if len(infos) > MAX_BUNDLE_ENTRIES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Bundle holds too many entries (max {MAX_BUNDLE_ENTRIES}).")
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.")
    for info in infos:
        if info.file_size > MAX_BUNDLE_ENTRY_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "A file in the bundle is larger than the maximum allowed.")
        if info.compress_size and info.file_size > 1024 * 1024 and info.file_size / info.compress_size > MAX_BUNDLE_RATIO:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The bundle compresses suspiciously well and was refused.")
    enforce_zip_uncompressed_size_limit(zf)
    return zf


def read_bundle_entry(zf: zipfile.ZipFile, name: str, *, limit: int = MAX_BUNDLE_ENTRY_BYTES) -> bytes:
    """Reads one entry, never more than `limit` bytes whatever its header claims.

    Raises:
        KeyError: The entry does not exist.
        HTTPException: 413 when the entry is larger than `limit`; 400 when it cannot be decompressed (a CRC error).
    """
    try:
        with zf.open(name) as handle:
            data = handle.read(limit + 1)
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.") from None
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "A file in the bundle is larger than the maximum allowed.")
    return data


def read_bundle_json(zf: zipfile.ZipFile, name: str) -> Any:
    """Reads and parses one JSON entry (capped at `MAX_BUNDLE_JSON_BYTES`).

    Raises:
        HTTPException: 400 when it is missing, not valid JSON or cannot be decompressed; 413 when too large.
    """
    try:
        return json.loads(read_bundle_entry(zf, name, limit=MAX_BUNDLE_JSON_BYTES))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a valid export bundle.") from None


def read_bundle_files(zf: zipfile.ZipFile) -> dict[str, bytes]:
    """Every `files/<ref>` entry, keyed by `ref`, each read with the per-entry cap."""
    return {n.removeprefix("files/"): read_bundle_entry(zf, n) for n in zf.namelist() if n.startswith("files/") and not n.endswith("/")}


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
    """Resolves the `*_email` references inside a bundle back to `User` ids in the target deployment, caching lookups
    within one import.

    A `User` is global (one row can hold roles in many organisations, see `models.user.User.email`'s uniqueness), but a
    bundle may only name people who belong to the organisation being imported into: an email that matches an account
    with no role there is not matched. Otherwise a bundle could attribute records to another tenant's users and the
    result would reveal which addresses are registered on the server.

    A person who is not matched becomes an imported person (`services.imported_people`): an inert stand-in that
    belongs to the organisation, so authorship and ownership keep a name. The importer may instead map a person to
    themself or to any member, and may force a stand-in where a member matches (`PeopleChoices`).
    """

    def __init__(
        self, db: Session, importing_user: User, warnings: BundleImportWarnings, *, organization_id: UUID,
        data: dict[str, Any] | None = None, choices: imported_people.PeopleChoices | None = None,
    ) -> None:
        self._db = db
        self._organization_id = organization_id
        self._importing_user = importing_user
        self._warnings = warnings
        self._cache: dict[str, UUID | None] = {}
        self._names = imported_people.people_names(data) if data else {}
        self.choices = choices or imported_people.PeopleChoices()
        self._warned: set[str] = set()
        #: Replay actor per address: the stand-in's id, or the importer for a member, the importer or a reassigned person.
        self._actor_cache: dict[str, UUID] = {}
        #: Organisation members found for a bundled principal's email, shared by `principal_from_bundle`.
        self.principal_user_cache: dict[tuple[UUID, str], UUID | None] = {}

    @property
    def importing_user_id(self) -> UUID:
        """The user performing the import, the fallback for a reference the importer maps to themself."""
        return self._importing_user.id

    def _lookup(self, email: str) -> UUID | None:
        normalized = imported_people.normalise_email(email)
        if not normalized:
            return None
        if normalized not in self._cache:
            self._cache[normalized] = self._decide(normalized)
        return self._cache[normalized]

    def _decide(self, normalized: str) -> UUID | None:
        """The user id for an address by the importer's choice, then membership; `None` when it needs a stand-in."""
        choice = self.choices.mapping.get(normalized)
        if choice == imported_people.CHOICE_ME:
            return self._importing_user.id
        if choice == imported_people.CHOICE_STAND_IN:
            return None
        if choice is not None:
            target = imported_people.reassignable_member(self._db, self._organization_id, choice)
            if target is not None:
                return target.id
        user = self._db.scalar(
            select(User).join(UserOrgRole, UserOrgRole.user_id == User.id)
            .where(func.lower(User.email) == normalized, UserOrgRole.organization_id == self._organization_id,
                   User.imported_organization_id.is_(None))
            .limit(1)
        )
        return user.id if user else None

    def stand_in_id(self, email: str, context: str) -> UUID:
        """The organisation's imported person for an address (created on first use), warning once per address."""
        normalized = imported_people.normalise_email(email)
        user = imported_people.stand_in_for(self._db, self._organization_id, normalized, self._names.get(normalized))
        if normalized not in self._warned:
            self._warned.add(normalized)
            self._warnings.add(f"{context}: '{user.display_name}' is not a member of this organisation — recorded as an imported person.")
        return user.id

    def person_id(self, email: str, context: str) -> UUID:
        """The user id for a non-blank address: a member, the importer or reassigned person by choice, else a stand-in."""
        found = self._lookup(email)
        return found if found is not None else self.stand_in_id(email, context)

    def actor_id(self, email: str | None, context: str) -> UUID:
        """Who a replayed history entry is recorded as acted by.

        A stand-in where the person is not a member. A member (matched or reassigned) is never named as the actor of an
        entry a bundle claims, so a bundle cannot attribute an action to a real colleague; the importer is recorded and
        the entry's detail names the original person.
        """
        if not email or not email.strip():
            return self._importing_user.id
        normalized = imported_people.normalise_email(email)
        if normalized not in self._actor_cache:
            found = self._lookup(normalized)
            self._actor_cache[normalized] = self.stand_in_id(normalized, context) if found is None else self._importing_user.id
        return self._actor_cache[normalized]

    def display_name_for(self, email: str | None) -> str | None:
        """The bundle's recorded name for an address, for a history entry's detail."""
        if not email:
            return None
        return self._names.get(imported_people.normalise_email(email)) or imported_people.clean_name(None, imported_people.normalise_email(email))

    @overload
    def resolve(self, email: str | None, *, required: Literal[True], context: str) -> UUID: ...

    @overload
    def resolve(self, email: str | None, *, required: bool, context: str) -> UUID | None: ...

    def resolve(self, email: str | None, *, required: bool, context: str) -> UUID | None:
        """Resolves an email to a user id.

        Args:
            email: The bundle's recorded email, or None/blank if the original field was itself null.
            required: Whether the target column is NOT NULL. A blank required reference is the user performing the
                import; a blank optional one is left null.
            context: Short human-readable description of what this reference is for, used only in the warning message.

        Returns:
            A member, the importer or reassigned person by the importer's choice, or an imported person; `None` for a
            blank optional reference.
        """
        if not email or not email.strip():
            return self._importing_user.id if required else None
        return self.person_id(email, context)


def import_bundled_file(
    db: Session, *, organization_id: UUID, uploaded_by: UUID,
    filename: str, content_type: str, data: bytes, confidential: bool = False,
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
    asset.confidential = confidential
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
        One `{"file_ref", "filename", "content_type", "confidential", "linked_by_email"}` entry per attachment.
    """
    primed = _primed_file_links(file_model, record_id)
    rows = primed if primed is not None else _file_link_rows(db, file_model, fk, [record_id]).get(record_id, [])
    out = []
    for asset, linked_by_email in rows:
        assets[asset.id] = asset
        out.append({
            "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename,
            "content_type": asset.content_type, "confidential": asset.confidential,
            "linked_by_email": linked_by_email,
        })
    return out


def _file_link_rows(db: Session, file_model: type[Any], fk: str, record_ids: list[UUID]) -> dict[UUID, list[tuple[FileAsset, str]]]:
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
            confidential=bool(att.get("confidential")),
        )
        db.add(file_model(**{fk: record_id}, file_id=asset.id, linked_by=uploader or current_user.id, created_at=now))
