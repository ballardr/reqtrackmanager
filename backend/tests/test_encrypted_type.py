"""Tests for `models.encrypted_type.EncryptedString` (SOC 2 encryption
hardening pass): confirms secret columns (`User.totp_secret`,
`Organization.oidc_client_secret`, `Organization.smtp_password`) are
genuinely encrypted in the database, not just formatted differently, and
that the ORM still round-trips the original plaintext transparently."""

import uuid

from cryptography.fernet import Fernet
from sqlalchemy import text

from app.database import SessionLocal
from app.models.encrypted_type import EncryptedString, _derive_fernet_key
from app.models.organization import Organization
from app.models.user import User


def test_derived_key_is_deterministic_and_fernet_compatible():
    key_a = _derive_fernet_key("some-configured-secret")
    key_b = _derive_fernet_key("some-configured-secret")
    assert key_a == key_b
    # Must not raise — confirms the derived key is a valid Fernet key.
    Fernet(key_a)


def test_derived_key_differs_for_different_secrets():
    assert _derive_fernet_key("secret-one") != _derive_fernet_key("secret-two")


def test_totp_secret_is_encrypted_at_rest_and_round_trips():
    db = SessionLocal()
    try:
        user = User(
            id=uuid.uuid4(), email=f"enc-test-{uuid.uuid4()}@example.com", display_name="Enc Test",
            auth_backend="native", password_hash="not-a-real-hash",
        )
        db.add(user)
        db.flush()
        plaintext = "JBSWY3DPEHPK3PXP"
        user.totp_secret = plaintext
        db.commit()

        raw = db.execute(text("SELECT totp_secret FROM users WHERE id = :id"), {"id": str(user.id)}).scalar()
        assert raw != plaintext
        assert plaintext not in raw

        db.expire(user)
        assert user.totp_secret == plaintext
    finally:
        db.rollback()
        db.close()


def test_oidc_client_secret_and_smtp_password_are_encrypted_at_rest():
    db = SessionLocal()
    try:
        org = Organization(name="Encryption Test Org")
        db.add(org)
        db.flush()
        org.oidc_client_secret = "super-secret-oidc-value"
        org.smtp_password = "super-secret-smtp-value"
        db.commit()

        raw_oidc, raw_smtp = db.execute(
            text("SELECT oidc_client_secret, smtp_password FROM organizations WHERE id = :id"),
            {"id": str(org.id)},
        ).one()
        assert raw_oidc != "super-secret-oidc-value"
        assert "super-secret-oidc-value" not in raw_oidc
        assert raw_smtp != "super-secret-smtp-value"
        assert "super-secret-smtp-value" not in raw_smtp

        db.expire(org)
        assert org.oidc_client_secret == "super-secret-oidc-value"
        assert org.smtp_password == "super-secret-smtp-value"
    finally:
        db.rollback()
        db.close()


def test_null_secret_round_trips_as_none():
    db = SessionLocal()
    try:
        org = Organization(name="Null Secret Org")
        db.add(org)
        db.flush()
        assert org.oidc_client_secret is None
        db.commit()
        db.expire(org)
        assert org.oidc_client_secret is None
    finally:
        db.rollback()
        db.close()


def test_process_result_value_returns_none_for_undecryptable_value():
    """A value written under a different/rotated key (or otherwise not
    valid Fernet ciphertext) is surfaced as None rather than raising,
    matching how every caller already treats an absent secret."""
    col = EncryptedString(255)
    assert col.process_result_value("not-valid-fernet-ciphertext", dialect=None) is None
    assert col.process_bind_param(None, dialect=None) is None
