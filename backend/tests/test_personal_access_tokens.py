"""Tests for Personal Access Tokens: creation/listing/revocation (self,
org-admin, server-admin scopes), org-scope enforcement layered on top of
real RBAC, and dynamic expiry (system default, per-org caps, retroactive
tightening). See docs/decisions.md's "Personal Access Tokens" section for
the design this verifies."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.database import engine as app_engine
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _create_pat(client, token, org_ids, requested_expires_at=None, name="test-token", project_ids=None):
    payload = {"name": name, "allowed_organization_ids": org_ids}
    if project_ids is not None:
        payload["allowed_project_ids"] = project_ids
    if requested_expires_at is not None:
        payload["requested_expires_at"] = requested_expires_at.isoformat()
    resp = client.post("/api/v1/me/pats", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _backdate(pat_id, *, created_at=None, expires_at_ceiling=None):
    with app_engine.begin() as conn:
        if created_at is not None:
            conn.execute(text("UPDATE personal_access_tokens SET created_at = :v WHERE id = :id"), {"v": created_at, "id": pat_id})
        if expires_at_ceiling is not None:
            conn.execute(
                text("UPDATE personal_access_tokens SET expires_at_ceiling = :v WHERE id = :id"),
                {"v": expires_at_ceiling, "id": pat_id},
            )


def _add_role(client, granter_token, org_id, user_id, role="member"):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles",
        json={"user_id": user_id, "role": role},
        headers=auth_headers(granter_token),
    )
    assert resp.status_code == 204, resp.text


def test_create_list_revoke_single_and_bulk(client, admin_token, org_id):
    pat = _create_pat(client, admin_token, [org_id])
    assert pat["token"].startswith("rtm_pat_")
    assert pat["allowed_organizations"][0]["id"] == org_id

    listed = client.get("/api/v1/me/pats", headers=auth_headers(admin_token)).json()
    assert any(p["id"] == pat["id"] for p in listed)
    assert "token" not in listed[0]  # never re-listed

    del_resp = client.delete(f"/api/v1/me/pats/{pat['id']}", headers=auth_headers(admin_token))
    assert del_resp.status_code == 204
    revoked = next(p for p in client.get("/api/v1/me/pats", headers=auth_headers(admin_token)).json() if p["id"] == pat["id"])
    assert revoked["revoked_at"] is not None

    pat2 = _create_pat(client, admin_token, [org_id])
    pat3 = _create_pat(client, admin_token, [org_id])
    bulk = client.post("/api/v1/me/pats/revoke-all", headers=auth_headers(admin_token))
    assert bulk.status_code == 200
    assert bulk.json()["revoked_count"] == 2  # pat2, pat3 (pat already revoked above, not recounted)
    for p in (pat2, pat3):
        row = next(x for x in client.get("/api/v1/me/pats", headers=auth_headers(admin_token)).json() if x["id"] == p["id"])
        assert row["revoked_at"] is not None


def test_cannot_create_pat_scoped_to_org_without_a_role(client, admin_token, org_id):
    org_b, _ = create_org_admin_in(client, admin_token, "PAT No Role Org")
    resp = client.post(
        "/api/v1/me/pats", json={"name": "x", "allowed_organization_ids": [org_b["id"]]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_pat_scoped_to_one_org_cannot_access_another(client, admin_token, org_id):
    """The org-scope restriction is layered on top of real RBAC: the caller
    genuinely holds org_admin in *both* orgs, so a 403 on org B can only be
    the PAT-scope check, not an ordinary permissions failure."""
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PAT Scope Org B")
    admin_user_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    _add_role(client, org_b_admin_token, org_b["id"], admin_user_id, role="org_admin")

    pat = _create_pat(client, admin_token, [org_id])
    pat_headers = auth_headers(pat["token"])

    ok = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=pat_headers)
    assert ok.status_code == 200

    blocked = client.get(f"/api/v1/orgs/{org_b['id']}/advanced-settings", headers=pat_headers)
    assert blocked.status_code == 403


def test_pat_scope_enforced_on_project_endpoints_too(client, admin_token, org_id):
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PAT Project Scope Org")
    admin_user_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    _add_role(client, org_b_admin_token, org_b["id"], admin_user_id, role="project_creator")
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = client.post(
        "/api/v1/projects", json={"organization_id": org_b["id"], "name": "Project B", "summary": ""},
        headers=auth_headers(admin_token),
    ).json()

    pat = _create_pat(client, admin_token, [org_id])
    pat_headers = auth_headers(pat["token"])

    assert client.get(f"/api/v1/projects/{project_a['id']}/requirements", headers=pat_headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project_b['id']}/requirements", headers=pat_headers).status_code == 403


def test_pat_optional_project_scope_restricts_within_allowed_org(client, admin_token, org_id):
    """`allowed_project_ids` is a *further* restriction layered on top of
    the org scope, not an alternative to it: both projects are in the same
    allowed org (so the org-scope check alone would pass either), but only
    the explicitly-listed one is reachable."""
    project_a = create_project(client, admin_token, org_id, "Scoped Project A")
    project_b = create_project(client, admin_token, org_id, "Scoped Project B")

    pat = _create_pat(client, admin_token, [org_id], project_ids=[project_a["id"]])
    assert pat["allowed_projects"] == [{"id": project_a["id"], "name": "Scoped Project A"}]
    pat_headers = auth_headers(pat["token"])

    ok = client.get(f"/api/v1/projects/{project_a['id']}/requirements", headers=pat_headers)
    assert ok.status_code == 200

    blocked = client.get(f"/api/v1/projects/{project_b['id']}/requirements", headers=pat_headers)
    assert blocked.status_code == 403
    assert "not scoped to this project" in blocked.json()["detail"].lower()


def test_pat_with_no_project_scope_reaches_every_project_in_its_orgs(client, admin_token, org_id):
    """Empty/omitted `allowed_project_ids` is the default, backward-
    compatible behaviour: no extra restriction beyond the org scope."""
    project_a = create_project(client, admin_token, org_id, "Unscoped Project A")
    project_b = create_project(client, admin_token, org_id, "Unscoped Project B")

    pat = _create_pat(client, admin_token, [org_id])
    assert pat["allowed_projects"] == []
    pat_headers = auth_headers(pat["token"])

    assert client.get(f"/api/v1/projects/{project_a['id']}/requirements", headers=pat_headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project_b['id']}/requirements", headers=pat_headers).status_code == 200


def test_cannot_create_pat_scoped_to_a_project_outside_the_selected_orgs(client, admin_token, org_id):
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PAT Project Cross Org")
    project_b = create_project(client, org_b_admin_token, org_b["id"], "Cross Org Project")

    resp = client.post(
        "/api/v1/me/pats",
        json={"name": "bad-scope", "allowed_organization_ids": [org_id], "allowed_project_ids": [project_b["id"]]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_cannot_create_pat_scoped_to_a_project_with_no_access(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "No Access Project")
    create_org_user(client, admin_token, org_id, "no-project-access@example.com", role="member")
    token = login(client, "no-project-access@example.com", "Password123!")

    resp = client.post(
        "/api/v1/me/pats",
        json={"name": "bad-scope", "allowed_organization_ids": [org_id], "allowed_project_ids": [project["id"]]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_max_lifetime_endpoint_matches_what_creation_would_produce(client, admin_token, org_id):
    resp = client.get(f"/api/v1/me/pats/max-lifetime?organization_ids={org_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    max_expires_at = datetime.fromisoformat(resp.json()["max_expires_at"])

    pat = _create_pat(client, admin_token, [org_id])
    # Both are computed as `now() + shortest cap` a moment apart — same
    # value in practice, allowing a small tolerance for the two `now()`
    # calls landing in different milliseconds.
    assert abs((datetime.fromisoformat(pat["expires_at"]) - max_expires_at).total_seconds()) < 5


def test_max_lifetime_endpoint_with_no_orgs_uses_system_default(client, admin_token):
    resp = client.get("/api/v1/me/pats/max-lifetime", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["max_expires_at"] is not None


def test_expiry_defaults_and_org_caps(client, admin_token, org_id):
    now = datetime.now(UTC)

    # No org cap set anywhere -> system default (90 days).
    pat_default = _create_pat(client, admin_token, [org_id])
    expires = datetime.fromisoformat(pat_default["expires_at"])
    assert abs((expires - now).total_seconds() - timedelta(days=90).total_seconds()) < 60

    # Org sets a tighter cap.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_use_tls": True, "pat_max_lifetime_days": 10},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    pat_capped = _create_pat(client, admin_token, [org_id])
    expires = datetime.fromisoformat(pat_capped["expires_at"])
    assert abs((expires - now).total_seconds() - timedelta(days=10).total_seconds()) < 60

    # Scoped to two orgs -> the shorter of the two caps wins.
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PAT Expiry Org B")
    admin_user_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    _add_role(client, org_b_admin_token, org_b["id"], admin_user_id, role="org_admin")
    client.put(
        f"/api/v1/orgs/{org_b['id']}/advanced-settings",
        json={"smtp_use_tls": True, "pat_max_lifetime_days": 3},
        headers=auth_headers(admin_token),
    )
    pat_multi = _create_pat(client, admin_token, [org_id, org_b["id"]])
    expires = datetime.fromisoformat(pat_multi["expires_at"])
    assert abs((expires - now).total_seconds() - timedelta(days=3).total_seconds()) < 60


def test_requested_expiry_beyond_cap_is_clamped_not_rejected(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_use_tls": True, "pat_max_lifetime_days": 10},
        headers=auth_headers(admin_token),
    )
    requested = datetime.now(UTC) + timedelta(days=365)
    pat = _create_pat(client, admin_token, [org_id], requested_expires_at=requested)
    expires = datetime.fromisoformat(pat["expires_at"])
    assert expires < requested
    assert abs((expires - datetime.now(UTC)).total_seconds() - timedelta(days=10).total_seconds()) < 60


def test_expired_pat_is_rejected(client, admin_token, org_id):
    pat = _create_pat(client, admin_token, [org_id])
    _backdate(pat["id"], expires_at_ceiling=datetime.now(UTC) - timedelta(hours=1))
    resp = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(pat["token"]))
    assert resp.status_code == 401


def test_lowering_org_cap_retroactively_expires_a_pat(client, admin_token, org_id):
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_use_tls": True, "pat_max_lifetime_days": 100},
        headers=auth_headers(admin_token),
    )
    old_pat = _create_pat(client, admin_token, [org_id])  # expires_at_ceiling ~= now + 100 days
    _backdate(old_pat["id"], created_at=datetime.now(UTC) - timedelta(days=10))

    # Tighten the org's cap: now + 5 days from a 10-days-ago creation is 5
    # days in the past — the stored, generous expires_at_ceiling never
    # changes, but the dynamically recomputed effective expiry does.
    client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"smtp_use_tls": True, "pat_max_lifetime_days": 5},
        headers=auth_headers(admin_token),
    )
    resp = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(old_pat["token"]))
    assert resp.status_code == 401

    # A brand-new token created *after* the tightened cap is unaffected —
    # it's freshly anchored to "now", well within the new 5-day cap.
    new_pat = _create_pat(client, admin_token, [org_id])
    resp = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(new_pat["token"]))
    assert resp.status_code == 200


def test_deactivated_users_pat_is_rejected_immediately(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "pat-owner@example.com", role="member")
    member_token = login(client, "pat-owner@example.com", "Password123!")
    pat = _create_pat(client, member_token, [org_id])
    member_id = client.get("/api/v1/auth/me", headers=auth_headers(member_token)).json()["id"]

    deactivate = client.post(f"/api/v1/orgs/{org_id}/users/{member_id}/deactivate", headers=auth_headers(admin_token))
    assert deactivate.status_code == 204

    resp = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(pat["token"]))
    assert resp.status_code == 401


def test_pat_rejected_for_server_admin_endpoint_even_for_a_real_server_admin(client, admin_token, org_id):
    pat = _create_pat(client, admin_token, [org_id])  # admin_token's user IS a real server admin
    resp = client.get("/api/v1/system/users", headers=auth_headers(pat["token"]))
    assert resp.status_code == 403


def test_org_admin_bulk_revoke_kills_every_matching_pat_but_leaves_others_alone(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "member1@example.com", role="member")
    member1_token = login(client, "member1@example.com", "Password123!")
    member1_id = client.get("/api/v1/auth/me", headers=auth_headers(member1_token)).json()["id"]

    org_c, org_c_admin_token = create_org_admin_in(client, admin_token, "Bulk Revoke Org C")
    _add_role(client, org_c_admin_token, org_c["id"], member1_id, role="member")

    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "Bulk Revoke Unrelated Org B")

    pat1 = _create_pat(client, member1_token, [org_id], name="pat1-single-org")
    pat2 = _create_pat(client, member1_token, [org_id, org_c["id"]], name="pat2-multi-org")
    pat3 = _create_pat(client, org_b_admin_token, [org_b["id"]], name="pat3-unrelated")

    bulk = client.post(f"/api/v1/orgs/{org_id}/pats/revoke-all", headers=auth_headers(admin_token))
    assert bulk.status_code == 200
    assert bulk.json()["revoked_count"] == 2

    assert client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(pat1["token"])).status_code == 401
    # pat2 is fully killed, not just descoped — even its org_c access is gone.
    assert client.get(f"/api/v1/orgs/{org_c['id']}/advanced-settings", headers=auth_headers(pat2["token"])).status_code == 401
    # pat3 (a genuinely unrelated org) is untouched.
    assert client.get(f"/api/v1/orgs/{org_b['id']}/advanced-settings", headers=auth_headers(pat3["token"])).status_code == 200

    forbidden_member = client.post(f"/api/v1/orgs/{org_id}/pats/revoke-all", headers=auth_headers(member1_token))
    assert forbidden_member.status_code == 403
    forbidden_other_admin = client.post(f"/api/v1/orgs/{org_id}/pats/revoke-all", headers=auth_headers(org_b_admin_token))
    assert forbidden_other_admin.status_code == 403


def test_server_admin_platform_wide_revoke_all(client, admin_token, org_id):
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "Platform Revoke Org B")
    pat_a = _create_pat(client, admin_token, [org_id])
    pat_b = _create_pat(client, org_b_admin_token, [org_b["id"]])

    forbidden = client.post("/api/v1/system/pats/revoke-all", headers=auth_headers(org_b_admin_token))
    assert forbidden.status_code == 403

    resp = client.post("/api/v1/system/pats/revoke-all", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["revoked_count"] == 2

    assert client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(pat_a["token"])).status_code == 401
    assert client.get(f"/api/v1/orgs/{org_b['id']}/advanced-settings", headers=auth_headers(pat_b["token"])).status_code == 401


def test_org_admin_per_token_list_revoke_descope(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "member2@example.com", role="member")
    member_token = login(client, "member2@example.com", "Password123!")
    member_id = client.get("/api/v1/auth/me", headers=auth_headers(member_token)).json()["id"]

    org_c, org_c_admin_token = create_org_admin_in(client, admin_token, "Per-token Org C")
    # org_admin (not just member) so the org_c-scoped assertion below, which
    # calls an org_admin-gated endpoint, isolates the PAT-scope check rather
    # than tripping over a plain role shortfall.
    _add_role(client, org_c_admin_token, org_c["id"], member_id, role="org_admin")

    multi_pat = _create_pat(client, member_token, [org_id, org_c["id"]], name="multi")
    single_pat = _create_pat(client, member_token, [org_id], name="single")

    listing = client.get(f"/api/v1/orgs/{org_id}/pats", headers=auth_headers(admin_token))
    assert listing.status_code == 200
    body = listing.json()
    multi_row = next(r for r in body if r["id"] == multi_pat["id"])
    assert multi_row["other_org_count"] == 1
    assert multi_row["user_email"] == "member2@example.com"
    # Confidentiality: org C's id/name must never appear anywhere in this org admin's view.
    assert org_c["id"] not in listing.text
    assert "Per-token Org C" not in listing.text

    # 404 (not disclosed) for a token this org has no relationship to.
    unrelated_pat = _create_pat(client, org_c_admin_token, [org_c["id"]], name="unrelated")
    not_found = client.post(f"/api/v1/orgs/{org_id}/pats/{unrelated_pat['id']}/revoke", headers=auth_headers(admin_token))
    assert not_found.status_code == 404

    # Descope: multi_pat loses org_id but stays valid for org_c.
    descope = client.post(f"/api/v1/orgs/{org_id}/pats/{multi_pat['id']}/descope", headers=auth_headers(admin_token))
    assert descope.status_code == 204
    assert client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(multi_pat["token"])).status_code == 403
    assert client.get(f"/api/v1/orgs/{org_c['id']}/advanced-settings", headers=auth_headers(multi_pat["token"])).status_code == 200

    # Descoping a single-org token's only org auto-revokes it.
    descope_to_zero = client.post(f"/api/v1/orgs/{org_id}/pats/{single_pat['id']}/descope", headers=auth_headers(admin_token))
    assert descope_to_zero.status_code == 204
    assert client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(single_pat["token"])).status_code == 401

    # Revoke (outright) also works on a single-org token.
    third_pat = _create_pat(client, member_token, [org_id], name="third")
    revoke = client.post(f"/api/v1/orgs/{org_id}/pats/{third_pat['id']}/revoke", headers=auth_headers(admin_token))
    assert revoke.status_code == 204
    assert client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(third_pat["token"])).status_code == 401


def test_pat_scope_enforced_on_file_download(client, admin_token, org_id):
    """Regression test: GET /api/v1/files/{id} resolves the caller via
    get_current_user_header_or_query (not one of rbac.py's require_*
    factories, since it needs to accept a ?token= query param for <img
    src> use) — a security-hardening review found this endpoint checked
    the caller's real RBAC role but never the Personal Access Token's own
    org scope, letting a token scoped to org A read files in org B that
    its owner happens to have genuine access to via their own account."""
    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "PAT File Scope Org B")
    admin_user_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    _add_role(client, org_b_admin_token, org_b["id"], admin_user_id, role="org_admin")

    upload = client.post(
        f"/api/v1/orgs/{org_b['id']}/resources",
        files={"file": ("secret.txt", b"org B confidential content", "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    # admin_token's user genuinely holds org_admin in both org_id and
    # org_b, so a 403 below can only be the PAT-scope check, not an
    # ordinary permissions failure.
    pat = _create_pat(client, admin_token, [org_id])

    blocked = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(pat["token"]))
    assert blocked.status_code == 403

    allowed_pat = _create_pat(client, admin_token, [org_b["id"]])
    ok = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(allowed_pat["token"]))
    assert ok.status_code == 200
    assert ok.content == b"org B confidential content"
