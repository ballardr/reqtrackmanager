"""Tests for the optional `definition` on Pain Point types, at both tiers.

An organisation type carries its own `definition`; a project override replaces it for that project only
(`definition_override`) and a project-only type has just its own. The effective list resolves the project's text
first, then the organisation's. A blank value clears: on an organisation type it removes the definition, on a
project override it makes the organisation's text show again.
"""

from __future__ import annotations

from tests.conftest import auth_headers, create_org_admin_in, create_project

MODULE_KEY = "context_strategy"


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _setup(client, admin_token, org_name: str):
    org, token = create_org_admin_in(client, admin_token, org_name)
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    project = create_project(client, token, org["id"], f"{org_name} Project")
    return org, project, token


def _effective(client, token, project_id: str, name: str) -> dict:
    resp = client.get(_project_base(project_id) + "/pain-point-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return next(t for t in resp.json() if t["name"] == name)


def test_seeded_types_have_no_definition(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Seed Co")
    assert _effective(client, token, project["id"], "Market")["definition"] is None


def test_org_type_definition_is_created_updated_trimmed_and_cleared(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Org Co")
    resp = client.post(
        _org_base(org["id"]) + "/pain-point-types",
        json={"name": "Regulatory", "definition": "  Rules we must comply with.  "}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    type_id = resp.json()["id"]
    assert resp.json()["definition"] == "Rules we must comply with."
    assert _effective(client, token, project["id"], "Regulatory")["definition"] == "Rules we must comply with."

    resp = client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{type_id}", json={"definition": "Legal duties."},
        headers=auth_headers(token),
    )
    assert resp.json()["definition"] == "Legal duties."

    # Omitting the field leaves it alone; a blank value clears it.
    resp = client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{type_id}", json={"is_active": True}, headers=auth_headers(token)
    )
    assert resp.json()["definition"] == "Legal duties."
    resp = client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{type_id}", json={"definition": "   "}, headers=auth_headers(token)
    )
    assert resp.json()["definition"] is None


def test_definition_longer_than_the_cap_is_rejected(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Cap Co")
    resp = client.post(
        _org_base(org["id"]) + "/pain-point-types", json={"name": "Long", "definition": "x" * 2001},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


def test_project_override_replaces_then_reverts_to_the_organisation_definition(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Override Co")
    market = _effective(client, token, project["id"], "Market")
    client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{market['id']}", json={"definition": "Org text."},
        headers=auth_headers(token),
    )
    assert _effective(client, token, project["id"], "Market")["definition"] == "Org text."

    resp = client.put(
        f"{_project_base(project['id'])}/pain-point-types/{market['id']}", json={"definition": "Project text."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["definition_override"] == "Project text."
    effective = _effective(client, token, project["id"], "Market")
    assert effective["definition"] == "Project text."
    assert effective["source"] == "project_override"

    # The organisation's own text is untouched by the project's override.
    org_row = next(
        t for t in client.get(_org_base(org["id"]) + "/pain-point-types", headers=auth_headers(token)).json()
        if t["id"] == market["id"]
    )
    assert org_row["definition"] == "Org text."

    # Clearing the override makes the organisation's text show again.
    resp = client.put(
        f"{_project_base(project['id'])}/pain-point-types/{effective['id']}", json={"definition": ""},
        headers=auth_headers(token),
    )
    assert resp.json()["definition_override"] is None
    assert _effective(client, token, project["id"], "Market")["definition"] == "Org text."


def test_project_only_type_carries_its_own_definition(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Local Co")
    resp = client.post(
        _project_base(project["id"]) + "/pain-point-types", json={"name": "Field Ops", "definition": "On-site work."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["definition_override"] == "On-site work."
    effective = _effective(client, token, project["id"], "Field Ops")
    assert effective["definition"] == "On-site work."
    assert effective["source"] == "project_local"


def test_other_projects_keep_the_organisation_definition(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Def Isolation Co")
    other = create_project(client, token, org["id"], "PP Def Isolation Other")
    market = _effective(client, token, project["id"], "Market")
    client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{market['id']}", json={"definition": "Org text."},
        headers=auth_headers(token),
    )
    client.put(
        f"{_project_base(project['id'])}/pain-point-types/{market['id']}", json={"definition": "Project text."},
        headers=auth_headers(token),
    )
    assert _effective(client, token, other["id"], "Market")["definition"] == "Org text."
