"""
Module: services.current_versions

Loads the current version of many versioned records in one statement.

Responsibilities:
- `current_versions`: `{record id: current version row}` for a list of record ids, so a list endpoint reads the
  versions of all the records it returns together instead of one `get_current_*_version` call per record.

Design decisions:
- Generic over the version table (any model with a record foreign key and `valid_to`), so every module's versioned
  type uses the one helper and none re-implements it.
- A record with no current version is a data-integrity fault, as in the per-record helpers: it raises rather than
  being left out of the answer.

Dependencies: SQLAlchemy; `modules.registry` (the export block's cache, for the priming pair).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def current_versions(db: Session, version_model: Any, fk: str, record_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """The current (`valid_to IS NULL`) version row of each record.

    Args:
        db: Active session (read only).
        version_model: The version table's ORM class (has `valid_to` and the foreign key `fk`).
        fk: Name of the attribute on `version_model` that holds the record id (e.g. `"risk_id"`).
        record_ids: The records.

    Returns:
        `{record id: version}`; empty for no ids, and one statement however many records.

    Raises:
        ValueError: If a record has no current version (a data-integrity fault).
    """
    if not record_ids:
        return {}
    column = getattr(version_model, fk)
    found = {getattr(v, fk): v for v in db.scalars(select(version_model).where(column.in_(list(record_ids)), version_model.valid_to.is_(None)))}
    missing = [i for i in record_ids if i not in found]
    if missing:
        raise ValueError(f"{len(missing)} record(s) have no current version, e.g. {missing[0]}.")
    return found


def prime_current_versions(db: Session, version_model: Any, fk: str, record_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """Reads the current version of many records in one statement, for `primed_current_version` to answer from.

    A bundle export asks for each record's current version through the per-record helpers; priming the records it will
    export first makes that one statement. It only has an effect inside a `memoize_module_state()` block (an
    export, which does not change versions between the read and its use); elsewhere it only returns them.

    Returns:
        `{record id: current version}`, which the caller can use to prime the versions' other lookups.
    """
    from app.modules.registry import module_state_memo

    found = current_versions(db, version_model, fk, record_ids)
    memo = module_state_memo()
    if memo is not None:
        for record_id, version in found.items():
            memo[("current_version", version_model.__name__, record_id)] = version
    return found


def primed_current_version(version_model: Any, record_id: uuid.UUID) -> Any | None:
    """The version `prime_current_versions` read for the record, or `None` when it was not primed (read it normally)."""
    from app.modules.registry import module_state_memo

    memo = module_state_memo()
    return None if memo is None else memo.get(("current_version", version_model.__name__, record_id))
