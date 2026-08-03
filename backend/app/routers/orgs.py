"""
Module: routers.orgs

Organisation management: creating organisations and organisation users
(I-M-05, server-admin only), organisation role assignment, user
deactivation/archival (C-U-04, C-U-05), and organisation groups (C-U-08,
C-U-12).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.file import FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, ReportTemplate, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User
from app.schemas.file import FileAssetOut
from app.schemas.org import (
    DefaultTemplateUpdate,
    DisplayNameLockUpdate,
    OrgAdvancedSettingsOut,
    OrgAdvancedSettingsUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrgGroupCreate,
    OrgGroupMemberAdd,
    OrgGroupOut,
    OrgLoginInfoOut,
    OrgRoleAssign,
    OrgSsoConfigOut,
    OrgSsoConfigUpdate,
    OrgUserCreate,
    OrgUserOut,
    ReportTemplateCreate,
    ReportTemplateOut,
)
from app.security import hash_password
from app.services import engagement
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.notifications import notify
from app.services.rbac import (
    get_effective_org_roles,
    get_project_managers,
    require_org_admin_or_server_admin,
    require_org_role,
    require_server_admin,
)

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Creates a new organisation. Server-admin only (I-M-05)."""
    org = Organization(name=payload.name)
    db.add(org)
    db.flush()
    log_event(db, entity_type="organization", entity_id=org.id, action="created", actor_id=current_user.id)
    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lists organisations. Server admins see all; other users see only orgs they belong to.

    This one server-admin bypass is kept deliberately (unlike every other
    org-scoped endpoint, see I-M-05 in rbac.py): `OrganizationOut` is thin
    directory metadata (id/name/logo/created_at), not "data within the
    organisation", and the server admin needs to see an org exists at all in
    order to complete the one capability I-M-05 actually grants them —
    creating that organisation's initial user.
    """
    if current_user.is_server_admin:
        return db.scalars(select(Organization)).all()
    org_ids = db.scalars(
        select(UserOrgRole.organization_id).where(UserOrgRole.user_id == current_user.id)
    ).all()
    if not org_ids:
        return []
    return db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if not current_user.is_server_admin and not get_effective_org_roles(db, current_user.id, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
    return org


@router.post("/{organization_id}/users", response_model=OrgUserOut, status_code=status.HTTP_201_CREATED)
def create_org_user(
    organization_id: UUID,
    payload: OrgUserCreate,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Creates a new user directly within an organisation (I-M-05 clarification).

    Server admins may call this even with no role of their own in the target
    organisation — this is the one documented carve-out (creating the
    initial user of a newly created org). Every other org-scoped endpoint
    requires a genuine org role.
    """
    if db.scalar(select(User).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_backend="native",
    )
    db.add(user)
    db.flush()
    db.add(UserOrgRole(user_id=user.id, organization_id=organization_id, role=payload.role))
    log_event(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgUserOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_archived=user.is_archived,
        roles=[payload.role],
    )


@router.get("/{organization_id}/users", response_model=list[OrgUserOut])
def list_org_users(
    organization_id: UUID,
    stale_since_days: int | None = Query(None, ge=0),
    never_logged_in: bool | None = None,
    has_2fa: bool | None = None,
    org_role: OrgRole | None = None,
    has_project_access: bool | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists users belonging to an organisation with their org roles.

    Archived users are excluded (C-U-05: an archived user "no longer
    show[s] as users", though their past contributions stay attributed to
    them elsewhere via the unaffected `creator_id`/`actor_id` foreign keys).

    The access-review filters (C-A-13) — `stale_since_days`,
    `never_logged_in`, `has_2fa`, `org_role`, `has_project_access`,
    `is_active` — are org-admin only; a plain member/project-creator can
    still call this endpoint unfiltered for the general member directory
    (existing behavior), but supplying any filter requires org-admin,
    scoped to *this* organisation via `organization_id` (not "an org admin
    somewhere else" — same pattern as every other org-scoped admin check).
    """
    filters_requested = any(
        v is not None for v in (stale_since_days, never_logged_in, has_2fa, org_role, has_project_access, is_active)
    )
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    if filters_requested and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation admin may use access-review filters.")

    rows = db.execute(
        select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, User.is_archived.is_(False)
        )
    ).all()
    by_user: dict[UUID, OrgUserOut] = {}
    for user, role in rows:
        if user.id not in by_user:
            by_user[user.id] = OrgUserOut(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                is_archived=user.is_archived,
                roles=[],
                display_name_locked=user.display_name_locked,
                # C-A-13 access-review data: real values only for org admins
                # (matching the filter gate above) — a plain member calling
                # this same endpoint for the general directory must not
                # receive other members' account-security posture.
                last_login_at=user.last_login_at if is_admin else None,
                is_2fa_enabled=user.is_2fa_enabled if is_admin else False,
            )
        by_user[user.id].roles.append(role)

    results = list(by_user.values())
    if is_active is not None:
        results = [r for r in results if r.is_active == is_active]
    if has_2fa is not None:
        results = [r for r in results if r.is_2fa_enabled == has_2fa]
    if org_role is not None:
        results = [r for r in results if org_role in r.roles]
    if never_logged_in:
        results = [r for r in results if r.last_login_at is None]
    if stale_since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=stale_since_days)
        results = [r for r in results if r.last_login_at is None or r.last_login_at < cutoff]
    if has_project_access is not None:
        access_ids = _org_users_with_project_access(db, organization_id)
        results = [r for r in results if (r.user_id in access_ids) == has_project_access]
    return results


def _org_users_with_project_access(db: Session, organization_id: UUID) -> set[UUID]:
    """User ids with at least one direct project role or direct project-group
    membership on any project in this organisation (used by the
    `has_project_access` access-review filter, C-A-13). Direct resolution
    only, not nested org groups — matches the same scope already used by
    `get_project_managers` for similar bulk/administrative queries."""
    direct_role_ids = set(
        db.scalars(
            select(UserProjectRole.user_id)
            .join(Project, Project.id == UserProjectRole.project_id)
            .where(Project.organization_id == organization_id)
        ).all()
    )
    direct_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .where(Project.organization_id == organization_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    return direct_role_ids | direct_group_ids


@router.put("/{organization_id}/users/{user_id}/display-name-lock", status_code=status.HTTP_204_NO_CONTENT)
def set_display_name_lock(
    organization_id: UUID,
    user_id: UUID,
    payload: DisplayNameLockUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Locks or unlocks a user's ability to change their own display name (C-U-16)."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.display_name_locked = payload.display_name_locked
    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="display_name_lock_changed",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"display_name_locked": payload.display_name_locked},
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_org_role(
    organization_id: UUID,
    user_id: UUID,
    payload: OrgRoleAssign,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Grants an organisation role to a user (C-U-01).

    The affected user is always the `{user_id}` path parameter, not
    `payload.user_id` — the request body's `role` field is the only part of
    the payload actually used; a mismatched body `user_id` is ignored rather
    than trusted, so the URL a caller is authorized against (and what ends
    up in the audit trail) can never diverge from who is actually affected.
    """
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == user_id,
            UserOrgRole.organization_id == organization_id,
            UserOrgRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserOrgRole(user_id=user_id, organization_id=organization_id, role=payload.role))
        log_event(
            db,
            entity_type="user_org_role",
            entity_id=user_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            detail={"role": payload.role.value},
        )
        granted_user = db.get(User, user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{payload.role.value}' role in an organisation.",
            )
        db.commit()


@router.delete("/{organization_id}/membership", status_code=status.HTTP_204_NO_CONTENT)
def leave_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: the caller removes their own membership in an organisation.

    Previously there was no way for a user to leave an org at all — see
    docs/e2e-workflows.md's "product gaps found" section, which this closes.

    Refuses (409) rather than silently reassigning anyone else's roles if
    leaving would strip the organisation of its last org_admin, or leave any
    of its projects with zero managers. Unlike `deactivate_org_user`'s C-U-09
    fallback (which reassigns the *acting admin* as a project's new manager
    when removing someone else), there is no natural recipient for that
    reassignment here — the caller is the one leaving — so this endpoint
    asks the caller to reassign those roles first instead of guessing who
    should inherit them.

    Also removes the caller's `OrgGroupMember` rows for this organisation's
    groups, not just their direct project roles/memberships — project access
    can be granted through an org group nested into a project group (C-U-12),
    and `get_project_managers` (used for the sole-manager guard below)
    deliberately only resolves *direct* managers, not nested-group-derived
    ones (see its own docstring). Leaving that cleanup out would let a user
    "leave" an org while silently retaining full project access through a
    still-active session — this endpoint checks both direct and
    nested-group-derived manager status precisely because of that gap.

    Locks the organisation row for the duration of this transaction
    (`lock_organization_for_update`) before doing anything else, and each
    project row in turn before checking its manager count
    (`lock_project_for_update`) — without this, two concurrent leavers (e.g.
    an org's last two admins, or a project's last two managers, each leaving
    at once) could each see the other as still-present backup and both
    proceed, since neither transaction's check would see the other's
    not-yet-committed removal.
    """
    from app.services.rbac import lock_organization_for_update, lock_project_for_update

    lock_organization_for_update(db, organization_id)

    roles = get_effective_org_roles(db, current_user.id, organization_id)
    if not roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not a member of this organisation.")

    if OrgRole.ORG_ADMIN in roles:
        other_admins = db.scalars(
            select(UserOrgRole.user_id).where(
                UserOrgRole.organization_id == organization_id,
                UserOrgRole.role == OrgRole.ORG_ADMIN,
                UserOrgRole.user_id != current_user.id,
            )
        ).all()
        if not other_admins:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You are this organisation's only admin. Assign another admin before leaving.",
            )

    from app.models.enums import ProjectRole  # local import matching this module's existing convention
    from app.models.project import Project, ProjectGroup  # local import to avoid cycle at module load
    from app.services.rbac import get_effective_project_roles

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    blocking_projects = []
    for p in projects:
        lock_project_for_update(db, p.id)
        concrete_managers = get_project_managers(db, p.id)
        # Fold in nested-org-group-derived PM status too: get_project_managers
        # only resolves direct assignments/direct group membership, so a
        # manager role held solely via a nested org group would otherwise be
        # invisible here, letting this guard miss a soon-to-be-orphaned
        # project (its only "manager" isn't a *concrete* manager per
        # get_project_managers' own definition, but removing this user's
        # nested-group access below would still leave nobody with the role).
        i_am_manager = current_user.id in concrete_managers or ProjectRole.PROJECT_MANAGER in get_effective_project_roles(
            db, current_user.id, p.id
        )
        if i_am_manager and not (concrete_managers - {current_user.id}):
            blocking_projects.append(p.name)
    if blocking_projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are the sole manager of: " + ", ".join(blocking_projects) + ". Assign another manager first.",
        )

    project_ids = [p.id for p in projects]
    if project_ids:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == current_user.id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(
                ProjectGroupMember.user_id == current_user.id,
                ProjectGroupMember.project_group_id.in_(
                    select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))
                ),
            )
        )
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.user_id == current_user.id,
            OrgGroupMember.org_group_id.in_(
                select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)
            ),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, current_user.id, project_ids)

    db.execute(
        UserOrgRole.__table__.delete().where(
            UserOrgRole.user_id == current_user.id, UserOrgRole.organization_id == organization_id
        )
    )
    log_event(
        db, entity_type="user_org_role", entity_id=current_user.id, action="left_organization",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Deactivates a user (C-U-04).

    Applies the C-U-09 fallback: for any project where this removal leaves
    no remaining project manager, the acting admin is assigned as manager so
    the project is never left without one (C-U-08). Each project is row-
    locked (`lock_project_for_update`) before its manager count is checked,
    so this can't race a concurrent removal (another deactivation, a role
    revocation, or someone leaving the org) on the same project — see
    `lock_project_for_update`'s docstring for the exact race this closes.

    The target user must actually be a member of `organization_id` — an org
    admin's authority to deactivate accounts is scoped to their own
    organisation's members, same as every other org-scoped action, not to
    every account in the deployment (SOC 2 access-control hardening pass).
    """
    from app.services.rbac import lock_project_for_update

    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.is_active = False
    user.deactivated_at = _now()

    from app.models.project import Project  # local import to avoid cycle at module load

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    for project in projects:
        lock_project_for_update(db, project.id)
        managers_before = get_project_managers(db, project.id)
        if user_id not in managers_before:
            continue
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(ProjectGroupMember.user_id == user_id)
        )
        remaining = get_project_managers(db, project.id) - {user_id}
        if not remaining:
            from app.models.enums import ProjectRole

            db.add(UserProjectRole(user_id=current_user.id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))
            log_event(
                db,
                entity_type="project",
                entity_id=project.id,
                action="manager_fallback_assigned",
                actor_id=current_user.id,
                project_id=project.id,
                detail={"assigned_to": str(current_user.id), "reason": "last_manager_deactivated"},
            )

    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="deactivated",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Archives a deactivated user, hiding them from user lists while
    preserving attribution of their past contributions (C-U-05).

    Scoped to members of `organization_id`, same as `deactivate_org_user`."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    if user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User must be deactivated before archiving.")
    user.is_archived = True
    log_event(
        db, entity_type="user", entity_id=user_id, action="archived", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/groups", response_model=OrgGroupOut, status_code=status.HTTP_201_CREATED)
def create_org_group(
    organization_id: UUID,
    payload: OrgGroupCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Creates an organisation group (C-U-08)."""
    group = OrgGroup(organization_id=organization_id, name=payload.name)
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="org_group", entity_id=group.id, action="created", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgGroupOut(id=group.id, name=group.name, member_user_ids=[])


@router.get("/{organization_id}/groups", response_model=list[OrgGroupOut])
def list_org_groups(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    groups = db.scalars(select(OrgGroup).where(OrgGroup.organization_id == organization_id)).all()
    out = []
    for g in groups:
        member_ids = db.scalars(select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == g.id)).all()
        out.append(OrgGroupOut(id=g.id, name=g.name, member_user_ids=list(member_ids)))
    return out


def _get_org_group_in_org(db: Session, organization_id: UUID, group_id: UUID) -> OrgGroup:
    """Loads an org group and 404s unless it belongs to `organization_id`.

    Without this check, an org_admin of organization A — validated only
    against the `organization_id` path param — could add/remove members of
    an org group belonging to a *different* organisation by supplying its
    id, a cross-tenant IDOR.
    """
    group = db.get(OrgGroup, group_id)
    if group is None or group.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org group not found.")
    return group


@router.post("/{organization_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    payload: OrgGroupMemberAdd,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    _get_org_group_in_org(db, organization_id, group_id)
    existing = db.scalar(
        select(OrgGroupMember).where(
            OrgGroupMember.org_group_id == group_id, OrgGroupMember.user_id == payload.user_id
        )
    )
    if existing is None:
        db.add(OrgGroupMember(org_group_id=group_id, user_id=payload.user_id))
        log_event(
            db, entity_type="org_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
            organization_id=organization_id, detail={"user_id": str(payload.user_id)},
        )
        db.commit()


@router.delete("/{organization_id}/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    _get_org_group_in_org(db, organization_id, group_id)
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.org_group_id == group_id, OrgGroupMember.user_id == user_id
        )
    )
    log_event(
        db, entity_type="org_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        organization_id=organization_id, detail={"user_id": str(user_id)},
    )
    db.commit()


def _now():
    """Returns the current UTC time."""
    from datetime import datetime

    return datetime.now(UTC)


# --- Shared resources (C-M-03), org logo (U-C-02), default template (C-E-04) ---


@router.post("/{organization_id}/resources", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_resource(
    organization_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Uploads a file as an organisation shared resource (C-M-03)."""
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream",
        data=data, is_org_resource=True,
    )
    log_event(db, entity_type="file_asset", entity_id=asset.id, action="uploaded",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{organization_id}/resources", response_model=list[FileAssetOut])
def list_org_resources(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(FileAsset).where(FileAsset.organization_id == organization_id, FileAsset.is_org_resource.is_(True))
    ).all()


@router.delete("/{organization_id}/resources/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_resource(
    organization_id: UUID, file_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    asset = db.get(FileAsset, file_id)
    if asset is None or asset.organization_id != organization_id or not asset.is_org_resource:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
    db.execute(RequirementFile.__table__.delete().where(RequirementFile.file_id == file_id))
    delete_file(db, asset)
    log_event(db, entity_type="file_asset", entity_id=file_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


@router.post("/{organization_id}/logo", response_model=OrganizationOut)
async def upload_org_logo(
    organization_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Uploads an organisation logo, shown in the UI (U-C-02)."""
    org = db.get(Organization, organization_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "logo", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    org.logo_file_id = asset.id
    log_event(db, entity_type="organization", entity_id=organization_id, action="logo_updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(org)
    return org


@router.put("/{organization_id}/default-template", response_model=OrganizationOut)
def set_default_template(
    organization_id: UUID, payload: DefaultTemplateUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets (or clears, with `project_id: null`) the default template project used
    when creating a new project in this organisation (C-E-04)."""
    from app.models.project import Project

    org = db.get(Organization, organization_id)
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.organization_id != organization_id or not project.is_template:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id must be a template project in this organisation.")
    org.default_template_project_id = payload.project_id
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="default_template_updated",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"project_id": str(payload.project_id) if payload.project_id else None},
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def get_advanced_settings(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Per-organisation SMTP override and SSO group-mapping settings.

    `smtp_*` remain storage-only (see `Organization` model docstring);
    `sso_group_mappings` is read by `services/oidc_provisioning.
    sync_org_roles_from_claims` on every SSO login. The stored
    `smtp_password` is never echoed back (write-only), matching how the
    bootstrap/native-auth password is handled elsewhere.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls, sso_group_mappings=org.sso_group_mappings,
    )


@router.put("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def update_advanced_settings(
    organization_id: UUID, payload: OrgAdvancedSettingsUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.smtp_host = payload.smtp_host
    org.smtp_port = payload.smtp_port
    org.smtp_username = payload.smtp_username
    if payload.smtp_password:
        # Blank means "leave unchanged" — the field is never returned by GET,
        # so a client re-submitting the form has no value to send back.
        org.smtp_password = payload.smtp_password
    org.smtp_use_tls = payload.smtp_use_tls
    org.sso_group_mappings = [m.model_dump() for m in payload.sso_group_mappings]
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="advanced_settings_updated",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()
    db.refresh(org)
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls, sso_group_mappings=org.sso_group_mappings,
    )


# --- SSO / branded login page (E-U-01, E-P-03) ------------------------------


@router.get("/by-slug/{slug}/login-info", response_model=OrgLoginInfoOut)
def get_org_login_info(slug: str, db: Session = Depends(get_db)):
    """Public, unauthenticated lookup used by the org-branded login page
    (`/login/{slug}` in the frontend) to render branding and decide whether
    to show a "Sign in with SSO" button. Returns no secrets."""
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgLoginInfoOut(
        name=org.name, slug=org.slug, logo_file_id=org.logo_file_id,
        login_background_file_id=org.login_background_file_id,
        sso_enabled=org.sso_enabled, sso_only=org.sso_only,
    )


@router.get("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def get_sso_config(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.put("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def update_sso_config(
    organization_id: UUID, payload: OrgSsoConfigUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Configures an organisation's OIDC SSO login (E-U-01) and its
    slug-resolved branded login page (E-P-03).

    `oidc_client_secret` is encrypted at rest at the application layer
    (`EncryptedString`, SOC 2 hardening pass) — see `models.organization`
    for details.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.slug is not None:
        existing = db.scalar(select(Organization).where(Organization.slug == payload.slug))
        if existing is not None and existing.id != org.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "This slug is already in use.")
        org.slug = payload.slug
    if payload.sso_enabled and not org.slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set a slug before enabling SSO (needed for the login page URL).")
    org.sso_enabled = payload.sso_enabled
    org.sso_only = payload.sso_only
    org.oidc_issuer_url = payload.oidc_issuer_url
    org.oidc_client_id = payload.oidc_client_id
    if payload.oidc_client_secret:
        # Blank means "leave unchanged" — same pattern as smtp_password above.
        org.oidc_client_secret = payload.oidc_client_secret
    org.oidc_required_group = payload.oidc_required_group
    log_event(db, entity_type="organization", entity_id=organization_id, action="sso_config_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.post("/{organization_id}/login-background", response_model=OrganizationOut)
async def upload_login_background(
    organization_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Uploads a custom background image for this organisation's branded
    login page (E-P-03), same upload pattern as the org logo."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "login-background", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    org.login_background_file_id = asset.id
    log_event(db, entity_type="organization", entity_id=organization_id, action="login_background_updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(org)
    return org


# --- Report templates (R-G-05) -----------------------------------------------


@router.post("/{organization_id}/report-templates", response_model=ReportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_report_template(
    organization_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a named PDF report branding preset for this organisation (R-G-05)."""
    template = ReportTemplate(
        organization_id=organization_id, name=payload.name, accent_color_hex=payload.accent_color_hex,
        include_cover_page=payload.include_cover_page, include_logo=payload.include_logo,
        footer_text=payload.footer_text, created_by=current_user.id,
    )
    db.add(template)
    db.flush()
    log_event(db, entity_type="report_template", entity_id=template.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template


@router.get("/{organization_id}/report-templates", response_model=list[ReportTemplateOut])
def list_report_templates(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's report templates — any org member may select
    one when generating a report, so listing isn't admin-only (only
    create/edit/delete are)."""
    return db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == organization_id)).all()


@router.put("/{organization_id}/report-templates/{template_id}", response_model=ReportTemplateOut)
def update_report_template(
    organization_id: UUID, template_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    template.name = payload.name
    template.accent_color_hex = payload.accent_color_hex
    template.include_cover_page = payload.include_cover_page
    template.include_logo = payload.include_logo
    template.footer_text = payload.footer_text
    log_event(db, entity_type="report_template", entity_id=template.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{organization_id}/report-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report_template(
    organization_id: UUID, template_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    log_event(db, entity_type="report_template", entity_id=template.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.delete(template)
    db.commit()
