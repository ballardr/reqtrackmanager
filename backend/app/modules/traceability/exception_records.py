"""
Module: modules.traceability.exception_records

How a traceability exception is found, listed, reported and exchanged as a record: its summary and search providers,
record table (export and import), report fields, evidence attachments, long-text declaration and scaling probe.

Responsibilities:
- Register the type with each core surface a record type takes part in.

Design decisions:
- A summary and a search result carry the exception's own code and title, never the excepted record's content.
- The record table names the excepted record by its code and the rule by its name. Both identify the exception, so a
  create reads them and an update refuses to change them.
- An import raises requests: status, decision and approver authority are export-only, so no file approves anything. An
  imported request notifies nobody.
- The table lists only exceptions whose record type the exporting person may read.

Dependencies: `exceptions`, `exception_views`, `models`, `modules.registry`, `services.search_core`,
`services.record_tables_core`, `services.report_fields`, `services.record_summaries`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.code_rules import leading_code
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    ArtefactSearchProvider,
    ArtefactSummary,
    ArtefactSummaryProvider,
    BrowseLevel,
    MarkdownField,
    RecordAttachmentProvider,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
    ReportFieldProvider,
    ScalingProbe,
    SearchColumns,
    SearchField,
    markdown_columns,
)
from app.modules.traceability import exception_views, exceptions
from app.modules.traceability._shared import (
    EXCEPTION_ARTEFACT_TYPE,
    TRACEABILITY_EXCEPTIONS,
    TRACEABILITY_MODULE_KEY,
)
from app.modules.traceability.enums import ExceptionStatus
from app.modules.traceability.labels import EXCEPTION_STATUS_LABEL, EXCEPTION_STATUS_TONE
from app.modules.traceability.models import (
    TraceabilityException,
    TraceabilityExceptionComment,
    TraceabilityExceptionFile,
)
from app.services import record_summaries
from app.services import tags as tag_service
from app.services.long_text_core import NOTE_LIMIT
from app.services.principals import principal_ref
from app.services.rbac import get_effective_permissions
from app.services.record_tables import PrincipalCells, find_many_by_code
from app.services.record_tables_core import (
    cached_lookup,
    count_rows,
    date_parser,
    enum_filter,
    list_cell,
    person_parser,
    text_parser,
    uuid_filter,
)
from app.services.report_fields import date_field, from_search, principal_field, text_field
from app.services.search_core import comments_of
from app.services.summary_facets import status_facet

# --- summary and search -----------------------------------------------------------------------------


def _summaries(rows: Sequence[TraceabilityException]) -> list[ArtefactSummary]:
    return [
        ArtefactSummary(
            id=r.id, project_id=r.project_id, label=f"{r.unique_code} {r.title}", status=r.status.value,
            is_archived=r.is_archived, facets={"status": status_facet(r.status.value, EXCEPTION_STATUS_LABEL)},
        )
        for r in rows
    ]


def _get(db: Session, record_id: uuid.UUID) -> ArtefactSummary | None:
    row = db.get(TraceabilityException, record_id)
    return None if row is None else _summaries([row])[0]


def _list_for_project(db: Session, project_id: uuid.UUID) -> list[ArtefactSummary]:
    return _summaries(list(db.scalars(
        select(TraceabilityException)
        .where(TraceabilityException.project_id == project_id, TraceabilityException.is_archived.is_(False))
        .order_by(TraceabilityException.unique_code)
    )))


def _get_many_in_project(db: Session, project_id: uuid.UUID, ids: Sequence[uuid.UUID]) -> list[ArtefactSummary]:
    return _summaries(list(db.scalars(
        select(TraceabilityException)
        .where(TraceabilityException.project_id == project_id, TraceabilityException.id.in_(ids))
    )))


SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    EXCEPTION_ARTEFACT_TYPE: ArtefactSummaryProvider(
        get=_get, list_for_project=_list_for_project, get_many_in_project=_get_many_in_project,
        browse_levels=(BrowseLevel("status", "Status"),),
    ),
}

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    EXCEPTION_ARTEFACT_TYPE: ArtefactSearchProvider(
        from_clause=TraceabilityException.__table__,
        columns=SearchColumns(
            id=TraceabilityException.id, project_id=TraceabilityException.project_id,
            code=TraceabilityException.unique_code, title=TraceabilityException.title,
            status=TraceabilityException.status, is_archived=TraceabilityException.is_archived,
            updated_at=TraceabilityException.updated_at,
        ),
        fields=(SearchField("reason", "Reason", TraceabilityException.reason, markdown=True),),
        status_labels=EXCEPTION_STATUS_LABEL,
        comments=comments_of(TraceabilityExceptionComment, TraceabilityExceptionComment.exception_id),
    ),
}

REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    EXCEPTION_ARTEFACT_TYPE: from_search(
        SEARCH_PROVIDERS[EXCEPTION_ARTEFACT_TYPE],
        text_field("rule_name", "Rule", TraceabilityException.rule_name),
        principal_field("requester", "Requester", TraceabilityException.requester_type, TraceabilityException.requester_id),
        principal_field("approver", "Approver", TraceabilityException.approver_type, TraceabilityException.approver_id),
        date_field("expires_on", "Expiry date", TraceabilityException.expires_on),
        date_field("review_date", "Review date", TraceabilityException.review_date),
        core_fields=("reason", "rule_name"),
    ),
}

RECORD_ATTACHMENTS: dict[str, RecordAttachmentProvider] = {
    EXCEPTION_ARTEFACT_TYPE: RecordAttachmentProvider(TraceabilityExceptionFile, TraceabilityExceptionFile.exception_id),
}

MARKDOWN_FIELDS: tuple[MarkdownField, ...] = (
    *markdown_columns(TraceabilityException, "reason", "decision_comment", limit=NOTE_LIMIT),
    *markdown_columns(TraceabilityExceptionComment, "body", limit=NOTE_LIMIT),
)


# --- record table -----------------------------------------------------------------------------------

IMPORT_FILTERS = frozenset({"include_archived", "status", "artefact_type", "record_id", "rule_id", "open_only", "search"})


def _list_exceptions(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Any]:
    """The rows the list page's filters keep."""
    query = select(TraceabilityException).where(TraceabilityException.project_id == project_id)
    if not filters.flag("include_archived"):
        query = query.where(TraceabilityException.is_archived.is_(False))
    state = enum_filter(filters, "status", ExceptionStatus)
    if state is not None:
        query = query.where(TraceabilityException.status == state)
    if filters.one("artefact_type"):
        query = query.where(TraceabilityException.artefact_type == filters.one("artefact_type"))
    for name, column in (("record_id", TraceabilityException.artefact_id), ("rule_id", TraceabilityException.rule_id)):
        value = uuid_filter(filters, name)
        if value is not None:
            query = query.where(column == value)
    held = get_effective_permissions(db, user.id, project_id=project_id)
    rows = exceptions.readable(held, list(db.scalars(query.order_by(TraceabilityException.unique_code))))
    needle = filters.one("search")
    if needle:
        rows = [r for r in rows if needle.casefold() in f"{r.unique_code} {r.title} {r.rule_name} {r.reason}".casefold()]
    if filters.flag("open_only"):
        project = db.get(Project, project_id)
        keep = {o.id for o in exception_views.rows_out(db, project, rows) if exception_views.is_open(o)} if project else set()
        rows = [r for r in rows if r.id in keep]
    return rows


class _Prepared:
    """Lookups handed to every column's `get`."""

    def __init__(self, db: Session, project: Project, records: list[Any]) -> None:
        self.out = {o.id: o for o in exception_views.rows_out(db, project, records)}
        self.people = PrincipalCells.load(db, [
            ref for r in records for ref in (
                principal_ref(r.requester_type, r.requester_id), principal_ref(r.approver_type, r.approver_id),
            )
        ])
        ids = [r.id for r in records]
        self.tags = tag_service.tag_names_for_records(db, EXCEPTION_ARTEFACT_TYPE, ids) if ids else {}


def _iso(value: Any) -> str:
    return value.isoformat() if value else ""


def _rule_choices(ctx: RecordImportContext) -> dict[str, list[Any]]:
    """The project's active rules by name, ignoring case; a name held twice maps to both."""

    def load() -> dict[str, list[Any]]:
        found: dict[str, list[Any]] = {}
        for entry in exceptions.rule_entries(ctx.db, ctx.project).values():
            if entry.active:
                found.setdefault(entry.rule.name.casefold(), []).append(entry)
        return found

    return cached_lookup(ctx, "traceability:rules", load)


def _rule_parser(ctx: RecordImportContext, text: str) -> uuid.UUID:
    found = _rule_choices(ctx).get(text.casefold(), [])
    if not found:
        raise RecordCellError(f"'{text}' is not a traceability rule in effect for this project.")
    if len(found) > 1:
        raise RecordCellError(f"More than one rule is named '{text}'; rename one before importing.")
    return found[0].rule.id


def _record_by_code(ctx: RecordImportContext, artefact_type: str, code: str) -> uuid.UUID:
    def load() -> dict[str, uuid.UUID]:
        found: dict[str, uuid.UUID] = {}
        for summary in record_summaries.list_summaries(ctx.db, ctx.project.id, artefact_type):
            own = leading_code(summary.label)
            if own and not summary.is_archived:
                found[own.upper()] = summary.id
        return found

    record_id = cached_lookup(ctx, f"traceability:records:{artefact_type}", load).get(code.upper())
    if record_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The project has no record '{code}' of the type the rule applies to.",
        )
    return record_id


def _locked_identity(prepared: Any, record: Any) -> str:
    return "The record and the rule identify an exception; raise a new one for a different pair."


def _columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        RecordColumn("title", "Title", lambda t, r: r.title, text_parser, editable=True),
        RecordColumn(
            "record_type", "Record type", lambda t, r: t.out[r.id].record.artefact_type_label, kind="enum",
        ),
        RecordColumn(
            "record", "Record", lambda t, r: t.out[r.id].record.code, text_parser, required=True,
            cell_lock=_locked_identity,
        ),
        RecordColumn(
            "rule", "Rule", lambda t, r: t.out[r.id].rule_name, _rule_parser, required=True, cell_lock=_locked_identity,
        ),
        RecordColumn("reason", "Reason", lambda t, r: r.reason, text_parser, required=True, markdown=True),
        RecordColumn(
            "requester", "Requester", lambda t, r: t.people.text(r.requester_type, r.requester_id),
            person_parser("requester"), kind="principal",
        ),
        RecordColumn(
            "approver", "Approver", lambda t, r: t.people.text(r.approver_type, r.approver_id),
            person_parser("approver"), kind="principal",
        ),
        RecordColumn(
            "expires_on", "Expiry date", lambda t, r: _iso(r.expires_on), date_parser("Expiry date"), kind="date",
            editable=True,
        ),
        RecordColumn(
            "review_date", "Review date", lambda t, r: _iso(r.review_date), date_parser("Review date"), kind="date",
            editable=True,
        ),
        RecordColumn(
            "status", "Status", lambda t, r: EXCEPTION_STATUS_LABEL[r.status.value], kind="enum",
            tones={EXCEPTION_STATUS_LABEL[value]: tone for value, tone in EXCEPTION_STATUS_TONE.items()},
        ),
        RecordColumn("covers", "Covers the record", lambda t, r: "Yes" if t.out[r.id].covers else "No", kind="enum"),
        RecordColumn("decided_by", "Decided by", lambda t, r: t.out[r.id].decided_by_name or ""),
        RecordColumn("decided_at", "Decided at", lambda t, r: _iso(r.decided_at), kind="instant"),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
    ]


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> TraceabilityException:
    rule_id, code = values.get("rule"), (values.get("record") or "").strip()
    if rule_id is None or not code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A new exception needs a record and a rule.")
    entry = exceptions.rule_entries(ctx.db, ctx.project)[rule_id]
    return exceptions.create_exception(
        ctx.db, project=ctx.project, actor=ctx.user, artefact_type=entry.rule.source_type,
        artefact_id=_record_by_code(ctx, entry.rule.source_type, code), rule_id=rule_id, title=values.get("title"),
        reason=values.get("reason") or "", requester=values.get("requester"), approver=values.get("approver"),
        expires_on=values.get("expires_on"), review_date=values.get("review_date"), notify=False,
    )


def _update(ctx: RecordImportContext, exception: TraceabilityException, values: Mapping[str, Any]) -> None:
    if "record" in values or "rule" in values:
        raise HTTPException(status.HTTP_409_CONFLICT, _locked_identity(None, exception))
    exceptions.update_exception(ctx.db, project=ctx.project, exception=exception, actor=ctx.user, changes=values)


def _find(db: Session, project: Project, code: str) -> TraceabilityException | None:
    return db.scalar(select(TraceabilityException).where(
        TraceabilityException.project_id == project.id, TraceabilityException.unique_code == code.upper(),
    ))


def _may_write(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """Any member may raise a request; each row's own rights are checked by the create and update functions."""
    return True


RECORD_TABLES: dict[str, RecordTableProvider] = {
    EXCEPTION_ARTEFACT_TYPE: RecordTableProvider(
        label="Traceability exceptions",
        columns=_columns,
        list_records=_list_exceptions,
        find=_find,
        find_many=find_many_by_code(TraceabilityException, "project_id"),
        prepare=lambda db, project, records: _Prepared(db, project, records),
        create=_create,
        update=_update,
        filter_params=IMPORT_FILTERS,
        gate=(TRACEABILITY_MODULE_KEY, TRACEABILITY_EXCEPTIONS),
        can_create=_may_write,
        can_update=_may_write,
        approval_gated=True,
        count=lambda db, user, project_id: count_rows(db, TraceabilityException, project_id, live_only=True),
    ),
}


# --- scaling probe ----------------------------------------------------------------------------------

_BASE = f"modules/{TRACEABILITY_MODULE_KEY}"
_PROBE_RULE = "Probe rule"


def _probe_place(api: Any, project_id: str) -> tuple[str, str]:
    base = f"/projects/{project_id}"
    components = api.get(f"{base}/components")
    component_id = components[0]["id"] if components else api.post(
        f"{base}/components", {"name": "Software", "prefix": "SW"}
    )["id"]
    categories = api.get(f"{base}/categories")
    category_id = categories[0]["id"] if categories else api.post(
        f"{base}/categories", {"name": "Performance", "prefix": "PERF", "component_id": component_id}
    )["id"]
    return component_id, category_id


def _probe_create(api: Any, project_id: str, start: int, count: int) -> list[str]:
    # Each exception is for its own requirement, so a list that reads records or rules per row grows.
    base = f"/projects/{project_id}"
    component_id, category_id = _probe_place(api, project_id)
    rules = [r for r in api.get(f"{base}/{_BASE}/rules")["rules"] if r["name"] == _PROBE_RULE]
    rule_id = rules[0]["id"] if rules else api.post(f"{base}/{_BASE}/rules", {
        "name": _PROBE_RULE, "source_type": "requirement", "level": "required",
        "requires": {"op": "link", "targets": [{"artefact_type": "requirement"}]},
    })["id"]
    out = []
    for i in range(count):
        requirement_id = api.post(
            f"{base}/requirements",
            {"name": f"Probe excepted {start + i}", "component_id": component_id, "category_id": category_id},
        )["id"]
        out.append(api.post(
            f"{base}/{_BASE}/exceptions",
            {"artefact_type": "requirement", "artefact_id": requirement_id, "rule_id": rule_id,
             "reason": "Scaling probe", "review_date": "2099-01-01"},
        )["id"])
    return out


SCALING_PROBES: dict[str, ScalingProbe] = {
    EXCEPTION_ARTEFACT_TYPE: ScalingProbe(list_path=f"{_BASE}/exceptions", create=_probe_create),
}
