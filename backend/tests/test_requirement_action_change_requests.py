"""Tests for the ADD_ACTION change request kind (2026-08 UX audit roadmap
item 514): once a requirement is locked (APPROVED/COMPLETED), adding or
linking an action must go through an approved change request, the same
change-request-only-once-locked rule the requirement's own fields already
follow — see `services.requirements.LOCKED_STATUSES` and
`routers.change_requests.create_change_request`'s ADD_ACTION branch."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _action_types(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()


def _create_requirement(client, admin_token, project_id, component_id, category_id, name="Boot fast"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve_requirement(client, admin_token, project_id, requirement_id):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/approve", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit_and_decide(client, admin_token, project_id, cr_id, approve=True):
    submitted = client.post(
        f"/api/v1/projects/{project_id}/change-requests/{cr_id}/submit", headers=auth_headers(admin_token)
    )
    assert submitted.status_code == 200, submitted.text
    decision = client.post(
        f"/api/v1/projects/{project_id}/change-requests/{cr_id}/decide",
        json={"approve": approve, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200, decision.text
    return decision.json()


def _setup_locked_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _approve_requirement(client, admin_token, project["id"], requirement["id"])
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    return project, requirement, action_type_id


def test_create_and_link_action_directly_rejected_once_locked(client, admin_token, org_id):
    project, requirement, action_type_id = _setup_locked_requirement(client, admin_token, org_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/create-and-link",
        json={"title": "Run regression suite", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_link_existing_action_directly_rejected_once_locked(client, admin_token, org_id):
    project, requirement, action_type_id = _setup_locked_requirement(client, admin_token, org_id)
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_create_and_link_action_still_works_directly_while_unlocked(client, admin_token, org_id):
    """The gate only applies once locked — a still-draft requirement's
    Actions card keeps working exactly as before."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/create-and-link",
        json={"title": "Run regression suite", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text


def test_add_action_change_request_rejected_against_a_still_draft_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_title": "Run regression suite", "proposed_action_type_id": action_type_id,
            "reason": "found a gap during review",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_add_action_change_request_rejects_both_or_neither_of_link_and_create(client, admin_token, org_id):
    project, requirement, action_type_id = _setup_locked_requirement(client, admin_token, org_id)
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    neither = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "add_action", "requirement_id": requirement["id"], "reason": "x"},
        headers=auth_headers(admin_token),
    )
    assert neither.status_code == 400, neither.text

    both = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"],
            "proposed_action_title": "Run regression suite", "proposed_action_type_id": action_type_id,
            "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert both.status_code == 400, both.text


def test_add_action_change_request_creates_and_links_a_new_action_on_approval(client, admin_token, org_id):
    project, requirement, action_type_id = _setup_locked_requirement(client, admin_token, org_id)

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_title": "Run regression suite", "proposed_action_description": "Full suite, not smoke",
            "proposed_action_type_id": action_type_id,
            "reason": "found a gap during review",
        },
        headers=auth_headers(admin_token),
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]

    # Nothing created yet — only on approval.
    before = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert before == []

    _submit_and_decide(client, admin_token, project["id"], cr_id, approve=True)

    after = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert len(after) == 1
    assert after[0]["title"] == "Run regression suite"
    assert after[0]["description"] == "Full suite, not smoke"
    assert after[0]["action_type_id"] == action_type_id


def test_add_action_change_request_links_an_existing_action_on_approval(client, admin_token, org_id):
    project, requirement, action_type_id = _setup_locked_requirement(client, admin_token, org_id)
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "this review already covers it",
        },
        headers=auth_headers(admin_token),
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]

    _submit_and_decide(client, admin_token, project["id"], cr_id, approve=True)

    after = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert len(after) == 1
    assert after[0]["id"] == action["id"]


def test_add_action_change_request_rejected_when_action_already_linked(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    # Link it while still unlocked (direct path, ungated).
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]}, headers=auth_headers(admin_token),
    )
    _approve_requirement(client, admin_token, project["id"], requirement["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_add_action_change_request_rejects_action_type_from_another_project(client, admin_token, org_id):
    project, requirement, _ = _setup_locked_requirement(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id)
    other_action_type_id = _action_types(client, admin_token, other_project["id"])[0]["id"]

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_title": "Run regression suite", "proposed_action_type_id": other_action_type_id,
            "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_add_action_change_request_rejects_linking_an_action_from_another_project(client, admin_token, org_id):
    project, requirement, _ = _setup_locked_requirement(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id)
    other_action_type_id = _action_types(client, admin_token, other_project["id"])[0]["id"]
    other_action = client.post(
        f"/api/v1/projects/{other_project['id']}/actions",
        json={"title": "Elsewhere", "action_type_id": other_action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": other_action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404, resp.text
