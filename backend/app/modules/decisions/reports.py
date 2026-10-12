"""
Module: modules.decisions.reports

Report data layer for Decision Management (docs/plans/platform-enhancements-
2026-10-plan.md Phase 8): four project-level reports, one `collect_*` function
each, returning the core framework's `ReportResult`, plus the
`REPORT_DEFINITIONS` that declare them to the registry. Result shapes, scope
(`readable_projects`), PDF/CSV rendering, routes, MCP tools and the catalogue
all live in `app.services.report_framework`, so this module is declarations
and queries only.

Reports: D1 Decision register, D2 Approval ageing, D3 Decision log, D4
Rationale coverage.

Design decisions (all Decided by: Agent unless stated):
- Project-level only; no organisation-wide variant (Decided by: User, Q8). The
  module defines no org-scoped role to gate one with.
- The module has no sub-components, so the collectors narrow `ctx.projects` to
  projects where the module is effectively enabled themselves (a child project
  can have it off while its parent has it on).
- "Overdue" in D2 is a waiting-time threshold (`overdue_days`), because a
  Decision has no due date; "unowned" is a missing *decision maker*, because
  `owner_id` is mandatory. Both are the nearest honest reading of the plan's
  "overdue and unowned highlighted".
- D2 measures the wait from the audit event that put the Decision into its
  current status (`proposed` / `submitted_for_review`), falling back to its
  creation time, because `updated_at` moves on any edit.
- D3 lists Decisions that were *made*: Approved and Superseded, by
  `decision_date`. Rejected Decisions are in the register (D1), not the log.
- D4 counts a Decision as having rationale when it links to at least one
  non-Decision artefact the caller can read; Decision-to-Decision links
  (supersession, depends on) are not rationale. Rejected and Superseded
  Decisions are history and are not expected to have it. A link to something
  the caller cannot read counts as absent rather than leaking, so a gap list
  may over-report but never reveals a hidden record.
- Free text in D3 is clipped (`_CLIP`) so a long rationale cannot make a PDF
  table row taller than a page; the Decision page holds the full text.
- Reports never include Restricted data and are not audit-logged (framework rule).

Dependencies: `app.services.report_framework`, `app.modules.registry`,
`app.services.relationships`, the Decisions models.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.labels import DECISION_STATUS_LABEL, decision_status_label
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.registry import (
    ReportDefinition,
    ReportParamDefinition,
    get_artefact_summary,
    is_module_enabled_for_project,
)
from app.services import relationships
from app.services.principals import principal_labels, principal_text
from app.services.report_framework import (
    ReportContext,
    ReportMetric,
    ReportResult,
    ReportSection,
    build_report_routers,
)

MODULE_KEY = "decisions"
DECISION_TYPE = "decision"
SUPERSEDES_FORWARD_NAME = "Supersedes"

# Decisions still expected to be justified by something: not history.
LIVE_STATUSES = frozenset(
    {DecisionStatus.DRAFT, DecisionStatus.PROPOSED, DecisionStatus.UNDER_REVIEW, DecisionStatus.APPROVED}
)
AWAITING_STATUSES = frozenset({DecisionStatus.PROPOSED, DecisionStatus.UNDER_REVIEW})
MADE_STATUSES = frozenset({DecisionStatus.APPROVED, DecisionStatus.SUPERSEDED})
# The audit action recorded when a Decision entered each awaiting status.
_ENTERED_ACTION = {DecisionStatus.PROPOSED: "proposed", DecisionStatus.UNDER_REVIEW: "submitted_for_review"}
DEFAULT_LOG_DAYS = 90
_CLIP = 400


# --- Small shared helpers ---------------------------------------------------------


def _fmt_date(value: date | datetime | None) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else (value.isoformat() if value else "")


def _clip(text: str | None, limit: int = _CLIP) -> str:
    """Collapses whitespace and cuts `text` to `limit` characters with an ellipsis."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _people(db: Session, decisions: list[Decision], *, owner: bool = True) -> Callable[[str | None, uuid.UUID | None, str], str]:
    """Resolves the principals (owner and decision maker) of `decisions` once; returns a lookup
    `(type, id, empty) -> text` (`services.principals.principal_text`: a group reads
    `Name (Organisation group)`). `owner=False` skips the owners when only decision makers are printed."""
    refs = [(d.decision_maker_type, d.decision_maker_id) for d in decisions if d.decision_maker_id]
    if owner:
        refs += [(d.owner_type, d.owner_id) for d in decisions]
    labels = principal_labels(db, refs)

    def text(type_value: str | None, principal_id: uuid.UUID | None, empty: str = "") -> str:
        if type_value is None or principal_id is None:
            return empty
        return principal_text(labels[(type_value, principal_id)], empty=empty)

    return text


def _enabled_projects(db: Session, req: ReportContext) -> list[Project]:
    """The in-scope projects where Decision Management is effectively enabled."""
    return [p for p in req.projects if is_module_enabled_for_project(db, p.id, MODULE_KEY)]


def _result(req: ReportContext, key: str, title: str, *, eligible: int, notes: list[str] | None = None) -> ReportResult:
    """Starts a `ReportResult` with the scope note and any report-specific notes."""
    return ReportResult(
        key=key, title=title, scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, *(notes or [])], sections=[], eligible_projects=eligible,
    )


def _type_names(db: Session, decisions: list[Decision]) -> dict[uuid.UUID, str]:
    """Maps the decisions' type ids to type names in one query."""
    ids = {d.decision_type_id for d in decisions}
    if not ids:
        return {}
    return dict(db.execute(
        select(DecisionTypeDefinition.id, DecisionTypeDefinition.name).where(DecisionTypeDefinition.id.in_(ids))
    ).all())


def _supersession(db: Session, req: ReportContext, decisions: list[Decision]) -> tuple[dict, dict, dict]:
    """Supersession edges touching `decisions`.

    Returns:
        `(supersedes, superseded_by, codes)`: for each decision id, the ids it
        supersedes and the ids superseding it, and a code lookup covering every
        id mentioned (including decisions outside `decisions`).
    """
    supersedes: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    superseded_by: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    link_type_id = db.scalar(select(RequirementLinkTypeDefinition.id).where(
        RequirementLinkTypeDefinition.organization_id == req.organization.id,
        RequirementLinkTypeDefinition.forward_name == SUPERSEDES_FORWARD_NAME,
    ))
    ids = [d.id for d in decisions]
    if link_type_id is not None and ids:
        links = [
            *relationships.get_links_from_many(db, DECISION_TYPE, ids),
            *relationships.get_links_to_many(db, DECISION_TYPE, ids),
        ]
        for link in {link.id: link for link in links}.values():
            if link.link_type_id == link_type_id and link.source_type == link.target_type == DECISION_TYPE:
                supersedes[link.source_id].append(link.target_id)
                superseded_by[link.target_id].append(link.source_id)
    mentioned = {i for group in (supersedes, superseded_by) for ids_ in group.values() for i in ids_} | set(ids)
    codes = dict(db.execute(select(Decision.id, Decision.unique_code).where(Decision.id.in_(mentioned))).all()) if mentioned else {}
    return supersedes, superseded_by, codes


def _load(db: Session, projects: list[Project], *statuses: DecisionStatus, include_archived: bool = False) -> list[Decision]:
    """Decisions of `projects`, optionally narrowed to `statuses`, oldest code first."""
    if not projects:
        return []
    query = select(Decision).where(Decision.project_id.in_([p.id for p in projects]))
    if not include_archived:
        query = query.where(Decision.is_archived.is_(False))
    if statuses:
        query = query.where(Decision.status.in_(statuses))
    return list(db.scalars(query.order_by(Decision.unique_code)).all())


# --- D1: Decision register ---------------------------------------------------------


@dataclass
class RegisterRow:
    """One Decision in the register, for the on-screen view."""

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str


def collect_decision_register(db: Session, req: ReportContext) -> ReportResult:
    """D1 — every Decision with its type, status, date, people and supersession.

    Args:
        db: Database session.
        req: The request (`status`, `decision_type`, `date_from`, `date_to`
            and `include_archived` narrow it).

    Returns:
        The report; `data` is `{"items": list[RegisterRow]}`.
    """
    projects = _enabled_projects(db, req)
    names = {p.id: p.name for p in projects}
    status_filter = req.params.get("status")
    wanted_type = (req.params.get("decision_type") or "").strip().lower()
    date_from, date_to = req.params.get("date_from"), req.params.get("date_to")
    decisions = _load(
        db, projects, *([DecisionStatus(status_filter)] if status_filter else []),
        include_archived=bool(req.params.get("include_archived")),
    )
    type_names = _type_names(db, decisions)
    decisions = [
        d for d in decisions
        if (not wanted_type or type_names.get(d.decision_type_id, "").lower() == wanted_type)
        and (date_from is None or (d.decision_date is not None and d.decision_date >= date_from))
        and (date_to is None or (d.decision_date is not None and d.decision_date <= date_to))
    ]
    decisions.sort(key=lambda d: (names[d.project_id].lower(), d.unique_code))
    people = _people(db, decisions)
    supersedes, superseded_by, codes = _supersession(db, req, decisions)

    def codes_of(ids: list[uuid.UUID]) -> str:
        return ", ".join(sorted(codes.get(i, "") for i in ids if i in codes))

    filters = [
        f for f in (
            f"status {decision_status_label(status_filter)}" if status_filter else "",
            f"type {req.params['decision_type']}" if wanted_type else "",
            f"decided from {date_from.isoformat()}" if date_from else "",
            f"decided to {date_to.isoformat()}" if date_to else "",
            "archived included" if req.params.get("include_archived") else "",
        ) if f
    ]
    result = _result(req, "d1", "Decision register", eligible=len(projects), notes=[
        f"Filters: {', '.join(filters)}." if filters else "No filters: every non-archived Decision is listed.",
    ])
    columns = [
        "Code", "Title", "Project", "Type", "Status", "Decision date", "Decision maker", "Owner", "Supersedes",
        "Superseded by",
    ]
    rows = [
        [
            d.unique_code, d.title, names[d.project_id], type_names.get(d.decision_type_id, ""),
            decision_status_label(d.status.value), _fmt_date(d.decision_date),
            people(d.decision_maker_type, d.decision_maker_id), people(d.owner_type, d.owner_id),
            codes_of(supersedes.get(d.id, [])), codes_of(superseded_by.get(d.id, [])),
        ]
        for d in decisions
    ]
    by_status = Counter(d.status.value for d in decisions)
    by_type = Counter(type_names.get(d.decision_type_id, "") for d in decisions)
    result.sections = [
        ReportSection("register", "Decisions", columns, rows),
        ReportSection(
            "by_status", "By status", ["Status", "Decisions"],
            [[label, str(by_status[value])] for value, label in DECISION_STATUS_LABEL.items()],
        ),
        ReportSection("by_type", "By type", ["Type", "Decisions"], [[n or "(none)", str(c)] for n, c in sorted(by_type.items())]),
    ]
    result.metrics = [
        ReportMetric("Decisions", len(decisions)),
        ReportMetric("Approved", by_status[DecisionStatus.APPROVED.value]),
        ReportMetric("Awaiting a verdict", sum(by_status[s.value] for s in AWAITING_STATUSES)),
        ReportMetric("Superseded", by_status[DecisionStatus.SUPERSEDED.value]),
        ReportMetric("Rejected", by_status[DecisionStatus.REJECTED.value]),
    ]
    result.data = {"items": [RegisterRow(d.id, d.project_id, d.unique_code, d.title) for d in decisions]}
    return result


# --- D2: Approval ageing -----------------------------------------------------------


def _waiting_since(db: Session, decisions: list[Decision]) -> dict[uuid.UUID, datetime]:
    """When each awaiting Decision entered its current status.

    The latest matching audit event wins; a Decision with no such event (created
    in that status by an import, say) falls back to its creation time.
    """
    ids = {str(d.id): d for d in decisions}
    if not ids:
        return {}
    since: dict[uuid.UUID, datetime] = {d.id: d.created_at for d in decisions}
    events = db.execute(
        select(AuditEvent.entity_id, AuditEvent.action, AuditEvent.created_at).where(
            AuditEvent.entity_type == DECISION_TYPE, AuditEvent.entity_id.in_(ids),
            AuditEvent.action.in_(list(_ENTERED_ACTION.values())),
        ).order_by(AuditEvent.created_at)
    ).all()
    for entity_id, action, created_at in events:
        decision = ids[entity_id]
        if _ENTERED_ACTION.get(decision.status) == action:
            since[decision.id] = created_at
    return since


def collect_approval_ageing(db: Session, req: ReportContext) -> ReportResult:
    """D2 — Proposed and Under review Decisions by days waiting, longest first.

    Args:
        db: Database session.
        req: The request (`overdue_days` is the waiting time after which a
            Decision is flagged overdue).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, days_waiting, is_overdue, unassigned}]}`.
    """
    projects = _enabled_projects(db, req)
    names = {p.id: p.name for p in projects}
    threshold = req.params["overdue_days"]
    decisions = _load(db, projects, *AWAITING_STATUSES)
    since = _waiting_since(db, decisions)
    type_names = _type_names(db, decisions)
    people = _people(db, decisions)
    entries = [
        {
            "decision": d, "days": max((req.today - since[d.id].date()).days, 0),
            "unassigned": d.decision_maker_id is None,
        }
        for d in decisions
    ]
    for e in entries:
        e["overdue"] = e["days"] > threshold
    entries.sort(key=lambda e: (-e["days"], e["decision"].unique_code))

    def row(e: dict[str, Any]) -> list[str]:
        d: Decision = e["decision"]
        return [
            d.unique_code, d.title, names[d.project_id], type_names.get(d.decision_type_id, ""),
            decision_status_label(d.status.value), str(e["days"]),
            "Overdue" if e["overdue"] else "", people(d.decision_maker_type, d.decision_maker_id, "No decision maker"),
            people(d.owner_type, d.owner_id),
        ]

    columns = ["Code", "Title", "Project", "Type", "Status", "Days waiting", "Overdue", "Decision maker", "Owner"]
    result = _result(req, "d2", "Approval ageing", eligible=len(projects), notes=[
        f"Days waiting counts from when the Decision entered its current status; over {threshold} days is flagged "
        "overdue. A Decision has no due date, so the threshold is the only overdue test.",
    ])
    result.sections = [
        ReportSection("awaiting", "Awaiting a verdict", columns, [row(e) for e in entries]),
        ReportSection("overdue", "Overdue", columns, [row(e) for e in entries if e["overdue"]], gap=True),
        ReportSection("unassigned", "No decision maker", columns, [row(e) for e in entries if e["unassigned"]], gap=True),
    ]
    result.metrics = [
        ReportMetric("Awaiting a verdict", len(entries)),
        ReportMetric("Overdue", sum(e["overdue"] for e in entries), gap=True),
        ReportMetric("No decision maker", sum(e["unassigned"] for e in entries), gap=True),
        ReportMetric("Longest wait (days)", entries[0]["days"] if entries else 0),
    ]
    result.data = {"items": [
        {
            "id": e["decision"].id, "project_id": e["decision"].project_id, "code": e["decision"].unique_code,
            "days_waiting": e["days"], "is_overdue": e["overdue"], "unassigned": e["unassigned"],
        }
        for e in entries
    ]}
    return result


# --- D3: Decision log ----------------------------------------------------------------


def collect_decision_log(db: Session, req: ReportContext) -> ReportResult:
    """D3 — Decisions made in a period, with context, chosen option and rationale.

    Args:
        db: Database session.
        req: The request (`date_from`/`date_to` bound `decision_date`; with no
            `date_from` the last `DEFAULT_LOG_DAYS` days are covered).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, decision_date}]}` oldest first.
    """
    projects = _enabled_projects(db, req)
    names = {p.id: p.name for p in projects}
    date_to = req.params.get("date_to") or req.today
    date_from = req.params.get("date_from") or (date_to - timedelta(days=DEFAULT_LOG_DAYS))
    decisions = [
        d for d in _load(db, projects, *MADE_STATUSES)
        if d.decision_date is not None and date_from <= d.decision_date <= date_to
    ]
    decisions.sort(key=lambda d: (d.decision_date, names[d.project_id].lower(), d.unique_code))
    type_names = _type_names(db, decisions)
    people = _people(db, decisions, owner=False)
    result = _result(req, "d3", "Decision log", eligible=len(projects), notes=[
        f"Approved and Superseded Decisions with a decision date from {date_from.isoformat()} to {date_to.isoformat()}. "
        f"Free-text fields are cut to {_CLIP} characters; open the Decision for the full text.",
    ])
    columns = [
        "Decision date", "Code", "Title", "Project", "Type", "Status", "Decision maker", "Context", "Chosen option",
        "Rationale",
    ]
    result.sections = [ReportSection("log", "Decisions made", columns, [
        [
            _fmt_date(d.decision_date), d.unique_code, d.title, names[d.project_id], type_names.get(d.decision_type_id, ""),
            decision_status_label(d.status.value), people(d.decision_maker_type, d.decision_maker_id),
            _clip(d.context), _clip(d.chosen_option or d.decision_statement), _clip(d.rationale),
        ]
        for d in decisions
    ])]
    result.metrics = [
        ReportMetric("Decisions made", len(decisions)),
        ReportMetric("Without a rationale", sum(not (d.rationale or "").strip() for d in decisions), gap=True),
    ]
    result.data = {"items": [
        {"id": d.id, "project_id": d.project_id, "code": d.unique_code, "decision_date": d.decision_date} for d in decisions
    ]}
    return result


# --- D4: Rationale coverage -----------------------------------------------------------


def collect_rationale_coverage(db: Session, req: ReportContext) -> ReportResult:
    """D4 — live Decisions with no linked artefact, and Requirements with no linked Decision.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"unlinked_decisions": int, "unlinked_requirements": int}`.
    """
    projects = _enabled_projects(db, req)
    names = {p.id: p.name for p in projects}
    project_ids = {p.id for p in projects}
    result = _result(req, "d4", "Rationale coverage", eligible=len(projects), notes=[
        "A Decision counts as having rationale when it links to at least one artefact other than a Decision. "
        "Rejected and Superseded Decisions are history and are not listed. Links to records you cannot read count as absent.",
    ])
    decisions = _load(db, projects)
    live = [d for d in decisions if d.status in LIVE_STATUSES]
    linked: set[uuid.UUID] = set()
    for link in relationships.get_links_from_many(db, DECISION_TYPE, [d.id for d in live]):
        other_type, other_id, own_id = link.target_type, link.target_id, link.source_id
        if other_type != DECISION_TYPE and _readable_artefact(db, other_type, other_id, project_ids):
            linked.add(own_id)
    for link in relationships.get_links_to_many(db, DECISION_TYPE, [d.id for d in live]):
        if link.source_type != DECISION_TYPE and _readable_artefact(db, link.source_type, link.source_id, project_ids):
            linked.add(link.target_id)
    type_names = _type_names(db, live)
    bare = [d for d in live if d.id not in linked]

    requirements = _requirements(db, project_ids)
    decision_ids = [d.id for d in decisions]
    covered: set[uuid.UUID] = set()
    req_ids = [r.id for r, _ in requirements]
    decision_id_set = set(decision_ids)
    for link in relationships.get_links_from_many(db, ArtefactType.REQUIREMENT.value, req_ids):
        if link.target_type == DECISION_TYPE and link.target_id in decision_id_set:
            covered.add(link.source_id)
    for link in relationships.get_links_to_many(db, ArtefactType.REQUIREMENT.value, req_ids):
        if link.source_type == DECISION_TYPE and link.source_id in decision_id_set:
            covered.add(link.target_id)
    uncovered = [(r, v) for r, v in requirements if r.id not in covered]

    result.sections = [
        ReportSection(
            "decisions_without_links", "Decisions with no linked artefact",
            ["Code", "Title", "Project", "Type", "Status"],
            [
                [d.unique_code, d.title, names[d.project_id], type_names.get(d.decision_type_id, ""),
                 decision_status_label(d.status.value)]
                for d in sorted(bare, key=lambda d: (names[d.project_id].lower(), d.unique_code))
            ],
            gap=True,
        ),
        ReportSection(
            "requirements_without_decisions", "Requirements with no linked Decision",
            ["Code", "Name", "Project"],
            [[r.unique_code, v.name, names[r.project_id]] for r, v in uncovered],
            note="Non-archived Requirements; whether each needs a Decision is for the team to judge.", gap=True,
        ),
    ]
    result.metrics = [
        ReportMetric("Live Decisions", len(live)),
        ReportMetric("Decisions with no linked artefact", len(bare), gap=True),
        ReportMetric("Requirements", len(requirements)),
        ReportMetric("Requirements with no linked Decision", len(uncovered), gap=True),
    ]
    result.data = {"unlinked_decisions": len(bare), "unlinked_requirements": len(uncovered)}
    return result


def _readable_artefact(db: Session, artefact_type: str, artefact_id: uuid.UUID, project_ids: set[uuid.UUID]) -> bool:
    """Whether the artefact exists, is not archived and sits in the report's scope.

    Requirements are core, not a module artefact, so they are checked directly; every other type goes
    through its owning module's summary provider (a disabled module reads as absent).
    """
    if artefact_type == ArtefactType.REQUIREMENT.value:
        requirement = db.get(Requirement, artefact_id)
        return requirement is not None and requirement.project_id in project_ids and not requirement.is_archived
    summary = get_artefact_summary(db, artefact_type, artefact_id)
    return summary is not None and summary.project_id in project_ids and not summary.is_archived


def _requirements(db: Session, project_ids: set[uuid.UUID]) -> list[tuple[Requirement, RequirementVersion]]:
    """Non-archived Requirements (current version) of `project_ids`, by code."""
    if not project_ids:
        return []
    rows = db.execute(
        select(Requirement, RequirementVersion)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.project_id.in_(project_ids), Requirement.is_archived.is_(False),
            RequirementVersion.valid_to.is_(None),
        )
        .order_by(Requirement.unique_code)
    ).all()
    return [(r, v) for r, v in rows]


# --- Declarations ----------------------------------------------------------------------

_STATUS = ReportParamDefinition(
    "status", "string", choices=tuple(DECISION_STATUS_LABEL), choice_labels=dict(DECISION_STATUS_LABEL), label="Status",
    description="Only Decisions in this status.",
)
_DECISION_TYPE = ReportParamDefinition(
    "decision_type", "string", label="Decision type",
    description="Only Decisions of the type with this name (case-insensitive).",
)
_DATE_FROM = ReportParamDefinition(
    "date_from", "date", label="Decided from", description="Earliest decision date to include.",
)
_DATE_TO = ReportParamDefinition(
    "date_to", "date", label="Decided to", description="Latest decision date to include.",
)
_LOG_DATE_FROM = ReportParamDefinition(
    "date_from", "date", label="Decided from",
    description=f"Earliest decision date to include (default: {DEFAULT_LOG_DAYS} days before the end of the period).",
)
_INCLUDE_ARCHIVED = ReportParamDefinition(
    "include_archived", "boolean", default=False, label="Include archived", description="Also list archived Decisions.",
)
_OVERDUE_DAYS = ReportParamDefinition(
    "overdue_days", "integer", default=14, minimum=1, maximum=365, label="Overdue after (days)",
    description="Days a Decision may wait for a verdict before it is flagged overdue (default 14).",
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "d1", "decision-register", "Decision register",
        "Every Decision with its type, status, date, decision maker, owner and supersession.",
        collect_decision_register, params=(_STATUS, _DECISION_TYPE, _DATE_FROM, _DATE_TO, _INCLUDE_ARCHIVED),
    ),
    ReportDefinition(
        "d2", "approval-ageing", "Approval ageing",
        "Proposed and Under review Decisions by days waiting, with overdue and decision-maker-less ones flagged.",
        collect_approval_ageing, params=(_OVERDUE_DAYS,),
    ),
    ReportDefinition(
        "d3", "decision-log", "Decision log",
        "Decisions made in a period, with context, chosen option and rationale.",
        collect_decision_log, params=(_LOG_DATE_FROM, _DATE_TO),
    ),
    ReportDefinition(
        "d4", "rationale-coverage", "Rationale coverage",
        "Decisions with no linked artefact, and Requirements with no linked Decision.", collect_rationale_coverage,
    ),
)

# Project router for the module to include (`project_router`); there is no organisation-wide variant.
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
