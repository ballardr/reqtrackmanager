"""
Module: services.report_record_images

The pictures attached to a record, chosen by a report's record-images block.

Responsibilities:
- List the files attached to a batch of records through each type's `RecordAttachmentProvider`, leaving out any file its
  owner marked confidential.
- Match file names against the block's patterns (an exact name or `*` and `?` wildcards), with a value filled in from the
  record never able to add a wildcard or a path.
- Pick the candidates by name, extension, size and order, and turn a chosen file into drawable bytes by what its
  *content* is, never its claimed type.

Design decisions:
- **Authorisation is the record's.** The engine asks only about records its traversal already showed the caller, and a
  file is reached only through the record's own link table, so a file prints exactly when the caller could open it from
  the record's page. It never goes through the shared-library visibility rule the Image block uses.
- **Confidential is the only per-file switch**, kept on the file (`FileAsset.confidential`); everything else is the
  block's rules. A confidential file is excluded in the query, so it is never read from storage.
- **No regular expressions.** An author's pattern is run over every attachment, so a pattern is matched by a linear
  two-pointer wildcard walk (bounded by pattern length times name length) with a cap on the number of `*`.
- **Cheap tests first, bytes last.** Name, extension, claimed type and recorded size narrow the candidates; a file's
  bytes are read only for those that survive, in order, until the block's count is reached.

Dependencies: `modules.registry` (the providers), `services.report_images` (decoding), `models.file`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.modules.registry import get_record_attachment_providers
from app.services.files import read_file
from app.services.report_images import (
    SVG_TYPE,
    ImageRejectedError,
    ResolvedImage,
    max_image_bytes,
    normalise_raster,
    sniff_image,
)
from app.services.report_layout_tree import RECORD_IMAGE_EXTENSIONS, RECORD_IMAGE_ORDERS
from app.services.report_svg import UnsafeSvgError, sanitize_svg

#: The vocabulary of a record-images block (extensions, pattern and count limits, orderings) is the tree's.
IMAGE_EXTENSIONS = RECORD_IMAGE_EXTENSIONS
ORDERS = RECORD_IMAGE_ORDERS

_STAR = object()
_ANY = object()
#: One element of a compiled pattern: a (case-folded) character, or `_STAR` / `_ANY`.
Token = Any


def has_attachments(artefact_type: str) -> bool:
    """Whether a report can print the files attached to records of `artefact_type`."""
    return artefact_type in get_record_attachment_providers()


def record_files(db: Session, artefact_type: str, record_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[FileAsset]]:
    """The non-confidential files attached to each record, by record id.

    Args:
        db: Active session (read only).
        artefact_type: The records' type.
        record_ids: Records the caller was already shown.

    Returns:
        `{record id: files}` with no entry for a record that has none. Empty for a type with no provider.
    """
    provider = get_record_attachment_providers().get(artefact_type)
    ids = list(record_ids)
    if provider is None or not ids:
        return {}
    found: dict[uuid.UUID, list[FileAsset]] = defaultdict(list)
    rows = db.execute(
        select(provider.record_column, FileAsset)
        .join(provider.link, provider.link.file_id == FileAsset.id)
        .where(provider.record_column.in_(ids), FileAsset.confidential.is_(False))
    ).all()
    for record_id, asset in rows:
        found[record_id].append(asset)
    return dict(found)


def compile_pattern(pattern: str, fill: Callable[[str], str] = lambda text: text) -> list[Token]:
    """A pattern as tokens: `*` matches any run of characters, `?` one character, anything else itself.

    Args:
        pattern: The author's pattern, possibly holding `{{placeholders}}`.
        fill: Fills the placeholders of one *literal* stretch of the pattern. It sees only text between wildcards, so a
            filled value is always literal: a record titled `*` or `../` matches only itself.

    Returns:
        The tokens, ready for `wildcard_match`. Consecutive `*` collapse to one.
    """
    tokens: list[Token] = []
    literal: list[str] = []

    def flush() -> None:
        if literal:
            tokens.extend(fill("".join(literal)).casefold())
            literal.clear()

    for char in pattern:
        if char in "*?":
            flush()
            token = _STAR if char == "*" else _ANY
            if not (token is _STAR and tokens and tokens[-1] is _STAR):
                tokens.append(token)
        else:
            literal.append(char)
    flush()
    return tokens


def wildcard_match(tokens: Sequence[Token], name: str) -> bool:
    """Whether the whole of `name` (case-insensitive) matches the compiled pattern.

    Linear greedy walk with one backtrack point: at most pattern length times name length steps, so a hostile pattern
    cannot make a run slow.
    """
    text = name.casefold()
    p = t = 0
    star = -1
    mark = 0
    while t < len(text):
        token = tokens[p] if p < len(tokens) else None
        if token is _STAR:
            star, mark = p, t
            p += 1
        elif token is not None and (token is _ANY or token == text[t]):
            p += 1
            t += 1
        elif star != -1:
            p = star + 1
            mark += 1
            t = mark
        else:
            return False
    while p < len(tokens) and tokens[p] is _STAR:
        p += 1
    return p == len(tokens)


def extension_of(filename: str) -> str:
    """The lower-case extension of a file name without its dot (`""` when it has none)."""
    return filename.rsplit(".", 1)[-1].casefold() if "." in filename.strip(".") else ""


def candidate_files(
    files: Sequence[FileAsset], *, patterns: Sequence[Sequence[Token]], extensions: Sequence[str], order: str, max_bytes: int | None,
) -> list[FileAsset]:
    """The files that pass the block's cheap tests, in the block's order.

    Args:
        files: A record's non-confidential attachments.
        patterns: Compiled name patterns; a file must match at least one (none given: any name).
        extensions: Allowed extensions (none given: every image extension).
        order: `name` (case-insensitive) or `uploaded` (oldest first).
        max_bytes: Per-picture size ceiling, or `None` for the library's own limit.

    Returns:
        Candidates only; whether the bytes really are an image is decided when the picture is loaded.
    """
    allowed = {e.casefold() for e in extensions} or set(IMAGE_EXTENSIONS)
    ceiling = min(max_bytes, max_image_bytes()) if max_bytes else max_image_bytes()
    chosen = [
        f for f in files
        if extension_of(f.filename) in allowed
        and f.size_bytes <= ceiling
        and (not patterns or any(wildcard_match(p, f.filename) for p in patterns))
    ]
    if order == "uploaded":
        return sorted(chosen, key=lambda f: (f.created_at, f.filename.casefold()))
    return sorted(chosen, key=lambda f: (f.filename.casefold(), str(f.id)))


def load_attachment_image(asset: FileAsset) -> tuple[ResolvedImage | None, str]:
    """Reads a record's attachment as a picture, deciding what it is from its bytes.

    Args:
        asset: The attached file (already reached through its record).

    Returns:
        `(image, "")`, or `(None, reason)` with a short reason for the run's warning. Never raises for a bad file.
    """
    try:
        raw = read_file(asset)
    except Exception:  # noqa: BLE001 - a missing object in storage must not fail the report
        return None, "could not be read"
    try:
        kind = sniff_image(raw)
    except ImageRejectedError as exc:
        return None, f"is not a picture a report can print ({str(exc).rstrip('.').lower()})"
    if kind == SVG_TYPE:
        try:
            return ResolvedImage(svg=sanitize_svg(raw.decode("utf-8"))), ""
        except (UnicodeDecodeError, UnsafeSvgError):
            return None, "is not a safe SVG"
    try:
        normal = normalise_raster(raw)
    except ImageRejectedError as exc:
        return None, f"could not be used ({str(exc).rstrip('.').lower()})"
    return ResolvedImage(normal.data, None, normal.width_px, normal.height_px), ""


__all__ = [
    "IMAGE_EXTENSIONS", "ORDERS", "candidate_files", "compile_pattern", "extension_of", "has_attachments",
    "load_attachment_image", "record_files", "wildcard_match",
]
