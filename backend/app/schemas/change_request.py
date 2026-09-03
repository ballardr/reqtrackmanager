"""
Module: schemas.change_request

Request/response models for the change request workflow (introduction,
C-G-03, C-G-12), plus review-stage tasks (C-R-02/04) and stakeholder voting
(C-R-03) added in Massif (v3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ChangeRequestKind, ChangeRequestStatus, ChangeRequestVoteChoice, RequirementLevel

#: Field names a MODIFY_REQUIREMENT change request may list in
#: `changed_fields` — matching RequirementVersion's own attribute names,
#: plus the synthetic `"attachments"` entry for proposed file attachments.
#: The single source of truth both `ChangeRequestCreate`'s validator and
#: `routers/change_requests.py::decide_change_request`'s approval-
#: application logic key off of, so the two can never drift apart.
CHANGEABLE_REQUIREMENT_FIELDS = frozenset({
    "name", "reasoning", "clarification", "description", "target_stage_id", "level",
    "review_date", "review_lead_days", "reviewer_id", "custom_fields", "attachments",
})

#: Maps a changed_fields entry to the ChangeRequestCreate attribute that
#: must be non-None when that field is listed — only for fields where the
#: requirement itself can never legitimately hold a null value (so None
#: unambiguously means "not proposing a change"). review_date/
#: review_lead_days/reviewer_id/custom_fields/attachments are deliberately
#: excluded: those genuinely support a null/empty *proposed* value (e.g.
#: clearing the reviewer), so changed_fields membership alone — not a
#: non-None check — is what signals they're being touched.
FIELDS_REQUIRING_A_VALUE_WHEN_CHANGED = {
    "name": "proposed_name",
    "reasoning": "proposed_reasoning",
    "clarification": "proposed_clarification",
    "description": "proposed_description",
    "target_stage_id": "proposed_target_stage_id",
    "level": "proposed_level",
}


class ChangeRequestCreate(BaseModel):
    """`proposed_*` fields are only meaningful when the corresponding name
    is listed in `changed_fields` (MODIFY_REQUIREMENT) or always
    (NEW_REQUIREMENT, which has no "current version" to diff against and so
    ignores `changed_fields` entirely — every field it sets is meaningful by
    definition). A field not in `changed_fields` is left completely
    untouched on approval, not overwritten with a stale/default value — see
    `docs/decisions.md`'s "Change request field-level tracking" entry."""

    kind: ChangeRequestKind
    requirement_id: UUID | None = None
    changed_fields: list[str] = []
    proposed_name: str | None = None
    proposed_reasoning: str | None = None
    proposed_clarification: str | None = None
    proposed_description: str | None = None
    proposed_component_id: UUID | None = None
    proposed_category_id: UUID | None = None
    proposed_target_stage_id: UUID | None = None
    proposed_level: RequirementLevel | None = None
    proposed_attachment_file_ids: list[UUID] = []
    reason: str
    custom_fields: dict[str, Any] = {}
    creator_id: UUID | None = None  # PM-only override (C-A-12)
    proposed_review_date: date | None = None  # C-R-06
    proposed_review_lead_days: int | None = None
    proposed_reviewer_id: UUID | None = None  # C-R-10
    # ADD_ACTION-only (item 514) — see `ChangeRequestVersion`'s docstring
    # for the mutually-exclusive link-existing-vs-create-new split.
    proposed_action_link_id: UUID | None = None
    proposed_action_title: str | None = None
    proposed_action_description: str | None = None
    proposed_action_type_id: UUID | None = None
    proposed_action_assignee_id: UUID | None = None
    proposed_action_due_date: date | None = None


class ChangeRequestOut(BaseModel):
    id: UUID
    project_id: UUID
    requirement_id: UUID | None
    kind: ChangeRequestKind
    status: ChangeRequestStatus
    creator_id: UUID
    changed_fields: list[str] = []
    proposed_name: str | None = None
    proposed_reasoning: str | None = None
    proposed_clarification: str | None = None
    proposed_description: str | None = None
    proposed_target_stage_id: UUID | None = None
    proposed_level: RequirementLevel | None = None
    proposed_attachment_file_ids: list[UUID] = []
    reason: str
    custom_fields: dict[str, Any]
    submitted_at: datetime | None
    decided_at: datetime | None
    decided_by: UUID | None
    decision_note: str
    created_at: datetime
    is_subscribed: bool = False
    # Derived list-view indicators (mock's card "badges"), computed at read time.
    comment_count: int = 0
    requires_approval: bool = False
    proposed_review_date: date | None = None
    proposed_review_lead_days: int | None = None
    proposed_reviewer_id: UUID | None = None
    proposed_action_link_id: UUID | None = None
    proposed_action_title: str | None = None
    proposed_action_description: str | None = None
    proposed_action_type_id: UUID | None = None
    proposed_action_assignee_id: UUID | None = None
    proposed_action_due_date: date | None = None


class ChangeRequestDecision(BaseModel):
    approve: bool
    note: str = ""
    # Explicit approver choice (C-G-11), meaningful only when `approve` is
    # True, the change request is `MODIFY_REQUIREMENT`-kind, and the target
    # requirement currently has `is_completed=True` — a no-op, not an error,
    # for any other combination (e.g. a `NEW_REQUIREMENT` change request, or
    # a target that isn't currently completed). Deliberately opt-in rather
    # than automatic: a plain "Approve" must keep leaving `is_completed`
    # untouched (see `routers.change_requests.decide_change_request`'s
    # `status_value=None` comment for why that carry-forward behaviour is
    # itself deliberate, not a gap to close here) — this field is how an
    # approver says a particular change is substantial enough that
    # completion needs re-verifying, distinct from every other approval.
    clear_completion: bool = False


class ChangeRequestTaskCreate(BaseModel):
    description: str
    assignee_id: UUID | None = None
    due_date: date | None = None


class ChangeRequestTaskUpdate(BaseModel):
    description: str | None = None
    assignee_id: UUID | None = None
    due_date: date | None = None
    is_done: bool | None = None


class ChangeRequestTaskOut(BaseModel):
    id: UUID
    change_request_id: UUID
    description: str
    assignee_id: UUID | None = None
    due_date: date | None = None
    is_done: bool
    completed_at: datetime | None = None
    created_by: UUID
    created_at: datetime


class ChangeRequestVoteCreate(BaseModel):
    vote: ChangeRequestVoteChoice
    comment: str | None = None


class ChangeRequestVoteOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    change_request_id: UUID
    user_id: UUID
    vote: ChangeRequestVoteChoice
    comment: str | None = None
    voted_at: datetime


class ChangeRequestVoteTallyOut(BaseModel):
    votes: list[ChangeRequestVoteOut]
    approve_count: int
    reject_count: int
