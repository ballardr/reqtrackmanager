"""
Module: scripts.demo_table_counts

Prints the number of rows in every database table as one JSON object (`{"table": rows}`).

Responsibilities:
- Give the usage-metrics bundle (`scripts/demo_metrics.py`) the size of the demonstration data per table, so a
  reviewer can relate request counts to how much data there was.

Design decisions:
- Counts only: no row, column value or identifier is read, so the output cannot carry record content.
- Run inside the backend container: `docker compose exec -T backend python scripts/demo_table_counts.py`.

External dependencies: the application's database engine and models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app import models  # noqa: E402,F401  (registers every table on the metadata)
from app.database import Base, SessionLocal  # noqa: E402


def table_counts() -> dict[str, int]:
    """Returns the row count of every table known to the metadata, by table name."""
    with SessionLocal() as db:
        return {table.name: int(db.scalar(select(func.count()).select_from(table)) or 0) for table in Base.metadata.sorted_tables}


def main() -> int:
    """Prints the counts as JSON; returns the exit status."""
    print(json.dumps(table_counts(), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
