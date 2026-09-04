"""Tests for the module system's Phase 0 server-tier RBAC extension
(docs/compliance-module-plan.md): the new `ServerRole.MODULE_ADMINISTRATOR`
role, its grant/revoke endpoints, `services.rbac.require_server_role`'s
composition with `User.is_server_admin`, and the deployment-wide default
module entitlement policy setting it gates."""

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login


def _grant_module_administrator(client, admin_token, user_id):
    resp = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": "module_administrator"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def test_server_admin_can_grant_and_revoke_module_administrator(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "future_module_admin@example.com", role="member")

    _grant_module_administrator(client, admin_token, user_id)
    resp = client.get("/api/v1/system/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["is_module_administrator"] is True

    resp = client.delete(
        f"/api/v1/system/users/{user_id}/server-roles/module_administrator", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204
    resp = client.get("/api/v1/system/users", headers=auth_headers(admin_token))
    by_id = {u["user_id"]: u for u in resp.json()}
    assert by_id[user_id]["is_module_administrator"] is False


def test_granting_module_administrator_twice_is_idempotent(client, admin_token, org_id):
    """Mirrors `assign_org_role`'s own existing-row check — a second grant
    of the same role must not raise (e.g. a UNIQUE constraint violation)."""
    user_id = create_org_user(client, admin_token, org_id, "double_grant@example.com", role="member")
    _grant_module_administrator(client, admin_token, user_id)
    _grant_module_administrator(client, admin_token, user_id)


def test_revoking_ungranted_module_administrator_is_noop(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "never_granted@example.com", role="member")
    resp = client.delete(
        f"/api/v1/system/users/{user_id}/server-roles/module_administrator", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204


def test_granting_server_admin_via_server_roles_endpoint_is_rejected(client, admin_token, org_id):
    """`ServerRole.SERVER_ADMIN` is never written as a `UserServerRole` row
    — `User.is_server_admin` stays its sole source of truth."""
    user_id = create_org_user(client, admin_token, org_id, "not_this_way@example.com", role="member")
    resp = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": "server_admin"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_org_admin_cannot_grant_module_administrator(client, admin_token, org_id):
    """A genuine org admin (not a server admin) must be rejected — this is a
    server-tier grant, org role has no bearing on it."""
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For Module Admin Grant Check")
    user_id = create_org_user(client, admin_token, org_id, "target_for_org_admin@example.com", role="member")
    resp = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": "module_administrator"},
        headers=auth_headers(other_admin_token),
    )
    assert resp.status_code == 403


def test_module_administrator_cannot_grant_roles_to_others(client, admin_token, org_id):
    """Privilege-escalation-safe pattern: a narrower role (MODULE_ADMINISTRATOR)
    can never grant itself or others a role — only a genuine SERVER_ADMIN
    may call the grant/revoke endpoints, mirroring `assign_org_role`'s own
    `ORG_ADMIN`-only gating."""
    grantee_id = create_org_user(client, admin_token, org_id, "module_admin_actor@example.com", role="member")
    _grant_module_administrator(client, admin_token, grantee_id)
    grantee_token = login(client, "module_admin_actor@example.com", "Password123!")

    other_user_id = create_org_user(client, admin_token, org_id, "escalation_target@example.com", role="member")
    resp = client.post(
        f"/api/v1/system/users/{other_user_id}/server-roles", json={"role": "module_administrator"},
        headers=auth_headers(grantee_token),
    )
    assert resp.status_code == 403


def test_module_administrator_can_read_and_update_entitlement_policy(client, admin_token, org_id):
    """`require_server_role(MODULE_ADMINISTRATOR)` grants access to the
    settings surface it exists to gate, without needing full server-admin
    power."""
    user_id = create_org_user(client, admin_token, org_id, "policy_admin@example.com", role="member")
    _grant_module_administrator(client, admin_token, user_id)
    token = login(client, "policy_admin@example.com", "Password123!")

    resp = client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["default_module_entitlement_policy"] == "open"

    resp = client.put(
        "/api/v1/system/module-entitlement-policy", json={"default_module_entitlement_policy": "closed"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["default_module_entitlement_policy"] == "closed"

    resp = client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(admin_token))
    assert resp.json()["default_module_entitlement_policy"] == "closed"


def test_server_admin_can_access_entitlement_policy_without_explicit_grant(client, admin_token, org_id):
    """`require_server_role` composes with `is_server_admin`: a genuine
    server admin passes with no `UserServerRole` row at all."""
    resp = client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(admin_token))
    assert resp.status_code == 200


def test_plain_member_cannot_access_entitlement_policy(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "plain_for_policy@example.com", role="member")
    token = login(client, "plain_for_policy@example.com", "Password123!")
    resp = client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(token))
    assert resp.status_code == 403
    resp = client.put(
        "/api/v1/system/module-entitlement-policy", json={"default_module_entitlement_policy": "closed"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_org_admin_alone_cannot_access_entitlement_policy(client, admin_token, org_id):
    """Org admin is a different tier entirely — must not implicitly satisfy
    a server-tier role check."""
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For Entitlement Policy Check")
    resp = client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(other_admin_token))
    assert resp.status_code == 403
