"""
Module: services.list_sort

The one sort every record list offers: a Sort by key and an Order, with four keys for every registered
artefact type (`code`, `title`, `created`, `modified`) plus the type's own columns, ascending or descending,
defaulting to Code ascending.

Responsibilities:
- Read the `sort` and `order` query parameters leniently (`ListSort`): a key the list cannot honour is ignored
  and the default applies, never an error, so a bookmarked address still opens.
- Order text and codes as a person reads them (`natural_key`: case-insensitive, digit runs by value, so
  `REQ-2` precedes `REQ-10`).
- Order records by a key with a stable tie-break on the record id (`order_records`), so a paged or repeated
  read never repeats or skips a row, and give the database the same order (`code_order_columns`,
  `text_order_column`).

Design decisions:
- A record with no value for the key (no due date) sorts last ascending and first descending, as the browser's
  list sort does, so the screen and a downloaded file agree.
- The canonical keys have aliases (`unique_code`, `created_at`, `updated_at`), the names the two paged lists
  (requirements, change requests) use; both spellings give one order.
- "Modified" is the record row's own `updated_at`, which moves with every change including a new version.

Dependencies: SQLAlchemy (order expressions), FastAPI (query parameters).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import Query
from sqlalchemy import BigInteger, String, cast, func
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

SortOrder = Literal["asc", "desc"]

#: The keys every record list offers, in the order the **Sort by** control lists them.
CODE_KEY = "code"
TITLE_KEY = "title"
CREATED_KEY = "created"
MODIFIED_KEY = "modified"
COMMON_KEYS = (CODE_KEY, TITLE_KEY, CREATED_KEY, MODIFIED_KEY)

#: Other spellings of a canonical key (the two paged lists' own names), mapped to it.
KEY_ALIASES = {"unique_code": CODE_KEY, "created_at": CREATED_KEY, "updated_at": MODIFIED_KEY}

_DIGITS = re.compile(r"(\d+)")
_MAX_KEY_LENGTH = 40


def canonical_key(key: str | None) -> str | None:
    """`key` with an alias replaced by its canonical name; `None` stays `None`."""
    return KEY_ALIASES.get(key, key) if key else None


@dataclass(frozen=True)
class ListSort:
    """The sort a list request asks for, as a FastAPI dependency (`sort_by: ListSort = Depends()`).

    Attributes:
        key: The requested key (unvalidated: a list uses it only when it knows it), or `None`.
        descending: Whether `order=desc` was given; any other value reads as ascending.
    """

    key: str | None = None
    descending: bool = False

    @classmethod
    def read(cls, sort: str | None, order: str | None) -> ListSort:
        """The sort for raw `sort`/`order` text (a value that is empty, too long or unknown is ignored later).

        Args:
            sort: The key text, or `None`.
            order: `"asc"` or `"desc"`; anything else is ascending.
        """
        key = sort.strip() if sort and len(sort) <= _MAX_KEY_LENGTH else None
        return cls(key=canonical_key(key or None), descending=order == "desc")


def list_sort(
    sort: str | None = Query(
        None, max_length=_MAX_KEY_LENGTH,
        description="Sort key: code, title, created, modified or a column of the list; an unknown key is ignored.",
    ),
    order: str = Query("asc", description="`asc` (default) or `desc`; anything else reads as `asc`."),
) -> ListSort:
    """The FastAPI dependency behind `ListSort`: `sort_by: ListSort = Depends(list_sort)`.

    Args:
        sort: The `sort` query parameter.
        order: The `order` query parameter.
    """
    return ListSort.read(sort, order)


def natural_key(text: str) -> tuple[tuple[int, int, str], ...]:
    """A key that orders text the way a person reads it: case-insensitively, digit runs by value.

    `REQ-2` precedes `REQ-10`, and `Item 9` precedes `item 10`. Each part is `(kind, number, text)` so numbers and
    words never compare to each other directly (a number part sorts before a word part).

    Args:
        text: Any text; an empty string sorts before every other text.
    """
    parts: list[tuple[int, int, str]] = []
    for piece in _DIGITS.split(text):
        if not piece:
            continue
        parts.append((0, int(piece), "") if piece.isdigit() else (1, 0, piece.casefold()))
    return tuple(parts)


def _comparable(value: Any) -> Any:
    """`value` as something Python can order next to values of its own kind: text by `natural_key`, others as they are."""
    if isinstance(value, str):
        return natural_key(value)
    return value


def order_records(
    records: Iterable[Any], value_of: Callable[[Any], Any], *, descending: bool = False, id_of: Callable[[Any], Hashable] | None = None,
    tie_of: Callable[[Any], Any] | None = None,
) -> list[Any]:
    """`records` ordered by `value_of`, a missing value last ascending (first descending), equal values in a fixed order.

    Equal values keep the order `tie_of` gives (ascending in both directions, so a list sorted by status descending still
    reads its statuses' records by code), then the record id, so a list that is read twice or in pages never repeats or
    skips a row.

    Args:
        records: The records, in any order.
        value_of: `(record) -> text, number or None`.
        descending: Reverse the order of the values (not of the ties).
        id_of: Reads a record's id for the last tie-break; defaults to `record.id` (a record with none keeps its place).
        tie_of: `(record) -> comparable` for the order of equal values; default none (the id alone).

    Returns:
        A new list.
    """
    read_id = id_of if id_of is not None else (lambda record: str(getattr(record, "id", "")))
    base = sorted(records, key=lambda record: ((tie_of(record) if tie_of is not None else 0), str(read_id(record))))
    present: list[tuple[Any, Any]] = []
    missing: list[Any] = []
    for record in base:
        value = value_of(record)
        if value is None or value == "":
            missing.append(record)
        else:
            present.append((_comparable(value), record))
    present.sort(key=lambda item: item[0], reverse=descending)  # a stable sort: equal values keep the tie order
    ordered_present = [item[1] for item in present]
    return [*missing, *ordered_present] if descending else [*ordered_present, *missing]


def instant(value: datetime | None) -> float | None:
    """`value` as seconds since the epoch, so instants of different timezone awareness compare; `None` stays `None`."""
    return value.timestamp() if value is not None else None


def code_order_columns(column: ColumnElement[str] | InstrumentedAttribute[str]) -> list[ColumnElement[Any]]:
    """The database order of a code column that reads as `REQ-2` before `REQ-10`: the text before the final digits, then
    their value. Ordered case-insensitively on the byte order (`COLLATE "C"`), never the database's locale.

    Args:
        column: A code column (`Requirement.unique_code`).

    Returns:
        Two expressions to pass to `ORDER BY` (descending is applied by the caller to both).
    """
    prefix = func.lower(func.regexp_replace(column, r"\d+$", "")).collate("C")
    number = cast(func.nullif(func.substring(column, r"\d+$"), ""), BigInteger)
    return [prefix, number]


def text_order_column(column: ColumnElement[str] | InstrumentedAttribute[str]) -> ColumnElement[str]:
    """The database order of a text column: lower-cased, on the byte order (`COLLATE "C"`), never the locale."""
    return func.lower(cast(column, String)).collate("C")


def apply_direction(columns: Sequence[ColumnElement[Any]], descending: bool) -> list[ColumnElement[Any]]:
    """`columns` ascending or descending, a missing value last ascending and first descending (the browser's order)."""
    if descending:
        return [c.desc().nulls_first() for c in columns]
    return [c.asc().nulls_last() for c in columns]
