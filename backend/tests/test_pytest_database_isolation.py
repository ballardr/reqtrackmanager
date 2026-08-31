"""Pins the fix for "pytest was destroying dev/demo data every time it ran"
(docs/decisions.md) — `tests/conftest.py` must always route this test suite
at its own dedicated `reqtrack_pytest_test` database, never at
`reqtrack_test` (the database `tests/container/docker-compose.yml`'s
`backend` service — the dev/demo stack and Playwright's target backend —
uses), regardless of what DATABASE_URL the process inherited from the
environment.
"""

from app.config import get_settings
from tests._pytest_database import PYTEST_DB_NAME, dedicated_pytest_database_url


def test_resolved_database_name_is_never_reqtrack_test():
    """The live, already-resolved settings this whole test session actually
    ran against (i.e. what `_ensure_test_database()`/`_schema` used) must
    never be `reqtrack_test` — the acceptance criterion for the isolation
    fix. Also confirms it's the dedicated pytest database, not just *some*
    other `_test`-suffixed name."""
    dbname = get_settings().database_url.rpartition("/")[2]
    assert dbname != "reqtrack_test"
    assert dbname == PYTEST_DB_NAME


def test_dedicated_pytest_database_url_rewrites_reqtrack_test():
    """The exact failure mode this fix closes: a DATABASE_URL inherited
    from tests/container/docker-compose.yml's `backend` service (pointed at
    `reqtrack_test`, shared with the live dev/demo app) must be rewritten to
    the dedicated pytest database, not passed through unchanged."""
    rewritten = dedicated_pytest_database_url("postgresql://reqtrack:reqtrack@db:5432/reqtrack_test")
    assert rewritten == "postgresql://reqtrack:reqtrack@db:5432/reqtrack_pytest_test"


def test_dedicated_pytest_database_url_preserves_connection_details():
    """Only the database name changes — scheme, credentials, host, and port
    are reused verbatim so the rewrite works unmodified against any
    environment's connection details."""
    rewritten = dedicated_pytest_database_url("postgresql://someuser:s3cr3t@dbhost.internal:6543/whatever")
    assert rewritten == "postgresql://someuser:s3cr3t@dbhost.internal:6543/reqtrack_pytest_test"


def test_dedicated_pytest_database_url_is_idempotent():
    """Already-correct input is left unchanged (a no-op rewrite), not
    mangled or double-suffixed."""
    already_correct = "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_pytest_test"
    assert dedicated_pytest_database_url(already_correct) == already_correct
