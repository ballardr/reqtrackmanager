"""
Module: services.rbac

Computes a user's effective organisation and project roles and exposes
FastAPI dependencies that enforce them (C-U-01, C-U-03).

Effective project role resolution combines three sources, per C-U-11 /
C-U-12:
    1. Direct per-user role assignments (UserProjectRole).
    2. Membership in a project group (ProjectGroupMember with user_id set).
    3. Membership in an org group that is itself nested inside a project
       group (ProjectGroupMember with org_group_id set, resolved via
       OrgGroupMember).

A project manager role implies project administrator and stakeholder
capabilities (C-U-03 clarification: "Project Managers can also perform all
project administrator and stakeholder tasks"). Holding any project role
implies baseline member-level view access.

Organisation admins do not automatically gain project content access
(C-U-01 clarification: "No Project access is guaranteed from any roles apart
from org admin being able to manage project settings") — that specific,
narrow capability is checked separately via `can_manage_project_settings`
rather than folded into the general project role set.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ProjectRole
from app.models.organization import OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User


def get_effective_org_roles(db: Session, user_id: UUID, organization_id: UUID) -> set[OrgRole]:
    """Returns the set of organisation roles a user holds in an organisation."""
    rows = db.scalars(
        select(UserOrgRole.role).where(
            UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id
        )
    ).all()
    return {OrgRole(r) for r in rows}


def is_org_admin(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Returns True if the user holds the org_admin role in the organisation."""
    return OrgRole.ORG_ADMIN in get_effective_org_roles(db, user_id, organization_id)


def can_manage_project_settings(db: Session, user: User, project: Project) -> bool:
    """Whether the user may manage project setup, stages, components, categories.

    True for project administrators/managers, and for organisation admins of
    the project's organisation (C-U-01 clarification).
    """
    if is_org_admin(db, user.id, project.organization_id):
        return True
    roles = get_effective_project_roles(db, user.id, project.id)
    return bool(roles & {ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR})


def get_effective_project_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Returns the set of project roles a user effectively holds.

    See module docstring for the resolution algorithm.
    """
    roles: set[ProjectRole] = set()

    direct = db.scalars(
        select(UserProjectRole.role).where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id
        )
    ).all()
    roles.update(ProjectRole(r) for r in direct)

    direct_group_roles = db.scalars(
        select(ProjectGroup.role)
        .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id == user_id)
    ).all()
    roles.update(ProjectRole(r) for r in direct_group_roles)

    user_org_group_ids = set(
        db.scalars(select(OrgGroupMember.org_group_id).where(OrgGroupMember.user_id == user_id)).all()
    )
    if user_org_group_ids:
        # Defense in depth: even though endpoints reject nesting an org
        # group from a different organisation into a project group at
        # write time, also constrain the read-side resolution to org
        # groups belonging to the project's own organisation, so a
        # cross-tenant row (however it got there) can never grant a role.
        nested_group_roles = db.scalars(
            select(ProjectGroup.role)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .join(OrgGroup, OrgGroup.id == ProjectGroupMember.org_group_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroupMember.org_group_id.in_(user_org_group_ids),
                OrgGroup.organization_id == Project.organization_id,
            )
        ).all()
        roles.update(ProjectRole(r) for r in nested_group_roles)

    if ProjectRole.PROJECT_MANAGER in roles:
        roles.add(ProjectRole.PROJECT_ADMINISTRATOR)
        roles.add(ProjectRole.STAKEHOLDER)
    if roles:
        roles.add(ProjectRole.MEMBER)

    return roles


def get_project_managers(db: Session, project_id: UUID) -> set[UUID]:
    """Returns the user ids who hold (directly or via group) the manager role.

    Used to enforce "a project must have at least one project manager"
    (C-U-08) and the org-removal fallback rule (C-U-09). Only resolves
    direct assignments and direct group membership (not nested org groups),
    since the fallback/guard rules operate on concrete, individually
    accountable users.
    """
    manager_ids: set[UUID] = set(
        db.scalars(
            select(UserProjectRole.user_id).where(
                UserProjectRole.project_id == project_id,
                UserProjectRole.role == ProjectRole.PROJECT_MANAGER,
            )
        ).all()
    )
    manager_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroup.role == ProjectRole.PROJECT_MANAGER,
                ProjectGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    return manager_ids


def get_project_users_by_role(db: Session, project_id: UUID, role: ProjectRole) -> set[UUID]:
    """Returns the user ids who hold `role` directly or via direct group
    membership (not nested org groups) — used for notification targeting
    (C-N-01), matching `get_project_managers`'s resolution semantics.
    """
    user_ids: set[UUID] = set(
        db.scalars(
            select(UserProjectRole.user_id).where(
                UserProjectRole.project_id == project_id, UserProjectRole.role == role
            )
        ).all()
    )
    user_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroup.role == role,
                ProjectGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    return user_ids


def get_project_member_user_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Returns every user id with any access to a project, for broadcast-style
    notifications (C-N-01) — direct roles, direct group membership, and
    members of org groups nested into a project group.
    """
    user_ids: set[UUID] = set(
        db.scalars(select(UserProjectRole.user_id).where(UserProjectRole.project_id == project_id)).all()
    )
    user_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    nested_org_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.org_group_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.org_group_id.is_not(None))
        ).all()
    )
    if nested_org_group_ids:
        user_ids.update(
            db.scalars(select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id.in_(nested_org_group_ids))).all()
        )
    return user_ids


def require_server_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency requiring the cross-tenant server admin role (I-M-05)."""
    if not current_user.is_server_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Server admin permission required.")
    return current_user


def require_org_role(*allowed: OrgRole):
    """FastAPI dependency factory requiring one of the given org roles.

    Expects an `organization_id` path parameter.

    Server admins do NOT bypass this check. I-M-05 is explicit that the
    server admin role "does not give access to data within organisations" —
    the only documented carve-out is creating the *initial* user in a new
    organisation, which uses `require_org_admin_or_server_admin` below
    instead of this factory.
    """

    def _dependency(
        organization_id: UUID,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_org_role` factory's docstring."""
        roles = get_effective_org_roles(db, current_user.id, organization_id)
        if not roles & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient organisation permissions.")
        return current_user

    return _dependency


def require_org_admin_or_server_admin(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Dependency for the one documented server-admin carve-out (I-M-05
    clarification): "This permission needs to be able to create users in
    organisations, such that they can create the initial organisation user."
    Used only by the create-org-user endpoint — every other org-scoped
    endpoint requires a genuine org role via `require_org_role`.
    """
    if current_user.is_server_admin:
        return current_user
    roles = get_effective_org_roles(db, current_user.id, organization_id)
    if OrgRole.ORG_ADMIN not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient organisation permissions.")
    return current_user


def require_project_role(*allowed: ProjectRole):
    """FastAPI dependency factory requiring one of the given project roles.

    Expects a `project_id` path parameter. Server admins do NOT bypass this
    check (I-M-05) — project content is "data within organisations".
    """

    def _dependency(
        project_id: UUID,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_project_role` factory's docstring."""
        roles = get_effective_project_roles(db, current_user.id, project_id)
        if not roles & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")
        return current_user

    return _dependency


def require_project_view(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Dependency requiring any project role (member-level content access).

    Org admins are not automatically included here: per C-U-01 clarification,
    org admin only guarantees the ability to manage project settings, not
    general content access (see `require_project_manage`). Server admins do
    not bypass this either (I-M-05).
    """
    if not get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this project.")
    return current_user


def require_project_manage(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Dependency requiring project-settings-management capability.

    Grants access to project managers, project administrators, and
    organisation admins of the project's organisation (C-U-01 clarification,
    C-U-03 clarification). Server admins do not bypass this (I-M-05).
    Returns the Project so callers avoid a second lookup.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if not can_manage_project_settings(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")
    return project
