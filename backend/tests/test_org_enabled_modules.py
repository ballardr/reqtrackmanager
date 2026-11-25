"""Tests for `GET /orgs/{id}/enabled-modules`: the member-readable list of modules an organisation can use.

Org Resources is a page people work in, so a plain member (not only an administrator) must be able to learn which
module sections to offer. The endpoint carries keys only, lists a module only while it is entitled and enabled, names
the sub-components that are off, and is refused to anyone outside the organisation.
"""

import uuid as uuid_lib

from app.database import SessionLocal
from app.models.module import OrganizationModuleEnablement, OrganizationModuleSubComponentDefault
from app.modules.registry import get_module_registry
from tests.conftest import auth_headers, create_org_user, login


def _enabled(client, token, org_id):
    resp = client.get(f"/api/v1/orgs/{org_id}/enabled-modules", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {row["module_key"]: row for row in resp.json()}


def test_a_plain_member_reads_the_enabled_modules_and_the_administrator_view_agrees(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "enabled-modules-member@example.com")
    member_token = login(client, "enabled-modules-member@example.com", "Password123!")

    # The administrator-only list is refused to the member; the member-readable one is not.
    assert client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(member_token)).status_code == 403
    by_key = _enabled(client, member_token, org_id)

    admin_view = client.get(f"/api/v1/orgs/{org_id}/modules", headers=auth_headers(admin_token)).json()
    assert set(by_key) == {m["module_key"] for m in admin_view if m["enabled"] and m["entitled"]}
    assert by_key
    # Keys only: nothing else of the module's description leaks to a member.
    assert all(set(row) == {"module_key", "disabled_sub_components"} for row in by_key.values())


def test_a_disabled_module_is_not_listed(client, admin_token, org_id):
    key = next(iter(_enabled(client, admin_token, org_id)))
    db = SessionLocal()
    try:
        db.add(OrganizationModuleEnablement(
            organization_id=uuid_lib.UUID(org_id), module_key=key, enabled=False, default_project_enabled=False,
        ))
        db.commit()
    finally:
        db.close()
    assert key not in _enabled(client, admin_token, org_id)


def test_a_switched_off_sub_component_is_named(client, admin_token, org_id):
    definition = next(m for m in get_module_registry().values() if m.sub_components)
    key, sub_key = definition.key, definition.sub_components[0].key
    db = SessionLocal()
    try:
        # The module is switched on explicitly, so the sub-component state is the only thing under test.
        db.add(OrganizationModuleEnablement(
            organization_id=uuid_lib.UUID(org_id), module_key=key, enabled=True, default_project_enabled=True,
        ))
        db.add(OrganizationModuleSubComponentDefault(
            organization_id=uuid_lib.UUID(org_id), module_key=key, subcomponent_key=sub_key, enabled=True,
            default_project_enabled=True,
        ))
        db.commit()
    finally:
        db.close()
    assert sub_key not in _enabled(client, admin_token, org_id)[key]["disabled_sub_components"]

    db = SessionLocal()
    try:
        row = db.query(OrganizationModuleSubComponentDefault).filter_by(
            organization_id=uuid_lib.UUID(org_id), module_key=key, subcomponent_key=sub_key,
        ).one()
        row.enabled = False
        db.commit()
    finally:
        db.close()
    assert sub_key in _enabled(client, admin_token, org_id)[key]["disabled_sub_components"]


def test_someone_outside_the_organisation_is_refused_and_an_unknown_organisation_is_not_found(client, admin_token, org_id):
    other = client.post("/api/v1/orgs", json={"name": "Enabled modules other org"}, headers=auth_headers(admin_token))
    assert other.status_code in (200, 201), other.text
    outsider_org = other.json()["id"]
    create_org_user(client, admin_token, outsider_org, "enabled-modules-outsider@example.com")
    outsider_token = login(client, "enabled-modules-outsider@example.com", "Password123!")
    assert client.get(f"/api/v1/orgs/{org_id}/enabled-modules", headers=auth_headers(outsider_token)).status_code == 403
    assert client.get(f"/api/v1/orgs/{uuid_lib.uuid4()}/enabled-modules", headers=auth_headers(admin_token)).status_code in (403, 404)
