"""
Module: services.perf_dataset.context

The state a per-type dataset generator receives, and the bulk-write helpers it uses.

Responsibilities:
- `PerfProjectContext`: one project's identifiers, the people and link types available in it, a seeded random
  generator, and a place to share ids with generators that run later (actions link to requirements).
- `insert_rows`: chunked multi-row INSERT through SQLAlchemy Core, which is what lets 20,000 requirements and
  their history load in seconds instead of the hours an HTTP create per record would take.
- `uuid_from`: deterministic UUIDs, so a dataset with the same spec has the same ids on every host.

Design decisions:
- Generators write rows with Core inserts but must populate what the application's own create path populates; the
  parity test (`tests/test_perf_dataset.py`) compares the populated columns of a generated row with an
  API-created one, so a column added to a model cannot silently stay empty here.
- The clock is a fixed anchor (`ANCHOR`), never `now()`, so generated timestamps do not depend on when it runs.

Dependencies: SQLAlchemy; `perf_dataset.skeleton` and `perf_dataset.spec` for the plan and spec types.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.services.perf_dataset.skeleton import OrgPlan, ProjectPlan
from app.services.perf_dataset.spec import DatasetSpec

#: The instant all generated history is measured back from (fixed, so output does not depend on the run date).
ANCHOR = datetime(2026, 10, 1, tzinfo=UTC)
#: Rows per INSERT statement batch; SQLAlchemy splits further to respect the driver's parameter limit.
CHUNK = 5000


def uuid_from(rng: random.Random) -> uuid.UUID:
    """A version-4 UUID drawn from `rng`, so the same seed gives the same ids."""
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def insert_rows(db: Session, model: Any, rows: Iterable[dict], *, chunk: int = CHUNK) -> int:
    """Inserts rows into a model's table in chunks without loading them into the session.

    Args:
        db: The session; nothing is committed here.
        model: The ORM class whose table receives the rows.
        rows: Dicts of column values. Every dict in one call must have the same keys; columns left out take the
            model's column defaults.
        chunk: Rows per statement.

    Returns:
        The number of rows written.
    """
    total = 0
    batch: list[dict] = []
    table = model.__table__
    for row in rows:
        batch.append(row)
        if len(batch) >= chunk:
            db.execute(insert(table), batch)
            total += len(batch)
            batch = []
    if batch:
        db.execute(insert(table), batch)
        total += len(batch)
    return total


@dataclass
class PerfProjectContext:
    """Everything a generator needs for one project.

    Attributes:
        db: The session generators write through; the caller commits after each project.
        spec: The dataset spec (ratios, tier, seed).
        org: The project's organisation plan.
        project: The project plan being filled.
        rng: A generator seeded from the spec and the project's position, independent of other projects.
        user_ids: Ids of the people who may author records in this project.
        link_type_ids: `(id, nesting_scope)` of link types usable between two requirements.
        action_type_ids: Ids of the action types the project offers (its own or an ancestor's).
        shared: Ids written by earlier generators for this project, keyed by artefact type (a later generator
            such as actions links to the requirement ids).
        parent_shared: The parent project's `shared`, or None for a root (for cross-level links).
        counts: Rows written, by table name; filled by the generators.
        histogram: Realised link-degree histogram for the manifest.
        say: Progress sink.
    """

    db: Session
    spec: DatasetSpec
    org: OrgPlan
    project: ProjectPlan
    rng: random.Random
    user_ids: list[uuid.UUID]
    link_type_ids: list[tuple[uuid.UUID, str]]
    action_type_ids: list[uuid.UUID]
    shared: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    parent_shared: dict[str, list[uuid.UUID]] | None = None
    counts: dict[str, int] = field(default_factory=dict)
    histogram: dict[str, int] = field(default_factory=dict)
    say: Any = print

    @property
    def project_uuid(self) -> uuid.UUID:
        """The project id as a UUID."""
        return uuid.UUID(self.project.id)

    @property
    def organization_uuid(self) -> uuid.UUID:
        """The organisation id as a UUID."""
        return uuid.UUID(self.org.id)

    def add_count(self, table: str, written: int) -> None:
        """Adds `written` to the running count for `table`."""
        self.counts[table] = self.counts.get(table, 0) + written
