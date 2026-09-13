"""Pins the fix for "pytest was destroying dev/demo data every time it ran"
(docs/decisions.md) — `tests/conftest.py` must always route this test suite
at its own dedicated `reqtrack_pytest_test` database (or, under
`pytest-xdist`, a `reqtrack_pytest_test_gw*` database per worker — see
Phase 1 of docs/platform-review-2026-09-plan.md), never at `reqtrack_test`
(the database `tests/container/docker-compose.yml`'s `backend` service —
the dev/demo stack and Playwright's target backend — uses), regardless of
what DATABASE_URL the process inherited from the environment.

Every rewrite test below pins `PYTEST_XDIST_WORKER` explicitly via
`monkeypatch` rather than relying on the ambient environment, so these
assertions hold the same way whether this file itself happens to be running
under an xdist worker or not.
"""

from app.config import get_settings
from tests._pytest_database import PYTEST_DB_NAME, dedicated_pytest_database_url


def test_resolved_database_name_is_pytest_dedicated_not_reqtrack_test():
    """The live, already-resolved settings this whole test session actually
    ran against (i.e. what `_ensure_test_database()`/`_schema` used) must
    never be `reqtrack_test` — the acceptance criterion for the isolation
    fix. Also confirms it's the dedicated pytest database (optionally with
    a worker suffix under xdist), not just *some* other `_test`-suffixed
    name."""
    dbname = get_settings().database_url.rpartition("/")[2]
    assert dbname != "reqtrack_test"
    assert dbname.startswith(PYTEST_DB_NAME)


def test_dedicated_pytest_database_url_rewrites_reqtrack_test(monkeypatch):
    """The exact failure mode this fix closes: a DATABASE_URL inherited
    from tests/container/docker-compose.yml's `backend` service (pointed at
    `reqtrack_test`, shared with the live dev/demo app) must be rewritten to
    the dedicated pytest database, not passed through unchanged."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    rewritten = dedicated_pytest_database_url("postgresql://reqtrack:reqtrack@db:5432/reqtrack_test")
    assert rewritten == "postgresql://reqtrack:reqtrack@db:5432/reqtrack_pytest_test"


def test_dedicated_pytest_database_url_preserves_connection_details(monkeypatch):
    """Only the database name changes — scheme, credentials, host, and port
    are reused verbatim so the rewrite works unmodified against any
    environment's connection details."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    rewritten = dedicated_pytest_database_url("postgresql://someuser:s3cr3t@dbhost.internal:6543/whatever")
    assert rewritten == "postgresql://someuser:s3cr3t@dbhost.internal:6543/reqtrack_pytest_test"


def test_dedicated_pytest_database_url_is_idempotent(monkeypatch):
    """Already-correct input is left unchanged (a no-op rewrite), not
    mangled or double-suffixed."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    already_correct = "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_pytest_test"
    assert dedicated_pytest_database_url(already_correct) == already_correct


def test_dedicated_pytest_database_url_appends_xdist_worker_suffix(monkeypatch):
    """Under pytest-xdist, each worker must be routed to its own database
    (not the bare `reqtrack_pytest_test` every worker would otherwise
    share) — see `tests/_pytest_database.py`'s `_worker_db_suffix()` for
    why sharing one database across concurrent worker processes isn't
    safe."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    rewritten = dedicated_pytest_database_url("postgresql://reqtrack:reqtrack@db:5432/reqtrack_test")
    assert rewritten == "postgresql://reqtrack:reqtrack@db:5432/reqtrack_pytest_test_gw3"


def test_dedicated_pytest_database_url_treats_xdist_master_as_no_suffix(monkeypatch):
    """xdist sets `PYTEST_XDIST_WORKER=master` for the controller process in
    some configurations (e.g. `-n 0`) rather than leaving it unset — that
    must resolve to the same unsuffixed database as running outside xdist
    entirely, not a literal `_master` database nothing else would create."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    rewritten = dedicated_pytest_database_url("postgresql://reqtrack:reqtrack@db:5432/reqtrack_test")
    assert rewritten == "postgresql://reqtrack:reqtrack@db:5432/reqtrack_pytest_test"
