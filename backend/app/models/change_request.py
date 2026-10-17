"""
Module: models.change_request

Defines change requests: the formal mechanism for proposing a new
requirement or modifying an approved one (introduction, C-G-03, C-G-12).
Mirrors the requirement versioning pattern so every edit to a change
request's proposed content is itself logged (C-A-04).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ChangeRequestVoteChoice,
    ProposedLinkOutcome,
    RequirementLevel,
    ReviewTargetType,
)
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column


class ChangeRequest(UUIDPKMixin, TimestampMixin, Base):
    """A proposal to add or modify a requirement, subject to review/approval.

    Attributes:
        requirement_id: The requirement being modified; null when kind is
            NEW_REQUIREMENT (the requirement does not exist yet).
        creator_id: The user who authored the change request (C-G-13).
        decided_by / decided_at: Set when a project manager approves or
            rejects the change request.
    """

    __tablename__ = "change_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[ChangeRequestKind] = mapped_column(str_enum(ChangeRequestKind))
    status: Mapped[ChangeRequestStatus] = mapped_column(str_enum(ChangeRequestStatus, 20), default=ChangeRequestStatus.DRAFT)

    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")

    versions: Mapped[list[ChangeRequestVersion]] = relationship(
        back_populates="change_request", order_by="ChangeRequestVersion.version_number"
    )


class ChangeRequestVersion(UUIDPKMixin, Base):
    """A snapshot of a change request's proposed content and justification.

    Attributes:
        reason: Why the change is being requested and wasn't identified
            during original scoping (introduction requirement for CR
            submissions).
        proposed_component_id / proposed_category_id: Only meaningful for
            NEW_REQUIREMENT change requests.
        changed_fields: For a MODIFY_REQUIREMENT change request, the
            explicit list of which requirement fields this change request
            actually proposes to change (field names matching
            RequirementVersion's own attribute names, e.g. `"name"`,
            `"target_stage_id"`, `"attachments"`). A `proposed_*` column not
            named here is not part of this proposal at all — approval must
            leave the corresponding requirement field completely untouched,
            not silently overwrite it with a same-or-stale value (the gap
            this replaces: every field used to be re-applied unconditionally
            on approval). Always empty for NEW_REQUIREMENT change requests,
            where every field is meaningful by definition (there's no
            "current version" to diff against). See
            `routers/change_requests.py::decide_change_request` for where
            this is consulted, and `docs/decisions.md`'s "Change request
            field-level tracking" entry for the full reasoning.
        proposed_attachment_file_ids: File ids (already uploaded as an
            organisation shared resource — the same upload path the report-
            image picker uses, see `routers/orgs.py::upload_org_resource`)
            this change request proposes attaching to the requirement.
            Always additive: approval creates new `RequirementFile` links
            for these, never removes existing attachments. Meaningful only
            when `"attachments"` is in `changed_fields`.
        proposed_action_link_id / proposed_action_title / proposed_action_
            description / proposed_action_type_id / proposed_action_
            assignee_type+_id (a principal — `models.principal`) / proposed_action_due_date: ADD_ACTION-only
. Either
            `proposed_action_link_id` (link an existing `RequirementAction`
            to the target requirement) or `proposed_action_title` +
            `proposed_action_type_id` (create a new one and link it) is
            set, mutually exclusive — see
            `routers/change_requests.py::create_change_request`'s
            validation. `proposed_action_link_id` is also REMOVE_ACTION's
            only field — which of the
            requirement's already-linked actions to unlink on approval;
            reusing the same column rather than adding a duplicate one,
            since the two kinds never coexist on one version row.
        proposed_links: The links this change request proposes,
            merged into the requirement on approval
            as the approver chooses. The whole payload of an ADD_LINK request
            and an optional addition to NEW_REQUIREMENT / MODIFY_REQUIREMENT
            ones. See `ChangeRequestProposedLink`.
        proposed_link_id: REMOVE_LINK-only — the existing `ArtefactLink` row to remove on approval.
            `ondelete="SET NULL"` since the link could in principle be
            removed by some other path between submission and approval;
            `decide_change_request` re-checks it still exists before acting,
            the same defensive re-check `proposed_attachment_file_ids`/
            `proposed_action_link_id` already get.
    """

    __tablename__ = "change_request_versions"
    __table_args__ = (
        UniqueConstraint("change_request_id", "version_number"),
        principal_check_constraint("proposed_action_assignee", nullable=True),
        principal_check_constraint("proposed_reviewer", nullable=True),
    )

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)

    # Nullable at the DB layer even though NEW_REQUIREMENT change requests
    # always need a real name — that requirement is enforced at the
    # schema/router layer (ChangeRequestCreate), not here, since a
    # MODIFY_REQUIREMENT change request that isn't proposing to rename
    # anything legitimately has no proposed_name at all (see changed_fields).
    proposed_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proposed_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_clarification: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="SET NULL"), nullable=True
    )
    proposed_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_categories.id", ondelete="SET NULL"), nullable=True
    )
    # Mirrors Requirement/RequirementVersion's target_stage_id/level (mock's
    # "Target"/"Level" fields) so a change request can propose changing them,
    # same as it can propose changing name/reasoning/clarification.
    proposed_target_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="SET NULL"), nullable=True
    )
    proposed_level: Mapped[RequirementLevel | None] = mapped_column(str_enum(RequirementLevel, 20), nullable=True)
    # Mirrors RequirementVersion's review-scheduling fields (C-R-06/08/10) so
    # a change request can propose setting/changing them, same as any other
    # requirement content — review_date can only change via this path once a
    # requirement is approved.
    proposed_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposed_review_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_reviewer_type: Mapped[str | None] = principal_type_column(nullable=True)
    proposed_reviewer_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    proposed_attachment_file_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # ADD_ACTION-only: either `proposed_action_link_id` (link an
    # existing `RequirementAction`) or `proposed_action_title` +
    # `proposed_action_type_id` (create a new one) is set, never both — see
    # `routers.change_requests.create_change_request`'s validation. Mirrors
    # the requirement detail page's own "Link existing action"/"Create and
    # link a new action" split rather than inventing a third shape.
    proposed_action_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_actions.id", ondelete="SET NULL"), nullable=True
    )
    proposed_action_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proposed_action_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_action_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("action_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    proposed_action_assignee_type: Mapped[str | None] = principal_type_column(nullable=True)
    proposed_action_assignee_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    proposed_action_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # REMOVE_LINK-only. References `artefact_links.id` (Platform Foundations)
    # — originally `requirement_links.id`; repointed by migration 0041
    # when that table was folded into the generic `ArtefactLink` table,
    # preserving each migrated row's original id so this FK never needed
    # its stored values to change, only its target.
    proposed_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artefact_links.id", ondelete="SET NULL"), nullable=True
    )
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reason: Mapped[str] = mapped_column(Text)
    # Values for this project's custom change-request attribute definitions
    # (C-C-01, C-C-02), keyed by CustomFieldDefinition id. Meaningful only
    # when "custom_fields" is in changed_fields (for MODIFY_REQUIREMENT) or
    # always for NEW_REQUIREMENT.
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    change_request: Mapped[ChangeRequest] = relationship(back_populates="versions")
    proposed_links: Mapped[list[ChangeRequestProposedLink]] = relationship(
        back_populates="version", order_by="ChangeRequestProposedLink.sort_order",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class ChangeRequestProposedLink(UUIDPKMixin, Base):
    """One link a change request proposes to create, merged on approval.

    A real table (not a JSON list) so the link
    type is a foreign key: deleting an in-use link type repoints or blocks on
    these rows (`services.link_type_usage`) instead of `SET NULL` silently
    stripping the type from a request that could then no longer be applied.

    Attributes:
        change_request_version_id: The version row the link was proposed on.
        link_type_id: The link type. `SET NULL` only reaches resolved (merged,
            declined, skipped) rows, since an open request blocks or repoints
            first; such a row keeps its outcome but no longer names a type.
        direction: `"outgoing"` when the requirement is the link's source,
            `"incoming"` when it is the target. Relative to the requirement
            because a `NEW_REQUIREMENT` request has no requirement id yet.
        other_type / other_id: The record at the far end.
        other_project_id: The far end's project when it is an ancestor or
            descendant of the request's project; `NULL` for the request's own.
        outcome / outcome_reason: What became of it (`ProposedLinkOutcome`) and,
            for `skipped`, why.
        sort_order: Display order, the order it was proposed in.
    """

    __tablename__ = "change_request_proposed_links"
    __table_args__ = (
        Index("ix_cr_proposed_links_version", "change_request_version_id"),
        Index("ix_cr_proposed_links_link_type", "link_type_id"),
    )

    change_request_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_request_versions.id", ondelete="CASCADE")
    )
    link_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_link_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(10))
    other_type: Mapped[str] = mapped_column(String(40))
    other_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    other_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    outcome: Mapped[ProposedLinkOutcome] = mapped_column(str_enum(ProposedLinkOutcome, 20), default=ProposedLinkOutcome.PENDING)
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    version: Mapped[ChangeRequestVersion] = relationship(back_populates="proposed_links")


class ReviewComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion thread comment on a requirement or change request (C-R-01).

    Kept separate from RequirementVersion/ChangeRequestVersion history so the
    UI change log can exclude discussion comments as required (C-A-09
    clarification).
    """

    __tablename__ = "review_comments"

    target_type: Mapped[ReviewTargetType] = mapped_column(str_enum(ReviewTargetType, 20))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    # Set only by PATCH .../comments/{id} (author-only) when the body is
    # actually changed — null for a never-edited comment. Deliberately its
    # own column rather than comparing created_at/updated_at: TimestampMixin's
    # two independent default=utcnow callables can resolve microseconds
    # apart on the same INSERT, which would make a fresh comment
    # intermittently read as "edited".
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChangeRequestTask(UUIDPKMixin, TimestampMixin, Base):
    """A task assigned during a change request's review (C-R-02, C-R-04).

    The assignee is a principal (`assignee_type` / `assignee_id`, `models.principal`): a user, an
    organisation group or one of the project's groups. Any one member of an assigned group may mark the
    task done.
    """

    __tablename__ = "change_request_tasks"
    __table_args__ = (principal_check_constraint("assignee", nullable=True),)

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(Text)
    assignee_type: Mapped[str | None] = principal_type_column(nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ChangeRequestVote(UUIDPKMixin, Base):
    """A stakeholder's advisory vote on a change request's approval (C-R-03).

    Advisory only — does not change `ChangeRequest.status` or bypass the
    project manager's own approve/reject decision; it's a visible tally the
    decision-maker can see alongside the change request.
    """

    __tablename__ = "change_request_votes"
    __table_args__ = (UniqueConstraint("change_request_id", "user_id"),)

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    vote: Mapped[ChangeRequestVoteChoice] = mapped_column(str_enum(ChangeRequestVoteChoice, 20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
