"""
Module: routers.projects.hierarchy

Parent/child project hierarchy (ancestors/children breadcrumb, detach), the member-source mechanism
(`models.project.ProjectMemberSource`) and the access-inheritance surfaces built on both: effective members
with provenance, and the "materialize inherited access" endpoints that snapshot an inherited role onto a
direct grant (decisions 9/10/11 in docs/decisions.md).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ProjectRole
from app.models.module_role import UserModuleRole
from app.models.organization import Organization, OrgGroup
from app.models.project import FavoriteProject, OrgGroupProjectRole, Project, ProjectMemberSource, ProjectStage, UserProjectRole
from app.models.stage_workflow import StageWorkflowPhase
from app.models.user import User
from app.modules.registry import list_enabled_module_roles
from app.routers.projects.core import _accessible_project_ids
from app.schemas.org import ModuleRoleGrantOut
from app.schemas.project import (
    EffectiveMemberOut,
    MaterializeResultOut,
    MemberSourceProvenanceOut,
    ProjectAncestorOut,
    ProjectListItemOut,
    ProjectMemberSourceAdd,
    ProjectMemberSourceOut,
)
from app.schemas.project_scope import ProjectScopeOptionsOut
from app.services.audit import log_event
from app.services.project_hierarchy import get_ancestor_chain
from app.services.project_scope import scope_options
from app.services.rbac import (
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_members_with_provenance,
    get_effective_project_roles,
    get_group_inherited_project_roles,
    is_org_admin,
    lock_project_for_update,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)

router = APIRouter(tags=["projects-hierarchy"])

_ROLE_RANK = {
    ProjectRole.MEMBER: 0, ProjectRole.STAKEHOLDER: 1,
    ProjectRole.PROJECT_ADMINISTRATOR: 1, ProjectRole.PROJECT_MANAGER: 2,
}


@router.get("/{project_id}/ancestors", response_model=list[ProjectAncestorOut])
def get_project_ancestors(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns `project_id`'s ancestor chain, root-first, for a breadcrumb.

    Truncated at the first ancestor the caller cannot view; it never skips an inaccessible ancestor to list
    further-up ones, which would present a misleading breadcrumb (visibility-boundary rule, docs/decisions.md).

    Org-admin bypass: an org admin of `project_id`'s organisation sees the true, untruncated chain
    regardless of their role on any ancestor, through an explicit `or is_org_admin(...)` at this call site
    rather than a change to `_accessible_project_ids` (docs/decisions.md's "Project hierarchy on Project
    Overview" entry). Keying off `project_id`'s organisation is safe because `parent_project_id` is validated
    same-organisation at write time in `create_project` and `update_project`. Gated by
    `require_project_view_or_manage`.
    """
    anchor_organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    admin_bypass = anchor_organization_id is not None and is_org_admin(db, current_user.id, anchor_organization_id)
    accessible_ids = _accessible_project_ids(db, current_user.id)
    chain = get_ancestor_chain(db, project_id)
    result: list[ProjectAncestorOut] = []
    for ancestor in chain:
        if not admin_bypass and ancestor.id not in accessible_ids:
            break
        result.append(ProjectAncestorOut(id=ancestor.id, name=ancestor.name))
    return result


@router.get("/{project_id}/children", response_model=list[ProjectListItemOut])
def get_project_children(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns `project_id`'s direct children, filtered to the caller's accessible set, with no hint of how
    many were omitted (the visibility-boundary rule of `list_projects`'s `children` field).

    Org-admin bypass: an org admin of `project_id`'s organisation sees every true child regardless of their
    role on it. A child is always same-organisation as its parent (enforced at write time, see
    `get_project_ancestors`), so `project_id`'s organisation is the one to check.
    """
    anchor_organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    admin_bypass = anchor_organization_id is not None and is_org_admin(db, current_user.id, anchor_organization_id)
    accessible_ids = _accessible_project_ids(db, current_user.id)
    children_filter = (
        Project.parent_project_id == project_id
        if admin_bypass
        else (Project.parent_project_id == project_id) & Project.id.in_(accessible_ids)
    )
    children = db.scalars(select(Project).where(children_filter)).all()
    favorite_ids = set(
        db.scalars(select(FavoriteProject.project_id).where(FavoriteProject.user_id == current_user.id)).all()
    )
    org_names = dict(
        db.execute(
            select(Organization.id, Organization.name).where(
                Organization.id.in_({c.organization_id for c in children})
            )
        ).tuples().all()
    )
    out = []
    for c in children:
        stage = db.scalar(select(ProjectStage).where(ProjectStage.project_id == c.id, ProjectStage.is_current.is_(True)))
        phase = db.get(StageWorkflowPhase, stage.phase_id) if stage else None
        roles = sorted(get_effective_project_roles(db, current_user.id, c.id), key=lambda r: r.value)
        out.append(
            ProjectListItemOut(
                id=c.id, organization_id=c.organization_id, name=c.name, code=c.code, summary=c.summary,
                created_at=c.created_at, updated_at=c.updated_at,
                is_archived=c.is_archived, is_template=c.is_template,
                allow_member_change_requests=c.allow_member_change_requests,
                require_change_request_for_approved_links=c.require_change_request_for_approved_links,
                exempt_from_org_link_lock=c.exempt_from_org_link_lock, allow_ai_approvals=c.allow_ai_approvals,
                visibility=c.visibility,
                terminology=c.terminology, status_id=c.status_id,
                current_stage_name=stage.name if stage else None,
                current_stage_phase_name=phase.name if phase else None,
                current_stage_phase_kind=phase.kind if phase else None,
                my_roles=list(roles), is_favorite=c.id in favorite_ids,
                organization_name=org_names.get(c.organization_id, ""),
                parent_project_id=project_id, parent_project_name=None,
                role_inheritance_mode=c.role_inheritance_mode, role_inheritance_filter_role=c.role_inheritance_filter_role,
                can_be_parent=c.can_be_parent,
            )
        )
    return out


@router.get("/{project_id}/scope-options", response_model=ProjectScopeOptionsOut)
def get_project_scope_options(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Which list-scope choices (`project_scope` on every list) this project offers the caller:
    whether they can open a parent and/or a child project. Counts only projects the caller can
    open, so it never reveals that a hidden one exists."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return scope_options(db, project, current_user.id)


@router.get("/{project_id}/member-sources", response_model=list[ProjectMemberSourceOut])
def list_member_sources(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists the other same-organisation projects `project_id` currently
    consumes members from (the reverse/source->receiving RBAC mechanism —
    see `models.project.ProjectMemberSource`'s docstring)."""
    rows = db.execute(
        select(
            ProjectMemberSource.source_project_id, Project.name,
            ProjectMemberSource.mirror_mode, ProjectMemberSource.mirror_filter_role,
        )
        .join(Project, Project.id == ProjectMemberSource.source_project_id)
        .where(ProjectMemberSource.project_id == project_id)
    ).all()
    return [
        ProjectMemberSourceOut(source_project_id=sid, source_project_name=name, mirror_mode=mode, mirror_filter_role=filter_role)
        for sid, name, mode, filter_role in rows
    ]


@router.post("/{project_id}/member-sources", response_model=ProjectMemberSourceOut, status_code=status.HTTP_201_CREATED)
def add_member_source(
    project_id: UUID, payload: ProjectMemberSourceAdd, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Adds another project to `project_id`'s member-source list. Gated by managing `project_id` (the
    receiving side) only, never the source (the authorisation asymmetry described in
    `models.project.ProjectMemberSource` and docs/decisions.md).

    `source_project_id` must belong to `project_id`'s own organisation (any project in it, not only a direct
    child). No separate accessible-set check: the caller already manages `project_id`, and requiring a role on
    the source would defeat the feature, since a manager must be able to consume members from any project they
    know about in their organisation, including one with no role structure yet. Project names are not
    confidential within an organisation, so this creates no existence-oracle concern as an accessible-set
    restriction on `parent_project_id` selection would.
    """
    source_project_id = payload.source_project_id
    if source_project_id == project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must not be this project itself.")
    source_project = db.get(Project, source_project_id)
    if source_project is None or source_project.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must belong to this project's organisation.")
    existing = db.scalar(
        select(ProjectMemberSource).where(
            ProjectMemberSource.project_id == project_id, ProjectMemberSource.source_project_id == source_project_id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project is already a member source.")
    db.add(ProjectMemberSource(
        project_id=project_id, source_project_id=source_project_id,
        mirror_mode=payload.mirror_mode, mirror_filter_role=payload.mirror_filter_role,
    ))
    log_event(
        db, entity_type="project_member_source", entity_id=project_id, action="added", actor_id=current_user.id,
        project_id=project_id, organization_id=project.organization_id,
        detail={
            "source_project_id": str(source_project_id), "mirror_mode": payload.mirror_mode.value,
            "mirror_filter_role": payload.mirror_filter_role.value if payload.mirror_filter_role else None,
        },
    )
    db.commit()
    return ProjectMemberSourceOut(
        source_project_id=source_project_id, source_project_name=source_project.name,
        mirror_mode=payload.mirror_mode, mirror_filter_role=payload.mirror_filter_role,
    )


@router.delete("/{project_id}/member-sources/{source_project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_source(
    project_id: UUID, source_project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Removes a child from `project_id`'s member-source list — always
    allowed (removing a grant is safe unilaterally), including for an
    already-stale entry."""
    existing = db.scalar(
        select(ProjectMemberSource).where(
            ProjectMemberSource.project_id == project_id, ProjectMemberSource.source_project_id == source_project_id
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="project_member_source", entity_id=project_id, action="removed", actor_id=current_user.id,
            project_id=project_id, organization_id=project.organization_id,
            detail={"source_project_id": str(source_project_id)},
        )
        db.commit()


@router.delete("/{project_id}/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_child_project(
    child_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Lets a parent detach a specific child from its own side, without `require_project_manage` on the child
    (decision 12 in docs/decisions.md). Gated on managing `project_id` (the parent; `require_project_manage`'s
    `{project_id}` path parameter is why the route uses `project_id` rather than `parent_id`). Still subject to
    the child's `Project.parent_required` gate (decision 11): a parent's manage rights alone cannot force a
    `parent_required` child loose, the same rule `update_project` applies to a child-initiated detach.
    """
    parent_id = project.id
    child = db.get(Project, child_id)
    if child is None or child.parent_project_id != parent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This project is not a direct child of the given parent.")
    lock_project_for_update(db, child_id)
    if child.parent_required:
        org_roles = get_effective_org_roles(db, current_user.id, child.organization_id)
        if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This project was created without organisation-level project-creation rights and must remain "
                "nested under a parent; only an organisation admin or project creator can detach it.",
            )
    proposed_managers = get_effective_project_managers(
        db, child_id, parent_override_set=True, parent_override=None,
    )
    if not proposed_managers:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{child.name}''s only manager is inherited from this project; it must be given a direct project "
            "manager before it can be detached.",
        )
    child.parent_project_id = None
    log_event(
        db, entity_type="project", entity_id=child_id, action="detached_by_parent", actor_id=current_user.id,
        project_id=child_id, organization_id=child.organization_id, detail={"former_parent_id": str(parent_id)},
    )
    db.commit()


@router.get("/{project_id}/effective-members", response_model=list[EffectiveMemberOut])
def get_effective_members(
    project_id: UUID,
    response: Response,
    search: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Every user with effective access to this project, with provenance: direct (and which of the five direct
    sources, see `MemberSourceProvenanceOut`) or inherited (and how), for the project admin/access-review view
    (decision 10 in docs/decisions.md) and the unified Members table (decision 11). `require_project_manage`
    gated: an access-review surface for people who already manage the project (see the forward and
    member-source inheritance discussion in docs/decisions.md for why this discloses nothing beyond what
    `role_inheritance_mode` already implies).

    `search` (case-insensitive name/email substring) and `limit`/`offset` are optional, as
    `list_project_groups`: omitting `limit` returns every match unpaginated; when given, the post-search,
    pre-slice total is returned via `X-Total-Count`.

    Pagination is application-level: `get_effective_project_members_with_provenance` resolves every candidate
    user's full provenance in Python (it iterates every user in the organisation, for an admin view opened
    occasionally), and `search`/`limit`/`offset` are applied as an in-memory slice after a deterministic sort
    by `display_name` (case-insensitive), not pushed into SQL. This does not scale as a database-level
    `LIMIT`/`OFFSET` would; it suits a project admin's realistic member-list size.
    """
    provenance = get_effective_project_members_with_provenance(db, project_id)
    project_name_cache: dict[UUID, str] = {}

    def project_name(pid: UUID | None) -> str | None:
        if pid is None:
            return None
        if pid not in project_name_cache:
            p = db.get(Project, pid)
            project_name_cache[pid] = p.name if p is not None else ""
        return project_name_cache[pid] or None

    # This project's module-contributed role grants, filtered to currently enabled modules (see
    # `ModuleRoleGrantOut`; filter, don't delete), computed once for the response and attached per member below.
    enabled_project_role_keys = {
        (module_key, role.role_key)
        for module_key, role in list_enabled_module_roles(db, project.organization_id, "project")
    }
    module_roles_by_user: dict[UUID, list[ModuleRoleGrantOut]] = {}
    if enabled_project_role_keys:
        module_role_rows = db.execute(
            select(UserModuleRole.user_id, UserModuleRole.module_key, UserModuleRole.role_key).where(
                UserModuleRole.project_id == project_id
            )
        ).all()
        for user_id, module_key, role_key in module_role_rows:
            if (module_key, role_key) in enabled_project_role_keys:
                module_roles_by_user.setdefault(user_id, []).append(
                    ModuleRoleGrantOut(module_key=module_key, role_key=role_key)
                )

    out: list[EffectiveMemberOut] = []
    for user_id, entries in provenance.items():
        user = db.get(User, user_id)
        if user is None:
            continue
        effective_roles = get_effective_project_roles(db, user_id, project_id)
        if not effective_roles:
            continue
        if ProjectRole.PROJECT_MANAGER in effective_roles:
            effective_role = ProjectRole.PROJECT_MANAGER
        elif ProjectRole.PROJECT_ADMINISTRATOR in effective_roles:
            effective_role = ProjectRole.PROJECT_ADMINISTRATOR
        elif ProjectRole.STAKEHOLDER in effective_roles:
            effective_role = ProjectRole.STAKEHOLDER
        else:
            effective_role = ProjectRole.MEMBER
        out.append(
            EffectiveMemberOut(
                user_id=user_id, display_name=user.display_name, email=user.email, effective_role=effective_role,
                is_service_account=user.is_service_account,
                sources=[
                    MemberSourceProvenanceOut.model_validate({
                        "kind": e["kind"], "role": e["role"], "via_project_id": e["via_project_id"],
                        "via_project_name": project_name(e["via_project_id"]), "via_mode": e["via_mode"],
                        "via_group_id": e["via_group_id"], "via_group_name": e["via_group_name"],
                    })
                    for e in entries
                ],
                module_roles=module_roles_by_user.get(user_id, []),
            )
        )

    out.sort(key=lambda m: m.display_name.lower())
    if search:
        needle = search.lower()
        out = [m for m in out if needle in m.display_name.lower() or needle in m.email.lower()]

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.post("/{project_id}/materialize-inherited-access", response_model=MaterializeResultOut)
def materialize_inherited_access(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Snapshots every currently forward- or member-source-inherited user onto a direct `UserProjectRole` row
    at their currently effective role (decision 9 in docs/decisions.md): a one-time conversion, not an
    ongoing sync, so those users keep access after inheritance is disabled, changed or removed. Idempotent:
    skips anyone who already holds an equal-or-higher direct role. Offered before disabling a
    manager-contributing mode, reparenting or removing a member-source entry, so nobody's access disappears.
    """
    provenance = get_effective_project_members_with_provenance(db, project_id)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for user_id, entries in provenance.items():
        inherited_roles = {e["role"] for e in entries if e["kind"] in ("forward_inherited", "member_source_inherited")}
        if not inherited_roles:
            continue
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(UserProjectRole.role).where(UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id)
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"user_id": str(user_id), "role": best_inherited.value})
            continue
        db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=best_inherited))
        created.append({"user_id": str(user_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="project", entity_id=project_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)


@router.post("/{project_id}/materialize-inherited-access/{user_id}", response_model=MaterializeResultOut)
def materialize_inherited_access_for_user(
    project_id: UUID, user_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Per-row counterpart to `materialize_inherited_access` (`ProjectMembersTable`'s per-member "Convert
    inherited access to direct roles" action): the same rank logic, idempotency and audit action, filtered to
    `user_id`'s provenance entries. A no-op if the user holds no forward- or member-source-inherited role, or
    their direct role already ranks at or above their best inherited one. Access-mutating (identify -> verify
    -> remediate review, docs/decisions.md), since it can create an independently revocable `UserProjectRole`.
    """
    provenance = get_effective_project_members_with_provenance(db, project_id)
    entries = provenance.get(user_id, [])
    inherited_roles = {e["role"] for e in entries if e["kind"] in ("forward_inherited", "member_source_inherited")}
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if inherited_roles:
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(UserProjectRole.role).where(UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id)
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"user_id": str(user_id), "role": best_inherited.value})
        else:
            db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=best_inherited))
            created.append({"user_id": str(user_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="project", entity_id=project_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created, "target_user_id": str(user_id)},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)


@router.post("/{project_id}/materialize-inherited-access/group/{org_group_id}", response_model=MaterializeResultOut)
def materialize_inherited_access_for_group(
    project_id: UUID, org_group_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Group-scoped counterpart to `materialize_inherited_access`: converts an org group's own forward- or
    member-source-inherited role on this project (`get_group_inherited_project_roles`, walking ancestor and
    source projects' `OrgGroupProjectRole` grants for this group) into a direct `OrgGroupProjectRole` grant,
    as the per-user endpoint converts a user's inherited role into a direct `UserProjectRole`.

    It applies `assign_group_project_role`'s cross-tenant re-check of `org_group_id`, the rank-based "skip if
    an equal-or-higher direct role is held" idempotency of the bulk and per-user endpoints, and the audit
    action `"inherited_access_materialized"` with entity type `org_group_project_role` (as
    `assign_group_project_role`).

    No UI row kind currently represents an org group's own `OrgGroupProjectRole` provenance (the Groups
    directory, `ProjectAdminPage.tsx`'s `groupsTabRows`, has only direct `ProjectGroup` rows and
    `ProjectMemberSource` virtual rows), so no screen calls it; it is covered directly through the API
    (see docs/decisions.md).
    """
    org_group = db.get(OrgGroup, org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")

    inherited_roles = get_group_inherited_project_roles(db, org_group_id, project_id)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if inherited_roles:
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(OrgGroupProjectRole.role).where(
                    OrgGroupProjectRole.org_group_id == org_group_id, OrgGroupProjectRole.project_id == project_id,
                )
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"org_group_id": str(org_group_id), "role": best_inherited.value})
        else:
            db.add(OrgGroupProjectRole(org_group_id=org_group_id, project_id=project_id, role=best_inherited))
            created.append({"org_group_id": str(org_group_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="org_group_project_role", entity_id=org_group_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)
