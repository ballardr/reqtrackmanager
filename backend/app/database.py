"""
Module: database

Provides the SQLAlchemy engine, session factory, and declarative base used
throughout the application. This module has no knowledge of any specific
domain model; it only wires up connectivity (and DB statement metrics).

External dependencies: SQLAlchemy, PostgreSQL (via psycopg2).
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import profiling
from app.config import get_settings
from app.metrics import instrument_engine

settings = get_settings()

# `connect_timeout` bounds how long an unreachable database can stall a request
# (notably the /health probe) instead of waiting on the OS TCP timeout.
# The pool bounds how many connections one worker holds (`pool_size` kept, `max_overflow` more under load); the
# deployment's total must stay under PostgreSQL's `max_connections` (see `Settings.db_pool_size`).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    connect_args={"connect_timeout": 5},
)
instrument_engine(engine)
if settings.profile_mode:
    profiling.instrument_engine(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base class shared by all ORM models."""


def get_db() -> Generator:
    """FastAPI dependency that yields a database session and closes it after use.

    Yields:
        A SQLAlchemy Session bound to the configured engine.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
