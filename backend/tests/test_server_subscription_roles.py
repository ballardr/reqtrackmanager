"""Tests for the two subscription server roles: `SUBSCRIPTION_MANAGER` ("Platform subscription manager") and
`SUBSCRIPTION_REMOVAL_AUTHORITY` ("Subscription removal authority").

Covers the allow-list (each role passes only its own routes), the exclusions (joining as an organisation
administrator and every deployment-wide setting stay with the server administrator), grant and revoke
rules, the personal-access-token refusal, the audit role, the caller's own access read, and a snapshot
that fails when a server-gated route is added or re-gated without being classified here.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app
from app.models.enums import ServerRole
from app.services.rbac import require_server_admin
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login

MANAGER = "subscription_manager"
REMOVER = "subscription_removal_authority"


def _grant(client, admin_token, user_id, role):
    resp = client.post(
        f"/api/v1/system/users/{user_id}/server-roles", json={"role": role}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text


def _holder(client, admin_token, org_id, role, email):
    """Creates a member holding only the given server role; returns their bearer token."""
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _grant(client, admin_token, user_id, role)
    return user_id, login(client, email, "Password123!")


def _new_org(client, token, name):
    resp = client.post("/api/v1/orgs", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _audit_detail(entity_id, action):
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT detail FROM audit_events WHERE entity_id = :e AND action = :a ORDER BY created_at DESC"),
            {"e": str(entity_id), "a": action},
        ).first()
    finally:
        db.close()
    assert row is not None
    return row[0]


# --- the manager's allow-list -------------------------------------------------------------------------------


def test_manager_creates_suspends_and_enables_but_cannot_delete(client, admin_token, org_id):
    _, token = _holder(client, admin_token, org_id, MANAGER, "sub_manager@example.com")

    created = _new_org(client, token, "Provisioned By Manager")
    assert client.get("/api/v1/orgs/creation-choices", headers=auth_headers(token)).status_code == 200

    resp = client.post(f"/api/v1/orgs/{created['id']}/disable", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    resp = client.post(f"/api/v1/orgs/{created['id']}/enable", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["is_active"] is True

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{created['id']}", json={"confirm_name": created["name"]}, headers=auth_headers(token)
    )
    assert resp.status_code == 403
    assert client.get(f"/api/v1/orgs/{created['id']}", headers=auth_headers(token)).status_code == 200


def test_manager_reads_the_directory_and_sets_entitlements(client, admin_token, org_id):
    _, token = _holder(client, admin_token, org_id, MANAGER, "sub_manager_dir@example.com")
    other = _new_org(client, admin_token, "Directory Target")

    listed = client.get("/api/v1/orgs", headers=auth_headers(token))
    assert listed.status_code == 200
    assert other["id"] in {o["id"] for o in listed.json()}
    assert client.get(f"/api/v1/orgs/{other['id']}", headers=auth_headers(token)).status_code == 200

    assert client.get("/api/v1/system/modules", headers=auth_headers(token)).status_code == 200
    resp = client.get(f"/api/v1/system/orgs/{other['id']}/module-entitlements", headers=auth_headers(token))
    assert resp.status_code == 200
    module_key = resp.json()[0]["module_key"]
    resp = client.put(
        f"/api/v1/system/orgs/{other['id']}/module-entitlements/{module_key}",
        json={"entitled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_manager_cannot_use_deployment_wide_module_settings(client, admin_token, org_id):
    """The entitlement policy and server defaults stay with the Module administrator."""
    _, token = _holder(client, admin_token, org_id, MANAGER, "sub_manager_policy@example.com")
    assert client.get("/api/v1/system/module-entitlement-policy", headers=auth_headers(token)).status_code == 403
    assert client.get("/api/v1/system/module-defaults", headers=auth_headers(token)).status_code == 403


# --- the removal authority's allow-list ----------------------------------------------------------------------


def test_remover_deletes_with_confirmation_but_cannot_provision(client, admin_token, org_id):
    _, token = _holder(client, admin_token, org_id, REMOVER, "sub_remover@example.com")
    target = _new_org(client, admin_token, "To Be Removed")

    assert client.post("/api/v1/orgs", json={"name": "Nope"}, headers=auth_headers(token)).status_code == 403
    assert client.post(f"/api/v1/orgs/{target['id']}/disable", headers=auth_headers(token)).status_code == 403
    assert client.get("/api/v1/orgs/creation-choices", headers=auth_headers(token)).status_code == 403
    assert client.get("/api/v1/system/modules", headers=auth_headers(token)).status_code == 403
    resp = client.put(
        f"/api/v1/system/orgs/{target['id']}/module-entitlements/anything", json={"entitled": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403

    # It reads the directory to find the target, and the name confirmation still applies.
    assert target["id"] in {o["id"] for o in client.get("/api/v1/orgs", headers=auth_headers(token)).json()}
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{target['id']}", json={"confirm_name": "wrong"}, headers=auth_headers(token)
    )
    assert resp.status_code == 400
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{target['id']}", json={"confirm_name": target["name"]}, headers=auth_headers(token)
    )
    assert resp.status_code == 204
    assert client.get(f"/api/v1/orgs/{target['id']}", headers=auth_headers(admin_token)).status_code == 404


def test_the_two_roles_are_independent(client, admin_token, org_id):
    """Holding both together gives both sets of powers; holding one never implies the other."""
    user_id, token = _holder(client, admin_token, org_id, MANAGER, "both_roles@example.com")
    assert client.get("/api/v1/system/access", headers=auth_headers(token)).json()["can_delete_organizations"] is False
    _grant(client, admin_token, user_id, REMOVER)
    access = client.get("/api/v1/system/access", headers=auth_headers(token)).json()
    assert access["can_create_organizations"] is True and access["can_delete_organizations"] is True
    assert access["can_administer_server"] is False


# --- exclusions ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [MANAGER, REMOVER])
def test_excluded_routes_are_refused_for_both_roles(client, admin_token, org_id, role):
    _, token = _holder(client, admin_token, org_id, role, f"excluded_{role}@example.com")
    headers = auth_headers(token)
    assert client.post(f"/api/v1/orgs/{org_id}/join-as-admin", headers=headers).status_code == 403
    assert client.get("/api/v1/system/users", headers=headers).status_code == 403
    assert client.put("/api/v1/system/signup-config", json={}, headers=headers).status_code == 403
    assert client.put("/api/v1/system/branding", json={}, headers=headers).status_code == 403
    assert client.put("/api/v1/system/file-uploads", json={"file_uploads_enabled": True}, headers=headers).status_code == 403
    assert client.post("/api/v1/system/pats/revoke-all", headers=headers).status_code == 403
    # No tenant content: a member-only organisation read of another organisation's records is refused.
    assert client.get(f"/api/v1/orgs/{org_id}/projects", headers=headers).status_code in (403, 404)


@pytest.mark.parametrize("role", [MANAGER, REMOVER])
def test_other_callers_get_403_on_subscription_actions(client, admin_token, org_id, role):
    """An organisation administrator, a member and a Module administrator hold neither role."""
    _, org_admin_token = create_org_admin_in(client, admin_token, "Org For Subscription Check")
    member_id = create_org_user(client, admin_token, org_id, "plain_member_sub@example.com", role="member")
    member_token = login(client, "plain_member_sub@example.com", "Password123!")
    _grant(client, admin_token, member_id, "module_administrator")
    module_admin_token = member_token  # same user: Module administrator only

    target = _new_org(client, admin_token, f"Target {role}")
    for token in (org_admin_token, module_admin_token):
        headers = auth_headers(token)
        assert client.post("/api/v1/orgs", json={"name": "x"}, headers=headers).status_code == 403
        assert client.post(f"/api/v1/orgs/{target['id']}/disable", headers=headers).status_code == 403
        resp = client.request(
            "DELETE", f"/api/v1/orgs/{target['id']}", json={"confirm_name": target["name"]}, headers=headers
        )
        assert resp.status_code == 403
        # A holder of neither role sees only organisations they belong to.
        assert target["id"] not in {o["id"] for o in client.get("/api/v1/orgs", headers=headers).json()}


# --- grant and revoke ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [MANAGER, REMOVER])
def test_only_a_server_admin_grants_or_revokes_and_roster_lists_it(client, admin_token, org_id, role):
    holder_id, holder_token = _holder(client, admin_token, org_id, role, f"grantee_{role}@example.com")
    target_id = create_org_user(client, admin_token, org_id, f"target_{role}@example.com", role="member")

    resp = client.post(
        f"/api/v1/system/users/{target_id}/server-roles", json={"role": role}, headers=auth_headers(holder_token)
    )
    assert resp.status_code == 403
    resp = client.delete(
        f"/api/v1/system/users/{holder_id}/server-roles/{role}", headers=auth_headers(holder_token)
    )
    assert resp.status_code == 403

    roster = {u["user_id"]: u for u in client.get("/api/v1/system/users", headers=auth_headers(admin_token)).json()}
    assert roster[holder_id]["server_roles"] == [role]
    assert _audit_detail(holder_id, "granted")["role"] == role


@pytest.mark.parametrize("role", [MANAGER, REMOVER])
def test_revoked_role_loses_access_on_the_next_request(client, admin_token, org_id, role):
    holder_id, token = _holder(client, admin_token, org_id, role, f"revoked_{role}@example.com")
    assert client.get("/api/v1/orgs/creation-choices" if role == MANAGER else "/api/v1/orgs",
                      headers=auth_headers(token)).status_code == 200
    resp = client.delete(f"/api/v1/system/users/{holder_id}/server-roles/{role}", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    assert client.get("/api/v1/orgs/creation-choices", headers=auth_headers(token)).status_code == 403
    access = client.get("/api/v1/system/access", headers=auth_headers(token)).json()
    assert access["roles"] == [] and access["can_view_organizations"] is False
    assert _audit_detail(holder_id, "revoked")["role"] == role


def test_personal_access_token_never_satisfies_a_subscription_role(client, admin_token, org_id):
    user_id, token = _holder(client, admin_token, org_id, MANAGER, "pat_holder@example.com")
    resp = client.post(
        "/api/v1/me/pats", json={"name": "t", "allowed_organization_ids": [org_id]}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    pat = resp.json()["token"]
    assert client.get("/api/v1/orgs/creation-choices", headers=auth_headers(pat)).status_code == 403
    access = client.get("/api/v1/system/access", headers=auth_headers(pat)).json()
    assert access["roles"] == [] and access["can_create_organizations"] is False


# --- audit, deletion behaviour and the counts-only read ------------------------------------------------------


def test_actions_are_audited_with_the_role_used(client, admin_token, org_id):
    _, manager_token = _holder(client, admin_token, org_id, MANAGER, "audit_manager@example.com")
    _, remover_token = _holder(client, admin_token, org_id, REMOVER, "audit_remover@example.com")

    created = _new_org(client, manager_token, "Audited Org")
    assert _audit_detail(created["id"], "created")["role_used"] == MANAGER
    client.post(f"/api/v1/orgs/{created['id']}/disable", headers=auth_headers(manager_token))
    assert _audit_detail(created["id"], "disabled")["role_used"] == MANAGER

    by_admin = _new_org(client, admin_token, "Audited By Admin")
    assert _audit_detail(by_admin["id"], "created")["role_used"] == "server_admin"

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{created['id']}", json={"confirm_name": created["name"]},
        headers=auth_headers(remover_token),
    )
    assert resp.status_code == 204
    detail = _audit_detail(created["id"], "deleted")
    assert detail == {"name": "Audited Org", "role_used": REMOVER}


def test_entitlement_write_audits_the_role(client, admin_token, org_id):
    _, token = _holder(client, admin_token, org_id, MANAGER, "audit_entitle@example.com")
    target = _new_org(client, admin_token, "Entitlement Audit")
    module_key = client.get("/api/v1/system/modules", headers=auth_headers(token)).json()[0]["module_key"]
    client.put(
        f"/api/v1/system/orgs/{target['id']}/module-entitlements/{module_key}",
        json={"entitled": False}, headers=auth_headers(token),
    )
    detail = _audit_detail(f"{target['id']}:{module_key}", "module.entitlement_updated")
    assert detail["role_used"] == MANAGER and detail["entitled"] is False


def test_directory_read_carries_no_tenant_content(client, admin_token, org_id):
    """The directory a subscription role reads is the same thin record a server administrator already reads."""
    _, token = _holder(client, admin_token, org_id, MANAGER, "counts_only@example.com")
    as_manager = client.get("/api/v1/orgs", headers=auth_headers(token)).json()
    as_admin = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()
    assert as_manager == as_admin
    forbidden = {"projects", "users", "members", "requirements", "email"}
    assert not forbidden & set(as_manager[0])


def test_access_read_reports_each_role(client, admin_token, org_id):
    admin_access = client.get("/api/v1/system/access", headers=auth_headers(admin_token)).json()
    assert admin_access["roles"] == ["server_admin"] and admin_access["can_administer_server"] is True

    _, token = _holder(client, admin_token, org_id, REMOVER, "access_remover@example.com")
    access = client.get("/api/v1/system/access", headers=auth_headers(token)).json()
    assert access == {
        "roles": [REMOVER], "can_view_organizations": True, "can_create_organizations": False,
        "can_delete_organizations": True, "can_manage_entitlements": False, "can_administer_server": False,
    }


# --- classification snapshot ---------------------------------------------------------------------------------


def _gates(dependant) -> set[str]:
    """The server-tier gates (`server_admin` or a role value) on a route's dependency tree."""
    found: set[str] = set()
    for dep in dependant.dependencies:
        call = dep.call
        if call is require_server_admin:
            found.add("server_admin")
        elif getattr(call, "__qualname__", "").startswith("require_server_role."):
            found |= {role.value for role in inspect.getclosurevars(call).nonlocals["allowed"]}
        found |= _gates(dep)
    return found


_ADMIN = frozenset({"server_admin"})
_ENTITLE = frozenset({"module_administrator", "subscription_manager"})
_MODULE = frozenset({"module_administrator"})
_NONE: frozenset[str] = frozenset()

# Every route of `routers/orgs/core.py` and `routers/system/` with its server-tier gate. A new route, or a
# re-gated one, fails the test until it is classified here, so a cross-tenant power cannot slip in unreviewed.
# An empty gate means a route with its own caller check (own membership, public, or a deployment read).
EXPECTED_GATES: dict[tuple[str, str], frozenset[str]] = {
    ("GET", "/api/v1/orgs/creation-choices"): frozenset({MANAGER}),
    ("POST", "/api/v1/orgs"): frozenset({MANAGER}),
    ("POST", "/api/v1/orgs/import"): frozenset({MANAGER}),
    ("POST", "/api/v1/orgs/{organization_id}/join-as-admin"): _ADMIN,
    ("POST", "/api/v1/orgs/{organization_id}/disable"): frozenset({MANAGER}),
    ("POST", "/api/v1/orgs/{organization_id}/enable"): frozenset({MANAGER}),
    ("DELETE", "/api/v1/orgs/{organization_id}"): frozenset({REMOVER}),
    ("GET", "/api/v1/orgs/{organization_id}/export"): _NONE,
    ("POST", "/api/v1/orgs/{organization_id}/import/preview"): _NONE,
    ("POST", "/api/v1/orgs/{organization_id}/import/merge"): _NONE,
    ("GET", "/api/v1/orgs"): _NONE,
    ("GET", "/api/v1/orgs/{organization_id}"): _NONE,
    ("PUT", "/api/v1/orgs/{organization_id}/name"): _NONE,
    ("GET", "/api/v1/orgs/{organization_id}/overview-stats"): _NONE,
    ("GET", "/api/v1/orgs/{organization_id}/projects"): _NONE,
    ("GET", "/api/v1/system/access"): _NONE,
    ("POST", "/api/v1/system/users/{user_id}/password-reset"): _ADMIN,
    ("POST", "/api/v1/system/credentials/force-reset"): _ADMIN,
    ("POST", "/api/v1/system/users"): _ADMIN,
    ("PUT", "/api/v1/system/users/{user_id}/server-admin"): _ADMIN,
    ("POST", "/api/v1/system/users/{user_id}/server-roles"): _ADMIN,
    ("DELETE", "/api/v1/system/users/{user_id}/server-roles/{role}"): _ADMIN,
    ("GET", "/api/v1/system/users"): _ADMIN,
    ("POST", "/api/v1/system/users/{user_id}/status"): _ADMIN,
    ("POST", "/api/v1/system/pats/revoke-all"): _ADMIN,
    ("GET", "/api/v1/system/branding"): _NONE,
    ("PUT", "/api/v1/system/branding"): _ADMIN,
    ("POST", "/api/v1/system/branding/image"): _ADMIN,
    ("DELETE", "/api/v1/system/branding/image"): _ADMIN,
    ("GET", "/api/v1/system/module-entitlement-policy"): _MODULE,
    ("PUT", "/api/v1/system/module-entitlement-policy"): _MODULE,
    ("GET", "/api/v1/system/modules"): _ENTITLE,
    ("GET", "/api/v1/system/orgs/{organization_id}/module-entitlements"): _ENTITLE,
    ("PUT", "/api/v1/system/orgs/{organization_id}/module-entitlements/{module_key}"): _ENTITLE,
    ("GET", "/api/v1/system/module-defaults"): _MODULE,
    ("PUT", "/api/v1/system/module-defaults/{module_key}"): _MODULE,
    ("POST", "/api/v1/system/module-defaults/apply"): _MODULE,
    ("GET", "/api/v1/system/modules/mcp-tools"): _NONE,
    ("GET", "/api/v1/system/version"): _NONE,
    ("GET", "/api/v1/system/client-config"): _NONE,
    ("GET", "/api/v1/system/storage-health"): _ADMIN,
    ("POST", "/api/v1/system/test-email"): _ADMIN,
    ("GET", "/api/v1/system/signup-config"): _NONE,
    ("PUT", "/api/v1/system/signup-config"): _ADMIN,
    ("PUT", "/api/v1/system/file-uploads"): _ADMIN,
    ("GET", "/api/v1/system/default-storage-quota"): _ADMIN,
    ("PUT", "/api/v1/system/default-storage-quota"): _ADMIN,
    ("GET", "/api/v1/orgs/{organization_id}/storage"): _NONE,
    ("PUT", "/api/v1/orgs/{organization_id}/storage"): frozenset({MANAGER}),
    ("GET", "/api/v1/system/record-sensitivity-policy"): _ADMIN,
    ("PUT", "/api/v1/system/record-sensitivity-policy/{tag}"): _ADMIN,
    ("GET", "/api/v1/system/report-fonts"): _ADMIN,
    ("GET", "/api/v1/system/report-fonts/choices"): _NONE,
    ("POST", "/api/v1/system/report-fonts/rescan"): _ADMIN,
    ("PUT", "/api/v1/system/report-fonts/{font_key}"): _ADMIN,
}


def test_every_server_gated_route_is_classified():
    observed: dict[tuple[str, str], frozenset[str]] = {}
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        module = endpoint.__module__
        if module in ("app.routers.orgs.core", "app.routers.orgs.storage") or module.startswith("app.routers.system"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                observed[(method, route.path)] = frozenset(_gates(route.dependant))
    assert observed == EXPECTED_GATES


def test_role_members_exist():
    assert ServerRole.SUBSCRIPTION_MANAGER.value == MANAGER
    assert ServerRole.SUBSCRIPTION_REMOVAL_AUTHORITY.value == REMOVER
    assert len(REMOVER) <= 30  # the `server_roles.role` column is VARCHAR(30)
