"""Tests for renaming and deleting project stages/components/categories:
rename validation (name/prefix collisions), delete-with-reassignment
(mandatory `reassign_to`, blocked when no valid target exists), the stage
delete's baseline-immutability guard and multi-version/change-request
reassignment, the component delete's "must be empty of categories" guard,
and the category delete's cross-component reassignment (which also fixes up
`Requirement.component_id`, not just `category_id`)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def _assign_project_role(client, admin_token, project_id, user_id, role):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _make_project_member(client, admin_token, org_id, project_id, email, role):
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project_id, user_id, role)
    return login(client, email, "Password123!")


def _create_requirement(client, admin_token, project_id, component_id, category_id, name="Boot fast", **extra):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id, **extra},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_stage(client, admin_token, project_id, name):
    resp = client.post(
        f"/api/v1/projects/{project_id}/stages", json={"name": name}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stages(client, admin_token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(admin_token)).json()


# --- Stage rename ------------------------------------------------------------


def test_rename_stage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage = _stages(client, admin_token, project["id"])[0]

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}", json={"name": "Renamed Stage"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed Stage"


def test_rename_stage_rejects_duplicate_name(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    first = _stages(client, admin_token, project["id"])[0]
    second = _add_stage(client, admin_token, project["id"], "Second Stage")

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/stages/{second['id']}", json={"name": first["name"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_rename_stage_requires_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage = _stages(client, admin_token, project["id"])[0]
    token = _make_project_member(client, admin_token, org_id, project["id"], "stakeholder_rename@example.com", "stakeholder")

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}", json={"name": "Hijacked"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


# --- Stage delete --------------------------------------------------------


def test_delete_stage_requires_a_different_existing_reassign_target(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    only_stage = _stages(client, admin_token, project["id"])[0]

    # Same-id target.
    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/stages/{only_stage['id']}?reassign_to={only_stage['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text

    # Only one stage exists at all: no valid target regardless.
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/stages/{only_stage['id']}?reassign_to={fake_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_delete_stage_blocked_by_existing_baseline(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage = _stages(client, admin_token, project["id"])[0]
    other = _add_stage(client, admin_token, project["id"], "Other Stage")

    review = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 200, review.text
    approve = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert approve.status_code == 200, approve.text

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/stages/{stage['id']}?reassign_to={other['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_delete_stage_reassigns_all_requirement_versions_and_cr_proposals(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    doomed = _stages(client, admin_token, project["id"])[0]
    keeper = _add_stage(client, admin_token, project["id"], "Keeper Stage")

    requirement = _create_requirement(
        client, admin_token, project["id"], component_id, category_id, target_stage_id=doomed["id"]
    )
    # A second version, still targeting the doomed stage — proves reassignment
    # touches every historical version, not just the current one.
    update = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Boot even faster", "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "target_stage_id": doomed["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert update.status_code == 200, update.text
    # A modify change request can only target an already-locked requirement
    # (2026-08 UX audit roadmap, "No requirement approval action; change
    # requests can target draft requirements") — approve it directly first.
    approve_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve", headers=auth_headers(admin_token)
    )
    assert approve_resp.status_code == 200, approve_resp.text

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["target_stage_id"], "proposed_target_stage_id": doomed["id"],
            "reason": "retarget",
        },
        headers=auth_headers(admin_token),
    ).json()

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/stages/{doomed['id']}?reassign_to={keeper['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    remaining = _stages(client, admin_token, project["id"])
    assert {s["id"] for s in remaining} == {keeper["id"]}
    assert keeper["id"] in [s["id"] for s in remaining]

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history) >= 2
    assert all(v["target_stage_id"] == keeper["id"] for v in history)

    current = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert current["target_stage_id"] == keeper["id"]

    cr_after = client.get(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}", headers=auth_headers(admin_token)
    ).json()
    assert cr_after["proposed_target_stage_id"] == keeper["id"]

    refreshed_keeper = next(s for s in remaining if s["id"] == keeper["id"])
    assert refreshed_keeper["is_current"] is True


def test_delete_stage_requires_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage = _stages(client, admin_token, project["id"])[0]
    other = _add_stage(client, admin_token, project["id"], "Other Stage")
    token = _make_project_member(client, admin_token, org_id, project["id"], "member_delete_stage@example.com", "member")

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/stages/{stage['id']}?reassign_to={other['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


# --- Component rename/delete --------------------------------------------


def test_rename_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, _ = create_component_and_category(client, admin_token, project["id"])

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/components/{component_id}",
        json={"name": "Renamed Component", "prefix": "RC"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": component_id, "project_id": project["id"], "name": "Renamed Component", "prefix": "RC", "sort_order": 0}


def test_rename_component_rejects_duplicate_prefix(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, _ = create_component_and_category(client, admin_token, project["id"])
    second = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/components/{second['id']}",
        json={"name": "Hardware", "prefix": "SW"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_delete_component_blocked_while_it_has_categories(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, _category_id = create_component_and_category(client, admin_token, project["id"])

    resp = client.delete(f"/api/v1/projects/{project['id']}/components/{component_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 409, resp.text


def test_delete_component_succeeds_once_empty(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Empty Component", "prefix": "EC"},
        headers=auth_headers(admin_token),
    ).json()["id"]

    resp = client.delete(f"/api/v1/projects/{project['id']}/components/{component_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text

    remaining = client.get(f"/api/v1/projects/{project['id']}/components", headers=auth_headers(admin_token)).json()
    assert component_id not in [c["id"] for c in remaining]


# --- Category rename/delete ----------------------------------------------


def test_rename_category(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/categories/{category_id}",
        json={"name": "Renamed Category", "prefix": "RC"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed Category"
    assert resp.json()["prefix"] == "RC"


def test_rename_category_rejects_duplicate_prefix_within_same_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    second_category = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Safety", "prefix": "SAF", "component_id": component_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/categories/{second_category['id']}",
        json={"name": "Safety", "prefix": "PERF"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_rename_category_allows_prefix_reused_across_different_components(client, admin_token, org_id):
    """A category prefix is only unique per-component (UniqueConstraint on
    component_id+prefix, not project_id+prefix) — reusing PERF under a
    second component must not collide with the first component's PERF."""
    project = create_project(client, admin_token, org_id)
    _component_id, _category_id = create_component_and_category(client, admin_token, project["id"])
    other_component = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(admin_token),
    ).json()
    other_category = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Thermal", "prefix": "THM", "component_id": other_component["id"]},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/categories/{other_category['id']}",
        json={"name": "Thermal", "prefix": "PERF"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def test_delete_category_requires_a_different_existing_reassign_target(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/categories/{category_id}?reassign_to={category_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text

    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/categories/{category_id}?reassign_to={fake_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_delete_category_cross_component_reassignment_fixes_up_requirement_component_id(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_a, category_a = create_component_and_category(client, admin_token, project["id"])
    component_b = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(admin_token),
    ).json()["id"]
    category_b = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Thermal", "prefix": "THM", "component_id": component_b},
        headers=auth_headers(admin_token),
    ).json()["id"]

    requirement = _create_requirement(client, admin_token, project["id"], component_a, category_a)
    assert requirement["component_id"] == component_a

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/categories/{category_a}?reassign_to={category_b}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    updated = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert updated["category_id"] == category_b
    assert updated["component_id"] == component_b

    categories = client.get(f"/api/v1/projects/{project['id']}/categories", headers=auth_headers(admin_token)).json()
    assert category_a not in [c["id"] for c in categories]


def test_delete_category_requires_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    other_category = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Safety", "prefix": "SAF", "component_id": component_id},
        headers=auth_headers(admin_token),
    ).json()["id"]
    token = _make_project_member(client, admin_token, org_id, project["id"], "member_delete_cat@example.com", "member")

    resp = client.request(
        "DELETE", f"/api/v1/projects/{project['id']}/categories/{category_id}?reassign_to={other_category}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 403
