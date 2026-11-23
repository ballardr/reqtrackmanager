"""
Module: tests._pytest_database

A dependency-free helper for `tests/conftest.py`, which must rewrite `DATABASE_URL` to pytest's dedicated database before
importing anything from `app.*` (`app.database` creates its engine at import time).

Design decisions:
- The function lives here because a `def` before the imports in `conftest.py` would trip ruff's `E402` on every import below it.
- It holds exactly one pure function (`dedicated_pytest_database_url`) and its constant, with no dependency on `app.*`,
  `pytest` or any project module, so it can be imported first.
"""

import os

#: The database pytest always runs against, whatever DATABASE_URL is inherited; never `reqtrack_test`
#: (see `dedicated_pytest_database_url()`). Under pytest-xdist each worker uses `{PYTEST_DB_NAME}_{worker_id}`
#: (see `_worker_db_suffix()`).
PYTEST_DB_NAME = "reqtrack_pytest_test"


def _worker_db_suffix() -> str:
    """Returns `_gw0`, `_gw1`, etc. when running under a pytest-xdist
    worker, or "" outside xdist (including xdist's "master" pseudo-id, used
    when xdist is installed but `-n` wasn't passed).

    `conftest.py`'s `_schema` fixture drops and recreates the whole schema
    once per session, and `_clean_tables` truncates every table after every
    test — safe for one process talking to one database, but not for
    multiple xdist worker *processes* sharing one: one worker's truncate
    would wipe out another's mid-test row, and two workers' session-start
    `DROP SCHEMA ... CASCADE` would race each other. Routing each worker to
    its own database (this suffix) removes that entirely, the same way
    `dedicated_pytest_database_url` already keeps pytest off the dev/demo
    stack's own `reqtrack_test` database.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
    return f"_{worker_id}" if worker_id and worker_id != "master" else ""


def dedicated_pytest_database_url(inherited_url: str) -> str:
    """Rewrites `inherited_url`'s database name (the part after the final `/`) to pytest's dedicated database:
    `PYTEST_DB_NAME`, plus a per-worker suffix under `pytest-xdist` (`_worker_db_suffix()`). Everything else (scheme, host,
    port, user, password) is preserved.

    The dev/demo Compose stack's `backend` service points DATABASE_URL at `reqtrack_test`, which its app process and
    Playwright's target also serve from, and `os.environ.setdefault(...)` in `conftest.py` is a no-op when DATABASE_URL is
    set. Without this rewrite the session `_schema` fixture (`DROP SCHEMA public CASCADE`) and the per-test truncation would
    destroy that data, so pytest gets its own `reqtrack_pytest_test` database (created by `conftest.py`
    `_ensure_test_database()`; the name still starts with `PYTEST_DB_NAME`, satisfying `conftest.py`'s guard). See
    docs/decisions.md.

    Args:
        inherited_url: A SQLAlchemy/psycopg2-style Postgres URL, e.g. `postgresql://user:pass@host:5432/dbname`.

    Returns:
        The same URL with its trailing database name replaced by `PYTEST_DB_NAME` (plus a worker suffix under xdist).
    """
    base_url, _, _ = inherited_url.rpartition("/")
    return f"{base_url}/{PYTEST_DB_NAME}{_worker_db_suffix()}"
