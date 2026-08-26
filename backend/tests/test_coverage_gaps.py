"""Targeted tests for real gaps found via `pytest --cov=app --cov-report=term-missing`:
health/metrics endpoints, requirement reordering, traceability links,
organisation-level role grants, and the manager-fallback-on-deactivation
safeguard (C-U-09). Each test below corresponds to a specific
previously-uncovered code path, not general-purpose coverage padding."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


def test_health_endpoint_reports_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_metrics_endpoint_returns_prometheus_text(client, admin_token):
    # Generate at least one request so a counter has a nonzero sample.
    client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text


def test_metrics_never_embeds_real_ids_from_a_cors_preflight(client, admin_token, org_id):
    """Regression test for a real data leak: a CORS preflight `OPTIONS`
    request is short-circuited by `CORSMiddleware` before FastAPI's router
    ever sets `request.scope["route"]` — even for a path that would
    otherwise resolve to a real endpoint — so the metrics middleware had no
    route *template* to label with and fell back to the raw resolved path,
    embedding this org's real id as a literal, unauthenticated `/metrics`
    label value on every preflight the SPA makes (one per non-simple
    cross-origin request)."""
    preflight = client.options(
        f"/api/v1/orgs/{org_id}/users",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    metrics_text = client.get("/metrics").text
    assert org_id not in metrics_text
    assert 'method="OPTIONS",path="unmatched"' in metrics_text


def _create_requirement(client, admin_token, project_id, component_id, category_id, name):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()


def test_reorder_requirements_during_scoping(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    first = _create_requirement(client, admin_token, project["id"], component_id, category_id, "First")
    second = _create_requirement(client, admin_token, project["id"], component_id, category_id, "Second")

    listing = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert [r["id"] for r in listing] == [first["id"], second["id"]]

    moved = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{second['id']}/move",
        json={"direction": "up"},
        headers=auth_headers(admin_token),
    )
    assert moved.status_code == 200, moved.text

    reordered = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert [r["id"] for r in reordered] == [second["id"], first["id"]]


def test_reorder_rejected_outside_scoping_stage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement(client, admin_token, project["id"], component_id, category_id, "Locked-in-place")

    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    stage_id = stages[0]["id"]
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/move",
        json={"direction": "up"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409


def test_create_and_list_traceability_link(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    source = _create_requirement(client, admin_token, project["id"], component_id, category_id, "Depends on target")
    target = _create_requirement(client, admin_token, project["id"], component_id, category_id, "The dependency")
    link_types = {lt["forward_name"]: lt["id"] for lt in client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(admin_token)).json()}

    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{source['id']}/links",
        json={"target_requirement_id": target["id"], "link_type_id": link_types["Depends on"]},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    assert created.json()["target_requirement_id"] == target["id"]
    assert created.json()["display_name"] == "Depends on"

    listed = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{source['id']}/links", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200
    assert any(link["target_requirement_id"] == target["id"] for link in listed.json())


def test_project_metrics_reflects_requirement_and_change_request_counts(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    empty_metrics = client.get(f"/api/v1/projects/{project['id']}/metrics", headers=auth_headers(admin_token))
    assert empty_metrics.status_code == 200
    body = empty_metrics.json()
    assert body["requirement_count"] == 0
    assert body["requirement_completed_percent"] == 0.0
    assert body["change_requests_proposed"] == 0
    assert body["change_requests_approved"] == 0
    assert body["change_requests_rejected"] == 0
    assert body["requirements_by_status"] == {}
    # A brand-new project starts with one un-baselined "Scoping" stage.
    assert len(body["stage_progress"]) == 1
    assert body["stage_progress"][0]["name"] == "Scoping"
    assert body["stage_progress"][0]["completed_percent"] == 0.0

    _create_requirement(client, admin_token, project["id"], component_id, category_id, "Tracked requirement")
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "x", "reason": "y"},
        headers=auth_headers(admin_token),
    )

    metrics = client.get(f"/api/v1/projects/{project['id']}/metrics", headers=auth_headers(admin_token)).json()
    assert metrics["requirement_count"] == 1
    assert metrics["requirement_completed_percent"] == 0.0
    # The change request above is still in "draft" (never submitted), so it
    # shouldn't count as proposed/approved/rejected yet.
    assert metrics["change_requests_proposed"] == 0


def test_org_role_grant_success_and_notification(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "role_grant_target@example.com", role="member")

    granted = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles", json={"user_id": user_id, "role": "project_creator"},
        headers=auth_headers(admin_token),
    )
    assert granted.status_code == 204

    listing = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    entry = next(u for u in listing if u["user_id"] == user_id)
    assert "project_creator" in entry["roles"]

    granted_token = login(client, "role_grant_target@example.com", "Password123!")
    notifications = client.get("/api/v1/notifications", headers=auth_headers(granted_token)).json()
    assert any(n["title"] == "Organisation permission granted" for n in notifications)


def test_revoke_org_role_removes_it(client, admin_token, org_id):
    """`revoke_org_role` (added alongside hierarchical projects — see
    docs/decisions.md's "Hierarchical projects" entry — to close a
    pre-existing gap: `assign_org_role` had no counterpart). Grants a second
    role ("member") first so the user still has a `UserOrgRole` row after
    the revoke and stays visible in the (role-join-backed) listing — a user
    left with zero roles drops out of `list_org_users` entirely, by design,
    which would make the listing the wrong way to observe a single-role
    revoke."""
    user_id = create_org_user(client, admin_token, org_id, "role_revoke_target@example.com", role="member")
    granted = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles", json={"user_id": user_id, "role": "project_creator"},
        headers=auth_headers(admin_token),
    )
    assert granted.status_code == 204

    revoked = client.delete(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles/project_creator", headers=auth_headers(admin_token)
    )
    assert revoked.status_code == 204

    listing = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    entry = next(u for u in listing if u["user_id"] == user_id)
    assert entry["roles"] == ["member"]

    # No-op, not an error, when the user doesn't currently hold the role.
    again = client.delete(
        f"/api/v1/orgs/{org_id}/users/{user_id}/roles/project_creator", headers=auth_headers(admin_token)
    )
    assert again.status_code == 204


def test_revoke_org_role_blocks_self_targeting(client, admin_token, org_id):
    """An org admin can never revoke their own org role through this
    endpoint — the guard that keeps an organisation from ever reaching zero
    admins via this path (see `revoke_org_role`'s own docstring)."""
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()

    resp = client.delete(
        f"/api/v1/orgs/{org_id}/users/{me['id']}/roles/org_admin", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400


def test_revoke_org_role_requires_org_admin(client, admin_token, org_id):
    """A caller without `ORG_ADMIN` (e.g. a plain member) gets 403, not a
    silent no-op or a successful revoke."""
    create_org_user(client, admin_token, org_id, "role_revoke_nonadmin@example.com", role="member")
    member_token = login(client, "role_revoke_nonadmin@example.com", "Password123!")

    target_id = create_org_user(client, admin_token, org_id, "role_revoke_victim@example.com", role="project_creator")
    resp = client.delete(
        f"/api/v1/orgs/{org_id}/users/{target_id}/roles/project_creator", headers=auth_headers(member_token)
    )
    assert resp.status_code == 403


def test_deactivating_last_project_manager_falls_back_to_acting_admin(client, admin_token, org_id):
    """C-U-09: deactivating a user who is a project's only manager must
    never leave the project without one — the acting org admin is assigned
    as a fallback manager. The project is created by the soon-to-be-deactivated
    user (not the admin), so the admin isn't already a manager via the
    default "Project Managers" group the creator is auto-added to."""
    manager_id = create_org_user(client, admin_token, org_id, "sole_manager@example.com", role="project_creator")
    manager_token = login(client, "sole_manager@example.com", "Password123!")
    project = create_project(client, manager_token, org_id, name="Solely Managed Project")

    resp = client.post(f"/api/v1/orgs/{org_id}/users/{manager_id}/deactivate", headers=auth_headers(admin_token))
    assert resp.status_code == 204

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    assert any(c["action"] == "manager_fallback_assigned" for c in changes)
