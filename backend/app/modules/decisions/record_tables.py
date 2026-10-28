"""
Module: modules.decisions.record_tables

The `RecordTableProvider` of Decision Management's one record type, the Decision: the Decisions list as a table,
so it exports to CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code
creates).

Responsibilities:
- Declare the Decision columns (title, statement, type, date, decision maker, owner, the ADR text fields, tags)
  and the status as an export-only cell.
- Share the list filters and the create / edit logic with the endpoints (`edits`), so the effective-type and
  principal checks, the content lock and the audit events are the ones the screen applies.

Design decisions:
- `status` is export-only: a Decision moves through propose / review / approve / reject only by the workflow
  endpoints, which keep segregation of duties and the AI-approval gate; a created Decision starts `Draft`.
  The type is marked approval-gated.
- Any project member may create (the create endpoint's gate); updating needs the Decision Owner role (the edit
  endpoint's gate), and an approved or superseded Decision refuses the edit per row, as the endpoint does.
- A blank owner on a new row means the importer (the create endpoint's default); a blank owner on an existing
  row is an error, because a Decision always has one.
- The type is written by name from the project's effective types, so a child project of a parent with decision
  types can use the parent's.

Dependencies: `edits` (queries and write paths), `service` (effective types), `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.decisions import edits
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.labels import DECISION_STATUS_LABEL, DECISION_STATUS_TONE
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE, resolve_effective_decision_types
from app.modules.registry import (
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.services import tags as tag_service
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells
from app.services.record_tables_core import (
    cached_lookup,
    count_rows,
    date_parser,
    enum_filter,
    list_cell,
    person_parser,
    text_parser,
)

DECISIONS_MODULE_KEY = "decisions"

#: Statuses the Decisions list's "Open only" view keeps (mirrors `DECISION_OPEN_STATUSES` in
#: `frontend/src/modules/decisions/types.ts`).
DECISION_OPEN = frozenset({DecisionStatus.DRAFT, DecisionStatus.PROPOSED, DecisionStatus.UNDER_REVIEW})

#: The list's filters by the names its export takes: `type` is a decision type id, `mine` the caller's own and their
#: groups' Decisions.
DECISION_FILTERS = frozenset({"include_archived", "status", "type", "mine", "decision_maker_mine", "open_only", "search"})

_ADR_TEXT = ("context", "options_considered", "chosen_option", "rationale", "consequences", "assumptions", "constraints")
_ADR_LABELS = {
    "context": "Context", "options_considered": "Options considered", "chosen_option": "Chosen option",
    "rationale": "Rationale", "consequences": "Consequences", "assumptions": "Assumptions", "constraints": "Constraints",
}


class _Prepared:
    """Lookups handed to every column's `get`: owner and decision maker cells, tags and the type names."""

    def __init__(self, db: Session, records: list[Decision]) -> None:
        refs = [
            ref for d in records
            for ref in (principal_ref(d.owner_type, d.owner_id), principal_ref(d.decision_maker_type, d.decision_maker_id))
        ]
        self.people = PrincipalCells.load(db, refs)
        ids = [r.id for r in records]
        self.tags = tag_service.tag_names_for_records(db, DECISION_ARTEFACT_TYPE, ids) if ids else {}
        type_ids = {r.decision_type_id for r in records}
        self.type_names: dict[uuid.UUID, str] = {
            t.id: t.name for t in db.scalars(select(DecisionTypeDefinition).where(DecisionTypeDefinition.id.in_(type_ids)))
        } if type_ids else {}


def _list_decisions(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Decision]:
    status = enum_filter(filters, "status", DecisionStatus)
    type_id = filters.one("type")
    decisions = edits.filter_decisions(
        db, user, project_id, include_archived=bool(filters.flag("include_archived")),
        decision_type_id=uuid.UUID(type_id) if type_id else None, status_filter=status,
        owner_mine=bool(filters.flag("mine")), decision_maker_mine=bool(filters.flag("decision_maker_mine")),
    )
    if filters.flag("open_only"):
        decisions = [d for d in decisions if d.status in DECISION_OPEN]
    return edits.search_decisions(decisions, filters.one("search"))


def _decision_type_id(ctx: RecordImportContext, name: str) -> uuid.UUID:
    """The id of the project's effective decision type called `name`."""
    types = cached_lookup(ctx, "decision:types", lambda: {
        t.name.casefold(): t.id for t in reversed(resolve_effective_decision_types(ctx.db, ctx.project.id))
    })
    found = types.get(name.casefold())
    if found is None:
        raise RecordCellError(f"Unknown Decision type '{name}'.")
    return found


def _adr_column(key: str) -> RecordColumn:
    return RecordColumn(key, _ADR_LABELS[key], lambda t, r: getattr(r, key) or "", text_parser, editable=True)


def _decision_columns(db: Session, project: Project) -> list[RecordColumn]:
    types = resolve_effective_decision_types(db, project.id)
    return [
        RecordColumn("title", "Title", lambda t, r: r.title, text_parser, editable=True, required=True),
        RecordColumn(
            "decision_statement", "Decision statement", lambda t, r: r.decision_statement, text_parser, editable=True, required=True,
        ),
        RecordColumn(
            "type", "Type", lambda t, r: t.type_names.get(r.decision_type_id, ""), _decision_type_id, kind="enum",
            editable=True, required=True, choices=tuple(x.name for x in types),
        ),
        RecordColumn(
            "decision_date", "Decision date", lambda t, r: r.decision_date.isoformat() if r.decision_date else "",
            date_parser("Decision date"), kind="date", editable=True,
        ),
        RecordColumn(
            "decision_maker", "Decision maker", lambda t, r: t.people.text(r.decision_maker_type, r.decision_maker_id),
            person_parser("decision_maker"), kind="principal",
        ),
        RecordColumn("owner", "Owner", lambda t, r: t.people.text(r.owner_type, r.owner_id), person_parser("owner"), kind="principal"),
        *(_adr_column(key) for key in _ADR_TEXT),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
        RecordColumn(
            "status", "Status", lambda t, r: DECISION_STATUS_LABEL[r.status.value], kind="enum",
            tones={DECISION_STATUS_LABEL[value]: tone for value, tone in DECISION_STATUS_TONE.items()},
        ),
    ]


def _fields(values: Mapping[str, Any]) -> dict[str, Any]:
    """The `edits` keyword arguments for the cells in `values`."""
    fields = {key: values[key] for key in ("title", "decision_statement", "decision_date", "decision_maker", "owner") + _ADR_TEXT if key in values}
    if "type" in values:
        fields["decision_type_id"] = values["type"]
    return fields


def _may_create(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """Any project member with the module enabled may create (the create endpoint's gate)."""
    return True


def _may_update(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The edit endpoint's gate: the Decision Owner role (composing with admin and project manager)."""
    return edits.user_is_decision_owner(db, user, db.get(Project, project_id))


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> Decision:
    fields = _fields(values)
    return edits.stage_decision(
        ctx.db, ctx.project, ctx.user, title=fields.pop("title"), decision_statement=fields.pop("decision_statement"),
        decision_type_id=fields.pop("decision_type_id"), decision_date=fields.pop("decision_date", None),
        decision_maker=fields.pop("decision_maker", None), owner=fields.pop("owner", None), **fields,
    )


def _update(ctx: RecordImportContext, decision: Decision, values: Mapping[str, Any]) -> None:
    edits.stage_decision_update(ctx.db, ctx.project, decision, ctx.user, _fields(values))


def _find(db: Session, project: Project, code: str) -> Decision | None:
    return db.scalar(select(Decision).where(Decision.project_id == project.id, Decision.unique_code == code.upper()))


DECISION_TABLE = RecordTableProvider(
    label="Decisions",
    columns=_decision_columns,
    list_records=_list_decisions,
    find=_find,
    prepare=lambda db, project, records: _Prepared(db, records),
    create=_create,
    update=_update,
    filter_params=DECISION_FILTERS,
    gate=(DECISIONS_MODULE_KEY, None),
    can_create=_may_create,
    can_update=_may_update,
    approval_gated=True,
    count=lambda db, user, project_id: count_rows(db, Decision, project_id, live_only=True),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {DECISION_ARTEFACT_TYPE: DECISION_TABLE}
