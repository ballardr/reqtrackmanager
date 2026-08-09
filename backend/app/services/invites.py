"""
Module: services.invites

Provisioning for the "add a project user by email who isn't already an
organisation member" flow (`routers/projects.py`), gated by
`Organization.external_user_policy`. Two distinct provisioning paths, chosen
by the target organisation's `sso_only` flag:

- Non-`sso_only` orgs: `create_pending_invite` creates a `PendingInvite` row
  and emails a tokenised signup link; `consume_pending_invites` redeems it
  once the invitee actually creates an account, from either of the two
  places that can do that — native signup (`routers/auth.py::signup`) and
  OIDC first-login (`routers/auth_oidc.py`), since the invitee may reach
  either one first.
- `sso_only` orgs: `provision_sso_invite` grants access immediately by
  pre-creating the `User` row and its org/project roles up front, with no
  token or `PendingInvite` at all — see its docstring for why this is safe
  and how it's later adopted by a real SSO login.

See docs/decisions.md's "Self-signup, invites, and SSO" entry for the full
reasoning behind this split.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrgRole, ProjectRole
from app.models.notification import NotificationType
from app.models.organization import Organization, PendingInvite, UserOrgRole
from app.models.project import Project, UserProjectRole
from app.models.user import User
from app.services.audit import log_event
from app.services.email import send_email
from app.services.notifications import notify

_INVITE_LIFETIME = timedelta(days=14)


def create_pending_invite(
    db: Session,
    *,
    email: str,
    organization: Organization,
    project: Project | None,
    project_role: ProjectRole | None,
    invited_by: uuid.UUID,
) -> PendingInvite:
    """Creates a `PendingInvite` and emails a tokenised signup link.

    Only valid for `organization.sso_only == False` — callers must route to
    `provision_sso_invite` instead for an `sso_only` organisation (see
    module docstring).

    Args:
        db: Active database session; the row is added but not committed.
        email: The invitee's email address (lowercased by the caller).
        organization: The organisation being granted (as `member`, on
            consumption).
        project: The project being granted, or `None` for an org-only invite.
        project_role: Required iff `project` is set.
        invited_by: The inviting user.

    Returns:
        The created (uncommitted) `PendingInvite`.
    """
    invite = PendingInvite(
        email=email,
        organization_id=organization.id,
        project_id=project.id if project else None,
        project_role=project_role,
        invited_by=invited_by,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + _INVITE_LIFETIME,
    )
    db.add(invite)
    db.flush()
    settings = get_settings()
    signup_url = f"{settings.frontend_base_url.rstrip('/')}/signup?invite={invite.token}"
    if project is not None:
        body = f"You've been invited to join the project '{project.name}' in {organization.name}. Sign up here: {signup_url}"
    else:
        body = f"You've been invited to join {organization.name}. Sign up here: {signup_url}"
    send_email(email, f"You've been invited to {organization.name}", body)
    return invite


def consume_pending_invites(db: Session, user: User) -> None:
    """Redeems every unexpired, unaccepted `PendingInvite` matching `user`'s
    email, granting the org (and, if set, project) role each one specifies.

    Called after a `User` row is resolved via either native signup or OIDC
    login — safe to call unconditionally on every login, not only "first
    ever": the `accepted_at IS NULL` filter makes it a no-op once already
    consumed. Idempotent per organisation (a second invite to an org the
    user already holds a role in from an earlier invite doesn't duplicate
    the grant).
    """
    invites = db.scalars(
        select(PendingInvite).where(
            PendingInvite.email == user.email.lower(),
            PendingInvite.accepted_at.is_(None),
            PendingInvite.expires_at > datetime.now(UTC),
        )
    ).all()
    for invite in invites:
        _grant_invite(db, invite, user)


def provision_sso_invite(
    db: Session,
    *,
    email: str,
    organization: Organization,
    project: Project | None,
    project_role: ProjectRole | None,
    invited_by: uuid.UUID,
) -> User:
    """Pre-provisions a `User` and grants org/project roles immediately, for
    an invite into an `sso_only` organisation.

    Only valid for `organization.sso_only == True`. There is no working
    native-signup path to redeem a token against for such an org (native
    login is rejected outright for an account whose only organisation
    requires SSO, `auth_backends.native._all_orgs_sso_only`), so instead of
    a `PendingInvite`, this grants access up front — the invitee shows up as
    a real (if not-yet-logged-in) member right away, same as any
    `create_org_user`-provisioned account.

    `auth_backend="invited"` (not `"native"` or `"oidc"`) marks the row as
    not-yet-linked to a real identity: `NativeAuthBackend` rejects native
    login against it (its `password_hash` is also `None`, but the backend
    name check alone already blocks it), and
    `oidc_provisioning.find_or_provision_user`'s existing-by-email match
    adopts it unmodified on the invitee's actual first SSO login (flipping
    `auth_backend` to `"oidc"` and attaching `external_subject`/
    `oidc_issuer`) — that adoption already refuses to link when the IdP
    doesn't assert a verified email, so this pre-provisioned row inherits
    that existing anti-hijack protection for free.

    Returns:
        The created (uncommitted) `User`.
    """
    user = User(
        id=uuid.uuid4(),
        email=email,
        display_name=email.split("@")[0],
        auth_backend="invited",
        password_hash=None,
    )
    db.add(user)
    db.flush()
    db.add(UserOrgRole(user_id=user.id, organization_id=organization.id, role=OrgRole.MEMBER))
    log_event(
        db, entity_type="user", entity_id=user.id, action="sso_invite_provisioned",
        actor_id=invited_by, organization_id=organization.id,
    )
    if project is not None and project_role is not None:
        db.add(UserProjectRole(user_id=user.id, project_id=project.id, role=project_role))
        log_event(
            db, entity_type="project", entity_id=project.id, action="role_assigned",
            actor_id=invited_by, organization_id=organization.id, project_id=project.id,
            detail={"user_id": str(user.id), "role": project_role.value, "via": "sso_invite"},
        )
    login_url = f"{get_settings().frontend_base_url.rstrip('/')}/login/{organization.slug}" if organization.slug else None
    body = f"You've been added to {organization.name}"
    body += f" and the project '{project.name}'" if project is not None else ""
    body += ". This organisation uses single sign-on — "
    body += f"sign in via SSO at {login_url}." if login_url else "sign in via SSO next time you log in."
    send_email(email, f"You've been added to {organization.name}", body)
    return user


def _grant_invite(db: Session, invite: PendingInvite, user: User) -> None:
    existing_org_roles = set(
        db.scalars(
            select(UserOrgRole.role).where(
                UserOrgRole.user_id == user.id, UserOrgRole.organization_id == invite.organization_id
            )
        ).all()
    )
    if OrgRole.MEMBER not in existing_org_roles:
        db.add(UserOrgRole(user_id=user.id, organization_id=invite.organization_id, role=OrgRole.MEMBER))
        # This session is autoflush=False (app/database.py) — without an
        # explicit flush here, a second PendingInvite for the same org
        # processed later in this same consume_pending_invites loop
        # wouldn't see this just-added row in its own "already a member?"
        # query, and would try to insert a duplicate UserOrgRole, violating
        # its (user_id, organization_id, role) unique constraint.
        db.flush()
        log_event(
            db, entity_type="user", entity_id=user.id, action="invite_accepted",
            actor_id=user.id, organization_id=invite.organization_id,
        )
        notify(
            db, user, notification_type=NotificationType.PERMISSION_GRANTED,
            title="You've joined a new organisation",
            body="Your invite was accepted and you now have access.",
        )
    if invite.project_id is not None and invite.project_role is not None:
        already_has_role = db.scalar(
            select(UserProjectRole).where(
                UserProjectRole.user_id == user.id,
                UserProjectRole.project_id == invite.project_id,
                UserProjectRole.role == invite.project_role,
            )
        )
        if already_has_role is None:
            db.add(UserProjectRole(user_id=user.id, project_id=invite.project_id, role=invite.project_role))
            log_event(
                db, entity_type="project", entity_id=invite.project_id, action="role_assigned",
                actor_id=user.id, organization_id=invite.organization_id, project_id=invite.project_id,
                detail={"user_id": str(user.id), "role": invite.project_role.value, "via": "invite"},
            )
            notify(
                db, user, notification_type=NotificationType.PROJECT_JOINED,
                title="You've joined a project",
                body="Your invite was accepted and you now have project access.",
                project_id=invite.project_id,
            )
    invite.accepted_at = datetime.now(UTC)
