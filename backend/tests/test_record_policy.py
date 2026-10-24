"""Tests for the personal-data policy of record export and import (`services.record_policy`,
`routers.system.record_policy`, `routers.orgs.record_policy`).

A tagged column is kept only when the organisation's policy allows its tag (override, else server default,
else excluded) **and** the person holds `export_personal_data` in the project. Each test builds its own
organisation, so none depends on state left by another.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant, UserCustomRoleGrant
from app.modules.registry import RECORD_SENSITIVITY_TAGS, get_record_table_providers
from app.services.permissions import ADMINISTRATIVE_PERMISSIONS
from app.services.rbac import EXPORT_PERSONAL_DATA, get_effective_permissions
from tests.conftest import auth_headers, create_org_admin_in, create_org_group, create_org_user
from tests.link_world import REQ, World
from tests.test_record_tables import _audit, _base, _csv, _export, _import, _member, _rows


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Policy Org", context_strategy=True)


@pytest.fixture
def owner_is_contact(monkeypatch):
    """Tags the requirement `owner` column as `contact` for the duration of a test."""
    real = get_record_table_providers()[REQ]

    def tagged(db, project_row):
        return [dataclasses.replace(c, sensitivity="contact") if c.key == "owner" else c for c in real.columns(db, project_row)]

    patched = dataclasses.replace(real, columns=tagged)
    from app.services import record_tables

    monkeypatch.setattr(record_tables, "get_record_table_providers", lambda: {**get_record_table_providers(), REQ: patched})


def _set_server(client, admin_token, tag: str, allowed: bool):
    return client.put(
        f"/api/v1/system/record-sensitivity-policy/{tag}", json={"allowed": allowed}, headers=auth_headers(admin_token),
    )


def _set_org(world: World, tag: str, allowed: bool | None, token: str | None = None):
    return world.client.put(
        f"/api/v1/orgs/{world.org['id']}/record-sensitivity-policy/{tag}", json={"allowed": allowed},
        headers=auth_headers(token or world.token),
    )


def _owner_exported(resp) -> bool:
    return "owner" in _rows(resp)[0]


# --- the permission -----------------------------------------------------------------------------------------------


def test_the_permission_is_held_by_org_admins_and_project_administrators_and_managers_only(world):
    project = world.project()
    db = SessionLocal()
    try:
        def held(user_id: uuid.UUID) -> bool:
            return EXPORT_PERSONAL_DATA in get_effective_permissions(db, user_id, project_id=uuid.UUID(project["id"]))

        assert EXPORT_PERSONAL_DATA in ADMINISTRATIVE_PERMISSIONS
        assert held(world.user_id)
        for role, expected in (("project_administrator", True), ("project_manager", True), ("stakeholder", False), ("member", False)):
            email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
            user_id = create_org_user(world.client, world.token, world.org["id"], email)
            resp = world.client.post(
                f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role},
                headers=auth_headers(world.token),
            )
            assert resp.status_code in (200, 201, 204), resp.text
            assert held(uuid.UUID(user_id)) is expected, role
    finally:
        db.close()


def test_a_custom_role_can_grant_the_permission_to_a_user_or_a_group(world):
    project = world.project()
    user_id = create_org_user(world.client, world.token, world.org["id"], f"u-{uuid.uuid4().hex[:6]}@example.com")
    member_id = create_org_user(world.client, world.token, world.org["id"], f"m-{uuid.uuid4().hex[:6]}@example.com")
    group_id = create_org_group(world.client, world.token, world.org["id"], "Privacy team", users=[member_id])
    for uid in (user_id, member_id):
        world.client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": uid, "role": "member"}, headers=auth_headers(world.token),
        )
    db = SessionLocal()
    try:
        role = CustomRoleDefinition(organization_id=world.org["id"], name="Privacy", description="", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=EXPORT_PERSONAL_DATA))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=world.org["id"]))
        db.add(GroupCustomRoleGrant(org_group_id=uuid.UUID(group_id), custom_role_id=role.id, organization_id=world.org["id"]))
        db.commit()
        for uid in (user_id, member_id):
            assert EXPORT_PERSONAL_DATA in get_effective_permissions(db, uuid.UUID(uid), project_id=uuid.UUID(project["id"]))
    finally:
        db.close()


# --- the matrix: server default x organisation override x permission ----------------------------------------------


@pytest.mark.parametrize(
    ("server", "override", "policy_allows"),
    [
        (False, None, False), (True, None, True),
        (False, True, True), (True, False, False),
        (False, False, False), (True, True, True),
    ],
)
def test_a_tagged_column_needs_the_policy_and_the_permission(client, admin_token, world, owner_is_contact, server, override, policy_allows):
    project = world.project()
    world.requirement(project, "Has an owner")
    if server:
        assert _set_server(client, admin_token, "contact", True).status_code == 200
    if override is not None:
        assert _set_org(world, "contact", override).status_code == 200
    member_token = _member(world, project, "member")
    admin_user = _export(world, project)  # organisation administrator: holds the permission
    reader = _export(world, project, token=member_token)  # project member: reads, lacks the permission

    assert _owner_exported(admin_user) is policy_allows
    assert _owner_exported(reader) is False
    columns = client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(member_token)).json()
    if policy_allows:
        assert columns["omitted_reasons"] == {"contact": "permission"}
    else:
        assert columns["omitted_reasons"] == {"contact": "policy"}
    admin_columns = client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(world.token)).json()
    assert admin_columns["omitted_reasons"] == ({} if policy_allows else {"contact": "policy"})


def test_a_project_administrator_may_include_the_column_once_the_policy_allows_it(client, admin_token, world, owner_is_contact):
    project = world.project()
    world.requirement(project, "Has an owner")
    _set_server(client, admin_token, "contact", True)
    token = _member(world, project, "project_administrator")
    assert _owner_exported(_export(world, project, token=token)) is True


def test_an_import_ignores_a_personal_column_the_person_may_not_write_and_says_why(client, admin_token, world, owner_is_contact):
    project = world.project()
    world.requirement(project, "Has an owner")
    _set_server(client, admin_token, "contact", True)
    code = _rows(_export(world, project))[0]["code"]
    body = _csv(["code", "owner"], [code, "someone@example.com"])

    allowed = _import(world, project, body, apply=False).json()
    assert "owner" not in allowed["ignored_columns"] and allowed["omitted_sensitivity"] == []

    _set_org(world, "contact", False)
    refused = _import(world, project, body, apply=False).json()
    assert refused["ignored_columns"]["owner"] == "Excluded by your organisation's policy."
    assert refused["omitted_sensitivity"] == ["contact"]

    _set_org(world, "contact", None)
    stakeholder = _member(world, project, "stakeholder")
    no_permission = _import(world, project, body, token=stakeholder)
    assert no_permission.status_code == 200
    assert no_permission.json()["ignored_columns"]["owner"] == "Excluded: you do not have permission to import personal data."


def test_an_export_and_an_import_that_include_tagged_columns_audit_the_tags_and_never_the_data(client, admin_token, world, owner_is_contact):
    project = world.project()
    world.requirement(project, "Has an owner")
    _set_server(client, admin_token, "contact", True)
    rows = _rows(_export(world, project))
    assert _audit(project, "records_exported")[0].detail["included_sensitivity"] == ["contact"]
    _import(world, project, _csv(["code", "owner"], [rows[0]["code"], ""]), apply=True)
    detail = _audit(project, "records_imported")[0].detail
    assert detail["included_sensitivity"] == ["contact"] and "someone@example.com" not in str(detail)


# --- the server panel's API ---------------------------------------------------------------------------------------


def test_a_fresh_server_excludes_every_tag_and_a_server_admin_can_opt_in_and_out(client, admin_token):
    listing = client.get("/api/v1/system/record-sensitivity-policy", headers=auth_headers(admin_token))
    assert listing.status_code == 200
    assert [(i["tag"], i["allowed"]) for i in listing.json()] == [(tag, False) for tag in RECORD_SENSITIVITY_TAGS]

    assert _set_server(client, admin_token, "personal", True).json() == {"tag": "personal", "allowed": True}
    states = {i["tag"]: i["allowed"] for i in client.get("/api/v1/system/record-sensitivity-policy", headers=auth_headers(admin_token)).json()}
    assert states == {"personal": True, "contact": False, "free_text_people": False}
    _set_server(client, admin_token, "personal", False)
    assert client.get("/api/v1/system/record-sensitivity-policy", headers=auth_headers(admin_token)).json()[0]["allowed"] is False


def test_only_a_server_admin_may_change_the_server_default_and_an_unknown_tag_is_a_404(client, admin_token, world):
    assert _set_server(client, world.token, "contact", True).status_code == 403
    assert client.get("/api/v1/system/record-sensitivity-policy", headers=auth_headers(world.token)).status_code == 403
    assert _set_server(client, admin_token, "nonsense", True).status_code == 404


def test_a_server_change_is_one_audit_event_with_old_and_new_and_nothing_else(client, admin_token):
    _set_server(client, admin_token, "free_text_people", True)
    db = SessionLocal()
    try:
        events = db.query(AuditEvent).filter(AuditEvent.action == "record_policy.server_default_updated").all()
    finally:
        db.close()
    assert [e.detail for e in events] == [{"tag": "free_text_people", "old": False, "new": True}]


# --- the organisation panel's API ---------------------------------------------------------------------------------


def test_an_organisation_sees_the_server_default_its_override_and_the_effective_value(client, admin_token, world):
    _set_server(client, admin_token, "contact", True)
    url = f"/api/v1/orgs/{world.org['id']}/record-sensitivity-policy"
    before = {i["tag"]: i for i in client.get(url, headers=auth_headers(world.token)).json()}
    assert before["contact"] == {"tag": "contact", "server_allowed": True, "override": None, "effective": True}
    assert before["personal"] == {"tag": "personal", "server_allowed": False, "override": None, "effective": False}

    assert _set_org(world, "contact", False).json() == {"tag": "contact", "server_allowed": True, "override": False, "effective": False}
    assert _set_org(world, "personal", True).json()["effective"] is True
    assert _set_org(world, "contact", None).json() == {"tag": "contact", "server_allowed": True, "override": None, "effective": True}


def test_an_override_only_reaches_its_own_organisation(client, admin_token, world):
    other, other_token = create_org_admin_in(client, admin_token, f"Other Policy Org {uuid.uuid4().hex[:6]}")
    _set_org(world, "contact", True)
    states = {i["tag"]: i for i in client.get(f"/api/v1/orgs/{other['id']}/record-sensitivity-policy", headers=auth_headers(other_token)).json()}
    assert states["contact"]["override"] is None and states["contact"]["effective"] is False


def test_only_an_org_admin_of_that_organisation_may_read_or_change_the_override(client, admin_token, world):
    project = world.project()
    member_token = _member(world, project, "project_administrator")
    url = f"/api/v1/orgs/{world.org['id']}/record-sensitivity-policy"
    assert client.get(url, headers=auth_headers(member_token)).status_code == 403
    assert _set_org(world, "contact", True, token=member_token).status_code == 403
    _, other_token = create_org_admin_in(client, admin_token, f"Foreign Policy Org {uuid.uuid4().hex[:6]}")
    assert _set_org(world, "contact", True, token=other_token).status_code == 403
    assert _set_org(world, "nonsense", True).status_code == 404


def test_an_override_change_is_one_audit_event_scoped_to_the_organisation(world):
    _set_org(world, "contact", True)
    _set_org(world, "contact", None)
    db = SessionLocal()
    try:
        events = (
            db.query(AuditEvent)
            .filter(AuditEvent.action == "record_policy.organization_override_updated", AuditEvent.organization_id == world.org["id"])
            .order_by(AuditEvent.created_at)
            .all()
        )
    finally:
        db.close()
    assert [e.detail for e in events] == [
        {"tag": "contact", "old": None, "new": True}, {"tag": "contact", "old": True, "new": None},
    ]


def test_deleting_the_organisation_leaves_no_override_behind(client, admin_token):
    from app.models.record_policy import OrganizationRecordSensitivityOverride

    org, token = create_org_admin_in(client, admin_token, f"Doomed Policy Org {uuid.uuid4().hex[:6]}")
    client.put(f"/api/v1/orgs/{org['id']}/record-sensitivity-policy/contact", json={"allowed": True}, headers=auth_headers(token))
    db = SessionLocal()
    try:
        assert db.query(OrganizationRecordSensitivityOverride).filter_by(organization_id=org["id"]).count() == 1
        constraint = OrganizationRecordSensitivityOverride.__table__.c.organization_id.foreign_keys
        assert {fk.ondelete for fk in constraint} == {"CASCADE"}
    finally:
        db.close()

