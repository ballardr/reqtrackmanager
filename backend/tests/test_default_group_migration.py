"""Tests for the Phase C default-project-group data migration
(`alembic/versions/0019_remove_default_project_groups.py`, follow-up UX
batch, 2026-08-31): for every pre-existing `is_default=True` `ProjectGroup`,
its direct user members are materialized into direct `UserProjectRole`
grants (idempotently, with the group's own role), and the group is then
either deleted (plain direct members only) or demoted to an ordinary group
(composition beyond plain direct members — a cross-project member-source
reference, in the case exercised here, or a nested org group).

Runs the *real* migration, not a reimplementation of its logic: downgrades
the live test database to revision 0018 (re-adding `project_groups.
is_default`), seeds pre-migration-shaped rows directly via raw SQL against
that shape (the project/user setup itself goes through the normal API —
only the `is_default` group rows need raw SQL, since that column no longer
exists on the `ProjectGroup` model to insert through the ORM/API at all),
then upgrades back to head — which runs 0019's actual conversion SQL — and
asserts against the result via the ordinary API. Always upgrades back to
head before returning, even on failure, so the shared session-scoped test
database (`conftest.py`'s `_schema` fixture) is left in the state every
other test in this suite expects (matching `Base.metadata`, per
`test_schema_migrations_match_models.py`).

The project/user setup must happen *before* entering the downgraded window,
not inside it — a regression found while implementing PR7 of the members/
groups directory rework plan (docs/decisions.md): `create_project`'s own
manager-assignment fallback (`_ensure_project_has_a_manager`) unconditionally
calls `get_effective_project_managers`, which (at head, from PR7 onward)
queries the new `project_group_roles` table — a table that doesn't exist
yet at revision 0018 (or anywhere below 0022). These two tests used to call
`create_project` *inside* the downgraded window without issue, since 0018's
own schema still had everything `create_project` needed at the time this
file was written; PR7's own new table broke that assumption. See
`test_project_group_role_migration.py`'s module docstring for the identical
issue found there first, and the same `contextmanager`-based fix applied
here.
"""

import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from alembic import command
from alembic.config import Config
from app.database import engine
from tests.conftest import auth_headers, create_org_user, create_project, direct_project_roles

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return cfg


@contextmanager
def _downgraded_to_0018():
    """Downgrades the live test database to revision 0018 (`project_groups.
    is_default` exists again) for the duration of the `with` block, then
    always upgrades back to head afterward — even on failure — restoring
    the schema every other test in this suite expects. Any project/org/user
    setup needed by the caller must happen *before* entering this block —
    see the module docstring for why."""
    command.downgrade(_alembic_config(), "0018")
    try:
        yield
    finally:
        command.upgrade(_alembic_config(), "head")


def test_plain_default_group_materializes_members_then_is_deleted(client, admin_token, org_id):
    """A default group with only plain direct user members: every member
    gets a direct UserProjectRole grant with the group's own role, then the
    now-fully-materialized group itself is deleted (its ProjectGroupMember
    rows cascade away with it, per the existing FK `ondelete="CASCADE"`)."""
    project = create_project(client, admin_token, org_id, "Migration Plain Group Project")
    member_a = create_org_user(client, admin_token, org_id, "migrate-plain-a@example.com", role="member")
    member_b = create_org_user(client, admin_token, org_id, "migrate-plain-b@example.com", role="member")

    group_id = uuid.uuid4()
    with _downgraded_to_0018(), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_groups (id, project_id, name, role, is_default, created_at, updated_at) "
                "VALUES (:id, :project_id, 'Stakeholders', 'stakeholder', true, now(), now())"
            ),
            {"id": str(group_id), "project_id": project["id"]},
        )
        for member_id in (member_a, member_b):
            conn.execute(
                text(
                    "INSERT INTO project_group_members (id, project_group_id, user_id, created_at, updated_at) "
                    "VALUES (:id, :group_id, :user_id, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "group_id": str(group_id), "user_id": member_id},
            )

    # Already back at head — the `with` block above ran the real upgrade.
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert not any(g["id"] == str(group_id) for g in groups), "the plain default group must be deleted"

    roles_by_user = direct_project_roles(project["id"])
    assert "stakeholder" in roles_by_user.get(member_a, set()), "member_a must hold a direct stakeholder grant"
    assert "stakeholder" in roles_by_user.get(member_b, set()), "member_b must hold a direct stakeholder grant"


def test_default_group_with_extra_composition_materializes_members_and_survives_demoted(client, admin_token, org_id):
    """A default group with composition beyond plain direct members (here:
    a cross-project member-source reference, mirroring `seed_demo_data.py`'s
    real "Stakeholders" group) — its direct user member still gets
    materialized into a direct grant, but the group itself is *not*
    deleted: it survives as an ordinary, fully-manageable custom group with
    its nested composition intact. Also pins C-U-08 (manager coverage is
    preserved exactly) for the case where the migrated group's role is
    PROJECT_MANAGER: the group's direct member ends up a manager via their
    new direct grant, the same person who was already a manager via the
    group beforehand — no manager is lost or gained."""
    project = create_project(client, admin_token, org_id, "Migration Extra Composition Project")
    referenced_project = create_project(client, admin_token, org_id, "Migration Referenced Project")
    solo_manager = create_org_user(client, admin_token, org_id, "migrate-extra-manager@example.com", role="member")

    group_id = uuid.uuid4()
    with _downgraded_to_0018(), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_groups (id, project_id, name, role, is_default, created_at, updated_at) "
                "VALUES (:id, :project_id, 'Project Managers', 'project_manager', true, now(), now())"
            ),
            {"id": str(group_id), "project_id": project["id"]},
        )
        conn.execute(
            text(
                "INSERT INTO project_group_members (id, project_group_id, user_id, created_at, updated_at) "
                "VALUES (:id, :group_id, :user_id, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "group_id": str(group_id), "user_id": solo_manager},
        )
        conn.execute(
            text(
                "INSERT INTO project_group_members (id, project_group_id, source_project_id, created_at, updated_at) "
                "VALUES (:id, :group_id, :source_project_id, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "group_id": str(group_id), "source_project_id": referenced_project["id"]},
        )

    # Already back at head — the `with` block above ran the real upgrade.
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next((g for g in groups if g["id"] == str(group_id)), None)
    assert reloaded is not None, "a group with extra composition must survive the migration, not be deleted"
    # PR7 of the members/groups directory rework plan (docs/decisions.md):
    # `role` was replaced by `roles` on `ProjectGroupOut` — the migrated
    # group's pre-existing role now survives as exactly one grant in that
    # list, backfilled by 0022 immediately after 0019's own conversion runs.
    assert reloaded["roles"] == ["project_manager"]
    assert "role" not in reloaded
    assert "is_default" not in reloaded
    assert solo_manager in reloaded["member_user_ids"], "the group's own composition is left intact"
    assert referenced_project["id"] in reloaded["member_source_project_ids"]

    roles_by_user = direct_project_roles(project["id"])
    assert "project_manager" in roles_by_user.get(solo_manager, set()), (
        "the group's direct member must also hold a direct PROJECT_MANAGER grant after migration"
    )

    # C-U-08: manager coverage preserved exactly — solo_manager was the
    # project's only manager (via this group) before the migration and
    # remains one afterward (now via their new direct grant, still backed
    # by the surviving group too), never zero.
