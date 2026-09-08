"""Permission-boundary tests for the Compliance Module's Phase 18 global (no
org/project id in the path) endpoints (docs/compliance-module-plan.md
Phase 18): `GET /api/v1/compliance/nav-visibility` and `GET /api/v1/
compliance/standards/{standard_id}` — mounted via `ModuleDefinition.
get_global_router` rather than either of this module's other two routers,
since neither endpoint has a single org/project id of its own to key a
per-request permission dependency off (see `global_router.py`'s own module
docstring for the full reasoning).

Covers the exact matrix compliance-module-plan.md Phase 18 asks for, and
this repo's `docs/soc2/policies/access-control-policy.md` posture every
other compliance endpoint already gives (404, not 403, for "not a member of
this org at all" — a disabled/inaccessible resource must be
indistinguishable from a nonexistent one):

- `nav-visibility`: `False` for a plain member with no role and no
  standards; `True` in isolation for a `compliance_manager` grant, for
  `org_admin`, and for `is_server_admin`; `False` for a user with zero org
  memberships anywhere.
- `standards/{id}`: 404 (not 403, not 200 with someone else's data) for a
  member of a *different* org than the one the standard belongs to
  (cross-org leak check) and for a genuine member of the right org whose
  org has the module disabled; 200 with the right `organization_id` for a
  real member; 404 for a genuinely nonexistent id.
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
    """Grants `user_id` a plain `member` `UserOrgRole` on `organization_id`
    via direct ORM insert, mirroring `tests/conftest.py::direct_project_
    roles`'s own precedent for reaching a state the real API has no
    endpoint for.

    Needed only for the server-admin isolation test below: the real
    `POST /orgs/{id}/users` endpoint always creates a *brand-new* user
    (409s on an existing email), so there is no API path to add the
    already-existing bootstrap server admin as a second org's plain
    member — this is a genuine gap in the directory API, not something
    this test works around for convenience; the bootstrap admin having
    membership in a second org is exactly the "server admin who also
    happens to be a member somewhere" case `get_nav_visibility` needs to
    isolate from its own `org_admin`/`compliance_manager` branches.
    """
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
    assert resp.json() == {"visible": False}


def test_nav_visibility_true_for_compliance_manager_grant(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "nav-manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "nav-manager@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(manager_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": True}


def test_nav_visibility_true_for_org_admin(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "nav-org-admin@example.com", role="org_admin")
    org_admin_token = login(client, "nav-org-admin@example.com", "Password123!")

    resp = client.get("/api/v1/compliance/nav-visibility", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"visible": True}


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
    assert resp.json() == {"visible": True}


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
    assert resp.json() == {"visible": False}


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
