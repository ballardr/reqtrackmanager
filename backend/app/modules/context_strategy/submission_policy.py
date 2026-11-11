"""
Module: modules.context_strategy.submission_policy

Who may submit a Pain Point in a project, and the one resolver every path asks.

- `resolve_submission_policy`: the policy that applies to a project and where it came from (its own setting,
  the nearest ancestor project's, the organisation default, or the platform default `MANAGERS`).
- `can_submit_pain_point` / `require_pain_point_submit`: the decision. The create endpoint, the record-table
  `can_create` (list import, the Links panel, the New button) and the MCP tool all call it, so the answers
  cannot drift apart.
- `set_project_submission_policy` / `set_org_submission_policy`: write or clear a setting (the caller commits).

Design decisions:
- The platform default is `MANAGERS`: submission is restricted unless a project or its organisation opts in to
  `MEMBERS`. Organisations that existed when the setting was introduced were given an explicit `MEMBERS` default
  by a migration, so none of them lost the ability to submit.
- Only submission is restricted. Editing, triage and scoring are manager-tier already, so a restricted project
  keeps the broad-creation model's other half (comments and evidence stay open to members).
- Resolution follows the nested-project rule used elsewhere (own, else nearest ancestor, else organisation, else
  default), always on and independent of role inheritance. A row is stored only where someone chose a value.
- "Managers" means the Pain Point manager tier (`can_manage_pain_points`), the same tier that triages.

Dependencies: this module's models and `_shared` role helpers; `services.project_hierarchy`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy._shared import can_manage_pain_points
from app.modules.context_strategy.enums import PainPointSubmissionPolicy
from app.modules.context_strategy.models import PainPointSubmissionSetting
from app.modules.registry import is_module_enabled_for_project
from app.services.project_hierarchy import get_project_chain_ids

DEFAULT_SUBMISSION_POLICY = PainPointSubmissionPolicy.MANAGERS

#: Where a resolved policy came from.
PolicySource = Literal["project", "ancestor", "organization", "default"]


@dataclass(frozen=True)
class ResolvedSubmissionPolicy:
    """The policy that applies to a project.

    Attributes:
        policy: The effective policy.
        source: Where it came from: the project's own setting, a parent project's, the organisation default,
            or the platform default.
        organization_default: The organisation's own default (`None` if it has not set one), so a project can
            show what clearing its override returns to.
    """

    policy: PainPointSubmissionPolicy
    source: PolicySource
    organization_default: PainPointSubmissionPolicy | None


def get_org_submission_policy(db: Session, organization_id: uuid.UUID) -> PainPointSubmissionPolicy | None:
    """The organisation's default policy, or `None` when it has not set one."""
    return db.scalar(select(PainPointSubmissionSetting.policy).where(
        PainPointSubmissionSetting.organization_id == organization_id, PainPointSubmissionSetting.project_id.is_(None),
    ))


def get_project_submission_policy(db: Session, project_id: uuid.UUID) -> PainPointSubmissionPolicy | None:
    """The project's own policy, or `None` when it inherits."""
    return db.scalar(select(PainPointSubmissionSetting.policy).where(PainPointSubmissionSetting.project_id == project_id))


def resolve_submission_policy(db: Session, project: Project) -> ResolvedSubmissionPolicy:
    """The submission policy that applies to `project`: its own setting, else the nearest ancestor's, else the
    organisation default, else the platform default `MANAGERS`."""
    chain = get_project_chain_ids(db, project.id)
    own = {
        row.project_id: row.policy for row in db.scalars(
            select(PainPointSubmissionSetting).where(PainPointSubmissionSetting.project_id.in_(chain))
        )
    }
    org_default = get_org_submission_policy(db, project.organization_id)
    for index, project_id in enumerate(chain):
        if project_id in own:
            return ResolvedSubmissionPolicy(own[project_id], "project" if index == 0 else "ancestor", org_default)
    if org_default is not None:
        return ResolvedSubmissionPolicy(org_default, "organization", org_default)
    return ResolvedSubmissionPolicy(DEFAULT_SUBMISSION_POLICY, "default", None)


def can_submit_pain_point(db: Session, user: User, project: Project) -> bool:
    """True when `user` may submit a Pain Point in `project`: always under `MEMBERS` (module access is checked by
    the caller's own gate), a Pain Point manager under `MANAGERS` (the platform default)."""
    if resolve_submission_policy(db, project).policy == PainPointSubmissionPolicy.MEMBERS:
        return True
    return can_manage_pain_points(db, user, organization_id=project.organization_id, project_id=project.id)


def restricted_message(db: Session, project: Project) -> str:
    """The refusal text for a restricted project: who submits, and where to raise an ordinary request."""
    message = "Pain Points are submitted by Pain Point Managers in this project."
    if is_module_enabled_for_project(db, project.id, "product_feedback"):
        message += " Raise an Enhancement Request instead."
    return message


def require_pain_point_submit(db: Session, user: User, project: Project) -> None:
    """Gate for submitting a Pain Point.

    Raises:
        HTTPException: 403 when the project's policy is `MANAGERS` and `user` is not a Pain Point manager.
    """
    if not can_submit_pain_point(db, user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, restricted_message(db, project))


def set_project_submission_policy(
    db: Session, project: Project, policy: PainPointSubmissionPolicy | None,
) -> PainPointSubmissionPolicy | None:
    """Sets the project's own policy, or clears it (`None`) so the project inherits (the caller commits).

    Returns:
        The previous own policy, or `None` when the project inherited.
    """
    row = db.scalar(select(PainPointSubmissionSetting).where(PainPointSubmissionSetting.project_id == project.id))
    previous = row.policy if row is not None else None
    if policy is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(PainPointSubmissionSetting(organization_id=project.organization_id, project_id=project.id, policy=policy))
    else:
        row.policy = policy
    db.flush()
    return previous


def set_org_submission_policy(
    db: Session, organization_id: uuid.UUID, policy: PainPointSubmissionPolicy | None,
) -> PainPointSubmissionPolicy | None:
    """Sets the organisation's default policy, or clears it (`None`) so the platform default applies (the caller
    commits).

    Returns:
        The previous default, or `None` when none was set.
    """
    row = db.scalar(select(PainPointSubmissionSetting).where(
        PainPointSubmissionSetting.organization_id == organization_id, PainPointSubmissionSetting.project_id.is_(None),
    ))
    previous = row.policy if row is not None else None
    if policy is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(PainPointSubmissionSetting(organization_id=organization_id, project_id=None, policy=policy))
    else:
        row.policy = policy
    db.flush()
    return previous
