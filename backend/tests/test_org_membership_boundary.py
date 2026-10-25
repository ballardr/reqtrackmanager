"""Tests for the organisation membership boundary (`services.org_membership`).

A `User` is global and organisation membership is what scopes an administrator's authority over it, so every
path that adds an existing account to an organisation on an administrator's say-so (a role grant by user id,
SCIM provisioning, an organisation bundle merge) must refuse an account another organisation holds unless the
organisation allows external users, and an organisation administrator must not be able to end an account that
is not wholly theirs: deactivating it (or SCIM `active: false`) removes it from that organisation only.
"""

import io
import json
import zipfile

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def _scim_headers(client, org_id: str, admin_headers: dict) -> dict:
    """Enables SCIM for the organisation and returns the bearer headers for its token."""
    resp = client.post(f"/api/v1/orgs/{org_id}/scim-token", headers=admin_headers)
    assert resp.status_code in (200, 201), resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _allow_external(client, org_id: str, admin_headers: dict) -> None:
    """Switches an organisation's external-user policy to `anyone`."""
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"external_user_policy": "anyone"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


def _foreign_account(client, admin_token, org_id) -> str:
    """An account that belongs to the default organisation only; returns its user id."""
    return create_org_user(client, admin_token, org_id, "victim@example.com")


def test_scim_cannot_pull_in_or_disable_an_account_another_organisation_holds(client, admin_token, org_id):
    """A tenant's SCIM token must not reach the server administrator or a member of another tenant."""
    _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Scim Attacker")
    scim = _scim_headers(client, attacker["id"], auth_headers(attacker_token))

    for email in ("victim@example.com", "admin@example.com"):
        resp = client.post("/scim/v2/Users", json={"userName": email}, headers=scim)
        assert resp.status_code == 403, (email, resp.text)

    # Neither account was touched.
    assert login(client, "victim@example.com", "Password123!")
    assert login(client, "admin@example.com", "ChangeMe123!")


def test_scim_still_provisions_new_and_unclaimed_accounts_and_allowed_externals(client, admin_token, org_id):
    """The supported flows keep working: a brand-new address, and an account the organisation may take."""
    victim_id = _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Scim Provisioner")
    headers = auth_headers(attacker_token)
    scim = _scim_headers(client, attacker["id"], headers)

    created = client.post("/scim/v2/Users", json={"userName": "fresh@example.com"}, headers=scim)
    assert created.status_code == 201, created.text

    _allow_external(client, attacker["id"], headers)
    taken = client.post("/scim/v2/Users", json={"userName": "victim@example.com"}, headers=scim)
    assert taken.status_code == 201 and taken.json()["id"] == victim_id


def test_scim_deactivation_is_scoped_to_the_organisation_for_a_shared_account(client, admin_token, org_id):
    """With external users allowed, deprovisioning an account two organisations hold removes it from the calling
    organisation only: it stays active and signed-in in the other one. A lone member is deactivated outright, and
    a ban is not lifted by `active: true`."""
    victim_id = _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Scim Deactivator")
    headers = auth_headers(attacker_token)
    scim = _scim_headers(client, attacker["id"], headers)
    _allow_external(client, attacker["id"], headers)
    assert client.post("/scim/v2/Users", json={"userName": "victim@example.com"}, headers=scim).status_code == 201

    patch = {"Operations": [{"op": "replace", "path": "active", "value": False}]}
    removed = client.patch(f"/scim/v2/Users/{victim_id}", json=patch, headers=scim)
    assert removed.status_code == 200 and removed.json()["active"] is False
    # Gone from the calling organisation...
    assert client.get(f"/scim/v2/Users/{victim_id}", headers=scim).status_code == 404
    # ...and untouched in the other one.
    victim_token = login(client, "victim@example.com", "Password123!")
    assert client.get("/api/v1/auth/me", headers=auth_headers(victim_token)).status_code == 200
    assert client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(victim_token)).status_code == 200

    sole = client.post("/scim/v2/Users", json={"userName": "sole@example.com"}, headers=scim).json()["id"]
    assert client.patch(f"/scim/v2/Users/{sole}", json=patch, headers=scim).json()["active"] is False


def test_scim_cannot_read_or_manage_a_server_administrator_who_joined_the_organisation(client, admin_token):
    """A platform administrator who joined an organisation as admin is still not that organisation's to manage."""
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Scim Joined")
    assert client.post(f"/api/v1/orgs/{attacker['id']}/join-as-admin", headers=auth_headers(admin_token)).status_code == 204
    scim = _scim_headers(client, attacker["id"], auth_headers(attacker_token))
    listing = client.get("/scim/v2/Users", headers=scim).json()
    assert all(u["userName"] != "admin@example.com" for u in listing["Resources"])


def test_role_grant_by_user_id_cannot_pull_in_a_foreign_account(client, admin_token, org_id):
    """A user id is not consent: granting a role to another tenant's account is refused unless the
    organisation allows external users; an unclaimed account is still assignable."""
    victim_id = _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Role Attacker")
    headers = auth_headers(attacker_token)

    refused = client.post(
        f"/api/v1/orgs/{attacker['id']}/users/{victim_id}/roles", json={"user_id": victim_id, "role": "member"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text

    _allow_external(client, attacker["id"], headers)
    allowed = client.post(
        f"/api/v1/orgs/{attacker['id']}/users/{victim_id}/roles", json={"user_id": victim_id, "role": "member"}, headers=headers,
    )
    assert allowed.status_code == 204, allowed.text


def test_deactivating_a_shared_account_deactivates_it_in_this_organisation_only(client, admin_token, org_id):
    """Deactivation ends a whole account, which is beyond one organisation's authority; for a two-organisation
    member it removes them from the acting organisation and leaves the account active in the other."""
    victim_id = _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Deactivate Attacker")
    headers = auth_headers(attacker_token)
    _allow_external(client, attacker["id"], headers)
    assert client.post(
        f"/api/v1/orgs/{attacker['id']}/users/{victim_id}/roles", json={"user_id": victim_id, "role": "member"}, headers=headers,
    ).status_code == 204

    resp = client.post(f"/api/v1/orgs/{attacker['id']}/users/{victim_id}/deactivate", headers=headers)
    assert resp.status_code == 204, resp.text

    members = client.get(f"/api/v1/orgs/{attacker['id']}/users", headers=headers).json()
    assert all(u["email"] != "victim@example.com" for u in members)
    victim_token = login(client, "victim@example.com", "Password123!")  # still active, and still in the first organisation
    assert client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(victim_token)).status_code == 200


def test_deactivating_a_server_administrator_only_removes_them_from_the_organisation(client, admin_token):
    """A server administrator who joined an organisation as admin loses that membership when its other admins
    deactivate them; the platform account stays active."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Deactivate Joined")
    assert client.post(f"/api/v1/orgs/{org['id']}/join-as-admin", headers=auth_headers(admin_token)).status_code == 204
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    resp = client.post(f"/api/v1/orgs/{org['id']}/users/{me['id']}/deactivate", headers=auth_headers(org_admin_token))
    assert resp.status_code == 204, resp.text
    members = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(org_admin_token)).json()
    assert all(u["email"] != "admin@example.com" for u in members)
    assert login(client, "admin@example.com", "ChangeMe123!")


def test_bundle_merge_does_not_add_a_foreign_account_or_its_group_membership(client, admin_token, org_id):
    """A crafted bundle (a zip the organisation administrator built) lists another tenant's account as an
    `org_admin` member and as a group member; the merge adds neither and says why."""
    _foreign_account(client, admin_token, org_id)
    attacker, attacker_token = create_org_admin_in(client, admin_token, "Merge Attacker")
    headers = auth_headers(attacker_token)
    exported = client.get(f"/api/v1/orgs/{attacker['id']}/export", headers=headers)
    assert exported.status_code == 200
    source = zipfile.ZipFile(io.BytesIO(exported.content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as crafted:
        for name in source.namelist():
            data = source.read(name)
            if name == "org.json":
                body = json.loads(data)
                body["members"].append({"email": "victim@example.com", "org_role": "org_admin"})
                body["org_groups"] = [{"name": "Crew", "member_emails": ["victim@example.com"], "nested_group_names": []}]
                data = json.dumps(body).encode()
            crafted.writestr(name, data)
    merged = client.post(
        f"/api/v1/orgs/{attacker['id']}/import/merge",
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, data={"resolutions": "{}"}, headers=headers,
    )
    assert merged.status_code == 200, merged.text
    assert any("victim@example.com" in w for w in merged.json()["warnings"])
    users = client.get(f"/api/v1/orgs/{attacker['id']}/users", headers=headers).json()
    assert all(u["email"] != "victim@example.com" for u in users)
