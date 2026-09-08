"""Tests for `GET /orgs/{organization_id}/overview-stats`
(compliance-module-plan.md Phase 19 — "Organisation Overview" page).

Covers the permission boundary (no bypass for a caller with no genuine org
role, matching I-M-05) and the product decision recorded in
docs/decisions.md's "Compliance module, human review follow-ups" entry: an
org admin sees real, unfiltered org-wide totals; a plain member sees counts
scoped to what they can actually see (`_accessible_project_ids`); the
member count itself is never scoped.
"""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _assign_project_role(client, admin_token, project_id, user_id, role="member"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles",
        json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _create_requirement(client, admin_token, project_id):
    component_id, category_id = create_component_and_category(client, admin_token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "A requirement", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _attach_file(client, admin_token, project_id, requirement_id, filename="attachment.txt"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/files",
        files={"file": (filename, b"hello world", "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_org_resource(client, admin_token, org_id, filename="resource.txt", content=b"shared resource"):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/resources",
        files={"file": (filename, content, "text/plain")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_overview_stats_requires_a_genuine_org_role(client, admin_token, org_id):
    """No I-M-05 bypass: a user with zero role in this org is rejected, the
    same as every other `require_org_role`-gated endpoint — this is not the
    one documented server-admin carve-out."""
    outsider_org, _ = (
        client.post("/api/v1/orgs", json={"name": "Outsider Org"}, headers=auth_headers(admin_token)).json(),
        None,
    )
    outsider_email = "outsider_stats@example.com"
    create_org_user(client, admin_token, outsider_org["id"], outsider_email, role="member")
    outsider_token = login(client, outsider_email, "Password123!")

    resp = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(outsider_token))
    assert resp.status_code == 403


def test_org_admin_sees_real_unfiltered_totals(client, admin_token, org_id):
    """The bootstrap admin is a genuine `org_admin` of the default org
    (`run_bootstrap`) — they must see every project in the org, including
    ones they hold no project-level role on themselves (default project
    visibility is `ONLY_SPECIFIED`, so this also proves the admin branch
    isn't just falling back to `_accessible_project_ids` by coincidence)."""
    project_a = create_project(client, admin_token, org_id, name="Overview Stats Project A")
    project_b = create_project(client, admin_token, org_id, name="Overview Stats Project B")
    _create_requirement(client, admin_token, project_a["id"])
    _create_requirement(client, admin_token, project_b["id"])

    resp = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["is_full_org_total"] is True
    assert stats["project_count"] >= 2
    assert stats["requirement_count"] >= 2


def test_plain_member_sees_only_their_own_accessible_totals(client, admin_token, org_id):
    """A plain member granted a role on only one of two projects must see
    counts scoped to that one project, not the org's real totals — the
    user's own correction recorded in docs/decisions.md: "a user can't see
    the number of all projects if they themselves can't see them all."""
    visible_project = create_project(client, admin_token, org_id, name="Member Visible Project")
    hidden_project = create_project(client, admin_token, org_id, name="Member Hidden Project")
    visible_requirement_id = _create_requirement(client, admin_token, visible_project["id"])
    _create_requirement(client, admin_token, hidden_project["id"])

    member_email = "scoped_member@example.com"
    member_id = create_org_user(client, admin_token, org_id, member_email, role="member")
    _assign_project_role(client, admin_token, visible_project["id"], member_id, role="member")
    member_token = login(client, member_email, "Password123!")

    admin_stats = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(admin_token)).json()
    member_stats = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(member_token)).json()

    assert member_stats["is_full_org_total"] is False
    assert member_stats["project_count"] == 1
    assert member_stats["requirement_count"] == 1
    assert member_stats["project_count"] < admin_stats["project_count"]
    assert member_stats["requirement_count"] < admin_stats["requirement_count"]

    # Member count is never scoped (list_org_users's own permission already
    # lets any member browse the full directory) — admin and member see the
    # exact same figure.
    assert member_stats["member_count"] == admin_stats["member_count"]

    _ = visible_requirement_id  # exercised via the attachment test below


def test_plain_member_file_size_scoped_to_org_resources_and_accessible_attachments(client, admin_token, org_id):
    """A member's file-size total includes org-wide shared resources (visible
    to any member regardless of per-project access) and attachments on
    requirements within their own accessible-project set, but not an
    attachment living only on a project they can't see."""
    visible_project = create_project(client, admin_token, org_id, name="File Scope Visible Project")
    hidden_project = create_project(client, admin_token, org_id, name="File Scope Hidden Project")
    visible_requirement_id = _create_requirement(client, admin_token, visible_project["id"])
    hidden_requirement_id = _create_requirement(client, admin_token, hidden_project["id"])

    org_resource = _upload_org_resource(client, admin_token, org_id, content=b"x" * 100)
    visible_attachment = _attach_file(client, admin_token, visible_project["id"], visible_requirement_id, filename="visible.txt")
    _attach_file(client, admin_token, hidden_project["id"], hidden_requirement_id, filename="hidden.txt")

    member_email = "file_scoped_member@example.com"
    member_id = create_org_user(client, admin_token, org_id, member_email, role="member")
    _assign_project_role(client, admin_token, visible_project["id"], member_id, role="member")
    member_token = login(client, member_email, "Password123!")

    member_stats = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(member_token)).json()
    admin_stats = client.get(f"/api/v1/orgs/{org_id}/overview-stats", headers=auth_headers(admin_token)).json()

    expected_visible_total = org_resource["size_bytes"] + visible_attachment["size_bytes"]
    assert member_stats["total_file_size_bytes"] == expected_visible_total
    assert admin_stats["total_file_size_bytes"] > member_stats["total_file_size_bytes"]
