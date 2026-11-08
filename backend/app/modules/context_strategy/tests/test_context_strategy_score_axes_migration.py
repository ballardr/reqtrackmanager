"""Tests for the migration that stores a Pain Point's scores one row per axis
(`migrations/0150_pain_point_score_axes.py`): every level held in the old Severity, Frequency and Confidence
columns is copied into `pain_point_score_axes` (an "all personas" row keeps its place as the General row, a persona
row is unchanged), the columns are dropped, and a repeated upgrade changes nothing.

Runs the real migration both ways, not a reimplementation of its SQL: scores are created through the API at head,
the live test database is downgraded to revision 0149 (which copies the axis rows back into the columns), the
columns are read, and the database is upgraded to head again (which copies them forward) and read through the API.
It always returns to head, even on failure, so the schema stays what every other test expects.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.context_strategy.tests.test_context_strategy_pain_point_scoring import (
    _entry,
    _get,
    _levels,
    _pain_point,
    _persona,
    _put,
    _setup,
)
from tests.conftest import build_alembic_config


@contextmanager
def _downgraded_to_0149():
    """Downgrades the live test database to revision 0149 (the three level columns exist again) for the `with`
    block, then always upgrades back to head."""
    command.downgrade(build_alembic_config(), "0149")
    try:
        yield
    finally:
        command.upgrade(build_alembic_config(), "head")


def test_scores_round_trip_through_the_columns_and_back_without_loss(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Axes Migration Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    tech = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)
    assert _put(client, token, pid, pp["id"], [
        _entry(levels, None, severity="Minor", frequency="Frequent"),
        _entry(levels, tech, severity="Major", confidence="High"),
    ]).status_code == 200
    before = {e["status"]: e["levels"] for e in _get(client, token, pid, pp["id"])["entries"]}

    with _downgraded_to_0149():
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT target_id IS NULL AS general, severity_level_id, frequency_level_id, confidence_level_id "
                "FROM pain_point_scores WHERE pain_point_id = :id"
            ), {"id": pp["id"]}).all()
            tables = conn.execute(text("SELECT to_regclass('pain_point_score_axes')")).scalar()
        by_kind = {("general" if row.general else "persona"): row for row in rows}
        assert str(by_kind["general"].severity_level_id) == levels["severity"]["Minor"]
        assert str(by_kind["general"].frequency_level_id) == levels["frequency"]["Frequent"]
        assert by_kind["general"].confidence_level_id is None
        assert str(by_kind["persona"].severity_level_id) == levels["severity"]["Major"]
        assert str(by_kind["persona"].confidence_level_id) == levels["confidence"]["High"]
        assert tables is None

    after = {e["status"]: e["levels"] for e in _get(client, token, pid, pp["id"])["entries"]}
    assert after == before

    # Running the upgrade again is harmless: no row is duplicated or lost.
    command.downgrade(build_alembic_config(), "0149")
    command.upgrade(build_alembic_config(), "head")
    assert {e["status"]: e["levels"] for e in _get(client, token, pid, pp["id"])["entries"]} == before
