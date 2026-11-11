"""
Module: services.password_change_gate

Holds an account whose password an administrator typed to the one thing it must do first: change it
(access control Known Gap 6).

Responsibilities:
- `enforce`: refuse every request of an account with `must_change_password` except reading itself, changing the
  password and signing out.
- The flag is set when an administrator creates an account with a typed password and cleared by a password change or
  a completed reset.

Design decisions:
- Everything else is refused, reads included: the administrator knows the password, so until it changes the session
  is not evidence that the person is the one at the keyboard.
- Applied in `deps` for every credential (session and Personal Access Token), like the policy acknowledgement gate.

External dependencies: none.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.models.user import User

BLOCK_CODE = "password_change_required"
_OPEN = {("GET", "/api/v1/auth/me"), ("POST", "/api/v1/auth/change-password")}


def enforce(user: User, method: str, path: str) -> None:
    """Refuses the request while the account must change its password.

    Raises:
        HTTPException: 403 with `BLOCK_CODE` in the detail.
    """
    if user.must_change_password and (method.upper(), path.rstrip("/")) not in _OPEN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": BLOCK_CODE, "message": "Change your password before continuing."},
        )
