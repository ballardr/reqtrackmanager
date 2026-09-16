"""Tests for the AI-approval-via-MCP gate (docs/decisions.md's "AI approval
via MCP" entry): approve_requirement, decide_change_request, and
complete_requirement all reject an MCP-originated call (identified by the
`X-Reqtrack-Client: mcp-server` header — see app.deps.get_request_channel)
unless both the project's and its organisation's `allow_ai_approvals` flags
are true, while a plain UI/API call (no such header) is completely
unaffected by either flag regardless of role. Also covers the two flags'
round trip through the existing advanced-settings/project-update endpoints
and the "via mcp" audit/change-note marker landing when the gate passes.
"""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _mcp_headers(token: str) -> dict:
    return {**auth_headers(token), "X-Reqtrack-Client": "mcp-server"}


def _create_requirement(client, admin_token, project_id, component_id, category_id, name="Boot fast"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_org_ai_approvals(client, admin_token, org_id, enabled: bool):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings", json={"allow_ai_approvals": enabled},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_project_ai_approvals(client, admin_token, project_id, enabled: bool):
    resp = client.patch(
        f"/api/v1/projects/{project_id}", json={"allow_ai_approvals": enabled}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_ai_approvals_flags_default_off_and_round_trip(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    assert project["allow_ai_approvals"] is False

    org_out = _set_org_ai_approvals(client, admin_token, org_id, True)
    assert org_out["allow_ai_approvals"] is True
    project_out = _set_project_ai_approvals(client, admin_token, project["id"], True)
    assert project_out["allow_ai_approvals"] is True

    # And the org-level flag is also visible on the plain project-scoped
    # organisation read any project manager (not just an org admin) can
    # reach — see OrganizationOut.allow_ai_approvals's docstring.
    org_resp = client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(admin_token))
    assert org_resp.status_code == 200
    assert org_resp.json()["allow_ai_approvals"] is True


def test_mcp_approve_requirement_blocked_when_both_flags_off(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403
    assert "AI approval is not enabled" in resp.text


def test_mcp_approve_requirement_blocked_when_only_one_flag_is_on(client, admin_token, org_id):
    """Both flags must be true — org-only or project-only must still fail."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    _set_org_ai_approvals(client, admin_token, org_id, True)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403

    _set_org_ai_approvals(client, admin_token, org_id, False)
    _set_project_ai_approvals(client, admin_token, project["id"], True)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403


def test_mcp_approve_requirement_allowed_when_both_flags_on_and_marks_via_mcp(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history",
        headers=auth_headers(admin_token),
    ).json()
    latest = history[-1]
    assert latest["change_note"] == "Approved via MCP."


def test_ui_channel_approve_requirement_unaffected_by_flags_being_off(client, admin_token, org_id):
    """Regression guard: the new gate must never affect a plain UI/API call
    (no X-Reqtrack-Client header) — a human with the right role can still
    approve directly, exactly as before this feature existed, regardless of
    either flag's value."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history",
        headers=auth_headers(admin_token),
    ).json()
    assert history[-1]["change_note"] == "Approved directly."


def test_mcp_complete_requirement_blocked_then_allowed(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    approve = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=auth_headers(admin_token),
    )
    assert approve.status_code == 200

    blocked = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/complete",
        headers=_mcp_headers(admin_token),
    )
    assert blocked.status_code == 403

    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)
    allowed = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/complete",
        headers=_mcp_headers(admin_token),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["is_completed"] is True


def test_mcp_decide_change_request_blocked_then_allowed(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    approve = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
        headers=auth_headers(admin_token),
    )
    assert approve.status_code == 200

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "reason": "x",
            "changed_fields": ["name"], "proposed_name": "New name",
        },
        headers=auth_headers(admin_token),
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]
    submit = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/submit", headers=auth_headers(admin_token)
    )
    assert submit.status_code == 200, submit.text

    blocked = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/decide",
        json={"approve": True, "note": ""}, headers=_mcp_headers(admin_token),
    )
    assert blocked.status_code == 403

    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)
    allowed = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/decide",
        json={"approve": True, "note": ""}, headers=_mcp_headers(admin_token),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "approved"
