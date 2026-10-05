"""Tests for the Stakeholders & Personas module's Phase 2 backend API
(docs/plans/module-02-stakeholders-and-personas-plan.md — Stakeholder Need),
through the real HTTP endpoints.

Covers: project-scoped CRUD, partial update, version history, the lifecycle,
the "has need" links from Stakeholders and Personas (both directions, with
tenancy filtering), the "gives rise to" links to Requirements (same-project
only), RBAC composition (owner role, FGAC grant, view-only members, no org
role), module/sub-component gates, cross-tenant isolation, comments/files,
audit logging, erasure of a linked Stakeholder, the bundle round-trip and
registration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.models.relationship import ArtefactLink
from app.modules.stakeholders.models import StakeholderNeed, StakeholderNeedVersion
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _grant_project_role,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_org_user, create_project

_PAYLOAD = {
    "name": "Diagnose faults quickly",
    "description": "I need to find out what is wrong with a unit without a laptop.",
    "rationale": "Observed on site visits; each delay costs an hour.",
}


def _needs(project_id) -> str:
    return _project_base(project_id) + "/needs"


def _create_need(client, token, project_id, **extra) -> dict:
    resp = client.post(_needs(project_id), json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_requirement(client, token, project_id, name="Remote diagnostics in 30 seconds") -> dict:
    component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- CRUD, versions, lifecycle -----------------------------------------------


def test_need_crud_versions_and_clearing_owner(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Crud Co")
    other_org, other_token = create_org_admin_in(client, admin_token, "Need Crud Other Co")
    owner_id = create_org_user(client, other_token, other_org["id"], "outsider@need-crud.example.com")  # not in this org
    created = _create_need(client, token, project["id"])
    assert created["project_id"] == project["id"] and created["status"] == "draft" and created["version_number"] == 1
    url = f"{_needs(project['id'])}/{created['id']}"

    resp = client.put(url, json={"rationale": "Refined", "change_note": "why"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rationale"] == "Refined" and body["name"] == _PAYLOAD["name"] and body["version_number"] == 2
    versions = client.get(url + "/versions", headers=auth_headers(token)).json()
    assert [v["version_number"] for v in versions] == [1, 2] and versions[1]["change_note"] == "why"

    assert client.put(url, json={"name": None}, headers=auth_headers(token)).status_code == 422
    assert client.put(url, json={"owner_id": owner_id}, headers=auth_headers(token)).status_code == 400
    assert [n["id"] for n in client.get(_needs(project["id"]), headers=auth_headers(token)).json()] == [created["id"]]


def test_lifecycle_and_archive(client, admin_token):
    _, project, token = _setup(client, admin_token, "Need Lifecycle Co")
    h = auth_headers(token)
    need = _create_need(client, token, project["id"])
    url = f"{_needs(project['id'])}/{need['id']}"
    assert client.post(url + "/activate", headers=h).json()["status"] == "active"
    assert client.post(url + "/activate", headers=h).status_code == 409
    assert client.post(url + "/retire", json={"comment": "obsolete"}, headers=h).json()["status"] == "retired"
    assert client.post(url + "/activate", headers=h).json()["status"] == "active"

    assert client.post(url + "/archive", headers=h).json()["is_archived"] is True
    assert client.get(_needs(project["id"]), headers=h).json() == []
    assert len(client.get(_needs(project["id"]) + "?include_archived=true", headers=h).json()) == 1
    assert client.post(url + "/unarchive", headers=h).json()["is_archived"] is False


# --- "Has need" --------------------------------------------------------------


def test_has_need_links_from_stakeholders_and_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Holders Co")
    h = auth_headers(token)
    need = _create_need(client, token, project["id"])
    other = _create_need(client, token, project["id"], name="Other need")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    org_persona = _create_org_persona(client, token, org["id"])
    url = f"{_needs(project['id'])}/{need['id']}/holders"

    for kind, record in (("stakeholder", stakeholder), ("persona", org_persona)):
        resp = client.post(url, json={"kind": kind, "id": record["id"]}, headers=h)
        assert resp.status_code == 201, resp.text
        assert resp.json()["name"] == record["name"] and resp.json()["kind"] == kind
        assert client.post(url, json={"kind": kind, "id": record["id"]}, headers=h).status_code == 409
    assert {(r["kind"], r["id"]) for r in client.get(url, headers=h).json()} == {
        ("stakeholder", stakeholder["id"]), ("persona", org_persona["id"]),
    }

    held = client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/needs", headers=h).json()
    assert [n["id"] for n in held] == [need["id"]] and held[0]["status"] == "draft"
    assert [n["id"] for n in client.get(f"{_project_base(project['id'])}/personas/{org_persona['id']}/needs", headers=h).json()] == [need["id"]]
    assert other["id"] not in {n["id"] for n in held}

    assert client.delete(f"{url}/stakeholder/{stakeholder['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/stakeholder/{stakeholder['id']}", headers=h).status_code == 404
    assert client.delete(f"{url}/bogus/{stakeholder['id']}", headers=h).status_code == 404
    assert client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/needs", headers=h).json() == []


def test_shared_org_holder_only_shows_this_projects_needs(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Need Shared Holder Co")
    project_b = create_project(client, token, org["id"], "Need Shared Holder B")
    h = auth_headers(token)
    org_stakeholder = _create_org_stakeholder(client, token, org["id"])
    need_a = _create_need(client, token, project_a["id"])
    need_b = _create_need(client, token, project_b["id"])
    for project, need in ((project_a, need_a), (project_b, need_b)):
        resp = client.post(
            f"{_needs(project['id'])}/{need['id']}/holders", json={"kind": "stakeholder", "id": org_stakeholder["id"]}, headers=h,
        )
        assert resp.status_code == 201, resp.text
    held = client.get(f"{_project_base(project_a['id'])}/stakeholders/{org_stakeholder['id']}/needs", headers=h).json()
    assert [n["id"] for n in held] == [need_a["id"]]


def test_holder_must_be_visible_to_the_project(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Need Holder Vis Co")
    project_b = create_project(client, token, org["id"], "Need Holder Vis B")
    other_org, other_project, other_token = _setup(client, admin_token, "Need Holder Vis Other Co")
    h = auth_headers(token)
    need = _create_need(client, token, project_a["id"])
    url = f"{_needs(project_a['id'])}/{need['id']}/holders"
    sibling_stakeholder = _create_project_stakeholder(client, token, project_b["id"])
    sibling_persona = _create_project_persona(client, token, project_b["id"])
    foreign = _create_org_stakeholder(client, other_token, other_org["id"])
    for kind, record in (("stakeholder", sibling_stakeholder), ("persona", sibling_persona), ("stakeholder", foreign)):
        assert client.post(url, json={"kind": kind, "id": record["id"]}, headers=h).status_code == 404


# --- "Gives rise to" ---------------------------------------------------------


def test_need_gives_rise_to_requirement(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Requirement Co")
    h = auth_headers(token)
    need = _create_need(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    url = f"{_needs(project['id'])}/{need['id']}/requirements"

    resp = client.post(url, json={"requirement_id": requirement["id"]}, headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["unique_code"] == requirement["unique_code"] and resp.json()["title"] == requirement["name"]
    assert client.post(url, json={"requirement_id": requirement["id"]}, headers=h).status_code == 409
    assert [r["id"] for r in client.get(url, headers=h).json()] == [requirement["id"]]
    assert client.delete(f"{url}/{requirement['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{requirement['id']}", headers=h).status_code == 404
    assert client.get(url, headers=h).json() == []


def test_requirement_must_be_in_the_same_project(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Need Req Scope Co")
    project_b = create_project(client, token, org["id"], "Need Req Scope B")
    need = _create_need(client, token, project_a["id"])
    foreign = _create_requirement(client, token, project_b["id"])
    resp = client.post(
        f"{_needs(project_a['id'])}/{need['id']}/requirements", json={"requirement_id": foreign["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_erasing_a_stakeholder_removes_its_has_need_links_but_not_the_need(client, admin_token):
    _, project, token = _setup(client, admin_token, "Need Erase Co")
    h = auth_headers(token)
    need = _create_need(client, token, project["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    client.post(f"{_needs(project['id'])}/{need['id']}/holders", json={"kind": "stakeholder", "id": stakeholder["id"]}, headers=h)
    assert client.delete(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", headers=h).status_code == 204
    assert client.get(f"{_needs(project['id'])}/{need['id']}", headers=h).status_code == 200
    assert client.get(f"{_needs(project['id'])}/{need['id']}/holders", headers=h).json() == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ArtefactLink).where(ArtefactLink.source_id == uuid.UUID(stakeholder["id"]))) == 0


# --- RBAC, gates, isolation --------------------------------------------------


def test_owner_role_gates_writes_and_members_can_read(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Rbac Co")
    need = _create_need(client, token, project["id"])
    user_id, member = _add_member(client, token, org["id"], project["id"], "needs@rbac.example.com")
    h = auth_headers(member)
    url = f"{_needs(project['id'])}/{need['id']}"
    assert client.get(url, headers=h).status_code == 200
    assert client.post(_needs(project["id"]), json=_PAYLOAD, headers=h).status_code == 403
    for method, path, body in (
        ("put", url, {"name": "x"}), ("post", url + "/activate", None), ("post", url + "/archive", None),
        ("post", url + "/holders", {"kind": "persona", "id": str(uuid.uuid4())}),
        ("post", url + "/requirements", {"requirement_id": str(uuid.uuid4())}),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=h, **kwargs).status_code == 403, path
    upload = client.post(url + "/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h)
    assert upload.status_code == 403
    _grant_project_role(client, token, project["id"], user_id, "stakeholder_need_owner")
    assert client.post(_needs(project["id"]), json=_PAYLOAD, headers=h).status_code == 201


def test_other_module_roles_confer_nothing_on_needs(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Role Iso Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "persona-only@need-iso.example.com")
    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    _grant_project_role(client, token, project["id"], user_id, "persona_owner")
    assert client.post(_needs(project["id"]), json=_PAYLOAD, headers=auth_headers(member)).status_code == 403


def test_fgac_manage_grant_satisfies_gate(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Fgac Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "fgac@need.example.com")
    with SessionLocal() as db:
        role = CustomRoleDefinition(organization_id=uuid.UUID(org["id"]), name="Need editors", description="Test.", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("stakeholder_need", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    assert client.post(_needs(project["id"]), json=_PAYLOAD, headers=auth_headers(member)).status_code == 201


def test_disabled_module_and_subcomponent_are_404(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Need Disabled Co")
    project = create_project(client, token, org["id"], "Need Disabled Project")
    assert client.get(_needs(project["id"]), headers=auth_headers(token)).status_code == 404

    org2, project2, token2 = _setup(client, admin_token, "Need Subcomponent Co")
    h = auth_headers(token2)
    resp = client.put(f"/api/v1/orgs/{org2['id']}/modules/stakeholders/subcomponents/stakeholder_need", json={"enabled": False}, headers=h)
    assert resp.status_code == 200, resp.text
    assert client.get(_needs(project2["id"]), headers=h).status_code == 404
    assert client.get(_project_base(project2["id"]) + "/stakeholders", headers=h).status_code == 200


def test_cross_tenant_and_sibling_needs_are_404(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Need Iso A Co")
    org_b, project_b, token_b = _setup(client, admin_token, "Need Iso B Co")
    sibling = create_project(client, token_a, org_a["id"], "Need Iso Sibling")
    need = _create_need(client, token_a, project_a["id"])
    for token, project_id in ((token_b, project_b["id"]), (token_a, sibling["id"])):
        for suffix in ("", "/versions", "/comments", "/holders", "/requirements", "/files"):
            resp = client.get(f"{_needs(project_id)}/{need['id']}{suffix}", headers=auth_headers(token))
            assert resp.status_code == 404, suffix


# --- Comments, files ---------------------------------------------------------


def test_comments_and_files(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Attach Co")
    need = _create_need(client, token, project["id"])
    _, member = _add_member(client, token, org["id"], project["id"], "commenter@need.example.com")
    base = f"{_needs(project['id'])}/{need['id']}"
    comment = client.post(base + "/comments", json={"body": "first"}, headers=auth_headers(member)).json()
    assert comment["need_id"] == need["id"]
    assert client.patch(f"{base}/comments/{comment['id']}", json={"body": "x"}, headers=auth_headers(token)).status_code == 403
    up = client.post(
        f"{base}/comments/{comment['id']}/files", files={"file": ("n.txt", b"hello", "text/plain")}, headers=auth_headers(member),
    )
    assert up.status_code == 201, up.text
    assert client.get(f"/api/v1/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 200
    assert client.delete(f"{base}/comments/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 204

    h = auth_headers(token)
    direct = client.post(base + "/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h)
    assert direct.status_code == 201, direct.text
    assert len(client.get(base + "/files", headers=h).json()) == 1
    assert client.get(f"/api/v1/files/{direct.json()['id']}", headers=h).status_code == 200
    assert client.delete(f"{base}/files/{direct.json()['id']}", headers=h).status_code == 204


# --- Org deletion, audit, bundle, registration --------------------------------


def test_deleting_an_org_removes_needs(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Org Delete Co")
    need = _create_need(client, token, project["id"])
    stakeholder = _create_org_stakeholder(client, token, org["id"])
    client.post(f"{_needs(project['id'])}/{need['id']}/holders", json={"kind": "stakeholder", "id": stakeholder["id"]}, headers=auth_headers(token))
    resp = client.request("DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StakeholderNeed)) == 0
        assert db.scalar(select(func.count()).select_from(StakeholderNeedVersion)) == 0
        assert db.scalar(select(func.count()).select_from(ArtefactLink).where(ArtefactLink.target_id == uuid.UUID(need["id"]))) == 0


def test_every_mutating_action_is_audit_logged(client, admin_token):
    org, project, token = _setup(client, admin_token, "Need Audit Co")
    h = auth_headers(token)
    need = _create_need(client, token, project["id"])
    persona = _create_project_persona(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    url = f"{_needs(project['id'])}/{need['id']}"
    client.put(url, json={"rationale": "x"}, headers=h)
    client.post(url + "/activate", headers=h)
    client.post(url + "/retire", headers=h)
    client.post(url + "/archive", headers=h)
    client.post(url + "/unarchive", headers=h)
    client.post(url + "/holders", json={"kind": "persona", "id": persona["id"]}, headers=h)
    client.delete(f"{url}/holders/persona/{persona['id']}", headers=h)
    client.post(url + "/requirements", json={"requirement_id": requirement["id"]}, headers=h)
    client.delete(f"{url}/requirements/{requirement['id']}", headers=h)
    comment = client.post(url + "/comments", json={"body": "a"}, headers=h).json()
    client.patch(f"{url}/comments/{comment['id']}", json={"body": "b"}, headers=h)
    with SessionLocal() as db:
        actions = {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == need["id"]))}
    assert actions >= {
        "created", "updated", "activated", "retired", "archived", "unarchived", "holder_added", "holder_removed",
        "requirement_linked", "requirement_unlinked", "comment_added", "comment_edited",
    }


def test_need_is_a_registered_artefact_type_with_mcp_tools():
    from app.modules.registry import get_all_registered_artefact_types
    from app.modules.stakeholders.module import MODULE_DEFINITION

    assert "stakeholder_need" in get_all_registered_artefact_types()
    names = {t.name for t in MODULE_DEFINITION.mcp_tools}
    assert {
        "list_stakeholder_needs", "get_stakeholder_need", "create_stakeholder_need", "update_stakeholder_need",
        "activate_stakeholder_need", "retire_stakeholder_need",
    } <= names
    assert any(r.role_key == "stakeholder_need_owner" and r.scope == "project" for r in MODULE_DEFINITION.roles)
