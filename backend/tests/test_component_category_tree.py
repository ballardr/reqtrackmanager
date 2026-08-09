"""Tests for the component/category tree (C-G-07): a category belongs to
exactly one component, not to the project independently — components and
categories are no longer two flat, orthogonal lists."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _create_component(client, token, project_id, name, prefix):
    resp = client.post(
        f"/api/v1/projects/{project_id}/components", json={"name": name, "prefix": prefix}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_category(client, token, project_id, component_id, name, prefix):
    return client.post(
        f"/api/v1/projects/{project_id}/categories",
        json={"name": name, "prefix": prefix, "component_id": component_id},
        headers=auth_headers(token),
    )


def test_category_creation_requires_a_component_id(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/categories", json={"name": "General"}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 422


def test_category_created_nested_under_its_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component = _create_component(client, admin_token, project["id"], "Core", "CORE")
    resp = _create_category(client, admin_token, project["id"], component["id"], "General", "GEN")
    assert resp.status_code == 201, resp.text
    assert resp.json()["component_id"] == component["id"]


def test_category_creation_rejects_a_component_from_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = create_project(client, admin_token, org_id, "Project B")
    component_a = _create_component(client, admin_token, project_a["id"], "Core", "CORE")
    resp = _create_category(client, admin_token, project_b["id"], component_a["id"], "General", "GEN")
    assert resp.status_code == 400


def test_category_prefix_is_unique_per_component_not_per_project(client, admin_token, org_id):
    """Two different components can each have their own "GEN" category —
    the tree scopes prefix uniqueness to the parent component."""
    project = create_project(client, admin_token, org_id)
    core = _create_component(client, admin_token, project["id"], "Core", "CORE")
    other = _create_component(client, admin_token, project["id"], "Other", "OTH")

    assert _create_category(client, admin_token, project["id"], core["id"], "General", "GEN").status_code == 201
    assert _create_category(client, admin_token, project["id"], other["id"], "General", "GEN").status_code == 201
    # But a duplicate prefix under the *same* component is still rejected.
    dup = _create_category(client, admin_token, project["id"], core["id"], "General Again", "GEN")
    assert dup.status_code == 400


def test_requirement_creation_rejects_a_category_from_a_different_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    core = _create_component(client, admin_token, project["id"], "Core", "CORE")
    other = _create_component(client, admin_token, project["id"], "Other", "OTH")
    core_category = _create_category(client, admin_token, project["id"], core["id"], "General", "GEN").json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Mismatched", "component_id": other["id"], "category_id": core_category["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"].lower()


def test_move_category_only_reorders_within_its_own_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    core = _create_component(client, admin_token, project["id"], "Core", "CORE")
    other = _create_component(client, admin_token, project["id"], "Other", "OTH")

    core_first = _create_category(client, admin_token, project["id"], core["id"], "First", "F1").json()
    core_second = _create_category(client, admin_token, project["id"], core["id"], "Second", "F2").json()
    other_only = _create_category(client, admin_token, project["id"], other["id"], "Solo", "S1").json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/categories/{core_second['id']}/move",
        json={"direction": "up"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    categories = client.get(f"/api/v1/projects/{project['id']}/categories", headers=auth_headers(admin_token)).json()
    by_id = {c["id"]: c for c in categories}
    # core_second moved ahead of core_first...
    assert by_id[core_second["id"]]["sort_order"] < by_id[core_first["id"]]["sort_order"]
    # ...and the other component's lone category was never touched.
    assert by_id[other_only["id"]]["sort_order"] == 0


def test_csv_import_resolves_category_within_the_named_component(client, admin_token, org_id):
    """Two components each have their own "GEN" category — the importer
    must resolve the one under the *named* component, not whichever
    happens to be found first."""
    project = create_project(client, admin_token, org_id)
    core = _create_component(client, admin_token, project["id"], "Core", "CORE")
    other = _create_component(client, admin_token, project["id"], "Other", "OTH")
    _create_category(client, admin_token, project["id"], core["id"], "General", "GEN")
    _create_category(client, admin_token, project["id"], other["id"], "General", "GEN")

    csv_content = "name,reasoning,component_prefix,category_prefix,level,target_version\nFrom Other,,OTH,GEN,requirement,\n"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 1
    assert resp.json()["errors"] == []

    requirements = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    imported = next(r for r in requirements if r["name"] == "From Other")
    assert imported["component_id"] == other["id"]


def test_change_request_rejects_mismatched_proposed_component_and_category(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    core = _create_component(client, admin_token, project["id"], "Core", "CORE")
    other = _create_component(client, admin_token, project["id"], "Other", "OTH")
    core_category = _create_category(client, admin_token, project["id"], core["id"], "General", "GEN").json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "new_requirement", "proposed_name": "New Thing", "proposed_reasoning": "x",
            "proposed_component_id": other["id"], "proposed_category_id": core_category["id"], "reason": "test",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_backward_compatible_shared_helper_still_produces_a_nested_category(client, admin_token, org_id):
    """The shared `create_component_and_category` test fixture helper
    (used across many other test files) now nests the category under the
    component it creates."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    category = client.get(f"/api/v1/projects/{project['id']}/categories", headers=auth_headers(admin_token)).json()
    match = next(c for c in category if c["id"] == category_id)
    assert match["component_id"] == component_id
