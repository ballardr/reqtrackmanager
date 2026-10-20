"""
Module: modules.risk_management.reports

Report data layer for Risk Management: four project-level reports, one `collect_*` function each,
returning the core framework's `ReportResult`, plus the `REPORT_DEFINITIONS`
that declare them to the registry. Result shapes, scope (`readable_projects`),
PDF/CSV/Word rendering, routes, MCP tools and the catalogue all live in
`app.services.report_framework`, so this module is declarations and queries.

Reports: RK1 Risk register, RK2 Risk exposure (inherent against residual),
RK3 Treatment coverage, RK4 Review schedule.

Design decisions (all Decided by: Agent unless stated):
- Project-level only, like Decision Management's reports: the module's only
  organisation role (Risk Type Admin) administers vocabulary, not risks, so it
  is not a sound gate for an aggregate across projects. "Include child
  projects" is the way to cover a hierarchy.
- Ratings are derived per project (`ratings.load_rating_context`), so a child
  project with its own matrix or bands is rated by its own, never its parent's.
  Rating *labels* are shown, not scores, because bands are configurable.
- "Exposed" risks (RK2) are those still carrying live exposure: Identified
  through Transferred. Closed and Rejected risks are history, and Avoided and
  Realised ones have left the exposure picture (one never arose, one already
  has), so counting them would flatter or distort the residual column.
- "Expected to be treated" (RK3) are Assessed, Treatment planned, Treatment in
  progress and Mitigated: the states where something is reducing
  the risk. Accepted and Transferred risks are deliberate non-treatment.
- A treatment link counts toward a verdict bucket by its `RiskTreatmentAssessment`
  row; a link with none is Proposed (the module's own rule). Links whose far end
  the reader cannot see are still counted, never named: the report names only
  the risk, so nothing hidden is disclosed.
- RK4 treats a missing review date on a live, assessed risk as a gap, since a
  risk nobody is due to look at again is exactly what the schedule exists to
  prevent. Identified risks are exempt: they are not assessed yet.
- Free text is clipped (`_CLIP`) so a long statement cannot make a PDF row taller
  than a page; the Risk page holds the full text.
- Reports never include Restricted data and are not audit-logged (framework rule).

Dependencies: `app.services.report_framework`, `app.modules.registry`, this
module's models, ratings and treatment helpers.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.registry import ReportDefinition, ReportParamDefinition
from app.modules.risk_management.enums import RiskStatus, TreatmentAssessmentStatus
from app.modules.risk_management.labels import (
    RISK_STATUS_LABEL,
    TREATMENT_ASSESSMENT_STATUS_LABEL,
    TREATMENT_STRATEGY_LABEL,
    risk_status_label,
)
from app.modules.risk_management.models import Risk, RiskReview, RiskTreatmentAssessment, RiskVersion
from app.modules.risk_management.ratings import RiskRating, load_rating_context, rate_version
from app.modules.risk_management.service import RISK_ARTEFACT_TYPE, RISK_SUBCOMPONENT_KEY, RISK_TYPES
from app.modules.risk_management.treatment import effective_treatment_counts, treatment_link_ids
from app.services.principals import principal_labels, principal_ref, principal_text
from app.services.report_framework import (
    ReportContext,
    ReportMetric,
    ReportResult,
    ReportSection,
    build_report_routers,
)

MODULE_KEY = "risk_management"

_S = RiskStatus
#: Risks still carrying live exposure (RK2).
EXPOSED_STATUSES = frozenset({
    _S.IDENTIFIED, _S.ASSESSED, _S.TREATMENT_PLANNED, _S.TREATMENT_IN_PROGRESS, _S.MITIGATED, _S.ACCEPTED, _S.TRANSFERRED,
})
#: Risks where a treatment is expected to be reducing the risk (RK3).
TREATED_STATUSES = frozenset({_S.ASSESSED, _S.TREATMENT_PLANNED, _S.TREATMENT_IN_PROGRESS, _S.MITIGATED})
#: Risks not yet settled either way (the register's "open" figure).
OPEN_STATUSES = frozenset({_S.IDENTIFIED, _S.ASSESSED, _S.TREATMENT_PLANNED, _S.TREATMENT_IN_PROGRESS})
#: Risks that are still due a review (RK4): not history.
REVIEWABLE_STATUSES = frozenset(set(RiskStatus) - {_S.CLOSED, _S.REJECTED})
NOT_RATED = "Not rated"
TOP_RESIDUAL_ROWS = 20
_CLIP = 300


# --- Shared helpers ---------------------------------------------------------------


def _fmt_date(value: date | datetime | None) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else (value.isoformat() if value else "")


def _clip(text: str | None, limit: int = _CLIP) -> str:
    """Collapses whitespace and cuts `text` to `limit` characters with an ellipsis."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _label(rating: RiskRating | None) -> str:
    return (rating.label or NOT_RATED) if rating is not None else NOT_RATED


@dataclass
class RiskRow:
    """One risk of a report, with everything the collectors need.

    Attributes:
        risk / version / project: The identity row, its current version and its project.
        inherent / residual: The derived ratings (`None` when not scored).
        type_name: The risk's effective type name ("" when untyped).
        owner: The owner as text (`principal_text`: a user's name, or a group's name with its kind; "" when none).
        effective: How many treatment links are assessed effective.
        tags: The risk's tags as comma-separated text ("" when none).
    """

    risk: Risk
    version: RiskVersion
    project: Project
    inherent: RiskRating | None
    residual: RiskRating | None
    type_name: str
    owner: str
    effective: int
    tags: str = ""


def _load_rows(db: Session, req: ReportContext, *, include_archived: bool = False) -> tuple[list[Project], list[RiskRow]]:
    """The in-scope projects with Risks enabled, and their risks as `RiskRow`s.

    Args:
        db: Database session.
        req: The request context.
        include_archived: Whether archived risks are included.

    Returns:
        `(eligible projects, rows ordered by project name then code)`.
    """
    projects = req.eligible(db, RISK_SUBCOMPONENT_KEY)
    if not projects:
        return [], []
    by_id = {p.id: p for p in projects}
    query = select(Risk, RiskVersion).join(RiskVersion, RiskVersion.risk_id == Risk.id).where(
        Risk.project_id.in_(by_id), RiskVersion.valid_to.is_(None),
    )
    if not include_archived:
        query = query.where(Risk.is_archived.is_(False))
    pairs = db.execute(query).all()
    owners = principal_labels(db, [principal_ref(v.owner_type, v.owner_id) for _, v in pairs])
    effective = effective_treatment_counts(db, [r.id for r, _ in pairs])
    tags = req.tag_text(db, RISK_ARTEFACT_TYPE, [r.id for r, _ in pairs])
    contexts = {p.id: load_rating_context(db, p) for p in projects}
    type_names: dict[uuid.UUID, str] = {}
    rows: list[RiskRow] = []
    for risk, version in pairs:
        if version.project_type_id is not None and version.project_type_id not in type_names:
            type_names[version.project_type_id] = RISK_TYPES.display_name(
                db, org_type_id=None, project_type_id=version.project_type_id,
            ) or ""
        inherent, residual = rate_version(contexts[risk.project_id], version)
        rows.append(RiskRow(
            risk, version, by_id[risk.project_id], inherent, residual,
            type_names.get(version.project_type_id, "") if version.project_type_id else "",
            principal_text(owners.get((version.owner_type, version.owner_id))) if version.owner_id else "",
            effective.get(risk.id, 0), tags.get(risk.id, ""),
        ))
    rows.sort(key=lambda r: (r.project.name.lower(), r.risk.unique_code))
    return projects, rows


def _result(req: ReportContext, key: str, title: str, *, eligible: int, notes: list[str] | None = None) -> ReportResult:
    """Starts a `ReportResult` with the scope note and any report-specific notes."""
    return ReportResult(
        key=key, title=title, scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, *(notes or [])], sections=[], eligible_projects=eligible,
    )


def _by_rating(ratings: list[RiskRating | None]) -> list[tuple[str, int]]:
    """Counts ratings by label, worst first (by the highest score seen under a label), "Not rated" last."""
    counts: Counter[str] = Counter()
    worst: dict[str, float] = {}
    for rating in ratings:
        label = _label(rating)
        counts[label] += 1
        if rating is not None:
            worst[label] = max(worst.get(label, 0.0), rating.normalised)
    ordered = sorted((lbl for lbl in counts if lbl != NOT_RATED), key=lambda lbl: -worst.get(lbl, 0.0))
    return [(lbl, counts[lbl]) for lbl in [*ordered, *([NOT_RATED] if NOT_RATED in counts else [])]]


# --- RK1: Risk register -----------------------------------------------------------


def collect_risk_register(db: Session, req: ReportContext) -> ReportResult:
    """RK1 — every Risk with its type, status, owner, strategy, ratings and next review.

    Args:
        db: Database session.
        req: The request (`status`, `risk_type` and `include_archived` narrow it).

    Returns:
        The report; `data` is `{"items": [{id, project_id, code, title}]}`.
    """
    status_filter = req.params.get("status")
    wanted_type = (req.params.get("risk_type") or "").strip().lower()
    include_archived = bool(req.params.get("include_archived"))
    projects, rows = _load_rows(db, req, include_archived=include_archived)
    rows = [
        r for r in rows
        if (not status_filter or r.version.status.value == status_filter) and (not wanted_type or r.type_name.lower() == wanted_type)
    ]
    filters = [
        f for f in (
            f"status {risk_status_label(status_filter)}" if status_filter else "",
            f"type {req.params['risk_type']}" if wanted_type else "",
            "archived included" if include_archived else "",
        ) if f
    ]
    result = _result(req, "rk1", "Risk register", eligible=len(projects), notes=[
        f"Filters: {', '.join(filters)}." if filters else "No filters: every non-archived Risk is listed.",
        "Ratings are derived from each project's current scoring matrix; they are not stored on the Risk.",
    ])
    columns = [
        "Code", "Title", "Project", "Type", "Status", "Owner", "Strategy", "Inherent", "Residual", "Effective treatments",
        "Next review", "Tags",
    ]
    result.sections = [
        ReportSection("register", "Risks", columns, [
            [
                req.code(r.risk.unique_code, r.project.id), r.version.title, r.project.name, r.type_name, risk_status_label(r.version.status.value),
                r.owner, TREATMENT_STRATEGY_LABEL.get(r.version.treatment_strategy.value, "") if r.version.treatment_strategy else "",
                _label(r.inherent), _label(r.residual), str(r.effective), _fmt_date(r.version.review_date),
                r.tags,
            ]
            for r in rows
        ]),
        ReportSection(
            "by_status", "By status", ["Status", "Risks"],
            [[label, str(sum(r.version.status.value == value for r in rows))] for value, label in RISK_STATUS_LABEL.items()],
        ),
        ReportSection("by_inherent", "By inherent rating", ["Rating", "Risks"], [[lbl, str(n)] for lbl, n in _by_rating([r.inherent for r in rows])]),
        ReportSection("by_residual", "By residual rating", ["Rating", "Risks"], [[lbl, str(n)] for lbl, n in _by_rating([r.residual for r in rows])]),
    ]
    overdue = sum(_is_overdue(r, req.today) for r in rows)
    result.metrics = [
        ReportMetric("Risks", len(rows)),
        ReportMetric("Open", sum(r.version.status in OPEN_STATUSES for r in rows)),
        ReportMetric("Mitigated", sum(r.version.status == RiskStatus.MITIGATED for r in rows)),
        ReportMetric("Accepted", sum(r.version.status == RiskStatus.ACCEPTED for r in rows)),
        ReportMetric("Realised", sum(r.version.status == RiskStatus.REALISED for r in rows)),
        ReportMetric("Review overdue", overdue, gap=True),
    ]
    result.data = {"items": [
        {"id": r.risk.id, "project_id": r.project.id, "code": req.code(r.risk.unique_code, r.project.id), "title": r.version.title} for r in rows
    ]}
    return result


def _is_overdue(row: RiskRow, today: date) -> bool:
    """Whether the risk's review date has passed and it is still due a review."""
    return row.version.review_date is not None and row.version.review_date < today and row.version.status in REVIEWABLE_STATUSES


# --- RK2: Risk exposure -----------------------------------------------------------


def collect_risk_exposure(db: Session, req: ReportContext) -> ReportResult:
    """RK2 — how treatment has moved the exposure: inherent against residual rating, plus the worst remaining risks.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"exposed": int, "not_rated": int}`.
    """
    projects, rows = _load_rows(db, req)
    exposed = [r for r in rows if r.version.status in EXPOSED_STATUSES]
    result = _result(req, "rk2", "Risk exposure", eligible=len(projects), notes=[
        "Covers Risks from Identified to Transferred. Closed, Rejected, Avoided and Realised Risks are not counted: "
        "they are history or no longer exposure. Residual ratings are set by a person and are not recalculated "
        "when treatments change.",
    ])
    inherent = dict(_by_rating([r.inherent for r in exposed]))
    residual = dict(_by_rating([r.residual for r in exposed]))
    labels = [lbl for lbl in dict.fromkeys([*inherent, *residual]) if lbl != NOT_RATED]
    labels += [NOT_RATED] if NOT_RATED in inherent or NOT_RATED in residual else []
    unrated = [r for r in exposed if r.inherent is None]
    ranked = sorted(
        (r for r in exposed if r.residual is not None),
        key=lambda r: (-r.residual.normalised, -(r.inherent.normalised if r.inherent else 0.0), r.risk.unique_code),
    )[:TOP_RESIDUAL_ROWS]
    columns = ["Code", "Title", "Project", "Status", "Owner", "Inherent", "Residual", "Tags"]

    def row(r: RiskRow) -> list[str]:
        return [
            req.code(r.risk.unique_code, r.project.id), r.version.title, r.project.name, risk_status_label(r.version.status.value), r.owner,
            _label(r.inherent), _label(r.residual), r.tags,
        ]

    result.sections = [
        ReportSection(
            "by_rating", "Inherent against residual", ["Rating", "Inherent", "Residual"],
            [[lbl, str(inherent.get(lbl, 0)), str(residual.get(lbl, 0))] for lbl in labels],
        ),
        ReportSection("top_residual", f"Highest residual risks (top {TOP_RESIDUAL_ROWS})", columns, [row(r) for r in ranked]),
        ReportSection(
            "not_rated", "Not rated", columns, [row(r) for r in unrated], gap=True,
            note="Exposed Risks with no inherent rating, so they cannot be placed on the matrix.",
        ),
    ]
    result.metrics = [
        ReportMetric("Exposed Risks", len(exposed)),
        ReportMetric("Treated (residual below inherent)", sum(
            1 for r in exposed if r.inherent and r.residual and r.residual.normalised < r.inherent.normalised
        )),
        ReportMetric("Not rated", len(unrated), gap=True),
    ]
    result.data = {"exposed": len(exposed), "not_rated": len(unrated)}
    return result


# --- RK3: Treatment coverage ------------------------------------------------------


def _verdict_counts(db: Session, rows: list[RiskRow]) -> dict[uuid.UUID, Counter[TreatmentAssessmentStatus]]:
    """Per risk, how many treatment links hold each verdict (a link with no verdict is Proposed)."""
    out: dict[uuid.UUID, Counter[TreatmentAssessmentStatus]] = {}
    for r in rows:
        link_ids = treatment_link_ids(db, r.project, r.risk.id)
        verdicts = {
            a.link_id: a.status
            for a in db.scalars(select(RiskTreatmentAssessment).where(RiskTreatmentAssessment.risk_id == r.risk.id)).all()
            if a.link_id in link_ids
        }
        out[r.risk.id] = Counter(verdicts.get(link_id, TreatmentAssessmentStatus.PROPOSED) for link_id in link_ids)
    return out


def collect_treatment_coverage(db: Session, req: ReportContext) -> ReportResult:
    """RK3 — which Risks expected to be treated have no effective treatment, and which rest on a verdict to reassess.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"untreated": int, "needs_reassessment": int}`.
    """
    projects, rows = _load_rows(db, req)
    expected = [r for r in rows if r.version.status in TREATED_STATUSES]
    verdicts = _verdict_counts(db, expected)
    columns = [
        "Code", "Title", "Project", "Status", "Owner", "Inherent", "Treatment links", "Effective", "Proposed", "Ineffective",
        "Needs reassessment", "Tags",
    ]

    def row(r: RiskRow) -> list[str]:
        c = verdicts[r.risk.id]
        return [
            req.code(r.risk.unique_code, r.project.id), r.version.title, r.project.name, risk_status_label(r.version.status.value), r.owner,
            _label(r.inherent), str(sum(c.values())), str(c[TreatmentAssessmentStatus.EFFECTIVE]),
            str(c[TreatmentAssessmentStatus.PROPOSED]), str(c[TreatmentAssessmentStatus.INEFFECTIVE]),
            str(c[TreatmentAssessmentStatus.NEEDS_REASSESSMENT]), r.tags,
        ]

    untreated = [r for r in expected if verdicts[r.risk.id][TreatmentAssessmentStatus.EFFECTIVE] == 0]
    stale = [r for r in expected if verdicts[r.risk.id][TreatmentAssessmentStatus.NEEDS_REASSESSMENT] > 0]
    totals = Counter[TreatmentAssessmentStatus]()
    for r in expected:
        totals.update(verdicts[r.risk.id])
    result = _result(req, "rk3", "Treatment coverage", eligible=len(projects), notes=[
        "Covers Assessed, Treatment planned, Treatment in progress and Mitigated Risks. A Risk counts as treated only "
        "through an Effective verdict; a link with no verdict is Proposed. Accepted and Transferred Risks are not listed: "
        "not treating them is the decision.",
    ])
    result.sections = [
        ReportSection("untreated", "No effective treatment", columns, [row(r) for r in untreated], gap=True),
        ReportSection(
            "needs_reassessment", "Resting on a verdict to reassess", columns, [row(r) for r in stale], gap=True,
            note="A linked Requirement changed after its treatment was judged Effective; a person must reassess it.",
        ),
        ReportSection(
            "verdicts", "Treatment links by verdict", ["Verdict", "Links"],
            [[label, str(totals[TreatmentAssessmentStatus(value)])] for value, label in TREATMENT_ASSESSMENT_STATUS_LABEL.items()],
        ),
    ]
    result.metrics = [
        ReportMetric("Risks expected to be treated", len(expected)),
        ReportMetric("With an effective treatment", len(expected) - len(untreated)),
        ReportMetric("No effective treatment", len(untreated), gap=True),
        ReportMetric("Needing reassessment", len(stale), gap=True),
    ]
    result.data = {"untreated": len(untreated), "needs_reassessment": len(stale)}
    return result


# --- RK4: Review schedule ---------------------------------------------------------


def _last_reviews(db: Session, risk_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """When each risk was last reviewed (risks never reviewed are absent)."""
    if not risk_ids:
        return {}
    rows = db.execute(
        select(RiskReview.risk_id, RiskReview.reviewed_at).where(RiskReview.risk_id.in_(risk_ids)).order_by(RiskReview.reviewed_at)
    ).all()
    return {risk_id: reviewed_at for risk_id, reviewed_at in rows}


def collect_review_schedule(db: Session, req: ReportContext) -> ReportResult:
    """RK4 — overdue and upcoming reviews, and assessed Risks nobody is due to review.

    Args:
        db: Database session.
        req: The request (`due_within_days` is how far ahead "due soon" looks).

    Returns:
        The report; `data` is `{"overdue": int, "due_soon": int, "unscheduled": int}`.
    """
    horizon = req.params["due_within_days"]
    projects, rows = _load_rows(db, req)
    reviewable = [r for r in rows if r.version.status in REVIEWABLE_STATUSES]
    last = _last_reviews(db, [r.risk.id for r in reviewable])
    overdue = sorted((r for r in reviewable if _is_overdue(r, req.today)), key=lambda r: (r.version.review_date, r.risk.unique_code))
    soon = sorted(
        (r for r in reviewable if r.version.review_date is not None
         and req.today <= r.version.review_date <= req.today + timedelta(days=horizon)),
        key=lambda r: (r.version.review_date, r.risk.unique_code),
    )
    unscheduled = [r for r in reviewable if r.version.review_date is None and r.version.status != RiskStatus.IDENTIFIED]
    columns = ["Code", "Title", "Project", "Status", "Owner", "Review date", "Days", "Last reviewed", "Tags"]

    def row(r: RiskRow) -> list[str]:
        days = (r.version.review_date - req.today).days if r.version.review_date else None
        return [
            req.code(r.risk.unique_code, r.project.id), r.version.title, r.project.name, risk_status_label(r.version.status.value), r.owner,
            _fmt_date(r.version.review_date), "" if days is None else (f"{-days} overdue" if days < 0 else str(days)),
            _fmt_date(last.get(r.risk.id)), r.tags,
        ]

    result = _result(req, "rk4", "Review schedule", eligible=len(projects), notes=[
        f"Covers every Risk that is not Closed or Rejected. Due soon looks {horizon} days ahead. A Risk that has been "
        "assessed but has no review date is listed because nobody is due to look at it again.",
    ])
    result.sections = [
        ReportSection("overdue", "Overdue reviews", columns, [row(r) for r in overdue], gap=True),
        ReportSection("due_soon", f"Due in the next {horizon} days", columns, [row(r) for r in soon]),
        ReportSection("unscheduled", "No review scheduled", columns, [row(r) for r in unscheduled], gap=True),
    ]
    result.metrics = [
        ReportMetric("Risks under review", len(reviewable)),
        ReportMetric("Overdue", len(overdue), gap=True),
        ReportMetric("Due soon", len(soon)),
        ReportMetric("No review scheduled", len(unscheduled), gap=True),
    ]
    result.data = {"overdue": len(overdue), "due_soon": len(soon), "unscheduled": len(unscheduled)}
    return result


# --- Declarations -----------------------------------------------------------------

_STATUS = ReportParamDefinition(
    "status", "string", choices=tuple(RISK_STATUS_LABEL), choice_labels=dict(RISK_STATUS_LABEL), label="Status",
    description="Only Risks in this status.",
)
_RISK_TYPE = ReportParamDefinition(
    "risk_type", "string", label="Risk type", description="Only Risks of the type with this name (case-insensitive).",
)
_INCLUDE_ARCHIVED = ReportParamDefinition(
    "include_archived", "boolean", default=False, label="Include archived", description="Also list archived Risks.",
)
_DUE_WITHIN = ReportParamDefinition(
    "due_within_days", "integer", default=30, minimum=1, maximum=365, label="Due within (days)",
    description="How many days ahead a review counts as due soon (default 30).",
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "rk1", "risk-register", "Risk register",
        "Every Risk with its type, status, owner, strategy, inherent and residual rating, and next review.",
        collect_risk_register, subcomponent=RISK_SUBCOMPONENT_KEY, params=(_STATUS, _RISK_TYPE, _INCLUDE_ARCHIVED),
        record_types=("risk",),
    ),
    ReportDefinition(
        "rk2", "risk-exposure", "Risk exposure",
        "Inherent against residual rating across live Risks, the highest remaining Risks, and Risks with no rating.",
        collect_risk_exposure, subcomponent=RISK_SUBCOMPONENT_KEY,
        record_types=("risk",),
    ),
    ReportDefinition(
        "rk3", "treatment-coverage", "Treatment coverage",
        "Risks expected to be treated that have no effective treatment, or rest on a verdict to reassess.",
        collect_treatment_coverage, subcomponent=RISK_SUBCOMPONENT_KEY,
        record_types=("risk",),
    ),
    ReportDefinition(
        "rk4", "review-schedule", "Review schedule",
        "Overdue and upcoming Risk reviews, and assessed Risks with no review scheduled.",
        collect_review_schedule, subcomponent=RISK_SUBCOMPONENT_KEY, params=(_DUE_WITHIN,),
        record_types=("risk",),
    ),
)

# Project router for the module to include; there is no organisation-wide variant.
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
