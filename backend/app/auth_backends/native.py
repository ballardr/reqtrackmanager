"""
Module: auth_backends.native

The default, always-available authentication backend: verifies an email and
password against the locally stored bcrypt hash (C-U-17). Also enforces
`Organization.sso_only`: a user whose every org membership requires SSO
cannot authenticate natively even with a correct password.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_backends.base import AuthResult
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.security import hash_password, verify_password

CONFIRMATION_REQUIRED_MESSAGE = (
    "Confirm your email address before signing in. Open the link in the email we sent when you signed up."
)
RESET_REQUIRED_MESSAGE = (
    "Your password must be reset before you can sign in. Choose \"Forgot your password?\" to get a reset link."
)

# A valid bcrypt hash with no real password, verified on every not-found/wrong-backend login attempt so
# that path takes the same time as a wrong password for a real user; otherwise response timing would let
# an attacker enumerate account emails. Computed at import so it matches the process's bcrypt configuration.
_DUMMY_HASH = hash_password("not-a-real-password-used-only-for-constant-time-comparison")


class NativeAuthBackend:
    """Authenticates users against the local `users` table."""

    name = "native"

    def authenticate(self, db: Session, identifier: str, credential: str) -> AuthResult:
        """Authenticates by email + password.

        Args:
            db: An active database session.
            identifier: The user's email address.
            credential: The plaintext password to verify.

        Returns:
            An AuthResult indicating success/failure and the matched user.

        Every failure up to and including the password check returns the same generic message after a
        real bcrypt comparison (against a dummy hash when there is none to check), so neither the body
        nor the timing reveals whether an email exists, uses another backend or is deactivated. The
        `sso_only` rejection fires only after a correct password, so it cannot enumerate accounts.
        """
        user = db.scalar(select(User).where(User.email == identifier.lower()))
        if user is None or user.auth_backend != self.name or not user.password_hash:
            verify_password(credential, _DUMMY_HASH)
            return AuthResult(success=False, error="Invalid email or password.")
        if not verify_password(credential, user.password_hash):
            return AuthResult(success=False, error="Invalid email or password.")
        if not user.is_active or user.is_archived:
            return AuthResult(success=False, error="Invalid email or password.")
        if user.must_reset_credentials:
            # Like the SSO message below, only reachable after a correct password, so it reveals nothing to
            # someone enumerating accounts. The old password is suspect (forced reset), so no session is
            # issued; the person gets a reset link instead.
            return AuthResult(success=False, user=user, error=RESET_REQUIRED_MESSAGE, reset_required=True)
        if user.email_confirmation_pending:
            # Only after a correct password, like the messages around it, so it cannot be used to find accounts.
            return AuthResult(success=False, user=user, error=CONFIRMATION_REQUIRED_MESSAGE, confirmation_required=True)
        if all_orgs_sso_only(db, user.id):
            # A specific message: the caller already proved the correct password, so this leaks nothing
            # to an attacker enumerating accounts.
            return AuthResult(success=False, error="This account must sign in via SSO.")
        return AuthResult(success=True, user=user)


def all_orgs_sso_only(db: Session, user_id: uuid.UUID) -> bool:
    """Whether every organisation `user_id` belongs to has `sso_only=True`.

    Enforces `Organization.sso_only` for native login.
    A user with *no* org memberships (e.g. an `always_on`-signup account not
    yet assigned to any org) is never blocked by this — there is no
    SSO-only org to conflict with. A user who belongs to at least one
    non-SSO-only org keeps native login working for that membership, since
    their password remains a legitimate credential there.
    """
    org_ids = list(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user_id)).all())
    if not org_ids:
        return False
    sso_only_flags = db.scalars(select(Organization.sso_only).where(Organization.id.in_(org_ids))).all()
    return all(sso_only_flags)
