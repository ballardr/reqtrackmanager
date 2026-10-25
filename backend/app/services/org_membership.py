"""
Module: services.org_membership

The one rule for pulling an existing platform account into an organisation it does not belong to yet.

Responsibilities:
- Decide whether an organisation may take an existing account as a member (`external_account_refusal`,
  `assert_may_add_account`), for every path that does it on an administrator's say-so rather than the
  person's own: a role grant by user id, SCIM provisioning, and an organisation bundle merge.
- Remove an account from one organisation without touching its standing anywhere else
  (`remove_member_from_organization`), which is what "deactivate" means for an account the organisation does not
  wholly own.
- Tell the callers whether an account is held by an organisation other than this one (`belongs_elsewhere`),
  which also bounds how far an organisation administrator may act on an account (`deactivate`, SCIM).

Design decisions:
- A `User` is global: one account may belong to many organisations and organisation membership is what
  scopes an administrator's authority over it. Adding an account to an organisation therefore hands that
  organisation's administrators authority over it, so an organisation that has not opted in to external
  users (`Organization.external_user_policy` is `DISABLED`, the default) may not do it to an account that
  another organisation already holds (a platform administrator's account is one, like any other). An account
  that belongs to no organisation yet is unclaimed and may be taken (self-signup accounts wait for an
  administrator to assign them).
- A banned account is never added; that is the same rule `assign_org_role` and the project by-email route
  already enforce, kept here so every path shares it.
- Callers authorise the acting administrator; this module only judges the target account.

Dependencies: `models.organization`, `models.user`, `models.enums`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ExternalUserPolicy, ProjectRole
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User
from app.services import engagement
from app.services.audit import log_event
from app.services.rbac import (
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    lock_organization_for_update,
    lock_project_for_update,
)


def belongs_elsewhere(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Whether the account holds a role in any organisation other than `organization_id`.

    Args:
        db: Active session.
        user_id: The account.
        organization_id: The organisation being acted in.

    Returns:
        True when another organisation also has a claim on the account.
    """
    return (
        db.scalar(
            select(UserOrgRole.id).where(UserOrgRole.user_id == user_id, UserOrgRole.organization_id != organization_id).limit(1)
        )
        is not None
    )


def holds_org_role(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Whether the account holds any directly granted role in the organisation."""
    return (
        db.scalar(
            select(UserOrgRole.id).where(UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id).limit(1)
        )
        is not None
    )


def external_account_refusal(db: Session, org: Organization, target: User) -> str | None:
    """Why `org` may not take `target` as a member, or `None` when it may.

    Args:
        db: Active session.
        org: The organisation that would gain the member.
        target: The existing account.

    Returns:
        A message for the caller to report, or `None` when the account is already a member, is unclaimed, or
        the organisation allows external users.
    """
    if holds_org_role(db, target.id, org.id):
        return None
    if target.is_banned:
        return "This user has been banned by a server admin and cannot be granted a role."
    if belongs_elsewhere(db, target.id, org.id) and org.external_user_policy == ExternalUserPolicy.DISABLED:
        return "This organisation does not allow external users."
    return None


def assert_account_active(db: Session, user_id: UUID) -> None:
    """Raises 409 when the account is deactivated, so no role or membership is granted to someone who cannot
    sign in (it would be inert, yet show up in member lists and as a manager or reviewer nobody can reach).

    Args:
        db: Active session.
        user_id: The account about to be granted a role or membership.

    Raises:
        HTTPException: 403 when the account is banned (the same refusal every grant path already gave); 409
            when it is deactivated or archived. A missing account is left to the caller's own not-found handling.
    """
    user = db.get(User, user_id)
    if user is not None and user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role.")
    if user is not None and (not user.is_active or user.is_archived):
        raise HTTPException(status.HTTP_409_CONFLICT, "This user is deactivated and cannot be granted a role or membership.")


def assert_may_add_account(db: Session, org: Organization, target: User) -> None:
    """Raises 403 unless `org` may take `target` as a member (see `external_account_refusal`).

    Args:
        db: Active session.
        org: The organisation that would gain the member.
        target: The existing account.

    Raises:
        HTTPException: 403 with the refusal message.
    """
    refusal = external_account_refusal(db, org, target)
    if refusal is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, refusal)


def remove_member_from_organization(
    db: Session, organization_id: UUID, user_id: UUID, *, actor_id: UUID | None, action: str = "removed_from_organization",
) -> None:
    """Removes a user's membership of one organisation and commits; the account itself is untouched.

    Deletes every direct project role and project-group membership across the organisation's projects, every
    membership of its org groups, the user's subscriptions and favourites on its projects, and finally their
    organisation roles. Locks the organisation, then each project in turn before its sole-manager check, so two
    concurrent removals cannot each count the other as the remaining manager.

    Args:
        db: Active session.
        organization_id: The organisation to remove the user from.
        user_id: The user.
        actor_id: The administrator acting, or `None` for a provisioning channel (SCIM) with no user behind it.
        action: The audit action recorded.

    Raises:
        HTTPException: 404 if the user holds no role in the organisation; 409 if they are the sole manager of
            a project (someone else has to be made manager first).
    """
    lock_organization_for_update(db, organization_id)
    if not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    blocking_projects = []
    for project in projects:
        lock_project_for_update(db, project.id)
        concrete_managers = get_effective_project_managers(db, project.id)
        is_manager = user_id in concrete_managers or ProjectRole.PROJECT_MANAGER in get_effective_project_roles(
            db, user_id, project.id
        )
        if is_manager and not (concrete_managers - {user_id}):
            blocking_projects.append(project.name)
    if blocking_projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user is the sole manager of: " + ", ".join(blocking_projects) + ". Assign another manager first.",
        )

    project_ids = [p.id for p in projects]
    if project_ids:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(
                ProjectGroupMember.user_id == user_id,
                ProjectGroupMember.project_group_id.in_(select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))),
            )
        )
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.user_id == user_id,
            OrgGroupMember.org_group_id.in_(select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, project_ids)
    db.execute(
        UserOrgRole.__table__.delete().where(UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id)
    )
    log_event(
        db, entity_type="user_org_role", entity_id=user_id, action=action, actor_id=actor_id, organization_id=organization_id,
    )
    db.commit()
