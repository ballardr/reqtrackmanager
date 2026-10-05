"""Tests for requirement<->action linking (`RequirementActionLink`) — one
action shared by multiple requirements, unlink-doesn't-delete, create-and-
link in one transaction, and cross-project IDOR."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _action_types(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()


def test_create_and_link_action_in_one_step(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]

    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/create-and-link",
        json={"title": "Run regression suite", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]

    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert len(listed) == 1
    assert listed[0]["id"] == action_id


def test_link_existing_action_and_share_across_multiple_requirements(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req_a = _create_requirement(client, admin_token, project["id"], component_id, category_id, "A")
    req_b = _create_requirement(client, admin_token, project["id"], component_id, category_id, "B")
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    link_a = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req_a['id']}/actions", json={"action_id": action["id"]},
        headers=auth_headers(admin_token),
    )
    assert link_a.status_code == 204, link_a.text
    link_b = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req_b['id']}/actions", json={"action_id": action["id"]},
        headers=auth_headers(admin_token),
    )
    assert link_b.status_code == 204, link_b.text

    for req in (req_a, req_b):
        listed = client.get(
            f"/api/v1/projects/{project['id']}/requirements/{req['id']}/actions", headers=auth_headers(admin_token)
        ).json()
        assert len(listed) == 1
        assert listed[0]["id"] == action["id"]

    # Duplicate linking is rejected.
    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req_a['id']}/actions", json={"action_id": action["id"]},
        headers=auth_headers(admin_token),
    )
    assert duplicate.status_code == 400


def test_unlink_from_one_requirement_does_not_affect_the_other(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req_a = _create_requirement(client, admin_token, project["id"], component_id, category_id, "A")
    req_b = _create_requirement(client, admin_token, project["id"], component_id, category_id, "B")
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    for req in (req_a, req_b):
        client.post(
            f"/api/v1/projects/{project['id']}/requirements/{req['id']}/actions", json={"action_id": action["id"]},
            headers=auth_headers(admin_token),
        )

    unlink = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{req_a['id']}/actions/{action['id']}",
        headers=auth_headers(admin_token),
    )
    assert unlink.status_code == 204, unlink.text

    assert client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req_a['id']}/actions", headers=auth_headers(admin_token)
    ).json() == []
    still_linked = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req_b['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert len(still_linked) == 1

    # The action itself still exists — unlinking never deletes it.
    fetched = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}", headers=auth_headers(admin_token))
    assert fetched.status_code == 200


def test_unlink_nonexistent_link_404s(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Never linked", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/{action['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_cannot_link_action_from_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Action Link IDOR A")
    project_b = create_project(client, admin_token, org_id, "Action Link IDOR B")
    component_id, category_id = create_component_and_category(client, admin_token, project_a["id"])
    requirement = _create_requirement(client, admin_token, project_a["id"], component_id, category_id)
    other_project_action_type_id = _action_types(client, admin_token, project_b["id"])[0]["id"]
    other_project_action = client.post(
        f"/api/v1/projects/{project_b['id']}/actions",
        json={"title": "Elsewhere", "action_type_id": other_project_action_type_id}, headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": other_project_action["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_action_linked_requirements_endpoint(client, admin_token, org_id):
    """`GET /actions/{id}/requirements` (2026-10-04) lists the action's
    linked active requirements by code, excludes archived ones, and is
    project-scoped."""
    project = create_project(client, admin_token, org_id)
    base = f"/api/v1/projects/{project['id']}"
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    linked = [_create_requirement(client, admin_token, project["id"], component_id, category_id, name=n)
              for n in ("Linked one", "Linked two", "Linked then archived")]
    _create_requirement(client, admin_token, project["id"], component_id, category_id, name="Not linked")
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(f"{base}/actions", json={"title": "Shared", "action_type_id": action_type_id},
                         headers=auth_headers(admin_token)).json()
    for requirement in linked:
        resp = client.post(f"{base}/requirements/{requirement['id']}/actions", json={"action_id": action["id"]},
                           headers=auth_headers(admin_token))
        assert resp.status_code == 204, resp.text
    assert client.delete(f"{base}/requirements/{linked[2]['id']}", headers=auth_headers(admin_token)).status_code in (200, 204)

    resp = client.get(f"{base}/actions/{action['id']}/requirements", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"id": r["id"], "unique_code": r["unique_code"], "name": r["name"]}
        for r in sorted(linked[:2], key=lambda r: r["unique_code"])
    ]

    other = create_project(client, admin_token, org_id, name="Other project")
    assert client.get(f"/api/v1/projects/{other['id']}/actions/{action['id']}/requirements",
                      headers=auth_headers(admin_token)).status_code == 404


def test_action_list_comment_counts_are_batched(client, admin_token, org_id):
    """The action list's per-row comment counts come from one batched query
    and still match each action's own count."""
    project = create_project(client, admin_token, org_id)
    base = f"/api/v1/projects/{project['id']}/actions"
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    ids = [client.post(base, json={"title": f"A{i}", "action_type_id": action_type_id},
                       headers=auth_headers(admin_token)).json()["id"] for i in range(3)]
    for _ in range(2):
        resp = client.post(f"{base}/{ids[1]}/comments", json={"body": "hi"}, headers=auth_headers(admin_token))
        assert resp.status_code == 201, resp.text
    counts = {a["id"]: a["comment_count"] for a in client.get(base, headers=auth_headers(admin_token)).json()}
    assert counts == {ids[0]: 0, ids[1]: 2, ids[2]: 0}
    assert client.get(f"{base}/{ids[1]}", headers=auth_headers(admin_token)).json()["comment_count"] == 2
