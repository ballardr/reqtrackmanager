"""
Module: services.bundle_comments

Carries a record's generic comments (`services.record_comments`) in a project bundle, beside its tags and places.

Responsibilities:
- `export_comments`: for a page of records of one type, each record's comments and pins as bundle rows, read in a
  fixed number of statements.
- `import_comments`: recreates one record's comments and pins on the new record (project- or organisation-owned),
  resolving authors through the bundle's `UserResolver` and anchors through the module's portable-key callback.

Design decisions:
- A bundle row carries `comments` and `comment_pins`. A pin has a bundle-local `ref`; a comment names its pin by that
  ref. An anchor travels as `{kind, code}` (the box's or line's record code), never as an id, and an import that cannot
  resolve or validate one keeps the pin as a free marker at its saved position (a comment is never dropped for it).
- Authors, resolvers and pin creators are `*_email` keys, so the bundle's people list and the importer's choices cover
  them with no change. A person with no match becomes an imported person; one that cannot be resolved leaves the author
  empty (shown as an unknown user).
- Resolved state and original times are carried as information. Counts and bodies are bounded on import, so a crafted
  bundle cannot make an unbounded write.
- A project made from a template does not copy comments (review history about that project's records): the module's
  template reset removes `comments` and `comment_pins` from the rows (`strip_comments`).

External dependencies: `models.record_comment`, `models.user`, `services.bundle_common`, `modules.registry`.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.record_comment import PIN_ANCHOR_KINDS, RecordComment, RecordCommentPin
from app.models.user import User
from app.modules.registry import get_record_comment_providers
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.record_comments import MAX_ANCHOR_KEY_LENGTH, MAX_COMMENT_LENGTH, MAX_COMMENTS_PER_RECORD

#: The row keys this module adds to a record's bundle row.
COMMENT_KEYS = ("comments", "comment_pins")


def _stamp(value: datetime | None) -> str | None:
    """A UTC ISO 8601 string, or `None`."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _instant(value: Any) -> datetime | None:
    """A timezone-aware UTC datetime from a bundle string, or `None` when it is absent or malformed."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: Any) -> float | None:
    """A finite float from a bundle value, or `None` for anything else (a bool, text, NaN or infinity)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def export_comments(
    db: Session, artefact_type: str, record_ids: Iterable[uuid.UUID], anchor_code: Callable[[str, str], str | None],
) -> dict[uuid.UUID, dict[str, list[dict[str, Any]]]]:
    """The comments and pins of the records as bundle rows, `{record id: {"comments": [...], "comment_pins": [...]}}`,
    in three statements however many records and comments (a record with none is absent).

    Args:
        db: Active session (read only).
        artefact_type: The records' type.
        record_ids: The records.
        anchor_code: `anchor_code(kind, key)` is the portable code of a pin's box or line, or `None` when it has none
            (the pin then travels as a free marker).
    """
    ids = list(record_ids)
    if not ids or artefact_type not in get_record_comment_providers():
        return {}
    comments = list(db.scalars(
        select(RecordComment).where(RecordComment.artefact_type == artefact_type, RecordComment.record_id.in_(ids))
        .order_by(RecordComment.created_at, RecordComment.id)
    ))
    pins = list(db.scalars(
        select(RecordCommentPin).where(RecordCommentPin.artefact_type == artefact_type, RecordCommentPin.record_id.in_(ids))
        .order_by(RecordCommentPin.created_at, RecordCommentPin.id)
    ))
    user_ids = (
        {c.author_id for c in comments} | {p.created_by for p in pins} | {p.resolved_by for p in pins}
    ) - {None}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    refs = {pin.id: f"p{n}" for n, pin in enumerate(pins, start=1)}
    out: dict[uuid.UUID, dict[str, list[dict[str, Any]]]] = {}
    for pin in pins:
        code = anchor_code(pin.anchor_kind, pin.anchor_key) if pin.anchor_key else None
        out.setdefault(pin.record_id, {"comments": [], "comment_pins": []})["comment_pins"].append({
            "ref": refs[pin.id], "anchor": {"kind": pin.anchor_kind, "code": code} if code else None,
            "x": pin.x, "y": pin.y, "resolved_at": _stamp(pin.resolved_at),
            "resolved_by_email": emails.get(pin.resolved_by) if pin.resolved_by else None,
            "created_by_email": emails.get(pin.created_by) if pin.created_by else None, "created_at": _stamp(pin.created_at),
        })
    for comment in comments:
        out.setdefault(comment.record_id, {"comments": [], "comment_pins": []})["comments"].append({
            "pin": refs.get(comment.pin_id) if comment.pin_id else None, "body": comment.body,
            "author_email": emails.get(comment.author_id) if comment.author_id else None,
            "created_at": _stamp(comment.created_at), "edited_at": _stamp(comment.edited_at),
        })
    return out


def strip_comments(rows: Iterable[dict[str, Any]]) -> None:
    """Removes the comment keys from bundle rows (a template copies no review history)."""
    for row in rows:
        for key in COMMENT_KEYS:
            row.pop(key, None)


def import_comments(
    db: Session, *, project: Project | None = None, organization: Organization | None = None, artefact_type: str,
    record_id: uuid.UUID, entry: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings, context: str,
    resolve_anchor: Callable[[str, str], str | None],
) -> None:
    """Recreates a record's comments and pins from its bundle row. The record belongs to `project` or, for an
    organisation-owned record, to `organization` (exactly one is given); an organisation-owned record has no drawing, so
    its pins can only be free markers.

    Args:
        db: Active session; rows are added and flushed, never committed.
        project: The importing project (a project-owned record).
        organization: The importing organisation (an organisation-owned record).
        artefact_type: The record's type.
        record_id: The new record.
        entry: The bundle row (`comments`, `comment_pins`).
        users: Resolves the `*_email` references.
        warnings: Receives a note when entries are skipped or an anchor falls back to a free marker.
        context: A short label for warnings (`"Diagram DGM-001"`).
        resolve_anchor: `resolve_anchor(kind, code)` is the new anchor key for a bundled box or line, or `None`.
    """
    if (project is None) == (organization is None):
        raise ValueError("Give exactly one of project and organization.")
    owner: dict[str, uuid.UUID | None] = (
        {"project_id": project.id, "organization_id": None} if project is not None
        else {"project_id": None, "organization_id": organization.id if organization else None}
    )
    provider = get_record_comment_providers().get(artefact_type)
    raw_comments, raw_pins = entry.get("comments"), entry.get("comment_pins")
    if provider is None or not isinstance(raw_comments, list) or not raw_comments:
        return
    pins: dict[str, uuid.UUID] = {}
    degraded = skipped = 0
    for raw in (raw_pins if isinstance(raw_pins, list) else [])[:MAX_COMMENTS_PER_RECORD]:
        if not isinstance(raw, dict) or not isinstance(raw.get("ref"), str):
            skipped += 1
            continue
        x, y = _number(raw.get("x")), _number(raw.get("y"))
        if x is None or y is None:
            skipped += 1
            continue
        kind, key = "none", None
        anchor = raw.get("anchor")
        if isinstance(anchor, dict) and anchor.get("kind") in PIN_ANCHOR_KINDS and isinstance(anchor.get("code"), str):
            candidate = resolve_anchor(anchor["kind"], anchor["code"])
            if (
                project is not None and candidate and len(candidate) <= MAX_ANCHOR_KEY_LENGTH
                and anchor["kind"] in provider.anchor_kinds and provider.validate_anchor is not None
                and provider.validate_anchor(db, project.id, record_id, anchor["kind"], candidate)
            ):
                kind, key = anchor["kind"], candidate
            else:
                degraded += 1
        elif anchor:
            degraded += 1
        resolved_at = _instant(raw.get("resolved_at"))
        pin = RecordCommentPin(
            **owner, artefact_type=artefact_type, record_id=record_id,
            anchor_kind=kind, anchor_key=key, x=x, y=y,
            resolved_at=resolved_at,
            resolved_by=users.resolve(raw.get("resolved_by_email"), required=False, context=f"{context} comment") if resolved_at else None,
            created_by=users.resolve(raw.get("created_by_email"), required=False, context=f"{context} comment"),
        )
        created = _instant(raw.get("created_at"))
        if created:
            pin.created_at = created
        db.add(pin)
        db.flush()
        pins[raw["ref"]] = pin.id
    for raw in raw_comments[:MAX_COMMENTS_PER_RECORD]:
        body = raw.get("body") if isinstance(raw, dict) else None
        if not isinstance(body, str) or not body.strip():
            skipped += 1
            continue
        pin_ref = raw.get("pin")
        if pin_ref is not None and pin_ref not in pins:
            skipped += 1
            continue
        comment = RecordComment(
            **owner, artefact_type=artefact_type, record_id=record_id,
            pin_id=pins.get(pin_ref) if pin_ref else None,
            author_id=users.resolve(raw.get("author_email"), required=False, context=f"{context} comment"),
            body=body.strip()[:MAX_COMMENT_LENGTH], edited_at=_instant(raw.get("edited_at")),
        )
        created = _instant(raw.get("created_at"))
        if created:
            comment.created_at = created
            comment.updated_at = created
        db.add(comment)
    if degraded:
        warnings.add(f"{context}: {degraded} comment marker(s) lost their box or line and were kept as free markers.")
    if skipped:
        warnings.add(f"{context}: {skipped} malformed comment entr{'y' if skipped == 1 else 'ies'} skipped.")
    db.flush()
