"""
Module: schemas.policies

Request and response shapes for policies (`routers.policies`).

The public shapes carry only what a reader needs: never the author, the working copy, the change note or an
owning organisation's id. The member shapes (an organisation's policies, read by its members) add the organisation's
name and id, which the member already knows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.policy import PolicyState
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services.org_policies import MAX_AUDIENCE
from app.services.policies import MAX_NOTE_LENGTH, MAX_TITLE_LENGTH


class PolicyIn(BaseModel):
    """The editable fields of a policy (create and replace).

    Attributes:
        key: Built-in slot to create (`privacy` or `data`); omitted for any other policy.
        title: Heading, one line; ignored for a slot, which keeps its fixed title.
        body: Rich-text document (validated against the allowed vocabulary).
        effective_from: Date the policy takes effect, as chosen by the author; `None` when not stated.
        requires_acknowledgement: Whether each person it applies to must accept the current version; a key left out
            of a replacement leaves the setting unchanged.
    """

    key: Literal["privacy", "data"] | None = None
    title: str = Field(default="", max_length=MAX_TITLE_LENGTH)
    body: dict[str, Any] = Field(default_factory=dict)
    effective_from: date | None = None
    requires_acknowledgement: bool | None = None


class PolicyPublishIn(BaseModel):
    """Publishing a policy.

    Attributes:
        change_note: Why this version differs from the last (plain text), shown to administrators only.
    """

    change_note: str = Field(default="", max_length=MAX_NOTE_LENGTH)


class PolicySummaryOut(BaseModel):
    """One row of the administration list; a built-in slot with no policy yet has `id` of `None`.

    Attributes:
        has_unpublished_changes: Whether the working copy differs from the published version.
        requires_acknowledgement: Whether each person it applies to must accept the current version.
    """

    id: UUID | None
    key: str | None
    title: str
    state: PolicyState
    effective_from: date | None
    current_version: int
    has_unpublished_changes: bool
    requires_acknowledgement: bool = False
    updated_at: datetime | None


class PolicyVersionOut(BaseModel):
    """A published version as administrators see it (without the body)."""

    version: int
    title: str
    effective_from: date | None
    published_at: datetime
    change_note: str


class PolicyVersionBodyOut(PolicyVersionOut):
    """A published version with its body."""

    body: dict[str, Any]


class PolicyOut(PolicySummaryOut):
    """A policy with its working copy and version history, as administrators see it."""

    body: dict[str, Any]
    versions: list[PolicyVersionOut]


class PublicPolicySummaryOut(BaseModel):
    """A published policy in the public list.

    Attributes:
        version: Current published version number.
        published_at: When that version was published (UTC).
    """

    id: UUID
    key: str | None
    title: str
    effective_from: date | None
    version: int
    published_at: datetime


class PublicPolicyOut(PublicPolicySummaryOut):
    """A published policy with its text."""

    body: dict[str, Any]


class OrgPolicyIn(PolicyIn):
    """The editable fields of an organisation policy.

    Attributes:
        audience: Who may read it; empty (or omitted on create) is every member of the organisation. A key left out of a
            replacement leaves the audience unchanged.
    """

    audience: list[PrincipalRef] | None = Field(default=None, max_length=MAX_AUDIENCE)


class OrgPolicyPublishIn(PolicyPublishIn):
    """Publishing an organisation policy.

    Attributes:
        notify_members: Tell the people who may read it (off by default; the publisher is not told).
    """

    notify_members: bool = False


class OrgPolicySummaryOut(PolicySummaryOut):
    """One row of the organisation's administration list.

    Attributes:
        audience: Who the policy is limited to (empty: every member).
    """

    audience: list[PrincipalOut]


class OrgPolicyOut(PolicyOut):
    """An organisation policy with its working copy and version history, as the organisation's administrators see it."""

    audience: list[PrincipalOut]


class OrgPolicySettingsIO(BaseModel):
    """The organisation's policy settings.

    Attributes:
        allow_links: Whether the organisation's policies may contain links.
        starter_titles: Titles the add dialog suggests (read-only).
    """

    allow_links: bool
    starter_titles: list[str] = []


class OrgPolicySettingsIn(BaseModel):
    """Changes the organisation's policy settings."""

    allow_links: bool


class MemberPolicySummaryOut(BaseModel):
    """A published organisation policy in a member's list.

    Attributes:
        organization_id / organization_name: The owning organisation.
        version: Current published version number.
        published_at: When that version was published (UTC).
        requires_acknowledgement: Whether the caller must accept it.
        acknowledged: Whether the caller has accepted this version.
    """

    id: UUID
    organization_id: UUID
    organization_name: str
    title: str
    effective_from: date | None
    version: int
    published_at: datetime
    requires_acknowledgement: bool = False
    acknowledged: bool = False


class MemberPolicyOut(MemberPolicySummaryOut):
    """A published organisation policy with its text."""

    body: dict[str, Any]


class OrgPolicyAudienceLookupIn(BaseModel):
    """People and groups to name in the audience editor before the policy is saved."""

    audience: list[PrincipalRef] = Field(max_length=MAX_AUDIENCE)


class PendingPolicyOut(BaseModel):
    """A required policy the caller has not accepted, with the text to read and accept.

    Attributes:
        organization_id / organization_name: The owning organisation, or `None` for a server policy.
        version: The version to accept.
        published_at: When it was published (UTC).
    """

    id: UUID
    organization_id: UUID | None
    organization_name: str | None
    title: str
    effective_from: date | None
    version: int
    published_at: datetime
    body: dict[str, Any]


class AcknowledgeIn(BaseModel):
    """Accepting a policy: the version the person read, so a text that changed meanwhile is not accepted unseen."""

    version: int = Field(ge=1)


class AcknowledgementOut(BaseModel):
    """A recorded acceptance."""

    policy_id: UUID
    version: int
    acknowledged_at: datetime


class AcknowledgementStatusRowOut(BaseModel):
    """One person in a policy's status view.

    Attributes:
        accepted_version: The latest version accepted, or `None`.
        accepted_at: When it was accepted (UTC), or `None`.
        current: Whether that is the policy's current version.
    """

    user_id: UUID
    display_name: str
    email: str
    accepted_version: int | None
    accepted_at: datetime | None
    current: bool


class AcknowledgementStatusOut(BaseModel):
    """Who has and has not accepted a policy's current version.

    Attributes:
        required / accepted: Counts over everyone the policy applies to.
        truncated: Whether `people` was cut at the response limit (the export carries every row).
    """

    policy_id: UUID
    title: str
    version: int
    requires_acknowledgement: bool
    required: int
    accepted: int
    truncated: bool
    people: list[AcknowledgementStatusRowOut]


class ReminderOut(BaseModel):
    """The result of sending a reminder."""

    notified: int
