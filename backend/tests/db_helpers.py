"""
Module: tests.db_helpers

Typed row lookups for tests.

`must_get` and `must_scalar` replace a bare `db.get(Model, id)` or `db.scalar(select(...))`.
A missing row fails the test at the lookup, not later as an `AttributeError` (or a type error).

`audit_detail` and `registered_module` give an audit event's detail and a registered module the same guarantee.

Dependencies: SQLAlchemy sessions, the audit model and the module registry.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.modules.registry import ModuleDefinition, get_module

_T = TypeVar("_T")


def must_get(db: Session, model: type[_T], key: object) -> _T:
    """Loads a row by primary key, failing the test when it is absent.

    Args:
        db: Database session.
        model: The mapped class.
        key: The primary key value.

    Returns:
        The row.

    Raises:
        AssertionError: no row has that key.
    """
    row = db.get(model, key)
    assert row is not None, f"{model.__name__} {key!r} not found"
    return row


def must_scalar(db: Session, statement: Select[tuple[_T]]) -> _T:
    """Runs a single-column select and returns its first value, failing the test when there is none.

    Args:
        db: Database session.
        statement: A select of one entity or column.

    Returns:
        The first result.

    Raises:
        AssertionError: the select returned no row.
    """
    value = db.scalar(statement)
    assert value is not None, "select returned no row"
    return value


def audit_detail(event: AuditEvent) -> dict:
    """The audit event's detail payload, failing the test when the event recorded none.

    Args:
        event: An audit event row.

    Returns:
        The detail dictionary.

    Raises:
        AssertionError: the event has no detail.
    """
    assert event.detail is not None, f"audit event {event.action!r} has no detail"
    return event.detail


def registered_module(key: str) -> ModuleDefinition:
    """The registered module definition for `key`, failing the test when none is registered.

    Args:
        key: The module key.

    Returns:
        The definition.

    Raises:
        AssertionError: no module is registered under the key.
    """
    definition = get_module(key)
    assert definition is not None, f"module {key!r} is not registered"
    return definition
