"""
Module: services.markdown_fields

Enforces the limits of every declared Markdown field when a value is written, whichever path writes it.

Responsibilities: resolve the registry's `MarkdownField` declarations into `{model class: {attribute: field}}`
and the inventory rows (`declared_columns`, `column_key`); in a session `before_flush` hook, check each new or
changed declared attribute with `validate_markdown` (size, nesting, diagrams, control characters, pictures)
and refuse the write with a 422 naming the field. A picture is allowed only in a field declaring
`MarkdownImages`, for a file attached to the record holding the text (`services.markdown_images`); a bundle
import defers that check until its attachments exist.

Design decisions:
- One hook instead of a validator per request schema: endpoint, file import, bundle import, MCP tool and seed
  all end in the same flush, so no path stores what another refuses and a later-declared field is covered.
- Only a changed attribute is checked, so a record already above a limit is refused only when that field is
  edited again, and editing another field is not blocked.
- The refusal is an `HTTPException` (422); a caller that stages rows (an import) turns it into the row's error.
- `install()` installs the hook at application start, not as an import side effect; the declaration map is
  resolved lazily on the first flush, after every module's models are imported.

Dependencies: `modules.registry`, `services.markdown_text`, SQLAlchemy.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, object_session

from app.modules.registry import MarkdownField, get_markdown_fields
from app.services import markdown_images
from app.services.markdown_text import MarkdownLimitError, check_images, validate_markdown

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
        label = name.replace("_", " ").capitalize()
        try:
            validate_markdown(value, max_chars=field.limit, field=label)
            pictures = check_images(value, allowed=field.images is not None, field=label)
        except MarkdownLimitError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        if pictures:
            importing = markdown_images.active_import()
            session = object_session(instance)
            if importing is not None:
                importing.defer(instance, name, field)
            elif session is not None:
                before = state.attrs[name].history.deleted if only_changed else ()
                markdown_images.require_attached(
                    session, field, instance, value, name=label, unchanged=str(before[0]) if before and before[0] else "",
                )


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
