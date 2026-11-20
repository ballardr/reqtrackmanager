"""
Module: services.markdown_fields

Enforces the limits of every declared Markdown field when the value is written, whichever path writes it.

Responsibilities:
- Resolve the registry's `MarkdownField` declarations into `{model class: {attribute: field}}` and the inventory rows
  (`declared_columns`, `column_key`).
- Check, in a session `before_flush` hook, each new or changed declared attribute against `validate_markdown` (size,
  nesting, diagram count and size, control characters) and refuse the write with a 422 naming the field.

Design decisions:
- One hook instead of a validator per request schema: an endpoint, a file import, a project bundle import, an MCP tool
  and a seed all end in the same flush, so no path can store what another refuses and a field declared later is
  covered with no further code.
- Only an attribute that changed is checked, so a record already stored above a limit (a text written before the field
  became Markdown) is refused only when that field is edited again, and an edit of another field is not blocked.
- The refusal is an `HTTPException` (422), the shape the Decision limits already answered with; a caller that stages
  rows (an import) turns it into that row's error.
- The hook is installed by `install()` from the application start, not as an import side effect.
- The declaration map is resolved lazily on the first flush, after every module's models are imported.

Dependencies: `modules.registry` (the declarations), `services.markdown_text` (the limits), SQLAlchemy.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.modules.registry import MarkdownField, get_markdown_fields
from app.services.markdown_text import MarkdownLimitError, validate_markdown

_lock = threading.Lock()
_by_class: dict[type, dict[str, MarkdownField]] | None = None


def column_key(field: MarkdownField) -> str:
    """
    The `table.column` name of a declared field.

    Args:
        field: A Markdown field declaration.

    Returns:
        The table and column name, joined by a dot (`risk_versions.statement`).
    """
    column = field.column.property.columns[0]
    return f"{column.table.name}.{column.name}"


def declared_columns() -> dict[str, MarkdownField]:
    """
    Every declared Markdown field by `table.column`.

    Returns:
        The declarations, core and module.

    Raises:
        ValueError: If a column is declared twice.
    """
    found: dict[str, MarkdownField] = {}
    for declared in get_markdown_fields():
        key = column_key(declared)
        if key in found:
            raise ValueError(f"{key} is declared as Markdown twice")
        found[key] = declared
    return found


def _classes() -> dict[type, dict[str, MarkdownField]]:
    """The declarations grouped by model class and attribute name (built once)."""
    global _by_class
    if _by_class is None:
        with _lock:
            if _by_class is None:
                grouped: dict[type, dict[str, MarkdownField]] = {}
                for declared in get_markdown_fields():
                    grouped.setdefault(declared.column.class_, {})[declared.column.key] = declared
                _by_class = grouped
    return _by_class


def check_instance(instance: Any, declared: dict[str, MarkdownField], *, only_changed: bool) -> None:
    """
    Checks the declared Markdown attributes of one record.

    Args:
        instance: An ORM object of a class that has declared fields.
        declared: That class's declarations by attribute name.
        only_changed: Check only attributes with a pending change (a persisted record), not every attribute.

    Raises:
        HTTPException: 422 when a value breaks its field's limits.
    """
    state = inspect(instance)
    for name, field in declared.items():
        if only_changed and not state.attrs[name].history.has_changes():
            continue
        value = getattr(instance, name, None)
        if not value:
            continue
        try:
            validate_markdown(value, max_chars=field.limit, field=name.replace("_", " ").capitalize())
        except MarkdownLimitError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _before_flush(session: Session, _context: Any, _instances: Any) -> None:
    """Checks every new or changed record of a class with declared Markdown fields."""
    classes = _classes()
    for instance in session.new:
        declared = classes.get(type(instance))
        if declared:
            check_instance(instance, declared, only_changed=False)
    for instance in session.dirty:
        declared = classes.get(type(instance))
        if declared:
            check_instance(instance, declared, only_changed=True)


def install() -> None:
    """Registers the `before_flush` hook on every session (idempotent); called once at application start."""
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
