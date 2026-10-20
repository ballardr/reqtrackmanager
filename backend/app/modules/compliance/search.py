"""
Module: modules.compliance.search

Compliance's contribution to the global search: an `ArtefactSearchProvider` for each of its four
artefact types and the "This standard" search scope.

Responsibilities:
- Declare, per type, the columns the search reads and the free-text fields it may match.
- Resolve the `standard` scope: the projects of the standard's organisation, and for each
  type that belongs to a standard an extra restriction to that standard (evidence is not tied
  to a standard, so it is not searched inside one).

Design decisions:
- A standard's clause is organisation-owned (`project_id` NULL): it is found through any
  project of the standard's organisation where the module is on, the rule the link finder
  uses. A clause, a project's requirement and an action assessment carry no code of their
  own; a clause and a project requirement show their clause reference in the code column.
- The scope's resolution names every project of the standard's organisation; the search
  service keeps only those the caller can read, and answers "not found" when none remain, so a
  standard in another organisation is indistinguishable from a missing one.
- Opt-in fields: the clause text, reasoning, a project's justification and notes, a required
  action's text and an assessment's notes.

Dependencies: this module's models and labels; `models.project`; `modules.registry`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, case, cast, func, literal, null, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.compliance.labels import COMPLIANCE_STATUS_LABEL
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
from app.modules.registry import ArtefactSearchProvider, ScopeResolution, SearchColumns, SearchField, SearchScope

_NO_CODE = literal("", type_=String)
_ASSESSMENT_STATUS_LABEL = {"open": "Open", "completed": "Completed"}


def _clause_code(reference_column):
    """A clause reference (`A.5.15`) standing in for the code the type does not have."""
    return func.coalesce(reference_column, "")


_VERSION_JOIN = ComplianceStandardVersion.id == ComplianceRequirement.standard_version_id
_STANDARD_JOIN = ComplianceStandard.id == ComplianceStandardVersion.standard_id


def _clause_provider() -> ArtefactSearchProvider:
    return ArtefactSearchProvider(
        from_clause=ComplianceRequirement.__table__.join(ComplianceStandardVersion.__table__, _VERSION_JOIN).join(
            ComplianceStandard.__table__, _STANDARD_JOIN
        ),
        columns=SearchColumns(
            id=ComplianceRequirement.id, project_id=cast(null(), PG_UUID(as_uuid=True)),
            code=_clause_code(ComplianceRequirement.reference), title=ComplianceRequirement.name,
            status=ComplianceStandardVersion.status, is_archived=ComplianceStandard.is_archived,
            updated_at=ComplianceRequirement.updated_at, organization_id=ComplianceStandard.organization_id,
        ),
        fields=(
            SearchField("description", "Description", ComplianceRequirement.description),
            SearchField("reasoning", "Reasoning", ComplianceRequirement.reasoning),
        ),
        status_labels={"draft": "Draft", "published": "Published", "retired": "Retired"},
        organization_owned=True,
    )


def _assignment_joined(model_from):
    """`model_from` joined through the project's assignment to its standard version and standard."""
    return model_from.join(
        ComplianceStandardVersion.__table__, ComplianceStandardVersion.id == ProjectCompliance.standard_version_id
    ).join(ComplianceStandard.__table__, ComplianceStandard.id == ComplianceStandardVersion.standard_id)


def _project_requirement_provider() -> ArtefactSearchProvider:
    joined = (
        ProjectComplianceRequirement.__table__
        .join(ComplianceRequirement.__table__, ComplianceRequirement.id == ProjectComplianceRequirement.requirement_id)
        .join(ProjectCompliance.__table__, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id)
    )
    return ArtefactSearchProvider(
        from_clause=_assignment_joined(joined),
        columns=SearchColumns(
            id=ProjectComplianceRequirement.id, project_id=ProjectCompliance.project_id,
            code=_clause_code(ComplianceRequirement.reference), title=ComplianceRequirement.name,
            status=ProjectComplianceRequirement.compliance_status, is_archived=ProjectCompliance.is_archived,
            updated_at=ProjectComplianceRequirement.updated_at,
        ),
        fields=(
            SearchField("description", "Description", ComplianceRequirement.description),
            SearchField("reasoning", "Reasoning", ComplianceRequirement.reasoning),
            SearchField("justification", "Justification", ProjectComplianceRequirement.justification),
            SearchField("notes", "Notes", ProjectComplianceRequirement.notes),
        ),
        status_labels=COMPLIANCE_STATUS_LABEL,
    )


def _assessment_provider() -> ArtefactSearchProvider:
    joined = (
        ComplianceRequiredActionAssessment.__table__
        .join(
            ComplianceRequiredAction.__table__,
            ComplianceRequiredAction.id == ComplianceRequiredActionAssessment.required_action_id,
        )
        .join(
            ProjectComplianceRequirement.__table__,
            ProjectComplianceRequirement.id == ComplianceRequiredActionAssessment.project_compliance_requirement_id,
        )
        .join(ProjectCompliance.__table__, ProjectCompliance.id == ProjectComplianceRequirement.project_compliance_id)
    )
    return ArtefactSearchProvider(
        from_clause=_assignment_joined(joined),
        columns=SearchColumns(
            id=ComplianceRequiredActionAssessment.id, project_id=ProjectCompliance.project_id, code=_NO_CODE,
            title=ComplianceRequiredAction.name,
            status=case((ComplianceRequiredActionAssessment.is_completed.is_(True), "completed"), else_="open"),
            is_archived=ProjectCompliance.is_archived, updated_at=ComplianceRequiredActionAssessment.updated_at,
        ),
        fields=(
            SearchField("description", "Description", ComplianceRequiredAction.description),
            SearchField("notes", "Notes", ComplianceRequiredActionAssessment.notes),
        ),
        status_labels=_ASSESSMENT_STATUS_LABEL,
    )


def _evidence_provider() -> ArtefactSearchProvider:
    return ArtefactSearchProvider(
        from_clause=ComplianceEvidence.__table__,
        columns=SearchColumns(
            id=ComplianceEvidence.id, project_id=ComplianceEvidence.project_id, code=ComplianceEvidence.unique_code,
            title=ComplianceEvidence.title, status=cast(null(), String), is_archived=ComplianceEvidence.is_archived,
            updated_at=ComplianceEvidence.updated_at,
        ),
        fields=(
            SearchField("description", "Description", ComplianceEvidence.description),
            SearchField("notes", "Notes", ComplianceEvidence.notes),
            SearchField("issuing_organisation", "Issuing organisation", ComplianceEvidence.issuing_organisation),
        ),
    )


SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "compliance_requirement": _clause_provider(),
    "compliance_evidence": _evidence_provider(),
    "project_compliance_requirement": _project_requirement_provider(),
    "compliance_required_action_assessment": _assessment_provider(),
}


def _resolve_standard(db: Session, user_id: uuid.UUID, standard_id: uuid.UUID) -> ScopeResolution | None:
    """The projects of the standard's organisation and the per-type restriction to that standard.

    Args:
        db: Active session (read only).
        user_id: The caller (authorisation is the search service's intersection with the projects
            the caller can read; nothing here reveals the standard).
        standard_id: The `ComplianceStandard` id.

    Returns:
        The resolution, or `None` when the standard does not exist.
    """
    organization_id = db.scalar(select(ComplianceStandard.organization_id).where(ComplianceStandard.id == standard_id))
    if organization_id is None:
        return None
    project_ids = tuple(db.scalars(select(Project.id).where(Project.organization_id == organization_id)).all())
    return ScopeResolution(
        project_ids=project_ids,
        restrictions={
            "compliance_requirement": ComplianceStandard.id == standard_id,
            "project_compliance_requirement": ComplianceStandard.id == standard_id,
            "compliance_required_action_assessment": ComplianceStandard.id == standard_id,
        },
    )


SEARCH_SCOPES: dict[str, SearchScope] = {
    "standard": SearchScope(label="This standard", resolve=_resolve_standard, narrowness=200),
}

__all__ = ["SEARCH_PROVIDERS", "SEARCH_SCOPES"]
