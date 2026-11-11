"""Tests for the Pain Point submission policy (who may submit a Pain Point in a project).

Covers the default (any member), a project restricting submission to Pain Point managers, the resolution order
(own setting, nearest ancestor project, organisation default, platform default), who may change each tier, the
single decision reaching every path (create endpoint, record-table `can_create`, import rights, the Links panel
flag) and the bundle round trip at project and organisation level.

Each test builds its own organisation, so none depends on state left by another test or run.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy.models import PainPointSubmissionSetting
from app.modules.context_strategy.tests.test_context_strategy_export_import import _export, _import
from app.modules.context_strategy.tests.test_context_strategy_pain_point_api import (
    _PAYLOAD_FIELDS,
    _add_plain_member,
    _create_pain_point,
    _grant_project_module_role,
    _market_type_id,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.registry import get_record_table_providers
from app.services.record_tables import creatable_record_types, import_rights
from tests.conftest import auth_headers, create_org_user, create_project, login

PAIN_POINT = "pain_point"


def _settings_url(project_id: str) -> str:
    return _project_base(project_id) + "/pain-point-settings"


def _set_project(client, token, project_id, policy):
    return client.put(_settings_url(project_id), json={"submission_policy": policy}, headers=auth_headers(token))


def _set_org(client, token, org_id, policy):
    return client.put(_org_base(org_id) + "/pain-point-settings", json={"submission_policy": policy}, headers=auth_headers(token))


def _read(client, token, project_id) -> dict:
    resp = client.get(_settings_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit_status(client, token, project_id) -> int:
    payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": _market_type_id(client, token, project_id)}
    return client.post(_project_base(project_id) + "/pain-points", json=payload, headers=auth_headers(token)).status_code


def _member(client, admin, org, project, label) -> str:
    return _add_plain_member(client, admin, org["id"], project["id"], f"{label}-{uuid.uuid4().hex[:6]}@policy.example.com")[1]


def test_default_is_managers_only_and_nothing_is_stored(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Default Co")
    member = _member(client, admin, org, project, "member")

    settings = _read(client, member, project["id"])
    assert settings == {
        "submission_policy": "managers", "source": "default", "own_policy": None, "organization_default": None,
        "can_submit": False, "restriction_message": "Pain Points are submitted by Pain Point Managers in this project.",
    }
    assert _read(client, admin, project["id"])["can_submit"] is True
    assert _submit_status(client, member, project["id"]) == 403
    assert _submit_status(client, admin, project["id"]) == 201
    db = SessionLocal()
    try:
        assert db.scalar(select(PainPointSubmissionSetting).where(PainPointSubmissionSetting.organization_id == uuid.UUID(org["id"]))) is None
    finally:
        db.close()


def test_the_default_refuses_a_member_and_accepts_a_manager(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Managers Co")
    member = _member(client, admin, org, project, "member")
    manager_email = f"manager-{uuid.uuid4().hex[:6]}@policy.example.com"
    manager_id = create_org_user(client, admin, org["id"], manager_email)
    resp = client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": manager_id, "role": "member"}, headers=auth_headers(admin))
    assert resp.status_code == 204, resp.text
    _grant_project_module_role(client, admin, project["id"], manager_id, "pain_point_manager")
    manager = login(client, manager_email, "Password123!")

    refused = client.post(
        _project_base(project["id"]) + "/pain-points",
        json={**_PAYLOAD_FIELDS, "pain_point_type_id": _market_type_id(client, member, project["id"])}, headers=auth_headers(member),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Pain Points are submitted by Pain Point Managers in this project."
    assert _read(client, member, project["id"])["can_submit"] is False
    assert _read(client, member, project["id"])["restriction_message"] == refused.json()["detail"]
    assert _read(client, manager, project["id"])["can_submit"] is True
    assert _submit_status(client, manager, project["id"]) == 201
    assert _submit_status(client, admin, project["id"]) == 201  # a project manager holds the manager tier

    assert _set_project(client, admin, project["id"], "members").status_code == 200
    assert _submit_status(client, member, project["id"]) == 201


def test_the_refusal_points_to_enhancement_requests_only_where_the_module_is_enabled(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Guidance Co")
    member = _member(client, admin, org, project, "member")

    def refusal() -> str:
        payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": _market_type_id(client, member, project["id"])}
        resp = client.post(_project_base(project["id"]) + "/pain-points", json=payload, headers=auth_headers(member))
        assert resp.status_code == 403
        return resp.json()["detail"]

    assert "Enhancement Request" not in refusal()
    enabled = client.put(f"/api/v1/orgs/{org['id']}/modules/product_feedback", json={"enabled": True}, headers=auth_headers(admin))
    assert enabled.status_code == 200, enabled.text
    assert refusal().endswith("Raise an Enhancement Request instead.")


def test_clearing_the_override_returns_to_the_inherited_policy(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Clear Co")
    member = _member(client, admin, org, project, "member")
    _set_project(client, admin, project["id"], "members")
    assert _submit_status(client, member, project["id"]) == 201

    cleared = _set_project(client, admin, project["id"], None)
    assert cleared.status_code == 200 and cleared.json()["source"] == "default" and cleared.json()["own_policy"] is None
    assert _submit_status(client, member, project["id"]) == 403


def test_a_plain_member_cannot_change_the_project_setting(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Write Gate Co")
    member = _member(client, admin, org, project, "member")

    assert _set_project(client, member, project["id"], "members").status_code == 403
    assert _read(client, admin, project["id"])["submission_policy"] == "managers"


def test_organisation_default_applies_and_a_project_setting_overrides_it(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Org Default Co")
    other = create_project(client, admin, org["id"], "Policy Org Default Other")
    member = _member(client, admin, org, project, "member")
    other_member = _add_plain_member(client, admin, org["id"], other["id"], f"other-{uuid.uuid4().hex[:6]}@policy.example.com")[1]

    assert _set_org(client, admin, org["id"], "members").json() == {"submission_policy": "members"}
    inherited = _read(client, member, project["id"])
    assert inherited["submission_policy"] == "members" and inherited["source"] == "organization"
    assert inherited["organization_default"] == "members" and inherited["own_policy"] is None
    assert _submit_status(client, member, project["id"]) == 201

    assert _set_project(client, admin, other["id"], "managers").status_code == 200
    overridden = _read(client, other_member, other["id"])
    assert overridden["submission_policy"] == "managers" and overridden["source"] == "project"
    assert overridden["organization_default"] == "members"
    assert _submit_status(client, other_member, other["id"]) == 403

    assert _set_org(client, admin, org["id"], None).json() == {"submission_policy": None}
    assert _read(client, member, project["id"])["source"] == "default"
    assert _submit_status(client, member, project["id"]) == 403


def test_only_an_organisation_administrator_changes_the_organisation_default(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Org Gate Co")
    member = _member(client, admin, org, project, "member")

    assert _set_org(client, member, org["id"], "members").status_code == 403
    read = client.get(_org_base(org["id"]) + "/pain-point-settings", headers=auth_headers(member))
    assert read.status_code == 200 and read.json() == {"submission_policy": None}


def test_a_child_project_follows_the_nearest_ancestor(client, admin_token):
    org, _unused, admin = _setup(client, admin_token, "Policy Nested Co")
    parent = create_project(client, admin, org["id"], "Policy Parent", can_be_parent=True)
    middle = create_project(client, admin, org["id"], "Policy Middle", parent_project_id=parent["id"], can_be_parent=True)
    child = create_project(client, admin, org["id"], "Policy Child", parent_project_id=middle["id"])
    member = _add_plain_member(client, admin, org["id"], child["id"], f"child-{uuid.uuid4().hex[:6]}@policy.example.com")[1]

    _set_project(client, admin, parent["id"], "members")
    inherited = _read(client, member, child["id"])
    assert inherited["submission_policy"] == "members" and inherited["source"] == "ancestor"
    assert _submit_status(client, member, child["id"]) == 201

    # The nearer ancestor wins over the farther one.
    _set_project(client, admin, middle["id"], "managers")
    assert _read(client, member, child["id"])["submission_policy"] == "managers"
    assert _submit_status(client, member, child["id"]) == 403


def test_every_path_reads_the_same_decision(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Paths Co")
    member_token = _member(client, admin, org, project, "member")
    member_id = client.get("/api/v1/auth/me", headers=auth_headers(member_token)).json()["id"]

    provider = get_record_table_providers()[PAIN_POINT]
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        user = db.get(User, uuid.UUID(member_id))
        admin_user = db.get(User, uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(admin)).json()["id"]))
        assert row is not None and user is not None and admin_user is not None

        assert provider.can_create is not None and provider.can_create(db, user, row.id) is False
        assert PAIN_POINT not in creatable_record_types(db, user, row, [PAIN_POINT])
        assert import_rights(db, user, row, PAIN_POINT, provider)[0] is False
        assert PAIN_POINT in creatable_record_types(db, admin_user, row, [PAIN_POINT])
        assert import_rights(db, admin_user, row, PAIN_POINT, provider)[0] is True
    finally:
        db.close()

    _set_project(client, admin, project["id"], "members")
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        user = db.get(User, uuid.UUID(member_id))
        assert row is not None and user is not None
        assert PAIN_POINT in creatable_record_types(db, user, row, [PAIN_POINT])
    finally:
        db.close()


def test_editing_and_commenting_stay_open_to_the_submitter_tier_unchanged(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Unchanged Co")
    member = _member(client, admin, org, project, "member")
    _set_project(client, admin, project["id"], "members")
    pain_point = _create_pain_point(client, member, project["id"])  # submitted while open to members
    _set_project(client, admin, project["id"], "managers")

    comment = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/comments", json={"body": "More evidence."},
        headers=auth_headers(member),
    )
    assert comment.status_code == 201, comment.text


def test_project_bundle_round_trips_the_setting(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Policy Bundle Co")
    _set_project(client, admin, project["id"], "managers")
    bundle = _export(client, admin, project["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    assert exported["pain_point_submission_policy"] == "managers"

    imported = _import(client, admin, org["id"], bundle, "Policy Bundle Copy")
    assert imported["warnings"] == []
    copy = _read(client, admin, imported["project"]["id"])
    assert copy["own_policy"] == "managers" and copy["source"] == "project"


def test_an_unset_project_exports_no_setting(client, admin_token):
    _org, project, admin = _setup(client, admin_token, "Policy Bundle Unset Co")
    exported = json.loads(zipfile.ZipFile(io.BytesIO(_export(client, admin, project["id"]))).read("project.json"))
    assert "pain_point_submission_policy" not in exported


def test_organisation_bundle_round_trips_the_default(client, admin_token):
    org, _project, admin = _setup(client, admin_token, "Policy Org Bundle Co")
    _set_org(client, admin, org["id"], "managers")
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(admin))
    assert export.status_code == 200, export.text
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Policy Org Bundle Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    new_org = uuid.UUID(resp.json()["organization"]["id"])

    db = SessionLocal()
    try:
        row = db.scalar(select(PainPointSubmissionSetting).where(
            PainPointSubmissionSetting.organization_id == new_org, PainPointSubmissionSetting.project_id.is_(None),
        ))
        assert row is not None and row.policy.value == "managers"
    finally:
        db.close()


def test_migration_keeps_existing_organisations_open_to_members(client, admin_token):
    """Revision 0142 gives an organisation with no default an explicit `members` default and leaves a chosen one alone.

    Runs inside a transaction that is rolled back, so organisations other tests are creating are not touched.
    """
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.database import engine

    path = Path(__file__).resolve().parents[1] / "migrations" / "0142_pain_point_submission_existing_orgs_open.py"
    spec = importlib.util.spec_from_file_location("pain_point_submission_0142", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    unset, _project, _admin = _setup(client, admin_token, "Policy Migration Unset Co")
    chosen, _project2, chosen_admin = _setup(client, admin_token, "Policy Migration Chosen Co")
    assert _set_org(client, chosen_admin, chosen["id"], "managers").status_code == 200

    def default_of(conn, org_id) -> str | None:
        return conn.execute(text(
            "SELECT policy FROM pain_point_submission_settings WHERE organization_id = :o AND project_id IS NULL"
        ), {"o": org_id}).scalar()

    with engine.connect() as conn, conn.begin() as transaction:
        assert default_of(conn, unset["id"]) is None
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()  # running it again changes nothing
        assert default_of(conn, unset["id"]) == "members"
        assert default_of(conn, chosen["id"]) == "managers"
        transaction.rollback()
