"""
Module: routers.projects.groups

Project groups (C-U-10/C-U-11, PR7 of the members/groups directory
rework — docs/decisions.md): bare-group creation, listing, per-group role
grant/revoke, deletion, and membership (user/org-group/source-project)
add/remove. A `ProjectGroup` can hold zero, one, or several
`ProjectRole`s at once, each independently revocable.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import ProjectRole
from app.models.notification import NotificationType
from app.models.organization import OrgGroup, OrgGroupMember
from app.models.project import Project, ProjectGroup, ProjectGroupMember, ProjectGroupRole
from app.models.user import User
from app.routers.projects.core import _require_user_in_org
from app.schemas.project import ProjectGroupCreate, ProjectGroupMemberAdd, ProjectGroupOut, ProjectGroupRoleAssign
from app.services import engagement
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.rbac import (
    _descendant_org_group_ids,
    _direct_project_member_ids_base,
    get_effective_project_managers,
    get_effective_project_roles,
    is_inherited_manager,
    lock_project_for_update,
    require_project_manage,
    require_project_view_or_manage,
)

router = APIRouter(tags=["projects-groups"])


@router.post("/{project_id}/groups", response_model=ProjectGroupOut, status_code=status.HTTP_201_CREATED)
def create_project_group(
    payload: ProjectGroupCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a bare project group with no role at all (PR7, docs/
    decisions.md) — a role is a separate, explicit grant added afterward via
    `POST /{project_id}/groups/{group_id}/roles`, symmetric with how
    `create_org_group` already creates an org group bare."""
    group = ProjectGroup(project_id=project.id, name=payload.name)
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="project_group", entity_id=group.id, action="created", actor_id=current_user.id,
        project_id=project.id, detail={"name": group.name},
    )
    db.commit()
    db.refresh(group)
    return ProjectGroupOut(id=group.id, name=group.name, roles=[],
                            member_user_ids=[], member_org_group_ids=[], member_source_project_ids=[])


@router.get("/{project_id}/groups", response_model=list[ProjectGroupOut])
def list_project_groups(
    project_id: UUID,
    response: Response,
    search: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists a project's groups, each with its resolved member/nested-org-
    group id lists.

    `search` (name substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are optional, same
    contract as `list_org_groups`: omitting `limit` returns every group
    unpaginated, and the pre-slice total is returned via `X-Total-Count`
    when given.

    `order` (Phase B, follow-up UX batch, 2026-08-31 — same reasoning as
    `list_org_groups`'s own `order` param) flips the existing name
    ascending order to descending; `DirectoryTable`'s Name column is this
    list's only sortable column, so there's no separate `sort` field param.
    """
    query = select(ProjectGroup).where(ProjectGroup.project_id == project_id)
    if search:
        query = query.where(ProjectGroup.name.ilike(f"%{search}%"))
    name_order = ProjectGroup.name.desc() if order == "desc" else ProjectGroup.name
    groups = db.scalars(query.order_by(name_order)).all()

    response.headers["X-Total-Count"] = str(len(groups))
    if limit is not None:
        groups = groups[offset:offset + limit]

    out = []
    for g in groups:
        members = db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == g.id)).all()
        roles = db.scalars(select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == g.id)).all()
        out.append(ProjectGroupOut(
            id=g.id, name=g.name, roles=list(roles),
            member_user_ids=[m.user_id for m in members if m.user_id],
            member_org_group_ids=[m.org_group_id for m in members if m.org_group_id],
            member_source_project_ids=[m.source_project_id for m in members if m.source_project_id],
        ))
    return out


def _get_group_in_project(db: Session, project_id: UUID, group_id: UUID) -> ProjectGroup:
    """Loads a project group and 404s unless it belongs to `project_id`.

    Without this check, a manager of *some* project (any project — that's
    all `require_project_manage` validates) could pass the `group_id` of a
    *different* project's "Project Managers" group and add themselves as a
    member, inheriting that project's manager role — a privilege escalation
    across the project boundary.
    """
    group = db.get(ProjectGroup, group_id)
    if group is None or group.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project group not found.")
    return group


@router.post("/{project_id}/groups/{group_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_group_role(
    project_id: UUID, group_id: UUID, payload: ProjectGroupRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grants a project group one more role (PR7, docs/decisions.md) —
    replaces the old `PATCH /{project_id}/groups/{group_id}` "change the
    group's one role" endpoint now that a group can hold zero, one, or
    several roles at once: each is its own independently-revocable
    `ProjectGroupRole` row rather than a single mutable field. Mirrors
    `assign_group_project_role` (PR4's org-group-role grant, in
    `routers.projects.roles`) as closely as sensible, adapted for a
    project-group target instead of an org-group one — same 204-no-body
    shape, and no cross-tenant check is needed here (unlike that endpoint's
    `org_group_id` re-validation), since a `ProjectGroup` already belongs
    to exactly one project by construction; `_get_group_in_project` already
    404s if `group_id` doesn't belong to `project_id` at all.

    Idempotent like `assign_group_project_role`/`assign_project_role`:
    granting an already-held role is a silent no-op, not a 409 — no audit
    event or commit happens on the no-op path.
    """
    _get_group_in_project(db, project.id, group_id)
    existing = db.scalar(
        select(ProjectGroupRole).where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(ProjectGroupRole(project_group_id=group_id, role=payload.role))
        log_event(
            db, entity_type="project_group", entity_id=group_id, action="role_granted", actor_id=current_user.id,
            project_id=project.id, detail={"role": payload.role.value},
        )
        db.commit()


@router.delete("/{project_id}/groups/{group_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_group_role(
    project_id: UUID, group_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes one role from a project group (PR7) — the group-scoped
    C-U-08 guard site this PR adds, shaped like `delete_project_group`'s
    (lock the project row, perform the delete, flush, then re-check
    `get_effective_project_managers` before commit) rather than a single-
    user pre-check, since revoking a group's role can remove effective
    access from every member of that group at once. Same defense-in-depth
    reasoning as `revoke_group_project_role`'s own C-U-08 guard (in
    `routers.projects.roles`): a `ProjectGroup`'s *direct user* members DO
    count towards the C-U-08 floor via `_direct_project_managers` (unlike a
    nested/direct org group), so this guard is the one that actually
    matters in practice for this mechanism, not just a defensive fallback —
    see docs/decisions.md's identify/verify/remediate entry for this
    endpoint.
    """
    _get_group_in_project(db, project.id, group_id)
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
    removed = db.execute(
        ProjectGroupRole.__table__.delete().where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == role,
        )
    )
    db.flush()
    if role == ProjectRole.PROJECT_MANAGER and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    if removed.rowcount:
        log_event(
            db, entity_type="project_group", entity_id=group_id, action="role_revoked", actor_id=current_user.id,
            project_id=project.id, detail={"role": role.value},
        )
        # Same per-member engagement cleanup `revoke_group_project_role`
        # applies for its own (potentially many-user) revocation: a group's
        # role can be one of several sources a member holds it through, so
        # only clean up subscriptions/favourites for someone this actually
        # left with no remaining access at all.
        affected_user_ids = {
            m.user_id
            for m in db.scalars(
                select(ProjectGroupMember).where(
                    ProjectGroupMember.project_group_id == group_id, ProjectGroupMember.user_id.is_not(None),
                )
            ).all()
        }
        for affected_user_id in affected_user_ids:
            if not get_effective_project_roles(db, affected_user_id, project.id):
                engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()


@router.delete("/{project_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_group(
    project_id: UUID, group_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a project group entirely; its `ProjectGroupMember` rows go
    with it via `ondelete="CASCADE"`. No group is specially protected from
    deletion any more (follow-up UX batch Phase C, 2026-08-31 removed the
    four auto-created "standard" groups and their `is_default` flag
    entirely — see docs/decisions.md) — the only thing standing between a
    delete and an unmanaged project is the C-U-08 guard immediately below,
    which applies identically to every group regardless of how it was
    created.

    Same C-U-08 guard as `assign_project_group_role`/`revoke_project_group_
    role`, shaped for a whole-group removal rather than a single-role
    change: if this group currently holds a `PROJECT_MANAGER` grant (PR7:
    checked against `ProjectGroupRole`, not the old scalar `ProjectGroup.
    role`), the project row is locked first, then the group (and every
    membership/role under it) is deleted and flushed, then `get_effective_
    project_managers` is re-checked before commit. The check has to run
    *after* the delete is flushed, not before, unlike `remove_project_group_
    member`'s single-membership check — a whole-group delete removes every
    membership at once, so a pre-check would have to reproduce "what would
    managers look like without this group" rather than just asking the
    normal live-state question afterward.
    """
    group = _get_group_in_project(db, project.id, group_id)

    group_roles = list(db.scalars(select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == group_id)).all())
    is_manager_group = ProjectRole.PROJECT_MANAGER in group_roles
    if is_manager_group:
        lock_project_for_update(db, project.id)

    log_event(
        db, entity_type="project_group", entity_id=group_id, action="deleted", actor_id=current_user.id,
        project_id=project.id, detail={"name": group.name, "roles": [r.value for r in group_roles]},
    )
    db.delete(group)
    db.flush()
    if is_manager_group and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.commit()


@router.post("/{project_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_project_group_member(
    project_id: UUID, group_id: UUID, payload: ProjectGroupMemberAdd,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_count = sum(x is not None for x in (payload.user_id, payload.org_group_id, payload.source_project_id))
    if target_count != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide exactly one of user_id, org_group_id, source_project_id.")
    _get_group_in_project(db, project.id, group_id)
    if payload.user_id is not None:
        # C-U-02: "All Project users, must be an organisation user."
        _require_user_in_org(db, payload.user_id, project.organization_id)
    if payload.org_group_id is not None:
        # Nesting an org group from a *different* organisation would let its
        # members inherit this project's role, crossing the tenant boundary
        # (organisations are the tenant boundary per C-U-02).
        org_group = db.get(OrgGroup, payload.org_group_id)
        if org_group is None or org_group.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
    if payload.source_project_id is not None:
        # Same cross-tenant boundary as org_group_id above, plus a
        # self-reference guard (a project referencing its own roster is
        # meaningless and would recurse straight into itself if the
        # non-recursive one-hop guarantee ever changed) — see
        # `models.project.ProjectGroupMember.source_project_id`'s docstring.
        if payload.source_project_id == project.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must not be this project itself.")
        source_project = db.get(Project, payload.source_project_id)
        if source_project is None or source_project.organization_id != project.organization_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "source_project_id must belong to the project's organisation."
            )
    db.add(ProjectGroupMember(
        project_group_id=group_id, user_id=payload.user_id, org_group_id=payload.org_group_id,
        source_project_id=payload.source_project_id,
    ))
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
        project_id=project.id,
        detail={"user_id": str(payload.user_id) if payload.user_id else None,
                "org_group_id": str(payload.org_group_id) if payload.org_group_id else None,
                "source_project_id": str(payload.source_project_id) if payload.source_project_id else None},
    )
    if payload.user_id is not None:
        added_user = db.get(User, payload.user_id)
        if added_user is not None:
            group = db.get(ProjectGroup, group_id)
            notify(
                db, added_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were added to the '{group.name}' group." if group else "",
                project_id=project.id, actor_id=current_user.id,
            )
    db.commit()


@router.delete("/{project_id}/groups/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_group_member(
    project_id: UUID, group_id: UUID, member_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Removes a member (user or nested org group) from a project group.

    Blocks the removal if `group` currently holds a `PROJECT_MANAGER` grant
    (PR7: checked against `ProjectGroupRole`, not the old scalar
    `ProjectGroup.role` — a group can now hold that grant alongside others)
    and `member_id` is currently the project's only manager (C-U-08),
    mirroring the same guard `revoke_project_role` (in `routers.projects.
    roles`) applies to direct role revocation — a project must always
    retain at least one manager. Same `is_inherited_manager` exception as
    that guard: removing this membership is safe if `member_id` would
    remain a manager via forward inheritance alone (member_id may be a
    user id, an org-group id, or a source-project id here —
    `is_inherited_manager` only applies to a real user, so a group/
    project-reference removal always falls through to the block, unchanged
    from before).
    """
    _get_group_in_project(db, project.id, group_id)
    group_is_manager = db.scalar(
        select(ProjectGroupRole).where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == ProjectRole.PROJECT_MANAGER,
        )
    ) is not None
    if group_is_manager:
        lock_project_for_update(db, project.id)
        managers = get_effective_project_managers(db, project.id)
        if managers == {member_id} and not is_inherited_manager(db, member_id, project.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    removed_member = db.scalar(
        select(ProjectGroupMember).where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id)
            | (ProjectGroupMember.org_group_id == member_id)
            | (ProjectGroupMember.source_project_id == member_id),
        )
    )
    db.execute(
        ProjectGroupMember.__table__.delete().where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id)
            | (ProjectGroupMember.org_group_id == member_id)
            | (ProjectGroupMember.source_project_id == member_id),
        )
    )
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        project_id=project.id, detail={"member_id": str(member_id)},
    )
    # Resolve the real user(s) this removal can actually affect. `member_id`
    # may be a real user id, an org-group id, or a source-project id (see
    # this function's own docstring) — only the first can be checked
    # directly against get_effective_project_roles. Pre-existing gap fixed
    # here (found while building revoke_group_project_role's own equivalent
    # cleanup — see docs/decisions.md): for the other two kinds this used to
    # call get_effective_project_roles(db, member_id, ...) with a group/
    # project id standing in for a user id — since no real user has that id,
    # the check always vacuously "passed" and remove_subscriptions_and_
    # favorites_for_projects was called with that same non-user id, so a
    # nested-group or project-reference removal never actually cleaned up
    # the real former members' subscriptions/favourites. Resolves each
    # kind's real member set first instead, same pattern
    # revoke_group_project_role uses for its own group-level cleanup.
    if removed_member is None:
        affected_user_ids: set[UUID] = set()
    elif removed_member.user_id is not None:
        affected_user_ids = {removed_member.user_id}
    elif removed_member.org_group_id is not None:
        affected_user_ids = set(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(
                        {removed_member.org_group_id} | _descendant_org_group_ids(db, {removed_member.org_group_id})
                    ),
                    OrgGroupMember.user_id.is_not(None),
                )
            ).all()
        )
    else:
        affected_user_ids = _direct_project_member_ids_base(db, removed_member.source_project_id)
    # A group can grant a role alongside other direct/group roles a user
    # holds on the same project, so only clean up subscriptions/favourites
    # for someone this removal actually left with no remaining access — not
    # on every membership change.
    for affected_user_id in affected_user_ids:
        if not get_effective_project_roles(db, affected_user_id, project.id):
            engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()
