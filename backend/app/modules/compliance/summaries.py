"""
Module: modules.compliance.summaries

`ArtefactSummaryProvider`s for the three Compliance artefact types (evidence,
a project's compliance requirement, a required-action assessment), so core (the
artefact link graph) can label and visibility-check them as link targets
without importing the models.

Responsibilities:
- Build an `ArtefactSummary` per record, resolving the owning project through
  the project-compliance assignment where the record has no `project_id` itself.
- Offer a one-query batch lookup scoped to a viewing project
  (`get_many_in_project`).

Design decisions:
- All three types are project-owned; none has an org-level form, so there is
  no hiding rule and `organization_id` stays `None`.
- A requirement or assessment is "archived" when its project-compliance
  assignment is.

Dependencies: this module's own models; `modules.registry` for the summary
dataclasses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.registry import ArtefactSummary, ArtefactSummaryProvider

ARTEFACT_TYPE_LABELS: dict[str, str] = {
    "compliance_evidence": "Compliance evidence",
    "project_compliance_requirement": "Compliance requirement",
    "compliance_required_action_assessment": "Compliance action",
}


def _provider(
    id_column: Any, project_id_column: Any, select_columns: Sequence[Any], joins: Callable[[Any], Any],
    to_summary: Callable[[Any], ArtefactSummary], archived_column: Any,
) -> ArtefactSummaryProvider:
    """Builds a provider over one joined query.

    Args:
        id_column: The record's id column.
        project_id_column: The column giving its owning project.
        select_columns: What to select (everything `to_summary` reads).
        joins: Adds the joins the columns need to a `select(...)`.
        to_summary: Maps one result row to an `ArtefactSummary`.
        archived_column: Column that is true when the record is archived.

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

    return ArtefactSummaryProvider(get=get, list_for_project=list_for_project, get_many_in_project=get_many_in_project)


def _evidence_summary(row: Any) -> ArtefactSummary:
    evidence = row[0]
    return ArtefactSummary(
        id=evidence.id, project_id=evidence.project_id, label=evidence.title, status=None,
        is_archived=evidence.is_archived,
    )


def _requirement_summary(row: Any) -> ArtefactSummary:
    link, requirement, assignment = row
    label = f"{requirement.reference} {requirement.name}" if requirement.reference else requirement.name
    return ArtefactSummary(
        id=link.id, project_id=assignment.project_id, label=label, status=link.compliance_status.value,
        is_archived=assignment.is_archived,
    )


def _assessment_summary(row: Any) -> ArtefactSummary:
    assessment, action, assignment = row
    return ArtefactSummary(
        id=assessment.id, project_id=assignment.project_id, label=action.name,
        status="completed" if assessment.is_completed else "open", is_archived=assignment.is_archived,
    )


ARTEFACT_SUMMARY_PROVIDERS: dict[str, ArtefactSummaryProvider] = {
    "compliance_evidence": _provider(
        ComplianceEvidence.id, ComplianceEvidence.project_id, (ComplianceEvidence,), lambda q: q,
        _evidence_summary, ComplianceEvidence.is_archived,
    ),
    "project_compliance_requirement": _provider(
        ProjectComplianceRequirement.id, ProjectCompliance.project_id,
        (ProjectComplianceRequirement, ComplianceRequirement, ProjectCompliance),
        lambda q: q.select_from(ProjectComplianceRequirement)
        .join(ComplianceRequirement, ComplianceRequirement.id == ProjectComplianceRequirement.requirement_id)
        .join(ProjectCompliance, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id),
        _requirement_summary, ProjectCompliance.is_archived,
    ),
    "compliance_required_action_assessment": _provider(
        ComplianceRequiredActionAssessment.id, ProjectCompliance.project_id,
        (ComplianceRequiredActionAssessment, ComplianceRequiredAction, ProjectCompliance),
        lambda q: q.select_from(ComplianceRequiredActionAssessment)
        .join(
            ComplianceRequiredAction,
            ComplianceRequiredAction.id == ComplianceRequiredActionAssessment.required_action_id,
        )
        .join(
            ProjectComplianceRequirement,
            ProjectComplianceRequirement.id == ComplianceRequiredActionAssessment.project_compliance_requirement_id,
        )
        .join(ProjectCompliance, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id),
        _assessment_summary, ProjectCompliance.is_archived,
    ),
}
