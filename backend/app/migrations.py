"""
Module: migrations

Applies pending Alembic migrations at application startup (I-M-02: the database is initialised on first
install; I-M-03: the schema version is determinable), so a fresh deployment, or one picking up an image with
schema changes, self-migrates instead of failing with "column/table does not exist".

Also applies any discovered external module's own schema changes
(`app.modules.registry.apply_external_module_migrations`) after the core schema is current; it is gated by
`Settings.allow_external_modules` and a no-op by default.

`configure_alembic_version_locations` (`app.modules.registry`) points the single Alembic chain at every
registered first-party module's `migrations_dir` as well as the core `alembic/versions` directory, so a
module's revision files live beside its code (for example `app.modules.compliance.migrations`) with no
per-module edit here.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.database import engine
from app.modules.registry import apply_external_module_migrations, configure_alembic_version_locations
from app.services.audit_protection import apply_audit_protection

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    """Runs `alembic upgrade head` against the configured database, then
    applies any currently-discovered external module's own migration
    (`apply_external_module_migrations`) — a no-op unless `Settings.
    allow_external_modules` is set."""
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    configure_alembic_version_locations(cfg)
    command.upgrade(cfg, "head")
    apply_external_module_migrations(engine)
    apply_audit_protection()
