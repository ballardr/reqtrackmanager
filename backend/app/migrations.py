"""
Module: migrations

Applies pending Alembic migrations programmatically at application startup
(I-M-02: the database must be easily initialised on first install; I-M-03:
the database must have a way of determining schema version). This means a
fresh deployment, or a deployment picking up a newer image with schema
changes, self-migrates to the current schema on boot instead of failing with
raw "column/table does not exist" errors and requiring an operator to run
`alembic upgrade head` by hand first.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    """Runs `alembic upgrade head` against the configured database."""
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
