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
from app.security import verify_password


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
        """
        user = db.scalar(select(User).where(User.email == identifier.lower()))
        if user is None or user.auth_backend != self.name or not user.password_hash:
            return AuthResult(success=False, error="Invalid email or password.")
        if not user.is_active or user.is_archived:
            return AuthResult(success=False, error="This account is deactivated.")
        if not verify_password(credential, user.password_hash):
            return AuthResult(success=False, error="Invalid email or password.")
        return AuthResult(success=True, user=user)
