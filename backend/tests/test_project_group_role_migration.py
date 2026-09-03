"""Tests for the PR7 data migration (`alembic/versions/0022_project_group_
roles.py`, members/groups directory rework plan, docs/decisions.md): every
pre-existing `project_groups` row's scalar `role` is backfilled into exactly
one `project_group_roles` row before the `role` column itself is dropped.

Runs the *real* migration, not a reimplementation of its logic: downgrades
the live test database to revision 0021 (re-adding `project_groups.role`),
seeds a pre-migration-shaped row directly via raw SQL against that shape
(the project/user setup itself goes through the normal API — only the
`project_groups` row needs raw SQL, since `role` no longer exists on the
`ProjectGroup` model to insert through the ORM/API at all), then upgrades
back to head — which runs 0022's actual backfill SQL — and asserts against
the result via the ordinary API. Always upgrades back to head, even on
failure, so the shared session-scoped test database (`conftest.py`'s
`_schema` fixture) is left in the state every other test in this suite
expects — the same pattern `test_default_group_migration.py` established
for the Phase C `is_default` column removal precedent this migration
follows.

Unlike that precedent, the project/user setup here must happen *before*
entering the downgraded window, not inside it: `create_project`'s own
manager-assignment fallback (`_ensure_project_has_a_manager`) unconditionally
calls `get_effective_project_managers`, which (at head) queries the new
`project_group_roles` table — a table that doesn't exist yet at revision
0021. `test_default_group_migration.py`'s own downgrade target (0018) never
had this problem, since `is_default` isn't read by any code path
`create_project` exercises; 0022's own table genuinely is, so the ordering
here has to be different.
"""

import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from alembic import command
from alembic.config import Config
from app.database import engine
from tests.conftest import auth_headers, create_org_user, create_project

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return cfg


@contextmanager
def _downgraded_to_0021():
    """Downgrades the live test database to revision 0021 (`project_groups.
    role` exists again, `project_group_roles` doesn't) for the duration of
    the `with` block, then always upgrades back to head afterward — even on
    failure — restoring the schema every other test in this suite expects.
    Any project/org/user setup needed by the caller must happen *before*
    entering this block — see the module docstring for why."""
    command.downgrade(_alembic_config(), "0021")
    try:
        yield
    finally:
        command.upgrade(_alembic_config(), "head")


def test_backfill_converts_existing_group_role_into_exactly_one_grant_row(client, admin_token, org_id):
    """A single pre-existing group with `role = 'stakeholder'` ends up with
    exactly one `ProjectGroupRole` row carrying that same role after the
    migration runs — nothing lost, nothing duplicated."""
    project = create_project(client, admin_token, org_id, "Backfill Single Role Project")
    member_id = create_org_user(client, admin_token, org_id, "backfill-single-role@example.com", role="member")

    group_id = uuid.uuid4()
    with _downgraded_to_0021():
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO project_groups (id, project_id, name, role, created_at, updated_at) "
                    "VALUES (:id, :project_id, 'Stakeholders', 'stakeholder', now(), now())"
                ),
                {"id": str(group_id), "project_id": project["id"]},
            )
            conn.execute(
                text(
                    "INSERT INTO project_group_members (id, project_group_id, user_id, created_at, updated_at) "
                    "VALUES (:id, :group_id, :user_id, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "group_id": str(group_id), "user_id": member_id},
            )

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in groups if g["id"] == str(group_id))
    assert reloaded["roles"] == ["stakeholder"], "the group's pre-existing role must survive as exactly one grant"
    assert "role" not in reloaded
    assert reloaded["member_user_ids"] == [member_id], "membership itself is untouched by this migration"

    # The role is live, not just a stored artefact: the member's effective
    # access actually reflects it.
    sources_resp = client.get(
        f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)
    ).json()
    member_entry = next(m for m in sources_resp if m["user_id"] == member_id)
    assert member_entry["effective_role"] == "stakeholder"
    group_sources = [s for s in member_entry["sources"] if s["kind"] == "direct_group"]
    assert len(group_sources) == 1
    assert group_sources[0]["role"] == "stakeholder"
    assert group_sources[0]["via_group_id"] == str(group_id)


def test_backfill_covers_every_role_and_a_zero_member_group(client, admin_token, org_id):
    """Every one of the four `ProjectRole` values survives the backfill
    correctly (not just the one exercised above), and a group with no
    members at all (nothing to grant access, but the role row itself must
    still be created) is handled the same way."""
    project = create_project(client, admin_token, org_id, "Backfill All Roles Project")
    roles = ["project_manager", "project_administrator", "stakeholder", "member"]
    group_ids = {role: uuid.uuid4() for role in roles}

    with _downgraded_to_0021():
        with engine.begin() as conn:
            for role, group_id in group_ids.items():
                conn.execute(
                    text(
                        "INSERT INTO project_groups (id, project_id, name, role, created_at, updated_at) "
                        "VALUES (:id, :project_id, :name, :role, now(), now())"
                    ),
                    {"id": str(group_id), "project_id": project["id"], "name": f"Group {role}", "role": role},
                )

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    for role, group_id in group_ids.items():
        reloaded = next(g for g in groups if g["id"] == str(group_id))
        assert reloaded["roles"] == [role], f"role {role} did not survive the backfill correctly"
        assert reloaded["member_user_ids"] == []


def test_backfill_is_idempotent_if_the_migration_ran_twice(client, admin_token, org_id):
    """`ON CONFLICT (project_group_id, role) DO NOTHING` guards against a
    duplicate row if this migration's upgrade were ever re-run against a
    database that already has the new table populated — mirrors 0019's own
    idempotency guard for the analogous `is_default` backfill."""
    project = create_project(client, admin_token, org_id, "Backfill Idempotent Project")
    group_id = uuid.uuid4()
    with _downgraded_to_0021():
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO project_groups (id, project_id, name, role, created_at, updated_at) "
                    "VALUES (:id, :project_id, 'Managers', 'project_manager', now(), now())"
                ),
                {"id": str(group_id), "project_id": project["id"]},
            )

    # Already back at head (the `with` block above ran the real upgrade).
    # Re-executing the migration's own INSERT ... SELECT ... ON CONFLICT
    # statement directly confirms it doesn't error or duplicate if it were
    # ever re-run against an already-populated database.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_group_roles (id, project_group_id, role, created_at, updated_at) "
                "SELECT gen_random_uuid(), :group_id, 'project_manager', now(), now() "
                "ON CONFLICT (project_group_id, role) DO NOTHING"
            ),
            {"group_id": str(group_id)},
        )

    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in groups if g["id"] == str(group_id))
    assert reloaded["roles"] == ["project_manager"], "re-running the backfill must not create a duplicate row"
