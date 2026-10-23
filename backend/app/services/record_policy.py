"""
Module: services.record_policy

Resolves and changes the personal-data policy for record-table export and import.

Responsibilities:
- The effective decision per sensitivity tag: the organisation's override if set, else the server
  default, else **excluded** (a fresh install lets no personal data leave through a file).
- Whether a person may include or import tagged columns at all: the policy must allow the tag **and**
  the person must hold `export_personal_data` in the project. Both have to say yes.
- Setting and clearing the server default and the organisation override, with one audit event each
  (old and new value, never any record data).

Design decisions:
- One resolver (`tag_decisions`) feeds export, import and the columns listing, so no route can apply a
  looser rule than another.
- A denied tag reports *why* (`policy` or `permission`) so the list can say so honestly.
- Functions leave committing to the caller.

External dependencies: SQLAlchemy; `services.rbac` for the permission check; `services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.record_policy import OrganizationRecordSensitivityOverride, ServerRecordSensitivityDefault
from app.models.user import User
from app.modules.registry import RECORD_SENSITIVITY_TAGS
from app.services.audit import log_event
from app.services.rbac import EXPORT_PERSONAL_DATA, get_effective_permissions

REASON_POLICY = "policy"
REASON_PERMISSION = "permission"


@dataclass(frozen=True)
class TagPolicy:
    """One sensitivity tag's policy as an organisation sees it.

    Attributes:
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        server_allowed: The server default (`False` when no default has been set).
        override: The organisation's own decision, or `None` when it follows the server.
        effective: What applies: the override if set, else the server default.
    """

    tag: str
    server_allowed: bool
    override: bool | None

    @property
    def effective(self) -> bool:
        return self.server_allowed if self.override is None else self.override


@dataclass(frozen=True)
class TagDecision:
    """Whether one person may export or import columns with one tag in one project.

    Attributes:
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        allowed: Both the policy and the person's permission allow it.
        reason: `None` when allowed, else `"policy"` (the organisation or server excludes it) or
            `"permission"` (the policy allows it but the person lacks `export_personal_data`).
    """

    tag: str
    allowed: bool
    reason: str | None


def check_tag(tag: str) -> None:
    """Raises `ValueError` unless `tag` is one of `RECORD_SENSITIVITY_TAGS`."""
    if tag not in RECORD_SENSITIVITY_TAGS:
        raise ValueError(f"Unknown sensitivity tag {tag!r}.")


def server_defaults(db: Session) -> dict[str, bool]:
    """The server default per tag; a tag nobody has set is `False` (excluded)."""
    rows = {row.tag: row.allowed for row in db.scalars(select(ServerRecordSensitivityDefault))}
    return {tag: rows.get(tag, False) for tag in RECORD_SENSITIVITY_TAGS}


def organization_policy(db: Session, organization_id: uuid.UUID) -> list[TagPolicy]:
    """Every tag's server default, organisation override and effective value, in vocabulary order."""
    defaults = server_defaults(db)
    overrides = {
        row.tag: row.allowed
        for row in db.scalars(
            select(OrganizationRecordSensitivityOverride).where(
                OrganizationRecordSensitivityOverride.organization_id == organization_id
            )
        )
    }
    return [TagPolicy(tag=tag, server_allowed=defaults[tag], override=overrides.get(tag)) for tag in RECORD_SENSITIVITY_TAGS]


def tag_decisions(db: Session, user: User, project: Project) -> dict[str, TagDecision]:
    """The decision per sensitivity tag for `user` in `project`.

    Args:
        db: Active session (read only).
        user: The person exporting or importing.
        project: The request project (its organisation's policy applies).

    Returns:
        A decision for every tag in `RECORD_SENSITIVITY_TAGS`.
    """
    policy = {item.tag: item for item in organization_policy(db, project.organization_id)}
    holds = EXPORT_PERSONAL_DATA in get_effective_permissions(
        db, user.id, organization_id=project.organization_id, project_id=project.id
    )
    decisions: dict[str, TagDecision] = {}
    for tag in RECORD_SENSITIVITY_TAGS:
        if not policy[tag].effective:
            decisions[tag] = TagDecision(tag, False, REASON_POLICY)
        elif not holds:
            decisions[tag] = TagDecision(tag, False, REASON_PERMISSION)
        else:
            decisions[tag] = TagDecision(tag, True, None)
    return decisions


def set_server_default(db: Session, tag: str, allowed: bool, actor_id: uuid.UUID) -> bool:
    """Sets the server default for `tag` and audits the change.

    Args:
        db: Active session; the caller commits.
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        allowed: The new default.
        actor_id: The server administrator making the change.

    Returns:
        The previous default (`False` when none had been set).

    Raises:
        ValueError: `tag` is not a known sensitivity tag.
    """
    check_tag(tag)
    row = db.get(ServerRecordSensitivityDefault, tag)
    previous = False if row is None else row.allowed
    if row is None:
        db.add(ServerRecordSensitivityDefault(tag=tag, allowed=allowed, updated_by=actor_id))
    else:
        row.allowed = allowed
        row.updated_by = actor_id
    log_event(
        db, entity_type="record_sensitivity_policy", entity_id=tag, action="record_policy.server_default_updated",
        actor_id=actor_id, detail={"tag": tag, "old": previous, "new": allowed},
    )
    return previous


def set_organization_override(
    db: Session, organization_id: uuid.UUID, tag: str, allowed: bool | None, actor_id: uuid.UUID
) -> bool | None:
    """Sets (or, with `allowed=None`, clears) the organisation's override for `tag` and audits the change.

    Args:
        db: Active session; the caller commits.
        organization_id: The organisation.
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        allowed: The override, or `None` to follow the server default again.
        actor_id: The organisation administrator making the change.

    Returns:
        The previous override (`None` when the organisation was following the server).

    Raises:
        ValueError: `tag` is not a known sensitivity tag.
    """
    check_tag(tag)
    row = db.get(OrganizationRecordSensitivityOverride, (organization_id, tag))
    previous = None if row is None else row.allowed
    if allowed is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(OrganizationRecordSensitivityOverride(
            organization_id=organization_id, tag=tag, allowed=allowed, updated_by=actor_id,
        ))
    else:
        row.allowed = allowed
        row.updated_by = actor_id
    log_event(
        db, entity_type="record_sensitivity_policy", entity_id=tag, action="record_policy.organization_override_updated",
        actor_id=actor_id, organization_id=organization_id, detail={"tag": tag, "old": previous, "new": allowed},
    )
    return previous
