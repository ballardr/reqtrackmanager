"""Tests for project templates (C-E-04 default template, C-E-05 create from template)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def test_create_project_from_template_copies_configuration_and_requirements(client, admin_token, org_id):
    template = create_project(client, admin_token, org_id, "Template Project")
    component_id, category_id = create_component_and_category(client, admin_token, template["id"])
    client.post(
        f"/api/v1/projects/{template['id']}/requirements",
        json={"name": "Boot fast", "reasoning": "UX", "component_id": component_id, "category_id": category_id, "keywords": ["perf"]},
        headers=auth_headers(admin_token),
    )
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))

    resp = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org_id, "name": "New From Template", "summary": "",
            "template_project_id": template["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    new_project = resp.json()

    components = client.get(f"/api/v1/projects/{new_project['id']}/components", headers=auth_headers(admin_token)).json()
    assert len(components) == 1
    assert components[0]["prefix"] == "SW"

    requirements = client.get(f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert len(requirements) == 1
    assert requirements[0]["name"] == "Boot fast"
    assert requirements[0]["status"] == "draft"
    assert requirements[0]["keywords"] == ["perf"]
    assert requirements[0]["unique_code"] == "SW-PERF-001"

    groups = client.get(f"/api/v1/projects/{new_project['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    assert me["id"] in manager_group["member_user_ids"]


def test_cannot_use_non_template_project_as_template(client, admin_token, org_id):
    other = create_project(client, admin_token, org_id, "Not A Template")
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Should Fail", "summary": "", "template_project_id": other["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_set_default_template_requires_template_flag(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    resp = client.put(
        f"/api/v1/orgs/{org_id}/default-template", json={"project_id": project["id"]}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400

    client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=auth_headers(admin_token))
    resp = client.put(
        f"/api/v1/orgs/{org_id}/default-template", json={"project_id": project["id"]}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["default_template_project_id"] == project["id"]


def test_template_project_creator_does_not_auto_become_manager_but_fallback_applies(client, admin_token, org_id):
    """C-U-10's explicit exception: creating from a template does not add the
    creator to the copied groups (they inherit whatever the template's group
    membership was) — but if that leaves no manager, the creator is still
    added as a fallback so C-U-08 is never violated."""
    template = create_project(client, admin_token, org_id, "Bare Template")
    # Remove the admin (template creator) from the manager group so the
    # template ends up with zero managers, simulating a template whose
    # original manager has moved on.
    groups = client.get(f"/api/v1/projects/{template['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()

    other_manager_id = create_org_user(client, admin_token, org_id, "other_manager@example.com", role="project_creator")
    client.post(
        f"/api/v1/projects/{template['id']}/groups/{manager_group['id']}/members",
        json={"user_id": other_manager_id}, headers=auth_headers(admin_token),
    )
    client.delete(
        f"/api/v1/projects/{template['id']}/groups/{manager_group['id']}/members/{me['id']}",
        headers=auth_headers(admin_token),
    )
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))

    other_token = login(client, "other_manager@example.com", "Password123!")
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Cloned", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 201
    new_project = resp.json()

    new_groups = client.get(f"/api/v1/projects/{new_project['id']}/groups", headers=auth_headers(other_token)).json()
    new_manager_group = next(g for g in new_groups if g["role"] == "project_manager")
    # other_manager was copied over from the template's manager group.
    assert other_manager_id in new_manager_group["member_user_ids"]
