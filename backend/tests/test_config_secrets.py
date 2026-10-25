"""Tests for the weak-secret check (`Settings.weak_secret_problems`, `main._check_secrets`) and the bounded
request-method metric label."""

import pytest

from app import main as app_main
from app.config import Settings

_STRONG = {"jwt_secret": "j" * 40, "app_secret_encryption_key": "short-but-not-the-placeholder", "server_admin_password": "Str0ng-and-unique!"}


def test_placeholders_and_short_jwt_secrets_are_reported_without_their_values():
    problems = Settings(_env_file=None).weak_secret_problems()
    text = " ".join(problems)
    assert "JWT_SECRET" in text and "APP_SECRET_ENCRYPTION_KEY" in text and "SERVER_ADMIN_PASSWORD" in text
    assert "change-me-in-production" not in text and "ChangeMe123!" not in text


def test_strong_values_have_no_problems_and_the_encryption_key_is_not_length_checked():
    assert Settings(_env_file=None, **_STRONG).weak_secret_problems() == []


def test_the_bundled_object_store_default_secret_is_flagged_only_for_the_s3_backend():
    assert Settings(_env_file=None, **_STRONG, storage_backend="local").weak_secret_problems() == []
    flagged = Settings(_env_file=None, **_STRONG, storage_backend="s3", storage_s3_secret_key="minioadmin").weak_secret_problems()
    assert any("STORAGE_S3_SECRET_KEY" in p for p in flagged)


def test_startup_refuses_weak_secrets_only_when_asked(monkeypatch, caplog):
    weak = Settings(_env_file=None)
    monkeypatch.setattr(app_main, "settings", weak)
    app_main._check_secrets()  # warns, does not raise
    assert "Weak or placeholder secrets" in caplog.text

    strict = Settings(_env_file=None, require_strong_secrets=True)
    monkeypatch.setattr(app_main, "settings", strict)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        app_main._check_secrets()


def test_an_unrecognised_request_method_does_not_mint_a_metric_series(client):
    for method in ("ATTACKONE", "ATTACKTWO"):
        client.request(method, "/api/v1/nope")
    body = client.get("/metrics").text
    assert "ATTACKONE" not in body and "ATTACKTWO" not in body
    assert 'method="OTHER"' in body
