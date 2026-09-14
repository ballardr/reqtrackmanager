"""
Module: tests._pytest_database

A tiny, dependency-free helper extracted out of `tests/conftest.py` for one
purely mechanical reason: `conftest.py` must rewrite `DATABASE_URL` to
pytest's own dedicated database *before* it imports anything from `app.*`
(importing `app.database` creates a SQLAlchemy engine from `DATABASE_URL` at
module import time), which means that rewrite has to happen among
`conftest.py`'s own very first lines, ahead of its other imports. A
module-level `def` statement there would itself count as "code before an
import" and trip ruff's `E402` (module-level import not at top of file) on
every import below it — pycodestyle/ruff's `E402` tolerates bare statements
like `os.environ.setdefault(...)` before later imports, but not a function
definition. Defining the function here instead, and importing it as
`conftest.py`'s own first import, sidesteps that: from `conftest.py`'s
perspective this is just another import, not code.

Responsibilities: exactly one pure function (`dedicated_pytest_database_url`)
and the constant it uses, nothing else — deliberately no dependency on
`app.*`, `pytest`, or any other project module, so this can be imported
before all of them.
"""

import os

#: The database pytest always runs against, regardless of what DATABASE_URL
#: it inherits from the environment. Never `reqtrack_test` — see
#: `dedicated_pytest_database_url()`'s docstring for the full rationale.
#: Under pytest-xdist, each worker gets its own database named
#: `{PYTEST_DB_NAME}_{worker_id}` — see `_worker_db_suffix()`.
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
    """Rewrites `inherited_url`'s database name (the part after the final
    `/`) to pytest's own dedicated database — `PYTEST_DB_NAME`, plus a
    per-xdist-worker suffix when running under `pytest-xdist` (see
    `_worker_db_suffix()`) — preserving everything else (scheme, host,
    port, user, password) unchanged. A no-op if the name already matches.

    This is what makes it safe to run `docker compose exec backend
    pytest -q` in `tests/container/docker-compose.yml` at any time, even
    while manually using the same stack for demo/dev testing or running
    Playwright against it: that container's `backend` service's own
    DATABASE_URL points at `reqtrack_test` — the SAME database its own
    long-running app process (and Playwright's target backend) serve
    requests from. Without this rewrite, `os.environ.setdefault(...)` in
    `conftest.py` is a no-op whenever DATABASE_URL is already set (as it
    always is in that container), so the test suite's session-scoped
    `_schema` fixture (`DROP SCHEMA public CASCADE` / recreate, every
    session start) and its per-test table truncation would run directly
    against `reqtrack_test` — destroying whatever manually-seeded demo/dev
    data existed there. This happened for real once (see `conftest.py`'s
    own module docstring for the incident) and, even after the mitigations
    described there (the `_test`-suffix guard, and no longer dropping the
    schema at teardown), a plain passing `pytest -q` run still destroyed
    live demo data every time, because neither mitigation addressed the
    actual root cause: pytest and the dev/demo stack sharing one database.
    Forcing pytest onto its own dedicated `reqtrack_pytest_test` database
    (auto-created by `conftest.py`'s own `_ensure_test_database()` if it
    doesn't exist, still starts with `PYTEST_DB_NAME` so `conftest.py`'s own
    guard is satisfied unmodified) removes the sharing entirely. See
    docs/decisions.md for the full account.

    Args:
        inherited_url: A SQLAlchemy/psycopg2-style Postgres URL, e.g.
            `postgresql://user:pass@host:5432/dbname`.

    Returns:
        The same URL with its trailing database name replaced by
        `PYTEST_DB_NAME` (plus a worker suffix under xdist).
    """
    base_url, _, _ = inherited_url.rpartition("/")
    return f"{base_url}/{PYTEST_DB_NAME}{_worker_db_suffix()}"
