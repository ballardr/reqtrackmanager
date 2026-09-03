"""Regression pins for the `ServerSettings` singleton race found
incidentally while verifying the follow-up UX batch's Phase D
(docs/decisions.md) — unrelated to that phase's own work, but a real bug:
`get_server_settings` (`backend/app/services/branding.py`) used to be a
pure application-level "read then insert if absent" check with no DB
constraint backing it, so two concurrent requests could both observe "no
row yet" and both insert, leaving two real rows an unordered `SELECT`
could return either of unpredictably. Migration 0020 adds a `singleton_
guard` (`UNIQUE`, always `True`) column that makes a second `INSERT` fail
outright; `get_server_settings` catches that and re-reads.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.organization import ServerSettings
from app.services.branding import get_server_settings


def test_singleton_guard_constraint_blocks_a_second_row(client, admin_token):
    """The core regression pin: the DB itself, not just application
    convention, must refuse a second `server_settings` row."""
    db = SessionLocal()
    try:
        get_server_settings(db)  # ensures exactly one row exists
        count_before = db.scalar(select(func.count()).select_from(ServerSettings))
        assert count_before == 1

        db.add(ServerSettings(accent_color_hex="#000000"))
        try:
            db.commit()
            raised = False
        except IntegrityError:
            db.rollback()
            raised = True
        assert raised, "a second server_settings row must be rejected by the singleton_guard UNIQUE constraint"

        count_after = db.scalar(select(func.count()).select_from(ServerSettings))
        assert count_after == 1
    finally:
        db.close()


def test_get_server_settings_recovers_from_a_racing_insert(client, admin_token, monkeypatch):
    """Simulates the exact race `get_server_settings` now handles: this
    call's own read sees no row (a stale/racing view), but by the time its
    `INSERT` reaches the DB another row already exists (a concurrent
    request that "won") — it must recover by re-reading that row rather
    than raising `IntegrityError` up to the caller."""
    db = SessionLocal()
    try:
        winner = get_server_settings(db)  # the "concurrent" row that already exists

        real_scalar = db.scalar
        call_count = {"n": 0}

        def scalar_once_lies_about_no_row(*args, **kwargs):
            # First call (get_server_settings's own initial read): pretend
            # nothing exists yet, as a racing caller genuinely would see
            # before the winner's commit. Every subsequent call (the
            # recovery re-read after the forced IntegrityError) sees the
            # real state.
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return real_scalar(*args, **kwargs)

        monkeypatch.setattr(db, "scalar", scalar_once_lies_about_no_row)

        recovered = get_server_settings(db)
        assert recovered.id == winner.id
        assert call_count["n"] >= 2, "must have re-read after the forced IntegrityError, not just used the lied-about None"

        count = db.scalar(select(func.count()).select_from(ServerSettings))
        assert count == 1
    finally:
        db.close()
