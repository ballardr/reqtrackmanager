"""
Module: auth_backends.native

The default, always-available authentication backend: verifies an email and
password against the locally stored bcrypt hash (C-U-17).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_backends.base import AuthResult
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

        Every failure path returns the same generic error message and
        performs a real bcrypt comparison (against a dummy hash when there's
        no real one to check), so neither the response body nor response
        timing reveals whether an email exists, uses a different auth
        backend, or is registered-but-deactivated — deactivated-account
        status in particular is not something an unauthenticated caller
        should be able to enumerate.
        """
        user = db.scalar(select(User).where(User.email == identifier.lower()))
        if user is None or user.auth_backend != self.name or not user.password_hash:
            verify_password(credential, _DUMMY_HASH)
            return AuthResult(success=False, error="Invalid email or password.")
        if not verify_password(credential, user.password_hash):
            return AuthResult(success=False, error="Invalid email or password.")
        if not user.is_active or user.is_archived:
            return AuthResult(success=False, error="Invalid email or password.")
        return AuthResult(success=True, user=user)
