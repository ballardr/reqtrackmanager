"""
Module: models.encrypted_type

A SQLAlchemy column type that transparently encrypts values before they're
written to the database and decrypts them on read, for columns that store
genuine secrets — SSO client secrets, TOTP secrets, per-org SMTP passwords —
rather than data that only needs least-privilege *access* control. These
values were previously stored as plain `String` columns, relying entirely on
infrastructure-level disk encryption (SOC 2 encryption-and-key-management
hardening pass); this closes that gap at the application layer, so the
values are unreadable even to someone with direct database access but no
`APP_SECRET_ENCRYPTION_KEY`.

Uses Fernet (symmetric, authenticated encryption — AES-128-CBC + HMAC,
built on `cryptography`, already a transitive dependency via
`python-jose[cryptography]`), keyed from `Settings.app_secret_encryption_key`
via SHA-256 key derivation (turns an arbitrary-length configured secret into
Fernet's required 32-byte key, the same way `jwt_secret` is an arbitrary
string rather than a pre-formatted key).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


def _derive_fernet_key(secret: str) -> bytes:
    """Derives a Fernet-compatible 32-byte urlsafe-base64 key from an
    arbitrary-length configured secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_fernet_key(get_settings().app_secret_encryption_key))


class EncryptedString(TypeDecorator):
    """A `String` column whose value is encrypted at rest.

    Application code always reads/writes plaintext; only the database ever
    sees ciphertext. `process_bind_param` runs on write, `process_result_value`
    on read — both no-ops for `None`, so nullable secret columns behave
    exactly as before.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # A value written before encryption was enabled, or under a
            # different APP_SECRET_ENCRYPTION_KEY. Surfacing None (rather
            # than raising) matches how every caller already treats an
            # absent secret — "not configured" — instead of crashing the
            # request that happens to read this row.
            return None
