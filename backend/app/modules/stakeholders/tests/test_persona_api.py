"""Tests for the Stakeholders & Personas module's Phase 1.1 backend API
(docs/plans/module-02-stakeholders-and-personas-plan.md — Persona), through
the real HTTP endpoints.

Covers: org- and project-scoped CRUD and the scope rules, partial update
(including clearing nullable fields), version history, the Draft/Active/
Retired lifecycle (including an illegal-transition 409), the Persona type
vocabulary (org CRUD, project override/local/delete, in-use blocking), the
weight resolution chain (own -> ancestor override -> project override),
RBAC composition (owner roles, FGAC grant, type admin, view-only members),
disabled module/sub-component 404s, cross-tenant isolation, comments, files,
the `scoring_target_providers` hook (including disabled-module output), and
the default-type seeding for new organisations.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.modules.registry import get_scoring_targets
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "stakeholders"


def _org_base(org_id) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def _project_base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _enable_module(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, org_name: str):
    """Org with a real admin, a project, and the module enabled."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    _enable_module(client, token, org["id"])
    return org, create_project(client, token, org["id"], f"{org_name} Project"), token


def _add_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _grant(client, org_admin_token, url, role_key) -> None:
    resp = client.post(url, json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(org_admin_token))
    assert resp.status_code == 204, resp.text


def _grant_project_role(client, token, project_id, user_id, role_key) -> None:
    _grant(client, token, f"/api/v1/projects/{project_id}/members/{user_id}/module-roles", role_key)


def _grant_org_role(client, token, org_id, user_id, role_key) -> None:
    _grant(client, token, f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles", role_key)


_PAYLOAD = {
    "name": "Field Technician",
    "description": "Inspects equipment on site.",
    "role_title": "Senior technician",
    "goals": "Finish inspections without rework.",
    "needs": "Offline access.",
    "behaviours": "Works in short bursts between sites.",
    "context_environment": "Outdoors, gloves on.",
    "skills_proficiency": "Expert in the equipment, novice with software.",
    "frequency_of_use": "Daily",
    "constraints": "No reliable network.",
}


def _create_project_persona(client, token, project_id, **extra) -> dict:
    resp = client.post(_project_base(project_id) + "/personas", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_org_persona(client, token, org_id, **extra) -> dict:
    resp = client.post(_org_base(org_id) + "/personas", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- CRUD, scope, versions ---------------------------------------------------


def test_project_persona_crud_and_versions(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona Crud Co")
    created = _create_project_persona(client, token, project["id"], weight=2.5)
    assert created["scope"] == "project" and created["project_id"] == project["id"]
    assert created["organization_id"] is None
    assert created["status"] == "draft" and created["version_number"] == 1
    assert created["weight"] == 2.5 and created["effective_weight"] == 2.5

    url = f"{_project_base(project['id'])}/personas/{created['id']}"
    resp = client.put(url, json={"goals": "New goal", "change_note": "refine"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["goals"] == "New goal" and body["name"] == "Field Technician" and body["version_number"] == 2
    assert body["weight"] == 2.5  # unspecified fields carry forward

    versions = client.get(url + "/versions", headers=auth_headers(token)).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["valid_to"] is not None and versions[1]["valid_to"] is None
    assert versions[1]["change_note"] == "refine"


def test_update_can_clear_nullable_fields(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Clear Co")
    user_id = create_org_user(client, token, org["id"], "champ@clear.example.com")
    created = _create_project_persona(client, token, project["id"], weight=3, champion_id=user_id)
    assert created["champion_id"] == user_id
    url = f"{_project_base(project['id'])}/personas/{created['id']}"
    resp = client.put(url, json={"weight": None, "champion_id": None}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["weight"] is None and resp.json()["champion_id"] is None


def test_weight_must_be_positive(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona Weight Positive Co")
    for bad in (0, -1):
        resp = client.post(_project_base(project["id"]) + "/personas", json={**_PAYLOAD, "weight": bad}, headers=auth_headers(token))
        assert resp.status_code == 422, resp.text


def test_owner_and_champion_must_be_org_members(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona People A Co")
    other_org, _ = create_org_admin_in(client, admin_token, "Persona People B Co")
    outsider = create_org_user(client, admin_token, other_org["id"], "outsider@b.example.com")
    resp = client.post(
        _project_base(project["id"]) + "/personas", json={**_PAYLOAD, "champion_id": outsider}, headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


def test_org_persona_crud_and_visible_from_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Org Scope Co")
    org_persona = _create_org_persona(client, token, org["id"])
    assert org_persona["scope"] == "organization" and org_persona["organization_id"] == org["id"]
    assert org_persona["project_id"] is None

    listed = client.get(_org_base(org["id"]) + "/personas", headers=auth_headers(token)).json()
    assert [p["id"] for p in listed] == [org_persona["id"]]

    # Visible read-only from a project in the org, with an effective weight.
    project_list = client.get(_project_base(project["id"]) + "/personas", headers=auth_headers(token)).json()
    assert [p["id"] for p in project_list] == [org_persona["id"]]
    only_project = client.get(_project_base(project["id"]) + "/personas?include_org=false", headers=auth_headers(token)).json()
    assert only_project == []

    # ...but the project router can't edit it.
    resp = client.put(
        f"{_project_base(project['id'])}/personas/{org_persona['id']}", json={"goals": "x"}, headers=auth_headers(token),
    )
    assert resp.status_code == 404, resp.text


def test_archive_hides_from_default_list(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona Archive Co")
    persona = _create_project_persona(client, token, project["id"])
    base = f"{_project_base(project['id'])}/personas"
    assert client.post(f"{base}/{persona['id']}/archive", headers=auth_headers(token)).json()["is_archived"] is True
    assert client.get(base, headers=auth_headers(token)).json() == []
    assert len(client.get(base + "?include_archived=true", headers=auth_headers(token)).json()) == 1
    assert client.post(f"{base}/{persona['id']}/unarchive", headers=auth_headers(token)).json()["is_archived"] is False


# --- Lifecycle ---------------------------------------------------------------


def test_lifecycle_transitions_and_illegal_409(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona Lifecycle Co")
    persona = _create_project_persona(client, token, project["id"])
    base = f"{_project_base(project['id'])}/personas/{persona['id']}"
    h = auth_headers(token)

    assert client.post(base + "/activate", headers=h).json()["status"] == "active"
    assert client.post(base + "/activate", headers=h).status_code == 409  # already active
    assert client.post(base + "/retire", json={"comment": "obsolete"}, headers=h).json()["status"] == "retired"
    assert client.post(base + "/retire", headers=h).status_code == 409
    assert client.post(base + "/activate", headers=h).json()["status"] == "active"  # reactivation
    # Content stays editable in every status (no approval gate / lock).
    assert client.put(base, json={"goals": "still editable"}, headers=h).status_code == 200
    versions = client.get(base + "/versions", headers=h).json()
    assert [v["status"] for v in versions] == ["draft", "active", "retired", "active", "active"]


# --- Types -------------------------------------------------------------------


def test_new_org_gets_default_persona_types(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Persona Seed Co")
    _enable_module(client, token, org["id"])
    types = client.get(_org_base(org["id"]) + "/persona-types", headers=auth_headers(token)).json()
    assert [t["name"] for t in types] == ["Primary", "Secondary", "Negative"]


def test_org_type_crud_and_in_use_blocking(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Types Co")
    h = auth_headers(token)
    base = _org_base(org["id"]) + "/persona-types"

    created = client.post(base, json={"name": "Edge case"}, headers=h)
    assert created.status_code == 201, created.text
    assert client.post(base, json={"name": "Edge case"}, headers=h).status_code == 400  # duplicate
    type_id = created.json()["id"]

    renamed = client.patch(f"{base}/{type_id}", json={"name": "Edge"}, headers=h)
    assert renamed.json()["name"] == "Edge"
    moved = client.post(f"{base}/{type_id}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200, moved.text

    # An org persona using the type blocks deletion.
    persona = _create_org_persona(client, token, org["id"], persona_type_id=type_id)
    assert persona["persona_type_name"] == "Edge"
    assert client.delete(f"{base}/{type_id}", headers=h).status_code == 409
    # Unused types delete cleanly.
    spare = client.post(base, json={"name": "Spare"}, headers=h).json()["id"]
    assert client.delete(f"{base}/{spare}", headers=h).status_code == 204


def test_project_type_override_local_and_disabled(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Project Types Co")
    h = auth_headers(token)
    base = _project_base(project["id"]) + "/persona-types"

    effective = client.get(base, headers=h).json()
    assert [t["name"] for t in effective] == ["Primary", "Secondary", "Negative"]
    assert all(t["source"] == "org" for t in effective)

    primary = effective[0]
    renamed = client.put(f"{base}/{primary['id']}", json={"name": "Core user"}, headers=h)
    assert renamed.status_code == 200, renamed.text
    local = client.post(base, json={"name": "Project-only"}, headers=h)
    assert local.status_code == 201, local.text
    names = [t["name"] for t in client.get(base, headers=h).json()]
    assert "Core user" in names and "Project-only" in names and "Primary" not in names

    # Using a project-local type, then trying to delete it.
    persona = _create_project_persona(client, token, project["id"], persona_type_id=local.json()["id"])
    assert persona["persona_type_name"] == "Project-only"
    assert client.delete(f"{base}/{local.json()['id']}", headers=h).status_code == 409

    # Disabled types are rejected on create.
    secondary = next(t for t in client.get(base, headers=h).json() if t["name"] == "Secondary")
    client.put(f"{base}/{secondary['id']}", json={"is_enabled": False}, headers=h)
    resp = client.post(
        _project_base(project["id"]) + "/personas", json={**_PAYLOAD, "persona_type_id": secondary["id"]}, headers=h,
    )
    assert resp.status_code == 400, resp.text


def test_persona_type_from_another_org_is_rejected(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona Types Iso A Co")
    other, other_token = create_org_admin_in(client, admin_token, "Persona Types Iso B Co")
    _enable_module(client, other_token, other["id"])
    foreign = client.get(_org_base(other["id"]) + "/persona-types", headers=auth_headers(other_token)).json()[0]["id"]
    resp = client.post(
        _project_base(project["id"]) + "/personas", json={**_PAYLOAD, "persona_type_id": foreign}, headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


# --- Weights -----------------------------------------------------------------


def test_weight_resolution_chain(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Persona Weight Chain Co")
    _enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Chain Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Chain Child", parent_project_id=parent["id"])
    h = auth_headers(token)
    persona = _create_org_persona(client, token, org["id"], weight=1.0)
    pid = persona["id"]

    def effective(project_id):
        return client.get(f"{_project_base(project_id)}/personas/{pid}", headers=h).json()["effective_weight"]

    def source(project_id):
        return client.get(f"{_project_base(project_id)}/personas/{pid}", headers=h).json()["weight_source"]

    assert effective(child["id"]) == 1.0 and source(child["id"]) == "persona"  # persona's own weight

    resp = client.put(f"{_project_base(parent['id'])}/personas/{pid}/weight", json={"weight": 3.0}, headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["weight_override"] == 3.0 and resp.json()["effective_weight"] == 3.0
    assert effective(child["id"]) == 3.0 and source(child["id"]) == "ancestor_project"  # nearest ancestor
    assert source(parent["id"]) == "project"

    client.put(f"{_project_base(child['id'])}/personas/{pid}/weight", json={"weight": 5.0}, headers=h)
    assert effective(child["id"]) == 5.0 and source(child["id"]) == "project"  # own override wins
    assert effective(parent["id"]) == 3.0

    cleared = client.delete(f"{_project_base(child['id'])}/personas/{pid}/weight", headers=h)
    assert cleared.json()["weight_override"] is None and cleared.json()["effective_weight"] == 3.0

    assert client.put(
        f"{_project_base(child['id'])}/personas/{pid}/weight", json={"weight": 0}, headers=h
    ).status_code == 422


def test_no_weight_anywhere_resolves_to_none(client, admin_token):
    _, project, token = _setup(client, admin_token, "Persona No Weight Co")
    persona = _create_project_persona(client, token, project["id"])
    assert persona["effective_weight"] is None and persona["weight_source"] == "none"


# --- RBAC --------------------------------------------------------------------


def test_plain_member_can_view_but_not_change(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Member Co")
    persona = _create_project_persona(client, token, project["id"])
    _, member = _add_member(client, token, org["id"], project["id"], "member@member.example.com")
    h = auth_headers(member)
    base = _project_base(project["id"])
    assert client.get(base + "/personas", headers=h).status_code == 200
    assert client.get(f"{base}/personas/{persona['id']}", headers=h).status_code == 200
    assert client.post(base + "/personas", json=_PAYLOAD, headers=h).status_code == 403
    assert client.put(f"{base}/personas/{persona['id']}", json={"goals": "x"}, headers=h).status_code == 403
    assert client.post(f"{base}/personas/{persona['id']}/retire", headers=h).status_code == 403
    assert client.put(f"{base}/personas/{persona['id']}/weight", json={"weight": 2}, headers=h).status_code == 403
    assert client.post(base + "/persona-types", json={"name": "Nope"}, headers=h).status_code == 403
    # Members can still discuss.
    assert client.post(f"{base}/personas/{persona['id']}/comments", json={"body": "hi"}, headers=h).status_code == 201


def test_persona_owner_role_grants_project_management(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Owner Role Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "owner@owner.example.com")
    _grant_project_role(client, token, project["id"], user_id, "persona_owner")
    assert client.post(_project_base(project["id"]) + "/personas", json=_PAYLOAD, headers=auth_headers(member)).status_code == 201


def test_org_persona_owner_role_is_org_scoped_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Org Owner Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "orgowner@owner.example.com")
    h = auth_headers(member)
    assert client.post(_org_base(org["id"]) + "/personas", json=_PAYLOAD, headers=h).status_code == 403
    _grant_org_role(client, token, org["id"], user_id, "org_persona_owner")
    assert client.post(_org_base(org["id"]) + "/personas", json=_PAYLOAD, headers=h).status_code == 201
    # Holding the org role doesn't grant project-scoped management.
    assert client.post(_project_base(project["id"]) + "/personas", json=_PAYLOAD, headers=h).status_code == 403


def test_persona_type_admin_role_gates_org_types(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Type Admin Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "typeadmin@owner.example.com")
    h = auth_headers(member)
    url = _org_base(org["id"]) + "/persona-types"
    assert client.post(url, json={"name": "Mine"}, headers=h).status_code == 403
    _grant_org_role(client, token, org["id"], user_id, "persona_type_admin")
    assert client.post(url, json={"name": "Mine"}, headers=h).status_code == 201


def test_fgac_manage_grant_satisfies_gate(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Fgac Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "fgac@owner.example.com")
    with SessionLocal() as db:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Persona editors", description="Test role.", scope="org",
        )
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("persona", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    assert client.post(_org_base(org["id"]) + "/personas", json=_PAYLOAD, headers=auth_headers(member)).status_code == 201


# --- Module gates and isolation ----------------------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Persona Disabled Co")
    project = create_project(client, token, org["id"], "Persona Disabled Project")
    assert client.get(_project_base(project["id"]) + "/personas", headers=auth_headers(token)).status_code == 404
    assert client.get(_org_base(org["id"]) + "/personas", headers=auth_headers(token)).status_code == 404


def test_disabled_subcomponent_is_404(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Subcomponent Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/persona", json={"enabled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert client.get(_project_base(project["id"]) + "/personas", headers=auth_headers(token)).status_code == 404
    assert client.get(_org_base(org["id"]) + "/personas", headers=auth_headers(token)).status_code == 404


def test_cross_tenant_persona_is_404(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Persona Iso A Co")
    org_b, project_b, token_b = _setup(client, admin_token, "Persona Iso B Co")
    org_persona = _create_org_persona(client, token_a, org_a["id"])
    project_persona = _create_project_persona(client, token_a, project_a["id"])
    # Org B can't reach org A's records through its own project or org routes.
    assert client.get(f"{_org_base(org_b['id'])}/personas/{org_persona['id']}", headers=auth_headers(token_b)).status_code == 404
    assert client.get(f"{_project_base(project_b['id'])}/personas/{org_persona['id']}", headers=auth_headers(token_b)).status_code == 404
    assert client.get(f"{_project_base(project_b['id'])}/personas/{project_persona['id']}", headers=auth_headers(token_b)).status_code == 404
    assert client.put(
        f"{_project_base(project_b['id'])}/personas/{project_persona['id']}/weight", json={"weight": 2}, headers=auth_headers(token_b),
    ).status_code == 404


def test_project_persona_not_visible_from_sibling_project(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Persona Sibling Co")
    project_b = create_project(client, token, org["id"], "Persona Sibling Project B")
    persona = _create_project_persona(client, token, project_a["id"])
    assert client.get(f"{_project_base(project_b['id'])}/personas/{persona['id']}", headers=auth_headers(token)).status_code == 404


# --- Comments and files ------------------------------------------------------


def test_comments_author_only_edit_and_attachments(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Comments Co")
    persona = _create_project_persona(client, token, project["id"])
    _, member = _add_member(client, token, org["id"], project["id"], "commenter@c.example.com")
    base = f"{_project_base(project['id'])}/personas/{persona['id']}/comments"

    comment = client.post(base, json={"body": "first"}, headers=auth_headers(member)).json()
    assert comment["author_display_name"] == "commenter"
    assert client.patch(f"{base}/{comment['id']}", json={"body": "hijack"}, headers=auth_headers(token)).status_code == 403
    edited = client.patch(f"{base}/{comment['id']}", json={"body": "edited"}, headers=auth_headers(member)).json()
    assert edited["body"] == "edited" and edited["edited_at"] is not None

    up = client.post(
        f"{base}/{comment['id']}/files", files={"file": ("n.txt", b"hello", "text/plain")}, headers=auth_headers(member),
    )
    assert up.status_code == 201, up.text
    assert len(client.get(base, headers=auth_headers(member)).json()[0]["attachments"]) == 1
    assert client.delete(f"{base}/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(token)).status_code == 403
    assert client.delete(f"{base}/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 204


def test_direct_file_attachment_project_and_org(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Files Co")
    h = auth_headers(token)
    for persona, base in (
        (_create_project_persona(client, token, project["id"]), f"{_project_base(project['id'])}/personas"),
        (_create_org_persona(client, token, org["id"]), f"{_org_base(org['id'])}/personas"),
    ):
        up = client.post(f"{base}/{persona['id']}/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h)
        assert up.status_code == 201, up.text
        assert len(client.get(f"{base}/{persona['id']}/files", headers=h).json()) == 1
        # Downloadable by a project/org member, i.e. the ownership hook resolves.
        assert client.get(f"/api/v1/files/{up.json()['id']}", headers=h).status_code == 200
        assert client.delete(f"{base}/{persona['id']}/files/{up.json()['id']}", headers=h).status_code == 204
        assert client.get(f"{base}/{persona['id']}/files", headers=h).json() == []


# --- Scoring-target hook -----------------------------------------------------


def test_scoring_target_provider_lists_active_personas_with_weights(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Hook Co")
    h = auth_headers(token)
    active = _create_org_persona(client, token, org["id"], name="Active one", weight=2.0)
    client.post(f"{_org_base(org['id'])}/personas/{active['id']}/activate", headers=h)
    _create_project_persona(client, token, project["id"], name="Draft one")
    archived = _create_project_persona(client, token, project["id"], name="Archived one")
    client.post(f"{_project_base(project['id'])}/personas/{archived['id']}/archive", headers=h)
    client.put(f"{_project_base(project['id'])}/personas/{active['id']}/weight", json={"weight": 4.0}, headers=h)

    with SessionLocal() as db:
        targets = {t.label: t for t in get_scoring_targets(db, uuid.UUID(project["id"]), "persona")}
    assert set(targets) == {"Active one", "Draft one"}  # archived excluded
    assert targets["Active one"].is_active is True and targets["Active one"].weight == 4.0
    assert targets["Draft one"].is_active is False and targets["Draft one"].weight is None


def test_scoring_target_provider_is_empty_when_module_disabled(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Hook Off Co")
    _create_project_persona(client, token, project["id"])
    client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": False}, headers=auth_headers(token))
    with SessionLocal() as db:
        assert get_scoring_targets(db, uuid.UUID(project["id"]), "persona") == []
        assert get_scoring_targets(db, uuid.UUID(project["id"]), "no_such_type") == []


# --- Hardening: non-finite weights and audit trail ---------------------------


def test_non_finite_weight_is_rejected(client, admin_token):
    """`inf`/`nan` would pass a plain `> 0` check or poison a weighted roll-up, so they're refused outright."""
    _, project, token = _setup(client, admin_token, "Persona Inf Weight Co")
    headers = {**auth_headers(token), "Content-Type": "application/json"}
    for literal in ("Infinity", "NaN"):
        resp = client.post(
            _project_base(project["id"]) + "/personas", content=f'{{"name": "Bad", "weight": {literal}}}', headers=headers,
        )
        assert resp.status_code == 422, (literal, resp.text)
    persona = _create_project_persona(client, token, project["id"])
    resp = client.put(
        f"{_project_base(project['id'])}/personas/{persona['id']}/weight", content='{"weight": Infinity}', headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_every_mutating_action_is_audit_logged(client, admin_token):
    """Create, update, lifecycle, archive, weight override, comment edit/attachment removal and type CRUD each leave an audit event."""
    from sqlalchemy import select

    from app.models.audit import AuditEvent

    org, project, token = _setup(client, admin_token, "Persona Audit Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    persona = _create_project_persona(client, token, project["id"])
    pid = f"{base}/personas/{persona['id']}"

    client.put(pid, json={"goals": "x"}, headers=h)
    client.post(pid + "/activate", headers=h)
    client.post(pid + "/retire", headers=h)
    client.post(pid + "/archive", headers=h)
    client.post(pid + "/unarchive", headers=h)
    client.put(pid + "/weight", json={"weight": 2}, headers=h)
    client.delete(pid + "/weight", headers=h)
    comment = client.post(pid + "/comments", json={"body": "a"}, headers=h).json()
    client.patch(f"{pid}/comments/{comment['id']}", json={"body": "b"}, headers=h)
    up = client.post(f"{pid}/comments/{comment['id']}/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h).json()
    client.delete(f"{pid}/comments/{comment['id']}/files/{up['id']}", headers=h)
    up2 = client.post(pid + "/files", files={"file": ("b.txt", b"x", "text/plain")}, headers=h).json()
    client.delete(f"{pid}/files/{up2['id']}", headers=h)
    local = client.post(base + "/persona-types", json={"name": "Audit local"}, headers=h).json()
    client.put(f"{base}/persona-types/{local['id']}", json={"is_enabled": False}, headers=h)
    client.delete(f"{base}/persona-types/{local['id']}", headers=h)
    org_type = client.post(_org_base(org["id"]) + "/persona-types", json={"name": "Audit org"}, headers=h).json()
    client.patch(f"{_org_base(org['id'])}/persona-types/{org_type['id']}", json={"is_active": False}, headers=h)
    client.delete(f"{_org_base(org['id'])}/persona-types/{org_type['id']}", headers=h)

    with SessionLocal() as db:
        persona_actions = {
            e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == persona["id"]))
        }
        type_actions = {
            (e.entity_type, e.action)
            for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type.in_(["project_persona_type", "persona_type_definition"])))
        }
    assert persona_actions >= {
        "created", "updated", "activated", "retired", "archived", "unarchived", "weight_override_set",
        "weight_override_cleared", "comment_added", "comment_edited", "comment_file_attached", "comment_file_removed",
        "file_attached", "file_unlinked",
    }
    assert type_actions >= {
        ("project_persona_type", "created"), ("project_persona_type", "updated"), ("project_persona_type", "deleted"),
        ("persona_type_definition", "created"), ("persona_type_definition", "updated"), ("persona_type_definition", "deleted"),
    }
