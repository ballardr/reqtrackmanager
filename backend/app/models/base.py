"""
Module: models.base

Shared mixins used by every ORM model: a UUID primary key and created/updated
timestamps. Centralising these avoids repeating the same columns on every
table and keeps id/timestamp semantics consistent across the schema.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Returns the current UTC time. Used as a shared column default."""
    return datetime.now(UTC)


def str_enum(enum_cls, length: int = 30) -> SqlEnum:
    """Builds a varchar-backed SQLAlchemy Enum type for a `str, enum.Enum` class.

    Plain `mapped_column(String(N))` with a `Mapped[SomeEnum]` annotation
    stores the value correctly but does NOT deserialize back into an enum
    member on read — SQLAlchemy returns a plain str, which breaks any code
    calling `.value` on a freshly-loaded attribute. Using `native_enum=False`
    keeps the column a plain VARCHAR (no Postgres CREATE TYPE / migration
    friction when adding members) while still round-tripping to real Python
    enum instances.
    """
    return SqlEnum(enum_cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])


class UUIDPKMixin:
    """Adds a UUID primary key column named `id` to a model."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Adds `created_at` and `updated_at` audit timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
