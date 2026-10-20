"""
Module: services.user_provisioning

The one place an administrator creates a person's account or invites one.

Responsibilities:
- `create_native_user`: an account with an admin-set password, optionally with an organisation role
  (Org Admin's "New user", Server Management's "Add user").
- `invite_user`: an emailed sign-up link that grants `member` in the organisation, if any, on redemption (Org Admin's
  "Invite user", Server Management's "Add user" by invite).
- Keep email uniqueness, lower-casing, the `sso_only` guard, the shared password rule and the audit row
  in one place so the two entry points cannot drift.

Design decisions:
- Callers authorise; this module does not. It raises `HTTPException` with the same messages the
  endpoints always returned, so moving a check here changes no response.
- The typed password is hashed immediately and never returned, logged or audited.
- An invite may name no organisation: the person then signs up to an account with no membership, the
  same shape as an always-on self-signup.

Dependencies: `security` (hashing, password rule), `services.invites`, `services.audit`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.organization import Organization, PendingInvite, UserOrgRole
from app.models.user import User
from app.security import MIN_PASSWORD_LENGTH, hash_password
from app.services import invites
from app.services.audit import log_event


def _require_unused_email(db: Session, email: str) -> None:
    """Rejects an email that already has an account.

    Raises:
        HTTPException: 409 when a user with `email` (lower-case) exists.
    """
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")


def create_native_user(
    db: Session,
    *,
    email: str,
    display_name: str,
    password: str,
    organization_id: UUID | None,
    role: OrgRole,
    actor_id: UUID,
) -> User:
    """Creates a password-credentialed account, in an organisation when one is given.

    Args:
        db: Active session; the rows are added and flushed, not committed.
        email: The new user's email (lower-cased here).
        display_name: Shown name.
        password: Clear-text password; validated against the shared rule, hashed, never stored or echoed.
        organization_id: Organisation to join with `role`, or `None` for an account with no membership.
        role: The organisation role granted (ignored when `organization_id` is `None`).
        actor_id: The administrator creating the account (audit actor).

    Returns:
        The created (uncommitted) `User`.

    Raises:
        HTTPException: 400 password shorter than `MIN_PASSWORD_LENGTH`, or an `sso_only` organisation;
            404 organisation not found; 409 email already in use.
    """
    email = email.lower()
    _require_unused_email(db, email)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if organization_id is not None:
        org = db.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
        if org.sso_only:
            # A native-credentialed account whose only org is sso_only could never log in
            # (NativeAuthBackend rejects native login when every org requires SSO).
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This organisation is SSO-only; native accounts cannot be created for it directly.",
            )
    user = User(
        email=email, display_name=display_name, password_hash=hash_password(password), auth_backend="native"
    )
    db.add(user)
    db.flush()
    if organization_id is not None:
        db.add(UserOrgRole(user_id=user.id, organization_id=organization_id, role=role))
    log_event(
        db, entity_type="user", entity_id=user.id, action="created",
        actor_id=actor_id, organization_id=organization_id,
    )
    return user


def invite_user(db: Session, *, email: str, organization_id: UUID | None, actor_id: UUID) -> PendingInvite:
    """Emails a sign-up link; redeeming it grants `member` in the organisation, if one is given.

    Args:
        db: Active session; the invite is added and flushed, not committed.
        email: The invitee's email (lower-cased here).
        organization_id: The organisation being granted, or `None` to invite a person who joins no
            organisation yet.
        actor_id: The inviting administrator.

    Returns:
        The created (uncommitted) `PendingInvite`.

    Raises:
        HTTPException: 404 organisation not found; 400 `sso_only` organisation (no native sign-up to
            redeem a link against); 409 email already in use.
    """
    org = None
    if organization_id is not None:
        org = db.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
        if org.sso_only:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This organisation is SSO-only; email invites are not used — access is provisioned at SSO login.",
            )
    email = email.lower()
    _require_unused_email(db, email)
    invite = invites.create_pending_invite(
        db, email=email, organization=org, project=None, project_role=None, invited_by=actor_id,
    )
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invited",
        actor_id=actor_id, organization_id=organization_id, detail={"email": email},
    )
    return invite
