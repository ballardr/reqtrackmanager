"""
Module: modules.product_feedback.reports

Report data layer for Product Feedback: five reports, one `collect_*` function each, returning the core
framework's `ReportResult`, plus the `REPORT_DEFINITIONS` that declare them to the registry. Result shapes, scope
(`readable_projects`), PDF/CSV/Word rendering, routes, MCP tools and the catalogue live in
`app.services.report_framework`, so this module is declarations and queries.

Reports: F1 Demand ranking, F2 Unlinked requests, F3 Close the loop, F4 Triage ageing, F5 Problem demand.

Design decisions (all Decided by: Agent unless stated):
- Every report reads the module's own definitions, never a copy: demand is `demand.compute_demand`, the Pain Point
  and Requirement counts are `relationships.compute_links` (a merged duplicate's links count for its canonical
  request) and the open loop is `loop.open_loop_requests`' rule (`_open_loops` is the same test over many projects),
  so a report and the request page never disagree.
- The reports exist for the work that is still open: F1, F2 and F4 list unarchived requests in the statuses they are
  about, a merged duplicate (status `Duplicate`) never appears (its demand and links are its canonical request's)
  and an archived request never appears.
- F1 ranks by weighted demand (the default) or by the chosen model's normalised score (`rank_by`), and says which
  model it scored under. The score is derived exactly as the list derives it (`ratings.score_levels`). A project run
  scores each project under its own scheme, so a model the project hides or does not define leaves its requests
  *unscored*, listed after the scored ones and never as zero. An organisation-wide run scores every request under the
  organisation's scheme, since a model a single project defined says nothing across projects.
- The inbox (the organisation's own requests) has no project, so a project run never lists it. An organisation-wide run
  lists it only when asked (`include_inbox`, F1 and F4): the organisation breakdown route calls a collector once per
  project and must not repeat the inbox in each. An inbox request cannot be linked, so it has no demand and no Pain
  Point; it is shown as "Inbox" rather than flagged as unlinked, and F2, F3 and F5 are about linked work and leave it out.
- F3 names no one: a requester's name is a Stakeholder's personal data, which the request page shows only to a viewer
  who can see the record and a record file carries only under the personal-data policy. The report gives the counts
  and the channel mix and points to the request, whose close-the-loop panel names them for a viewer allowed to see them.
- F4 measures the time since the request *entered its current status* (the start of its unbroken run in New or Under
  review), not since its last edit, which would let any edit reset the clock.
- F5 counts Pain Points of the project itself; a Pain Point of a related project is not listed (its record is not the
  project's to name), and a Pain Point in a project where the person running the report cannot view Pain Points
  (`ReportContext.can_view`, which fails closed when the viewer is unknown) is counted in a note, never named. A Pain
  Point "has a Requirement" when a Requirement is linked to it directly, or realises a request that addresses it.
- Ages are elapsed time between two instants (UTC), so no calendar day or time zone is involved.
- Reports never include Restricted data and are not audit-logged (framework rule).

Dependencies: `app.services.report_framework`, `app.modules.registry`, and this module's demand, links, loop, ratings
and channel helpers.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.modules.product_feedback.channels import channels_by_request
from app.modules.product_feedback.demand import EMPTY_DEMAND, Demand, compute_demand
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE, request_status_label
from app.modules.product_feedback.loop import CLOSED_STATUSES, informed_by_request
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.ratings import RatingContext, RequestScore, load_rating_context, score_levels
from app.modules.product_feedback.relationships import NO_LINKS, PAIN_POINT_TYPE, REQUIREMENT_TYPE, RequestLinks, compute_links
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_OPEN_STATUSES,
    REQUEST_SUBCOMPONENT_KEY,
    version_levels,
)
from app.modules.registry import (
    ReportDefinition,
    ReportParamDefinition,
    ReportPartDefinition,
    get_artefact_summaries_in_project,
    is_org_module_subcomponent_enabled,
)
from app.services.principals import principal_labels, principal_ref, principal_text
from app.services.report_framework import (
    ReportContext,
    ReportMetric,
    ReportResult,
    ReportSection,
    build_report_routers,
    tones_by_label,
)
from app.services.scoring import get_registered_scheme, resolve_effective_model
from app.services.scoring_custom import effective_scheme

MODULE_KEY = PRODUCT_FEEDBACK_MODULE_KEY

_S = EnhancementRequestStatus
#: Statuses F4 is about: a request nobody has decided on yet.
TRIAGE_STATUSES = frozenset({_S.NEW, _S.UNDER_REVIEW})
#: Statuses F2 lists besides the open ones when asked (`include_closed`); a merged duplicate is never listed.
CLOSED_LISTED_STATUSES = frozenset({_S.DELIVERED, _S.DECLINED})
INBOX = "Inbox"
NOT_SCORED = "Not scored"
_CLIP = 300
#: How many request codes F5 names in a Pain Point's row before "+n".
_NAMES_SHOWN = 5


# --- Shared helpers ---------------------------------------------------------------


def _fmt_date(value: datetime | None) -> str:
    """A past instant as its UTC date (`""` when unset)."""
    return value.astimezone(UTC).date().isoformat() if value else ""


def _utc(value: datetime) -> datetime:
    """`value` as an aware UTC instant (a stored time is always UTC)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _clip(text: str | None, limit: int = _CLIP) -> str:
    """Collapses whitespace and cuts `text` to `limit` characters with an ellipsis."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _weighted(value: float) -> str:
    """Weighted demand as text, without a trailing `.0`."""
    return f"{value:g}"


@dataclass
class RequestRow:
    """One request of a report, with everything the collectors need.

    Attributes:
        request / version: The identity row and its current version.
        project: The owning project, `None` for an inbox request.
        demand: Its requesters (`EMPTY_DEMAND` for an inbox request).
        links: Its Pain Points and Requirements (`NO_LINKS` for an inbox request).
        owner: The owner as text ("" when none).
        tags: The tags as comma-separated text ("" when none).
    """

    request: EnhancementRequest
    version: EnhancementRequestVersion
    project: Project | None
    demand: Demand = EMPTY_DEMAND
    links: RequestLinks = NO_LINKS
    owner: str = ""
    tags: str = ""

    @property
    def is_inbox(self) -> bool:
        return self.project is None

    @property
    def project_name(self) -> str:
        return self.project.name if self.project is not None else INBOX


def _code(ctx: ReportContext, row: RequestRow) -> str:
    """The request's code as the report shows it (qualified for an inbox request, which the organisation owns)."""
    if row.project is None:
        return ctx.org_code(row.request.unique_code)
    return ctx.code(row.request.unique_code, row.project.id)


def _inbox_wanted(db: Session, ctx: ReportContext, include_inbox: bool) -> bool:
    """Whether the run lists the organisation's inbox: asked for, an organisation-wide run, and the inbox switched on."""
    return bool(
        include_inbox and ctx.root_project is None
        and is_org_module_subcomponent_enabled(db, ctx.organization.id, MODULE_KEY, ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY)
    )


def _load_rows(
    db: Session, ctx: ReportContext, statuses: frozenset[EnhancementRequestStatus], *, include_inbox: bool = False,
    with_links: bool = True,
) -> tuple[list[Project], list[RequestRow], bool]:
    """The in-scope projects with the list on, and their unarchived requests in `statuses` as `RequestRow`s.

    Args:
        db: Database session.
        ctx: The report context.
        statuses: The statuses to keep.
        include_inbox: Also read the organisation's inbox (an organisation-wide run with the inbox on only).
        with_links: Whether to read each request's Pain Points and Requirements (one set of statements per project).

    Returns:
        `(eligible projects, rows ordered by project name then code, whether the inbox was read)`.
    """
    projects = ctx.eligible(db, REQUEST_SUBCOMPONENT_KEY)
    by_id = {p.id: p for p in projects}
    inbox = _inbox_wanted(db, ctx, include_inbox)
    if not by_id and not inbox:
        return [], [], False
    owned = EnhancementRequest.project_id.in_(by_id) if by_id else None
    in_inbox = (
        (EnhancementRequest.organization_id == ctx.organization.id)
        & (EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION)
    ) if inbox else None
    where = or_(*(c for c in (owned, in_inbox) if c is not None))
    pairs = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(
            where, EnhancementRequest.is_archived.is_(False), EnhancementRequestVersion.valid_to.is_(None),
            EnhancementRequestVersion.status.in_(statuses),
        )
    ).all()
    rows = [RequestRow(request, version, by_id.get(request.project_id) if request.project_id else None) for request, version in pairs]
    owners = principal_labels(db, [principal_ref(r.version.owner_type, r.version.owner_id) for r in rows])
    tags = ctx.tag_text(db, REQUEST_ARTEFACT_TYPE, [r.request.id for r in rows])
    per_project: dict[uuid.UUID, list[RequestRow]] = defaultdict(list)
    for row in rows:
        owner_type, owner_id = row.version.owner_type, row.version.owner_id
        row.owner = principal_text(owners.get((owner_type, owner_id))) if owner_type and owner_id else ""
        row.tags = tags.get(row.request.id, "")
        if row.project is not None:
            per_project[row.project.id].append(row)
    for project_id, project_rows in per_project.items():
        project = by_id[project_id]
        ids = [r.request.id for r in project_rows]
        demand = compute_demand(db, project, ids)
        links = compute_links(db, project, ids) if with_links else {}
        for row in project_rows:
            row.demand = demand[row.request.id]
            row.links = links.get(row.request.id, NO_LINKS)
    rows.sort(key=lambda r: (r.project_name.lower(), r.request.unique_code))
    return projects, rows, inbox


def _result(ctx: ReportContext, key: str, title: str, *, eligible: int, notes: list[str] | None = None) -> ReportResult:
    """Starts a `ReportResult` with the scope note and any report-specific notes."""
    return ReportResult(
        key=key, title=title, scope_label=ctx.scope_label, generated_at=datetime.now(UTC),
        notes=[ctx.scope_note, *(notes or [])], sections=[], eligible_projects=eligible,
    )


def _items(ctx: ReportContext, rows: Sequence[RequestRow]) -> dict[str, list[dict[str, object]]]:
    """The structured `data` of a report that lists requests: `{id, project_id, code, title}` per row."""
    return {"items": [
        {"id": r.request.id, "project_id": r.project.id if r.project else None, "code": _code(ctx, r), "title": r.version.title}
        for r in rows
    ]}


def _status_text(row: RequestRow) -> str:
    return request_status_label(row.version.status.value)


def _problem_text(row: RequestRow) -> str:
    """Whether the request rests on a problem: the count of Pain Points it addresses, or why it cannot."""
    if row.is_inbox:
        return INBOX
    n = len(row.links.pain_point_ids)
    return f"{n} linked" if n else "No Pain Point"


def _problem_tone(row: RequestRow) -> str | None:
    return "warning" if not row.is_inbox and not row.links.pain_point_ids else None


# --- F1: Demand ranking -----------------------------------------------------------


def _score_rows(
    db: Session, ctx: ReportContext, rows: Sequence[RequestRow], model_key: str | None,
) -> tuple[dict[uuid.UUID, RequestScore | None], str, int]:
    """Scores each row under one model.

    A project run scores a project's requests under that project's scheme (so its own criteria count), the
    organisation-wide run scores everything under the organisation's.

    Args:
        db: Database session.
        ctx: The report context.
        rows: The requests to score.
        model_key: The model asked for, else the default of the project reported on (or the organisation).

    Returns:
        `(score by request id, the model's label, how many requests have no scheme with that model)`.

    Raises:
        HTTPException: 400 when `model_key` is not a model of the reference scheme.
    """
    registered = get_registered_scheme(REQUEST_SCORING_SCHEME_KEY).scheme
    organization_id = ctx.organization.id
    reference_id = ctx.root_project.id if ctx.root_project is not None else None
    reference = effective_scheme(db, organization_id, registered, reference_id)
    if model_key is not None and reference.model(model_key) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring model '{model_key}'.")
    key = model_key or resolve_effective_model(db, organization_id, reference, reference_id)[0]
    model = reference.model(key)
    label = model.label if model is not None else key
    contexts: dict[uuid.UUID | None, RatingContext | None] = {}

    def context_of(tier_id: uuid.UUID | None) -> RatingContext | None:
        if tier_id not in contexts:
            scheme = effective_scheme(db, organization_id, registered, tier_id)
            contexts[tier_id] = load_rating_context(db, organization_id, tier_id, [key]) if scheme.model(key) is not None else None
        return contexts[tier_id]

    levels = version_levels(db, [r.version.id for r in rows])
    scores: dict[uuid.UUID, RequestScore | None] = {}
    without_model = 0
    for row in rows:
        context = context_of(row.project.id if ctx.root_project is not None and row.project is not None else None)
        if context is None:
            without_model += 1
            scores[row.request.id] = None
            continue
        scores[row.request.id] = score_levels(context, levels[row.version.id], row.demand.weighted)[key]
    return scores, label, without_model


def collect_demand_ranking(db: Session, ctx: ReportContext) -> ReportResult:
    """F1 — open requests ranked by weighted demand or by score, with the requests resting on no problem flagged.

    Args:
        db: Database session.
        ctx: The request (`scoring_model`, `rank_by` and `include_inbox` shape it).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}], "scoring_model": key-or-label}` in rank order.

    Raises:
        HTTPException: 400 for a scoring model the scheme does not define.
    """
    rank_by = ctx.params.get("rank_by") or "demand"
    model_param = (ctx.params.get("scoring_model") or "").strip() or None
    projects, rows, inbox = _load_rows(db, ctx, REQUEST_OPEN_STATUSES, include_inbox=bool(ctx.params.get("include_inbox")))
    scores, model_label, without_model = _score_rows(db, ctx, rows, model_param) if rows else ({}, "", 0)

    def normalised(row: RequestRow) -> float:
        score = scores.get(row.request.id)
        return score.normalised if score is not None else -1.0

    if rank_by == "score":
        rows.sort(key=lambda r: (-normalised(r), -r.demand.weighted, r.project_name.lower(), r.request.unique_code))
    else:
        rows.sort(key=lambda r: (-r.demand.weighted, -normalised(r), r.project_name.lower(), r.request.unique_code))
    ranked_by = "score, then weighted demand" if rank_by == "score" else "weighted demand, then score"
    notes = [
        f"Open requests (New, Under review, Accepted), ranked by {ranked_by}. "
        f"Scored under {model_label or 'the default model'}"
        f"{' for the organisation' if ctx.root_project is None else ''}; scores of different models are not comparable.",
        "A request with no level on one of the model's criteria is Not scored, and is listed after the scored ones.",
    ]
    if without_model:
        notes.append(f"{without_model} request(s) are in a project whose scoring does not offer this model, so they are Not scored.")
    if inbox:
        notes.append("The organisation's inbox is included: inbox requests have no requesters, so their demand is 0.")
    elif ctx.params.get("include_inbox"):
        notes.append("The inbox is listed only in an organisation-wide run with the organisation inbox switched on.")
    result = _result(ctx, "f1", "Demand ranking", eligible=len(projects) + int(inbox), notes=notes)
    columns = ["Rank", "Code", "Request", "Project", "Status", "Requesters", "Weighted demand", "Score", "Rating", "Problem", "Owner", "Tags"]
    table: list[list[str]] = []
    tones: list[list[str | None]] = []
    for rank, row in enumerate(rows, start=1):
        score = scores.get(row.request.id)
        table.append([
            str(rank), _code(ctx, row), row.version.title, row.project_name, _status_text(row), str(row.demand.count),
            _weighted(row.demand.weighted), f"{score.normalised:.0%}" if score else NOT_SCORED,
            (score.label or "") if score else "", _problem_text(row), row.owner, row.tags,
        ])
        tones.append([
            None, None, None, None, None, None, None, None, score.tone if score else None, _problem_tone(row), None, None,
        ])
    result.sections = [ReportSection("ranking", "Open requests", columns, table, tones=tones)]
    result.metrics = [
        ReportMetric("Open requests", len(rows)),
        ReportMetric("Total weighted demand", _weighted(sum(r.demand.weighted for r in rows))),
        ReportMetric("Not scored", sum(scores.get(r.request.id) is None for r in rows), gap=True),
        ReportMetric("No Pain Point linked", sum(not r.is_inbox and not r.links.pain_point_ids for r in rows), gap=True),
    ]
    result.data = {**_items(ctx, rows), "scoring_model": model_label, "rank_by": rank_by}
    return result


# --- F2: Unlinked requests --------------------------------------------------------


def collect_unlinked(db: Session, ctx: ReportContext) -> ReportResult:
    """F2 — requests that address no Pain Point: a solution with no problem behind it, loudest first.

    Args:
        db: Database session.
        ctx: The request (`include_closed` also lists delivered and declined requests).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}]}`.
    """
    include_closed = bool(ctx.params.get("include_closed"))
    statuses = REQUEST_OPEN_STATUSES | (CLOSED_LISTED_STATUSES if include_closed else frozenset())
    projects, rows, _ = _load_rows(db, ctx, frozenset(statuses))
    unlinked = sorted(
        (r for r in rows if not r.links.pain_point_ids),
        key=lambda r: (-r.demand.weighted, r.project_name.lower(), r.request.unique_code),
    )
    now = datetime.now(UTC)
    result = _result(ctx, "f2", "Unlinked requests", eligible=len(projects), notes=[
        "A request is a proposed solution; a Pain Point is the problem it solves. These requests address no Pain Point, "
        "so nothing shows what they are for. They are not blocked: link a Pain Point, or decide the request.",
        f"Covers {'open, delivered and declined' if include_closed else 'open (New, Under review, Accepted)'} requests "
        "in projects. The organisation inbox is left out: an inbox request cannot be linked until it is moved to a project.",
    ])
    columns = ["Code", "Request", "Project", "Status", "Requesters", "Weighted demand", "Requirements", "Age (days)", "Owner", "Tags"]
    table = [
        [
            _code(ctx, r), r.version.title, r.project_name, _status_text(r), str(r.demand.count), _weighted(r.demand.weighted),
            str(len(r.links.requirement_ids)), str((now - _utc(r.request.created_at)).days), r.owner, r.tags,
        ]
        for r in unlinked
    ]
    result.sections = [ReportSection("unlinked", "Requests with no Pain Point", columns, table, gap=True)]
    result.metrics = [
        ReportMetric("Requests", len(rows)),
        ReportMetric("No Pain Point linked", len(unlinked), gap=True),
        ReportMetric("Of which realised by a Requirement", sum(bool(r.links.requirement_ids) for r in unlinked), gap=True),
        ReportMetric("Demand with no problem", _weighted(sum(r.demand.weighted for r in unlinked))),
    ]
    result.data = _items(ctx, unlinked)
    return result


# --- F3: Close the loop -----------------------------------------------------------


def _open_loops(db: Session, ctx: ReportContext) -> list[tuple[RequestRow, int, int, str]]:
    """Delivered or declined requests with a requester not yet told: `(row, to tell, told, channel mix)`.

    The test is `loop.open_loop_requests`' (a requester is anyone `compute_demand` reports; informed rows are matched
    to the current requesters), applied to every in-scope project at once.
    """
    _, rows, _ = _load_rows(db, ctx, CLOSED_STATUSES, with_links=False)
    ids = [r.request.id for r in rows if r.demand.count]
    informed = informed_by_request(db, ids)
    channels = channels_by_request(db, ids)
    out: list[tuple[RequestRow, int, int, str]] = []
    for row in rows:
        told = informed.get(row.request.id, {})
        pending = sum(1 for q in row.demand.requesters if (q.artefact_type, q.id) not in told)
        if not pending:
            continue
        counts: dict[str, int] = defaultdict(int)
        for q in row.demand.requesters:
            if (q.artefact_type, q.id) in told:
                continue
            choice = channels[row.request.id].get((q.artefact_type, q.id))
            name = choice.name if choice else ("Engagement" if q.via_engagement else "")
            counts[name or "No channel recorded"] += 1
        mix = "; ".join(n if c == 1 else f"{n} x{c}" for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        out.append((row, pending, row.demand.count - pending, mix))
    return out


def collect_close_the_loop(db: Session, ctx: ReportContext) -> ReportResult:
    """F3 — delivered or declined requests whose requesters have not all been told.

    Args:
        db: Database session.
        ctx: The request.

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}]}`, oldest request first.
    """
    projects = ctx.eligible(db, REQUEST_SUBCOMPONENT_KEY)
    loops = _open_loops(db, ctx) if projects else []
    loops.sort(key=lambda entry: (entry[0].project_name.lower(), entry[0].request.unique_code))
    result = _result(ctx, "f3", "Close the loop", eligible=len(projects), notes=[
        "Delivered or declined requests with at least one requester not marked as told. Nothing is sent to anyone: "
        "a triager tells the person and ticks them off on the request page.",
        "Requesters are not named here (their names are personal data); open the request to see who to tell. "
        "The organisation inbox is left out: an inbox request has no requesters.",
    ])
    columns = ["Code", "Request", "Project", "Outcome", "To tell", "Told", "Still to tell, by channel", "Decline reason", "Owner", "Tags"]
    table = [
        [
            _code(ctx, row), row.version.title, row.project_name, _status_text(row), str(pending), str(told), mix,
            _clip(row.version.decline_reason) if row.version.status == _S.DECLINED else "", row.owner, row.tags,
        ]
        for row, pending, told, mix in loops
    ]
    result.sections = [ReportSection("open_loops", "Requests with requesters still to tell", columns, table, gap=True)]
    result.metrics = [
        ReportMetric("Requests with an open loop", len(loops), gap=True),
        ReportMetric("Requesters still to tell", sum(pending for _, pending, _, _ in loops), gap=True),
        ReportMetric("Delivered", sum(row.version.status == _S.DELIVERED for row, *_ in loops)),
        ReportMetric("Declined", sum(row.version.status == _S.DECLINED for row, *_ in loops)),
    ]
    result.data = _items(ctx, [row for row, *_ in loops])
    return result


# --- F4: Triage ageing ------------------------------------------------------------


def _status_runs(db: Session, rows: Sequence[RequestRow]) -> dict[uuid.UUID, datetime]:
    """When each request entered its current status: the start of its unbroken run of versions in that status.

    One statement over the requests' versions; an edit that leaves the status alone does not restart the clock.
    """
    if not rows:
        return {}
    wanted = {r.request.id: r.version.status for r in rows}
    since: dict[uuid.UUID, datetime] = {}
    settled: set[uuid.UUID] = set()
    for request_id, version_status, valid_from in db.execute(
        select(EnhancementRequestVersion.request_id, EnhancementRequestVersion.status, EnhancementRequestVersion.valid_from)
        .where(EnhancementRequestVersion.request_id.in_(list(wanted)))
        .order_by(EnhancementRequestVersion.request_id, EnhancementRequestVersion.version_number.desc())
    ):
        if request_id in settled:
            continue
        if version_status == wanted[request_id]:
            since[request_id] = _utc(valid_from)
        else:
            settled.add(request_id)
    return since


def collect_triage_ageing(db: Session, ctx: ReportContext) -> ReportResult:
    """F4 — requests waiting in New or Under review for longer than a number of days.

    Args:
        db: Database session.
        ctx: The request (`older_than_days`, `include_inbox`).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}], "older_than_days": n}`, oldest first.
    """
    raw_threshold = ctx.params.get("older_than_days")
    threshold = 14 if raw_threshold is None else int(raw_threshold)
    projects, rows, inbox = _load_rows(
        db, ctx, TRIAGE_STATUSES, include_inbox=bool(ctx.params.get("include_inbox")), with_links=False,
    )
    since = _status_runs(db, rows)
    now = datetime.now(UTC)
    days = {r.request.id: (now - since.get(r.request.id, _utc(r.version.valid_from))).days for r in rows}
    waiting = sorted(rows, key=lambda r: (-days[r.request.id], r.project_name.lower(), r.request.unique_code))
    late = [r for r in waiting if days[r.request.id] > threshold]
    notes = [
        f"Requests in New or Under review for more than {threshold} day(s). The clock starts when the request entered its "
        "current status; editing it does not restart it.",
    ]
    if inbox:
        notes.append("The organisation's inbox is included.")
    elif ctx.params.get("include_inbox"):
        notes.append("The inbox is listed only in an organisation-wide run with the organisation inbox switched on.")
    result = _result(ctx, "f4", "Triage ageing", eligible=len(projects) + int(inbox), notes=notes)
    columns = ["Code", "Request", "Project", "Status", "Waiting since", "Days waiting", "Requesters", "Weighted demand", "Owner", "Tags"]
    table = [
        [
            _code(ctx, r), r.version.title, r.project_name, _status_text(r), _fmt_date(since.get(r.request.id, r.version.valid_from)),
            str(days[r.request.id]), str(r.demand.count), _weighted(r.demand.weighted), r.owner, r.tags,
        ]
        for r in late
    ]
    by_status = [
        [
            label, str(sum(r.version.status.value == value for r in rows)),
            str(max((days[r.request.id] for r in rows if r.version.status.value == value), default=0)),
            str(sum(r.version.status.value == value for r in late)),
        ]
        for value, label in REQUEST_STATUS_LABEL.items() if value in {s.value for s in TRIAGE_STATUSES}
    ]
    result.sections = [
        ReportSection("waiting", f"Waiting more than {threshold} days", columns, table, gap=True),
        ReportSection(
            "by_status", "By status", ["Status", "Requests", "Oldest (days)", f"Over {threshold} days"], by_status,
        ),
    ]
    result.metrics = [
        ReportMetric("Awaiting a decision", len(rows)),
        ReportMetric(f"Over {threshold} days", len(late), gap=True),
        ReportMetric("Oldest (days)", max(days.values(), default=0)),
    ]
    result.data = {**_items(ctx, late), "older_than_days": threshold}
    return result


# --- F5: Problem demand -----------------------------------------------------------


def _pain_points_with_requirement(db: Session, pain_point_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    """The Pain Points with a Requirement linked to them directly, in either direction (one statement)."""
    if not pain_point_ids:
        return set()
    ids = list(pain_point_ids)
    found: set[uuid.UUID] = set()
    for source_type, source_id, _target_type, target_id in db.execute(
        select(ArtefactLink.source_type, ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id).where(
            ArtefactLink.source_project_id.is_(None),
            or_(
                (ArtefactLink.source_type == PAIN_POINT_TYPE) & (ArtefactLink.source_id.in_(ids)) & (ArtefactLink.target_type == REQUIREMENT_TYPE),
                (ArtefactLink.target_type == PAIN_POINT_TYPE) & (ArtefactLink.target_id.in_(ids)) & (ArtefactLink.source_type == REQUIREMENT_TYPE),
            ),
        )
    ):
        found.add(source_id if source_type == PAIN_POINT_TYPE else target_id)
    return found


def collect_problem_demand(db: Session, ctx: ReportContext) -> ReportResult:
    """F5 — Pain Points by how many requests address them, how many people asked and whether a Requirement exists.

    Args:
        db: Database session.
        ctx: The request.

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}]}` (the Pain Points, most requested first;
        `code` is the Pain Point's own label).
    """
    projects, rows, _ = _load_rows(db, ctx, frozenset(_S) - {_S.DUPLICATE, _S.DECLINED})
    by_project: dict[uuid.UUID, dict[uuid.UUID, list[RequestRow]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.project is None:
            continue
        for pain_point_id in row.links.pain_point_ids:
            by_project[row.project.id][pain_point_id].append(row)
    entries: list[tuple[str, str, uuid.UUID, uuid.UUID, list[RequestRow], bool]] = []
    related = 0
    withheld = 0
    for project in projects:
        wanted = by_project.get(project.id, {})
        if wanted and not ctx.can_view(db, PAIN_POINT_TYPE, project.id):
            withheld += len(wanted)
            continue
        named = get_artefact_summaries_in_project(db, project.id, PAIN_POINT_TYPE, list(wanted)) or {}
        related += sum(1 for i in wanted if i not in named)
        direct = _pain_points_with_requirement(db, [i for i in wanted if i in named])
        for pain_point_id, summary in named.items():
            if summary.is_archived:
                continue
            requests = wanted[pain_point_id]
            has_requirement = pain_point_id in direct or any(r.links.requirement_ids for r in requests)
            entries.append((project.name, summary.label, project.id, pain_point_id, requests, has_requirement))

    def people(requests: Sequence[RequestRow]) -> tuple[int, float]:
        parties = {(q.artefact_type, q.id): q.effective_weight for r in requests for q in r.demand.requesters}
        return len(parties), round(sum(parties.values()), 4)

    entries.sort(key=lambda e: (-len(e[4]), -people(e[4])[1], e[0].lower(), e[1]))
    open_count = {e[3]: sum(r.version.status in REQUEST_OPEN_STATUSES for r in e[4]) for e in entries}
    columns = ["Pain Point", "Project", "Requests", "Open", "Requesters", "Weighted demand", "Requirement", "Asked for by"]
    table: list[list[str]] = []
    tones: list[list[str | None]] = []
    for project_name, label, _project_id, pain_point_id, requests, has_requirement in entries:
        count, weighted = people(requests)
        table.append([
            label, project_name, str(len(requests)), str(open_count[pain_point_id]), str(count), _weighted(weighted),
            "Yes" if has_requirement else "None yet",
            "; ".join(sorted(_code(ctx, r) for r in requests)[:_NAMES_SHOWN])
            + (f" +{len(requests) - _NAMES_SHOWN}" if len(requests) > _NAMES_SHOWN else ""),
        ])
        tones.append([None, None, None, None, None, None, None if has_requirement else "warning", None])
    notes = [
        "Pain Points that at least one request addresses (declined and merged-duplicate requests are not counted). "
        "Requesters are counted once across the requests, so the same person asking twice is one. A Pain Point has a "
        "Requirement when one is linked to it or realises a request that addresses it.",
    ]
    if withheld:
        notes.append(f"{withheld} Pain Point(s) are not listed: you do not have permission to view Pain Points in their project.")
    if related:
        notes.append(f"{related} Pain Point link(s) to a related project are not listed: they are that project's records.")
    result = _result(ctx, "f5", "Problem demand", eligible=len(projects), notes=notes)
    result.sections = [ReportSection("problems", "Pain Points by requests", columns, table, gap=True)]
    result.metrics = [
        ReportMetric("Pain Points asked for", len(entries)),
        ReportMetric("With no Requirement yet", sum(not e[5] for e in entries), gap=True),
        ReportMetric("Requests addressing a problem", len({r.request.id for e in entries for r in e[4]})),
    ]
    result.data = {"items": [
        {"id": e[3], "project_id": e[2], "code": e[1], "title": e[1]} for e in entries
    ]}
    return result


# --- Declarations -----------------------------------------------------------------

_RANK_BY = ReportParamDefinition(
    "rank_by", "string", default="demand", choices=("demand", "score"),
    choice_labels={"demand": "Weighted demand", "score": "Score"}, label="Rank by",
    description="Rank by weighted demand (then score) or by score (then weighted demand).",
)
_SCORING_MODEL = ReportParamDefinition(
    "scoring_model", "string", label="Scoring model",
    description="Key of the scoring model to score under (for example ice, rice); default: the project's, or the organisation's, default model.",
)
_INCLUDE_INBOX = ReportParamDefinition(
    "include_inbox", "boolean", default=False, label="Include the inbox",
    description="Organisation-wide runs only: also list the organisation's own (inbox) requests.",
)
_INCLUDE_CLOSED = ReportParamDefinition(
    "include_closed", "boolean", default=False, label="Include delivered and declined",
    description="Also list delivered and declined requests with no Pain Point.",
)
_OLDER_THAN = ReportParamDefinition(
    "older_than_days", "integer", default=14, minimum=0, maximum=3650, label="Waiting longer than (days)",
    description="List requests that have been in New or Under review for more than this many days (default 14).",
)

# Badge colours for the PDF and Word output, as the screen's badges show them.
_CELL_TONES = {
    "Status": tones_by_label((REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE)),
    "Outcome": tones_by_label((REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE)),
}

_ORG_ROLE = "org_feedback_triager"

_REPORTS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "f1", "demand-ranking", "Demand ranking",
        "Open requests ranked by weighted demand and score, with requests resting on no Pain Point flagged.",
        collect_demand_ranking, subcomponent=REQUEST_SUBCOMPONENT_KEY, org_level=True, org_role_key=_ORG_ROLE,
        params=(_RANK_BY, _SCORING_MODEL, _INCLUDE_INBOX),
        parts=(ReportPartDefinition("ranking", "Open requests"),),
        record_types=(REQUEST_ARTEFACT_TYPE,),
    ),
    ReportDefinition(
        "f2", "unlinked-requests", "Unlinked requests",
        "Requests that address no Pain Point: a proposed solution with no problem behind it.",
        collect_unlinked, subcomponent=REQUEST_SUBCOMPONENT_KEY, org_level=True, org_role_key=_ORG_ROLE,
        params=(_INCLUDE_CLOSED,),
        parts=(ReportPartDefinition("unlinked", "Requests with no Pain Point"),),
        record_types=(REQUEST_ARTEFACT_TYPE,),
    ),
    ReportDefinition(
        "f3", "close-the-loop", "Close the loop",
        "Delivered or declined requests with requesters who have not been told the outcome.",
        collect_close_the_loop, subcomponent=REQUEST_SUBCOMPONENT_KEY, org_level=True, org_role_key=_ORG_ROLE,
        parts=(ReportPartDefinition("open_loops", "Requests with requesters still to tell"),),
        record_types=(REQUEST_ARTEFACT_TYPE,),
    ),
    ReportDefinition(
        "f4", "triage-ageing", "Triage ageing",
        "Requests that have waited in New or Under review longer than a number of days.",
        collect_triage_ageing, subcomponent=REQUEST_SUBCOMPONENT_KEY, org_level=True, org_role_key=_ORG_ROLE,
        params=(_OLDER_THAN, _INCLUDE_INBOX),
        parts=(ReportPartDefinition("waiting", "Waiting too long"), ReportPartDefinition("by_status", "By status")),
        record_types=(REQUEST_ARTEFACT_TYPE,),
    ),
    ReportDefinition(
        "f5", "problem-demand", "Problem demand",
        "Pain Points by the number of requests and people asking for a fix, and whether a Requirement exists.",
        collect_problem_demand, subcomponent=REQUEST_SUBCOMPONENT_KEY, org_level=True, org_role_key=_ORG_ROLE,
        parts=(ReportPartDefinition("problems", "Pain Points by requests"),),
        record_types=(REQUEST_ARTEFACT_TYPE, PAIN_POINT_TYPE),
    ),
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = tuple(replace(d, cell_tones=_CELL_TONES) for d in _REPORTS)

# Project and organisation routers for the module to include.
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
