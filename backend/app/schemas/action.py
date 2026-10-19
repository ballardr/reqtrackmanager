"""
Module: schemas.action

Request/response models for requirement actions (`RequirementAction`) and
their many-to-many links to requirements (untyped `ArtefactLink` rows,
`models.relationship`). The assignee is a principal: requests send a
`PrincipalRef` (`{type, id}`; null clears it) and responses return a resolved
`PrincipalOut` (users and groups on parity).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RequirementActionOutcome
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.project_scope import ProjectScopedRow


class RequirementActionCreate(BaseModel):
    """Creates a standalone action — does not link it to any requirement by
    itself (see `RequirementActionLinkCreate`/the requirement-scoped
    create-and-link endpoint for that)."""

    title: str
    description: str = ""
    action_type_id: UUID
    assignee: PrincipalRef | None = None
    due_date: date | None = None


class RequirementActionUpdate(BaseModel):
    """Edit payload. Omitting `outcome_status` leaves it unchanged; setting
    it away from PENDING stamps `completed_at`/`completed_by` (see
    `services.actions.apply_outcome_transition`)."""

    title: str
    description: str = ""
    action_type_id: UUID
    assignee: PrincipalRef | None = None
    due_date: date | None = None
    outcome_status: RequirementActionOutcome | None = None


class LinkedRequirementOut(BaseModel):
    """A requirement an action is linked to, as the action's detail page lists it."""

    id: UUID
    unique_code: str
    name: str


class RequirementActionOut(ProjectScopedRow):
    id: UUID
    project_id: UUID
    unique_code: str
    action_type_id: UUID
    title: str
    description: str
    outcome_status: RequirementActionOutcome
    assignee: PrincipalOut | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    creator_id: UUID
    is_archived: bool
    archived_at: datetime | None = None
    archived_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0


class RequirementActionLinkCreate(BaseModel):
    """Links an existing action to the requirement in the URL path."""

    action_id: UUID
