"""Pydantic types for a principal (user, org group or project group) named by a record field."""

from uuid import UUID

from pydantic import BaseModel

from app.models.enums import PrincipalType


class PrincipalRef(BaseModel):
    """A request-side principal: what a form sends for an owner/assignee field."""

    type: PrincipalType
    id: UUID


class PrincipalOut(BaseModel):
    """A response-side principal, resolved for display.

    Attributes:
        type: User, organisation group or project group.
        id: The principal's id.
        label: The user's display name or the group's name; a placeholder when the principal no longer exists.
        member_count: Effective members of a group (None for a user), so a badge can show how many people
            an owner group stands for.
        exists: False once a group has been deleted but a history row still names it.
    """

    type: PrincipalType
    id: UUID
    label: str
    member_count: int | None = None
    exists: bool = True


class WatcherCreate(BaseModel):
    """Adds a group as a watcher of a requirement or change request (its members all follow it)."""

    group: PrincipalRef


class PrincipalUsageItem(BaseModel):
    """One kind of record that names a group, and how many."""

    label: str
    count: int
    mandatory: bool


class PrincipalUsageOut(BaseModel):
    """What still names a group (see `services.principals.compute_usage`).

    Attributes:
        total: Rows naming the group across every declared field.
        mandatory_total: Rows where the field cannot be left empty (so a replacement is required).
        items: The breakdown, one line per declared field that has at least one row.
    """

    total: int
    mandatory_total: int
    items: list[PrincipalUsageItem]
