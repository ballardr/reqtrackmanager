"""Tests for typed, bidirectional requirement links (`RequirementLink`) —
create/list/delete, directional `display_name` correctness resolved from
both ends, and cross-project/cross-org IDOR."""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_project,
)


def _link_types(client, token, org_id):
    return {lt["forward_name"]: lt["id"] for lt in client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()}


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()


def test_create_link_shows_correct_display_name_from_both_ends(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Direction Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    source = _create_requirement(client, token, project["id"], component_id, category_id, "Source req")
    target = _create_requirement(client, token, project["id"], component_id, category_id, "Target req")
    link_types = _link_types(client, token, org["id"])

    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{source['id']}/links",
        json={"target_requirement_id": target["id"], "link_type_id": link_types["Derives from"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["direction"] == "outgoing"
    assert body["display_name"] == "Derives from"
    assert body["other_requirement_id"] == target["id"]
    assert body["other_requirement_unique_code"] == target["unique_code"]
    assert body["other_requirement_name"] == "Target req"

    from_source = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{source['id']}/links", headers=auth_headers(token)
    ).json()
    assert len(from_source) == 1
    assert from_source[0]["direction"] == "outgoing"
    assert from_source[0]["display_name"] == "Derives from"
    assert from_source[0]["other_requirement_id"] == target["id"]

    from_target = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{target['id']}/links", headers=auth_headers(token)
    ).json()
    assert len(from_target) == 1
    assert from_target[0]["direction"] == "incoming"
    assert from_target[0]["display_name"] == "Is the source of"
    assert from_target[0]["other_requirement_id"] == source["id"]
    assert from_target[0]["other_requirement_unique_code"] == source["unique_code"]


def test_symmetric_link_type_shows_same_name_from_both_ends(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Symmetric Link Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])

    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    )
    from_a = client.get(f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)).json()
    from_b = client.get(f"/api/v1/projects/{project['id']}/requirements/{b['id']}/links", headers=auth_headers(token)).json()
    assert from_a[0]["display_name"] == "Related to"
    assert from_b[0]["display_name"] == "Related to"


def test_delete_link_from_either_end(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Delete Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])

    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    ).json()

    # Deletable from the target's side, not just the source it was created from.
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{b['id']}/links/{link['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 204, resp.text
    assert client.get(f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)).json() == []


def test_cannot_link_using_a_link_type_from_another_org(client, admin_token):
    org_a, token_a = create_org_admin_in(client, admin_token, "Link Type Org A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Link Type Org B")
    project = create_project(client, token_a, org_a["id"])
    component_id, category_id = create_component_and_category(client, token_a, project["id"])
    a = _create_requirement(client, token_a, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token_a, project["id"], component_id, category_id, "B")
    other_org_link_type_id = _link_types(client, token_b, org_b["id"])["Related to"]

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": other_org_link_type_id},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 400


def test_cannot_delete_link_via_a_requirement_it_does_not_touch(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Delete IDOR Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    c = _create_requirement(client, token, project["id"], component_id, category_id, "C")
    link_types = _link_types(client, token, org["id"])

    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    ).json()

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{c['id']}/links/{link['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 404
