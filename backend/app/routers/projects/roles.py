"""
Module: routers.projects.roles

Direct (non-group) project role assignment for a user or organisation
group (C-U-10/C-U-11), the by-email flow for a user outside the project's
own organisation (gated by `Organization.external_user_policy`), and the
pending-invite list/resend this creates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
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
from app.services.notifications import notify
from app.services.rbac import (
    _descendant_org_group_ids,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    is_inherited_manager,
    lock_project_for_update,
    require_project_manage,
)

router = APIRouter(tags=["projects-roles"])


@router.post("/{project_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_role(
    project_id: UUID, payload: UserProjectRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-group) project role to a user."""
    _require_user_in_org(db, payload.user_id, project.organization_id)  # C-U-02
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
        db.commit()


@router.get("/{project_id}/group-roles", response_model=list[OrgGroupProjectRoleSummaryOut])
def list_group_project_roles(
    project_id: UUID,
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Lists every organisation group holding at least one direct
    `OrgGroupProjectRole` grant on this project — the read side PR4's
    assign/revoke endpoints never got (Phase 6, docs/platform-review-2026-
    09-plan.md). Before this endpoint, a group granted a role through the
    Members section's add-control (`assign_group_project_role`) had no way
    to be seen, edited, or removed again except by reaching into a
    member's own per-role Source line (`direct_org_group_role` provenance)
    or calling the DELETE endpoint by hand — this is what lets
    `ProjectMembersTable`'s own group row exist at all.

    `require_project_manage`-gated like `get_effective_members`, the
    equivalent read for user rows, and like the assign/revoke endpoints
    this is the read counterpart to.
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


@router.post("/{project_id}/group-roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_group_project_role(
    project_id: UUID, payload: OrgGroupProjectRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-nested) project role to an organisation group —
    the group-level counterpart to `assign_project_role`, and a genuinely
    separate mechanism from nesting an org group inside a `ProjectGroup`
    (C-U-12, `routers.projects.groups.add_project_group_member`): this
    creates the group's own independently-revocable `OrgGroupProjectRole`
    row, parallel to how `UserProjectRole` already works for a single
    user. Both mechanisms coexist by design — see `docs/decisions.md`'s
    identify/verify/remediate entry for this endpoint.

    Same cross-tenant check `add_project_group_member` already applies to
    its own `org_group_id` target: the group must belong to this project's
    own organisation, re-validated here rather than trusted from the
    frontend. Idempotent like `assign_project_role`: granting an
    already-held (group, project, role) triple is a silent no-op, not a
    409 — no audit event or commit happens on the no-op path, matching that
    endpoint's exact behavior.

    No per-member notification is sent (matching `add_project_group_member`'s
    own `org_group_id` path, not `assign_project_role`'s single-user path)
    — a group grant potentially affects many users at once, and this
    codebase's existing group-membership endpoints don't notify on
    group-level composition changes either.
    """
    org_group = db.get(OrgGroup, payload.org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
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
        db.commit()


@router.post("/{project_id}/roles/by-email", response_model=AssignByEmailOut)
def assign_project_role_by_email(
    project_id: UUID, payload: UserProjectRoleAssignByEmail,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The by-email counterpart to `assign_project_role`, for a user who
    isn't (yet) a member of this project's organisation — the project-user
    picker's "add external user" action (`orgs.py::search_org_users`
    surfaces the candidate; this endpoint re-validates and acts on it,
    never trusting the frontend's search-result flags).

    Gated by `Organization.external_user_policy`:
      - DISABLED: always 403, whether or not an account already exists.
      - ORG_DOMAIN_ONLY: an *existing* account can always be added; a
        *new* account can only be invited if the email's domain matches
        `auto_accept_email_domain`.
      - ANYONE: both existing and brand-new accounts are allowed.

    For a brand-new account, branches on `Organization.sso_only` (see
    `services/invites.py`): an SSO-only org gets the account and roles
    provisioned immediately (`outcome="sso_provisioned"`); otherwise an
    email invite with a signup link is sent (`outcome="invited"`) and the
    role is granted once they complete signup.
    """
    email = payload.email.lower()
    org = db.get(Organization, project.organization_id)
    existing_user = db.scalar(select(User).where(User.email == email))

    if existing_user is not None:
        already_in_org = bool(get_effective_org_roles(db, existing_user.id, org.id))
        if not already_in_org:
            if org.external_user_policy == ExternalUserPolicy.DISABLED:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation does not allow external users.")
            if existing_user.is_banned:
                # Same check assign_org_role already enforces for the
                # ordinary org-role-grant path (routers/orgs.py) — this
                # endpoint grants org membership too (as a side effect of
                # adding a project member by email) and must not become a
                # second, unguarded way back in for a banned account.
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
        db.commit()
        return AssignByEmailOut(outcome="sso_provisioned")

    invites.create_pending_invite(
        db, email=email, organization=org, project=project, project_role=payload.role, invited_by=current_user.id,
    )
    db.commit()
    return AssignByEmailOut(outcome="invited")


def _pending_invite_out(invite: PendingInvite) -> PendingInviteOut:
    """Shared status computation for both endpoints below — `status` is
    derived from `expires_at` at read time rather than stored, so it's
    always current."""
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
    """Lists this project's outstanding (unaccepted) `PendingInvite`s, most
    recent first — including already-expired ones, since an expired invite
    is exactly the case `resend_pending_project_invite` exists to fix.

    Standard (non-SSO) `PendingInvite` flow only (Phase 3 scope decision,
    docs/decisions.md) — an `sso_only` org's by-email invites are
    provisioned immediately via `services.invites.provision_sso_invite`
    and never create a row here. Gated the same as
    `assign_project_role_by_email`, the only endpoint that creates these
    rows, since listing/resending them is a continuation of that same
    capability.
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
    org = db.get(Organization, project.organization_id)
    invites.resend_pending_invite(db, invite, organization=org, project=project)
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invite_resent",
        actor_id=current_user.id, organization_id=org.id, project_id=project.id,
        detail={"email": invite.email},
    )
    db.commit()
    return _pending_invite_out(invite)


@router.delete("/{project_id}/roles/{user_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_role(
    project_id: UUID, user_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
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
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
        managers = get_effective_project_managers(db, project.id)
        if managers == {user_id} and not is_inherited_manager(db, user_id, project.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.execute(
        UserProjectRole.__table__.delete().where(
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
    # Only clean up subscriptions/favourites if the user has no other role
    # (direct or group-derived) left granting them access to this project.
    if not get_effective_project_roles(db, user_id, project.id):
        engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, [project.id])
    db.commit()


@router.delete("/{project_id}/group-roles/{org_group_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_group_project_role(
    project_id: UUID, org_group_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct (non-nested) project role from an organisation
    group — the group-level counterpart to `revoke_project_role`.

    C-U-08 guard shaped like `delete_project_group`'s (lock the project row,
    perform the delete, flush, then re-check `get_effective_project_
    managers` before commit) rather than `revoke_project_role`'s
    single-user pre-check (`managers == {user_id}`): revoking a group's
    role can remove effective access from every member of that group at
    once, not just one user, so there's no single user id to compare
    against. In practice this rarely actually trips for a *group* role
    specifically: `get_effective_project_managers`/`_direct_project_
    managers` deliberately never count any group-derived manager — neither
    the pre-existing nested-org-group mechanism (`ProjectGroup` +
    `ProjectGroupMember.org_group_id`) nor this new direct-grant mechanism
    — towards the C-U-08 "at least one manager" floor (see that function's
    own docstring: only direct `UserProjectRole` grants and a group's
    *direct user* members count as "concrete, individually accountable"
    managers). This guard is kept anyway, for defense-in-depth and
    consistency with `delete_project_group`/`update_project_group`, which
    apply the identical pattern for the identical reason: it still
    correctly catches the case where the project already had zero
    individually-accountable managers at the moment of this call. See
    docs/decisions.md's identify/verify/remediate entry for this endpoint
    for the full reasoning on why C-U-08 was not extended to count
    group-derived managers here — that would be a materially larger,
    separate change to a longstanding invariant, not something this PR
    introduces.

    `org_group_id` is validated to belong to this project's own
    organisation before anything else runs (hardening pass, 2026-09) —
    the delete itself was already safely scoped by its own `WHERE
    project_id=...` clause (no cross-tenant row can ever exist to remove),
    but an unvalidated id let a caller fabricate an "revoked" audit-log
    entry for a grant that never existed and run the membership-resolution
    query below against an arbitrary group, mirroring the same rowcount
    guard `revoke_project_group_role` (its `ProjectGroupRole`-scoped
    sibling, in `routers.projects.groups`) already has.
    """
    org_group = db.get(OrgGroup, org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation group not found.")
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
    removed = db.execute(
        OrgGroupProjectRole.__table__.delete().where(
            OrgGroupProjectRole.org_group_id == org_group_id, OrgGroupProjectRole.project_id == project.id,
            OrgGroupProjectRole.role == role,
        )
    )
    db.flush()
    if role == ProjectRole.PROJECT_MANAGER and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    if not removed.rowcount:
        db.commit()
        return
    log_event(
        db, entity_type="org_group_project_role", entity_id=org_group_id, action="revoked",
        actor_id=current_user.id, project_id=project.id, detail={"role": role.value},
    )
    # Clean up subscriptions/favourites for every member of this group (direct
    # or via a nested subgroup, same descendant-expansion `_direct_project_
    # role_holder_ids` uses to resolve this mechanism) who has no other role
    # left granting them access to this project — mirrors `revoke_project_
    # role`'s own per-user cleanup, extended to the (potentially many) users
    # a group-level revocation can affect at once.
    affected_user_ids = set(
        db.scalars(
            select(OrgGroupMember.user_id).where(
                OrgGroupMember.org_group_id.in_({org_group_id} | _descendant_org_group_ids(db, {org_group_id})),
                OrgGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    for affected_user_id in affected_user_ids:
        if not get_effective_project_roles(db, affected_user_id, project.id):
            engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()
