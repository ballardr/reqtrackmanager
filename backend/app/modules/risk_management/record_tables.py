"""
Module: modules.risk_management.record_tables

The `RecordTableProvider` of Risk Management's one record type, the Risk: the register as a table, so it exports
to CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code creates).

Responsibilities:
- Declare the Risk columns (text, type, treatment strategy, the six scoring levels by name, owner, review date,
  tags) and the derived ratings and status as export-only cells.
- Share the create and edit logic with the endpoints (`_shared.stage_risk` / `stage_risk_update`), so the
  scoring-level and type validation, the accepted-risk content lock, the version history and the audit event
  are the ones the screen applies.

Design decisions:
- `status` is export-only: a Risk moves through its lifecycle only by the transition endpoint, whose guards
  (an inherent rating before Assessed, the separate Risk Acceptor sign-off for Accepted) a file must not bypass.
  A created Risk starts `Identified`, as the create endpoint starts it. The type is marked approval-gated.
- The inherent and residual ratings are derived on every read and so are export-only; the levels they come from
  are the columns, written by the level's name on its axis (`Likely`, `Major`) for the organisation's own scheme.
- Updating needs the Risk Manager role (the edit endpoint's gate); any project member may create (the create
  endpoint's gate), including naming an owner.
- A change to an accepted Risk's signed-off assessment is refused per row with the endpoint's message.
- Rating tones and the type pick list are read from the project when the table is built, so a project's own
  rating bands and its enabled types are what the cells and the pick lists show.

Dependencies: `_shared` (stage functions, gates), `ratings`, `service`, `treatment`, `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.modules.risk_management import _shared as sh
from app.modules.risk_management.enums import RiskStatus, TreatmentStrategy
from app.modules.risk_management.labels import RISK_STATUS_LABEL, RISK_STATUS_TONE
from app.modules.risk_management.models import Risk, RiskVersion
from app.modules.risk_management.ratings import load_rating_context, rate_version
from app.modules.risk_management.schemas import RiskCreate, RiskUpdate
from app.modules.risk_management.scoring import LEVEL_COLUMN_AXES, RISK_SCORING_SCHEME_KEY
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    RISK_TYPES,
    list_project_risks,
)
from app.modules.risk_management.treatment import effective_treatment_counts
from app.services import tags as tag_service
from app.services.client_date import effective_today
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells
from app.services.record_tables_core import (
    cached_lookup,
    count_rows,
    date_parser,
    enum_filter,
    enum_parser,
    label_map,
    list_cell,
    person_parser,
    text_parser,
)
from app.services.scoring import list_levels

IMPORT_NOTE = "Edited by record import."

#: Statuses the register's "Open only" view keeps (mirrors `RISK_OPEN_STATUSES` in
#: `frontend/src/modules/risk_management/types.ts`).
RISK_OPEN = frozenset({
    RiskStatus.IDENTIFIED, RiskStatus.ASSESSED, RiskStatus.TREATMENT_PLANNED, RiskStatus.TREATMENT_IN_PROGRESS,
    RiskStatus.MITIGATED, RiskStatus.ACCEPTED,
})

#: The register's own filters, by the names its export takes. `cell` is the matrix cell the page filters on
#: (`inherent~<likelihood level id>~<consequence level id>`).
RISK_FILTERS = frozenset({"include_archived", "status", "type", "open_only", "review_overdue", "untreated", "cell", "search"})

_TEXT = ("statement", "cause", "risk_event", "consequence", "acceptance_criteria")
_STRATEGY_LABELS = label_map(TreatmentStrategy)

#: Level column key (`inherent_likelihood`) -> (the `RiskVersion` level column, the label shown).
_LEVEL_COLUMNS: dict[str, tuple[str, str]] = {
    column.removesuffix("_level_id"): (column, column.removesuffix("_level_id").replace("_", " ").capitalize())
    for column in LEVEL_COLUMN_AXES
}


class _Prepared:
    """Lookups handed to every column's `get`: current versions, owner cells, tags, type and level names, ratings."""

    def __init__(self, db: Session, project: Project, records: list[Any]) -> None:
        ids = [r.id for r in records]
        self.versions: dict[uuid.UUID, RiskVersion] = {
            v.risk_id: v
            for v in db.scalars(select(RiskVersion).where(RiskVersion.risk_id.in_(ids), RiskVersion.valid_to.is_(None)))
        } if ids else {}
        self.people = PrincipalCells.load(db, [principal_ref(v.owner_type, v.owner_id) for v in self.versions.values()])
        self.tags = tag_service.tag_names_for_records(db, RISK_ARTEFACT_TYPE, ids) if ids else {}
        self.type_names: dict[uuid.UUID, str] = {}
        for version in self.versions.values():
            type_id = version.project_type_id
            if type_id is not None and type_id not in self.type_names:
                self.type_names[type_id] = RISK_TYPES.display_name(db, org_type_id=None, project_type_id=type_id) or ""
        self.level_names = {
            level.id: level.name
            for levels in list_levels(db, project.organization_id, RISK_SCORING_SCHEME_KEY).values() for level in levels
        }
        ctx = load_rating_context(db, project)
        self.ratings = {rid: rate_version(ctx, v) for rid, v in self.versions.items()}


def _cell_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _parse_cell_filter(text: str | None) -> tuple[str, uuid.UUID, uuid.UUID] | None:
    """The matrix cell filter `basis~likelihood~consequence`, or `None` when absent or malformed."""
    if not text:
        return None
    parts = text.split("~")
    if len(parts) != 3 or parts[0] not in ("inherent", "residual"):
        return None
    try:
        return parts[0], uuid.UUID(parts[1]), uuid.UUID(parts[2])
    except ValueError:
        return None


def _list_risks(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Any]:
    """The project's risks the register's filters keep, oldest first (the register page applies the same rules)."""
    risks = list_project_risks(db, project_id, include_archived=bool(filters.flag("include_archived")))
    if not risks:
        return risks
    status = enum_filter(filters, "status", RiskStatus)
    type_id, needle = filters.one("type"), filters.one("search")
    cell = _parse_cell_filter(filters.one("cell"))
    versions = {
        v.risk_id: v
        for v in db.scalars(select(RiskVersion).where(RiskVersion.risk_id.in_([r.id for r in risks]), RiskVersion.valid_to.is_(None)))
    }
    counts = effective_treatment_counts(db, [r.id for r in risks]) if filters.flag("untreated") else {}
    today = effective_today()
    kept = []
    for risk in risks:
        version = versions[risk.id]
        if status is not None and version.status != status:
            continue
        if filters.flag("open_only") and version.status not in RISK_OPEN:
            continue
        if type_id and str(version.project_type_id) != type_id:
            continue
        if filters.flag("review_overdue") and not (
            version.review_date is not None and version.review_date < today
            and version.status != RiskStatus.CLOSED and not risk.is_archived
        ):
            continue
        if filters.flag("untreated") and counts.get(risk.id, 0) > 0:
            continue
        if cell is not None:
            basis, likelihood, consequence = cell
            held = (getattr(version, f"{basis}_likelihood_level_id"), getattr(version, f"{basis}_consequence_level_id"))
            if held != (likelihood, consequence):
                continue
        if needle and needle.casefold() not in f"{risk.unique_code} {version.title} {version.statement}".casefold():
            continue
        kept.append(risk)
    return kept


def _risk_type_id(ctx: RecordImportContext, name: str) -> uuid.UUID | None:
    """The effective-type id for a type name of this project (a blank cell means no type)."""
    if not name:
        return None
    types = cached_lookup(ctx, "risk:types", lambda: {
        t.name.casefold(): t.id
        for t in RISK_TYPES.resolve_effective(ctx.db, ctx.project.id, ctx.project.organization_id) if t.is_enabled
    })
    found = types.get(name.casefold())
    if found is None:
        raise RecordCellError(f"Unknown Risk type '{name}'.")
    return found


def _level_parser(column: str) -> Any:
    """A parser for a scoring level cell: the level's name on the column's axis in the organisation's scheme."""
    axis = LEVEL_COLUMN_AXES[column]

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            return None
        levels = cached_lookup(ctx, "risk:levels", lambda: {
            key: {level.name.casefold(): level.id for level in rows}
            for key, rows in list_levels(ctx.db, ctx.project.organization_id, RISK_SCORING_SCHEME_KEY).items()
        })
        found = levels.get(axis, {}).get(text.casefold())
        if found is None:
            raise RecordCellError(f"'{text}' is not a {axis} level of this organisation's risk scheme.")
        return found

    return parse


def _text(key: str, label: str, *, required: bool = False) -> RecordColumn:
    return RecordColumn(
        key, label, lambda t, r: getattr(t.versions[r.id], key) or "", text_parser, editable=True, required=required,
    )


def _risk_columns(db: Session, project: Project) -> list[RecordColumn]:
    bands = {b.label: b.tone for b in load_rating_context(db, project).bands}
    levels = list_levels(db, project.organization_id, RISK_SCORING_SCHEME_KEY)
    types = RISK_TYPES.resolve_effective(db, project.id, project.organization_id)

    def level_column(key: str) -> RecordColumn:
        column, label = _LEVEL_COLUMNS[key]
        return RecordColumn(
            key, label, lambda t, r: t.level_names.get(getattr(t.versions[r.id], column), ""), _level_parser(column),
            kind="enum", editable=True, choices=tuple(level.name for level in levels.get(LEVEL_COLUMN_AXES[column], [])),
        )

    def rating(index: int) -> Any:
        def get(t: _Prepared, r: Any) -> str:
            found = t.ratings[r.id][index]
            return (found.label or "") if found is not None else ""

        return get

    return [
        _text("title", "Title", required=True),
        _text("statement", "Statement"),
        _text("cause", "Cause"),
        _text("risk_event", "Risk event"),
        _text("consequence", "Consequence"),
        RecordColumn(
            "type", "Type", lambda t, r: t.type_names.get(t.versions[r.id].project_type_id, ""), _risk_type_id,
            kind="enum", editable=True, choices=tuple(x.name for x in types if x.is_enabled),
        ),
        RecordColumn(
            "treatment_strategy", "Treatment strategy",
            lambda t, r: _STRATEGY_LABELS[t.versions[r.id].treatment_strategy.value] if t.versions[r.id].treatment_strategy else "",
            enum_parser(TreatmentStrategy, "Treatment strategy"), kind="enum", editable=True,
            choices=tuple(_STRATEGY_LABELS.values()),
        ),
        _text("acceptance_criteria", "Acceptance criteria"),
        *(level_column(key) for key in _LEVEL_COLUMNS),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(t.versions[r.id].owner_type, t.versions[r.id].owner_id),
            person_parser("owner"), kind="principal",
        ),
        RecordColumn(
            "review_date", "Review date", lambda t, r: _cell_date(t.versions[r.id].review_date), date_parser("Review date"),
            kind="date", editable=True,
        ),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
        RecordColumn("inherent_rating", "Inherent rating", rating(0), kind="enum", tones=bands),
        RecordColumn("residual_rating", "Residual rating", rating(1), kind="enum", tones=bands),
        RecordColumn(
            "status", "Status", lambda t, r: RISK_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones={RISK_STATUS_LABEL[value]: tone for value, tone in RISK_STATUS_TONE.items()},
        ),
    ]


def _fields(values: Mapping[str, Any]) -> dict[str, Any]:
    """The `RiskCreate` / `RiskUpdate` keyword arguments for the cells in `values`."""
    fields: dict[str, Any] = {
        key: values[key] for key in _TEXT + ("title", "treatment_strategy", "owner", "review_date") if key in values
    }
    if "type" in values:
        fields["risk_type_id"] = values["type"]
    for key, (column, _label) in _LEVEL_COLUMNS.items():
        if key in values:
            fields[column] = values[key]
    return fields


def _may_manage(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The edit endpoint's gate: the Risk Manager role or the `(risk, manage)` grant."""
    try:
        sh.require_risk_manage(db, user, db.get(Project, project_id))
    except HTTPException:
        return False
    return True


def _may_create(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """Any project member may propose a risk (the create endpoint's gate)."""
    return True


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> Risk:
    return sh.stage_risk(ctx.db, RiskCreate(**_fields(values)), ctx.user, ctx.project)


def _update(ctx: RecordImportContext, risk: Risk, values: Mapping[str, Any]) -> None:
    sh.stage_risk_update(ctx.db, risk, RiskUpdate(**_fields(values), change_note=IMPORT_NOTE), ctx.user, ctx.project)


def _find(db: Session, project: Project, code: str) -> Risk | None:
    return db.scalar(select(Risk).where(Risk.project_id == project.id, Risk.unique_code == code.upper()))


RISK_TABLE = RecordTableProvider(
    label="Risks",
    columns=_risk_columns,
    list_records=_list_risks,
    find=_find,
    prepare=lambda db, project, records: _Prepared(db, project, records),
    create=_create,
    update=_update,
    filter_params=RISK_FILTERS,
    gate=(RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY),
    can_create=_may_create,
    can_update=_may_manage,
    approval_gated=True,
    count=lambda db, user, project_id: count_rows(db, Risk, project_id, live_only=True),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {RISK_ARTEFACT_TYPE: RISK_TABLE}
