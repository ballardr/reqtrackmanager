"""Permission-boundary tests for the Compliance Module's global endpoints, `GET /api/v1/compliance/nav-visibility` and
`GET /api/v1/compliance/standards/{standard_id}`, mounted through `ModuleDefinition.get_global_router` because neither has
an organisation or project id to key a permission dependency off (see `global_router.py`). They pin the matrix of
`docs/soc2/policies/access-control-policy.md`: 404, not 403, for a non-member, so an inaccessible resource looks absent.

- `nav-visibility`: `False` for a plain member with no role and no standards; `True` in isolation for a
  `compliance_manager` grant, `org_admin` and `is_server_admin`; `False` for a user with no organisation membership.
- `standards/{id}`: 404 for a member of a different organisation (cross-organisation leak check), for a member whose
  organisation has the module disabled and for a nonexistent id; 200 with the right `organization_id` for a member.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.enums import OrgRole
from app.models.organization import UserOrgRole
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def _create_standard(client, token, org_id, *, reference="NAV-STD", name="Nav Test Standard"):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/modules/compliance/standards",
        json={"reference": reference, "name": name, "initial_version_label": "1.0"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _grant_compliance_manager(client, admin_token, org_id, user_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_manager"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _set_module_enabled(client, admin_token, org_id, enabled: bool):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": enabled}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def _get_current_user_id(client, token) -> str:
    resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _grant_plain_membership_directly(user_id: str, organization_id: str) -> None:
    """Grants `user_id` a plain `member` `UserOrgRole` on `organization_id` by direct ORM insert, as
    `tests/conftest.py::direct_project_roles` does for a state the API cannot reach.

    The server-admin isolation test needs it: `POST /orgs/{id}/users` always creates a new user (409 on an existing
    email), so the API cannot add the bootstrap server admin to a second organisation as a plain member, the case
    `get_nav_visibility` must isolate from its `org_admin` and `compliance_manager` branches."""
    db = SessionLocal()
    try:
        db.add(UserOrgRole(user_id=uuid.UUID(user_id), organization_id=uuid.UUID(organization_id), role=OrgRole.MEMBER))
        db.commit()
    finally:
        db.close()


# --- nav-visibility -------------------------------------------------------------


def test_nav_visibility_false_for_plain_member_with_no_role_and_no_standards(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "nav-plain-member@example.com", role="member")
    member_token = login(client, "nav-plain-member@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(member_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": False, "status_organization_ids": []}


def test_nav_visibility_true_for_compliance_manager_grant(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "nav-manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "nav-manager@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(manager_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": True, "status_organization_ids": [str(org_id)]}


def test_nav_visibility_true_for_org_admin(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "nav-org-admin@example.com", role="org_admin")
    org_admin_token = login(client, "nav-org-admin@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": True, "status_organization_ids": [str(org_id)]}


def test_nav_visibility_true_for_server_admin_via_plain_membership(client, admin_token, org_id):
    """Isolates the `is_server_admin` branch from the `org_admin` branch:
    the bootstrap server admin is *also* `org_admin` on the seeded `org_id`
    fixture (see `test_compliance_standards_api.py`'s own comment on
    `admin_token`), so this test gives it only a plain `member` role on a
    second, freshly created org instead, and confirms visibility is still
    `True` there purely on `is_server_admin`."""
    second_org, _second_org_admin_token = create_org_admin_in(client, admin_token, "Nav Visibility Server Admin Org")
    admin_user_id = _get_current_user_id(client, admin_token)
    _grant_plain_membership_directly(admin_user_id, second_org["id"])

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visible"] is True
    assert str(second_org["id"]) in body["status_organization_ids"]


def test_nav_visibility_false_for_user_with_no_org_memberships_at_all(client, admin_token, org_id):
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Nav Visibility Orgless Org")
    orgless_id = create_org_user(
        client, other_org_admin_token, other_org["id"], "nav-orgless@example.com", role="member",
    )
    remove_resp = client.delete(
        f"/api/v1/orgs/{other_org['id']}/users/{orgless_id}/membership", headers=auth_headers(other_org_admin_token),
    )
    assert remove_resp.status_code == 204, remove_resp.text
    orgless_token = login(client, "nav-orgless@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(orgless_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": False, "status_organization_ids": []}


def test_nav_visibility_lists_no_status_organisation_for_a_member_who_only_sees_a_standard(client, admin_token, org_id):
    """A plain member sees the Standards tab because the organisation has a standard, but holds no role that reads the
    status views, so the By standard and Outstanding tabs (and the Organisation filter) must not list the organisation."""
    _create_standard(client, admin_token, org_id, reference="NAV-VIS-1", name="Visible Standard")
    create_org_user(client, admin_token, org_id, "nav-reader@example.com", role="member")
    reader_token = login(client, "nav-reader@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(reader_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": True, "status_organization_ids": []}


# --- standards/{id} ---------------------------------------------------------------


def test_get_standard_by_id_404s_for_a_member_of_a_different_org(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id)
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Cross Org Standard Lookup")
    assert other_org["id"] != org_id

    resp = client.get(f"/api/v1/compliance/standards/{standard['id']}", headers=auth_headers(other_org_admin_token))
    assert resp.status_code == 404, resp.text


def test_get_standard_by_id_404s_when_module_disabled_for_the_owning_org(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id)
    _set_module_enabled(client, admin_token, org_id, False)
    try:
        resp = client.get(f"/api/v1/compliance/standards/{standard['id']}", headers=auth_headers(admin_token))
        assert resp.status_code == 404, resp.text
    finally:
        _set_module_enabled(client, admin_token, org_id, True)


def test_get_standard_by_id_returns_the_standard_for_a_real_member(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id)

    resp = client.get(f"/api/v1/compliance/standards/{standard['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == standard["id"]
    assert body["organization_id"] == org_id


def test_get_standard_by_id_404s_for_a_nonexistent_standard(client, admin_token):
    resp = client.get(f"/api/v1/compliance/standards/{uuid.uuid4()}", headers=auth_headers(admin_token))
    assert resp.status_code == 404, resp.text
