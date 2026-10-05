"""
Module: modules.context_strategy.reports

Report data layer for Context & Strategy (docs/plans/module-01-context-and-
strategy-plan.md Phases 12/12b): the nine reports R1–R9 as one `collect_*`
function each, returning the core framework's `ReportResult`, plus the
`REPORT_DEFINITIONS` that declare them to the registry. Everything
module-neutral — result shapes, scope rule (`readable_projects`), PDF/CSV
rendering, routes, MCP tools, the catalogue — lives in
`app.services.report_framework`; every output form (PDF, CSV, on-screen JSON,
MCP) reads the same `ReportResult`, so a figure is computed exactly once.

Responsibilities:
- Collectors R1–R9. Pain Point scoring is not recomputed here: R1 and R9 are
  built on `pain_point_scores.build_pain_point_scoring`.
- Collectors never widen `ctx.projects` and further narrow it per
  sub-component (`pain_point`, `strategy`, ...) that is enabled.
- `REPORT_DEFINITIONS`: key, slug, gating sub-component, organisation role and
  declared parameters per report.

Design decisions (all Decided by: Agent unless stated; the report list,
formats, model/roll-up choice and access rules are Phase 9, Decided by:
User):
- "Open" Pain Points are Submitted, Triaged and Accepted. Addressed means
  the problem is fixed and Rejected/Duplicate/Closed are finished, so none
  of them belong in a fix ranking.
- Org-wide reports group Pain Points by the scoring model actually applied
  (the project's resolved default unless a model is requested), never
  ranking different models together (Phase 9 Q3).
- Cross-artefact checks ("has a Requirement", "has a Strategy") count only
  artefacts inside the report's readable scope. A link to something the
  caller cannot read is treated as absent rather than leaked, so a gap list
  may over-report; it never reveals a hidden record.
- R2, R5, R6 and R7 are project-level only; R1, R3, R4, R8 and R9 also run
  organisation-wide (Phase 9 Q12), gated by the `org_reports_viewer` role and
  the framework's default `readable_projects` scope. Organisation-scoped
  Strategies, Future States and Guiding Principles appear in the project
  reports they relate to (R2 parents, R6 and R7 rows) because every org
  member can already read them.
- Report reads are not audit-logged, following `modules.compliance.reports`:
  every field here is already returned to the same caller by the module's
  JSON endpoints, and nothing Restricted (no file content, no secrets) is
  included.
- R9 has no tier columns yet: `intentional_in`/`removed_by` stay reserved
  until Product Tiers (Module 13) exists, so the report says so in a note.

Dependencies: core `services.relationships`/`services.scoring`/
`services.report_framework`, the `registry` artefact-summary hook (Decisions,
without importing Module 4) and this module's own models.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.modules.context_strategy._shared import MODULE_KEY, _effective_pain_point_type_name
from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionStatus,
    PainPointStatus,
    StrategyScope,
    StrategyStatus,
)
from app.modules.context_strategy.labels import (
    LIFECYCLE_STATUS_LABEL,
    OPEN_QUESTION_STATUS_LABEL,
    PAIN_POINT_STATUS_LABEL,
    PRIORITY_LABEL,
    ROLLUP_LABEL,
    SCOPE_LABEL,
    SCORE_TARGET_STATUS_LABEL,
    label,
)
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    OpenQuestion,
    PainPoint,
    ProjectPainPointType,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.pain_point_scores import (
    PainPointScoringSummary,
    RollupMethod,
    ScoringContext,
    TargetStatus,
    build_pain_point_scoring,
    load_scoring_context,
    resolve_model,
)
from app.modules.registry import ReportDefinition, ReportParamDefinition, get_artefact_summary
from app.services import relationships
from app.services.report_framework import ReportContext, ReportResult, ReportSection, build_report_routers

STRATEGY_TYPE = "strategy"
FUTURE_STATE_TYPE = "future_state"
PAIN_POINT_TYPE = "pain_point"
GUIDING_PRINCIPLE_TYPE = "guiding_principle"
REQUIREMENT_TYPE = "requirement"
DECISION_TYPE = "decision"

OPEN_PAIN_POINT_STATUSES = frozenset({PainPointStatus.SUBMITTED, PainPointStatus.TRIAGED, PainPointStatus.ACCEPTED})
OPEN_QUESTION_OPEN_STATUSES = frozenset(
    {OpenQuestionStatus.OPEN, OpenQuestionStatus.INVESTIGATING, OpenQuestionStatus.READY_FOR_DECISION}
)
# A Future State that is still expected to arrive; Superseded/Retired ones
# are not part of a forward-looking roadmap.
ROADMAP_FUTURE_STATE_STATUSES = frozenset(
    {FutureStateStatus.DRAFT, FutureStateStatus.PROPOSED, FutureStateStatus.UNDER_REVIEW,
     FutureStateStatus.APPROVED, FutureStateStatus.ACTIVE}
)
# An intentional item whose worst persona is at or above this share of the
# top Severity level is a churn risk rather than an upsell lever (R9).
CHURN_RISK_SEVERITY_RATIO = 0.8
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# --- Small shared helpers --------------------------------------------------------


def _rollup(req: ReportContext) -> RollupMethod:
    """The persona roll-up method requested (the framework already rejected an unknown value)."""
    return RollupMethod(req.params["rollup"])


def _fmt_date(value: date | datetime | None) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else (value.isoformat() if value else "")


def _user_names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """Maps user ids to display names (ids that no longer resolve are absent)."""
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(wanted))).all()}


def _outgoing(db: Session, source_type: str, source_ids: list[uuid.UUID], target_type: str) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Maps each source id to the ids of `target_type` artefacts it links to."""
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for link in relationships.get_links_from_many(db, source_type, source_ids):
        if link.target_type == target_type:
            out[link.source_id].append(link.target_id)
    return out


def _incoming(db: Session, target_type: str, target_ids: list[uuid.UUID], source_type: str) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Maps each target id to the ids of `source_type` artefacts linking to it."""
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for link in relationships.get_links_to_many(db, target_type, target_ids):
        if link.source_type == source_type:
            out[link.target_id].append(link.source_id)
    return out


@dataclass(frozen=True)
class _RequirementRef:
    """A readable Requirement as shown in a report."""

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    status: str


def _requirements(db: Session, ids: set[uuid.UUID], project_ids: set[uuid.UUID]) -> dict[uuid.UUID, _RequirementRef]:
    """Loads the non-archived Requirements among `ids` that sit in
    `project_ids` (links to anything else are treated as absent)."""
    if not ids:
        return {}
    rows = db.execute(
        select(Requirement, RequirementVersion)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.id.in_(ids), Requirement.project_id.in_(project_ids),
            Requirement.is_archived.is_(False), RequirementVersion.valid_to.is_(None),
        )
    ).all()
    from app.services.labels import requirement_status_label

    return {
        r.id: _RequirementRef(r.id, r.project_id, r.unique_code, v.name, requirement_status_label(v.status.value))
        for r, v in rows
    }


def _project_names(projects: list[Project]) -> dict[uuid.UUID, str]:
    return {p.id: p.name for p in projects}


def _result(req: ReportContext, key: str, title: str, *, eligible: int, notes: list[str] | None = None) -> ReportResult:
    """Starts a `ReportResult` with the scope note and any report-specific notes."""
    return ReportResult(
        key=key, title=title, scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, *(notes or [])], sections=[], eligible_projects=eligible,
    )


# --- R1 / R9: Pain Point scoring ------------------------------------------------


@dataclass
class LevelRef:
    """A scoring level as shown on a matrix axis."""

    name: str
    weight: float


@dataclass
class PersonaScoreRow:
    """One persona's (or the all-personas) score of a Pain Point."""

    persona: str
    target_status: str
    severity: str | None
    frequency: str | None
    confidence: str | None
    score: float | None
    band: str | None
    is_blocker: bool
    severity_ratio: float | None


@dataclass
class MatrixPoint:
    """Where a Pain Point sits on the Severity × Frequency matrix: its
    worst counted persona (highest Severity × Frequency)."""

    severity: str
    severity_weight: float
    frequency: str
    frequency_weight: float
    confidence: str | None
    confidence_weight: float | None


@dataclass
class RankedPainPoint:
    """One Pain Point under one model and roll-up."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    title: str
    type_name: str
    status: str
    status_label: str
    priority: str
    date_identified: date
    is_intentional: bool
    model_key: str
    score: float | None
    band: str | None
    band_tone: str | None
    is_blocker: bool
    blocker_personas: list[str]
    churn_risk: bool
    scope: str
    personas_degraded: bool
    personas: list[PersonaScoreRow]
    matrix: MatrixPoint | None
    rank: int | None = None


@dataclass
class ScoredGroup:
    """Pain Points scored under one model (never mixed with another's)."""

    model_key: str
    model_label: str
    rollup: str
    severity_levels: list[LevelRef]
    frequency_levels: list[LevelRef]
    items: list[RankedPainPoint]


def _persona_rows(ctx: ScoringContext, summary: PainPointScoringSummary) -> list[PersonaScoreRow]:
    """Per-persona breakdown of one Pain Point's score rows."""
    rows: list[PersonaScoreRow] = []
    for e in summary.entries:
        levels = {a: ctx.levels_by_id.get(getattr(e.row, f"{a}_level_id")) for a in ("severity", "frequency", "confidence")}
        severity = levels["severity"]
        ratio = (
            float(severity.weight / ctx.top_severity_weight)
            if severity is not None and ctx.top_severity_weight else None
        )
        persona = e.label or ("All personas" if e.target_status is TargetStatus.ALL else "Persona unavailable")
        rows.append(PersonaScoreRow(
            persona=persona, target_status=e.target_status.value,
            severity=severity.name if severity else None,
            frequency=levels["frequency"].name if levels["frequency"] else None,
            confidence=levels["confidence"].name if levels["confidence"] else None,
            score=e.score.normalised if e.score else None, band=e.score.band.label if e.score and e.score.band else None,
            is_blocker=e.is_blocker, severity_ratio=ratio,
        ))
    return rows


def _matrix_point(ctx: ScoringContext, summary: PainPointScoringSummary) -> MatrixPoint | None:
    """The worst counted persona with both Severity and Frequency set."""
    best: tuple[Any, MatrixPoint] | None = None
    for e in summary.entries:
        if e.target_status is TargetStatus.INACTIVE:
            continue
        sev = ctx.levels_by_id.get(e.row.severity_level_id)
        freq = ctx.levels_by_id.get(e.row.frequency_level_id)
        if sev is None or freq is None:
            continue
        conf = ctx.levels_by_id.get(e.row.confidence_level_id)
        point = MatrixPoint(
            sev.name, float(sev.weight), freq.name, float(freq.weight),
            conf.name if conf else None, float(conf.weight) if conf else None,
        )
        weight = sev.weight * freq.weight
        if best is None or weight > best[0]:
            best = (weight, point)
    return best[1] if best else None


def _score_pain_points(
    db: Session, req: ReportContext, statuses: frozenset[PainPointStatus], *, intentional: bool | None = None,
) -> list[ScoredGroup]:
    """Scores the in-scope Pain Points in `statuses`, grouped by the model
    actually applied.

    Args:
        db: Database session.
        req: The request; `model_key` forces one model, otherwise each
            project's resolved default applies.
        statuses: Which Pain Point statuses to include.
        intentional: `True`/`False` keeps only intentional/unintentional
            items; `None` keeps both.

    Returns:
        One group per model that has at least one item, ordered by model key.

    Raises:
        HTTPException: 400 for an unknown `model_key`.
    """
    groups: dict[str, ScoredGroup] = {}
    type_names: dict[uuid.UUID, str] = {}
    for project in req.eligible(db, "pain_point"):
        query = select(PainPoint).where(
            PainPoint.project_id == project.id, PainPoint.is_archived.is_(False), PainPoint.status.in_(statuses),
        )
        if intentional is not None:
            query = query.where(PainPoint.is_intentional.is_(intentional))
        pain_points = list(db.scalars(query.order_by(PainPoint.created_at)).all())
        ctx = load_scoring_context(db, project)
        model = resolve_model(ctx, req.params["model_key"])
        group = groups.get(model.key)
        if group is None:
            group = groups[model.key] = ScoredGroup(
                model_key=model.key, model_label=model.label, rollup=_rollup(req).value,
                severity_levels=[LevelRef(lvl.name, float(lvl.weight)) for lvl in ctx.levels_by_axis.get("severity", [])],
                frequency_levels=[LevelRef(lvl.name, float(lvl.weight)) for lvl in ctx.levels_by_axis.get("frequency", [])],
                items=[],
            )
        summaries = build_pain_point_scoring(db, ctx, pain_points, model, _rollup(req))
        for pp, summary in zip(pain_points, summaries, strict=True):
            if pp.pain_point_type_id not in type_names:
                ppt = db.get(ProjectPainPointType, pp.pain_point_type_id)
                type_names[pp.pain_point_type_id] = _effective_pain_point_type_name(db, ppt) if ppt else ""
            personas = _persona_rows(ctx, summary)
            counted = [p for p in personas if p.target_status != TargetStatus.INACTIVE.value]
            group.items.append(RankedPainPoint(
                id=pp.id, project_id=project.id, project_name=project.name, title=pp.title,
                type_name=type_names[pp.pain_point_type_id], status=pp.status.value,
                status_label=label(PAIN_POINT_STATUS_LABEL, pp.status.value), priority=pp.priority.value,
                date_identified=pp.date_identified, is_intentional=pp.is_intentional, model_key=model.key,
                score=summary.score.normalised if summary.score else None,
                band=summary.score.band.label if summary.score and summary.score.band else None,
                band_tone=summary.score.band.tone if summary.score and summary.score.band else None,
                is_blocker=summary.is_blocker, blocker_personas=summary.blocker_labels,
                churn_risk=any((p.severity_ratio or 0) >= CHURN_RISK_SEVERITY_RATIO for p in counted),
                scope=summary.scope, personas_degraded=summary.personas_degraded,
                personas=personas, matrix=_matrix_point(ctx, summary),
            ))
    return [groups[k] for k in sorted(groups) if groups[k].items]


def _fmt_score(value: float | None) -> str:
    return f"{value * 100:.0f}" if value is not None else ""


def _item_row(i: RankedPainPoint) -> list[str]:
    """The common Pain Point row used by the R1 tables."""
    return [
        i.model_key, str(i.rank) if i.rank else "", i.title, i.project_name, i.type_name, i.status_label,
        label(PRIORITY_LABEL, i.priority), _fmt_score(i.score), i.band or "",
        "Blocker: " + (", ".join(i.blocker_personas) or "yes") if i.is_blocker else "",
        "Persona links degraded" if i.personas_degraded else "",
    ]


_R1_COLUMNS = ["Model", "Rank", "Pain point", "Project", "Type", "Status", "Priority", "Score (0–100)", "Band", "Blocker", "Note"]


def collect_pain_point_prioritisation(db: Session, req: ReportContext) -> ReportResult:
    """R1 — open Pain Points ranked by the chosen model and roll-up.

    Ranked items are unintentional, open and scored; unscored items and
    intentional ones are listed separately, and a Blocker is listed in its
    own table so an averaged-away persona-blocking problem stays visible.
    A Severity × Frequency matrix and a per-persona breakdown complete the
    report.

    Args:
        db: Database session.
        req: The request (`model_key`, `rollup` apply).

    Returns:
        The report; `data` is `{"rollup", "groups": list[ScoredGroup]}`.
    """
    groups = _score_pain_points(db, req, OPEN_PAIN_POINT_STATUSES)
    eligible = len(req.eligible(db, "pain_point"))
    result = _result(req, "r1", "Pain Point prioritisation", eligible=eligible, notes=[
        f"Persona roll-up: {label(ROLLUP_LABEL, _rollup(req).value)}. Unscored personas are excluded, not counted as zero.",
        "Items are ranked within one scoring model only; a Blocker is shown whatever the roll-up.",
        "Intentional limitations are excluded from the ranking (see the Intentional section and R9).",
    ])
    ranking, unscored, blockers, intentional, breakdown, matrix = [], [], [], [], [], []
    open_count = scored = 0
    for group in groups:
        fixable = [i for i in group.items if not i.is_intentional]
        ranked = sorted((i for i in fixable if i.score is not None), key=lambda i: (-(i.score or 0), i.title.lower()))
        for n, item in enumerate(ranked, start=1):
            item.rank = n
        ranking += [_item_row(i) for i in ranked]
        unscored += [_item_row(i) for i in fixable if i.score is None]
        blockers += [_item_row(i) for i in fixable if i.is_blocker]
        intentional += [_item_row(i) for i in sorted(
            (i for i in group.items if i.is_intentional), key=lambda i: (-(i.score or 0), i.title.lower()))]
        for i in group.items:
            breakdown += [
                [i.model_key, i.title, i.project_name, p.persona, label(SCORE_TARGET_STATUS_LABEL, p.target_status),
                 p.severity or "", p.frequency or "", p.confidence or "", _fmt_score(p.score), p.band or "",
                 "Yes" if p.is_blocker else ""]
                for p in i.personas
            ]
        open_count += len(fixable)
        scored += len(ranked)
        matrix += _matrix_rows(group, [i for i in fixable if i.matrix is not None])
    result.sections = [
        ReportSection("ranking", "Ranked Pain Points", _R1_COLUMNS, ranking),
        ReportSection("blockers", "Blockers", _R1_COLUMNS, blockers, gap=True,
                      note="At least one persona is at the top Severity level."),
        ReportSection("unscored", "Not scored under this model", _R1_COLUMNS, unscored, gap=True,
                      note="No persona has every input this model needs."),
        ReportSection("matrix", "Severity × Frequency matrix",
                      ["Model", "Severity \\ Frequency", *_matrix_columns(groups)], matrix,
                      note="Count of Pain Points by their worst counted persona; confidence in brackets."),
        ReportSection("intentional", "Intentional limitations", _R1_COLUMNS, intentional,
                      note="Deliberate tier limitations: scored, but not part of the fix ranking."),
        ReportSection("personas", "Per-persona breakdown",
                      ["Model", "Pain point", "Project", "Persona", "Persona status", "Severity", "Frequency",
                       "Confidence", "Score (0–100)", "Band", "Blocker"], breakdown),
    ]
    result.metrics = [
        ("Open Pain Points (excluding intentional)", open_count), ("Scored", scored),
        ("Not scored", len(unscored)), ("Blockers", len(blockers)), ("Intentional limitations", len(intentional)),
    ]
    result.data = {"rollup": _rollup(req).value, "groups": groups}
    return result


def _matrix_columns(groups: list[ScoredGroup]) -> list[str]:
    """Frequency column headings (the first group's levels, low to high)."""
    return [lvl.name for lvl in sorted(groups[0].frequency_levels, key=lambda lvl: lvl.weight)] if groups else []


def _matrix_rows(group: ScoredGroup, items: list[RankedPainPoint]) -> list[list[str]]:
    """One row per Severity level (highest first); each cell counts Pain
    Points with a breakdown of their Confidence."""
    frequencies = sorted(group.frequency_levels, key=lambda lvl: lvl.weight)
    rows: list[list[str]] = []
    for sev in sorted(group.severity_levels, key=lambda lvl: -lvl.weight):
        cells: list[str] = []
        for freq in frequencies:
            here = [i for i in items if i.matrix and i.matrix.severity == sev.name and i.matrix.frequency == freq.name]
            confidence = Counter(i.matrix.confidence or "Unrated" for i in here if i.matrix)
            cells.append(
                f"{len(here)} ({', '.join(f'{k} ×{v}' for k, v in sorted(confidence.items()))})" if here else ""
            )
        rows.append([group.model_key, sev.name, *cells])
    return rows


def collect_upgrade_drivers(db: Session, req: ReportContext) -> ReportResult:
    """R9 — intentional Pain Points (deliberate tier limitations) with
    per-persona Severity.

    A limitation whose worst persona is at or above
    `CHURN_RISK_SEVERITY_RATIO` of the top Severity level is flagged as a
    churn risk rather than an upsell lever. Tier columns are reserved until
    Product Tiers (Module 13) exists.

    Args:
        db: Database session.
        req: The request (`model_key`, `rollup` apply).

    Returns:
        The report; `data` is `{"rollup", "groups"}` as for R1.
    """
    groups = _score_pain_points(db, req, OPEN_PAIN_POINT_STATUSES, intentional=True)
    result = _result(req, "r9", "Upgrade drivers", eligible=len(req.eligible(db, "pain_point")), notes=[
        "Tier columns are empty until Product Tiers (Module 13) is available; limitations are not yet linked to a tier.",
        "Churn risk: a persona is at or near the top Severity level, so the limitation may push users away "
        "rather than towards an upgrade.",
    ])
    columns = ["Model", "Pain point", "Project", "Status", "Introduced in tier", "Removed by tier",
               "Persona severity", "Score (0–100)", "Band", "Assessment"]
    rows, churn_rows = [], []
    for group in groups:
        for i in sorted(group.items, key=lambda i: (-(i.score or 0), i.title.lower())):
            persona_severity = "; ".join(f"{p.persona}: {p.severity}" for p in i.personas if p.severity) or "Not scored"
            row = [
                i.model_key, i.title, i.project_name, i.status_label, "", "", persona_severity, _fmt_score(i.score),
                i.band or "", "Churn risk" if i.churn_risk else "Upsell lever",
            ]
            rows.append(row)
            if i.churn_risk:
                churn_rows.append(row)
    result.sections = [
        ReportSection("drivers", "Intentional limitations", columns, rows),
        ReportSection("churn", "Churn risks", columns, churn_rows, gap=True),
    ]
    result.metrics = [("Intentional limitations", len(rows)), ("Churn risks", len(churn_rows))]
    result.data = {"rollup": _rollup(req).value, "groups": groups}
    return result


# --- R2: Strategy cascade -----------------------------------------------------------


@dataclass
class CascadeNode:
    """One node of the Strategy → Future State → Requirement tree."""

    kind: str
    id: uuid.UUID
    title: str
    status: str
    project: str
    children: list[CascadeNode] = field(default_factory=list)


def collect_strategy_cascade(db: Session, req: ReportContext) -> ReportResult:
    """R2 — Org Strategy → Project Strategy → Future State → Requirement,
    with the alignment gaps: Project Strategies with no organisation parent,
    Active Strategies with no Requirement, Future States with no Strategy.

    Args:
        db: Database session.
        req: The request (project-level).

    Returns:
        The report; `data` is `{"tree": list[CascadeNode]}`.
    """
    projects = req.eligible(db, "strategy")
    project_ids = {p.id for p in req.projects}
    names = _project_names(req.projects)
    result = _result(req, "r2", "Strategy cascade and alignment", eligible=len(projects), notes=[
        "Links to artefacts outside the projects you can read in this report are not counted.",
    ])
    project_strategies = list(db.scalars(select(Strategy).where(
        Strategy.scope == StrategyScope.PROJECT, Strategy.project_id.in_([p.id for p in projects]),
        Strategy.is_archived.is_(False),
    )).all())
    ps_ids = [s.id for s in project_strategies]
    org_links_out = _outgoing(db, STRATEGY_TYPE, ps_ids, STRATEGY_TYPE)
    org_links_in = _incoming(db, STRATEGY_TYPE, ps_ids, STRATEGY_TYPE)
    related_ids = {t for ts in org_links_out.values() for t in ts} | {t for ss in org_links_in.values() for t in ss}
    org_strategies = {
        s.id: s for s in db.scalars(select(Strategy).where(
            Strategy.id.in_(related_ids), Strategy.scope == StrategyScope.ORGANIZATION,
            Strategy.organization_id == req.organization.id, Strategy.is_archived.is_(False),
        )).all()
    } if related_ids else {}
    all_strategies = {**{s.id: s for s in project_strategies}, **org_strategies}
    versions = _current_versions(db, StrategyVersion, "strategy_id", list(all_strategies))
    future_states = _future_states_in_scope(db, req, req.eligible(db, "future_state"), list(all_strategies))
    fs_by_strategy = _outgoing(db, STRATEGY_TYPE, list(all_strategies), FUTURE_STATE_TYPE)
    req_by_strategy = _outgoing(db, STRATEGY_TYPE, list(all_strategies), REQUIREMENT_TYPE)
    req_by_fs = _outgoing(db, FUTURE_STATE_TYPE, list(future_states), REQUIREMENT_TYPE)
    requirements = _requirements(
        db, {r for rs in (*req_by_strategy.values(), *req_by_fs.values()) for r in rs}, project_ids,
    )
    fs_versions = _current_versions(db, FutureStateVersion, "future_state_id", list(future_states))

    def project_label(project_id: uuid.UUID | None) -> str:
        return names.get(project_id, "") if project_id else "Organisation"

    def fs_node(fs_id: uuid.UUID) -> CascadeNode | None:
        fs = future_states.get(fs_id)
        if fs is None:
            return None
        v = fs_versions[fs.id]
        node = CascadeNode("future_state", fs.id, v.title, label(LIFECYCLE_STATUS_LABEL, v.status.value),
                           project_label(fs.project_id))
        node.children = [_req_node(requirements[r], names) for r in req_by_fs.get(fs.id, []) if r in requirements]
        return node

    def strategy_node(s: Strategy) -> CascadeNode:
        v = versions[s.id]
        kind = "org_strategy" if s.scope is StrategyScope.ORGANIZATION else "strategy"
        node = CascadeNode(kind, s.id, v.title, label(LIFECYCLE_STATUS_LABEL, v.status.value), project_label(s.project_id))
        node.children = [n for n in (fs_node(f) for f in fs_by_strategy.get(s.id, [])) if n]
        node.children += [_req_node(requirements[r], names) for r in req_by_strategy.get(s.id, []) if r in requirements]
        return node

    parent_of: dict[uuid.UUID, uuid.UUID] = {}
    for s in project_strategies:
        for other in (*org_links_out.get(s.id, []), *org_links_in.get(s.id, [])):
            if other in org_strategies:
                parent_of.setdefault(s.id, other)
    children_of: dict[uuid.UUID, list[CascadeNode]] = defaultdict(list)
    tree: list[CascadeNode] = []
    for s in sorted(project_strategies, key=lambda s: versions[s.id].title.lower()):
        node = strategy_node(s)
        if s.id in parent_of:
            children_of[parent_of[s.id]].append(node)
        else:
            tree.append(node)
    org_nodes: list[CascadeNode] = []
    for org_id in sorted(children_of, key=lambda i: versions[i].title.lower()):
        node = strategy_node(org_strategies[org_id])
        node.children = children_of[org_id] + node.children
        org_nodes.append(node)
    tree = org_nodes + tree

    cascade_rows: list[list[str]] = []

    def flatten(node: CascadeNode, depth: int) -> None:
        cascade_rows.append([_KIND_LABEL[node.kind], "— " * depth + node.title, node.status, node.project])
        for child in node.children:
            flatten(child, depth + 1)

    for node in tree:
        flatten(node, 0)

    no_parent = [s for s in project_strategies if s.id not in parent_of]
    no_requirement = [
        s for s in project_strategies
        if versions[s.id].status is StrategyStatus.ACTIVE and not any(r in requirements for r in req_by_strategy.get(s.id, []))
    ]
    fs_strategy_links = _incoming(db, FUTURE_STATE_TYPE, list(future_states), STRATEGY_TYPE)
    visible_strategies = _all_visible_strategy_ids(db, req)
    fs_no_strategy = [
        fs for fs in future_states.values()
        if fs.project_id is not None and not any(sid in visible_strategies for sid in fs_strategy_links.get(fs.id, []))
    ]
    cols = ["Artefact", "Title", "Status", "Project"]
    result.sections = [
        ReportSection("cascade", "Cascade", ["Level", "Title", "Status", "Project"], cascade_rows),
        ReportSection("no_parent", "Project Strategies with no organisation Strategy", cols,
                      [["Strategy", versions[s.id].title, label(LIFECYCLE_STATUS_LABEL, versions[s.id].status.value),
                        project_label(s.project_id)] for s in no_parent], gap=True),
        ReportSection("no_requirement", "Active Strategies with no Requirement", cols,
                      [["Strategy", versions[s.id].title, "Active", project_label(s.project_id)] for s in no_requirement],
                      gap=True),
        ReportSection("no_strategy", "Future States with no Strategy", cols,
                      [["Future State", fs_versions[fs.id].title,
                        label(LIFECYCLE_STATUS_LABEL, fs_versions[fs.id].status.value), project_label(fs.project_id)]
                       for fs in fs_no_strategy], gap=True),
    ]
    result.metrics = [
        ("Project Strategies", len(project_strategies)), ("Strategies with no organisation parent", len(no_parent)),
        ("Active Strategies with no Requirement", len(no_requirement)), ("Future States with no Strategy", len(fs_no_strategy)),
    ]
    result.data = {"tree": tree}
    return result


_KIND_LABEL = {
    "org_strategy": "Organisation Strategy", "strategy": "Project Strategy", "future_state": "Future State",
    "requirement": "Requirement",
}


def _req_node(r: _RequirementRef, names: dict[uuid.UUID, str]) -> CascadeNode:
    return CascadeNode("requirement", r.id, f"{r.code} {r.name}", r.status, names.get(r.project_id, ""))


def _current_versions(db: Session, model: Any, fk: str, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """Maps each artefact id to its current (`valid_to IS NULL`) version row."""
    if not ids:
        return {}
    rows = db.scalars(select(model).where(getattr(model, fk).in_(ids), model.valid_to.is_(None))).all()
    return {getattr(v, fk): v for v in rows}


def _future_states_in_scope(
    db: Session, req: ReportContext, projects: list[Project], strategy_ids: list[uuid.UUID],
) -> dict[uuid.UUID, FutureState]:
    """Non-archived Future States of `projects`, plus org-scoped ones linked
    from any of `strategy_ids`."""
    found = {fs.id: fs for fs in db.scalars(select(FutureState).where(
        FutureState.scope == FutureStateScope.PROJECT, FutureState.project_id.in_([p.id for p in projects]),
        FutureState.is_archived.is_(False),
    )).all()}
    linked = {t for ts in _outgoing(db, STRATEGY_TYPE, strategy_ids, FUTURE_STATE_TYPE).values() for t in ts}
    if linked - set(found):
        for fs in db.scalars(select(FutureState).where(
            FutureState.id.in_(linked - set(found)), FutureState.scope == FutureStateScope.ORGANIZATION,
            FutureState.organization_id == req.organization.id, FutureState.is_archived.is_(False),
        )).all():
            found[fs.id] = fs
    return found


def _all_visible_strategy_ids(db: Session, req: ReportContext) -> set[uuid.UUID]:
    """Ids of every non-archived Strategy the report scope can see: those of
    its projects, plus the organisation's own."""
    ids = db.scalars(select(Strategy.id).where(
        Strategy.is_archived.is_(False),
        (Strategy.project_id.in_([p.id for p in req.projects]))
        | ((Strategy.scope == StrategyScope.ORGANIZATION) & (Strategy.organization_id == req.organization.id)),
    )).all()
    return set(ids)


# --- R3: Pain Point coverage and ageing -------------------------------------------------


def collect_pain_point_coverage(db: Session, req: ReportContext) -> ReportResult:
    """R3 — Pain Point type × status matrix, Accepted Pain Points with no
    motivated Requirement, the Requirements that answer them, and the age of
    each open Pain Point.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"accepted_without_requirement": [...]}` ids.
    """
    projects = req.eligible(db, "pain_point")
    names = _project_names(projects)
    result = _result(req, "r3", "Pain Point coverage and ageing", eligible=len(projects), notes=[
        "Links to Requirements outside the projects you can read in this report are not counted.",
    ])
    pain_points = list(db.scalars(select(PainPoint).where(
        PainPoint.project_id.in_([p.id for p in projects]), PainPoint.is_archived.is_(False),
    ).order_by(PainPoint.date_identified)).all()) if projects else []
    type_names: dict[uuid.UUID, str] = {}
    for pp in pain_points:
        if pp.pain_point_type_id not in type_names:
            ppt = db.get(ProjectPainPointType, pp.pain_point_type_id)
            type_names[pp.pain_point_type_id] = _effective_pain_point_type_name(db, ppt) if ppt else ""
    statuses = list(PainPointStatus)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for pp in pain_points:
        counts[type_names[pp.pain_point_type_id]][pp.status.value] += 1
    matrix_rows = [
        [t, *(str(counts[t][s.value]) for s in statuses), str(sum(counts[t].values()))] for t in sorted(counts)
    ]
    links = _outgoing(db, PAIN_POINT_TYPE, [p.id for p in pain_points], REQUIREMENT_TYPE)
    requirements = _requirements(db, {r for rs in links.values() for r in rs}, set(names))
    accepted = [p for p in pain_points if p.status is PainPointStatus.ACCEPTED]
    uncovered = [p for p in accepted if not any(r in requirements for r in links.get(p.id, []))]
    linked_rows = [
        [pp.title, names[pp.project_id], f"{requirements[r].code} {requirements[r].name}", requirements[r].status]
        for pp in pain_points for r in links.get(pp.id, []) if r in requirements
    ]
    open_pps = [p for p in pain_points if p.status in OPEN_PAIN_POINT_STATUSES]
    age_rows = [
        [pp.title, names[pp.project_id], label(PAIN_POINT_STATUS_LABEL, pp.status.value),
         _fmt_date(pp.date_identified), str((req.today - pp.date_identified).days)]
        for pp in open_pps
    ]
    result.sections = [
        ReportSection("matrix", "Type × status", ["Type", *(label(PAIN_POINT_STATUS_LABEL, s.value) for s in statuses), "Total"], matrix_rows),
        ReportSection("uncovered", "Accepted Pain Points with no Requirement",
                      ["Pain point", "Project", "Identified", "Age (days)"],
                      [[p.title, names[p.project_id], _fmt_date(p.date_identified), str((req.today - p.date_identified).days)]
                       for p in uncovered], gap=True,
                      note="An Accepted Pain Point is a commitment; none of these has a Requirement that addresses it."),
        ReportSection("requirements", "Linked Requirements", ["Pain point", "Project", "Requirement", "Requirement status"], linked_rows),
        ReportSection("ageing", "Age of open Pain Points", ["Pain point", "Project", "Status", "Identified", "Age (days)"], age_rows),
    ]
    result.metrics = [
        ("Pain Points", len(pain_points)), ("Accepted", len(accepted)),
        ("Accepted with no Requirement", len(uncovered)),
        ("Oldest open Pain Point (days)", max((req.today - p.date_identified).days for p in open_pps) if open_pps else 0),
    ]
    result.data = {"accepted_without_requirement": [p.id for p in uncovered]}
    return result


# --- R4: Open Question register -------------------------------------------------------------


@dataclass
class OpenQuestionRow:
    """One open Open Question for the on-screen register."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    question: str
    priority: str
    status: str
    owner: str | None
    due_date: date | None
    days_open: int
    is_overdue: bool


def collect_open_question_register(db: Session, req: ReportContext) -> ReportResult:
    """R4 — unresolved Open Questions by priority and owner, with overdue,
    unowned and days-open figures.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"items": list[OpenQuestionRow]}`.
    """
    projects = req.eligible(db, "open_question")
    names = _project_names(projects)
    result = _result(req, "r4", "Open Question register", eligible=len(projects))
    questions = list(db.scalars(select(OpenQuestion).where(
        OpenQuestion.project_id.in_([p.id for p in projects]), OpenQuestion.is_archived.is_(False),
        OpenQuestion.status.in_(OPEN_QUESTION_OPEN_STATUSES),
    )).all()) if projects else []
    owners = _user_names(db, {q.owner_id for q in questions})
    items = [
        OpenQuestionRow(
            q.id, q.project_id, names[q.project_id], q.question, q.priority.value, q.status.value,
            owners.get(q.owner_id) if q.owner_id else None, q.due_date, (req.today - q.created_at.date()).days,
            q.due_date is not None and q.due_date < req.today,
        )
        for q in questions
    ]
    items.sort(key=lambda i: (_PRIORITY_ORDER.get(i.priority, 9), i.due_date or date.max, i.question.lower()))

    def row(i: OpenQuestionRow) -> list[str]:
        return [
            i.question, i.project_name, label(PRIORITY_LABEL, i.priority), label(OPEN_QUESTION_STATUS_LABEL, i.status),
            i.owner or "Unowned", _fmt_date(i.due_date), "Overdue" if i.is_overdue else "", str(i.days_open),
        ]

    columns = ["Question", "Project", "Priority", "Status", "Owner", "Due", "Overdue", "Days open"]
    by_priority = Counter(i.priority for i in items)
    by_owner = Counter(i.owner or "Unowned" for i in items)
    result.sections = [
        ReportSection("open", "Open Questions", columns, [row(i) for i in items]),
        ReportSection("overdue", "Overdue", columns, [row(i) for i in items if i.is_overdue], gap=True),
        ReportSection("unowned", "Unowned", columns, [row(i) for i in items if i.owner is None], gap=True),
        ReportSection("by_priority", "By priority", ["Priority", "Open"],
                      [[label(PRIORITY_LABEL, p), str(by_priority[p])] for p in ("high", "medium", "low")]),
        ReportSection("by_owner", "By owner", ["Owner", "Open"], [[o, str(n)] for o, n in sorted(by_owner.items())]),
    ]
    result.metrics = [
        ("Open Questions", len(items)), ("Overdue", sum(i.is_overdue for i in items)),
        ("Unowned", sum(i.owner is None for i in items)),
    ]
    result.data = {"items": items}
    return result


# --- R5: Future State roadmap ----------------------------------------------------------------


def collect_future_state_roadmap(db: Session, req: ReportContext) -> ReportResult:
    """R5 — Future States on a timeline by `target_date`, flagging target
    dates already passed while not Active and Future States with no
    `success_measures`.

    Args:
        db: Database session.
        req: The request (project-level).

    Returns:
        The report; `data` is `{"items": [...]}` with the roadmap rows.
    """
    projects = req.eligible(db, "future_state")
    names = _project_names(projects)
    result = _result(req, "r5", "Future State roadmap", eligible=len(projects))
    states = list(db.scalars(select(FutureState).where(
        FutureState.scope == FutureStateScope.PROJECT, FutureState.project_id.in_([p.id for p in projects]),
        FutureState.is_archived.is_(False),
    )).all()) if projects else []
    versions = _current_versions(db, FutureStateVersion, "future_state_id", [s.id for s in states])
    items = []
    for s in states:
        v = versions[s.id]
        if v.status not in ROADMAP_FUTURE_STATE_STATUSES:
            continue
        overdue = v.target_date is not None and v.target_date < req.today and v.status is not FutureStateStatus.ACTIVE
        items.append({
            "id": s.id, "project_id": s.project_id, "project_name": names[s.project_id], "title": v.title,
            "status": v.status.value, "target_date": v.target_date, "is_overdue": overdue,
            "has_success_measures": bool(v.success_measures.strip()),
            "days_to_target": (v.target_date - req.today).days if v.target_date else None,
        })
    items.sort(key=lambda i: (i["target_date"] is None, i["target_date"] or date.max, i["title"].lower()))

    def row(i: dict[str, Any]) -> list[str]:
        return [
            _fmt_date(i["target_date"]) or "No target date", i["title"], i["project_name"],
            label(LIFECYCLE_STATUS_LABEL, i["status"]),
            "" if i["days_to_target"] is None else str(i["days_to_target"]),
            "Target passed" if i["is_overdue"] else "", "" if i["has_success_measures"] else "No success measures",
        ]

    columns = ["Target date", "Future State", "Project", "Status", "Days to target", "Target passed", "Measures"]
    result.sections = [
        ReportSection("roadmap", "Roadmap", columns, [row(i) for i in items],
                      note="Negative days mean the target date has passed. Superseded and Retired Future States are omitted."),
        ReportSection("overdue", "Target date passed, not yet Active", columns, [row(i) for i in items if i["is_overdue"]], gap=True),
        ReportSection("no_measures", "No success measures", columns,
                      [row(i) for i in items if not i["has_success_measures"]], gap=True,
                      note="Without success measures nobody can tell whether the Future State has been reached."),
    ]
    result.metrics = [
        ("Future States on the roadmap", len(items)), ("Target date passed", sum(i["is_overdue"] for i in items)),
        ("Without success measures", sum(not i["has_success_measures"] for i in items)),
    ]
    result.data = {"items": items}
    return result


# --- R6: Guiding Principle usage -----------------------------------------------------------------


def collect_guiding_principle_usage(db: Session, req: ReportContext) -> ReportResult:
    """R6 — Active Guiding Principles with how many Requirements and
    Decisions they are linked to, and those never applied.

    A principle counts as applied when it is linked to at least one readable
    Requirement or Decision. Decision links are resolved through the generic
    artefact-summary hook, so they show as zero until Decision Management
    populates them (Module 4 Phase 7).

    Args:
        db: Database session.
        req: The request (project-level).

    Returns:
        The report; `data` is `{"items": [...]}`.
    """
    projects = req.eligible(db, "guiding_principle")
    names = _project_names(projects)
    project_ids = {p.id for p in req.projects}
    result = _result(req, "r6", "Guiding Principle register and usage", eligible=len(projects), notes=[
        "Counts cover the readable projects in this report only. Decision links appear once Decision Management "
        "links Decisions to principles.",
    ])
    principles = list(db.scalars(select(GuidingPrinciple).where(
        GuidingPrinciple.is_archived.is_(False),
        (GuidingPrinciple.project_id.in_([p.id for p in projects]))
        | ((GuidingPrinciple.scope == GuidingPrincipleScope.ORGANIZATION)
           & (GuidingPrinciple.organization_id == req.organization.id)),
    )).all()) if projects else []
    versions = _current_versions(db, GuidingPrincipleVersion, "guiding_principle_id", [p.id for p in principles])
    active = [p for p in principles if versions[p.id].status is GuidingPrincipleStatus.ACTIVE]
    ids = [p.id for p in active]
    req_links = _outgoing(db, GUIDING_PRINCIPLE_TYPE, ids, REQUIREMENT_TYPE)
    requirements = _requirements(db, {r for rs in req_links.values() for r in rs}, project_ids)
    decision_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for link in [*relationships.get_links_from_many(db, GUIDING_PRINCIPLE_TYPE, ids),
                 *relationships.get_links_to_many(db, GUIDING_PRINCIPLE_TYPE, ids)]:
        if link.target_type == DECISION_TYPE and link.source_type == GUIDING_PRINCIPLE_TYPE:
            decision_ids[link.source_id].add(link.target_id)
        elif link.source_type == DECISION_TYPE and link.target_type == GUIDING_PRINCIPLE_TYPE:
            decision_ids[link.target_id].add(link.source_id)
    owners = _user_names(db, {versions[p.id].owner_id for p in active})
    items = []
    for p in active:
        v = versions[p.id]
        decisions = 0
        for d in decision_ids.get(p.id, set()):
            summary = get_artefact_summary(db, DECISION_TYPE, d)
            decisions += summary is not None and summary.project_id in project_ids and not summary.is_archived
        reqs = sum(1 for r in req_links.get(p.id, []) if r in requirements)
        items.append({
            "id": p.id, "name": v.name, "scope": p.scope.value, "project_name": names.get(p.project_id, "") if p.project_id else "",
            "priority": v.priority.value, "owner": owners.get(v.owner_id) if v.owner_id else None,
            "decisions": decisions, "requirements": reqs, "applied": decisions + reqs > 0,
        })
    items.sort(key=lambda i: (-(i["decisions"] + i["requirements"]), i["name"].lower()))

    def row(i: dict[str, Any]) -> list[str]:
        return [
            i["name"], label(SCOPE_LABEL, i["scope"]), i["project_name"], label(PRIORITY_LABEL, i["priority"]),
            i["owner"] or "", str(i["decisions"]), str(i["requirements"]), "Yes" if i["applied"] else "Never applied",
        ]

    columns = ["Principle", "Scope", "Project", "Priority", "Owner", "Linked Decisions", "Linked Requirements", "Applied"]
    result.sections = [
        ReportSection("register", "Active Guiding Principles", columns, [row(i) for i in items]),
        ReportSection("unused", "Never applied", columns, [row(i) for i in items if not i["applied"]], gap=True,
                      note="Apply these to a Decision or Requirement, or retire them."),
    ]
    result.metrics = [("Active Guiding Principles", len(items)), ("Never applied", sum(not i["applied"] for i in items))]
    result.data = {"items": items}
    return result


# --- R7: Strategy change history ---------------------------------------------------------------------


def _months_ago(today: date, months: int) -> date:
    """`today` shifted back `months` calendar months (day clamped to 28)."""
    index = today.year * 12 + today.month - 1 - months
    return date(index // 12, index % 12 + 1, min(today.day, 28))


def collect_change_history(db: Session, req: ReportContext) -> ReportResult:
    """R7 — every version of the Strategies, Future States and Guiding
    Principles in scope (status moves, change note, author), plus Active
    items not revised within `stale_months`.

    Args:
        db: Database session.
        req: The request (`since`, `stale_months` apply; project-level).

    Returns:
        The report; `data` is `{"items": [...]}` newest first.
    """
    enabled_ids = {p.id for sub in ("strategy", "future_state", "guiding_principle") for p in req.eligible(db, sub)}
    projects = [p for p in req.projects if p.id in enabled_ids]
    names = _project_names(req.projects)
    result = _result(req, "r7", "Strategy change history", eligible=len(projects), notes=[
        f"Active items not revised in {req.params["stale_months"]} months are listed as stale."
        + (f" History from {req.params["since"].isoformat()}." if req.params["since"] else ""),
    ])
    kinds = [
        ("strategy", "Strategy", Strategy, StrategyVersion, "strategy_id", "title", StrategyScope.ORGANIZATION, StrategyStatus.ACTIVE),
        ("future_state", "Future State", FutureState, FutureStateVersion, "future_state_id", "title",
         FutureStateScope.ORGANIZATION, FutureStateStatus.ACTIVE),
        ("guiding_principle", "Guiding Principle", GuidingPrinciple, GuidingPrincipleVersion, "guiding_principle_id", "name",
         GuidingPrincipleScope.ORGANIZATION, GuidingPrincipleStatus.ACTIVE),
    ]
    entries: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    threshold = _months_ago(req.today, req.params["stale_months"])
    for sub, kind_label, root, version_model, fk, title_attr, org_scope, active_status in kinds:
        enabled = [p.id for p in req.eligible(db, sub)]
        if not enabled:
            continue
        artefacts = list(db.scalars(select(root).where(
            root.is_archived.is_(False),
            (root.project_id.in_(enabled)) | ((root.scope == org_scope) & (root.organization_id == req.organization.id)),
        )).all())
        by_artefact: dict[uuid.UUID, list[Any]] = defaultdict(list)
        for v in db.scalars(select(version_model).where(getattr(version_model, fk).in_([a.id for a in artefacts]))
                            .order_by(version_model.version_number)).all() if artefacts else []:
            by_artefact[getattr(v, fk)].append(v)
        authors = _user_names(db, {v.created_by for vs in by_artefact.values() for v in vs})
        for a in artefacts:
            versions = by_artefact.get(a.id, [])
            previous = None
            for v in versions:
                entry = {
                    "kind": kind_label, "artefact_id": a.id, "title": getattr(v, title_attr),
                    "project_name": names.get(a.project_id, "") if a.project_id else "Organisation",
                    "version": v.version_number, "status": v.status.value,
                    "previous_status": previous.status.value if previous else None,
                    "change_note": v.change_note, "author": authors.get(v.created_by, ""), "changed_at": v.created_at,
                }
                previous = v
                if req.params["since"] is None or v.created_at.date() >= req.params["since"]:
                    entries.append(entry)
            if versions and versions[-1].status is active_status and versions[-1].created_at.date() < threshold:
                stale.append({**entry, "changed_at": versions[-1].created_at})
    entries.sort(key=lambda e: (e["changed_at"], e["version"]), reverse=True)
    stale.sort(key=lambda e: e["changed_at"])

    def row(e: dict[str, Any]) -> list[str]:
        move = (
            f"{label(LIFECYCLE_STATUS_LABEL, e['previous_status'])} → {label(LIFECYCLE_STATUS_LABEL, e['status'])}"
            if e["previous_status"] and e["previous_status"] != e["status"] else ""
        )
        return [
            _fmt_date(e["changed_at"]), e["kind"], e["title"], e["project_name"], f"v{e['version']}",
            label(LIFECYCLE_STATUS_LABEL, e["status"]), move, e["change_note"], e["author"],
        ]

    columns = ["Date", "Artefact", "Title", "Project", "Version", "Status", "Status change", "Change note", "Author"]
    result.sections = [
        ReportSection("history", "Version history", columns, [row(e) for e in entries]),
        ReportSection("stale", f"Active, not revised in {req.params["stale_months"]} months", columns, [row(e) for e in stale],
                      gap=True, note="Review each: confirm it still holds, or revise or retire it."),
    ]
    result.metrics = [("Versions in range", len(entries)), ("Active items not revised recently", len(stale))]
    result.data = {"items": entries}
    return result


# --- R8: Summary pack --------------------------------------------------------------------------------------

def collect_summary_pack(db: Session, req: ReportContext) -> ReportResult:
    """R8 — headline counts plus every other report's gap lists in one
    document. At organisation level only the organisation-wide reports are
    included; reports whose sub-component is off everywhere are omitted.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"included": [report keys]}`.
    """
    org_level = req.root_project is None
    parts = [
        spec for spec in REPORT_DEFINITIONS
        if spec.key != "r8" and (spec.org_level or not org_level)
    ]
    results = [r for r in (spec.collector(db, req) for spec in parts) if r.eligible_projects > 0]
    result = _result(req, "r8", "Context & Strategy summary", eligible=len(results), notes=[
        "Headline figures first, then the gaps each report found. Open the individual reports for the full picture.",
    ])
    headline = [[r.title, name, str(value)] for r in results for name, value in r.metrics]
    result.sections = [ReportSection("headline", "Headline figures", ["Report", "Measure", "Value"], headline)]
    for r in results:
        for section in r.sections:
            if section.gap:
                result.sections.append(ReportSection(
                    f"{r.key}_{section.key}", f"{r.title}: {section.title}", section.columns, section.rows,
                    note=section.note, gap=True,
                ))
    result.metrics = [(f"{r.title}: {name}", value) for r in results for name, value in r.metrics]
    result.data = {"included": [r.key for r in results]}
    return result


# --- Declarations ---------------------------------------------------------------------------------------------

_ORG_ROLE = "org_reports_viewer"
_MODEL_KEY = ReportParamDefinition(
    "model_key", "string",
    description="Scoring model: sxf (Severity x Frequency), sxc (Severity x Confidence) or sxfxc; "
                "defaults to the project's configured default.",
)
_ROLLUP = ReportParamDefinition(
    "rollup", "string", default=RollupMethod.WEIGHTED_AVERAGE.value, choices=tuple(m.value for m in RollupMethod),
    description="How per-persona scores combine: weighted_average (default), worst_case or average.",
)
_STALE_MONTHS = ReportParamDefinition(
    "stale_months", "integer", default=6, minimum=1, maximum=120,
    description="Change history only: months without a revision before an Active item is stale (default 6).",
)
_SINCE = ReportParamDefinition(
    "since", "date", description="Change history only: earliest version date to include.",
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "r1", "pain-point-prioritisation", "Pain Point prioritisation",
        "Open Pain Points ranked by the chosen scoring model and persona roll-up, with Blockers always shown.",
        collect_pain_point_prioritisation, subcomponent="pain_point", org_level=True, org_role_key=_ORG_ROLE,
        params=(_MODEL_KEY, _ROLLUP),
    ),
    ReportDefinition(
        "r2", "strategy-cascade", "Strategy cascade and alignment",
        "Organisation Strategy to Requirement, with alignment gaps.", collect_strategy_cascade, subcomponent="strategy",
    ),
    ReportDefinition(
        "r3", "pain-point-coverage", "Pain Point coverage and ageing",
        "Pain Points by type and status, Accepted ones with no Requirement, and age.", collect_pain_point_coverage,
        subcomponent="pain_point", org_level=True, org_role_key=_ORG_ROLE,
    ),
    ReportDefinition(
        "r4", "open-question-register", "Open Question register",
        "Unresolved Open Questions by priority and owner, with overdue and unowned items.",
        collect_open_question_register, subcomponent="open_question", org_level=True, org_role_key=_ORG_ROLE,
    ),
    ReportDefinition(
        "r5", "future-state-roadmap", "Future State roadmap",
        "Future States by target date, with missed targets and missing success measures.",
        collect_future_state_roadmap, subcomponent="future_state",
    ),
    ReportDefinition(
        "r6", "guiding-principle-usage", "Guiding Principle register and usage",
        "Active Guiding Principles and how they are applied.", collect_guiding_principle_usage,
        subcomponent="guiding_principle",
    ),
    ReportDefinition(
        "r7", "strategy-change-history", "Strategy change history",
        "Version history of Strategies, Future States and Guiding Principles, and stale Active items.",
        collect_change_history, params=(_STALE_MONTHS, _SINCE),
    ),
    ReportDefinition(
        "r8", "summary", "Context & Strategy summary", "Headline figures and every report's gap lists in one pack.",
        collect_summary_pack, org_level=True, org_role_key=_ORG_ROLE,
        params=(_MODEL_KEY, _ROLLUP, _STALE_MONTHS, _SINCE),
    ),
    ReportDefinition(
        "r9", "upgrade-drivers", "Upgrade drivers",
        "Intentional tier limitations with per-persona Severity and churn risk.", collect_upgrade_drivers,
        subcomponent="pain_point", org_level=True, org_role_key=_ORG_ROLE, params=(_MODEL_KEY, _ROLLUP),
    ),
)

# Project and organisation routers for the module to include (`router.py`, `project_router.py`).
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
