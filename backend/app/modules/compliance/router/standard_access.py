"""
Module: modules.compliance.router.standard_access

Standard-scoped RBAC (Phase 22): a standard's own member list, and
direct/group `standards_manager`/`standards_contributor` role grant and
revoke (with the "last Standards Manager" floor check, covered by a
direct/group grant or the org's fallback group). Kept in its own
bucket, deliberately not folded into `standards.py`, because this is a
role-grant surface (RBAC-adjacent), the same category the compliance
module's MCP write-tool declarations (`module.py`) exclude on
principle — see that file's "2026-09-22 reversal" docstring section,
point 2.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.module_role import GroupModuleRole, UserModuleRole
from app.models.notification import NotificationType
from app.models.organization import OrgGroup
from app.models.user import User
from app.modules.compliance.router._shared import _get_standard_or_404, _require_standard_manage, _require_view
from app.modules.compliance.schemas import (
    ComplianceStandardGroupMemberOut,
    ComplianceStandardGroupRoleAssign,
    ComplianceStandardMemberOut,
    ComplianceStandardMemberRoleAssign,
    ComplianceStandardMembersOut,
)
from app.modules.compliance.service import standard_manager_floor_covered_by_fallback, standard_manager_floor_covered_by_group_grants
from app.services import notifications
from app.services.audit import log_event
from app.services.rbac import effective_org_group_member_ids

router = APIRouter(tags=["compliance-org-standard-access"])


@router.get("/standards/{standard_id}/members", response_model=ComplianceStandardMembersOut)
def list_standard_members(
    organization_id: UUID, standard_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this standard's own direct `standards_manager`/`standards_
    contributor` role grants (Phase 22) — the standard's dedicated working
    group — plus its group-based grants (`GroupModuleRole`, module system
    Phase 30) and whether this standard's manager floor is *also* covered
    by the org's designated fallback compliance-managers group currently
    having at least one member. View-gated, same as every other read on a
    standard. Deliberately excludes the org-wide `compliance_manager`/
    `OrgRole.ORG_ADMIN` override tier and fallback-group members
    themselves as rows — this is a roster of this standard's own *direct*
    (user or group) grants, not every user who happens to currently have
    access to it."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    grants = db.scalars(
        select(UserModuleRole).where(
            UserModuleRole.module_key == "compliance",
            UserModuleRole.role_key.in_(["standards_manager", "standards_contributor"]),
            UserModuleRole.scope_entity_id == standard.id,
        )
    ).all()
    role_keys_by_user: dict[UUID, list[str]] = {}
    for grant in grants:
        role_keys_by_user.setdefault(grant.user_id, []).append(grant.role_key)
    members = []
    for user_id, role_keys in role_keys_by_user.items():
        user = db.get(User, user_id)
        if user is None:
            continue
        members.append(
            ComplianceStandardMemberOut(
                user_id=user_id, display_name=user.display_name, email=user.email, role_keys=role_keys
            )
        )
    group_grants = db.scalars(
        select(GroupModuleRole).where(
            GroupModuleRole.module_key == "compliance",
            GroupModuleRole.role_key.in_(["standards_manager", "standards_contributor"]),
            GroupModuleRole.scope_entity_id == standard.id,
        )
    ).all()
    role_keys_by_group: dict[UUID, list[str]] = {}
    for grant in group_grants:
        role_keys_by_group.setdefault(grant.org_group_id, []).append(grant.role_key)
    group_members = []
    for group_id, role_keys in role_keys_by_group.items():
        group = db.get(OrgGroup, group_id)
        if group is None:
            continue
        group_members.append(
            ComplianceStandardGroupMemberOut(
                org_group_id=group_id, group_name=group.name, role_keys=role_keys,
                member_count=len(effective_org_group_member_ids(db, group_id)),
            )
        )
    return ComplianceStandardMembersOut(
        group_members=group_members,
        members=members,
        manager_floor_covered_by_fallback=standard_manager_floor_covered_by_fallback(db, organization_id),
    )


@router.post("/standards/{standard_id}/members/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_standard_member_role(
    organization_id: UUID, standard_id: UUID, user_id: UUID, payload: ComplianceStandardMemberRoleAssign,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Grants a direct `standards_manager`/`standards_contributor` role on
    this standard (Phase 22) — manager-tier-only, mirroring `assign_org_
    module_role`'s own `ORG_ADMIN`-only gate one tier down (a standards
    manager already implicitly holds this via `require_module_role`'s own
    composition, so it's consistent that a standards manager is also who
    explicitly grants/revokes this standard's own membership). Silent
    no-op if the grant already exists, matching every other module-role
    grant endpoint's own idempotency."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )
    existing = db.scalar(
        select(UserModuleRole).where(
            UserModuleRole.user_id == user_id, UserModuleRole.module_key == "compliance",
            UserModuleRole.role_key == payload.role_key, UserModuleRole.scope_entity_id == standard.id,
        )
    )
    if existing is None:
        db.add(
            UserModuleRole(
                user_id=user_id, module_key="compliance", role_key=payload.role_key,
                organization_id=organization_id, scope_entity_id=standard.id, granted_by=current_user.id,
            )
        )
        log_event(
            db, entity_type="user_module_role", entity_id=user_id, action="granted",
            actor_id=current_user.id, organization_id=organization_id,
            detail={"module_key": "compliance", "role_key": payload.role_key, "standard_id": str(standard.id)},
        )
        notifications.notify(
            db, target, notification_type=NotificationType.PERMISSION_GRANTED,
            title="Compliance standard permission granted",
            body=f"You were granted the '{payload.role_key}' role on '{standard.name}'.",
            actor_id=current_user.id,
        )
        db.commit()


@router.delete("/standards/{standard_id}/members/{user_id}/roles/{role_key}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_standard_member_role(
    organization_id: UUID, standard_id: UUID, user_id: UUID, role_key: str,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Revokes a direct standard-scoped role grant (Phase 22) — blocks
    removing this standard's *last remaining* `standards_manager` grant
    (§3's manager floor) unless another explicit manager grant covers it
    (direct or group, module system Phase 30) or the org's fallback
    compliance-managers group currently has at least one member, mirroring
    `revoke_project_role`'s own "last manager" guard (`routers/projects.py`)
    one tier down, including its same "the floor must be satisfied by a
    real, resolvable set of people, not merely a theoretical admin
    override" reasoning — see `service.py::standard_manager_floor_covered_
    by_fallback`'s own docstring. Silent no-op if the grant doesn't exist,
    matching every other module-role revoke endpoint's own idempotency."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    if role_key not in ("standards_manager", "standards_contributor"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such role.")
    if role_key == "standards_manager":
        is_a_manager = db.scalar(
            select(UserModuleRole.id).where(
                UserModuleRole.user_id == user_id, UserModuleRole.module_key == "compliance",
                UserModuleRole.role_key == "standards_manager", UserModuleRole.scope_entity_id == standard.id,
            )
        ) is not None
        other_managers_exist = db.scalar(
            select(UserModuleRole.id).where(
                UserModuleRole.module_key == "compliance", UserModuleRole.role_key == "standards_manager",
                UserModuleRole.scope_entity_id == standard.id, UserModuleRole.user_id != user_id,
            )
        ) is not None
        if (
            is_a_manager and not other_managers_exist
            and not standard_manager_floor_covered_by_group_grants(db, standard.id)
            and not standard_manager_floor_covered_by_fallback(db, organization_id)
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This standard must always have at least one Standards Manager. Assign another manager, or "
                "configure a fallback compliance-managers group in this organisation's Compliance settings, "
                "before removing the last one.",
            )
    db.execute(
        UserModuleRole.__table__.delete().where(
            UserModuleRole.user_id == user_id, UserModuleRole.module_key == "compliance",
            UserModuleRole.role_key == role_key, UserModuleRole.scope_entity_id == standard.id,
        )
    )
    log_event(
        db, entity_type="user_module_role", entity_id=user_id, action="revoked",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"module_key": "compliance", "role_key": role_key, "standard_id": str(standard.id)},
    )
    db.commit()


@router.post("/standards/{standard_id}/group-roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_standard_group_role(
    organization_id: UUID, standard_id: UUID, payload: ComplianceStandardGroupRoleAssign,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Grants a `standards_manager`/`standards_contributor` role on this
    standard to every (transitive) member of an org group (`GroupModuleRole`,
    module system Phase 30) — the group-grant counterpart to `assign_
    standard_member_role`, same manager-tier-only gate. Mirrors `routers/
    projects.py::assign_group_project_role`'s own cross-tenant re-check
    (`org_group_id` must belong to this standard's own organisation) and
    idempotency (a silent no-op if the grant already exists, no audit event
    or commit on that path)."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    org_group = db.get(OrgGroup, payload.org_group_id)
    if org_group is None or org_group.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to this organisation.")
    existing = db.scalar(
        select(GroupModuleRole).where(
            GroupModuleRole.org_group_id == payload.org_group_id, GroupModuleRole.module_key == "compliance",
            GroupModuleRole.role_key == payload.role_key, GroupModuleRole.scope_entity_id == standard.id,
        )
    )
    if existing is None:
        db.add(
            GroupModuleRole(
                org_group_id=payload.org_group_id, module_key="compliance", role_key=payload.role_key,
                organization_id=organization_id, scope_entity_id=standard.id, granted_by=current_user.id,
            )
        )
        log_event(
            db, entity_type="group_module_role", entity_id=payload.org_group_id, action="granted",
            actor_id=current_user.id, organization_id=organization_id,
            detail={"module_key": "compliance", "role_key": payload.role_key, "standard_id": str(standard.id)},
        )
        db.commit()


@router.delete("/standards/{standard_id}/group-roles/{org_group_id}/{role_key}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_standard_group_role(
    organization_id: UUID, standard_id: UUID, org_group_id: UUID, role_key: str,
    current_user: User = Depends(_require_standard_manage), db: Session = Depends(get_db),
):
    """Revokes a `GroupModuleRole` grant on this standard (module system
    Phase 30) — same "last standards_manager" floor guard as `revoke_
    standard_member_role`, extended one direction further: removing this
    group's own `standards_manager` grant additionally checks whether some
    *other* group grant still covers the floor (`standard_manager_floor_
    covered_by_group_grants`'s own `exclude_org_group_id`, so this group's
    about-to-be-revoked row never counts towards its own answer). Silent
    no-op if the grant doesn't exist, matching every other module-role
    revoke endpoint's own idempotency."""
    standard = _get_standard_or_404(db, organization_id, standard_id)
    if role_key not in ("standards_manager", "standards_contributor"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such role.")
    if role_key == "standards_manager":
        is_a_manager = db.scalar(
            select(GroupModuleRole.id).where(
                GroupModuleRole.org_group_id == org_group_id, GroupModuleRole.module_key == "compliance",
                GroupModuleRole.role_key == "standards_manager", GroupModuleRole.scope_entity_id == standard.id,
            )
        ) is not None
        other_managers_exist = db.scalar(
            select(UserModuleRole.id).where(
                UserModuleRole.module_key == "compliance", UserModuleRole.role_key == "standards_manager",
                UserModuleRole.scope_entity_id == standard.id,
            )
        ) is not None
        if (
            is_a_manager and not other_managers_exist
            and not standard_manager_floor_covered_by_group_grants(
                db, standard.id, exclude_org_group_id=org_group_id
            )
            and not standard_manager_floor_covered_by_fallback(db, organization_id)
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This standard must always have at least one Standards Manager. Assign another manager, or "
                "configure a fallback compliance-managers group in this organisation's Compliance settings, "
                "before removing the last one.",
            )
    db.execute(
        GroupModuleRole.__table__.delete().where(
            GroupModuleRole.org_group_id == org_group_id, GroupModuleRole.module_key == "compliance",
            GroupModuleRole.role_key == role_key, GroupModuleRole.scope_entity_id == standard.id,
        )
    )
    log_event(
        db, entity_type="group_module_role", entity_id=org_group_id, action="revoked",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"module_key": "compliance", "role_key": role_key, "standard_id": str(standard.id)},
    )
    db.commit()
