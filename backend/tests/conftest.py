"""
Module: tests.conftest

Test fixtures for the backend test suite. Runs against a real PostgreSQL
database (a dedicated `reqtrack_test` database on the same server used by
docker-compose) rather than SQLite, since the schema uses PostgreSQL-specific
types (UUID, JSONB). The schema is created once per test session by running
the real Alembic migrations (not `Base.metadata.create_all()` directly) so
the test suite exercises the same migration path production deployments use
— and so it doesn't fight with the app's own startup-time
`alembic upgrade head` (see app/migrations.py), which would otherwise try to
re-apply non-idempotent `op.add_column` migrations against a schema a raw
`create_all()` had already brought to the same end state. Every table is
truncated between tests so each test starts from a clean slate, including a
freshly bootstrapped server admin user.
"""

import os

# NOTE: `setdefault` here is a convenience for local/CI runners that haven't
# set DATABASE_URL at all — it is NOT sufficient on its own to guarantee
# tests run against a test database. If DATABASE_URL is already set in the
# environment (as it always is inside the `backend` service container, to
# the real application database), `setdefault` is a no-op and this whole
# suite would otherwise run its session-scoped schema DROP/CREATE fixture
# below against that real database. This previously happened for real: running
# `docker compose exec backend pytest` wiped the live dev/demo database on
# every test run, including at session teardown, which left the running app
# with no tables at all until its next restart. See docs/decisions.md.
os.environ.setdefault("DATABASE_URL", "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test")
os.environ.setdefault("SERVER_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("SERVER_ADMIN_PASSWORD", "ChangeMe123!")
os.environ.setdefault("SERVER_ADMIN_CREATE_ORG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import app.models  # noqa: F401  (populates Base.metadata)
from app.config import get_settings
from app.database import Base, SessionLocal
from app.database import engine as app_engine
from app.migrations import run_migrations
from app.services.bootstrap import run_bootstrap

_settings_for_guard = get_settings()
_test_db_name = _settings_for_guard.database_url.rpartition("/")[2]
if not _test_db_name.endswith("_test"):
    raise RuntimeError(
        "Refusing to run the test suite: DATABASE_URL resolves to "
        f"database {_test_db_name!r}, which doesn't look like a test database "
        "(expected a name ending in '_test'). This suite drops and recreates "
        "the entire public schema, including at session teardown — running it "
        "against the wrong database destroys real data. Set DATABASE_URL to a "
        "*_test database explicitly, e.g. "
        "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test."
    )


def _ensure_test_database() -> None:
    settings = get_settings()
    base_url, _, dbname = settings.database_url.rpartition("/")
    admin_engine = create_engine(f"{base_url}/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin_engine.dispose()


_ensure_test_database()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    # Drop and recreate the whole schema (rather than Base.metadata.drop_all)
    # so a stale schema left by a previous conftest revision, a previous
    # model version, or a partially-applied migration can never make this
    # fixture inconsistent with a truly fresh `alembic upgrade head` run.
    with app_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    run_migrations()
    yield
    # No teardown drop here on purpose: the *next* session's setup above
    # already guarantees a clean slate regardless of what's left behind, so
    # a teardown drop only ever served to tidy up between runs — at the cost
    # of leaving a completely tableless database for anything else pointed
    # at it. In tests/container/docker-compose.yml, the backend app
    # container shares this exact database with the test suite, so a
    # teardown drop meant every `docker compose exec backend pytest` left
    # the live app unable to serve any request (`relation "..." does not
    # exist`) until it was restarted. Leaving the migrated-but-truncated
    # schema in place after the session lets that app keep running (with an
    # empty admin/session state until its next restart, rather than none at
    # all).


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with app_engine.begin() as conn:
        # A single TRUNCATE ... CASCADE (rather than per-table DELETE in
        # dependency order) sidesteps the FK cycles some tables have via
        # use_alter columns (e.g. users.avatar_file_id -> file_assets,
        # file_assets.uploaded_by -> users), which `sorted_tables` ordering
        # cannot fully resolve for deletion purposes.
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))


@pytest.fixture(scope="session")
def _app_client():
    # Session-scoped so `alembic upgrade head`, the server-admin bootstrap,
    # and the scheduler/background-task startup in app.main.lifespan each
    # run once for the whole suite rather than once per test. Previously
    # `client` itself was function-scoped, so every test re-entered
    # `TestClient(app)`'s context manager and re-ran the full app lifespan
    # (a no-op `alembic upgrade head` alone costs ~0.5s), which dominated
    # the suite's runtime across ~370 tests. Nothing in this suite depends
    # on a fresh lifespan per test: the scheduler/disk-monitor tests call
    # their check functions directly rather than relying on the
    # lifespan-managed background loop's timing, and no test mutates
    # persistent TestClient state (headers/cookies) that would leak across
    # tests. Per-test isolation still comes from `_clean_tables` below.
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_app_client):
    # `_clean_tables` truncates every table (including `users`) after each
    # test, so the server admin the session-scoped lifespan bootstrapped
    # once at startup won't exist for the next test. Re-run just the
    # bootstrap (a cheap idempotency check, only paying bcrypt's cost when
    # it actually needs to recreate the admin) rather than the whole
    # lifespan, since only tests that request `client` need an admin to be
    # present.
    db = SessionLocal()
    try:
        run_bootstrap(db)
    finally:
        db.close()
    return _app_client


def login(client: TestClient, email: str, password: str) -> str:
    """Helper: logs in and returns a bearer token."""
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client) -> str:
    return login(client, "admin@example.com", "ChangeMe123!")


@pytest.fixture
def org_id(client, admin_token) -> str:
    resp = client.get("/api/v1/orgs", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    return resp.json()[0]["id"]


def create_org_user(client, admin_token, org_id, email, password="Password123!", role="member") -> str:
    """Creates a user in the org with the given org role. Returns the user id."""
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users",
        json={"email": email, "display_name": email.split("@")[0], "password": password, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user_id"]


def create_project(
    client, admin_token, org_id, name="Demo Project", *,
    parent_project_id=None, role_inheritance_mode=None, role_inheritance_filter_role=None,
) -> dict:
    payload = {"organization_id": org_id, "name": name, "summary": ""}
    if parent_project_id is not None:
        payload["parent_project_id"] = parent_project_id
    if role_inheritance_mode is not None:
        payload["role_inheritance_mode"] = role_inheritance_mode
    if role_inheritance_filter_role is not None:
        payload["role_inheritance_filter_role"] = role_inheritance_filter_role
    resp = client.post("/api/v1/projects", json=payload, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_org_admin_in(client, admin_token, org_name) -> tuple[dict, str]:
    """Creates a new organisation, then a genuine org_admin user within it.

    Since I-M-05 removed the server-admin bypass from `require_org_role`,
    the bootstrap server admin can no longer act directly on an org it
    creates (only the documented carve-out of creating that org's *initial*
    user still works, matching real deployments). Tests that need to act
    within a second organisation should log in as this returned user
    instead of continuing to use `admin_token`.

    Returns:
        A tuple of (organization dict, bearer token for the new org_admin).
    """
    org = client.post("/api/v1/orgs", json={"name": org_name}, headers=auth_headers(admin_token)).json()
    email = f"{org_name.lower().replace(' ', '_')}_admin@example.com"
    client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": email, "display_name": "Org Admin", "password": "Password123!", "role": "org_admin"},
        headers=auth_headers(admin_token),
    )
    return org, login(client, email, "Password123!")


def create_component_and_category(client, admin_token, project_id) -> tuple[str, str]:
    component = client.post(
        f"/api/v1/projects/{project_id}/components", json={"name": "Software", "prefix": "SW"},
        headers=auth_headers(admin_token),
    ).json()
    category = client.post(
        f"/api/v1/projects/{project_id}/categories",
        json={"name": "Performance", "prefix": "PERF", "component_id": component["id"]},
        headers=auth_headers(admin_token),
    ).json()
    return component["id"], category["id"]
