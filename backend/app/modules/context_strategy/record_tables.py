"""
Module: modules.context_strategy.record_tables

The `RecordTableProvider`s of Context & Strategy's five record types (Strategy, Future State, Guiding
Principle, Pain Point, Open Question): the columns of each list as a table, so every one of them exports to
CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code creates).

Responsibilities:
- Declare, per type, the columns (key, label, cell text, parser, editable flag) and how a row is created or
  updated.
- Share the list query with the list endpoint and the create / edit logic with the edit endpoint
  (`edits.py`), so a filter, lock or audit event added there reaches the file too.

Design decisions:
- Create and update go through the same checks as the endpoints: any project member may create (the
  endpoints' gate), a record's owner role (`strategy_owner`, `pain_point_manager`, ...) may update, and a
  record past review or at a terminal outcome refuses the edit (the row's error carries the endpoint's message).
- `status` is export-only for every type: a Strategy, Future State and Guiding Principle move through
  propose / review / approve, and a Pain Point and an Open Question through decide-tier transitions that need a
  comment, so a file never moves a record through its lifecycle (a created record starts as the endpoints
  start it: `draft`, `submitted`, `open`). All five are marked approval-gated for that reason.
- `Tags` is export-only: tags are governed by the tag vocabulary and tag authority, which a column cannot
  carry. Pain Point scores are not columns here; the scoring grid reads them from the scoring service.
- A Pain Point or Open Question owner is assigned by a manager (the create form has no owner field), so an
  import that names one on a new row needs the manager role and says so otherwise.
- The project tier lists only a project's own records. Organisation-owned Strategies, Future States and Guiding
  Principles have no project: their `OrganizationRecordTable` lists and writes them for the organisation pages,
  through the same column definitions and the organisation endpoints' own create / edit functions.

Dependencies: `modules.context_strategy.edits` (queries and write paths), `models`, `labels`, `_shared` (role
checks), `services.record_tables_core` (cell helpers), `services.tags`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy import edits
from app.modules.context_strategy._shared import (
    MODULE_KEY,
    can_manage_pain_points,
    user_satisfies_future_state_owner_role,
    user_satisfies_guiding_principle_owner_role,
    user_satisfies_owner_role,
)
from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.labels import (
    LIFECYCLE_STATUS_LABEL,
    LIFECYCLE_STATUS_TONE,
    OPEN_QUESTION_STATUS_LABEL,
    OPEN_QUESTION_STATUS_TONE,
    PAIN_POINT_STATUS_LABEL,
    PAIN_POINT_STATUS_TONE,
)
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    OpenQuestion,
    PainPoint,
    PainPointTypeDefinition,
    ProjectPainPointType,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.pain_point_scores import (
    RollupMethod,
    build_pain_point_scoring,
    load_scoring_context,
    resolve_model,
)
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    OPEN_QUESTION_ARTEFACT_TYPE,
    PAIN_POINT_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
    resolve_effective_pain_point_types,
)
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.schemas.principal import PrincipalRef
from app.services import tags as tag_service
from app.services.client_date import effective_today
from app.services.principals import principal_ref
from app.services.rbac import user_satisfies_module_role
from app.services.record_tables import PrincipalCells
from app.services.record_tables_core import (
    bool_cell,
    bool_parser,
    cached_lookup,
    date_parser,
    enum_filter,
    enum_parser,
    label_map,
    list_cell,
    person_parser,
    text_parser,
)

IMPORT_NOTE = "Edited by record import."


def _all_may_create(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """Any project member may create these records: the gate the create endpoints apply (module on, member)."""
    return True


def _org_id(db: Session, project_id: uuid.UUID) -> uuid.UUID:
    return db.get(Project, project_id).organization_id


def _include_archived(filters: RecordFilters) -> bool:
    return bool(filters.flag("include_archived"))


def _tones(labels: Mapping[str, str], tones: Mapping[str, str]) -> dict[str, str]:
    """`{label: tone}` for a status, the shape `RecordColumn.tones` takes."""
    return {labels[value]: tone for value, tone in tones.items() if value in labels}


def _cell_date(value: Any) -> str:
    return value.isoformat() if value else ""


#: The filters every list shares with its page: `status`, `priority` (stored values) and `search` (the code or the
#: record's main text contains it), plus `include_archived`.
COMMON_FILTERS = frozenset({"include_archived", "status", "priority", "search"})

#: Statuses the pages' "Open only" / "Roadmap only" toggles keep (mirrors `PAIN_POINT_OPEN_STATUSES` and
#: `FUTURE_STATE_ROADMAP_STATUSES` in `frontend/src/modules/context_strategy/types.ts`).
PAIN_POINT_OPEN = frozenset({PainPointStatus.SUBMITTED, PainPointStatus.TRIAGED, PainPointStatus.ACCEPTED})
FUTURE_STATE_ROADMAP = frozenset({
    FutureStateStatus.DRAFT, FutureStateStatus.PROPOSED, FutureStateStatus.UNDER_REVIEW, FutureStateStatus.APPROVED,
    FutureStateStatus.ACTIVE,
})
OPEN_QUESTION_OPEN = frozenset({OpenQuestionStatus.OPEN, OpenQuestionStatus.INVESTIGATING, OpenQuestionStatus.READY_FOR_DECISION})


def _search_hit(filters: RecordFilters, code: str, text: str) -> bool:
    """Whether the page's search box (`search`) matches: the code or the main text contains it, ignoring case."""
    needle = filters.one("search")
    return needle is None or needle.casefold() in f"{code} {text}".casefold()


def _current_versions(db: Session, model: Any, fk: str, records: list[Any]) -> dict[uuid.UUID, Any]:
    """The current version of each record, keyed by the record's id."""
    if not records:
        return {}
    column = getattr(model, fk)
    return {getattr(v, fk): v for v in db.scalars(select(model).where(column.in_([r.id for r in records]), model.valid_to.is_(None)))}


class _Prepared:
    """Lookups handed to every column's `get`: the current versions (of a versioned type), the owners' cells,
    the type names (Pain Points) and the tags of the rows being written."""

    def __init__(
        self, db: Session, records: list[Any], artefact_type: str, *, version_model: Any = None, version_fk: str = "",
        owners_on_version: bool = False,
    ) -> None:
        ids = [r.id for r in records]
        self.versions: dict[uuid.UUID, Any] = {}
        if version_model is not None and ids:
            fk = getattr(version_model, version_fk)
            self.versions = {
                getattr(v, version_fk): v for v in db.scalars(select(version_model).where(fk.in_(ids), version_model.valid_to.is_(None)))
            }
        owner_rows = list(self.versions.values()) if owners_on_version else records
        self.people = PrincipalCells.load(
            db, [principal_ref(r.owner_type, r.owner_id) for r in owner_rows if hasattr(r, "owner_type")]
        )
        self.tags = tag_service.tag_names_for_records(db, artefact_type, ids) if ids else {}
        self.type_names: dict[uuid.UUID, str] = {}


def _tags_column() -> RecordColumn:
    return RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list")


def _text(key: str, label: str, attr: str, *, required: bool = False, versioned: bool = True) -> RecordColumn:
    """An editable text column read from the current version (or the record itself)."""
    if versioned:
        return RecordColumn(key, label, lambda t, r: getattr(t.versions[r.id], attr) or "", text_parser, editable=True, required=required)
    return RecordColumn(key, label, lambda t, r: getattr(r, attr) or "", text_parser, editable=True, required=required)


def _enum(key: str, label: str, attr: str, enum_class: Any, labels: Mapping[str, str], default: Any, *, versioned: bool = True) -> RecordColumn:
    """An editable enum column written by its label (a blank cell means the default)."""
    def get(t: _Prepared, r: Any) -> str:
        source = t.versions[r.id] if versioned else r
        return labels[getattr(source, attr).value]

    return RecordColumn(
        key, label, get, enum_parser(enum_class, label, blank=default), kind="enum", editable=True, choices=tuple(labels.values()),
    )


def _updates(values: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """The changed cells among `keys`, named as the service functions name them."""
    return {key: values[key] for key in keys if key in values}


# --- Strategy ----------------------------------------------------------------------------------------------------

_PRIORITY_LABELS = label_map(StrategyPriority)
_HORIZON_LABELS = label_map(StrategyTimeHorizon)
_STRATEGY_TEXT = ("title", "objective", "current_state", "desired_future_state", "rationale", "expected_outcomes",
                  "constraints", "measures_of_success")


def _filter_strategies(db: Session, records: list[Strategy], filters: RecordFilters) -> list[Strategy]:
    status, priority = enum_filter(filters, "status", StrategyStatus), enum_filter(filters, "priority", StrategyPriority)
    versions = _current_versions(db, StrategyVersion, "strategy_id", records)
    return [
        r for r in records
        if (status is None or versions[r.id].status == status) and (priority is None or versions[r.id].priority == priority)
        and _search_hit(filters, r.unique_code, versions[r.id].title)
    ]


def _list_strategies(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Strategy]:
    return _filter_strategies(db, edits.project_strategies(db, project_id, _include_archived(filters)), filters)


def _list_org_strategies(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[Strategy]:
    return _filter_strategies(db, edits.organization_strategies(db, organization.id, _include_archived(filters)), filters)


def _strategy_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("title", "Title", "title", required=True),
        _text("objective", "Objective", "objective", required=True),
        _text("current_state", "Current state", "current_state"),
        _text("desired_future_state", "Desired future state", "desired_future_state"),
        _text("rationale", "Rationale", "rationale"),
        _text("expected_outcomes", "Expected outcomes", "expected_outcomes"),
        _text("constraints", "Constraints", "constraints"),
        _text("measures_of_success", "Measures of success", "measures_of_success"),
        _enum("priority", "Priority", "priority", StrategyPriority, _PRIORITY_LABELS, StrategyPriority.MEDIUM),
        _enum("time_horizon", "Time horizon", "time_horizon", StrategyTimeHorizon, _HORIZON_LABELS, StrategyTimeHorizon.MEDIUM_TERM),
        _tags_column(),
        RecordColumn(
            "status", "Status", lambda t, r: LIFECYCLE_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones=_tones(LIFECYCLE_STATUS_LABEL, LIFECYCLE_STATUS_TONE),
        ),
    ]


def _create_strategy(ctx: RecordImportContext, values: Mapping[str, Any]) -> Strategy:
    return edits.create_project_strategy_record(
        ctx.db, ctx.project, ctx.user, title=values["title"], objective=values["objective"],
        **_updates(values, _STRATEGY_TEXT[2:]),
        **{k: v for k, v in _updates(values, ("priority", "time_horizon")).items() if v is not None},
    )


def _update_strategy(ctx: RecordImportContext, strategy: Strategy, values: Mapping[str, Any]) -> None:
    edits.edit_project_strategy_record(
        ctx.db, ctx.project, strategy, ctx.user, change_note=IMPORT_NOTE,
        **_updates(values, _STRATEGY_TEXT + ("priority", "time_horizon")),
    )


def _find_strategy(db: Session, project: Project, code: str) -> Strategy | None:
    return db.scalar(select(Strategy).where(
        Strategy.project_id == project.id, Strategy.scope == StrategyScope.PROJECT, Strategy.unique_code == code.upper(),
    ))


def _may_update_strategy(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return user_satisfies_owner_role(db, user, StrategyScope.PROJECT, organization_id=_org_id(db, project_id), project_id=project_id)


def _create_org_strategy(ctx: RecordImportContext, values: Mapping[str, Any]) -> Strategy:
    return edits.create_strategy_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), ctx.user, title=values["title"], objective=values["objective"],
        **_updates(values, _STRATEGY_TEXT[2:]),
        **{k: v for k, v in _updates(values, ("priority", "time_horizon")).items() if v is not None},
    )


def _update_org_strategy(ctx: RecordImportContext, strategy: Strategy, values: Mapping[str, Any]) -> None:
    edits.edit_strategy_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), strategy, ctx.user, change_note=IMPORT_NOTE,
        **_updates(values, _STRATEGY_TEXT + ("priority", "time_horizon")),
    )


def _find_org_scoped(model: Any, scope: Any) -> Any:
    """A finder of the organisation's own records of `model` (its `scope` column equal to `scope`) by code."""

    def find(db: Session, organization: Organization, code: str) -> Any | None:
        return db.scalar(select(model).where(
            model.organization_id == organization.id, model.scope == scope, model.unique_code == code.upper(),
        ))

    return find


def _org_owner_check(check: Any, scope: Any) -> Any:
    """`(db, user, organization_id) -> bool` for the owner-role check of an organisation-scoped type."""

    def allowed(db: Session, user: User, organization_id: uuid.UUID) -> bool:
        return check(db, user, scope, organization_id=organization_id, project_id=None)

    return allowed


def _all_org_members_may_create(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    """Any organisation member may create these records: the gate the organisation create endpoints apply."""
    return True


STRATEGY_TABLE = RecordTableProvider(
    label="Strategies",
    columns=_strategy_columns,
    list_records=_list_strategies,
    find=_find_strategy,
    prepare=lambda db, project, records: _Prepared(db, records, STRATEGY_ARTEFACT_TYPE, version_model=StrategyVersion, version_fk="strategy_id"),
    create=_create_strategy,
    update=_update_strategy,
    filter_params=COMMON_FILTERS,
    gate=(MODULE_KEY, "strategy"),
    can_create=_all_may_create,
    can_update=_may_update_strategy,
    approval_gated=True,
    organization=OrganizationRecordTable(
        subcomponent="strategy",
        columns=lambda db, organization: _strategy_columns(db, None),
        list_records=_list_org_strategies,
        find=_find_org_scoped(Strategy, StrategyScope.ORGANIZATION),
        prepare=lambda db, organization, records: _Prepared(
            db, records, STRATEGY_ARTEFACT_TYPE, version_model=StrategyVersion, version_fk="strategy_id",
        ),
        create=_create_org_strategy,
        update=_update_org_strategy,
        filter_params=COMMON_FILTERS,
        can_create=_all_org_members_may_create,
        can_update=_org_owner_check(user_satisfies_owner_role, StrategyScope.ORGANIZATION),
    ),
)


# --- Future State ------------------------------------------------------------------------------------------------

_FUTURE_STATE_TEXT = ("title", "current_state", "desired_state", "outcomes", "success_measures", "constraints", "assumptions")


def _filter_future_states(db: Session, records: list[FutureState], filters: RecordFilters) -> list[FutureState]:
    status = enum_filter(filters, "status", FutureStateStatus)
    roadmap_only, passed_only, no_measures = filters.flag("roadmap_only"), filters.flag("target_passed_only"), filters.flag("no_measures_only")
    today = effective_today()
    versions = _current_versions(db, FutureStateVersion, "future_state_id", records)

    def keep(record: FutureState) -> bool:
        v = versions[record.id]
        return (
            (status is None or v.status == status)
            and (not roadmap_only or v.status in FUTURE_STATE_ROADMAP)
            and (not passed_only or (v.target_date is not None and v.target_date < today and v.status != FutureStateStatus.ACTIVE))
            and (not no_measures or not v.success_measures.strip())
            and _search_hit(filters, record.unique_code, v.title)
        )

    return [r for r in records if keep(r)]


def _list_future_states(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[FutureState]:
    return _filter_future_states(db, edits.project_future_states(db, project_id, _include_archived(filters)), filters)


def _list_org_future_states(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[FutureState]:
    return _filter_future_states(db, edits.organization_future_states(db, organization.id, _include_archived(filters)), filters)


def _future_state_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("title", "Title", "title", required=True),
        _text("current_state", "Current state", "current_state"),
        _text("desired_state", "Desired state", "desired_state"),
        RecordColumn(
            "target_date", "Target date", lambda t, r: _cell_date(t.versions[r.id].target_date), date_parser("Target date"),
            kind="date", editable=True,
        ),
        _text("outcomes", "Outcomes", "outcomes"),
        _text("success_measures", "Success measures", "success_measures"),
        _text("constraints", "Constraints", "constraints"),
        _text("assumptions", "Assumptions", "assumptions"),
        _tags_column(),
        RecordColumn(
            "status", "Status", lambda t, r: LIFECYCLE_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones=_tones(LIFECYCLE_STATUS_LABEL, LIFECYCLE_STATUS_TONE),
        ),
    ]


def _create_future_state(ctx: RecordImportContext, values: Mapping[str, Any]) -> FutureState:
    return edits.create_project_future_state_record(
        ctx.db, ctx.project, ctx.user, title=values["title"], **_updates(values, _FUTURE_STATE_TEXT[1:] + ("target_date",)),
    )


def _update_future_state(ctx: RecordImportContext, future_state: FutureState, values: Mapping[str, Any]) -> None:
    edits.edit_project_future_state_record(
        ctx.db, ctx.project, future_state, ctx.user, change_note=IMPORT_NOTE,
        target_date_explicitly_set="target_date" in values, **_updates(values, _FUTURE_STATE_TEXT + ("target_date",)),
    )


def _find_future_state(db: Session, project: Project, code: str) -> FutureState | None:
    return db.scalar(select(FutureState).where(
        FutureState.project_id == project.id, FutureState.scope == FutureStateScope.PROJECT,
        FutureState.unique_code == code.upper(),
    ))


def _may_update_future_state(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return user_satisfies_future_state_owner_role(
        db, user, FutureStateScope.PROJECT, organization_id=_org_id(db, project_id), project_id=project_id,
    )


def _create_org_future_state(ctx: RecordImportContext, values: Mapping[str, Any]) -> FutureState:
    return edits.create_future_state_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), ctx.user, title=values["title"],
        **_updates(values, _FUTURE_STATE_TEXT[1:] + ("target_date",)),
    )


def _update_org_future_state(ctx: RecordImportContext, future_state: FutureState, values: Mapping[str, Any]) -> None:
    edits.edit_future_state_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), future_state, ctx.user, change_note=IMPORT_NOTE,
        target_date_explicitly_set="target_date" in values, **_updates(values, _FUTURE_STATE_TEXT + ("target_date",)),
    )


FUTURE_STATE_TABLE = RecordTableProvider(
    label="Future states",
    columns=_future_state_columns,
    list_records=_list_future_states,
    find=_find_future_state,
    prepare=lambda db, project, records: _Prepared(
        db, records, FUTURE_STATE_ARTEFACT_TYPE, version_model=FutureStateVersion, version_fk="future_state_id",
    ),
    create=_create_future_state,
    update=_update_future_state,
    filter_params=frozenset({"include_archived", "status", "search", "roadmap_only", "target_passed_only", "no_measures_only"}),
    gate=(MODULE_KEY, "future_state"),
    can_create=_all_may_create,
    can_update=_may_update_future_state,
    approval_gated=True,
    organization=OrganizationRecordTable(
        subcomponent="future_state",
        columns=lambda db, organization: _future_state_columns(db, None),
        list_records=_list_org_future_states,
        find=_find_org_scoped(FutureState, FutureStateScope.ORGANIZATION),
        prepare=lambda db, organization, records: _Prepared(
            db, records, FUTURE_STATE_ARTEFACT_TYPE, version_model=FutureStateVersion, version_fk="future_state_id",
        ),
        create=_create_org_future_state,
        update=_update_org_future_state,
        filter_params=frozenset({"include_archived", "status", "search", "roadmap_only", "target_passed_only", "no_measures_only"}),
        can_create=_all_org_members_may_create,
        can_update=_org_owner_check(user_satisfies_future_state_owner_role, FutureStateScope.ORGANIZATION),
    ),
)


# --- Guiding Principle -------------------------------------------------------------------------------------------

_GP_PRIORITY_LABELS = label_map(GuidingPrinciplePriority)


def _filter_guiding_principles(db: Session, records: list[GuidingPrinciple], filters: RecordFilters) -> list[GuidingPrinciple]:
    status = enum_filter(filters, "status", GuidingPrincipleStatus)
    priority = enum_filter(filters, "priority", GuidingPrinciplePriority)
    versions = _current_versions(db, GuidingPrincipleVersion, "guiding_principle_id", records)
    return [
        r for r in records
        if (status is None or versions[r.id].status == status) and (priority is None or versions[r.id].priority == priority)
        and _search_hit(filters, r.unique_code, versions[r.id].name)
    ]


def _list_guiding_principles(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[GuidingPrinciple]:
    return _filter_guiding_principles(db, edits.project_guiding_principles(db, project_id, _include_archived(filters)), filters)


def _list_org_guiding_principles(
    db: Session, user: User, organization: Organization, filters: RecordFilters
) -> list[GuidingPrinciple]:
    return _filter_guiding_principles(db, edits.organization_guiding_principles(db, organization.id, _include_archived(filters)), filters)


def _guiding_principle_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("name", "Name", "name", required=True),
        _text("principle_statement", "Principle statement", "principle_statement", required=True),
        _text("rationale", "Rationale", "rationale"),
        _enum("priority", "Priority", "priority", GuidingPrinciplePriority, _GP_PRIORITY_LABELS, GuidingPrinciplePriority.MEDIUM),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(t.versions[r.id].owner_type, t.versions[r.id].owner_id),
            person_parser("owner"), kind="principal",
        ),
        _tags_column(),
        RecordColumn(
            "status", "Status", lambda t, r: LIFECYCLE_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones=_tones(LIFECYCLE_STATUS_LABEL, LIFECYCLE_STATUS_TONE),
        ),
    ]


def _create_guiding_principle(ctx: RecordImportContext, values: Mapping[str, Any]) -> GuidingPrinciple:
    return edits.create_project_guiding_principle_record(
        ctx.db, ctx.project, ctx.user, name=values["name"], principle_statement=values["principle_statement"],
        rationale=values.get("rationale", ""), priority=values.get("priority") or GuidingPrinciplePriority.MEDIUM,
        owner=values.get("owner"),
    )


def _update_guiding_principle(ctx: RecordImportContext, guiding_principle: GuidingPrinciple, values: Mapping[str, Any]) -> None:
    edits.edit_project_guiding_principle_record(
        ctx.db, ctx.project, guiding_principle, ctx.user, change_note=IMPORT_NOTE, owner_explicitly_set="owner" in values,
        **_updates(values, ("name", "principle_statement", "rationale", "priority", "owner")),
    )


def _find_guiding_principle(db: Session, project: Project, code: str) -> GuidingPrinciple | None:
    return db.scalar(select(GuidingPrinciple).where(
        GuidingPrinciple.project_id == project.id, GuidingPrinciple.scope == GuidingPrincipleScope.PROJECT,
        GuidingPrinciple.unique_code == code.upper(),
    ))


def _may_update_guiding_principle(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return user_satisfies_guiding_principle_owner_role(
        db, user, GuidingPrincipleScope.PROJECT, organization_id=_org_id(db, project_id), project_id=project_id,
    )


def _create_org_guiding_principle(ctx: RecordImportContext, values: Mapping[str, Any]) -> GuidingPrinciple:
    return edits.create_guiding_principle_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), ctx.user, name=values["name"],
        principle_statement=values["principle_statement"], rationale=values.get("rationale", ""),
        priority=values.get("priority") or GuidingPrinciplePriority.MEDIUM, owner=values.get("owner"),
    )


def _update_org_guiding_principle(ctx: RecordImportContext, guiding_principle: GuidingPrinciple, values: Mapping[str, Any]) -> None:
    edits.edit_guiding_principle_record(
        ctx.db, edits.RecordOwner(ctx.organization.id), guiding_principle, ctx.user, change_note=IMPORT_NOTE,
        owner_explicitly_set="owner" in values,
        **_updates(values, ("name", "principle_statement", "rationale", "priority", "owner")),
    )


GUIDING_PRINCIPLE_TABLE = RecordTableProvider(
    label="Guiding principles",
    columns=_guiding_principle_columns,
    list_records=_list_guiding_principles,
    find=_find_guiding_principle,
    prepare=lambda db, project, records: _Prepared(
        db, records, GUIDING_PRINCIPLE_ARTEFACT_TYPE, version_model=GuidingPrincipleVersion,
        version_fk="guiding_principle_id", owners_on_version=True,
    ),
    create=_create_guiding_principle,
    update=_update_guiding_principle,
    filter_params=COMMON_FILTERS,
    gate=(MODULE_KEY, "guiding_principle"),
    can_create=_all_may_create,
    can_update=_may_update_guiding_principle,
    approval_gated=True,
    organization=OrganizationRecordTable(
        subcomponent="guiding_principle",
        columns=lambda db, organization: _guiding_principle_columns(db, None),
        list_records=_list_org_guiding_principles,
        find=_find_org_scoped(GuidingPrinciple, GuidingPrincipleScope.ORGANIZATION),
        prepare=lambda db, organization, records: _Prepared(
            db, records, GUIDING_PRINCIPLE_ARTEFACT_TYPE, version_model=GuidingPrincipleVersion,
            version_fk="guiding_principle_id", owners_on_version=True,
        ),
        create=_create_org_guiding_principle,
        update=_update_org_guiding_principle,
        filter_params=COMMON_FILTERS,
        can_create=_all_org_members_may_create,
        can_update=_org_owner_check(user_satisfies_guiding_principle_owner_role, GuidingPrincipleScope.ORGANIZATION),
    ),
)


# --- Pain Point --------------------------------------------------------------------------------------------------

_PAIN_POINT_PRIORITY_LABELS = label_map(PainPointPriority)
_PAIN_POINT_TEXT = ("title", "description", "source", "impact", "evidence")


def _pain_point_type_names(db: Session, type_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The effective name of each project Pain Point type row (its own name, else its organisation type's)."""
    rows = list(db.scalars(select(ProjectPainPointType).where(ProjectPainPointType.id.in_(type_ids)))) if type_ids else []
    org_ids = {r.org_type_id for r in rows if r.name_override is None and r.org_type_id}
    org_names = {
        o.id: o.name for o in db.scalars(select(PainPointTypeDefinition).where(PainPointTypeDefinition.id.in_(org_ids)))
    } if org_ids else {}
    return {r.id: r.name_override if r.name_override is not None else org_names.get(r.org_type_id, "") for r in rows}


def _prepare_pain_points(db: Session, project: Project, records: list[PainPoint]) -> _Prepared:
    prepared = _Prepared(db, records, PAIN_POINT_ARTEFACT_TYPE)
    prepared.type_names = _pain_point_type_names(db, {r.pain_point_type_id for r in records})
    return prepared


def _list_pain_points(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[PainPoint]:
    records = edits.project_pain_points(db, project_id, _include_archived(filters))
    status, priority = enum_filter(filters, "status", PainPointStatus), enum_filter(filters, "priority", PainPointPriority)
    open_only, hide_intentional, only_intentional = filters.flag("open_only"), filters.flag("hide_intentional"), filters.flag("only_intentional")
    records = [
        r for r in records
        if (status is None or r.status == status) and (priority is None or r.priority == priority)
        and (not open_only or r.status in PAIN_POINT_OPEN) and not (hide_intentional and r.is_intentional)
        and not (only_intentional and not r.is_intentional) and _search_hit(filters, r.unique_code, r.title)
    ]
    blockers_only, scored = filters.flag("blockers_only"), filters.one("scored")
    if scored not in (None, "yes", "no"):
        raise HTTPException(422, "scored must be yes or no.")
    if not (blockers_only or scored) or not records:
        return records
    try:
        method = RollupMethod(filters.one("rollup") or RollupMethod.WEIGHTED_AVERAGE.value)
    except ValueError:
        raise HTTPException(422, "rollup is not a known roll-up method.") from None
    project = db.get(Project, project_id)
    scoring = load_scoring_context(db, project)
    summaries = {s.pain_point_id: s for s in build_pain_point_scoring(db, scoring, records, resolve_model(scoring, filters.one("model_key")), method)}
    return [
        r for r in records
        if (not blockers_only or summaries[r.id].is_blocker)
        and (scored is None or (summaries[r.id].score is not None) == (scored == "yes"))
    ]


def _pain_point_type_ref(ctx: RecordImportContext, name: str) -> uuid.UUID:
    """The effective-type id for a type name of this project (hidden types are not offered)."""
    types = cached_lookup(ctx, "pp:types", lambda: {
        t.name.casefold(): t.id for t in reversed(resolve_effective_pain_point_types(ctx.db, ctx.project.id, ctx.project.organization_id))
    })
    found = types.get(name.casefold())
    if found is None:
        raise RecordCellError(f"Unknown Pain Point type '{name}'.")
    return found


def _pain_point_columns(db: Session, project: Project) -> list[RecordColumn]:
    effective = resolve_effective_pain_point_types(db, project.id, project.organization_id)
    return [
        _text("title", "Title", "title", required=True, versioned=False),
        RecordColumn(
            "type", "Type", lambda t, r: t.type_names.get(r.pain_point_type_id, ""), text_parser, kind="enum", editable=True,
            required=True, choices=tuple(e.name for e in effective if e.is_enabled),
        ),
        _text("description", "Description", "description", versioned=False),
        _text("source", "Source", "source", versioned=False),
        _text("impact", "Impact", "impact", versioned=False),
        _text("evidence", "Evidence", "evidence", versioned=False),
        _enum("priority", "Priority", "priority", PainPointPriority, _PAIN_POINT_PRIORITY_LABELS, PainPointPriority.MEDIUM, versioned=False),
        RecordColumn("owner", "Owner", lambda t, r: t.people.text(r.owner_type, r.owner_id), person_parser("owner"), kind="principal"),
        RecordColumn(
            "date_identified", "Date identified", lambda t, r: _cell_date(r.date_identified), date_parser("Date identified"),
            kind="date",
        ),
        RecordColumn(
            "is_intentional", "Intentional", lambda t, r: bool_cell(r.is_intentional), bool_parser("Intentional"), kind="bool",
            editable=True,
        ),
        _tags_column(),
        RecordColumn(
            "status", "Status", lambda t, r: PAIN_POINT_STATUS_LABEL[r.status.value], kind="enum",
            tones=_tones(PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE),
        ),
    ]


def _pain_point_fields(values: Mapping[str, Any]) -> dict[str, Any]:
    """The `update_pain_point` keyword arguments for the changed cells (not the type or owner)."""
    fields = _updates(values, _PAIN_POINT_TEXT + ("priority", "date_identified", "is_intentional"))
    return {k: v for k, v in fields.items() if v is not None}


def _may_manage_pain_points(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return can_manage_pain_points(db, user, organization_id=_org_id(db, project_id), project_id=project_id)


def _create_pain_point(ctx: RecordImportContext, values: Mapping[str, Any]) -> PainPoint:
    owner: PrincipalRef | None = values.get("owner")
    if owner is not None and not _may_manage_pain_points(ctx.db, ctx.user, ctx.project.id):
        raise RecordCellError("Only a Pain Point Manager may assign an owner.")
    pain_point_type = edits.resolve_usable_pain_point_type(ctx.db, ctx.project, _pain_point_type_ref(ctx, values["type"]))
    pain_point = edits.create_project_pain_point_record(
        ctx.db, ctx.project, ctx.user, pain_point_type, **_pain_point_fields(values),
    )
    if owner is not None:
        edits.edit_project_pain_point_record(ctx.db, ctx.project, pain_point, ctx.user, owner=owner, owner_explicitly_set=True)
    return pain_point


def _update_pain_point(ctx: RecordImportContext, pain_point: PainPoint, values: Mapping[str, Any]) -> None:
    edits.edit_project_pain_point_record(
        ctx.db, ctx.project, pain_point, ctx.user,
        type_ref_id=_pain_point_type_ref(ctx, values["type"]) if "type" in values else None,
        owner=values.get("owner"), owner_explicitly_set="owner" in values, **_pain_point_fields(values),
    )


def _find_pain_point(db: Session, project: Project, code: str) -> PainPoint | None:
    return db.scalar(select(PainPoint).where(PainPoint.project_id == project.id, PainPoint.unique_code == code.upper()))


PAIN_POINT_TABLE = RecordTableProvider(
    label="Pain points",
    columns=_pain_point_columns,
    list_records=_list_pain_points,
    find=_find_pain_point,
    prepare=_prepare_pain_points,
    create=_create_pain_point,
    update=_update_pain_point,
    filter_params=COMMON_FILTERS | {"open_only", "hide_intentional", "only_intentional", "blockers_only", "scored", "model_key", "rollup"},
    gate=(MODULE_KEY, "pain_point"),
    can_create=_all_may_create,
    can_update=_may_manage_pain_points,
    approval_gated=True,
)


# --- Open Question -----------------------------------------------------------------------------------------------

_OQ_PRIORITY_LABELS = label_map(OpenQuestionPriority)
_OQ_TEXT = ("question", "context", "evidence")


def _list_open_questions(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[OpenQuestion]:
    records = edits.project_open_questions(db, project_id, _include_archived(filters))
    status, priority = enum_filter(filters, "status", OpenQuestionStatus), enum_filter(filters, "priority", OpenQuestionPriority)
    open_only, overdue_only, unowned_only = filters.flag("open_only"), filters.flag("overdue_only"), filters.flag("unowned_only")
    today = effective_today()
    return [
        r for r in records
        if (status is None or r.status == status) and (priority is None or r.priority == priority)
        and (not open_only or r.status in OPEN_QUESTION_OPEN) and (not overdue_only or (r.due_date is not None and r.due_date < today))
        and (not unowned_only or r.owner_id is None) and _search_hit(filters, r.unique_code, r.question)
    ]


def _open_question_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("question", "Question", "question", required=True, versioned=False),
        _text("context", "Context", "context", versioned=False),
        _text("evidence", "Evidence", "evidence", versioned=False),
        _enum("priority", "Priority", "priority", OpenQuestionPriority, _OQ_PRIORITY_LABELS, OpenQuestionPriority.MEDIUM, versioned=False),
        RecordColumn("owner", "Owner", lambda t, r: t.people.text(r.owner_type, r.owner_id), person_parser("owner"), kind="principal"),
        RecordColumn(
            "due_date", "Due date", lambda t, r: _cell_date(r.due_date), date_parser("Due date"), kind="date", editable=True,
        ),
        _tags_column(),
        RecordColumn(
            "status", "Status", lambda t, r: OPEN_QUESTION_STATUS_LABEL[r.status.value], kind="enum",
            tones=_tones(OPEN_QUESTION_STATUS_LABEL, OPEN_QUESTION_STATUS_TONE),
        ),
    ]


def _may_manage_open_questions(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return user_satisfies_module_role(
        db, user, MODULE_KEY, "open_question_owner", organization_id=_org_id(db, project_id), project_id=project_id,
    )


def _create_open_question(ctx: RecordImportContext, values: Mapping[str, Any]) -> OpenQuestion:
    owner: PrincipalRef | None = values.get("owner")
    if owner is not None and not _may_manage_open_questions(ctx.db, ctx.user, ctx.project.id):
        raise RecordCellError("Only an Open Question Owner may assign an owner.")
    open_question = edits.create_project_open_question_record(
        ctx.db, ctx.project, ctx.user, question=values["question"], context=values.get("context", ""),
        evidence=values.get("evidence", ""), priority=values.get("priority") or OpenQuestionPriority.MEDIUM,
        due_date=values.get("due_date"),
    )
    if owner is not None:
        edits.edit_project_open_question_record(ctx.db, ctx.project, open_question, ctx.user, owner=owner, owner_explicitly_set=True)
    return open_question


def _update_open_question(ctx: RecordImportContext, open_question: OpenQuestion, values: Mapping[str, Any]) -> None:
    fields = {k: v for k, v in _updates(values, _OQ_TEXT + ("priority",)).items() if v is not None}
    edits.edit_project_open_question_record(
        ctx.db, ctx.project, open_question, ctx.user, owner=values.get("owner"), owner_explicitly_set="owner" in values,
        due_date=values.get("due_date"), due_date_explicitly_set="due_date" in values, **fields,
    )


def _find_open_question(db: Session, project: Project, code: str) -> OpenQuestion | None:
    return db.scalar(select(OpenQuestion).where(OpenQuestion.project_id == project.id, OpenQuestion.unique_code == code.upper()))


OPEN_QUESTION_TABLE = RecordTableProvider(
    label="Open questions",
    columns=_open_question_columns,
    list_records=_list_open_questions,
    find=_find_open_question,
    prepare=lambda db, project, records: _Prepared(db, records, OPEN_QUESTION_ARTEFACT_TYPE),
    create=_create_open_question,
    update=_update_open_question,
    filter_params=COMMON_FILTERS | {"open_only", "overdue_only", "unowned_only"},
    gate=(MODULE_KEY, "open_question"),
    can_create=_all_may_create,
    can_update=_may_manage_open_questions,
    approval_gated=True,
)


RECORD_TABLES: dict[str, RecordTableProvider] = {
    STRATEGY_ARTEFACT_TYPE: STRATEGY_TABLE,
    FUTURE_STATE_ARTEFACT_TYPE: FUTURE_STATE_TABLE,
    PAIN_POINT_ARTEFACT_TYPE: PAIN_POINT_TABLE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE: GUIDING_PRINCIPLE_TABLE,
    OPEN_QUESTION_ARTEFACT_TYPE: OPEN_QUESTION_TABLE,
}
