"""
Module: modules.product_feedback.record_tables

The `RecordTableProvider` of Product Feedback's one record type, the enhancement request: the list as a table, so
it exports to CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code creates).
The organisation's inbox is the provider's `OrganizationRecordTable`.

Responsibilities:
- Declare the columns (title, description, owner, external references, the scoring levels, tags) and the
  status, decline reason, demand, channel mix and derived score as export-only cells.
- Share the create and edit logic with the endpoints (`_shared.stage_request` / `stage_request_update`), so the
  owner validation, the version history and the audit event are the ones the screen applies.

Design decisions:
- `status` and `decline_reason` are export-only: a request moves through its lifecycle only by the transition
  endpoint, whose rules (a reason to decline, no direct move to duplicate) a file must not bypass. A created
  request starts `New`, as the create endpoint starts it.
- A scoring level is written by its name on its axis (`Many`, `Large`) for the organisation's own scheme; the
  score is derived (under the owner's default model) and so is export-only. A blank level cell clears the level.
- `references` is one list cell, `System:key` (the system's name; `System:https://...` for a link with no key;
  ` (origin)` after a reference that came from there), the way the export writes it. An import *adds* the
  references a cell names that the request lacks and never removes or edits one (the role and link of an existing
  reference are not in the cell), so a round trip changes nothing and removing a reference stays a deliberate act
  on the request. `channels` (how the requesters asked, as a count per channel) is export-only.
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
from app.modules.product_feedback import references as refs
from app.modules.product_feedback.channels import channels_by_request
from app.modules.product_feedback.demand import EMPTY_DEMAND
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, ExternalRefRole
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.ratings import derived_levels, load_rating_context, parse_model_keys, score_levels
from app.modules.product_feedback.schemas import ExternalRefIn, RequestCreate, RequestUpdate, check_web_url
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME, REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.scoring_filter import ScoredFilter
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
    PainPointFilter,
    RecordOwner,
    filter_requests,
    list_organization_requests,
    list_project_requests,
    version_levels,
)
from app.modules.product_feedback.vocabularies import EXTERNAL_SYSTEMS
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
from app.services.record_tables_core import (
    LIST_SEPARATOR,
    cached_lookup,
    count_rows,
    enum_filter,
    list_cell,
    list_parser,
    person_parser,
    text_parser,
)
from app.services.scoring import list_levels
from app.services.scoring_custom import effective_scheme

IMPORT_NOTE = "Edited by record import."

#: The list's own filters, by the names its export takes.
REQUEST_FILTERS = frozenset({"include_archived", "status", "open_only", "search", "scored", "missing_axis", "scoring_model", "pain_points"})


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
        extras = sh.request_extras(db, records)
        demand = extras.demand
        self.references = extras.references
        self.channel_mix: dict[uuid.UUID, str] = _channel_mix(db, records, demand)
        ctx = load_rating_context(db, organization_id, project_id)
        self.levels: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
        self.scores = {}
        self.requesters: dict[uuid.UUID, int] = {}
        self.weighted_demand: dict[uuid.UUID, float] = {}
        for rid, version in self.versions.items():
            weighted = demand.get(rid, EMPTY_DEMAND).weighted
            self.requesters[rid] = demand.get(rid, EMPTY_DEMAND).count
            self.weighted_demand[rid] = weighted
            self.levels[rid] = {**derived_levels(ctx, stored[version.id], weighted), **stored[version.id]}
            self.scores[rid] = score_levels(ctx, stored[version.id], weighted)[ctx.model.key]


def _channel_mix(db: Session, records: list[Any], demand: dict[uuid.UUID, Any]) -> dict[uuid.UUID, str]:
    """`{request id: "Call x2; Email"}`: how many of each request's requesters asked through each channel (a
    requester reached through an Engagement counts as an Engagement; one with no channel recorded is left out).
    Names no one, so it carries no personal data."""
    project_owned = [r.id for r in records if r.project_id is not None]
    channels = channels_by_request(db, project_owned)
    mix: dict[uuid.UUID, str] = {}
    for request_id in project_owned:
        counts: dict[str, int] = {}
        for requester in demand.get(request_id, EMPTY_DEMAND).requesters:
            choice = channels[request_id].get((requester.artefact_type, requester.id))
            name = choice.name if choice else ("Engagement" if requester.via_engagement else "")
            if name:
                counts[name] = counts.get(name, 0) + 1
        mix[request_id] = LIST_SEPARATOR.join(
            name if n == 1 else f"{name} x{n}" for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
    return mix


def _filtered(
    db: Session, holder: RecordOwner, requests: list[EnhancementRequest], filters: RecordFilters,
) -> list[EnhancementRequest]:
    """The requests the list's filters keep (the same rules the list endpoints apply)."""
    scored = filters.one("scored")
    if scored not in (None, "scored", "unscored"):
        raise HTTPException(422, "scored is not a valid value.")
    pain_points = filters.one("pain_points")
    if pain_points not in (None, "none", "some"):
        raise HTTPException(422, "pain_points is not a valid value.")
    return filter_requests(
        db, holder, requests, status=enum_filter(filters, "status", EnhancementRequestStatus),
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
        scored=cast(ScoredFilter | None, scored),
        missing_axis=filters.one("missing_axis"), scoring_model=parse_model_keys(filters.many("scoring_model")),
        pain_points=cast(PainPointFilter | None, pain_points),
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


def _reference_text(ref: Any) -> str:
    """One reference as a cell entry: `System:key` (`System:link` when it has no key), `(origin)` marked."""
    text = f"{ref.system_name}:{ref.key or ref.url or ''}"
    return f"{text} (origin)" if ref.role == ExternalRefRole.ORIGIN else text


def _references_parser(ctx: RecordImportContext, text: str) -> list[tuple[str, str, str | None, ExternalRefRole]]:
    """The `;`-separated entries of a references cell as `(system name, key, link, role)`, each checked as the API
    checks a reference (a system name is matched when the import is applied, against the request's own list)."""
    entries = []
    for part in list_parser(ctx, text):
        role = ExternalRefRole.DELIVERY
        if part.lower().endswith("(origin)"):
            part, role = part[: -len("(origin)")].strip(), ExternalRefRole.ORIGIN
        system, sep, rest = part.partition(":")
        rest = rest.strip()
        if not sep or not system.strip() or not rest:
            raise RecordCellError(f"'{part}' is not a reference: write System:key, e.g. Jira:PROJ-123.")
        is_link = rest.lower().startswith(("http://", "https://"))
        try:
            link = check_web_url(rest) if is_link else None
        except ValueError as exc:
            raise RecordCellError(str(exc)) from None
        if len(rest) > (500 if is_link else 100):
            raise RecordCellError(f"A reference's {'link' if is_link else 'key'} is too long.")
        entries.append((system.strip(), "" if is_link else rest, link, role))
    return entries


def _system_ids(ctx: RecordImportContext) -> dict[str, uuid.UUID]:
    """`{system name (lower case): id}` the import's tier can pick from (the project's effective list, or the
    organisation's active entries for the inbox)."""
    def load() -> dict[str, uuid.UUID]:
        if ctx.project is not None:
            return {
                e.name.casefold(): e.id
                for e in EXTERNAL_SYSTEMS.resolve_effective(ctx.db, ctx.project.id, ctx.organization.id) if e.is_enabled
            }
        return {t.name.casefold(): t.id for t in EXTERNAL_SYSTEMS.active_org_types(ctx.db, ctx.organization.id)}

    return cached_lookup(ctx, "feedback:systems", lambda: load())


def _reference_inputs(ctx: RecordImportContext, entries: list[tuple[str, str, str | None, ExternalRefRole]]) -> list[ExternalRefIn]:
    """The entries as API payloads, naming each system in the request's tier; an unknown system is a row error."""
    systems = _system_ids(ctx)
    out = []
    for name, key, link, role in entries:
        system_id = systems.get(name.casefold())
        if system_id is None:
            raise RecordCellError(f"'{name}' is not an external system here; pick one from the list.")
        out.append(ExternalRefIn(system_id=system_id, key=key, url=link, role=role))
    return out


def _text(key: str, label: str, *, required: bool = False, parser: Any = text_parser) -> RecordColumn:
    return RecordColumn(
        key, label, lambda t, r: getattr(t.versions[r.id], key) or "", parser, editable=True, required=required,
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
        RecordColumn(
            "references", "External references", lambda t, r: list_cell([_reference_text(x) for x in t.references.get(r.id, [])]),
            _references_parser, kind="list",
        ),
        *(level_column(a.key, a.label, a.derived_source is not None) for a in scheme.axes),
        RecordColumn("requesters", "Requesters", lambda t, r: str(t.requesters.get(r.id, 0)), kind="number"),
        RecordColumn(
            "weighted_demand", "Weighted demand", lambda t, r: f"{t.weighted_demand.get(r.id, 0.0):g}", kind="number",
        ),
        RecordColumn("channels", "Request channels", lambda t, r: t.channel_mix.get(r.id, ""), kind="list"),
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
        for key in ("title", "description", "owner") if key in values
    }
    levels = {a.key: values[a.key] for a in scheme.axes if a.derived_source is None and a.key in values}
    return fields | ({"levels": levels} if levels else {})


def _holder(ctx: RecordImportContext) -> RecordOwner:
    """The tier the import writes into: the project, or (without one) the organisation's inbox."""
    return RecordOwner.of_project(ctx.project) if ctx.project is not None else RecordOwner(ctx.organization.id)


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> EnhancementRequest:
    references = _reference_inputs(ctx, values["references"]) if values.get("references") else []
    return sh.stage_request(ctx.db, _holder(ctx), RequestCreate(**_fields(ctx, values), references=references), ctx.user)


def _update(ctx: RecordImportContext, request: EnhancementRequest, values: Mapping[str, Any]) -> None:
    fields = _fields(ctx, values)
    if fields:
        sh.stage_request_update(ctx.db, _holder(ctx), request, RequestUpdate(**fields, change_note=IMPORT_NOTE), ctx.user)
    if values.get("references"):
        _add_missing_references(ctx, request, _reference_inputs(ctx, values["references"]))


def _add_missing_references(ctx: RecordImportContext, request: EnhancementRequest, wanted: list[ExternalRefIn]) -> None:
    """Adds the references of `wanted` the request does not hold (same system and key or link), keeping the rest."""
    held = {
        (r.system_name.casefold(), r.key or r.url or "") for r in refs.references_by_request(ctx.db, [request.id])[request.id]
    }
    systems = {v: k for k, v in _system_ids(ctx).items()}
    for item in wanted:
        marker = (systems.get(item.system_id, ""), item.key or item.url or "")
        if marker in held:
            continue
        try:
            refs.add_reference(
                ctx.db, request, system_id=item.system_id, key=item.key, url=item.url, role=item.role, actor=ctx.user,
            )
        except ValueError as exc:
            raise RecordCellError(str(exc)) from None
        held.add(marker)


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
