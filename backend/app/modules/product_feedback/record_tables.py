"""
Module: modules.product_feedback.record_tables

The `RecordTableProvider` of Product Feedback's one record type, the enhancement request: the list as a table, so
it exports to CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code creates).
The organisation's inbox is the provider's `OrganizationRecordTable`.

Responsibilities:
- Declare the columns (title, description, owner, external reference, the four scoring levels, tags) and the
  status, decline reason and derived score as export-only cells.
- Share the create and edit logic with the endpoints (`_shared.stage_request` / `stage_request_update`), so the
  owner validation, the version history and the audit event are the ones the screen applies.

Design decisions:
- `status` and `decline_reason` are export-only: a request moves through its lifecycle only by the transition
  endpoint, whose rules (a reason to decline, no direct move to duplicate) a file must not bypass. A created
  request starts `New`, as the create endpoint starts it.
- A scoring level is written by its name on its axis (`Many`, `Large`) for the organisation's own scheme; the
  score is derived (under the owner's default model) and so is export-only. A blank level cell clears the level.
- Updating needs the triager role (the edit endpoint's gate); creating follows the endpoint's gate (any member,
  unless the project restricted submission to triagers).

Dependencies: `_shared` (stage functions, gates), `service`, `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.demand import EMPTY_DEMAND
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.ratings import derived_levels, load_rating_context, parse_model_keys, score_levels
from app.modules.product_feedback.schemas import RequestCreate, RequestUpdate
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME, REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.scoring_filter import ScoredFilter
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
    RecordOwner,
    filter_requests,
    list_organization_requests,
    list_project_requests,
    version_levels,
)
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.services import tags as tag_service
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells, find_many_by_code
from app.services.record_tables_core import cached_lookup, count_rows, enum_filter, list_cell, person_parser, text_parser
from app.services.scoring import list_levels
from app.services.scoring_custom import effective_scheme

IMPORT_NOTE = "Edited by record import."

#: The list's own filters, by the names its export takes.
REQUEST_FILTERS = frozenset({"include_archived", "status", "open_only", "search", "scored", "missing_axis", "scoring_model"})


def _owner_ids(owner: Project | Organization) -> tuple[uuid.UUID, uuid.UUID | None]:
    """`(organization id, project id)` of the table's owner (the project id is `None` for the inbox)."""
    return (owner.organization_id, owner.id) if isinstance(owner, Project) else (owner.id, None)


class _Prepared:
    """Lookups handed to every column's `get`: current versions, owner cells, tags, level names, each request's
    levels (the derived ones included) and its score under the default model."""

    def __init__(self, db: Session, owner: Project | Organization, records: list[Any]) -> None:
        ids = [r.id for r in records]
        self.versions: dict[uuid.UUID, EnhancementRequestVersion] = {
            v.request_id: v
            for v in db.scalars(select(EnhancementRequestVersion).where(
                EnhancementRequestVersion.request_id.in_(ids), EnhancementRequestVersion.valid_to.is_(None),
            ))
        } if ids else {}
        self.people = PrincipalCells.load(db, [principal_ref(v.owner_type, v.owner_id) for v in self.versions.values()])
        self.tags = tag_service.tag_names_for_records(db, REQUEST_ARTEFACT_TYPE, ids) if ids else {}
        organization_id, project_id = _owner_ids(owner)
        self.level_names = {
            level.id: level.name
            for levels in list_levels(db, organization_id, REQUEST_SCORING_SCHEME_KEY).values() for level in levels
        }
        stored = version_levels(db, [v.id for v in self.versions.values()])
        demand = sh.request_extras(db, records).demand
        ctx = load_rating_context(db, organization_id, project_id)
        self.levels: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
        self.scores = {}
        for rid, version in self.versions.items():
            weighted = demand.get(rid, EMPTY_DEMAND).weighted
            self.levels[rid] = {**derived_levels(ctx, stored[version.id], weighted), **stored[version.id]}
            self.scores[rid] = score_levels(ctx, stored[version.id], weighted)[ctx.model.key]


def _filtered(
    db: Session, holder: RecordOwner, requests: list[EnhancementRequest], filters: RecordFilters,
) -> list[EnhancementRequest]:
    """The requests the list's filters keep (the same rules the list endpoints apply)."""
    scored = filters.one("scored")
    if scored not in (None, "scored", "unscored"):
        raise HTTPException(422, "scored is not a valid value.")
    return filter_requests(
        db, holder, requests, status=enum_filter(filters, "status", EnhancementRequestStatus),
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
        scored=cast(ScoredFilter | None, scored),
        missing_axis=filters.one("missing_axis"), scoring_model=parse_model_keys(filters.many("scoring_model")),
    )


def _list_project(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[EnhancementRequest]:
    project = db.get(Project, project_id)
    assert project is not None  # the engine has resolved the project
    return _filtered(
        db, RecordOwner.of_project(project),
        list_project_requests(db, project_id, include_archived=bool(filters.flag("include_archived"))), filters,
    )


def _list_organization(
    db: Session, user: User, organization: Organization, filters: RecordFilters
) -> list[EnhancementRequest]:
    return _filtered(
        db, RecordOwner(organization.id),
        list_organization_requests(db, organization.id, include_archived=bool(filters.flag("include_archived"))),
        filters,
    )


def _text(key: str, label: str, *, required: bool = False) -> RecordColumn:
    return RecordColumn(
        key, label, lambda t, r: getattr(t.versions[r.id], key) or "", text_parser, editable=True, required=required,
    )


def _level_parser(axis: str) -> Any:
    """A parser for a scoring level cell: the level's name on `axis` in the organisation's scheme."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            return None
        levels = cached_lookup(ctx, "feedback:levels", lambda: {
            key: {level.name.casefold(): level.id for level in rows}
            for key, rows in list_levels(ctx.db, ctx.organization.id, REQUEST_SCORING_SCHEME_KEY).items()
        })
        found = levels.get(axis, {}).get(text.casefold())
        if found is None:
            raise RecordCellError(f"'{text}' is not a {axis} level of this organisation's request scheme.")
        return found

    return parse


def _score_text(table: _Prepared, request: Any) -> str:
    score = table.scores.get(request.id)
    return "" if score is None else f"{score.raw:g}"


def _columns(db: Session, owner: Project | Organization) -> list[RecordColumn]:
    organization_id, project_id = _owner_ids(owner)
    scheme = effective_scheme(db, organization_id, REQUEST_SCORING_SCHEME, project_id)
    levels = list_levels(db, organization_id, REQUEST_SCORING_SCHEME_KEY)

    def level_column(axis_key: str, label: str, derived: bool) -> RecordColumn:
        # A derived axis (Demand) shows the level the request's demand falls in and is read-only here: it is
        # changed, to override the derived level, through the request's own `levels`.
        return RecordColumn(
            axis_key, label, lambda t, r: t.level_names.get(t.levels[r.id].get(axis_key), ""), _level_parser(axis_key),
            kind="enum", editable=not derived, choices=tuple(level.name for level in levels.get(axis_key, [])),
        )

    return [
        _text("title", "Title", required=True),
        _text("description", "Description"),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(t.versions[r.id].owner_type, t.versions[r.id].owner_id),
            person_parser("owner"), kind="principal",
        ),
        _text("external_ref_url", "External reference URL"),
        _text("external_ref_key", "External reference key"),
        *(level_column(a.key, a.label, a.derived_source is not None) for a in scheme.axes),
        RecordColumn("score", "Score", _score_text, kind="number"),
        RecordColumn("score_band", "Score band", lambda t, r: (t.scores[r.id].label or "") if t.scores.get(r.id) else ""),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
        RecordColumn(
            "status", "Status", lambda t, r: REQUEST_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones={REQUEST_STATUS_LABEL[value]: tone for value, tone in REQUEST_STATUS_TONE.items()},
        ),
        RecordColumn("decline_reason", "Decline reason", lambda t, r: t.versions[r.id].decline_reason or ""),
    ]


def _fields(ctx: RecordImportContext, values: Mapping[str, Any]) -> dict[str, Any]:
    """The `RequestCreate` / `RequestUpdate` keyword arguments for the cells in `values`; a level cell is any
    manual axis of the scheme as it applies to the import's project (or the organisation)."""
    scheme = effective_scheme(
        ctx.db, ctx.organization.id, REQUEST_SCORING_SCHEME, ctx.project.id if ctx.project is not None else None,
    )
    fields = {
        key: values[key]
        for key in ("title", "description", "owner", "external_ref_url", "external_ref_key") if key in values
    }
    levels = {a.key: values[a.key] for a in scheme.axes if a.derived_source is None and a.key in values}
    return fields | ({"levels": levels} if levels else {})


def _holder(ctx: RecordImportContext) -> RecordOwner:
    """The tier the import writes into: the project, or (without one) the organisation's inbox."""
    return RecordOwner.of_project(ctx.project) if ctx.project is not None else RecordOwner(ctx.organization.id)


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> EnhancementRequest:
    return sh.stage_request(ctx.db, _holder(ctx), RequestCreate(**_fields(ctx, values)), ctx.user)


def _update(ctx: RecordImportContext, request: EnhancementRequest, values: Mapping[str, Any]) -> None:
    sh.stage_request_update(
        ctx.db, _holder(ctx), request, RequestUpdate(**_fields(ctx, values), change_note=IMPORT_NOTE), ctx.user,
    )


def _may_manage_project(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The edit endpoint's gate: the Feedback Triager role or the `(enhancement_request, manage)` grant."""
    project = db.get(Project, project_id)
    return project is not None and sh.can_manage(db, user, RecordOwner.of_project(project))


def _may_create_project(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The create endpoint's gate: any member, unless the project restricted submission to triagers."""
    project = db.get(Project, project_id)
    if project is None:
        return False
    try:
        sh.require_request_submit(db, user, RecordOwner.of_project(project))
    except HTTPException:
        return False
    return True


def _may_manage_organization(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    return sh.can_manage(db, user, RecordOwner(organization_id))


def _may_create_organization(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    """Any organisation member may submit to the inbox (the organisation create endpoint's gate)."""
    return True


def _find_project(db: Session, project: Project, code: str) -> EnhancementRequest | None:
    return db.scalar(select(EnhancementRequest).where(
        EnhancementRequest.project_id == project.id, EnhancementRequest.unique_code == code.upper(),
    ))


def _find_organization(db: Session, organization: Organization, code: str) -> EnhancementRequest | None:
    return db.scalar(select(EnhancementRequest).where(
        EnhancementRequest.organization_id == organization.id,
        EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
        EnhancementRequest.unique_code == code.upper(),
    ))


REQUEST_TABLE = RecordTableProvider(
    label="Enhancement requests",
    columns=_columns,
    list_records=_list_project,
    find=_find_project,
    find_many=find_many_by_code(EnhancementRequest, "project_id", EnhancementRequest.scope == EnhancementRequestScope.PROJECT),
    prepare=lambda db, project, records: _Prepared(db, project, records),
    create=_create,
    update=_update,
    filter_params=REQUEST_FILTERS,
    gate=(PRODUCT_FEEDBACK_MODULE_KEY, REQUEST_SUBCOMPONENT_KEY),
    can_create=_may_create_project,
    can_update=_may_manage_project,
    organization=OrganizationRecordTable(
        subcomponent=ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
        columns=lambda db, organization: _columns(db, organization),
        list_records=_list_organization,
        find=_find_organization,
        find_many=find_many_by_code(
            EnhancementRequest, "organization_id", EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
        ),
        prepare=lambda db, organization, records: _Prepared(db, organization, records),
        create=_create,
        update=_update,
        filter_params=REQUEST_FILTERS,
        can_create=_may_create_organization,
        can_update=_may_manage_organization,
    ),
    count=lambda db, user, project_id: count_rows(db, EnhancementRequest, project_id, live_only=True),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {REQUEST_ARTEFACT_TYPE: REQUEST_TABLE}
