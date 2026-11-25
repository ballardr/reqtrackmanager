"""Guards against a model column with no Alembic migration (see docs/decisions.md):
`create_all()` hides the gap in dev, while a deployment running `alembic upgrade head`
(`app/migrations.py`) hits `UndefinedColumn`.

The `_schema` session fixture in conftest.py builds the test database with the real
Alembic migrations, so comparing the live migrated schema against `Base.metadata` is
Alembic's autogenerate diff. A nonempty diff means a model field was added, changed or
removed without a migration in backend/alembic/versions/ (core) or a first-party module's
`migrations_dir` (e.g. backend/app/modules/compliance/migrations/);
`app.modules.registry.configure_alembic_version_locations` merges both into the one chain
the fixture migrates, so drift in either location is caught.
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
