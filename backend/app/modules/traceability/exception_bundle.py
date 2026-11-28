"""
Module: modules.traceability.exception_bundle

Carries a project's traceability exceptions, with their comments, evidence, tags, places and external references, in the
project bundle.

Responsibilities:
- Export (`export_exceptions`), import (`import_exceptions`) and the template reset (`reset_for_template`).

Design decisions:
- The excepted record is named by type, code and title. A requirement keeps its code on import and every other record is
  numbered afresh, so a match is by code and title, else by a title only one record of the type has. An exception whose
  record cannot be matched is not imported: there is nothing for it to except.
- The rule is named by its profile (for a profile's rule) and name. An exception whose rule cannot be matched is kept and
  covers nothing.
- Exceptions are imported after every module's records exist (`import_late`).
- Approval state travels, and is removed with every other record's when the organisation does not allow imported approval
  state or the project is made from a template (`reset_for_template`). The organisation-level approval mark is kept only
  when the person importing holds that right themselves, so a file cannot waive a rule an organisation enforces.
- Whether the rule had changed since approval is carried as a flag, because link types and types are renumbered and the
  digest of the imported rule differs from the source's.
- An import notifies nobody and writes no per-record audit event: the import is the recorded act.

Dependencies: `exceptions`, `exception_cover`, `models`, `services.bundle_common`, `services.record_summaries`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.traceability import exception_cover, exceptions, rules
from app.modules.traceability._shared import EXCEPTION_ARTEFACT_TYPE, EXCEPTION_CODE_PREFIX
from app.modules.traceability.enums import ExceptionStatus
from app.modules.traceability.exception_views import record_code_and_title
from app.modules.traceability.models import (
    GovernanceProfile,
    TraceabilityException,
    TraceabilityExceptionComment,
    TraceabilityExceptionCommentFile,
    TraceabilityExceptionFile,
)
from app.services import record_summaries
from app.services.bundle_common import (
    BundleImportWarnings,
    UserResolver,
    export_file_links,
    import_bundled_file,
    import_file_links,
    prime_file_links,
)
from app.services.external_references import prime_record_references, record_references, restore_record_references
from app.services.long_text_core import NOTE_LIMIT
from app.services.placements import prime_record_placements, record_placements, restore_record_placements
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.sequences import generate_unique_code
from app.services.tags import prime_record_tag_names, record_tag_names, restore_record_tags
from app.services.template_reset import fresh_drafts, keeps_history

KEY = "traceability_exceptions"
#: A stored digest that matches no rule, so an imported approval of a changed rule keeps reading as changed.
_CHANGED_FINGERPRINT = "changed-before-import"


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def _instant(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def export_exceptions(db: Session, project: Project) -> tuple[list[dict[str, Any]], dict[uuid.UUID, FileAsset]]:
    """The project's exceptions as bundle entries, archived ones included, with the files they embed."""
    rows = list(db.scalars(
        select(TraceabilityException).where(TraceabilityException.project_id == project.id)
        .order_by(TraceabilityException.unique_code)
    ))
    assets: dict[uuid.UUID, FileAsset] = {}
    if not rows:
        return [], assets
    ids = [r.id for r in rows]
    wanted: dict[str, set[uuid.UUID]] = {}
    for row in rows:
        wanted.setdefault(row.artefact_type, set()).add(row.artefact_id)
    records = {
        (artefact_type, record_id): summary
        for artefact_type, record_ids in wanted.items()
        for record_id, summary in record_summaries.read_summaries(db, project.id, artefact_type, sorted(record_ids)).items()
    }
    entries = exceptions.rule_entries(db, project)
    prime_record_tag_names(db, EXCEPTION_ARTEFACT_TYPE, ids)
    prime_record_placements(db, EXCEPTION_ARTEFACT_TYPE, ids)
    prime_record_references(db, EXCEPTION_ARTEFACT_TYPE, ids)
    prime_file_links(db, TraceabilityExceptionFile, "exception_id", ids)
    comments: dict[uuid.UUID, list[TraceabilityExceptionComment]] = {}
    for comment in db.scalars(
        select(TraceabilityExceptionComment).where(TraceabilityExceptionComment.exception_id.in_(ids))
        .order_by(TraceabilityExceptionComment.created_at)
    ):
        comments.setdefault(comment.exception_id, []).append(comment)
    comment_files: dict[uuid.UUID, list[tuple[FileAsset, uuid.UUID]]] = {}
    comment_ids = [c.id for thread in comments.values() for c in thread]
    if comment_ids:
        for comment_id, asset, uploader in db.execute(
            select(TraceabilityExceptionCommentFile.comment_id, FileAsset, TraceabilityExceptionCommentFile.uploaded_by)
            .join(FileAsset, FileAsset.id == TraceabilityExceptionCommentFile.file_id)
            .where(TraceabilityExceptionCommentFile.comment_id.in_(comment_ids))
        ):
            comment_files.setdefault(comment_id, []).append((asset, uploader))
    people: set[uuid.UUID] = {c.author_id for thread in comments.values() for c in thread}
    people |= {uploader for found in comment_files.values() for _, uploader in found}
    for row in rows:
        people |= {p for p in (row.creator_id, row.decided_by_id, row.archived_by) if p is not None}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(people)))} if people else {}

    def comment_entry(comment: TraceabilityExceptionComment) -> dict[str, Any]:
        files = []
        for asset, uploader in comment_files.get(comment.id, []):
            assets[asset.id] = asset
            files.append({
                "file_ref": f"{asset.id}_{asset.filename}", "filename": asset.filename, "content_type": asset.content_type,
                "confidential": asset.confidential, "linked_by_email": emails.get(uploader),
            })
        return {
            "author_email": emails.get(comment.author_id), "body": comment.body, "created_at": _iso(comment.created_at),
            "edited_at": _iso(comment.edited_at), "attachments": files,
        }

    profile_names = _profile_names(db, entries)
    out = []
    for row in rows:
        code, title = record_code_and_title(records.get((row.artefact_type, row.artefact_id)))
        entry = None if row.rule_id is None else entries.get(row.rule_id)
        out.append({
            "unique_code": row.unique_code, "title": row.title,
            "record": {
                "artefact_type": row.artefact_type,
                "code": code or None,
                "title": title or None,
            },
            "rule": {
                "name": row.rule_name if entry is None else entry.rule.name,
                "profile": None if entry is None else profile_names.get(entry.rule.id),
            },
            "reason": row.reason,
            "requester": principal_to_bundle(db, row.requester_type, row.requester_id),
            "approver": principal_to_bundle(db, row.approver_type, row.approver_id),
            "status": row.status.value, "expires_on": _iso(row.expires_on), "review_date": _iso(row.review_date),
            "decided_by_email": emails.get(row.decided_by_id) if row.decided_by_id else None,
            "decided_at": _iso(row.decided_at), "decision_comment": row.decision_comment,
            "rule_changed": exception_cover.rule_changed(row, None if entry is None else entry.rule),
            "org_approved": row.org_approved,
            "created_by_email": emails.get(row.creator_id), "created_at": _iso(row.created_at),
            "is_archived": row.is_archived, "archived_at": _iso(row.archived_at),
            "archived_by_email": emails.get(row.archived_by) if row.archived_by else None,
            "tags": record_tag_names(db, EXCEPTION_ARTEFACT_TYPE, row.id),
            "placements": record_placements(db, EXCEPTION_ARTEFACT_TYPE, row.id),
            "external_references": record_references(db, EXCEPTION_ARTEFACT_TYPE, row.id),
            "attachments": export_file_links(db, TraceabilityExceptionFile, "exception_id", row.id, assets),
            "comments": [comment_entry(c) for c in comments.get(row.id, [])],
        })
    return out, assets


def _profile_names(db: Session, entries: Mapping[uuid.UUID, rules.EffectiveRule]) -> dict[uuid.UUID, str]:
    """`{rule id: profile name}` for the rules a profile owns."""
    owners = {e.rule.id: e.rule.profile_id for e in entries.values() if e.rule.profile_id is not None}
    if not owners:
        return {}
    names = {
        p.id: p.name for p in db.scalars(select(GovernanceProfile).where(GovernanceProfile.id.in_(set(owners.values()))))
    }
    return {rule_id: names[profile_id] for rule_id, profile_id in owners.items() if profile_id in names}


def reset_for_template(entries: list[dict[str, Any]]) -> None:
    """Returns exported exceptions to undecided requests, in place; a template also drops their discussion."""
    fresh_drafts(
        entries, status=ExceptionStatus.REQUESTED.value,
        clear=("decided_by_email", "decided_at", "decision_comment", "rule_changed", "org_approved"),
        empty=() if keeps_history() else ("comments",),
    )


class _Records:
    """The importing project's records by type, read once per type."""

    def __init__(self, db: Session, project: Project) -> None:
        self._db, self._project = db, project
        self._types: dict[str, tuple[dict[tuple[str, str], uuid.UUID], dict[str, list[uuid.UUID]]]] = {}

    def match(self, artefact_type: str, code: str | None, title: str | None) -> uuid.UUID | None:
        """The record with that code and title, else the only one with that title."""
        if title is None or artefact_type not in registry.get_all_registered_artefact_types():
            return None
        if artefact_type not in self._types:
            by_both: dict[tuple[str, str], uuid.UUID] = {}
            by_title: dict[str, list[uuid.UUID]] = {}
            for summary in record_summaries.list_summaries(self._db, self._project.id, artefact_type):
                code_here, own = record_code_and_title(summary)
                by_both[(code_here, own)] = summary.id
                by_title.setdefault(own, []).append(summary.id)
            self._types[artefact_type] = (by_both, by_title)
        by_both, by_title = self._types[artefact_type]
        found = by_both.get((code or "", title))
        if found is not None:
            return found
        named = by_title.get(title, [])
        return named[0] if len(named) == 1 else None


def import_exceptions(
    db: Session, project: Project, entries: list[dict[str, Any]], file_bytes: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the bundle's exceptions, numbered afresh."""
    if not entries:
        return
    effective = exceptions.rule_entries(db, project)
    profile_names = _profile_names(db, effective)
    by_rule = {(profile_names.get(rule_id), e.rule.name.casefold()): e for rule_id, e in effective.items()}
    records = _Records(db, project)
    has_authority = exceptions.has_org_authority(db, current_user.id, project.organization_id)
    for entry in entries:
        code = str(entry.get("unique_code", ""))
        record = entry.get("record") or {}
        artefact_type = str(record.get("artefact_type", ""))
        record_id = records.match(artefact_type, record.get("code"), record.get("title"))
        if record_id is None:
            warnings.add(f"Traceability exception {code}: its record was not found; the exception was not imported.")
            continue
        named = entry.get("rule") or {}
        rule_name = str(named.get("name", ""))
        rule = by_rule.get((named.get("profile"), rule_name.casefold()))
        if rule is None or rule.rule.source_type != artefact_type:
            warnings.add(f"Traceability exception {code}: the rule {rule_name!r} was not found; it covers nothing.")
            rule = None
        status = ExceptionStatus(entry.get("status", ExceptionStatus.REQUESTED.value))
        creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"Traceability exception {code} creator")
        decider = users.resolve(entry.get("decided_by_email"), required=False, context=f"Traceability exception {code} approver")
        fingerprint = None
        if status == ExceptionStatus.APPROVED and rule is not None:
            fingerprint = _CHANGED_FINGERPRINT if entry.get("rule_changed") else exception_cover.rule_fingerprint(rule.rule)
        org_approved = bool(entry.get("org_approved")) and has_authority
        if entry.get("org_approved") and not has_authority:
            warnings.add(
                f"Traceability exception {code}: its organisation-level approval was not carried over, because you do not "
                "hold that right."
            )
        archived = bool(entry.get("is_archived"))
        archiver = users.resolve(entry.get("archived_by_email"), required=False, context=f"Traceability exception {code} archiver")
        row = TraceabilityException(
            project_id=project.id,
            unique_code=generate_unique_code(db, project, EXCEPTION_ARTEFACT_TYPE, EXCEPTION_CODE_PREFIX),
            creator_id=creator_id, title=str(entry.get("title", ""))[:300], artefact_type=artefact_type,
            artefact_id=record_id, rule_id=None if rule is None else rule.rule.id, rule_name=rule_name[:200],
            reason=str(entry.get("reason", ""))[:NOTE_LIMIT], status=status, expires_on=_date(entry.get("expires_on")),
            review_date=_date(entry.get("review_date")), decided_by_id=decider, decided_at=_instant(entry.get("decided_at")),
            decision_comment=str(entry.get("decision_comment") or "")[:NOTE_LIMIT], approved_fingerprint=fingerprint,
            org_approved=org_approved, is_archived=archived, archived_at=_instant(entry.get("archived_at")),
            archived_by=(archiver or creator_id) if archived else None,
            **principal_columns_from_bundle(
                db, entry, "requester", organization_id=project.organization_id, project_id=project.id, users=users,
                warnings=warnings, context=f"Traceability exception {code} requester", required=True,
            ),
            **principal_columns_from_bundle(
                db, entry, "approver", organization_id=project.organization_id, project_id=project.id, users=users,
                warnings=warnings, context=f"Traceability exception {code} approver", required=False,
            ),
        )
        db.add(row)
        db.flush()
        _import_children(db, project, row, entry, file_bytes, current_user, users)


def _import_children(
    db: Session, project: Project, row: TraceabilityException, entry: Mapping[str, Any], file_bytes: dict[str, bytes],
    current_user: User, users: UserResolver,
) -> None:
    context = f"Traceability exception {entry.get('unique_code', '')}"
    shared: dict[str, Any] = {"artefact_type": EXCEPTION_ARTEFACT_TYPE, "artefact_id": row.id}
    restore_record_tags(
        db, organization_id=project.organization_id, record_project_id=project.id, actor_id=row.creator_id,
        names=entry.get("tags"), **shared,
    )
    restore_record_placements(db, project_id=project.id, actor_id=row.creator_id, entries=entry.get("placements"), **shared)
    restore_record_references(
        db, organization_id=project.organization_id, record_project_id=project.id, actor_id=row.creator_id,
        entries=entry.get("external_references"), **shared,
    )
    import_file_links(
        db, organization_id=project.organization_id, file_model=TraceabilityExceptionFile, fk="exception_id",
        record_id=row.id, entries=entry.get("attachments") or [], file_bytes_by_ref=file_bytes,
        current_user=current_user, users=users, context=context,
    )
    for comment in entry.get("comments") or []:
        author = users.resolve(comment.get("author_email"), required=False, context=f"{context} comment author")
        added = TraceabilityExceptionComment(
            exception_id=row.id, author_id=author or current_user.id, body=str(comment.get("body", ""))[:NOTE_LIMIT],
            created_at=_instant(comment.get("created_at")) or datetime.now(UTC),
            edited_at=_instant(comment.get("edited_at")),
        )
        db.add(added)
        db.flush()
        for attachment in comment.get("attachments") or []:
            data = file_bytes.get(attachment["file_ref"])
            if data is None:
                continue
            uploader = users.resolve(attachment.get("linked_by_email"), required=False, context=f"{context} file uploader")
            asset = import_bundled_file(
                db, organization_id=project.organization_id, uploaded_by=uploader or current_user.id,
                filename=attachment["filename"], content_type=attachment.get("content_type") or "application/octet-stream",
                data=data, confidential=bool(attachment.get("confidential")),
            )
            db.add(TraceabilityExceptionCommentFile(
                comment_id=added.id, file_id=asset.id, uploaded_by=uploader or current_user.id,
            ))
    db.flush()
