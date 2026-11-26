"""
Module: modules.compliance.lifecycles

The approval state of a project's compliance assessment as a `LifecycleDefinition`, so a project can turn off the
submit-for-approval step and an organisation can require it (`services.lifecycles`).

Responsibilities:
- `APPROVAL_TRANSITIONS`: the moves the submit, approve and reject actions make, the one table the routes enforce through
  `services.lifecycles.check_move`.
- Declare the path (not assessed, assessed, pending approval, approved), Pending approval optional and Approved gated:
  turning the submit step off lets an assessed requirement be approved or rejected directly, still behind the approver's
  right and approval separation.
- `_entry_guard`: the checks of the routes, for a skip of steps (an approver for a decision, an officer to submit).

Design decisions:
- Rejected and Requires re-assessment are off the path. The moves into them that the system makes (a fresh assessment
  returns the state to Assessed; a material change moves a pending or approved assessment to Requires re-assessment) are
  not moves the engine checks: an approval must never survive a change of what was approved, whatever a project turned off.
- The assessment's creator for approval separation is the person who last assessed it (`ProjectComplianceRequirement.
  creator_id` names `assessed_by`).

Dependencies: `enums`, `labels`, `approval`, `models`, `services.lifecycles`, `services.rbac`.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.compliance.approval import require_assessment_approver
from app.modules.compliance.enums import ComplianceApprovalState
from app.modules.compliance.labels import COMPLIANCE_APPROVAL_STATE_LABEL
from app.modules.compliance.models import ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, ProjectComplianceRequirement
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum
from app.services.rbac import user_satisfies_module_role

_S = ComplianceApprovalState

APPROVAL_TRANSITIONS: dict[ComplianceApprovalState, set[ComplianceApprovalState]] = {
    _S.NOT_ASSESSED: {_S.ASSESSED},
    _S.ASSESSED: {_S.PENDING_APPROVAL},
    _S.PENDING_APPROVAL: {_S.APPROVED, _S.REJECTED},
    _S.APPROVED: set(),
    _S.REJECTED: set(),
    _S.REQUIRES_REASSESSMENT: set(),
}


def _entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move the assessment into `state`: an approver for a decision, a Compliance Officer
    to submit for approval.

    Raises:
        HTTPException: 403 when the person lacks the right.
    """
    if state in (_S.APPROVED.value, _S.REJECTED.value):
        require_assessment_approver(db, user, project.id)
    elif not user_satisfies_module_role(
        db, user, "compliance", "compliance_officer", organization_id=project.organization_id, project_id=project.id,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")


LIFECYCLES: dict[str, LifecycleDefinition] = {
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT: LifecycleDefinition(
        label="Compliance requirement assessment",
        path=(_S.NOT_ASSESSED.value, _S.ASSESSED.value, _S.PENDING_APPROVAL.value, _S.APPROVED.value),
        transitions=table_from_enum(APPROVAL_TRANSITIONS), labels=COMPLIANCE_APPROVAL_STATE_LABEL,
        optional=(_S.PENDING_APPROVAL.value,), gated=(_S.APPROVED.value,), entry_guard=_entry_guard,
        record_model=ProjectComplianceRequirement,
    ),
}
