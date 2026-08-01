"""Pluggable authentication backend interface (C-U-06, C-U-07)."""

from app.auth_backends.base import AuthBackend, AuthResult
from app.auth_backends.native import NativeAuthBackend

__all__ = ["AuthBackend", "AuthResult", "NativeAuthBackend"]
