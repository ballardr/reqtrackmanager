"""
Module: services.lookups

Row lookups that answer 404 instead of `None`.

Responsibilities:
- `get_or_404`: one row by primary key, else an HTTP 404 naming the record kind.
- `project_or_404`: the project, else 404 `Project not found.`
- `present`: the non-`None` members of a nullable column's values, typed as such.

Design decisions:
- A route that has already passed its permission dependency still has to prove the row exists
  before dereferencing it; a typed helper replaces the unchecked `db.get(...)` whose `None`
  surfaced as an `AttributeError` (a 500) and as a type error in every caller.
- The 404 text is the one the permission helpers in `services.rbac` already use, so a missing
  project reads the same whichever check notices it first.

Dependencies: SQLAlchemy sessions, FastAPI's `HTTPException`, the `Project` model.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project

_T = TypeVar("_T")


def get_or_404(db: Session, model: type[_T], key: object, label: str) -> _T:
    """Loads a row by primary key.

    Args:
        db: Database session.
        model: The mapped class.
        key: The primary key value.
        label: The record kind used in the message (`"Project"`).

    Returns:
        The row.

    Raises:
        HTTPException: 404 `<label> not found.` when no row has that key.
    """
    row = db.get(model, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    return row


def project_or_404(db: Session, project_id: UUID) -> Project:
    """Loads a project by id, else raises 404 `Project not found.`."""
    return get_or_404(db, Project, project_id, "Project")


def present(values: Iterable[_T | None]) -> list[_T]:
    """The members of `values` that are not `None`, in order.

    Used on the rows of a nullable column that the query already filters with `IS NOT NULL`, so the
    narrowing is stated in the type as well as in the SQL.
    """
    return [value for value in values if value is not None]
