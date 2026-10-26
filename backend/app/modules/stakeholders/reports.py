"""
Module: modules.stakeholders.reports

Report data layer for Stakeholders & Personas: five project-level reports, one `collect_*` function
each, returning the core framework's `ReportResult`, plus the `REPORT_DEFINITIONS`
that declare them to the registry. Result shapes, scope (`readable_projects`),
PDF/CSV/Word rendering, routes, MCP tools and the catalogue all live in
`app.services.report_framework`, so this module is declarations and queries.

Reports: S1 Power/interest grid, S2 Persona validation, S3 Need coverage,
S4 Engagement staleness, S5 Engagement & research yield.

Design decisions (all Decided by: Agent unless stated):
- Project-level only, like Risk Management and Decision Management: none of this
  module's organisation roles (Persona/Stakeholder owner, type admin) is a sound
  gate for an aggregate across projects, and engagements are project-scoped.
  "Include child projects" is the way to cover a hierarchy. Each row names its project.
- "Current" Stakeholders and Personas are those the project can see (its own plus the
  organisation's, minus ones hidden from it) that are not archived or Retired. A hidden
  record is never counted, so a report never discloses what the project has hidden.
- Engagement evidence counts only this project's engagements dated today or earlier:
  a shared org Stakeholder never leaks another project's contact history, and a planned
  engagement is not evidence yet. A Persona's engagements are those that cover it by
  link plus those with an anonymous participant tagged with it.
- Research extras (anonymous participants, findings) are counted only in projects where
  that sub-component is on, so switching it off hides them from reports as it does the UI.
- S3 counts a Requirement as traced when a Need gave rise to it, or a Stakeholder or
  Persona provides it or is affected by it. Approving or reviewing a Requirement is not
  where it came from, so those relationships do not count.
- S4 turns a target cadence into an interval of 7, 30, 91 or 365 days. One-off and Ad hoc
  have no interval and are excluded; a Stakeholder with no cadence cannot be judged and is
  listed on its own so the gap is visible rather than silently skipped.
- Group filtering (S1, S4) includes descendant groups; `group_by` adds a branch column
  and orders by it, exactly as the Stakeholder list does.
- Free text is clipped (`_CLIP`) so a long value cannot make a PDF row taller than a page.
- Reports never include Restricted data (contact details are never shown) and are not
  audit-logged (framework rule).

Dependencies: `app.services.report_framework`, `app.modules.registry`, this module's
models, service and group helpers.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.scoring import ScoringLevel
from app.modules.registry import ReportDefinition, ReportParamDefinition, ReportPartDefinition, is_module_enabled_for_project
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders.engagements import (
    COVERS_FORWARD,
    ENGAGEMENT_ARTEFACT_TYPE,
    FINDING_ARTEFACT_TYPE,
    OPEN_QUESTION_TYPE,
    OUTCOME_KINDS,
    PAIN_POINT_TYPE,
    RESEARCH_SUBCOMPONENT,
    anonymous_participant_counts,
    last_engaged_by_stakeholder,
    list_facilitators,
    participant_counts,
)
from app.modules.stakeholders.enums import NeedStatus, PersonaStatus, StakeholderStatus, TargetCadence
from app.modules.stakeholders.labels import (
    ENGAGEMENT_CHANNEL_LABEL,
    GRID_QUADRANT_LABEL,
    RECORD_STATUS_LABEL,
    RECORD_STATUS_TONE,
    REQUIREMENT_STATUS_LABEL,
    TARGET_CADENCE_LABEL,
    label,
)
from app.modules.stakeholders.models import (
    Engagement,
    EngagementAnonymousParticipant,
    Persona,
    PersonaVersion,
    ResearchFinding,
    Stakeholder,
    StakeholderNeed,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.modules.stakeholders.relationships import get_kind
from app.modules.stakeholders.scoring import STAKEHOLDER_SCORING_SCHEME_KEY
from app.modules.stakeholders.service import (
    GIVES_RISE_TO_FORWARD,
    HAS_NEED_FORWARD,
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    REPRESENTS_FORWARD,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    STAKEHOLDERS_MODULE_KEY,
    GridQuadrant,
    grid_quadrant,
    hidden_persona_ids,
    hidden_stakeholder_ids,
    link_type_id_if_exists,
    list_project_needs,
    list_project_visible_personas,
    list_project_visible_stakeholders,
    resolve_persona_weight_with_source,
    suggest_cadence,
)
from app.services.labels import REQUIREMENT_STATUS_TONE
from app.services.principals import principal_labels, principal_ref, principal_text
from app.services.report_framework import (
    ReportContext,
    ReportMetric,
    ReportResult,
    ReportSection,
    build_report_routers,
    tones_by_label,
)

MODULE_KEY = STAKEHOLDERS_MODULE_KEY
PERSONA_SUBCOMPONENT = "persona"
STAKEHOLDER_SUBCOMPONENT = "stakeholder"
NEED_SUBCOMPONENT = "stakeholder_need"

#: Days a Stakeholder may go between engagements, per target cadence (S4). One-off and Ad hoc have none.
CADENCE_INTERVAL_DAYS: dict[TargetCadence, int] = {
    TargetCadence.WEEKLY: 7,
    TargetCadence.MONTHLY: 30,
    TargetCadence.QUARTERLY: 91,
    TargetCadence.YEARLY: 365,
}
QUADRANT_ORDER: tuple[GridQuadrant, ...] = ("manage_closely", "keep_satisfied", "keep_informed", "monitor")
_QUADRANT_NOTE: dict[str, str] = {
    "manage_closely": "High influence and high interest: involve them in decisions.",
    "keep_satisfied": "High influence, lower interest: keep them satisfied without overloading them.",
    "keep_informed": "Lower influence, high interest: keep them informed and listen for feedback.",
    "monitor": "Lower influence and interest: watch for change, minimal effort.",
}
_DAYS_PER_MONTH = 30
_CLIP = 300


# --- Shared helpers ---------------------------------------------------------------


def _fmt_date(value: date | datetime | None) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else (value.isoformat() if value else "")


def _clip(text: str | None, limit: int = _CLIP) -> str:
    """Collapses whitespace and cuts `text` to `limit` characters with an ellipsis."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"




def _result(req: ReportContext, key: str, title: str, *, eligible: int, notes: list[str] | None = None) -> ReportResult:
    """Starts a `ReportResult` with the scope note and any report-specific notes."""
    return ReportResult(
        key=key, title=title, scope_label=req.scope_label, generated_at=datetime.now(UTC),
        notes=[req.scope_note, *(notes or [])], sections=[], eligible_projects=eligible,
    )


def _research_project_ids(db: Session, req: ReportContext) -> set[uuid.UUID]:
    """The in-scope projects with the research extras on."""
    return {p.id for p in req.eligible(db, RESEARCH_SUBCOMPONENT)}


def _weight_text(weight: float | None, source: str) -> str:
    """A Persona's effective weight for a table cell ("Equal" when unset, with where an override came from)."""
    if weight is None:
        return "Equal (not set)"
    text = f"{weight:g}"
    return text + {"project": " (project override)", "ancestor_project": " (parent project override)"}.get(source, "")


def _current_stakeholders(db: Session, project: Project) -> list[tuple[Stakeholder, StakeholderVersion]]:
    """The project's current Stakeholders with their current version: visible (not hidden from the
    project), not archived and not Retired."""
    stakeholders = list_project_visible_stakeholders(db, project)
    if not stakeholders:
        return []
    versions = {
        v.stakeholder_id: v for v in db.scalars(select(StakeholderVersion).where(
            StakeholderVersion.stakeholder_id.in_([s.id for s in stakeholders]), StakeholderVersion.valid_to.is_(None),
        ))
    }
    return [
        (s, versions[s.id]) for s in stakeholders
        if s.id in versions and versions[s.id].status != StakeholderStatus.RETIRED
    ]


def _current_personas(db: Session, project: Project) -> list[tuple[Persona, PersonaVersion]]:
    """The project's current Personas with their current version: visible, not archived and not Retired."""
    personas = list_project_visible_personas(db, project)
    if not personas:
        return []
    versions = {
        v.persona_id: v for v in db.scalars(select(PersonaVersion).where(
            PersonaVersion.persona_id.in_([p.id for p in personas]), PersonaVersion.valid_to.is_(None),
        ))
    }
    return [(p, versions[p.id]) for p in personas if p.id in versions and versions[p.id].status != PersonaStatus.RETIRED]


def _links(
    db: Session, link_type_id: uuid.UUID | None, *, source_type: str, source_ids, target_type: str | None = None,
    target_ids=None,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """`(source_id, target_id)` for the same-project links of one link type from the given sources
    (optionally narrowed to a target type and ids); empty when the link type has never been used."""
    source_ids = list(source_ids)
    if link_type_id is None or not source_ids:
        return []
    query = select(ArtefactLink.source_id, ArtefactLink.target_id).where(
        ArtefactLink.source_type == source_type, ArtefactLink.source_id.in_(source_ids),
        ArtefactLink.link_type_id == link_type_id, ArtefactLink.source_project_id.is_(None),
    )
    if target_type is not None:
        query = query.where(ArtefactLink.target_type == target_type)
    if target_ids is not None:
        query = query.where(ArtefactLink.target_id.in_(list(target_ids)))
    return [(s, t) for s, t in db.execute(query).all()]


# --- Stakeholder rows, shared by S1 and S4 -----------------------------------------


@dataclass
class StakeholderRow:
    """One current Stakeholder of a report, with the derived grid position.

    Attributes:
        stakeholder / version / project: The identity row, its current version and the project it is reported in.
        quadrant: The power/interest quadrant, or `None` when Influence or Interest is unset.
        influence / interest: The level names ("" when unset).
        influence_weight / interest_weight: The levels' weights (0 when unset), for ordering.
        type_name: The effective Stakeholder type name ("" when untyped).
        owner: The owner as text ("" when none).
        groups: The names of the groups they are in, comma separated.
        branch: With `group_by`, the branch names under that root group, comma separated.
        branch_key: Sort key for the branch (unassigned last).
    """

    stakeholder: Stakeholder
    version: StakeholderVersion
    project: Project
    quadrant: GridQuadrant | None
    influence: str
    interest: str
    influence_weight: float
    interest_weight: float
    type_name: str
    owner: str = ""
    groups: str = ""
    branch: str = ""
    branch_key: tuple[int, str] = (1, "")


def _load_stakeholder_rows(db: Session, req: ReportContext, projects: list[Project]) -> list[StakeholderRow]:
    """The current Stakeholders of `projects`, ordered by project then name (by branch first with `group_by`).

    Args:
        db: Database session.
        req: The request (`group_id` keeps a group's members and its descendants'; `group_by` adds a branch column
            under that top-level group).
        projects: The projects to read, already narrowed to those with Stakeholders enabled.

    Returns:
        The rows.

    Raises:
        HTTPException: 404 if `group_id` is not a reachable group in any project; 400 if `group_by` is not a
            reachable top-level group in any project.
    """
    group_id = req.params.get("group_id")
    group_by = req.params.get("group_by")
    org_id = req.organization.id
    levels = {
        lvl.id: lvl for lvl in db.scalars(select(ScoringLevel).where(
            ScoringLevel.organization_id == org_id, ScoringLevel.scheme_key == STAKEHOLDER_SCORING_SCHEME_KEY,
        ))
    }
    quadrants: dict[tuple[uuid.UUID | None, uuid.UUID | None], GridQuadrant | None] = {}
    type_names: dict[tuple[uuid.UUID | None, uuid.UUID | None], str] = {}
    found_group = found_root = False
    rows: list[StakeholderRow] = []
    for project in projects:
        universe = grp.load_groups(db, org_id, project.id) if group_id or group_by else {}
        members: set[uuid.UUID] | None = None
        if group_id is not None and group_id in universe:
            found_group = True
            members = grp.member_ids(db, {group_id, *grp.descendant_ids(universe, group_id)})
        root = universe.get(group_by) if group_by is not None else None
        has_root = root is not None and root.parent_group_id is None
        found_root = found_root or has_root
        if group_id is not None and members is None:
            continue
        pairs = [(s, v) for s, v in _current_stakeholders(db, project) if members is None or s.id in members]
        refs = grp.group_refs(db, [s.id for s, _ in pairs], universe) if universe else {}
        for stakeholder, version in pairs:
            pair = (version.influence_level_id, version.interest_level_id)
            if pair not in quadrants:
                try:
                    quadrants[pair] = grid_quadrant(
                        db, org_id, influence_level_id=pair[0], interest_level_id=pair[1],
                    )
                except ValueError:
                    quadrants[pair] = None  # a level that is no longer valid leaves the stakeholder unscored
            type_key = (version.org_type_id, version.project_type_id)
            if type_key not in type_names:
                type_names[type_key] = STAKEHOLDER_TYPES.display_name(
                    db, org_type_id=version.org_type_id, project_type_id=version.project_type_id,
                ) or ""
            influence = levels.get(version.influence_level_id) if version.influence_level_id else None
            interest = levels.get(version.interest_level_id) if version.interest_level_id else None
            row = StakeholderRow(
                stakeholder, version, project, quadrants[pair],
                influence.name if influence else "", interest.name if interest else "",
                float(influence.weight) if influence else 0.0, float(interest.weight) if interest else 0.0,
                type_names[type_key],
            )
            stakeholder_refs = refs.get(stakeholder.id, [])
            row.groups = ", ".join(r.name for r in stakeholder_refs)
            if has_root:
                row.branch = ", ".join(grp.branch_names(stakeholder_refs, universe, group_by))
                row.branch_key = grp.branch_sort_key(stakeholder_refs, universe, group_by)
            rows.append(row)
    if group_id is not None and not found_group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder group not found.")
    if group_by is not None and not found_root:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "group_by must be a top-level stakeholder group.")
    owners = principal_labels(db, [principal_ref(r.version.owner_type, r.version.owner_id) for r in rows])
    for row in rows:
        row.owner = principal_text(owners.get((row.version.owner_type, row.version.owner_id))) if row.version.owner_id else ""
    rows.sort(key=lambda r: (r.branch_key if group_by else (0, ""), r.project.name.lower(), r.version.name.lower()))
    return rows


def _record_code(req: ReportContext, record: Persona | Stakeholder | StakeholderNeed) -> str:
    """A Persona's, Stakeholder's or Need's code as the report shows it: an organisation-owned record is always
    qualified by the organisation's code, a project-scoped one by the report's rule."""
    if record.project_id is None:
        return req.org_code(record.unique_code)
    return req.code(record.unique_code, record.project_id)


def _cadence_text(version: StakeholderVersion) -> str:
    return label(TARGET_CADENCE_LABEL, version.target_cadence.value if version.target_cadence else None)


# --- S1: Power/interest grid ------------------------------------------------------


def collect_power_interest_grid(db: Session, req: ReportContext) -> ReportResult:
    """S1 — current Stakeholders on Influence × Interest, grouped into the four grid quadrants, with the unscored listed apart.

    Args:
        db: Database session.
        req: The request (`group_id` and `group_by` narrow and arrange it).

    Returns:
        The report; `data` is `{"group_by": bool, "quadrants": {quadrant: [item]}, "unscored": [item]}` where an
        item is `{id, project_id, code, name, influence, interest}`.
    """
    projects = req.eligible(db, STAKEHOLDER_SUBCOMPONENT)
    rows = _load_stakeholder_rows(db, req, projects)
    by_branch = req.params.get("group_by") is not None
    columns = [
        "Code", "Stakeholder", "Project", "Type", "Influence", "Interest", "Owner", "Groups", *(["Branch"] if by_branch else []),
        "Target cadence", "Tags",
    ]
    tags = req.tag_text(db, STAKEHOLDER_ARTEFACT_TYPE, [r.stakeholder.id for r in rows])

    def ordered(subset: list[StakeholderRow]) -> list[StakeholderRow]:
        return sorted(subset, key=lambda r: (
            r.branch_key if by_branch else (0, ""), -r.influence_weight, -r.interest_weight,
            r.project.name.lower(), r.version.name.lower(),
        ))

    def table_row(r: StakeholderRow) -> list[str]:
        return [
            _record_code(req, r.stakeholder), r.version.name, r.project.name, r.type_name, r.influence, r.interest, r.owner,
            r.groups, *([r.branch] if by_branch else []), _cadence_text(r.version), tags.get(r.stakeholder.id, ""),
        ]

    def item(r: StakeholderRow) -> dict:
        return {
            "id": r.stakeholder.id, "project_id": r.project.id, "code": _record_code(req, r.stakeholder),
            "name": r.version.name, "influence": r.influence, "interest": r.interest,
        }

    filters = [f for f in (
        "a group and its sub-groups" if req.params.get("group_id") else "", "arranged by group branch" if by_branch else "",
    ) if f]
    result = _result(req, "s1", "Power/interest grid", eligible=len(projects), notes=[
        "Covers Stakeholders the project can see that are not archived or Retired. A quadrant is High on an axis when its "
        "level is in the upper half of that axis's levels, so Medium counts as High on the default Low/Medium/High levels."
        + (f" Narrowed to {', '.join(filters)}." if filters else ""),
    ])
    placed = {q: ordered([r for r in rows if r.quadrant == q]) for q in QUADRANT_ORDER}
    unscored = ordered([r for r in rows if r.quadrant is None])
    result.sections = [
        ReportSection(q, GRID_QUADRANT_LABEL[q], columns, [table_row(r) for r in placed[q]], note=_QUADRANT_NOTE[q])
        for q in QUADRANT_ORDER
    ] + [ReportSection(
        "unscored", "Not scored", columns, [table_row(r) for r in unscored], gap=True,
        note="Influence or Interest is not set, so these Stakeholders have no place on the grid.",
    )]
    result.metrics = [
        ReportMetric("Stakeholders", len(rows)),
        *(ReportMetric(GRID_QUADRANT_LABEL[q], len(placed[q])) for q in QUADRANT_ORDER),
        ReportMetric("Not scored", len(unscored), gap=True),
    ]
    result.data = {
        "group_by": by_branch,
        "quadrants": {q: [item(r) for r in placed[q]] for q in QUADRANT_ORDER},
        "unscored": [item(r) for r in unscored],
    }
    return result


# --- Persona evidence, shared by S2, S4 and S5 ------------------------------------


@dataclass
class PersonaRow:
    """One current Persona of a report with the evidence behind it.

    Attributes:
        persona / version / project: The identity row, its current version and the project it is reported in.
        weight / weight_source: The effective scoring weight and where it came from (`resolve_persona_weight_with_source`).
        stakeholders: Names of the current Stakeholders that represent it.
        engagement_ids: This project's counted engagements that cover it or have an anonymous participant tagged with it.
        dates: The dates of those engagements.
        anonymous: Anonymous participants tagged with it (0 where the research extras are off).
        findings: Findings of those engagements (0 where the research extras are off).
        owner: The owner as text.
    """

    persona: Persona
    version: PersonaVersion
    project: Project
    weight: float | None
    weight_source: str
    stakeholders: list[str] = field(default_factory=list)
    engagement_ids: set[uuid.UUID] = field(default_factory=set)
    dates: list[date] = field(default_factory=list)
    anonymous: int = 0
    findings: int = 0
    owner: str = ""

    @property
    def is_assumption(self) -> bool:
        """Whether nothing real backs it: no representing Stakeholder and no engagement."""
        return not self.stakeholders and not self.engagement_ids

    @property
    def last_engaged(self) -> date | None:
        return max(self.dates) if self.dates else None


def _load_persona_rows(
    db: Session, req: ReportContext, projects: list[Project], *, since: date | None = None
) -> list[PersonaRow]:
    """The current Personas of `projects` with their evidence, ordered by project then name.

    Args:
        db: Database session.
        req: The request.
        projects: The projects to read, already narrowed to those with Personas enabled.
        since: Only engagements on or after this date count.

    Returns:
        The rows.
    """
    org_id = req.organization.id
    research = _research_project_ids(db, req)
    represents = link_type_id_if_exists(db, org_id, REPRESENTS_FORWARD)
    covers = link_type_id_if_exists(db, org_id, COVERS_FORWARD)
    rows: list[PersonaRow] = []
    for project in projects:
        personas = _current_personas(db, project)
        if not personas:
            continue
        by_id: dict[uuid.UUID, PersonaRow] = {}
        for persona, version in personas:
            weight, source = resolve_persona_weight_with_source(db, project.id, persona.id, version.weight)
            by_id[persona.id] = PersonaRow(persona, version, project, weight, source)
        stakeholder_names = {s.id: v.name for s, v in _current_stakeholders(db, project)}
        for source_id, target_id in _links(
            db, represents, source_type=STAKEHOLDER_ARTEFACT_TYPE, source_ids=stakeholder_names,
            target_type=PERSONA_ARTEFACT_TYPE, target_ids=by_id,
        ):
            by_id[target_id].stakeholders.append(stakeholder_names[source_id])
        query = select(Engagement.id, Engagement.engagement_date).where(
            Engagement.project_id == project.id, Engagement.engagement_date <= req.today,
        )
        if since is not None:
            query = query.where(Engagement.engagement_date >= since)
        dates = {eid: d for eid, d in db.execute(query).all()}
        counted: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for engagement_id, persona_id in _links(
            db, covers, source_type=ENGAGEMENT_ARTEFACT_TYPE, source_ids=dates, target_type=PERSONA_ARTEFACT_TYPE,
            target_ids=by_id,
        ):
            counted[persona_id].add(engagement_id)
        findings_by_engagement: Counter[uuid.UUID] = Counter()
        if project.id in research and dates:
            for engagement_id, persona_id in db.execute(
                select(EngagementAnonymousParticipant.engagement_id, EngagementAnonymousParticipant.persona_id).where(
                    EngagementAnonymousParticipant.engagement_id.in_(list(dates)),
                    EngagementAnonymousParticipant.persona_id.in_(list(by_id)),
                )
            ).all():
                counted[persona_id].add(engagement_id)
                by_id[persona_id].anonymous += 1
            findings_by_engagement.update(dict(db.execute(
                select(ResearchFinding.engagement_id, func.count()).where(ResearchFinding.engagement_id.in_(list(dates)))
                .group_by(ResearchFinding.engagement_id)
            ).all()))
        for persona_id, row in by_id.items():
            row.stakeholders.sort(key=str.lower)
            row.engagement_ids = counted[persona_id]
            row.dates = sorted(dates[eid] for eid in row.engagement_ids)
            row.findings = sum(findings_by_engagement[eid] for eid in row.engagement_ids)
        rows.extend(by_id.values())
    owners = principal_labels(db, [principal_ref(r.version.owner_type, r.version.owner_id) for r in rows])
    for row in rows:
        row.owner = principal_text(owners.get((row.version.owner_type, row.version.owner_id))) if row.version.owner_id else ""
    rows.sort(key=lambda r: (r.project.name.lower(), r.version.name.lower()))
    return rows


# --- S2: Persona validation -------------------------------------------------------


def collect_persona_validation(db: Session, req: ReportContext) -> ReportResult:
    """S2 — the evidence behind each Persona, with Personas resting on nothing flagged as assumptions.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"personas": int, "assumptions": int}`.
    """
    projects = req.eligible(db, PERSONA_SUBCOMPONENT)
    rows = _load_persona_rows(db, req, projects)
    assumptions = [r for r in rows if r.is_assumption]
    columns = [
        "Code", "Persona", "Project", "Status", "Weight", "Linked stakeholders", "Engagements", "Anonymous participants",
        "Findings", "Last engagement", "Evidence", "Tags",
    ]
    tags = req.tag_text(db, PERSONA_ARTEFACT_TYPE, [r.persona.id for r in rows])
    result = _result(req, "s2", "Persona validation", eligible=len(projects), notes=[
        "Covers Personas the project can see that are not archived or Retired. A Persona's engagements are those that cover "
        "it plus those with an anonymous participant tagged with it, dated today or earlier. A Persona with no linked "
        "Stakeholder and no engagement is an assumption, and its weight still shapes Pain Point scoring.",
    ])
    result.sections = [
        ReportSection("evidence", "Evidence by Persona", columns, [
            [
                _record_code(req, r.persona), r.version.name, r.project.name, label(RECORD_STATUS_LABEL, r.version.status.value),
                _weight_text(r.weight, r.weight_source), _clip(", ".join(r.stakeholders)), str(len(r.engagement_ids)),
                str(r.anonymous), str(r.findings), _fmt_date(r.last_engaged), "Assumption" if r.is_assumption else "Evidenced",
                tags.get(r.persona.id, ""),
            ]
            for r in rows
        ]),
        ReportSection(
            "assumptions", "Assumptions", ["Code", "Persona", "Project", "Status", "Weight", "Owner", "Tags"],
            [
                [
                    _record_code(req, r.persona), r.version.name, r.project.name, label(RECORD_STATUS_LABEL, r.version.status.value),
                    _weight_text(r.weight, r.weight_source), r.owner, tags.get(r.persona.id, ""),
                ]
                for r in assumptions
            ],
            gap=True, note="No linked real Stakeholder and no engagement or anonymous participant covers these Personas.",
        ),
    ]
    result.metrics = [
        ReportMetric("Personas", len(rows)),
        ReportMetric("With evidence", len(rows) - len(assumptions)),
        ReportMetric("Assumptions", len(assumptions), gap=True),
    ]
    result.data = {"personas": len(rows), "assumptions": len(assumptions)}
    return result


# --- S3: Need coverage ------------------------------------------------------------


def _links_to(
    db: Session, link_type_id: uuid.UUID | None, *, source_types: list[str], target_type: str, target_ids,
) -> list[tuple[str, uuid.UUID, uuid.UUID]]:
    """`(source_type, source_id, target_id)` for the same-project links of one link type that point at the
    given targets from the given source types; empty when the link type has never been used."""
    target_ids = list(target_ids)
    if link_type_id is None or not target_ids:
        return []
    return [(st, sid, tid) for st, sid, tid in db.execute(
        select(ArtefactLink.source_type, ArtefactLink.source_id, ArtefactLink.target_id).where(
            ArtefactLink.source_type.in_(source_types), ArtefactLink.target_type == target_type,
            ArtefactLink.target_id.in_(target_ids), ArtefactLink.link_type_id == link_type_id,
            ArtefactLink.source_project_id.is_(None),
        )
    ).all()]


def collect_need_coverage(db: Session, req: ReportContext) -> ReportResult:
    """S3 — Needs no Requirement came from, and Requirements that trace to no Need, Stakeholder or Persona.

    Args:
        db: Database session.
        req: The request.

    Returns:
        The report; `data` is `{"needs_without_requirement": int, "requirements_without_origin": int}`.
    """
    projects = req.eligible(db, NEED_SUBCOMPONENT)
    org_id = req.organization.id
    gives = link_type_id_if_exists(db, org_id, GIVES_RISE_TO_FORWARD)
    has_need = link_type_id_if_exists(db, org_id, HAS_NEED_FORWARD)
    origin_types = [
        link_type_id_if_exists(db, org_id, get_kind(key).forward) for key in ("provides_requirement", "affected_by_requirement")
    ]
    need_total = req_total = 0
    need_rows: list[list[str]] = []
    requirement_rows: list[list[str]] = []
    for project in projects:
        needs = list_project_needs(db, project.id)
        need_ids = [n.id for n in needs]
        versions = {
            v.need_id: v for v in db.scalars(select(StakeholderNeedVersion).where(
                StakeholderNeedVersion.need_id.in_(need_ids), StakeholderNeedVersion.valid_to.is_(None),
            ))
        } if needs else {}
        requirements = db.execute(
            select(Requirement.id, Requirement.unique_code, Requirement.project_id, RequirementVersion.name, RequirementVersion.status)
            .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
            .where(Requirement.project_id == project.id, Requirement.is_archived.is_(False), RequirementVersion.valid_to.is_(None))
            .order_by(Requirement.unique_code)
        ).all()
        requirement_ids = {r.id for r in requirements}
        need_to_requirement = _links(
            db, gives, source_type=NEED_ARTEFACT_TYPE, source_ids=need_ids, target_type="requirement", target_ids=requirement_ids,
        )
        covered = {need_id for need_id, _ in need_to_requirement}
        requirement_ids_from_needs = {requirement_id for _, requirement_id in need_to_requirement}
        hidden = {STAKEHOLDER_ARTEFACT_TYPE: hidden_stakeholder_ids(db, project.id), PERSONA_ARTEFACT_TYPE: hidden_persona_ids(db, project.id)}
        traced = set(requirement_ids_from_needs)
        # A hidden Stakeholder or Persona is not counted; an archived or Retired one still originated the Requirement.
        for type_id in origin_types:
            traced |= {
                tid for st, sid, tid in _links_to(
                    db, type_id, source_types=list(hidden), target_type="requirement", target_ids=requirement_ids,
                ) if sid not in hidden[st]
            }
        names = {
            STAKEHOLDER_ARTEFACT_TYPE: {s.id: v.name for s, v in _current_stakeholders(db, project)},
            PERSONA_ARTEFACT_TYPE: {p.id: v.name for p, v in _current_personas(db, project)},
        }
        holders: dict[uuid.UUID, list[str]] = defaultdict(list)
        for st, sid, need_id in _links_to(
            db, has_need, source_types=list(names), target_type=NEED_ARTEFACT_TYPE, target_ids=need_ids,
        ):
            if sid in names[st]:
                holders[need_id].append(names[st][sid])
        active = [n for n in needs if n.id in versions and versions[n.id].status != NeedStatus.RETIRED]
        need_tags = req.tag_text(db, NEED_ARTEFACT_TYPE, [n.id for n in active])
        requirement_tags = req.tag_text(db, "requirement", [r.id for r in requirements])
        need_total += len(active)
        req_total += len(requirements)
        for need in active:
            if need.id not in covered:
                v = versions[need.id]
                need_rows.append([
                    _record_code(req, need), v.name, project.name, label(RECORD_STATUS_LABEL, v.status.value),
                    _clip(", ".join(sorted(holders[need.id], key=str.lower))), _fmt_date(need.created_at),
                    need_tags.get(need.id, ""),
                ])
        requirement_rows += [
            [
                req.code(r.unique_code, r.project_id), r.name, project.name, label(REQUIREMENT_STATUS_LABEL, r.status.value),
                requirement_tags.get(r.id, ""),
            ]
            for r in requirements if r.id not in traced
        ]
    result = _result(req, "s3", "Need coverage", eligible=len(projects), notes=[
        "Interim view until a dedicated requirements-coverage report exists. Covers active Needs (not archived or Retired) and "
        "non-archived Requirements. A Requirement is traced when a Need gave rise to it, or a Stakeholder or Persona provides it "
        "or is affected by it; approving or reviewing it is not where it came from.",
    ])
    result.sections = [
        ReportSection(
            "needs_without_requirement", "Needs with no Requirement",
            ["Code", "Need", "Project", "Status", "Held by", "Created", "Tags"], need_rows, gap=True,
            note="No Requirement has come from these Needs.",
        ),
        ReportSection(
            "requirements_without_origin", "Requirements tracing to no Need, Stakeholder or Persona",
            ["Code", "Requirement", "Project", "Status", "Tags"], requirement_rows, gap=True,
            note="Nobody is recorded as the reason these Requirements exist.",
        ),
    ]
    result.metrics = [
        ReportMetric("Active Needs", need_total),
        ReportMetric("Needs with no Requirement", len(need_rows), gap=True),
        ReportMetric("Requirements", req_total),
        ReportMetric("Requirements with no origin", len(requirement_rows), gap=True),
    ]
    result.data = {"needs_without_requirement": len(need_rows), "requirements_without_origin": len(requirement_rows)}
    return result


# --- S4: Engagement staleness -----------------------------------------------------


def collect_engagement_staleness(db: Session, req: ReportContext) -> ReportResult:
    """S4 — Stakeholders overdue for engagement against their own target cadence, those with no cadence, and Personas not engaged lately.

    Args:
        db: Database session.
        req: The request (`group_id`/`group_by` as S1; `persona_months` is how long a Persona may go unengaged).

    Returns:
        The report; `data` is `{"overdue": int, "no_cadence": int, "personas_not_engaged": int}`.
    """
    months = req.params["persona_months"]
    projects = req.eligible(db, STAKEHOLDER_SUBCOMPONENT)
    rows = _load_stakeholder_rows(db, req, projects)
    last: dict[tuple[uuid.UUID, uuid.UUID], date] = {}
    for project in projects:
        ids = [r.stakeholder.id for r in rows if r.project.id == project.id]
        for sid, when in last_engaged_by_stakeholder(db, project, ids, today=req.today).items():
            last[(project.id, sid)] = when
    by_branch = req.params.get("group_by") is not None
    overdue: list[tuple[StakeholderRow, date | None, int | None]] = []
    no_cadence: list[StakeholderRow] = []
    excluded = tracked = 0
    for r in rows:
        cadence = r.version.target_cadence
        if cadence is None:
            no_cadence.append(r)
            continue
        interval = CADENCE_INTERVAL_DAYS.get(cadence)
        if interval is None:
            excluded += 1
            continue
        tracked += 1
        when = last.get((r.project.id, r.stakeholder.id))
        if when is None:
            overdue.append((r, None, None))
        elif (req.today - when).days > interval:
            overdue.append((r, when, (req.today - when).days - interval))
    overdue.sort(key=lambda t: (
        t[0].branch_key if by_branch else (0, ""), -t[0].influence_weight, -(t[2] if t[2] is not None else 10**6),
        t[0].version.name.lower(),
    ))
    columns = [
        "Code", "Stakeholder", "Project", "Influence", "Interest", "Target cadence", "Last engaged", "Overdue by", "Availability",
        *(["Branch"] if by_branch else []), "Owner", "Tags",
    ]
    stakeholder_tags = req.tag_text(db, STAKEHOLDER_ARTEFACT_TYPE, [r.stakeholder.id for r in rows])
    persona_rows = _load_persona_rows(db, req, req.eligible(db, PERSONA_SUBCOMPONENT))
    cutoff = req.today - timedelta(days=months * _DAYS_PER_MONTH)
    stale_personas = sorted(
        (p for p in persona_rows if p.last_engaged is None or p.last_engaged < cutoff),
        key=lambda p: (-(p.weight or 0.0), p.version.name.lower()),
    )
    persona_tags = req.tag_text(db, PERSONA_ARTEFACT_TYPE, [p.persona.id for p in stale_personas])
    result = _result(req, "s4", "Engagement staleness", eligible=len(projects), notes=[
        "Covers Stakeholders the project can see that are not archived or Retired, against engagements in this project dated "
        "today or earlier. Weekly, monthly, quarterly and yearly cadences allow 7, 30, 91 and 365 days. One-off and Ad hoc "
        "Stakeholders are excluded. Sorted by Influence, then how overdue.",
    ])
    result.sections = [
        ReportSection(
            "overdue", "Overdue for engagement", columns, [
                [
                    _record_code(req, r.stakeholder), r.version.name, r.project.name, r.influence, r.interest,
                    _cadence_text(r.version), _fmt_date(when), "Never engaged" if days is None else f"{days} days",
                    _clip(r.version.availability_constraints), *([r.branch] if by_branch else []), r.owner,
                    stakeholder_tags.get(r.stakeholder.id, ""),
                ]
                for r, when, days in overdue
            ], gap=True,
        ),
        ReportSection(
            "no_cadence", "No target cadence set", [
                "Code", "Stakeholder", "Project", "Influence", "Interest", "Suggested cadence", "Last engaged",
                *(["Branch"] if by_branch else []), "Owner", "Tags",
            ], [
                [
                    _record_code(req, r.stakeholder), r.version.name, r.project.name, r.influence, r.interest,
                    label(TARGET_CADENCE_LABEL, c.value) if (c := suggest_cadence(r.quadrant)) else "",
                    _fmt_date(last.get((r.project.id, r.stakeholder.id))), *([r.branch] if by_branch else []), r.owner,
                    stakeholder_tags.get(r.stakeholder.id, ""),
                ]
                for r in no_cadence
            ], gap=True, note="Without a target cadence staleness cannot be judged. The suggestion follows the grid quadrant.",
        ),
        ReportSection(
            "personas_not_engaged", f"Personas with no engagement in {months} months",
            ["Code", "Persona", "Project", "Weight", "Last engagement", "Owner", "Tags"], [
                [
                    _record_code(req, p.persona), p.version.name, p.project.name, _weight_text(p.weight, p.weight_source),
                    _fmt_date(p.last_engaged), p.owner, persona_tags.get(p.persona.id, ""),
                ]
                for p in stale_personas
            ], gap=True,
            note="Engagements covering the Persona, or with an anonymous participant tagged with it.",
        ),
    ]
    result.metrics = [
        ReportMetric("Stakeholders tracked", tracked),
        ReportMetric("Overdue", len(overdue), gap=True),
        ReportMetric("No target cadence", len(no_cadence), gap=True),
        ReportMetric("One-off / ad hoc (excluded)", excluded),
        ReportMetric("Personas not engaged", len(stale_personas), gap=True),
    ]
    result.data = {"overdue": len(overdue), "no_cadence": len(no_cadence), "personas_not_engaged": len(stale_personas)}
    return result


# --- S5: Engagement & research yield ----------------------------------------------


def collect_engagement_yield(db: Session, req: ReportContext) -> ReportResult:
    """S5 — engagements by channel and Persona, and what they produced: findings, Pain Points, Needs and Open Questions.

    Args:
        db: Database session.
        req: The request (`since` drops engagements dated before it).

    Returns:
        The report; `data` is `{"engagements": int, "without_outcome": int}`.
    """
    since = req.params.get("since")
    projects = [p for p in req.projects if is_module_enabled_for_project(db, p.id, MODULE_KEY)]
    research = _research_project_ids(db, req)
    org_id = req.organization.id
    kind_types = {kind.key: link_type_id_if_exists(db, org_id, kind.forward) for kind in OUTCOME_KINDS}
    engagements: list[tuple[Engagement, Project]] = []
    participants: Counter[uuid.UUID] = Counter()
    anonymous: Counter[uuid.UUID] = Counter()
    finding_engagement: dict[uuid.UUID, uuid.UUID] = {}
    for project in projects:
        query = select(Engagement).where(Engagement.project_id == project.id, Engagement.engagement_date <= req.today)
        if since is not None:
            query = query.where(Engagement.engagement_date >= since)
        found = list(db.scalars(query.order_by(Engagement.engagement_date.desc(), Engagement.created_at.desc())))
        engagements += [(e, project) for e in found]
        ids = [e.id for e in found]
        participants.update(participant_counts(db, project, ids))
        if project.id in research and ids:
            anonymous.update(anonymous_participant_counts(db, ids))
            finding_engagement.update({
                fid: eid for fid, eid in db.execute(
                    select(ResearchFinding.id, ResearchFinding.engagement_id).where(ResearchFinding.engagement_id.in_(ids))
                ).all()
            })
    engagement_ids = [e.id for e, _ in engagements]
    findings_per_engagement = Counter(finding_engagement.values())
    holder_engagement = {**{eid: eid for eid in engagement_ids}, **finding_engagement}
    raised: dict[uuid.UUID, set[tuple[str, uuid.UUID]]] = defaultdict(set)
    answered: set[tuple[str, uuid.UUID]] = set()
    answering: set[uuid.UUID] = set()
    for kind in OUTCOME_KINDS:
        type_id = kind_types[kind.key]
        if type_id is None or not holder_engagement:
            continue
        for source_id, target_type, target_id in db.execute(
            select(ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id).where(
                ArtefactLink.source_type.in_([ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE]),
                ArtefactLink.source_id.in_(list(holder_engagement)), ArtefactLink.link_type_id == type_id,
                ArtefactLink.source_project_id.is_(None),
            )
        ).all():
            if kind.key == "raised":
                raised[holder_engagement[source_id]].add((target_type, target_id))
            else:
                answered.add((target_type, target_id))
                answering.add(holder_engagement[source_id])
    no_outcome = [
        (e, p) for e, p in engagements
        if not raised.get(e.id) and e.id not in answering and findings_per_engagement[e.id] == 0
    ]
    by_channel: Counter[str] = Counter(e.channel.value for e, _ in engagements)
    facilitator_refs = list_facilitators(db, [e.id for e, _ in no_outcome])
    facilitators = principal_labels(db, [ref for refs in facilitator_refs.values() for ref in refs])
    persona_rows = [
        r for r in _load_persona_rows(db, req, req.eligible(db, PERSONA_SUBCOMPONENT), since=since)
        if r.engagement_ids
    ]
    persona_tags = req.tag_text(db, PERSONA_ARTEFACT_TYPE, [r.persona.id for r in persona_rows])
    engagement_tags = req.tag_text(db, ENGAGEMENT_ARTEFACT_TYPE, [e.id for e, _ in no_outcome])
    raised_all = set().union(*raised.values()) if raised else set()
    raised_count = Counter(t for t, _ in raised_all)
    show_research = bool(research)
    result = _result(req, "s5", "Engagement & research yield", eligible=len(projects), notes=[
        "Covers this project's engagements dated today or earlier"
        + (f" and on or after {since.isoformat()}" if since else "") + ". Outcomes are what an engagement, or one of its "
        "findings, raised or answered."
        + ("" if show_research else " The research extras are off, so findings and anonymous participants are not counted."),
    ])
    yield_rows = [
        ["Engagements", str(len(engagements))],
        ["Engagements that produced an outcome", str(len(engagements) - len(no_outcome))],
        ["Pain Points raised", str(raised_count[PAIN_POINT_TYPE])],
        ["Needs raised", str(raised_count[NEED_ARTEFACT_TYPE])],
        ["Open Questions raised", str(raised_count[OPEN_QUESTION_TYPE])],
        ["Open Questions answered", str(len(answered))],
        *([["Findings", str(sum(findings_per_engagement.values()))]] if show_research else []),
    ]
    result.sections = [
        ReportSection("yield", "Yield", ["Measure", "Count"], yield_rows),
        ReportSection(
            "by_channel", "Engagements by channel", ["Channel", "Engagements", "Stakeholder participants", "Anonymous participants"],
            [
                [
                    label(ENGAGEMENT_CHANNEL_LABEL, channel), str(count),
                    str(sum(participants[e.id] for e, _ in engagements if e.channel.value == channel)),
                    str(sum(anonymous[e.id] for e, _ in engagements if e.channel.value == channel)),
                ]
                for channel, count in sorted(by_channel.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        ),
        ReportSection(
            "by_persona", "Engagements by Persona",
            ["Code", "Persona", "Project", "Engagements", "Anonymous participants", "Findings", "Tags"],
            [
                [
                    _record_code(req, r.persona), r.version.name, r.project.name, str(len(r.engagement_ids)), str(r.anonymous),
                    str(r.findings), persona_tags.get(r.persona.id, ""),
                ]
                for r in sorted(persona_rows, key=lambda r: (-len(r.engagement_ids), r.version.name.lower()))
            ],
            note="Engagements that cover the Persona or have an anonymous participant tagged with it.",
        ),
        ReportSection(
            "no_outcome", "Engagements with no outcome", ["Date", "Code", "Engagement", "Project", "Channel", "Facilitators", "Tags"],
            [
                [
                    _fmt_date(e.engagement_date), req.code(e.unique_code, e.project_id), e.title, p.name,
                    label(ENGAGEMENT_CHANNEL_LABEL, e.channel.value),
                    ", ".join(principal_text(facilitators[(ref.type.value, ref.id)]) for ref in facilitator_refs.get(e.id, [])),
                    engagement_tags.get(e.id, ""),
                ]
                for e, p in no_outcome
            ], gap=True,
            note="Nothing was raised or answered, and no finding was recorded: the contact has not reached the backlog.",
        ),
    ]
    result.metrics = [
        ReportMetric("Engagements", len(engagements)),
        ReportMetric("With an outcome", len(engagements) - len(no_outcome)),
        ReportMetric("No outcome", len(no_outcome), gap=True),
        ReportMetric("Pain Points raised", raised_count[PAIN_POINT_TYPE]),
        ReportMetric("Needs raised", raised_count[NEED_ARTEFACT_TYPE]),
        *([ReportMetric("Findings", sum(findings_per_engagement.values()))] if show_research else []),
    ]
    result.data = {"engagements": len(engagements), "without_outcome": len(no_outcome)}
    return result


# --- Declarations -----------------------------------------------------------------

_GROUP_ID = ReportParamDefinition(
    "group_id", "uuid", label="Group", description="Only Stakeholders in this Stakeholder group or its sub-groups.",
)
_GROUP_BY = ReportParamDefinition(
    "group_by", "uuid", label="Group by",
    description="A top-level Stakeholder group: adds a branch column and orders Stakeholders by their branch under it.",
)
_PERSONA_MONTHS = ReportParamDefinition(
    "persona_months", "integer", default=6, minimum=1, maximum=60, label="Persona window (months)",
    description="How many months a Persona may go without an engagement before it is listed (default 6).",
)
_SINCE = ReportParamDefinition(
    "since", "date", label="Since", description="Only engagements on or after this date (YYYY-MM-DD).",
)

# Badge colours for the PDF and Word output: the Status column (Persona, Need and Requirement statuses).
_CELL_TONES = {
    "Status": tones_by_label((RECORD_STATUS_LABEL, RECORD_STATUS_TONE), (REQUIREMENT_STATUS_LABEL, REQUIREMENT_STATUS_TONE)),
}

_REPORTS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        "s1", "power-interest-grid", "Power/interest grid",
        "Stakeholders on Influence × Interest, grouped into Manage closely, Keep satisfied, Keep informed and Monitor, "
        "with unscored Stakeholders listed apart.",
        collect_power_interest_grid, subcomponent=STAKEHOLDER_SUBCOMPONENT, params=(_GROUP_ID, _GROUP_BY),
        parts=(
            ReportPartDefinition("manage_closely", "Manage closely"),
            ReportPartDefinition("keep_satisfied", "Keep satisfied"),
            ReportPartDefinition("keep_informed", "Keep informed"),
            ReportPartDefinition("monitor", "Monitor"),
            ReportPartDefinition("unscored", "Not scored"),
        ),
        record_types=("stakeholder",),
    ),
    ReportDefinition(
        "s2", "persona-validation", "Persona validation",
        "The evidence behind each Persona (linked Stakeholders, engagements, anonymous participants, findings), flagging "
        "Personas that are assumptions together with their weight.",
        collect_persona_validation, subcomponent=PERSONA_SUBCOMPONENT,
        parts=(
            ReportPartDefinition("evidence", "Evidence by Persona"),
            ReportPartDefinition("assumptions", "Assumptions"),
        ),
        record_types=("persona",),
    ),
    ReportDefinition(
        "s3", "need-coverage", "Need coverage",
        "Needs no Requirement came from, and Requirements that trace to no Need, Stakeholder or Persona.",
        collect_need_coverage, subcomponent=NEED_SUBCOMPONENT,
        parts=(
            ReportPartDefinition("needs_without_requirement", "Needs with no Requirement"),
            ReportPartDefinition("requirements_without_origin", "Requirements tracing to no Need, Stakeholder or Persona"),
        ),
        record_types=("stakeholder_need", "requirement"),
    ),
    ReportDefinition(
        "s4", "engagement-staleness", "Engagement staleness",
        "Stakeholders overdue for engagement against their own target cadence (or never engaged), sorted by Influence, "
        "Stakeholders with no cadence, and Personas not engaged lately.",
        collect_engagement_staleness, subcomponent=STAKEHOLDER_SUBCOMPONENT, params=(_GROUP_ID, _GROUP_BY, _PERSONA_MONTHS),
        parts=(
            ReportPartDefinition("overdue", "Overdue for engagement"),
            ReportPartDefinition("no_cadence", "No target cadence set"),
            ReportPartDefinition("personas_not_engaged", "Personas not recently engaged"),
        ),
        record_types=("stakeholder", "persona"),
    ),
    ReportDefinition(
        "s5", "engagement-yield", "Engagement & research yield",
        "Engagements by channel and Persona, and what they produced: findings, Pain Points, Needs and Open Questions "
        "raised, against engagements that produced nothing.",
        collect_engagement_yield, params=(_SINCE,),
        parts=(
            ReportPartDefinition("yield", "Yield"),
            ReportPartDefinition("by_channel", "Engagements by channel"),
            ReportPartDefinition("by_persona", "Engagements by Persona"),
            ReportPartDefinition("no_outcome", "Engagements with no outcome"),
        ),
        record_types=("persona", "engagement"),
    ),
)

REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = tuple(replace(d, cell_tones=_CELL_TONES) for d in _REPORTS)

# Project router for the module to include; there is no organisation-wide variant.
REPORT_ROUTERS = build_report_routers(MODULE_KEY, REPORT_DEFINITIONS)
