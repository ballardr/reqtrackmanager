"""
Module: routers.orgs

Organisation management: creating organisations and organisation users
(I-M-05, server-admin only), organisation role assignment, user
deactivation/archival (C-U-04, C-U-05), and organisation groups (C-U-08,
C-U-12).
"""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.file import FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import ProjectGroupMember, UserProjectRole
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
    OrgRoleAssign,
    OrgUserCreate,
    OrgUserOut,
)
from app.security import hash_password
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
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists users belonging to an organisation with their org roles.

    Archived users are excluded (C-U-05: an archived user "no longer
    show[s] as users", though their past contributions stay attributed to
    them elsewhere via the unaffected `creator_id`/`actor_id` foreign keys).
    """
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
            )
        by_user[user.id].roles.append(role)
    return list(by_user.values())


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
    """Grants an organisation role to a user (C-U-01)."""
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == payload.user_id,
            UserOrgRole.organization_id == organization_id,
            UserOrgRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserOrgRole(user_id=payload.user_id, organization_id=organization_id, role=payload.role))
        log_event(
            db,
            entity_type="user_org_role",
            entity_id=payload.user_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            detail={"role": payload.role.value},
        )
        granted_user = db.get(User, payload.user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{payload.role.value}' role in an organisation.",
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
    the project is never left without one (C-U-08).
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    user.is_active = False
    user.deactivated_at = _now()

    from app.models.project import Project  # local import to avoid cycle at module load

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    for project in projects:
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
    preserving attribution of their past contributions (C-U-05)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
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

    Storage-only: see `Organization` model docstring for why nothing
    currently reads `smtp_*`/`sso_group_mappings` at runtime. The stored
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
