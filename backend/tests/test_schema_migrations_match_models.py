"""Guards against the exact production incident recorded in
docs/decisions.md where `Organization`/`ServerSettings` gained
`email_footer_*` model columns but no Alembic migration was written for
them: `create_all()` (used implicitly by any workflow that builds its
schema straight from the models) papered over the gap in dev, while a real
deployment running `alembic upgrade head` (`app/migrations.py`) hit
`UndefinedColumn` in production.

The `_schema` session fixture in conftest.py already builds the test
database by running the real Alembic migrations rather than
`Base.metadata.create_all()` (see its own docstring for why), so by the
time this test runs, comparing the live migrated schema against
`Base.metadata` is exactly Alembic's own autogenerate diff — the same
check `alembic revision --autogenerate` uses to decide whether a new
migration is needed. A nonempty diff here means a model field was
added/changed/removed without a matching migration in either
backend/alembic/versions/ (core) or a first-party module's own
`migrations_dir` (e.g. backend/app/modules/compliance/migrations/,
compliance-module-plan.md Phase 11 follow-up) — `app.modules.registry.
configure_alembic_version_locations` merges both into the one chain this
test's own `_schema` fixture (conftest.py) migrates against, so a drift in
either location is caught identically here.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.database import Base, engine


def test_models_and_migrations_have_not_drifted():
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diff = compare_metadata(context, Base.metadata)

    assert not diff, (
        "Model classes and Alembic migrations have drifted apart:\n"
        f"{diff}\n\n"
        "This means a model field (or table/index) was added, changed, or "
        "removed without a matching Alembic migration under "
        "backend/alembic/versions/ (or the owning first-party module's own "
        "migrations_dir) — see change-management-and-secure-"
        "development-policy.md. Add a migration for the diff above (an "
        "`IF NOT EXISTS`/`IF EXISTS` one, per the pattern in 0002 onward, "
        "since a fresh database's `create_all()` may already have the "
        "column while an already-migrated one won't)."
    )
