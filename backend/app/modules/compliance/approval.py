"""
Module: modules.compliance.approval

The approval gate of a project compliance requirement's assessment, registered with the core approval engine
(`ModuleDefinition.approval_gates`) so the assessment takes part in approval separation and approval policy like every
other gated type.

Responsibilities:
- `ASSESSMENT_APPROVAL_GATES`: the registration (type, label, record context).
- `record_context`: who made the assessment (the person approval must be separate from), the project it is in.
- `require_assessment_approver`: the check the approve route makes, through `services.approval_policy`.

Design decisions:
- The default approver is unchanged: a Compliance Officer, a project manager, an organisation administrator or a server
  administrator (`user_satisfies_module_role`). A role an approval policy names, or the type's `approve_baseline`
  permission, also admits a person; neither removes the default.
- The assessment's "creator" is the person who last changed its compliance status (`assessed_by`). An assessment that
  has none cannot be approved (it must be assessed first), so approval has nobody to be separate from.
- Rejection is a decision that needs the same approver but no separation: a person may reject their own assessment.

Dependencies: `services.approval_policy`, `services.rbac`, `modules.compliance.models`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.compliance.models import (
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.seams import ApprovalGateDefinition
from app.services import approval_policy
from app.services.lookups import project_or_404
from app.services.rbac import user_satisfies_module_role


def record_context(db: Session, record_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None] | None:
    """`ApprovalGateDefinition.record_context` for an assessment.

    Args:
        db: Active session (read only).
        record_id: The project compliance requirement.

    Returns:
        `(assessor, project id, None)`, or `None` when the assessment does not exist or has no assessor.
    """
    pcr = db.get(ProjectComplianceRequirement, record_id)
    if pcr is None or pcr.assessed_by is None:
        return None
    assignment = db.get(ProjectCompliance, pcr.project_compliance_id)
    return None if assignment is None else (pcr.assessed_by, assignment.project_id, None)


ASSESSMENT_APPROVAL_GATES = {
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT: ApprovalGateDefinition(
        label="Compliance requirement assessment", record_context=record_context,
    ),
}


def require_assessment_approver(db: Session, user: User, project_id: uuid.UUID) -> None:
    """Refuses (403) a person who may not approve or reject assessments in the project.

    Args:
        db: Active session (read only).
        user: The person.
        project_id: The project.

    Raises:
        HTTPException: 403 "Insufficient permissions." when the person is not a Compliance Officer (or a higher role) and
            no approval policy or permission admits them.
    """
    project = project_or_404(db, project_id)
    approval_policy.require_approver(
        db, user, artefact_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, organization_id=project.organization_id,
        project_id=project_id, denied="Insufficient permissions.",
        default=user_satisfies_module_role(
            db, user, "compliance", "compliance_officer", organization_id=project.organization_id, project_id=project_id,
        ),
    )
