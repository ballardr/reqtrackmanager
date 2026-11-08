"""A template project is read-only for everyone below project administrator.

Whatever the project's own configuration says (an organisation-wide visibility baseline, a module's "any member may
submit" setting) and whichever module role is held, only a project manager, a project administrator or an
organisation administrator may change a template; a person's own preferences are not a change.
"""

from __future__ import annotations

from app.main import app
from app.services.template_guard import READ_ONLY_ROUTES
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

DECISIONS = "decisions"


def _member(client, token, org_id, project_id, email) -> str:
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return login(client, email, "Password123!")


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    assert client.put(f"/api/v1/orgs/{org['id']}/modules/{DECISIONS}", json={"enabled": True}, headers=auth_headers(token)).status_code == 200
    return org, token


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements", json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )


def test_a_member_cannot_add_to_a_template_but_can_to_an_ordinary_project(client, admin_token):
    org, token = _setup(client, admin_token, "Template RO Co")
    ordinary = create_project(client, token, org["id"], "Ordinary")
    template = create_project(client, token, org["id"], "Template")
    template_ids = create_component_and_category(client, token, template["id"])
    member_token = _member(client, token, org["id"], ordinary["id"], "ro-member@example.com")
    member_id = client.get("/api/v1/auth/me", headers=auth_headers(member_token)).json()["id"]
    added = client.post(f"/api/v1/projects/{template['id']}/roles", json={"user_id": member_id, "role": "member"}, headers=auth_headers(token))
    assert added.status_code == 204
    assert client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(token)).status_code == 200

    def decision(project_id: str, token_: str):
        types = client.get(f"/api/v1/projects/{project_id}/modules/{DECISIONS}/decision-types", headers=auth_headers(token_)).json()
        return client.post(
            f"/api/v1/projects/{project_id}/modules/{DECISIONS}", headers=auth_headers(token_),
            json={"title": "A decision", "decision_statement": "Yes.", "decision_type_id": types[0]["id"]},
        )

    assert decision(ordinary["id"], member_token).status_code == 201  # control: any member may submit a Decision here
    refused = decision(template["id"], member_token)
    assert refused.status_code == 403 and "template" in refused.json()["detail"]
    # Reading is still allowed, and so is a person's own preference.
    assert client.get(f"/api/v1/projects/{template['id']}/requirements", headers=auth_headers(member_token)).status_code == 200
    assert client.put(f"/api/v1/projects/{template['id']}/favorite", headers=auth_headers(member_token)).status_code in (200, 204)
    # A manager still can, and once it is no longer a template the member can add again.
    assert _create_requirement(client, token, template["id"], *template_ids, name="By manager").status_code == 201
    assert client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": False}, headers=auth_headers(token)).status_code == 200
    assert decision(template["id"], member_token).status_code == 201


def test_an_org_wide_template_is_read_only_for_every_organisation_member(client, admin_token):
    org, token = _setup(client, admin_token, "Template Wide Co")
    template = create_project(client, token, org["id"], "Wide Template")
    ids = create_component_and_category(client, token, template["id"])
    assert client.patch(
        f"/api/v1/projects/{template['id']}", json={"is_template": True, "visibility": "org_wide"}, headers=auth_headers(token),
    ).status_code == 200
    create_org_user(client, token, org["id"], "wide-reader@example.com")
    reader = login(client, "wide-reader@example.com", "Password123!")

    assert client.get(f"/api/v1/projects/{template['id']}/requirements", headers=auth_headers(reader)).status_code == 200
    assert _create_requirement(client, reader, template["id"], *ids).status_code == 403
    assert _create_requirement(client, token, template["id"], *ids).status_code == 201  # the organisation administrator


def test_every_read_only_route_is_a_real_route():
    """A renamed or removed endpoint must not leave a stale entry behind (a stale entry would silently stop
    matching, refusing a read on templates)."""
    real = {(method, route.path) for route in app.routes for method in (getattr(route, "methods", None) or ())}
    assert not READ_ONLY_ROUTES - real, sorted(READ_ONLY_ROUTES - real)


def test_publishing_a_template_to_the_whole_organisation_needs_the_organisation_permission(client, admin_token):
    """A project manager may make a project a template, or organisation-wide, but not both; an organisation
    administrator may, and a project that already has both can still be changed back."""
    org, token = _setup(client, admin_token, "Template Publish Co")
    h = auth_headers(token)
    project = create_project(client, token, org["id"], "Publish Project")
    user_id = create_org_user(client, token, org["id"], "publish-manager@example.com")
    assert client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_manager"}, headers=h).status_code == 204
    manager = auth_headers(login(client, "publish-manager@example.com", "Password123!"))
    url = f"/api/v1/projects/{project['id']}"

    assert client.patch(url, json={"is_template": True}, headers=manager).status_code == 200  # a team-only template
    refused = client.patch(url, json={"visibility": "org_wide"}, headers=manager)
    assert refused.status_code == 403 and "publish organisation templates" in refused.json()["detail"]
    assert client.patch(url, json={"is_template": False}, headers=manager).status_code == 200
    assert client.patch(url, json={"visibility": "org_wide"}, headers=manager).status_code == 200  # an org-wide project
    refused = client.patch(url, json={"is_template": True}, headers=manager)  # the other order
    assert refused.status_code == 403
    assert client.patch(url, json={"is_template": True, "visibility": "org_wide"}, headers=manager).status_code == 403

    assert client.patch(url, json={"is_template": True}, headers=h).status_code == 200  # the organisation administrator
    assert client.patch(url, json={"summary": "Edited by the manager"}, headers=manager).status_code == 200  # already published
    assert client.patch(url, json={"is_template": False}, headers=manager).status_code == 200  # removing is always allowed

    created = client.post("/api/v1/projects", json={
        "organization_id": org["id"], "name": "Born Published", "summary": "", "is_template": True, "visibility": "org_wide",
    }, headers=h)
    assert created.status_code == 201, created.text
    create_org_user(client, token, org["id"], "publish-creator@example.com", role="project_creator")
    creator = auth_headers(login(client, "publish-creator@example.com", "Password123!"))
    refused = client.post("/api/v1/projects", json={
        "organization_id": org["id"], "name": "Creator Published", "summary": "", "is_template": True, "visibility": "org_wide",
    }, headers=creator)
    assert refused.status_code == 403
