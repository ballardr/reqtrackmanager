"""
Module: migrations

Applies pending Alembic migrations programmatically at application startup
(I-M-02: the database must be easily initialised on first install; I-M-03:
the database must have a way of determining schema version). This means a
fresh deployment, or a deployment picking up a newer image with schema
changes, self-migrates to the current schema on boot instead of failing with
raw "column/table does not exist" errors and requiring an operator to run
`alembic upgrade head` by hand first.

Also applies any currently-discovered *external* module's own schema
changes (`app.modules.registry.apply_external_module_migrations`,
compliance-module-plan.md's module system follow-up) right after the core
schema is current — gated behind `Settings.allow_external_modules`, a
no-op for the default deployment. See that function's own docstring for the
full gating/isolation rationale; this module only sequences it after the
core upgrade.

`configure_alembic_version_locations` (`app.modules.registry`, a further
Phase 11 follow-up) points the single Alembic chain `alembic upgrade head`
walks at every registered first-party module's own `migrations_dir`, in
addition to the core `alembic/versions` directory — so a module's revision
file living alongside the rest of its own code (e.g. `app.modules.
compliance.migrations`) is picked up here exactly as if it were still in
the flat core directory, with no per-module edit to this file needed.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.database import engine
from app.modules.registry import apply_external_module_migrations, configure_alembic_version_locations

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
