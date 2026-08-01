"""
Regression tests for vulnerabilities found and fixed in the security
hardening pass (see docs/decisions.md "Security hardening" section):

- IDOR: requirement links/comments and change-request comments not scoped
  to the project in the URL.
- Privilege escalation: adding/removing project-group members without
  verifying the group belongs to the project, and org-group members
  without verifying the group belongs to the organisation.
- Cross-tenant role grant: nesting an org group from a different
  organisation into a project group.
- ReportLab markup injection: unescaped user content passed to
  reportlab.platypus.Paragraph().
"""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    return resp.json()


def test_cannot_read_or_write_comments_on_requirement_in_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = create_project(client, admin_token, org_id, "Project B")
    comp_a, cat_a = create_component_and_category(client, admin_token, project_a["id"])
    requirement_b_comp, requirement_b_cat = create_component_and_category(client, admin_token, project_b["id"])
    requirement_b = _create_requirement(
        client, admin_token, project_b["id"], requirement_b_comp, requirement_b_cat, "Belongs to B"
    )

    # Attempt to read/write comments on B's requirement via A's URL prefix.
    resp = client.get(
        f"/api/v1/projects/{project_a['id']}/requirements/{requirement_b['id']}/comments",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/requirements/{requirement_b['id']}/comments",
        json={"body": "cross-project injection attempt"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404

    resp = client.get(
        f"/api/v1/projects/{project_a['id']}/requirements/{requirement_b['id']}/links",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_cannot_link_to_requirement_in_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = create_project(client, admin_token, org_id, "Project B")
    comp_a, cat_a = create_component_and_category(client, admin_token, project_a["id"])
    comp_b, cat_b = create_component_and_category(client, admin_token, project_b["id"])
    requirement_a = _create_requirement(client, admin_token, project_a["id"], comp_a, cat_a, "A req")
    requirement_b = _create_requirement(client, admin_token, project_b["id"], comp_b, cat_b, "B req")

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/requirements/{requirement_a['id']}/links",
        json={"target_requirement_id": requirement_b["id"], "link_type": "relates_to"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_cannot_read_or_write_comments_on_change_request_in_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = create_project(client, admin_token, org_id, "Project B")
    comp_b, cat_b = create_component_and_category(client, admin_token, project_b["id"])
    requirement_b = _create_requirement(client, admin_token, project_b["id"], comp_b, cat_b, "B req")
    cr_b = client.post(
        f"/api/v1/projects/{project_b['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement_b["id"],
            "proposed_name": "x", "reason": "y",
        },
        headers=auth_headers(admin_token),
    ).json()

    resp = client.get(
        f"/api/v1/projects/{project_a['id']}/change-requests/{cr_b['id']}/comments",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/change-requests/{cr_b['id']}/comments",
        json={"body": "cross-project injection attempt"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_cannot_join_project_group_belonging_to_another_project(client, admin_token, org_id):
    """A manager of project A must not be able to add themselves to project B's manager group."""
    create_org_user(client, admin_token, org_id, "attacker@example.com", role="project_creator")
    attacker_token = login(client, "attacker@example.com", "Password123!")

    project_a = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Attacker Project", "summary": ""},
        headers=auth_headers(attacker_token),
    ).json()
    project_b = create_project(client, admin_token, org_id, "Victim Project")

    groups_b = client.get(f"/api/v1/projects/{project_b['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group_b = next(g for g in groups_b if g["role"] == "project_manager")

    attacker_id = client.get("/api/v1/auth/me", headers=auth_headers(attacker_token)).json()["id"]
    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/groups/{manager_group_b['id']}/members",
        json={"user_id": attacker_id},
        headers=auth_headers(attacker_token),
    )
    assert resp.status_code == 404

    roles_b = client.get(f"/api/v1/projects/{project_b['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group_b_after = next(g for g in roles_b if g["role"] == "project_manager")
    assert attacker_id not in manager_group_b_after["member_user_ids"]


def test_cannot_nest_org_group_from_another_organization(client, admin_token, org_id):
    """An org group from organisation X must not be nestable into a project group in organisation Y."""
    other_org = client.post(
        "/api/v1/orgs", json={"name": "Other Org"}, headers=auth_headers(admin_token)
    ).json()
    other_group = client.post(
        f"/api/v1/orgs/{other_org['id']}/groups", json={"name": "Other Org Team"},
        headers=auth_headers(admin_token),
    ).json()

    project = create_project(client, admin_token, org_id, "My Project")
    groups = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/groups/{manager_group['id']}/members",
        json={"org_group_id": other_group["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_report_content_is_escaped_against_markup_injection(client, admin_token, org_id):
    """Requirement names/report markdown containing markup-like syntax must render as literal text,
    not be interpreted by ReportLab as a tag (the SSRF/local-file-read vector)."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": '<img src="http://169.254.169.254/" width="1" height="1"/>',
            "component_id": component_id, "category_id": category_id,
        },
        headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"pre_markdown": '<img src="file:///etc/passwd"/>', "post_markdown": ""},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
