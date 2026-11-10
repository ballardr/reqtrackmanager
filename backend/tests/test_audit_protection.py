"""The runtime database role can add to the audit trail and read it, and cannot change or remove an entry."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from app.config import get_settings
from app.database import engine as owner_engine
from app.services.audit_protection import apply_audit_protection

ROLE = "audit_runtime_test"


@pytest.fixture
def runtime_role(monkeypatch):
    with owner_engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))
        conn.execute(text(f"CREATE ROLE {ROLE} LOGIN PASSWORD 'runtime-pw'"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))  # the suite recreates the schema without the default grant
        conn.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {ROLE}"))
    monkeypatch.setattr(get_settings(), "audit_runtime_role", ROLE)
    yield ROLE
    with owner_engine.begin() as conn:
        conn.execute(text(f"DROP OWNED BY {ROLE}"))
        conn.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))


def _as_runtime():
    url = make_url(str(owner_engine.url.render_as_string(hide_password=False))).set(username=ROLE, password="runtime-pw")
    return create_engine(url, connect_args={"options": "-c search_path=public"})


def test_the_runtime_role_can_append_and_read_but_not_change_or_remove(runtime_role):
    assert apply_audit_protection() == "applied"
    event_id = uuid.uuid4()
    runtime = _as_runtime()
    try:
        with runtime.begin() as conn:
            conn.execute(
                text("INSERT INTO audit_events (id, entity_type, entity_id, action, created_at) VALUES (:i, 'x', 'y', 'z', now())"),
                {"i": event_id},
            )
            assert conn.scalar(text("SELECT count(*) FROM audit_events WHERE id = :i"), {"i": event_id}) == 1
        for statement in (
            "UPDATE audit_events SET action = 'tampered' WHERE id = :i",
            "DELETE FROM audit_events WHERE id = :i",
            "TRUNCATE audit_events",
            "UPDATE login_events SET email_attempted = 'x'",
            "DELETE FROM login_events",
        ):
            with pytest.raises(ProgrammingError), runtime.begin() as conn:
                conn.execute(text(statement), {"i": event_id})
        with runtime.begin() as conn:  # the one column filled in afterwards stays writable
            conn.execute(text("UPDATE login_events SET location = 'somewhere'"))
    finally:
        runtime.dispose()


def test_the_owner_still_changes_the_trail_because_foreign_key_actions_and_retention_run_as_the_owner(runtime_role):
    apply_audit_protection()
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))


def test_a_missing_or_owning_role_is_reported_not_applied(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "audit_runtime_role", "")
    assert apply_audit_protection() == "disabled"
    monkeypatch.setattr(settings, "audit_runtime_role", "no_such_role_here")
    assert apply_audit_protection() == "role_missing"
    owner = make_url(settings.database_url).username
    monkeypatch.setattr(settings, "audit_runtime_role", (owner or "reqtrack").lower())
    assert apply_audit_protection() in {"owner", "role_missing"}
    monkeypatch.setattr(settings, "audit_runtime_role", "Bad Role; DROP")
    assert apply_audit_protection() == "role_missing"
