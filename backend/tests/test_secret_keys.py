"""Encryption key rotation, and the start-up check for values the configured keys cannot read."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.database import SessionLocal
from app.models.encrypted_type import _derive_fernet_key, decrypts_with_current_key, re_encrypt
from app.models.user import User
from app.services import secret_keys


def _use_keys(monkeypatch, current: str, previous: str = "") -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_secret_encryption_key", current)
    monkeypatch.setattr(settings, "app_secret_encryption_key_previous", previous)


def _store_secret(email: str, secret: str) -> None:
    db = SessionLocal()
    try:
        db.add(User(email=email, display_name="T", auth_backend="native", totp_secret=secret))
        db.commit()
    finally:
        db.close()


def test_a_previous_key_still_decrypts_and_rotation_moves_the_value_to_the_new_key(monkeypatch):
    old, new = "old-key-" + "o" * 30, "new-key-" + "n" * 30
    _use_keys(monkeypatch, old)
    _store_secret("rotate@example.com", "JBSWY3DPEHPK3PXP")
    _use_keys(monkeypatch, new, previous=old)

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "rotate@example.com").one().totp_secret == "JBSWY3DPEHPK3PXP"
        assert secret_keys.rotate(db)["users.totp_secret"] == 1
    finally:
        db.close()

    _use_keys(monkeypatch, new)  # the previous key is no longer needed
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "rotate@example.com").one().totp_secret == "JBSWY3DPEHPK3PXP"
        assert secret_keys.unreadable_counts(db) == {}
    finally:
        db.close()


def test_a_value_no_configured_key_reads_is_counted_logged_without_the_value_and_left_alone(monkeypatch, caplog):
    _use_keys(monkeypatch, "lost-key-" + "l" * 30)
    _store_secret("lost@example.com", "JBSWY3DPEHPK3PXP")
    _use_keys(monkeypatch, "replacement-" + "r" * 30)

    db = SessionLocal()
    try:
        with caplog.at_level("ERROR"):
            assert secret_keys.warn_if_unreadable(db) == {"users.totp_secret": 1}
        assert "users.totp_secret" in caplog.text and "JBSWY3DPEHPK3PXP" not in caplog.text
        assert secret_keys.rotate(db)["users.totp_secret"] == 0  # not destroyed by a rotation
        assert db.query(User).filter(User.email == "lost@example.com").one().totp_secret is None
    finally:
        db.close()


def test_rotating_an_unreadable_value_raises_and_a_readable_one_decrypts_under_the_current_key(monkeypatch):
    from cryptography.fernet import InvalidToken

    _use_keys(monkeypatch, "k" * 40)
    token = Fernet(_derive_fernet_key("k" * 40)).encrypt(b"x").decode()
    assert decrypts_with_current_key(token) and re_encrypt(token) != token
    with pytest.raises(InvalidToken):
        re_encrypt("not-a-token")
