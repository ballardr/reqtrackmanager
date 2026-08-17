"""Tests for org-definable, bidirectional requirement link types
(`RequirementLinkTypeDefinition`) — creation seeds 12 defaults, and the
shared §4.0 rename/reorder/delete-with-reassignment rules
(`services.definitions`), plus the link-type-specific rename (both
directional names at once) and reassignment (`reassign_verb="convert"`,
since it changes a link's asserted meaning)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def _link_types(client, token, org_id):
    return client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()


def test_new_org_is_seeded_with_twelve_default_link_types(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Type Seed Org")
    link_types = _link_types(client, token, org["id"])
    assert len(link_types) == 12
    names = {lt["forward_name"] for lt in link_types}
    assert {"Related to", "Derives from", "Satisfies", "Depends on", "Conflicts with"} <= names
    related = next(lt for lt in link_types if lt["forward_name"] == "Related to")
    assert related["reverse_name"] == "Related to"  # symmetric
    derives = next(lt for lt in link_types if lt["forward_name"] == "Derives from")
    assert derives["reverse_name"] == "Is the source of"  # asymmetric


def test_create_rename_move_link_type(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Type CRUD Org")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/link-types", json={"forward_name": "Blocks", "reverse_name": "Is blocked by"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    link_type_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/orgs/{org['id']}/link-types/{link_type_id}",
        json={"forward_name": "Prevents", "reverse_name": "Is prevented by"}, headers=auth_headers(token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["forward_name"] == "Prevents"
    assert renamed.json()["reverse_name"] == "Is prevented by"

    duplicate = client.post(
        f"/api/v1/orgs/{org['id']}/link-types", json={"forward_name": "Related to", "reverse_name": "x"},
        headers=auth_headers(token),
    )
    assert duplicate.status_code == 400

    moved = client.post(
        f"/api/v1/orgs/{org['id']}/link-types/{link_type_id}/move", json={"direction": "up"},
        headers=auth_headers(token),
    )
    assert moved.status_code == 200


def test_cannot_delete_last_remaining_link_type_even_if_unused(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Type Min Count Org")
    link_types = _link_types(client, token, org["id"])
    for lt in link_types[1:]:
        resp = client.delete(f"/api/v1/orgs/{org['id']}/link-types/{lt['id']}", headers=auth_headers(token))
        assert resp.status_code == 204, resp.text

    last = _link_types(client, token, org["id"])
    assert len(last) == 1
    resp = client.delete(f"/api/v1/orgs/{org['id']}/link-types/{last[0]['id']}", headers=auth_headers(token))
    assert resp.status_code == 409


def test_deleting_in_use_link_type_without_reassign_id_409s_with_count(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Type Reassign Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = {lt["forward_name"]: lt["id"] for lt in _link_types(client, token, org["id"])}

    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Depends on"]},
        headers=auth_headers(token),
    )

    resp = client.delete(f"/api/v1/orgs/{org['id']}/link-types/{link_types['Depends on']}", headers=auth_headers(token))
    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]


def test_deleting_in_use_link_type_with_reassign_id_converts_links_then_deletes(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Link Type Reassign Success Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = {lt["forward_name"]: lt["id"] for lt in _link_types(client, token, org["id"])}

    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Depends on"]},
        headers=auth_headers(token),
    ).json()

    resp = client.delete(
        f"/api/v1/orgs/{org['id']}/link-types/{link_types['Depends on']}",
        params={"reassign_to_id": link_types["Related to"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text

    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)
    ).json()
    updated = next(item for item in listed if item["id"] == link["id"])
    assert updated["link_type_id"] == link_types["Related to"]
    remaining_ids = {lt["id"] for lt in _link_types(client, token, org["id"])}
    assert link_types["Depends on"] not in remaining_ids


def test_reassign_to_id_must_be_in_same_org_and_not_self(client, admin_token):
    # reassign_to_id is only validated once the item being deleted is
    # actually in use (§4.0: "Not in use -> deletes immediately,
    # reassign_to_id ignored if passed") — so this test creates a link
    # using the type first, to exercise the validated path.
    org_a, token_a = create_org_admin_in(client, admin_token, "Link Reassign Org A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Link Reassign Org B")
    link_types_a = {lt["forward_name"]: lt["id"] for lt in _link_types(client, token_a, org_a["id"])}
    link_types_b = {lt["forward_name"]: lt["id"] for lt in _link_types(client, token_b, org_b["id"])}
    project = create_project(client, token_a, org_a["id"])
    component_id, category_id = create_component_and_category(client, token_a, project["id"])
    a = _create_requirement(client, token_a, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token_a, project["id"], component_id, category_id, "B")
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types_a["Depends on"]},
        headers=auth_headers(token_a),
    )

    resp = client.delete(
        f"/api/v1/orgs/{org_a['id']}/link-types/{link_types_a['Depends on']}",
        params={"reassign_to_id": link_types_a["Depends on"]}, headers=auth_headers(token_a),
    )
    assert resp.status_code == 400

    resp = client.delete(
        f"/api/v1/orgs/{org_a['id']}/link-types/{link_types_a['Depends on']}",
        params={"reassign_to_id": link_types_b["Related to"]}, headers=auth_headers(token_a),
    )
    assert resp.status_code == 400
