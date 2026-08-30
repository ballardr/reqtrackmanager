"""Permission-level access tests: for each significant authorization
boundary, verifies both that roles below the required level are rejected
(403) and that a role that should be allowed actually succeeds. This
complements test_rbac.py (which covers a handful of boundaries already) and
test_security_hardening.py (cross-tenant IDOR) with a broader, systematic
sweep across org and project roles."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _assign_project_role(client, admin_token, project_id, user_id, role):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _make_project_member(client, admin_token, org_id, project_id, email, role):
    """Creates an org member and grants them a single project role. Returns their token."""
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project_id, user_id, role)
    return login(client, email, "Password123!")


# --- Project settings management: project_manager/administrator/org_admin only ---

def test_stakeholder_cannot_update_project_settings(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    token = _make_project_member(client, admin_token, org_id, project["id"], "stakeholder_settings@example.com", "stakeholder")
    resp = client.patch(f"/api/v1/projects/{project['id']}", json={"summary": "hijacked"}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_project_administrator_can_update_project_settings(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    token = _make_project_member(
        client, admin_token, org_id, project["id"], "admin_settings@example.com", "project_administrator"
    )
    resp = client.patch(f"/api/v1/projects/{project['id']}", json={"summary": "updated by administrator"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "updated by administrator"


def test_member_cannot_create_project_stage_component_or_category(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, _ = create_component_and_category(client, admin_token, project["id"])
    token = _make_project_member(client, admin_token, org_id, project["id"], "plain_member@example.com", "member")

    assert client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Extra"}, headers=auth_headers(token)
    ).status_code == 403
    assert client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "X", "prefix": "X"}, headers=auth_headers(token)
    ).status_code == 403
    assert client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "X", "prefix": "X", "component_id": component_id}, headers=auth_headers(token)
    ).status_code == 403


# --- Requirement editing: stakeholder/administrator/manager yes, plain member no ---

def test_stakeholder_can_create_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    token = _make_project_member(client, admin_token, org_id, project["id"], "stakeholder_req@example.com", "stakeholder")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Stakeholder-authored requirement", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


# --- Change request decision: project_manager only, not administrator/stakeholder ---

def test_project_administrator_cannot_decide_change_request(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    token = _make_project_member(
        client, admin_token, org_id, project["id"], "admin_decide@example.com", "project_administrator"
    )
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "x", "reason": "y"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_project_manager_can_decide_change_request(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    token = _make_project_member(
        client, admin_token, org_id, project["id"], "manager_decide@example.com", "project_manager"
    )
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "new_requirement", "proposed_name": "x", "reason": "y",
            "proposed_component_id": component_id, "proposed_category_id": category_id,
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


# --- Requirement approval via direct edit: project_manager only, not
# administrator/stakeholder — hardening-review regression (self-approval) ---

def _create_requirement_for_approval(client, admin_token, project_id, component_id, category_id):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Needs approval", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()


def test_stakeholder_cannot_approve_requirement_via_direct_edit(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement_for_approval(client, admin_token, project["id"], component_id, category_id)
    token = _make_project_member(client, admin_token, org_id, project["id"], "stakeholder_approve@example.com", "stakeholder")

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": requirement["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "status": "approved",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_project_administrator_cannot_approve_requirement_via_direct_edit(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement_for_approval(client, admin_token, project["id"], component_id, category_id)
    token = _make_project_member(
        client, admin_token, org_id, project["id"], "admin_approve@example.com", "project_administrator"
    )

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": requirement["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "status": "approved",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_project_manager_can_approve_requirement_via_direct_edit(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement_for_approval(client, admin_token, project["id"], component_id, category_id)
    token = _make_project_member(client, admin_token, org_id, project["id"], "pm_approve@example.com", "project_manager")

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": requirement["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "status": "approved",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_direct_edit_cannot_jump_straight_to_completed(client, admin_token, org_id):
    """Completion has its own dedicated, precondition-checked endpoint
    (POST .../complete, requiring the requirement to already be approved) —
    the general-purpose direct-edit PUT must not be usable to skip that
    precondition, regardless of the caller's role.

    C-G-11: this used to be an explicit application-level guard in
    `update_requirement` (a `payload.status == RequirementStatus.COMPLETED`
    check returning 400) — now that `COMPLETED` isn't a valid
    `RequirementStatus` value at all (completion is the independent
    `Requirement.is_completed` overlay instead), the same rejection happens
    naturally via Pydantic/enum request validation, which FastAPI reports as
    422, not 400."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement_for_approval(client, admin_token, project["id"], component_id, category_id)

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": requirement["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "status": "completed",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422


# --- Custom field definitions: require_project_manage, not just view/edit access ---

def test_stakeholder_cannot_manage_custom_field_definitions(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    token = _make_project_member(client, admin_token, org_id, project["id"], "stakeholder_cf@example.com", "stakeholder")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/custom-fields",
        json={"entity_kind": "requirement", "name": "Priority", "field_type": "short_text", "required": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


# --- Org-level administration: org_admin only, not project_creator/member ---

def test_project_creator_cannot_create_org_group_or_manage_users(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "creator_org_admin_test@example.com", role="project_creator")
    token = login(client, "creator_org_admin_test@example.com", "Password123!")

    assert client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Should not be allowed"}, headers=auth_headers(token)
    ).status_code == 403
    other_user_id = create_org_user(client, admin_token, org_id, "victim_of_test@example.com")
    assert client.post(
        f"/api/v1/orgs/{org_id}/users/{other_user_id}/deactivate", headers=auth_headers(token)
    ).status_code == 403
    assert client.post(
        f"/api/v1/orgs/{org_id}/users/{other_user_id}/roles", json={"user_id": other_user_id, "role": "member"},
        headers=auth_headers(token),
    ).status_code == 403


def test_org_admin_can_create_org_group(client, admin_token, org_id):
    resp = client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": "Allowed"}, headers=auth_headers(admin_token))
    assert resp.status_code == 201


# --- Project view boundary: someone with zero role on the project is fully blocked ---

def test_non_member_cannot_list_requirements_or_change_requests(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "outsider@example.com", role="member")
    token = login(client, "outsider@example.com", "Password123!")

    assert client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(token)).status_code == 403
    assert client.get(f"/api/v1/projects/{project['id']}/change-requests", headers=auth_headers(token)).status_code == 403
    assert client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(token)).status_code == 403
