"""Guard: an action that grants access, creates an account with a chosen password, or changes how people sign in is
never available to a Personal Access Token (the class of defect behind a token minting wider access than it holds)."""

from __future__ import annotations

import re

from app.deps import get_current_session_user, refuse_personal_access_token
from app.main import app
from tests.conftest import auth_headers, create_org_admin_in

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Paths that grant or revoke access, issue credentials or change sign-in. Role *definitions* (a custom role's own
# create, edit and delete) and stakeholder groups (a register of people, not an access group) are not grants.
GRANT = re.compile(
    r"/(roles|group-roles|module-roles|scim-token|sso-config|advanced-settings|server-roles)(/|$)|/custom-roles/\{role_id\}/(users|groups)/"
    r"|/groups/\{group_id\}/members|/users$|/membership$|/standards/\{standard_id\}/(members|group-roles)"
)
NOT_GRANTS = re.compile(r"stakeholder-groups|^/scim/|/pats|/auth/")
SESSION_ONLY_CALLS = {refuse_personal_access_token, get_current_session_user}


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _grant_routes():
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if methods & MUTATING and GRANT.search(path) and not NOT_GRANTS.search(path):
            # `DELETE /orgs/{id}/users/{user_id}/membership` removes another member; only leaving is session-only.
            if path.endswith("/users/{user_id}/membership"):
                continue
            yield route


def test_every_grant_route_refuses_a_personal_access_token():
    routes = list(_grant_routes())
    assert len(routes) >= 30, "the walk found too few routes; the path patterns have drifted"
    missing = [
        f"{sorted(r.methods & MUTATING)} {r.path}" for r in routes if not set(_calls(r.dependant)) & SESSION_ONLY_CALLS
    ]
    assert not missing, f"These routes accept a Personal Access Token: {missing}"


def test_a_token_cannot_issue_a_scim_token_or_grant_a_role(client, admin_token):
    org, org_admin = create_org_admin_in(client, admin_token, "Pat Org")
    org_id = org["id"]
    resp = client.post(
        "/api/v1/me/pats", json={"name": "ci", "allowed_organization_ids": [org_id]}, headers=auth_headers(org_admin)
    )
    assert resp.status_code in (200, 201), resp.text
    pat = resp.json()["token"]
    refused = client.post(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(pat))
    assert refused.status_code == 403
    assert client.post(f"/api/v1/orgs/{org_id}/scim-token", headers=auth_headers(org_admin)).status_code == 200
    assert client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(pat)).status_code == 403
    settings = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(org_admin)).json()
    assert client.put(f"/api/v1/orgs/{org_id}/advanced-settings", json=settings, headers=auth_headers(pat)).status_code == 403
    assert client.put(f"/api/v1/orgs/{org_id}/advanced-settings", json=settings, headers=auth_headers(org_admin)).status_code == 200


def test_marking_a_file_confidential_does_not_accept_the_url_media_token(client, admin_token):
    from app.main import app as application

    route = next(r for r in application.routes if getattr(r, "path", "").endswith("/files/{file_id}/confidential"))
    names = {p.name for p in route.dependant.query_params}
    assert "token" not in names
