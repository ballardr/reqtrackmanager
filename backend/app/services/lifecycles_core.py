"""
Module: services.lifecycles_core

The state paths of the core record types that are not owned by a module, registered with
`modules.registry.get_lifecycles` (module key `""`) beside each module's own `lifecycles`.

Responsibilities:
- Describe the Requirement and the Change Request state paths as `LifecycleDefinition`s: the legal moves of today's
  endpoints, which states a project may turn off, which states are gated and who may enter each step.

Design decisions:
- The transition tables record the moves the endpoints allow now (`routers.requirements`, `routers.change_requests`), so a
  project that configures nothing sees no difference. A definition registers a type with the engine; it does not by
  itself change what an endpoint accepts. A type's own move endpoint enforces the table by calling
  `services.lifecycles.check_move`.
- Requirement: Draft, Reviewed, Approved. Reviewed is optional (a draft may go straight to Approved). Approved is gated
  (the project manager role and approval separation) and locks the content; changes then go through a change request, so
  Approved has no outgoing move. Archived is the status an edit can set on an unlocked requirement; it is off the path.
  The archive flag (`Requirement.is_archived`) is a separate soft delete and not a state.
- Change Request: Draft, Submitted, Approved, with Rejected and Withdrawn off the path. No state is optional: a decision
  is made only on a submitted request. In review is a state a request may be in (a decision accepts it) but no endpoint
  moves a request into it, so the table has no move to it.
- A step's entry check mirrors the right the endpoint demands, so a skip of steps never lets a person pass a step they
  could not enter.

Dependencies: `modules.registry` (`LifecycleDefinition`), `services.lifecycles` (`table_from_enum`), `services.labels`,
`services.change_request_summary` (status labels), `services.rbac` (effective roles).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest
from app.models.enums import ChangeRequestStatus, ProjectRole, RequirementStatus
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.registry import LifecycleDefinition
from app.services.change_request_summary import CHANGE_REQUEST_STATUS_LABEL
from app.services.labels import REQUIREMENT_STATUS_LABEL
from app.services.lifecycles import table_from_enum
from app.services.rbac import get_effective_project_roles
from app.services.requirements import CAN_EDIT_ROLES

REQUIREMENT_TYPE = "requirement"
CHANGE_REQUEST_TYPE = "change_request"

_R = RequirementStatus
_C = ChangeRequestStatus

# Moves `update_requirement` and the record table import accept: any edit of an unlocked requirement may set another
# status. Approved locks the requirement, so it has no way out.
_REQUIREMENT_TRANSITIONS = {
    _R.DRAFT: {_R.REVIEWED, _R.APPROVED, _R.ARCHIVED},
    _R.REVIEWED: {_R.DRAFT, _R.APPROVED, _R.ARCHIVED},
    _R.APPROVED: set(),
    _R.ARCHIVED: {_R.DRAFT, _R.REVIEWED, _R.APPROVED},
}

# Submit (creator), decide (project manager) and withdraw (creator) of a change request. A request is decided only
# from a submitted (or in review) state.
_CHANGE_REQUEST_TRANSITIONS = {
    _C.DRAFT: {_C.SUBMITTED, _C.WITHDRAWN},
    _C.SUBMITTED: {_C.APPROVED, _C.REJECTED, _C.WITHDRAWN},
    _C.IN_REVIEW: {_C.APPROVED, _C.REJECTED, _C.WITHDRAWN},
    _C.APPROVED: set(),
    _C.REJECTED: set(),
    _C.WITHDRAWN: set(),
}


def _requirement_entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move a requirement into `state`: Approved needs the project manager role, any
    other state a requirement-editing role.

    Args:
        db: Active session.
        user: The person moving the requirement.
        project: The requirement's project.
        record_id: The requirement (not read: the right depends on the state and the project).
        state: The state entered.

    Raises:
        HTTPException: 403 when the person lacks the role.
    """
    roles = get_effective_project_roles(db, user.id, project.id)
    if state == RequirementStatus.APPROVED.value:
        if ProjectRole.PROJECT_MANAGER not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a requirement.")
    elif not roles & set(CAN_EDIT_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _change_request_entry_guard(db: Session, user: User, project: Project, record_id: uuid.UUID, state: str) -> None:
    """Refuses (403) when `user` may not move a change request into `state`: only its creator submits, and only a project
    manager decides.

    Args:
        db: Active session.
        user: The person moving the change request.
        project: The change request's project.
        record_id: The change request.
        state: The state entered.

    Raises:
        HTTPException: 403 when the person lacks the right.
    """
    if state == ChangeRequestStatus.SUBMITTED.value:
        cr = db.get(ChangeRequest, record_id)
        if cr is not None and cr.creator_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator may submit this change request.")
    elif ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, user.id, project.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can decide a change request.")


CORE_LIFECYCLES: dict[str, LifecycleDefinition] = {
    REQUIREMENT_TYPE: LifecycleDefinition(
        label="Requirement",
        path=(_R.DRAFT.value, _R.REVIEWED.value, _R.APPROVED.value),
        transitions=table_from_enum(_REQUIREMENT_TRANSITIONS), labels=REQUIREMENT_STATUS_LABEL,
        optional=(_R.REVIEWED.value,), gated=(_R.APPROVED.value,), entry_guard=_requirement_entry_guard,
        record_model=Requirement,
    ),
    CHANGE_REQUEST_TYPE: LifecycleDefinition(
        label="Change request",
        path=(_C.DRAFT.value, _C.SUBMITTED.value, _C.APPROVED.value),
        transitions=table_from_enum(_CHANGE_REQUEST_TRANSITIONS), labels=CHANGE_REQUEST_STATUS_LABEL,
        gated=(_C.APPROVED.value,), entry_guard=_change_request_entry_guard, record_model=ChangeRequest,
    ),
}
