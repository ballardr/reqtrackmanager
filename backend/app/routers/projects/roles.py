"""
Module: routers.projects.roles

Direct (non-group) project role assignment for a user or organisation group (C-U-10/C-U-11), the by-email
flow for a user outside the project's organisation (gated by `Organization.external_user_policy`) and the
pending-invite list/resend it creates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, refuse_personal_access_token
from app.models.enums import ExternalUserPolicy, OrgRole, ProjectRole
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, PendingInvite, UserOrgRole
from app.models.project import OrgGroupProjectRole, Project, UserProjectRole
from app.models.user import User
from app.routers.projects.core import _require_user_in_org
from app.schemas.project import (
    AssignByEmailOut,
    OrgGroupProjectRoleAssign,
    OrgGroupProjectRoleSummaryOut,
    PendingInviteOut,
    UserProjectRoleAssign,
    UserProjectRoleAssignByEmail,
)
from app.services import engagement, invites
from app.services.audit import log_event
from app.services.lookups import affected_rows, get_or_404, present
from app.services.membership_notifications import (
    actor_bypasses_project_managers,
    notify_managers_of_member_change,
)
from app.services.notifications import notify
from app.services.org_membership import assert_account_active
from app.services.rbac import (
    _descendant_org_group_ids,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    is_inherited_manager,
    lock_project_for_update,
    require_project_manage,
    require_project_manage_or_grant_roles,
)

router = APIRouter(tags=["projects-roles"])


@router.post("/{project_id}/roles", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(refuse_personal_access_token)])
def assign_project_role(
    project_id: UUID, payload: UserProjectRoleAssign,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-group) project role to a user. Gated by
    `require_project_manage_or_grant_roles` — no `OrgRole.ORG_ADMIN`-equivalent carve-out is
    needed at project-role scope (no `ProjectRole` value is non-delegable)."""
    _require_user_in_org(db, payload.user_id, project.organization_id)  # C-U-02
    bypass = actor_bypasses_project_managers(db, current_user, project)
    existing = db.scalar(
        select(UserProjectRole).where(
            UserProjectRole.user_id == payload.user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserProjectRole(user_id=payload.user_id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="user_project_role", entity_id=payload.user_id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value},
        )
        granted_user = db.get(User, payload.user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were granted the '{payload.role.value}' role.",
                project_id=project.id, actor_id=current_user.id,
            )
            if bypass:
                notify_managers_of_member_change(
                    db, project=project, actor=current_user, verb="Added", target=granted_user.display_name,
                    role=payload.role,
                )
        db.commit()


@router.get("/{project_id}/group-roles", response_model=list[OrgGroupProjectRoleSummaryOut])
def list_group_project_roles(
    project_id: UUID,
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Lists every organisation group holding a direct `OrgGroupProjectRole` grant on this project: the read
    side of the assign/revoke endpoints, which lets `ProjectMembersTable` show a group row and its role be
    edited or removed.

    `require_project_manage`-gated like `get_effective_members`, the equivalent read for user rows.
    """
    rows = db.execute(
        select(OrgGroupProjectRole.org_group_id, OrgGroupProjectRole.role, OrgGroup.name)
        .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
        .where(OrgGroupProjectRole.project_id == project_id)
        .order_by(OrgGroup.name)
    ).all()
    grouped: dict[UUID, OrgGroupProjectRoleSummaryOut] = {}
    for org_group_id, role, org_group_name in rows:
        entry = grouped.get(org_group_id)
        if entry is None:
            entry = OrgGroupProjectRoleSummaryOut(org_group_id=org_group_id, org_group_name=org_group_name, roles=[])
            grouped[org_group_id] = entry
        entry.roles.append(role)
    return list(grouped.values())


@router.post("/{project_id}/group-roles", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(refuse_personal_access_token)])
def assign_group_project_role(
    project_id: UUID, payload: OrgGroupProjectRoleAssign,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-nested) project role to an organisation group: the group-level counterpart to
    `assign_project_role`, and a separate mechanism from nesting an org group inside a `ProjectGroup`
    (C-U-12, `routers.projects.groups.add_project_group_member`): it creates the group's own independently
    revocable `OrgGroupProjectRole` row, as `UserProjectRole` works for a user. Both coexist (see
    docs/decisions.md's identify/verify/remediate entry for this endpoint).

    The cross-tenant check of `add_project_group_member`'s `org_group_id` applies: the group must belong to
    this project's organisation, re-validated here rather than trusted from the frontend. Idempotent as
    `assign_project_role`: granting an already-held (group, project, role) triple is a silent no-op with no
    audit event or commit.

    No per-member notification is sent (as `add_project_group_member`'s `org_group_id` path): a group grant can
    affect many users and group-level composition changes do not notify. The project's managers are notified
    when the actor is not one of them (`services.membership_notifications`).
    """
    org_group = db.get(OrgGroup, payload.org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
    bypass = actor_bypasses_project_managers(db, current_user, project)
    existing = db.scalar(
        select(OrgGroupProjectRole).where(
            OrgGroupProjectRole.org_group_id == payload.org_group_id, OrgGroupProjectRole.project_id == project.id,
            OrgGroupProjectRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(OrgGroupProjectRole(org_group_id=payload.org_group_id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="org_group_project_role", entity_id=payload.org_group_id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value},
        )
        if bypass:
            notify_managers_of_member_change(
                db, project=project, actor=current_user, verb="Added", target=f"group {org_group.name}",
                role=payload.role,
            )
        db.commit()


@router.post("/{project_id}/roles/by-email", response_model=AssignByEmailOut, dependencies=[Depends(refuse_personal_access_token)])
def assign_project_role_by_email(
    project_id: UUID, payload: UserProjectRoleAssignByEmail,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The by-email counterpart to `assign_project_role`, for a user who is not (yet) a member of this
    project's organisation: the project-user picker's "add external user" action (`orgs.py::search_org_users`
    surfaces the candidate; this endpoint re-validates and acts, never trusting the frontend's flags).

    Gated by `Organization.external_user_policy`:
      - DISABLED: always 403, whether or not an account exists.
      - ORG_DOMAIN_ONLY: an existing account can always be added; a new account can only be invited if the
        email's domain matches `auto_accept_email_domain`.
      - ANYONE: both existing and new accounts are allowed.

    For a new account, branches on `Organization.sso_only` (see `services/invites.py`): an SSO-only org gets the
    account and roles provisioned immediately (`outcome="sso_provisioned"`); otherwise an email invite with a
    signup link is sent (`outcome="invited"`) and the role is granted once they complete signup.
    """
    email = payload.email.lower()
    bypass = actor_bypasses_project_managers(db, current_user, project)
    org = get_or_404(db, Organization, project.organization_id, "Organisation")
    existing_user = db.scalar(select(User).where(User.email == email))

    if existing_user is not None:
        assert_account_active(db, existing_user.id)
        already_in_org = bool(get_effective_org_roles(db, existing_user.id, org.id))
        if not already_in_org and existing_user.is_service_account:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "A service user belongs to one organisation and cannot be added to another.")
        if not already_in_org:
            if org.external_user_policy == ExternalUserPolicy.DISABLED:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation does not allow external users.")
            if existing_user.is_banned:
                # Same check `assign_org_role` enforces for the ordinary org-role grant (routers/orgs.py): this
                # endpoint also grants org membership (adding a project member by email) and must not be an
                # unguarded way back in for a banned account.
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "This user has been banned by a server admin and cannot be granted a role.",
                )
            db.add(UserOrgRole(user_id=existing_user.id, organization_id=org.id, role=OrgRole.MEMBER))
            log_event(
                db, entity_type="user", entity_id=existing_user.id, action="external_user_added_to_org",
                actor_id=current_user.id, organization_id=org.id,
            )
        existing_role = db.scalar(
            select(UserProjectRole).where(
                UserProjectRole.user_id == existing_user.id, UserProjectRole.project_id == project.id,
                UserProjectRole.role == payload.role,
            )
        )
        if existing_role is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This user already has this role on the project.")
        db.add(UserProjectRole(user_id=existing_user.id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="user_project_role", entity_id=existing_user.id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value, "via": "email"},
        )
        notify(
            db, existing_user, notification_type=NotificationType.PROJECT_JOINED,
            title=f"You were added to {project.name}",
            body=f"You were granted the '{payload.role.value}' role.",
            project_id=project.id, actor_id=current_user.id,
        )
        if bypass:
            notify_managers_of_member_change(
                db, project=project, actor=current_user, verb="Added", target=existing_user.display_name,
                role=payload.role,
            )
        db.commit()
        return AssignByEmailOut(outcome="added")

    # No account exists anywhere yet.
    if org.external_user_policy == ExternalUserPolicy.DISABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation does not allow external users.")
    if org.external_user_policy == ExternalUserPolicy.ORG_DOMAIN_ONLY:
        domain = email.rsplit("@", 1)[-1]
        if not org.auto_accept_email_domain or org.auto_accept_email_domain.lower() != domain:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This email's domain is not eligible for an invite in this organisation."
            )

    if org.sso_only:
        invites.provision_sso_invite(
            db, email=email, organization=org, project=project, project_role=payload.role,
            invited_by=current_user.id,
        )
        if bypass:
            notify_managers_of_member_change(
                db, project=project, actor=current_user, verb="Added", target=email, role=payload.role,
            )
        db.commit()
        return AssignByEmailOut(outcome="sso_provisioned")

    invites.create_pending_invite(
        db, email=email, organization=org, project=project, project_role=payload.role, invited_by=current_user.id,
    )
    if bypass:
        notify_managers_of_member_change(
            db, project=project, actor=current_user, verb="Invited", target=email, role=payload.role,
        )
    db.commit()
    return AssignByEmailOut(outcome="invited")


def _pending_invite_out(invite: PendingInvite) -> PendingInviteOut:
    """Shared status computation for both endpoints below — `status` is
    derived from `expires_at` at read time rather than stored, so it's
    always current."""
    if invite.project_role is None:
        raise ValueError("A project's pending invite always carries a project role.")
    return PendingInviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.project_role,
        status="pending" if invite.expires_at > datetime.now(UTC) else "expired",
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


def _get_pending_invite_in_project(db: Session, project_id: UUID, invite_id: UUID) -> PendingInvite:
    """Loads a `PendingInvite` and 404s unless it targets `project_id`.

    Without this check, a manager of *some* project (any project — that's
    all `require_project_manage` validates) could pass the `invite_id` of a
    *different* project's pending invite and resend it (rotating its
    token and re-sending its email), the same cross-project-boundary shape
    `routers.projects.groups._get_group_in_project` already guards against
    for group membership.
    """
    invite = db.get(PendingInvite, invite_id)
    if invite is None or invite.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found.")
    return invite


@router.get("/{project_id}/pending-invites", response_model=list[PendingInviteOut])
def list_pending_project_invites(
    project_id: UUID,
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Lists this project's outstanding (unaccepted) `PendingInvite`s, most recent first, including expired
    ones, which `resend_pending_project_invite` exists to fix.

    Standard (non-SSO) `PendingInvite` flow only (docs/decisions.md): an `sso_only` org's by-email invites are
    provisioned immediately via `services.invites.provision_sso_invite` and create no row here. Gated as
    `assign_project_role_by_email`, the only endpoint that creates these rows.
    """
    invites_list = db.scalars(
        select(PendingInvite)
        .where(PendingInvite.project_id == project.id, PendingInvite.accepted_at.is_(None))
        .order_by(PendingInvite.created_at.desc())
    ).all()
    return [_pending_invite_out(invite) for invite in invites_list]


@router.post("/{project_id}/pending-invites/{invite_id}/resend", response_model=PendingInviteOut)
def resend_pending_project_invite(
    project_id: UUID, invite_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotates the invite's token/`expires_at` and re-sends the signup-link
    email (`services.invites.resend_pending_invite`) — for "the original
    invite email never arrived" or reviving an invite that's since
    expired. Works in either case (still-pending or already-expired);
    only an already-*accepted* invite is rejected, since there's nothing
    left to resend once someone's redeemed it.
    """
    invite = _get_pending_invite_in_project(db, project.id, invite_id)
    if invite.accepted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invite has already been accepted.")
    org = get_or_404(db, Organization, project.organization_id, "Organisation")
    invites.resend_pending_invite(db, invite, organization=org, project=project)
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invite_resent",
        actor_id=current_user.id, organization_id=org.id, project_id=project.id,
        detail={"email": invite.email},
    )
    db.commit()
    return _pending_invite_out(invite)


@router.delete("/{project_id}/roles/{user_id}/{role}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(refuse_personal_access_token)])
def revoke_project_role(
    project_id: UUID, user_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct project role, blocking removal of the last manager
    (C-U-08). Removing user_id's *direct* manager role is allowed even when
    they're currently the only effective manager, as long as they'd remain
    one via forward inheritance alone (`is_inherited_manager`) — otherwise
    this would over-block a safe removal for any manager who happens to
    also be a direct manager of a project they inherit that same role
    from."""
    bypass = actor_bypasses_project_managers(db, current_user, project)
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
        managers = get_effective_project_managers(db, project.id)
        if managers == {user_id} and not is_inherited_manager(db, user_id, project.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.execute(
        delete(UserProjectRole).where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == role,
        )
    )
    log_event(
        db, entity_type="user_project_role", entity_id=user_id, action="revoked",
        actor_id=current_user.id, project_id=project.id, detail={"role": role.value},
    )
    revoked_user = db.get(User, user_id)
    if revoked_user is not None:
        notify(
            db, revoked_user, notification_type=NotificationType.PERMISSION_REVOKED,
            title=f"Your '{role.value}' role on {project.name} was revoked", project_id=project.id,
            actor_id=current_user.id,
        )
        if bypass:
            notify_managers_of_member_change(
                db, project=project, actor=current_user, verb="Removed", target=revoked_user.display_name,
                role=role,
            )
    # Only clean up subscriptions/favourites if the user has no other role
    # (direct or group-derived) left granting them access to this project.
    if not get_effective_project_roles(db, user_id, project.id):
        engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, [project.id])
    db.commit()


@router.delete(
    "/{project_id}/group-roles/{org_group_id}/{role}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(refuse_personal_access_token)],
)
def revoke_group_project_role(
    project_id: UUID, org_group_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage_or_grant_roles),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct (non-nested) project role from an organisation group: the group-level counterpart to
    `revoke_project_role`.

    C-U-08 guard shaped like `delete_project_group`'s (lock the project row, delete, flush, then re-check
    `get_effective_project_managers` before commit) rather than `revoke_project_role`'s single-user pre-check,
    since revoking a group's role can remove effective access from every member at once. It rarely trips for a
    group role: `get_effective_project_managers`/`_direct_project_managers` never count a group-derived manager
    (nested org group or this direct-grant mechanism) towards the C-U-08 floor; only direct `UserProjectRole`
    grants and a group's direct user members count. The guard is kept for defence in depth and consistency
    with `delete_project_group`/`update_project_group`: it catches the case where the project already had zero
    individually accountable managers. See docs/decisions.md's identify/verify/remediate entry for this
    endpoint on why C-U-08 does not count group-derived managers.

    `org_group_id` is validated to belong to this project's organisation first: the delete is scoped by
    `project_id`, but an unvalidated id would let a caller fabricate a "revoked" audit entry for a grant that
    never existed and run the membership-resolution query below against an arbitrary group (as the rowcount
    guard of `revoke_project_group_role` in `routers.projects.groups`).
    """
    org_group = db.get(OrgGroup, org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation group not found.")
    bypass = actor_bypasses_project_managers(db, current_user, project)
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
    removed = db.execute(
        delete(OrgGroupProjectRole).where(
            OrgGroupProjectRole.org_group_id == org_group_id, OrgGroupProjectRole.project_id == project.id,
            OrgGroupProjectRole.role == role,
        )
    )
    db.flush()
    if role == ProjectRole.PROJECT_MANAGER and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    if not affected_rows(removed):
        db.commit()
        return
    log_event(
        db, entity_type="org_group_project_role", entity_id=org_group_id, action="revoked",
        actor_id=current_user.id, project_id=project.id, detail={"role": role.value},
    )
    if bypass:
        notify_managers_of_member_change(
            db, project=project, actor=current_user, verb="Removed", target=f"group {org_group.name}", role=role,
        )
    # Clean up subscriptions/favourites for every member of this group (direct or via a nested subgroup, the
    # descendant expansion `_direct_project_role_holder_ids` uses) who has no other role granting access to
    # this project, as `revoke_project_role` does per user, extended to the many users a group revocation affects.
    affected_user_ids = set(
        present(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_({org_group_id} | _descendant_org_group_ids(db, {org_group_id})),
                    OrgGroupMember.user_id.is_not(None),
                )
            ).all()
        )
    )
    for affected_user_id in affected_user_ids:
        if not get_effective_project_roles(db, affected_user_id, project.id):
            engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()
