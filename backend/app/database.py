"""
Module: database

Provides the SQLAlchemy engine, session factory, and declarative base used
throughout the application. This module has no knowledge of any specific
domain model; it only wires up connectivity.

External dependencies: SQLAlchemy, PostgreSQL (via psycopg2).
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
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
