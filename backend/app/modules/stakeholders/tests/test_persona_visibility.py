"""Tests for project persona visibility (Module 2 Phase 3b, the Persona half of
docs/plans/module-02-stakeholders-and-personas-plan.md): a project can hide an
org Persona from itself, reversibly, without touching the shared record.
`test_stakeholder_visibility.py` covers the Stakeholder half; the shared
resolution code is exercised by both.

Covers: hide/show/reset and the list/detail effects, the effect on scoring
targets, needs, relationships and "represents" links (hidden means unlinkable
and unlisted, but existing links survive an un-hide), nearest-row-wins
hierarchy resolution, scope/tenancy rules, RBAC, the audit trail, and bundle
round-tripping.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.registry import get_scoring_targets
from app.modules.stakeholders.tests.test_need_api import _create_need
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _enable_module,
    _grant_project_role,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_relationship_api import _rels
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _vis(project_id, persona_id) -> str:
    return f"{_project_base(project_id)}/personas/{persona_id}/visibility"


def _names(client, token, project_id, query="") -> list[str]:
    resp = client.get(f"{_project_base(project_id)}/personas{query}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [p["name"] for p in resp.json()]


def _hide(client, token, project_id, persona_id, hidden=True):
    return client.put(_vis(project_id, persona_id), json={"hidden": hidden}, headers=auth_headers(token))


# --- Hide / show / reset -----------------------------------------------------


def test_hide_removes_from_list_and_detail_and_reset_restores(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Basic Co")
    h = auth_headers(token)
    shared = _create_org_persona(client, token, org["id"], name="Shared Technician")
    own = _create_project_persona(client, token, project["id"], name="Local Persona")
    base = _project_base(project["id"])
    assert set(_names(client, token, project["id"])) == {"Shared Technician", "Local Persona"}

    resp = _hide(client, token, project["id"], shared["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_hidden"] is True and resp.json()["hidden_override"] is True
    assert resp.json()["hidden_source"] == "project"
    assert _names(client, token, project["id"]) == ["Local Persona"]
    assert client.get(f"{base}/personas/{shared['id']}", headers=h).status_code == 404

    flagged = {p["name"]: p for p in client.get(base + "/personas?include_hidden=true", headers=h).json()}
    assert flagged["Shared Technician"]["project_hidden"] is True and flagged["Local Persona"]["project_hidden"] is None
    assert own["id"] == flagged["Local Persona"]["id"]

    # The shared record is untouched: another project still sees it, and the org list still has it.
    other = create_project(client, token, org["id"], "Other Persona Visibility Project")
    assert "Shared Technician" in _names(client, token, other["id"])
    assert [p["name"] for p in client.get(_org_base(org["id"]) + "/personas", headers=h).json()] == ["Shared Technician"]

    resp = client.delete(_vis(project["id"], shared["id"]), headers=h)
    assert resp.status_code == 200 and resp.json()["project_hidden"] is False and resp.json()["hidden_override"] is None
    assert set(_names(client, token, project["id"])) == {"Shared Technician", "Local Persona"}
    assert client.delete(_vis(project["id"], shared["id"]), headers=h).status_code == 200  # no-op


def test_only_org_personas_of_the_projects_org_can_be_hidden(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Scope Co")
    own = _create_project_persona(client, token, project["id"])
    assert _hide(client, token, project["id"], own["id"]).status_code == 404  # archive a project's own instead
    assert _hide(client, token, project["id"], str(uuid.uuid4())).status_code == 404
    other_org, _, other_token = _setup(client, admin_token, "Persona Visibility Scope Other Co")
    foreign = _create_org_persona(client, other_token, other_org["id"])
    assert _hide(client, token, project["id"], foreign["id"]).status_code == 404
    assert client.delete(_vis(project["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404
    shared = _create_org_persona(client, token, org["id"])
    assert client.put(_vis(project["id"], shared["id"]), json={"hidden": "maybe"}, headers=auth_headers(token)).status_code == 422


# --- Effect on scoring and links ---------------------------------------------


def test_hidden_persona_is_not_a_scoring_target_until_shown(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Scoring Co")
    shared = _create_org_persona(client, token, org["id"], name="Scored Persona")
    client.post(f"{_org_base(org['id'])}/personas/{shared['id']}/activate", json={}, headers=auth_headers(token))

    def targets():
        with SessionLocal() as db:
            return {t.label for t in get_scoring_targets(db, uuid.UUID(project["id"]), "persona")}

    assert targets() == {"Scored Persona"}
    _hide(client, token, project["id"], shared["id"])
    assert targets() == set()
    client.delete(_vis(project["id"], shared["id"]), headers=auth_headers(token))
    assert targets() == {"Scored Persona"}


def test_hidden_persona_cannot_be_linked_and_existing_links_survive_unhide(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Links Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    shared = _create_org_persona(client, token, org["id"], name="Shared Persona")
    holder = _create_org_stakeholder(client, token, org["id"], name="Regulator")
    need = _create_need(client, token, project["id"])
    holders = f"{base}/needs/{need['id']}/holders"
    assert client.post(holders, json={"kind": "persona", "id": shared["id"]}, headers=h).status_code == 201
    represents = client.post(
        f"{_org_base(org['id'])}/stakeholders/{holder['id']}/personas", json={"persona_id": shared["id"]}, headers=h
    )
    assert represents.status_code == 201, represents.text

    assert _hide(client, token, project["id"], shared["id"]).status_code == 200

    assert client.get(holders, headers=h).json() == []
    second = _create_need(client, token, project["id"], name="Second need")
    assert client.post(f"{base}/needs/{second['id']}/holders", json={"kind": "persona", "id": shared["id"]}, headers=h).status_code == 404
    assert client.get(_rels(project["id"], "persona", shared["id"]), headers=h).status_code == 404
    assert client.get(f"{base}/personas/{shared['id']}/needs", headers=h).status_code == 404
    assert client.get(f"{base}/personas/{shared['id']}/stakeholders", headers=h).status_code == 404
    # The stakeholder's own view omits the hidden persona, and a stakeholder cannot represent it afresh.
    assert client.get(f"{base}/stakeholders/{holder['id']}/personas", headers=h).json() == []
    own_stakeholder = _create_project_stakeholder(client, token, project["id"], name="Local Person")
    assert client.post(
        f"{base}/stakeholders/{own_stakeholder['id']}/personas", json={"persona_id": shared["id"]}, headers=h
    ).status_code == 404

    assert client.delete(_vis(project["id"], shared["id"]), headers=h).status_code == 200
    assert [(r["kind"], r["id"]) for r in client.get(holders, headers=h).json()] == [("persona", shared["id"])]
    assert [s["name"] for s in client.get(f"{base}/personas/{shared['id']}/stakeholders", headers=h).json()] == ["Regulator"]
    assert [p["name"] for p in client.get(f"{base}/stakeholders/{holder['id']}/personas", headers=h).json()] == ["Shared Persona"]


def test_stakeholder_side_represents_list_omits_hidden_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Represents Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    shared = _create_org_persona(client, token, org["id"], name="Hidden Persona")
    kept = _create_org_persona(client, token, org["id"], name="Kept Persona")
    holder = _create_project_stakeholder(client, token, project["id"], name="Local Person")
    for persona in (shared, kept):
        assert client.post(f"{base}/stakeholders/{holder['id']}/personas", json={"persona_id": persona["id"]}, headers=h).status_code == 201
    url = f"{base}/stakeholders/{holder['id']}/personas"
    assert {p["name"] for p in client.get(url, headers=h).json()} == {"Hidden Persona", "Kept Persona"}
    _hide(client, token, project["id"], shared["id"])
    assert {p["name"] for p in client.get(url, headers=h).json()} == {"Kept Persona"}
    # The link can still be cleaned up from the stakeholder's side.
    assert client.delete(f"{url}/{shared['id']}", headers=h).status_code == 204


# --- Hierarchy ---------------------------------------------------------------


def test_visibility_resolves_nearest_override_up_the_hierarchy(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Persona Visibility Chain Co")
    _enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Chain Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Chain Child", parent_project_id=parent["id"], can_be_parent=True)
    grandchild = create_project(client, token, org["id"], "Chain Grandchild", parent_project_id=child["id"])
    shared = _create_org_persona(client, token, org["id"], name="Shared Persona")
    pid = shared["id"]

    def state(project_id):
        body = client.get(f"{_project_base(project_id)}/personas?include_hidden=true", headers=auth_headers(token)).json()[0]
        return body["project_hidden"], body["hidden_source"], body["hidden_override"]

    assert state(grandchild["id"]) == (False, None, None)
    _hide(client, token, parent["id"], pid)
    assert state(parent["id"]) == (True, "project", True)
    assert state(child["id"]) == (True, "ancestor_project", None)
    assert state(grandchild["id"]) == (True, "ancestor_project", None)

    assert _hide(client, token, child["id"], pid, hidden=False).status_code == 200
    assert state(child["id"]) == (False, "project", False)
    assert state(grandchild["id"]) == (False, "ancestor_project", None)
    assert _names(client, token, grandchild["id"]) == ["Shared Persona"]
    assert _names(client, token, parent["id"]) == []

    client.delete(_vis(child["id"], pid), headers=auth_headers(token))
    assert state(child["id"]) == (True, "ancestor_project", None)


def test_persona_and_stakeholder_overrides_are_independent(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Independent Co")
    persona = _create_org_persona(client, token, org["id"], name="Shared Persona")
    stakeholder = _create_org_stakeholder(client, token, org["id"], name="Shared Stakeholder")
    _hide(client, token, project["id"], persona["id"])
    assert _names(client, token, project["id"]) == []
    resp = client.get(_project_base(project["id"]) + "/stakeholders", headers=auth_headers(token))
    assert [s["name"] for s in resp.json()] == [stakeholder["name"]]


# --- RBAC, audit, bundles ----------------------------------------------------


def test_hiding_needs_the_persona_manage_permission(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Rbac Co")
    shared = _create_org_persona(client, token, org["id"])
    user_id, member = _add_member(client, token, org["id"], project["id"], "member@persona-visibility-rbac.example.com")
    assert _hide(client, member, project["id"], shared["id"]).status_code == 403
    assert client.delete(_vis(project["id"], shared["id"]), headers=auth_headers(member)).status_code == 403
    assert len(_names(client, member, project["id"])) == 1  # view-only members still read

    _grant_project_role(client, token, project["id"], user_id, "persona_owner")
    assert _hide(client, member, project["id"], shared["id"]).status_code == 200
    assert _names(client, member, project["id"]) == []


def test_visibility_changes_are_audit_logged(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Audit Co")
    shared = _create_org_persona(client, token, org["id"], name="Audited Persona")
    _hide(client, token, project["id"], shared["id"])
    _hide(client, token, project["id"], shared["id"], hidden=False)
    client.delete(_vis(project["id"], shared["id"]), headers=auth_headers(token))
    client.delete(_vis(project["id"], shared["id"]), headers=auth_headers(token))  # no-op: not logged
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == shared["id"], AuditEvent.action.like("visibility_%")
        ).order_by(AuditEvent.created_at)).all()
    assert [e.action for e in events] == ["visibility_hidden", "visibility_shown", "visibility_reset"]
    assert all(str(e.project_id) == project["id"] for e in events)


def test_project_bundle_round_trips_persona_visibility_and_warns_when_target_lacks_the_persona(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Visibility Bundle Co")
    h = auth_headers(token)
    hidden = _create_org_persona(client, token, org["id"], name="Hidden Persona")
    shown = _create_org_persona(client, token, org["id"], name="Re-shown Persona")
    _hide(client, token, project["id"], hidden["id"])
    _hide(client, token, project["id"], shown["id"], hidden=False)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert {(v["org_persona_name"], v["hidden"]) for v in exported["project_persona_visibility"]} == {
        ("Hidden Persona", True), ("Re-shown Persona", False),
    }

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Persona Visibility Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_id = imported.json()["project"]["id"]
    assert _names(client, token, new_id) == ["Re-shown Persona"]
    assert set(_names(client, token, new_id, "?include_hidden=true")) == {"Hidden Persona", "Re-shown Persona"}

    other, _, other_token = _setup(client, admin_token, "Persona Visibility Bundle Target Co")
    foreign = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Persona Visibility Foreign"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert foreign.status_code == 201, foreign.text
    assert sum("persona visibility override was skipped" in w for w in foreign.json()["warnings"]) == 2
