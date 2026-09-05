"""Alembic migration environment: points at the application's settings and
metadata so `alembic upgrade head` and future autogenerate runs stay in
sync with the SQLAlchemy models (I-M-03: schema version tracking)."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (populates Base.metadata)
from alembic import context
from app.config import get_settings
from app.database import Base
from app.modules.registry import import_all_module_models

import_all_module_models()  # populates Base.metadata for every registered module's own models

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which would silently set
    # `.disabled = True` on every already-configured logger not named in
    # alembic.ini's [loggers] section — including uvicorn's own loggers and
    # this app's `logging.getLogger(__name__)` loggers, since migrations run
    # on every app startup (app/migrations.py) *after* uvicorn has already
    # set its loggers up. That silently swallowed all uvicorn access/error
    # logging and all app-level `logger.exception(...)` calls in every
    # deployment, which is how a real backend bug went undiagnosed for a
    # while (see docs/decisions.md).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
