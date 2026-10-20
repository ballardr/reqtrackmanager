"""
Module: services.project_access

Which projects a user can open at all.

Responsibilities:
- `accessible_project_ids`: every project the user holds some effective role on, however
  it is reached (direct role, project group, organisation-wide visibility, an organisation
  group, or inheritance through the project hierarchy / member sources).

Design decisions:
- One definition shared by the project list, the hierarchy endpoints, the organisation
  overview and the global search, so "can this user see this project" never has two answers.
- No server-admin bypass: project content is data within organisations, so even a server
  administrator sees only projects they hold a genuine role in.

Dependencies: `services.rbac` (effective roles), the project and organisation models.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.enums import ProjectRoleInheritanceMode, ProjectVisibility
from app.models.organization import UserOrgRole
from app.models.project import (
    OrgGroupProjectRole,
    Project,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    UserProjectRole,
)
from app.services.rbac import get_effective_project_roles, get_user_org_group_ids

_ACCESSIBLE_EXPANSION_ITERATION_CAP = 50


def accessible_project_ids(db: Session, user_id: UUID) -> set[UUID]:
    """Every project id the user has *some* effective role on — direct,
    group, org-wide visibility, plus (hierarchical projects) any project
    reachable *only* through forward or member-source inheritance from one
    of those.

    Without the inheritance expansion below, a user with access to a child
    purely via `role_inheritance_mode` (no direct/group/org-wide role of
    their own on the child) would never see it in `list_projects`/the tree/
    ancestors/children endpoints at all — the whole point of the feature
    would be invisible to exactly the users it's for. The expansion walks
    structural neighbours of already-accessible projects iteratively, since
    a multi-hop chain can make a project only reachable after an earlier
    hop's own expansion — three kinds of neighbour: children (source 5),
    projects whose member-source list names an accessible project as a
    source (source 6, same-organisation only since the mechanism was
    generalized beyond strict parent/child), and projects with a group
    whose members are defined as an accessible project's roster (source 7,
    same-organisation only) — but verifies each candidate's *actual*
    effective role (`get_effective_project_roles`) before including it,
    rather than trusting structural adjacency alone: a `MIRROR_ROLE`-
    filtered child, for instance, is only actually reachable by users
    holding the filtered role on the parent, not every accessible-parent
    user.
    """
    project_ids_via_role = set(
        db.scalars(select(UserProjectRole.project_id).where(UserProjectRole.user_id == user_id)).all()
    )
    # Members/groups directory rework (docs/decisions.md): a group
    # can now hold zero roles, so plain membership alone no longer implies
    # any access — the `join(ProjectGroupRole, ...)` below requires the
    # group to actually hold at least one role, matching `get_effective_
    # project_roles`'s own authoritative check (`rbac._direct_effective_
    # project_roles_by_kind`'s `direct_group` branch already requires this).
    # Found and fixed together with the identical pre-existing gap in
    # `rbac._direct_project_member_ids_base` — see that function's own
    # docstring for the regression this closes.
    project_ids_via_group = set(
        db.scalars(
            select(ProjectGroup.project_id)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(ProjectGroupMember.user_id == user_id)
        ).all()
    )
    user_org_ids = set(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user_id)).all())
    project_ids_via_org_wide = (
        set(
            db.scalars(
                select(Project.id).where(
                    Project.visibility == ProjectVisibility.ORG_WIDE, Project.organization_id.in_(user_org_ids)
                )
            ).all()
        )
        if user_org_ids
        else set()
    )
    # Pre-existing gap fixed here, found while regression-testing the org-group role grants (see
    # docs/decisions.md): the two sets above only ever covered a user's
    # *direct* membership (a UserProjectRole, or being a plain user_id
    # member of a ProjectGroup) — never a role reached only via an org group
    # the user belongs to, whether nested inside a ProjectGroup
    # (`ProjectGroupMember.org_group_id`, pre-existing) or granted a role
    # directly (`OrgGroupProjectRole`, the new mechanism). Both are
    # already correctly resolved by `get_effective_project_roles`/`require_
    # project_view`, so `GET /{project_id}` has always worked for such a
    # user — but `_accessible_project_ids` is the separate function behind
    # `list_projects`/`/ancestors`/`/children`, so that same user's project
    # simply never appeared in their own project list or search. Uses the
    # same `get_user_org_group_ids` (direct + transitively-nested) already
    # used elsewhere for this exact resolution, once per organisation the
    # user belongs to.
    all_user_org_group_ids: set[UUID] = set()
    for member_org_id in user_org_ids:
        direct_group_ids, inherited_group_ids = get_user_org_group_ids(db, user_id, member_org_id)
        all_user_org_group_ids |= direct_group_ids | inherited_group_ids
    project_ids_via_nested_org_group = (
        set(
            db.scalars(
                select(ProjectGroup.project_id)
                .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
                .where(ProjectGroupMember.org_group_id.in_(all_user_org_group_ids))
            ).all()
        )
        if all_user_org_group_ids
        else set()
    )
    project_ids_via_direct_group_role = (
        set(
            db.scalars(
                select(OrgGroupProjectRole.project_id).where(
                    OrgGroupProjectRole.org_group_id.in_(all_user_org_group_ids)
                )
            ).all()
        )
        if all_user_org_group_ids
        else set()
    )
    accessible_ids = (
        project_ids_via_role
        | project_ids_via_group
        | project_ids_via_org_wide
        | project_ids_via_nested_org_group
        | project_ids_via_direct_group_role
    )

    frontier = set(accessible_ids)
    iterations = 0
    while frontier and iterations < _ACCESSIBLE_EXPANSION_ITERATION_CAP:
        iterations += 1
        candidate_children = set(
            db.scalars(
                select(Project.id).where(
                    Project.parent_project_id.in_(frontier),
                    Project.role_inheritance_mode != ProjectRoleInheritanceMode.NONE,
                )
            ).all()
        )
        OwnerProject = aliased(Project)
        candidate_via_member_source = set(
            db.scalars(
                select(ProjectMemberSource.project_id)
                .join(Project, Project.id == ProjectMemberSource.source_project_id)
                .join(OwnerProject, OwnerProject.id == ProjectMemberSource.project_id)
                .where(
                    ProjectMemberSource.source_project_id.in_(frontier),
                    Project.organization_id == OwnerProject.organization_id,
                )
            ).all()
        )
        GroupOwnerProject = aliased(Project)
        candidate_via_project_ref_group = set(
            db.scalars(
                select(ProjectGroup.project_id)
                .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
                .join(GroupOwnerProject, GroupOwnerProject.id == ProjectGroup.project_id)
                .join(Project, Project.id == ProjectGroupMember.source_project_id)
                .where(
                    ProjectGroupMember.source_project_id.in_(frontier),
                    Project.organization_id == GroupOwnerProject.organization_id,
                )
            ).all()
        )
        new_frontier: set[UUID] = set()
        for candidate_id in (
            candidate_children | candidate_via_member_source | candidate_via_project_ref_group
        ) - accessible_ids:
            if get_effective_project_roles(db, user_id, candidate_id):
                accessible_ids.add(candidate_id)
                new_frontier.add(candidate_id)
        frontier = new_frontier

    return accessible_ids
