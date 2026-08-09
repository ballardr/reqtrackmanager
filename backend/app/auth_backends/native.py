"""
Module: auth_backends.native

The default, always-available authentication backend: verifies an email and
password against the locally stored bcrypt hash (C-U-17). Also enforces
`Organization.sso_only` (a user whose every org membership requires SSO
cannot authenticate natively even with a correct password) — previously a
UI-only hint on the org's branded login page, not a real backend control.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_backends.base import AuthResult
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.security import hash_password, verify_password

# A fixed, valid bcrypt hash with no corresponding real password, verified
# against on every not-found/wrong-backend login attempt purely to spend the
# same amount of time bcrypt verification normally takes — otherwise that
# code path returns near-instantly while a real user's wrong-password
# attempt takes bcrypt's full (deliberately slow) comparison time, letting
# an attacker enumerate valid account emails from response timing alone,
# independent of the response body. Computed once at import time, not
# hardcoded, so it always matches this process's actual bcrypt configuration.
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

        Every failure path up to and including the correct-password check
        returns the same generic error message and performs a real bcrypt
        comparison (against a dummy hash when there's no real one to check),
        so neither the response body nor response timing reveals whether an
        email exists, uses a different auth backend, or is
        registered-but-deactivated. The one deliberate exception is the
        `sso_only` rejection below: it only fires after a *correct* password
        match, so it cannot be used to enumerate accounts — the caller has
        already proven they know this account's real password.
        """
        user = db.scalar(select(User).where(User.email == identifier.lower()))
        if user is None or user.auth_backend != self.name or not user.password_hash:
            verify_password(credential, _DUMMY_HASH)
            return AuthResult(success=False, error="Invalid email or password.")
        if not verify_password(credential, user.password_hash):
            return AuthResult(success=False, error="Invalid email or password.")
        if not user.is_active or user.is_archived:
            return AuthResult(success=False, error="Invalid email or password.")
        if _all_orgs_sso_only(db, user.id):
            # Deliberately a distinct, specific message rather than the
            # generic one above: the caller already proved they know the
            # correct password, so telling them to use SSO instead leaks
            # nothing an attacker enumerating accounts could exploit — this
            # is not the enumeration-sensitive wrong-password path the
            # generic message/dummy-hash comparison above exists to protect.
            return AuthResult(success=False, error="This account must sign in via SSO.")
        return AuthResult(success=True, user=user)


def _all_orgs_sso_only(db: Session, user_id: uuid.UUID) -> bool:
    """Whether every organisation `user_id` belongs to has `sso_only=True`.

    Used to enforce `Organization.sso_only` at the one place it previously
    had no real teeth (native login always succeeded regardless of the
    flag — it only hid the native form on that org's branded login page).
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
