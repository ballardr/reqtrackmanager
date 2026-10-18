"""
Module: modules.compliance.summaries

`ArtefactSummaryProvider`s for the four Compliance artefact types (a standard's
clause, evidence, a project's compliance requirement, a required-action
assessment), so core (the artefact link graph and the link finder) can label,
visibility-check and narrow them as link targets without importing the models.

Responsibilities:
- Build an `ArtefactSummary` per record, resolving the owning project through
  the project-compliance assignment where the record has no `project_id` itself.
- Offer a one-query batch lookup scoped to a viewing project
  (`get_many_in_project`).
- Declare each type's browse levels (Standard -> Version -> Requirement for a
  clause; Standard -> Version for a project's requirement or action assessment;
  validity for evidence) and, for the clause, an SQL `filter` (an organisation
  can hold thousands, so it is never loaded whole).

Design decisions:
- Evidence, a project's requirement and a required-action assessment are
  project-owned (`organization_id` stays `None`). A standard's clause
  (`compliance_requirement`) is organisation-owned: `project_id` is `None` and
  it is visible to every project of the standard's organisation (the provider
  applies that rule, the module-enabled gate is the registry's), the shape org
  Personas already use. It is "archived" when its standard is.
- A requirement or assessment is "archived" when its project-compliance
  assignment is.

Dependencies: this module's own models; `modules.registry` for the summary
dataclasses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.compliance.labels import compliance_evidence_validity_state_label
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.service import compute_evidence_validity_state
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider, BrowseLevel

ARTEFACT_TYPE_LABELS: dict[str, str] = {
    "compliance_requirement": "Compliance standard clause",
    "compliance_evidence": "Compliance evidence",
    "project_compliance_requirement": "Compliance requirement",
    "compliance_required_action_assessment": "Compliance action",
}


def _provider(
    id_column: Any, project_id_column: Any, select_columns: Sequence[Any], joins: Callable[[Any], Any],
    to_summary: Callable[[Any], ArtefactSummary], archived_column: Any, browse_levels: tuple[BrowseLevel, ...],
) -> ArtefactSummaryProvider:
    """Builds a provider over one joined query.

    Args:
        id_column: The record's id column.
        project_id_column: The column giving its owning project.
        select_columns: What to select (everything `to_summary` reads).
        joins: Adds the joins the columns need to a `select(...)`.
        to_summary: Maps one result row to an `ArtefactSummary`.
        archived_column: Column that is true when the record is archived.
        browse_levels: The type's finder levels; each reads a facet `to_summary` sets.

    Returns:
        The provider.
    """

    def query(*conditions: Any):
        return joins(select(*select_columns)).where(*conditions)

    def get(db: Session, record_id: UUID) -> ArtefactSummary | None:
        row = db.execute(query(id_column == record_id)).first()
        return None if row is None else to_summary(row)

    def list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
        rows = db.execute(query(project_id_column == project_id, archived_column.is_(False))).all()
        return sorted((to_summary(r) for r in rows), key=lambda s: s.label.lower())

    def get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
        return [to_summary(r) for r in db.execute(query(id_column.in_(ids), project_id_column == project_id)).all()]

    return ArtefactSummaryProvider(
        get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project,
        browse_levels=browse_levels,
    )


def _standard_label(standard: ComplianceStandard) -> str:
    return f"{standard.reference} {standard.name}"


def _version_label(version: ComplianceStandardVersion) -> str:
    """The version as it reads next to a standard ("v2.0"): a bare number gets a "v"."""
    label = version.version_label
    return f"v{label}" if label[:1].isdigit() else label


def _standard_version_facets(standard: ComplianceStandard, version: ComplianceStandardVersion) -> dict[str, tuple[str, str]]:
    return {
        "standard": (str(standard.id), _standard_label(standard)),
        "version": (str(version.id), _version_label(version)),
    }


_STANDARD_VERSION_LEVELS = (BrowseLevel("standard", "Standard"), BrowseLevel("version", "Version"))


def _evidence_summary(row: Any) -> ArtefactSummary:
    evidence = row[0]
    state = compute_evidence_validity_state(evidence).value
    return ArtefactSummary(
        id=evidence.id, project_id=evidence.project_id, label=f"{evidence.unique_code} {evidence.title}", status=None,
        is_archived=evidence.is_archived,
        facets={"validity": (state, compliance_evidence_validity_state_label(state))},
    )


def _requirement_summary(row: Any) -> ArtefactSummary:
    link, requirement, assignment, version, standard = row
    label = f"{requirement.reference} {requirement.name}" if requirement.reference else requirement.name
    return ArtefactSummary(
        id=link.id, project_id=assignment.project_id, label=label, status=link.compliance_status.value,
        is_archived=assignment.is_archived, facets=_standard_version_facets(standard, version),
    )


def _assessment_summary(row: Any) -> ArtefactSummary:
    assessment, action, assignment, version, standard = row
    return ArtefactSummary(
        id=assessment.id, project_id=assignment.project_id, label=action.name,
        status="completed" if assessment.is_completed else "open", is_archived=assignment.is_archived,
        facets=_standard_version_facets(standard, version),
    )


def _assignment_joins(q: Any) -> Any:
    return (
        q.join(ComplianceStandardVersion, ComplianceStandardVersion.id == ProjectCompliance.standard_version_id)
        .join(ComplianceStandard, ComplianceStandard.id == ComplianceStandardVersion.standard_id)
    )


# --- a standard's clause (organisation-owned) --------------------------------------------------


def _clause_label(standard: ComplianceStandard, version: ComplianceStandardVersion, clause: ComplianceRequirement) -> str:
    """`ISO-27001 v2.0 · A.5.15 Logical access control`, so text search finds a clause directly."""
    clause_text = f"{clause.reference} {clause.name}" if clause.reference else clause.name
    return f"{standard.reference} {_version_label(version)} · {clause_text}"


def _clause_summary(row: Any) -> ArtefactSummary:
    clause, version, standard = row
    return ArtefactSummary(
        id=clause.id, project_id=None, organization_id=standard.organization_id,
        label=_clause_label(standard, version, clause), status=version.status.value, is_archived=standard.is_archived,
    )


def _clause_query(*conditions: Any):
    return (
        select(ComplianceRequirement, ComplianceStandardVersion, ComplianceStandard)
        .join(ComplianceStandardVersion, ComplianceStandardVersion.id == ComplianceRequirement.standard_version_id)
        .join(ComplianceStandard, ComplianceStandard.id == ComplianceStandardVersion.standard_id)
        .where(*conditions)
    )


def _project_org_id(db: Session, project_id: UUID) -> UUID | None:
    return db.scalar(select(Project.organization_id).where(Project.id == project_id))


def _clause_options(
    db: Session, project_id: UUID, selected: Mapping[str, str], query: str, level: str
) -> list[tuple[str, str]]:
    """Options of one clause level, always bounded by the project's organisation."""
    org_id = _project_org_id(db, project_id)
    like = f"%{query}%"
    if level == "standard":
        stmt = select(ComplianceStandard).where(
            ComplianceStandard.organization_id == org_id, ComplianceStandard.is_archived.is_(False)
        )
        if query:
            stmt = stmt.where(ComplianceStandard.reference.ilike(like) | ComplianceStandard.name.ilike(like))
        return [(str(st.id), _standard_label(st)) for st in db.scalars(stmt.order_by(ComplianceStandard.reference))]
    standard_id = _uuid(selected.get("standard"))
    if level == "version":
        if standard_id is None:
            return []
        stmt = (
            select(ComplianceStandardVersion).join(ComplianceStandard, ComplianceStandard.id == ComplianceStandardVersion.standard_id)
            .where(ComplianceStandardVersion.standard_id == standard_id, ComplianceStandard.organization_id == org_id)
        )
        if query:
            stmt = stmt.where(ComplianceStandardVersion.version_label.ilike(like))
        return [(str(v.id), _version_label(v)) for v in db.scalars(stmt.order_by(ComplianceStandardVersion.version_number.desc()))]
    version_id = _uuid(selected.get("version"))
    if version_id is None:
        return []
    stmt = (
        select(ComplianceRequirement).join(ComplianceStandardVersion, ComplianceStandardVersion.id == ComplianceRequirement.standard_version_id)
        .join(ComplianceStandard, ComplianceStandard.id == ComplianceStandardVersion.standard_id)
        .where(ComplianceRequirement.standard_version_id == version_id, ComplianceStandard.organization_id == org_id)
    )
    if query:
        stmt = stmt.where(ComplianceRequirement.reference.ilike(like) | ComplianceRequirement.name.ilike(like))
    return [
        (str(c.id), f"{c.reference} {c.name}" if c.reference else c.name)
        for c in db.scalars(stmt.order_by(ComplianceRequirement.sort_order, ComplianceRequirement.reference))
    ]


def _uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


def _clause_get(db: Session, record_id: UUID) -> ArtefactSummary | None:
    row = db.execute(_clause_query(ComplianceRequirement.id == record_id)).first()
    return None if row is None else _clause_summary(row)


def _clause_get_many_in_project(db: Session, project_id: UUID, ids: Sequence[UUID]) -> list[ArtefactSummary]:
    """The clauses among `ids` whose standard belongs to the project's organisation."""
    org_id = _project_org_id(db, project_id)
    rows = db.execute(_clause_query(ComplianceRequirement.id.in_(ids), ComplianceStandard.organization_id == org_id)).all()
    return [_clause_summary(r) for r in rows]


def _clause_list_for_project(db: Session, project_id: UUID) -> list[ArtefactSummary]:
    org_id = _project_org_id(db, project_id)
    rows = db.execute(_clause_query(ComplianceStandard.organization_id == org_id, ComplianceStandard.is_archived.is_(False))).all()
    return sorted((_clause_summary(r) for r in rows), key=lambda s: s.label.lower())


def _clause_filter(
    db: Session, project_id: UUID, selected: Mapping[str, str], query: str, limit: int
) -> list[ArtefactSummary]:
    """Unarchived clauses of the project's organisation, narrowed by the chosen standard / version /
    clause and by text matched against the standard, version, reference and name (at most `limit` + 1)."""
    org_id = _project_org_id(db, project_id)
    conditions: list[Any] = [ComplianceStandard.organization_id == org_id, ComplianceStandard.is_archived.is_(False)]
    if (standard_id := _uuid(selected.get("standard"))) is not None:
        conditions.append(ComplianceStandard.id == standard_id)
    if (version_id := _uuid(selected.get("version"))) is not None:
        conditions.append(ComplianceStandardVersion.id == version_id)
    if (clause_id := _uuid(selected.get("requirement"))) is not None:
        conditions.append(ComplianceRequirement.id == clause_id)
    for word in query.split():
        like = f"%{word}%"
        conditions.append(
            ComplianceStandard.reference.ilike(like) | ComplianceStandard.name.ilike(like)
            | ComplianceStandardVersion.version_label.ilike(like)
            | ComplianceRequirement.reference.ilike(like) | ComplianceRequirement.name.ilike(like)
        )
    stmt = _clause_query(*conditions).order_by(
        ComplianceStandard.reference, ComplianceStandardVersion.version_number, ComplianceRequirement.sort_order
    ).limit(limit + 2)
    return [_clause_summary(r) for r in db.execute(stmt).all()]


def _clause_level(key: str, label: str) -> BrowseLevel:
    return BrowseLevel(key, label, lambda db, project_id, selected, query: _clause_options(db, project_id, selected, query, key))


ARTEFACT_SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    "compliance_requirement": ArtefactSummaryProvider(
        get=_clause_get, list_for_project=_clause_list_for_project, get_many_in_project=_clause_get_many_in_project,
        browse_levels=(_clause_level("standard", "Standard"), _clause_level("version", "Version"), _clause_level("requirement", "Requirement")),
        filter=_clause_filter,
    ),
    "compliance_evidence": _provider(
        ComplianceEvidence.id, ComplianceEvidence.project_id, (ComplianceEvidence,), lambda q: q,
        _evidence_summary, ComplianceEvidence.is_archived, (BrowseLevel("validity", "Validity"),),
    ),
    "project_compliance_requirement": _provider(
        ProjectComplianceRequirement.id, ProjectCompliance.project_id,
        (ProjectComplianceRequirement, ComplianceRequirement, ProjectCompliance, ComplianceStandardVersion, ComplianceStandard),
        lambda q: _assignment_joins(
            q.select_from(ProjectComplianceRequirement)
            .join(ComplianceRequirement, ComplianceRequirement.id == ProjectComplianceRequirement.requirement_id)
            .join(ProjectCompliance, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id)
        ),
        _requirement_summary, ProjectCompliance.is_archived, _STANDARD_VERSION_LEVELS,
    ),
    "compliance_required_action_assessment": _provider(
        ComplianceRequiredActionAssessment.id, ProjectCompliance.project_id,
        (ComplianceRequiredActionAssessment, ComplianceRequiredAction, ProjectCompliance, ComplianceStandardVersion, ComplianceStandard),
        lambda q: _assignment_joins(
            q.select_from(ComplianceRequiredActionAssessment)
            .join(
                ComplianceRequiredAction,
                ComplianceRequiredAction.id == ComplianceRequiredActionAssessment.required_action_id,
            )
            .join(
                ProjectComplianceRequirement,
                ProjectComplianceRequirement.id == ComplianceRequiredActionAssessment.project_compliance_requirement_id,
            )
            .join(ProjectCompliance, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id)
        ),
        _assessment_summary, ProjectCompliance.is_archived, _STANDARD_VERSION_LEVELS,
    ),
}
