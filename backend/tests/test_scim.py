"""Tests for inbound SCIM 2.0 provisioning (routers/scim.py) — bearer-token
auth, Users/Groups CRUD, group-membership PATCH, cross-org isolation, and
that it never touches nested-group edges or a banned account."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.organization import OrgGroup, OrgGroupMember
from tests.conftest import auth_headers, create_org_admin_in, create_project
from tests.test_access_review import _make_orphaned_user


def _generate_scim_token(client, admin_token, org_id) -> str:
    resp = client.post(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_scim_token_lifecycle(client, admin_token, org_id):
    status_resp = client.get(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(admin_token))
    assert status_resp.json() == {"enabled": False, "token_prefix": None}

    token = _generate_scim_token(client, admin_token, org_id)
    status_resp = client.get(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(admin_token))
    assert status_resp.json()["enabled"] is True
    assert status_resp.json()["token_prefix"] == token[:15]

    resp = client.get("/scim/v2/Users", headers=auth_headers(token))
    assert resp.status_code == 200

    revoke = client.delete(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(admin_token))
    assert revoke.status_code == 204
    resp = client.get("/scim/v2/Users", headers=auth_headers(token))
    assert resp.status_code == 401


def test_scim_requires_a_valid_bearer_token(client):
    resp = client.get("/scim/v2/Users")
    assert resp.status_code == 401
    resp = client.get("/scim/v2/Users", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_scim_create_user_provisions_and_grants_member_role(client, admin_token, org_id):
    token = _generate_scim_token(client, admin_token, org_id)
    resp = client.post(
        "/scim/v2/Users", json={"userName": "scim.new@example.com", "displayName": "SCIM New"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["userName"] == "scim.new@example.com"
    assert body["active"] is True

    # Idempotent: posting the same userName again resolves to the same user.
    resp2 = client.post("/scim/v2/Users", json={"userName": "scim.new@example.com"}, headers=auth_headers(token))
    assert resp2.json()["id"] == body["id"]

    listed = client.get('/scim/v2/Users?filter=userName eq "scim.new@example.com"', headers=auth_headers(token)).json()
    assert listed["totalResults"] == 1
    assert listed["Resources"][0]["id"] == body["id"]


def test_scim_patch_user_deactivates(client, admin_token, org_id):
    token = _generate_scim_token(client, admin_token, org_id)
    user = client.post("/scim/v2/Users", json={"userName": "scim.deactivate@example.com"}, headers=auth_headers(token)).json()

    resp = client.patch(
        f"/scim/v2/Users/{user['id']}",
        json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    fetched = client.get(f"/scim/v2/Users/{user['id']}", headers=auth_headers(token)).json()
    assert fetched["active"] is False


def test_scim_group_create_and_membership_patch_add_remove(client, admin_token, org_id):
    token = _generate_scim_token(client, admin_token, org_id)
    user = client.post("/scim/v2/Users", json={"userName": "scim.member@example.com"}, headers=auth_headers(token)).json()

    group = client.post("/scim/v2/Groups", json={"displayName": "SCIM Engineering"}, headers=auth_headers(token)).json()
    assert group["members"] == []

    resp = client.patch(
        f"/scim/v2/Groups/{group['id']}",
        json={"Operations": [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert {"value": user["id"]} in resp.json()["members"]

    resp = client.patch(
        f"/scim/v2/Groups/{group['id']}",
        json={"Operations": [{"op": "remove", "path": f"members[value eq \"{user['id']}\"]"}]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["members"] == []


def test_scim_group_replace_sets_membership_exactly(client, admin_token, org_id):
    token = _generate_scim_token(client, admin_token, org_id)
    user_a = client.post("/scim/v2/Users", json={"userName": "scim.a@example.com"}, headers=auth_headers(token)).json()
    user_b = client.post("/scim/v2/Users", json={"userName": "scim.b@example.com"}, headers=auth_headers(token)).json()
    group = client.post(
        "/scim/v2/Groups", json={"displayName": "SCIM Replace Group", "members": [{"value": user_a["id"]}]},
        headers=auth_headers(token),
    ).json()
    assert {m["value"] for m in group["members"]} == {user_a["id"]}

    resp = client.put(
        f"/scim/v2/Groups/{group['id']}",
        json={"displayName": "SCIM Replace Group", "members": [{"value": user_b["id"]}]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert {m["value"] for m in resp.json()["members"]} == {user_b["id"]}


def test_scim_delete_group_removes_it(client, admin_token, org_id):
    token = _generate_scim_token(client, admin_token, org_id)
    group = client.post("/scim/v2/Groups", json={"displayName": "SCIM Delete Me"}, headers=auth_headers(token)).json()
    resp = client.delete(f"/scim/v2/Groups/{group['id']}", headers=auth_headers(token))
    assert resp.status_code == 204
    assert client.get(f"/scim/v2/Groups/{group['id']}", headers=auth_headers(token)).status_code == 404


def test_scim_cannot_access_another_organisations_resources(client, admin_token, org_id):
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "SCIM Other Org")
    token = _generate_scim_token(client, admin_token, org_id)
    other_token = _generate_scim_token(client, other_admin_token, other_org["id"])

    group = client.post("/scim/v2/Groups", json={"displayName": "Mine"}, headers=auth_headers(token)).json()
    resp = client.get(f"/scim/v2/Groups/{group['id']}", headers=auth_headers(other_token))
    assert resp.status_code == 404

    user = client.post("/scim/v2/Users", json={"userName": "scim.isolated@example.com"}, headers=auth_headers(token)).json()
    resp = client.get(f"/scim/v2/Users/{user['id']}", headers=auth_headers(other_token))
    assert resp.status_code == 404


def test_scim_membership_sync_never_touches_nested_group_edges(client, admin_token, org_id):
    """A SCIM-managed group's nested-group edges (structural, admin-managed
    relationships — see the org-group-nesting feature) must survive any
    SCIM membership PATCH untouched."""
    token = _generate_scim_token(client, admin_token, org_id)
    group = client.post("/scim/v2/Groups", json={"displayName": "SCIM Nesting Parent"}, headers=auth_headers(token)).json()

    db = SessionLocal()
    try:
        child = OrgGroup(organization_id=org_id, name="Nested Under SCIM Group")
        db.add(child)
        db.flush()
        db.add(OrgGroupMember(org_group_id=group["id"], member_org_group_id=child.id))
        db.commit()
        child_id = child.id
    finally:
        db.close()

    user = client.post("/scim/v2/Users", json={"userName": "scim.nesting@example.com"}, headers=auth_headers(token)).json()
    client.patch(
        f"/scim/v2/Groups/{group['id']}",
        json={"Operations": [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}]},
        headers=auth_headers(token),
    )

    db = SessionLocal()
    try:
        nested_edges = db.scalars(
            select(OrgGroupMember.member_org_group_id).where(OrgGroupMember.org_group_id == group["id"])
        ).all()
        assert child_id in nested_edges
    finally:
        db.close()


def test_scim_delete_group_audit_event_records_the_access_it_cascaded_away(client, admin_token, org_id):
    """Hardening-review finding: deleting a group via SCIM cascades away
    whatever project access it granted through nesting (via DB-level
    ondelete=CASCADE on both OrgGroupMember and ProjectGroupMember) with
    zero prior audit trail beyond "a group was deleted" — this is the
    only group-deletion path in the app at all. Fixed by recording the
    affected ProjectGroup and parent-OrgGroup ids in the event detail
    before the cascade runs."""
    token = _generate_scim_token(client, admin_token, org_id)
    group = client.post("/scim/v2/Groups", json={"displayName": "SCIM Blast Radius"}, headers=auth_headers(token)).json()

    parent_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "SCIM Blast Radius Parent"}, headers=auth_headers(admin_token)
    ).json()
    nest_resp = client.post(
        f"/api/v1/orgs/{org_id}/groups/{parent_group['id']}/members",
        json={"member_org_group_id": group["id"]}, headers=auth_headers(admin_token),
    )
    assert nest_resp.status_code == 204, nest_resp.text

    project = create_project(client, admin_token, org_id, "SCIM Blast Radius Project")
    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "SCIM Blast Radius PG", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    pg_nest_resp = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": group["id"]}, headers=auth_headers(admin_token),
    )
    assert pg_nest_resp.status_code == 204, pg_nest_resp.text

    resp = client.delete(f"/scim/v2/Groups/{group['id']}", headers=auth_headers(token))
    assert resp.status_code == 204

    db = SessionLocal()
    try:
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "scim_deleted", AuditEvent.entity_id == group["id"])
        )
        assert event is not None
        assert event.detail["affected_project_group_ids"] == [project_group["id"]]
        assert event.detail["was_nested_inside_org_group_ids"] == [parent_group["id"]]
    finally:
        db.close()


def test_scim_group_patch_and_create_reject_malformed_member_ids_without_500ing(client, admin_token, org_id):
    """Hardening-review finding: a malformed `value` in a Groups
    payload (not a real UUID — a real IdP only ever echoes back an id
    this app itself issued, but the request body is untyped) previously
    hit a raw `UUID(...)` call and 500ed instead of being cleanly
    skipped, matching `_add_group_member`'s existing tolerance for an
    unrecognised-but-well-formed id."""
    token = _generate_scim_token(client, admin_token, org_id)

    created = client.post(
        "/scim/v2/Groups",
        json={"displayName": "SCIM Malformed Members", "members": [{"value": "not-a-uuid"}]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    assert created.json()["members"] == []

    group_id = created.json()["id"]
    patched = client.patch(
        f"/scim/v2/Groups/{group_id}",
        json={"Operations": [{"op": "add", "path": "members", "value": [{"value": "still-not-a-uuid"}]}]},
        headers=auth_headers(token),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["members"] == []

    filter_patched = client.patch(
        f"/scim/v2/Groups/{group_id}",
        json={"Operations": [{"op": "remove", "path": 'members[value eq "also-not-a-uuid"]'}]},
        headers=auth_headers(token),
    )
    assert filter_patched.status_code == 200, filter_patched.text


def test_scim_banned_user_cannot_be_reprovisioned(client, admin_token, org_id):
    banned_email = "scim.banned@example.com"
    # ban_orphaned_user requires zero org membership anywhere (I-M-05
    # clarification) — same _make_orphaned_user pattern test_access_review.py
    # and test_oidc_provisioning.py already use to reach a bannable state.
    user_id = _make_orphaned_user(client, admin_token, org_id, banned_email)
    resp = client.post(f"/api/v1/system/users/{user_id}/ban", headers=auth_headers(admin_token))
    assert resp.status_code in (200, 204), resp.text

    token = _generate_scim_token(client, admin_token, org_id)
    resp = client.post("/scim/v2/Users", json={"userName": banned_email}, headers=auth_headers(token))
    assert resp.status_code == 403
