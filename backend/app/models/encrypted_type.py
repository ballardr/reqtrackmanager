"""
Module: models.encrypted_type

A SQLAlchemy column type that encrypts values before they are written and decrypts them on read, for
columns holding genuine secrets (SSO client secrets, TOTP secrets, per-org SMTP passwords) rather than
data that needs only access control. Values are unreadable to someone with direct database access but
without `APP_SECRET_ENCRYPTION_KEY` (SOC 2 encryption and key management policy).

Uses Fernet (symmetric authenticated encryption, AES-128-CBC + HMAC, from `cryptography`), keyed from
`Settings.app_secret_encryption_key` through SHA-256 key derivation, which turns an arbitrary-length
secret into Fernet's 32-byte key.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import get_settings
from app.metrics import secret_decrypt_failures_total

logger = logging.getLogger(__name__)
_LAST_FAILURE_LOG = 0.0


def _derive_fernet_key(secret: str) -> bytes:
    """Derives a Fernet-compatible 32-byte urlsafe-base64 key from an
    arbitrary-length configured secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> MultiFernet:
    """Encrypts with the configured key and decrypts with it or any `APP_SECRET_ENCRYPTION_KEY_PREVIOUS` (rotation)."""
    settings = get_settings()
    keys = [settings.app_secret_encryption_key, *[k.strip() for k in settings.app_secret_encryption_key_previous.split(",") if k.strip()]]
    return MultiFernet([Fernet(_derive_fernet_key(k)) for k in keys])


def re_encrypt(ciphertext: str) -> str:
    """The same secret under the current key (for `scripts/rotate_secret_key.py`).

    Raises:
        InvalidToken: No configured key decrypts it.
    """
    return _fernet().rotate(ciphertext.encode()).decode()


def decrypts_with_current_key(ciphertext: str) -> bool:
    """Whether `ciphertext` is a valid token under the configured `APP_SECRET_ENCRYPTION_KEY`.

    `EncryptedString` hides a failed decrypt as `None`, so a restored database read with the wrong key
    looks like "no secret configured". Disaster-recovery verification calls this on the raw stored value
    to tell those two cases apart; the plaintext is never returned.

    Args:
        ciphertext: The raw value stored in an `EncryptedString` column.

    Returns:
        True when the configured key decrypts it, False otherwise.
    """
    try:
        _fernet().decrypt(ciphertext.encode())
    except InvalidToken:
        return False
    return True


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
            # A value written before encryption was enabled, or under a key no longer configured. None (not
            # an exception) matches how callers treat an absent secret ("not configured"), so a read does
            # not crash the request. It is counted and logged because a second factor cannot be verified
            # and a single sign-on secret reads as empty until the right key is restored.
            _note_decrypt_failure()
            return None


def _note_decrypt_failure() -> None:
    """Counts an undecryptable stored secret and logs it at most once a minute (never the value)."""
    global _LAST_FAILURE_LOG
    secret_decrypt_failures_total.inc()
    now = time.monotonic()
    if now - _LAST_FAILURE_LOG > 60:
        _LAST_FAILURE_LOG = now
        logger.error(
            "A stored secret could not be decrypted with APP_SECRET_ENCRYPTION_KEY or APP_SECRET_ENCRYPTION_KEY_PREVIOUS; "
            "restore the key it was written under."
        )
