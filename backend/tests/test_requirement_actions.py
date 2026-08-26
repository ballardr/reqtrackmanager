"""Tests for requirement actions (`RequirementAction`) — CRUD, archive,
`unique_code` sequencing, outcome-transition stamping, comments, direct
file attachments, and cross-project IDOR."""

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _action_types(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()


def test_create_action_and_get(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]

    created = client.post(
        f"/api/v1/projects/{project['id']}/actions",
        json={"title": "Review the design", "description": "Check it over", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["unique_code"] == "ACT-001"
    assert body["title"] == "Review the design"
    assert body["outcome_status"] == "pending"
    assert body["is_archived"] is False
    assert body["completed_at"] is None

    fetched = client.get(f"/api/v1/projects/{project['id']}/actions/{body['id']}", headers=auth_headers(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_unique_code_sequencing_never_reused(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]

    codes = []
    for i in range(3):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/actions",
            json={"title": f"Action {i}", "action_type_id": action_type_id},
            headers=auth_headers(admin_token),
        )
        codes.append(resp.json()["unique_code"])
    assert codes == ["ACT-001", "ACT-002", "ACT-003"]

    # Archiving doesn't free up its code for reuse.
    client.post(f"/api/v1/projects/{project['id']}/actions", json={"title": "x", "action_type_id": action_type_id}, headers=auth_headers(admin_token))
    resp = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "y", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    )
    assert resp.json()["unique_code"] == "ACT-005"


def test_update_action_fields(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions",
        json={"title": "Original", "action_type_id": action_types[0]["id"]}, headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}",
        json={"title": "Updated", "description": "New desc", "action_type_id": action_types[1]["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"
    assert resp.json()["action_type_id"] == action_types[1]["id"]
    assert resp.json()["outcome_status"] == "pending"


def test_outcome_transition_stamps_and_clears_completion(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    completed = client.patch(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}",
        json={"title": "T", "action_type_id": action_type_id, "outcome_status": "completed"},
        headers=auth_headers(admin_token),
    ).json()
    assert completed["outcome_status"] == "completed"
    assert completed["completed_at"] is not None
    assert completed["completed_by"] is not None

    reverted = client.patch(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}",
        json={"title": "T", "action_type_id": action_type_id, "outcome_status": "pending"},
        headers=auth_headers(admin_token),
    ).json()
    assert reverted["outcome_status"] == "pending"
    assert reverted["completed_at"] is None
    assert reverted["completed_by"] is None

    failed = client.patch(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}",
        json={"title": "T", "action_type_id": action_type_id, "outcome_status": "failed"},
        headers=auth_headers(admin_token),
    ).json()
    assert failed["outcome_status"] == "failed"
    assert failed["completed_at"] is not None


def test_list_actions_filters(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    a = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "A", "action_type_id": action_types[0]["id"]},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "B", "action_type_id": action_types[1]["id"]},
        headers=auth_headers(admin_token),
    )
    client.patch(
        f"/api/v1/projects/{project['id']}/actions/{a['id']}",
        json={"title": "A", "action_type_id": action_types[0]["id"], "outcome_status": "completed"},
        headers=auth_headers(admin_token),
    )

    by_type = client.get(
        f"/api/v1/projects/{project['id']}/actions", params={"action_type_id": action_types[1]["id"]},
        headers=auth_headers(admin_token),
    ).json()
    assert len(by_type) == 1 and by_type[0]["title"] == "B"

    by_outcome = client.get(
        f"/api/v1/projects/{project['id']}/actions", params={"outcome_status": "completed"},
        headers=auth_headers(admin_token),
    ).json()
    assert len(by_outcome) == 1 and by_outcome[0]["title"] == "A"


def test_archive_action_hides_it_from_default_list(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    archived = client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/archive", headers=auth_headers(admin_token))
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert archived.json()["archived_at"] is not None

    default_list = client.get(f"/api/v1/projects/{project['id']}/actions", headers=auth_headers(admin_token)).json()
    assert action["id"] not in [a["id"] for a in default_list]

    with_archived = client.get(
        f"/api/v1/projects/{project['id']}/actions", params={"include_archived": True}, headers=auth_headers(admin_token)
    ).json()
    assert action["id"] in [a["id"] for a in with_archived]

    # Archiving again is refused (already archived), not silently accepted.
    resp = client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/archive", headers=auth_headers(admin_token))
    assert resp.status_code == 409


def test_unarchive_action_restores_it_and_is_idempotent(client, admin_token, org_id):
    """Pins the `/unarchive` counterpart to
    `test_archive_action_hides_it_from_default_list` above (2026-08 UX audit
    roadmap: archive was previously one-way for actions, unlike projects).
    Also covers the idempotency contract: unlike `archive`'s 409-on-already-
    archived above, calling unarchive on an already-active action is a
    no-op, matching `unarchive_project`'s own shape."""
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/archive", headers=auth_headers(admin_token))

    resp = client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/unarchive", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is False
    assert resp.json()["archived_at"] is None

    default_list = client.get(f"/api/v1/projects/{project['id']}/actions", headers=auth_headers(admin_token)).json()
    assert action["id"] in [a["id"] for a in default_list]

    # Idempotent: unarchiving an already-active action doesn't error.
    again = client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/unarchive", headers=auth_headers(admin_token))
    assert again.status_code == 200
    assert again.json()["is_archived"] is False


def test_unarchive_action_requires_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/actions/{action['id']}/archive", headers=auth_headers(admin_token))

    user_id = create_org_user(client, admin_token, org_id, "stakeholder_action_unarchive@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    stakeholder_token = login(client, "stakeholder_action_unarchive@example.com", "Password123!")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/unarchive", headers=auth_headers(stakeholder_token)
    )
    assert resp.status_code == 403


def test_action_comments_and_reactions(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    comment = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments", json={"body": "Looks good"},
        headers=auth_headers(admin_token),
    )
    assert comment.status_code == 201, comment.text
    comment_id = comment.json()["id"]

    listed = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments", headers=auth_headers(admin_token)).json()
    assert len(listed) == 1
    assert listed[0]["body"] == "Looks good"

    react = client.put(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments/{comment_id}/reaction",
        headers=auth_headers(admin_token),
    )
    assert react.status_code == 204

    fetched_action = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}", headers=auth_headers(admin_token)).json()
    assert fetched_action["comment_count"] == 1

    edited = client.patch(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments/{comment_id}", json={"body": "Edited"},
        headers=auth_headers(admin_token),
    )
    assert edited.status_code == 200
    assert edited.json()["body"] == "Edited"
    assert edited.json()["edited_at"] is not None


def test_action_comment_file_attachment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    comment = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments", json={"body": "See attached"},
        headers=auth_headers(admin_token),
    ).json()

    upload = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments/{comment['id']}/files",
        files={"file": ("evidence.txt", b"test evidence", "text/plain")}, headers=auth_headers(admin_token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    listed = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments", headers=auth_headers(admin_token)).json()
    assert len(listed[0]["attachments"]) == 1

    removed = client.delete(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/comments/{comment['id']}/files/{file_id}",
        headers=auth_headers(admin_token),
    )
    assert removed.status_code == 204


def test_action_direct_file_attachment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    upload = client.post(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/files",
        files={"file": ("report.pdf", b"%PDF-fake", "application/pdf")}, headers=auth_headers(admin_token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    listed = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}/files", headers=auth_headers(admin_token)).json()
    assert len(listed) == 1

    removed = client.delete(
        f"/api/v1/projects/{project['id']}/actions/{action['id']}/files/{file_id}", headers=auth_headers(admin_token)
    )
    assert removed.status_code == 204
    assert client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}/files", headers=auth_headers(admin_token)).json() == []


def test_action_type_id_must_belong_to_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Action IDOR Project A")
    project_b = create_project(client, admin_token, org_id, "Action IDOR Project B")
    other_project_type_id = _action_types(client, admin_token, project_b["id"])[0]["id"]

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/actions",
        json={"title": "T", "action_type_id": other_project_type_id}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_cannot_access_action_from_another_project(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Action Cross Project A")
    project_b = create_project(client, admin_token, org_id, "Action Cross Project B")
    action_type_id = _action_types(client, admin_token, project_a["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project_a['id']}/actions", json={"title": "T", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.get(f"/api/v1/projects/{project_b['id']}/actions/{action['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 404


def test_action_endpoints_require_project_membership(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _other_org, other_token = create_org_admin_in(client, admin_token, "Action Auth Other Org")
    resp = client.get(f"/api/v1/projects/{project['id']}/actions", headers=auth_headers(other_token))
    assert resp.status_code == 403
