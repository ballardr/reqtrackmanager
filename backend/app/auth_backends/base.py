"""
Module: auth_backends.base

Defines the AuthBackend interface. The implementation of user storage must
allow different identity backends to be used (C-U-06), such as the native
credential store implemented here, or a future OAuth/SSO backend (C-U-07,
Keycloak/Authentica per docs/requirements.md). Ossa (v1) ships only the
native backend; this interface is the seam a future SSO backend would
implement without requiring changes to the rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.user import User


@dataclass
class AuthResult:
    """Outcome of an authentication attempt.

    Attributes:
        success: Whether authentication succeeded.
        user: The authenticated User, if success is True.
        error: A human-readable failure reason, if success is False.
    """

    success: bool
    user: User | None = None
    error: str | None = None


class AuthBackend(Protocol):
    """Interface every authentication backend must implement."""

    name: str

    def authenticate(self, db: Session, identifier: str, credential: str) -> AuthResult:
        """Authenticates a user given an identifier and credential.

        Args:
            db: An active database session.
            identifier: The login identifier (e.g. email).
            credential: The credential to verify (e.g. password).

        Returns:
            An AuthResult describing the outcome.
        """
        ...
