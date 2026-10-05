"""Tests for project stakeholder visibility (Module 2 Phase 3b,
docs/plans/module-02-stakeholders-and-personas-plan.md): a project can hide an
org Stakeholder from itself, reversibly, without touching the shared record.

Covers: hide/show/reset and the list/detail effects, the effect on needs,
relationships and "represents" links (hidden means unlinkable and unlisted, but
existing links survive an un-hide), the nearest-row-wins hierarchy resolution,
scope/tenancy rules, RBAC, the audit trail, bundle round-tripping and cascade
on erasure.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.stakeholders.models import ProjectStakeholderVisibility
from app.modules.stakeholders.tests.test_need_api import _create_need, _create_requirement
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _enable_module,
    _grant_project_role,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_relationship_api import _add, _rels
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _vis(project_id, stakeholder_id) -> str:
    return f"{_project_base(project_id)}/stakeholders/{stakeholder_id}/visibility"


def _names(client, token, project_id, query="") -> list[str]:
    resp = client.get(f"{_project_base(project_id)}/stakeholders{query}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [s["name"] for s in resp.json()]


def _hide(client, token, project_id, stakeholder_id, hidden=True):
    return client.put(_vis(project_id, stakeholder_id), json={"hidden": hidden}, headers=auth_headers(token))


# --- Hide / show / reset -----------------------------------------------------


def test_hide_removes_from_list_and_detail_and_reset_restores(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Basic Co")
    h = auth_headers(token)
    shared = _create_org_stakeholder(client, token, org["id"], name="Regulator")
    own = _create_project_stakeholder(client, token, project["id"], name="Local Person")
    base = _project_base(project["id"])
    assert set(_names(client, token, project["id"])) == {"Regulator", "Local Person"}

    resp = _hide(client, token, project["id"], shared["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_hidden"] is True and resp.json()["hidden_override"] is True
    assert resp.json()["hidden_source"] == "project"
    assert _names(client, token, project["id"]) == ["Local Person"]
    assert client.get(f"{base}/stakeholders/{shared['id']}", headers=h).status_code == 404

    # The manage UI can still see it, flagged; the project's own stakeholder carries no flag.
    flagged = {s["name"]: s for s in client.get(base + "/stakeholders?include_hidden=true", headers=h).json()}
    assert flagged["Regulator"]["project_hidden"] is True and flagged["Local Person"]["project_hidden"] is None
    assert own["id"] == flagged["Local Person"]["id"]

    # The shared record is untouched: another project still sees it, and the org list still has it.
    other = create_project(client, token, org["id"], "Other Visibility Project")
    assert "Regulator" in _names(client, token, other["id"])
    assert [s["name"] for s in client.get(_org_base(org["id"]) + "/stakeholders", headers=h).json()] == ["Regulator"]

    resp = client.delete(_vis(project["id"], shared["id"]), headers=h)
    assert resp.status_code == 200 and resp.json()["project_hidden"] is False and resp.json()["hidden_override"] is None
    assert set(_names(client, token, project["id"])) == {"Regulator", "Local Person"}
    # Resetting again is a harmless no-op.
    assert client.delete(_vis(project["id"], shared["id"]), headers=h).status_code == 200


def test_unflagged_org_stakeholder_reports_visible(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Flag Co")
    shared = _create_org_stakeholder(client, token, org["id"])
    listed = client.get(_project_base(project["id"]) + "/stakeholders", headers=auth_headers(token)).json()
    assert listed[0]["id"] == shared["id"]
    assert listed[0]["project_hidden"] is False and listed[0]["hidden_override"] is None and listed[0]["hidden_source"] is None


def test_only_org_stakeholders_of_the_projects_org_can_be_hidden(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Scope Co")
    own = _create_project_stakeholder(client, token, project["id"])
    assert _hide(client, token, project["id"], own["id"]).status_code == 404  # archive/erase a project's own instead
    assert _hide(client, token, project["id"], str(uuid.uuid4())).status_code == 404
    other_org, _, other_token = _setup(client, admin_token, "Visibility Scope Other Co")
    foreign = _create_org_stakeholder(client, other_token, other_org["id"])
    assert _hide(client, token, project["id"], foreign["id"]).status_code == 404
    assert client.delete(_vis(project["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404
    shared = _create_org_stakeholder(client, token, org["id"])
    assert client.put(_vis(project["id"], shared["id"]), json={"hidden": "maybe"}, headers=auth_headers(token)).status_code == 422
    assert client.put(_vis(project["id"], shared["id"]), json={}, headers=auth_headers(token)).status_code == 422


# --- Effect on links ---------------------------------------------------------


def test_hidden_stakeholder_cannot_be_linked_and_existing_links_survive_unhide(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Links Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    shared = _create_org_stakeholder(client, token, org["id"], name="Regulator")
    need = _create_need(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    holders = f"{base}/needs/{need['id']}/holders"

    # Set up a need link and a relationship while visible.
    assert client.post(holders, json={"kind": "stakeholder", "id": shared["id"]}, headers=h).status_code == 201
    rel = _add(client, token, project["id"], "stakeholder", shared["id"], "provides_requirement", "requirement", requirement["id"])
    assert rel.status_code == 201, rel.text

    assert _hide(client, token, project["id"], shared["id"]).status_code == 200

    # Not listed, not addable, not reachable through any project endpoint.
    assert client.get(holders, headers=h).json() == []
    second_need = _create_need(client, token, project["id"], name="Second need")
    assert client.post(
        f"{base}/needs/{second_need['id']}/holders", json={"kind": "stakeholder", "id": shared["id"]}, headers=h
    ).status_code == 404
    assert _add(client, token, project["id"], "stakeholder", shared["id"], "reviews", "requirement", requirement["id"]).status_code == 404
    assert client.get(_rels(project["id"], "stakeholder", shared["id"]), headers=h).status_code == 404
    assert client.get(f"{base}/stakeholders/{shared['id']}/needs", headers=h).status_code == 404
    assert client.get(f"{base}/stakeholders/{shared['id']}/personas", headers=h).status_code == 404

    # Un-hiding restores the existing links exactly (nothing was deleted).
    assert client.delete(_vis(project["id"], shared["id"]), headers=h).status_code == 200
    assert [(r["kind"], r["id"]) for r in client.get(holders, headers=h).json()] == [("stakeholder", shared["id"])]
    assert len(client.get(_rels(project["id"], "stakeholder", shared["id"]), headers=h).json()) == 1


def test_persona_side_reverse_list_omits_hidden_stakeholders(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Reverse Co")
    h = auth_headers(token)
    persona = _create_org_persona(client, token, org["id"], name="Shared persona")
    shared = _create_org_stakeholder(client, token, org["id"], name="Regulator")
    visible = _create_org_stakeholder(client, token, org["id"], name="Visible")
    for s in (shared, visible):
        resp = client.post(f"{_org_base(org['id'])}/stakeholders/{s['id']}/personas", json={"persona_id": persona["id"]}, headers=h)
        assert resp.status_code == 201, resp.text
    url = f"{_project_base(project['id'])}/personas/{persona['id']}/stakeholders"
    assert {s["name"] for s in client.get(url, headers=h).json()} == {"Regulator", "Visible"}
    _hide(client, token, project["id"], shared["id"])
    assert {s["name"] for s in client.get(url, headers=h).json()} == {"Visible"}


# --- Hierarchy ---------------------------------------------------------------


def test_visibility_resolves_nearest_override_up_the_hierarchy(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Visibility Chain Co")
    _enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Chain Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Chain Child", parent_project_id=parent["id"], can_be_parent=True)
    grandchild = create_project(client, token, org["id"], "Chain Grandchild", parent_project_id=child["id"])
    shared = _create_org_stakeholder(client, token, org["id"], name="Regulator")
    sid = shared["id"]

    def state(project_id):
        body = client.get(
            f"{_project_base(project_id)}/stakeholders?include_hidden=true", headers=auth_headers(token)
        ).json()[0]
        return body["project_hidden"], body["hidden_source"], body["hidden_override"]

    assert state(grandchild["id"]) == (False, None, None)
    _hide(client, token, parent["id"], sid)
    assert state(parent["id"]) == (True, "project", True)
    assert state(child["id"]) == (True, "ancestor_project", None)  # inherited
    assert state(grandchild["id"]) == (True, "ancestor_project", None)
    assert _names(client, token, grandchild["id"]) == []

    # A child can re-show what its parent hid; its own descendants follow it (nearest wins).
    assert _hide(client, token, child["id"], sid, hidden=False).status_code == 200
    assert state(child["id"]) == (False, "project", False)
    assert state(grandchild["id"]) == (False, "ancestor_project", None)
    assert _names(client, token, grandchild["id"]) == ["Regulator"]
    assert _names(client, token, parent["id"]) == []

    # Resetting the child's override reverts it to inheriting the parent's.
    client.delete(_vis(child["id"], sid), headers=auth_headers(token))
    assert state(child["id"]) == (True, "ancestor_project", None)

    # Hiding one more stakeholder in the child does not un-hide what the parent hid.
    second = _create_org_stakeholder(client, token, org["id"], name="Second")
    _hide(client, token, child["id"], second["id"])
    assert _names(client, token, child["id"]) == []


# --- RBAC and gates ----------------------------------------------------------


def test_hiding_needs_the_stakeholder_manage_permission(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Rbac Co")
    shared = _create_org_stakeholder(client, token, org["id"])
    user_id, member = _add_member(client, token, org["id"], project["id"], "member@visibility-rbac.example.com")
    assert _hide(client, member, project["id"], shared["id"]).status_code == 403
    assert client.delete(_vis(project["id"], shared["id"]), headers=auth_headers(member)).status_code == 403
    assert _names(client, member, project["id"]) == ["Pat Regulator"]  # view-only members still read

    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    assert _hide(client, member, project["id"], shared["id"]).status_code == 200
    assert _names(client, member, project["id"]) == []


def test_disabled_module_is_404(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Visibility Gate Co")
    project = create_project(client, token, org["id"], "Visibility Gate Project")
    assert _hide(client, token, project["id"], str(uuid.uuid4())).status_code == 404


# --- Audit, erasure, bundles -------------------------------------------------


def test_visibility_changes_are_audit_logged_without_personal_data(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Audit Co")
    shared = _create_org_stakeholder(client, token, org["id"], name="Audited Visible Name")
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
    assert "audited visible" not in " ".join(str(e.detail) for e in events).lower()


def test_erasing_the_org_stakeholder_removes_its_overrides(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Erase Co")
    shared = _create_org_stakeholder(client, token, org["id"])
    _hide(client, token, project["id"], shared["id"])
    resp = client.delete(f"{_org_base(org['id'])}/stakeholders/{shared['id']}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ProjectStakeholderVisibility).where(
            ProjectStakeholderVisibility.stakeholder_id == uuid.UUID(shared["id"])
        )) == 0


def test_project_bundle_round_trips_visibility_and_warns_when_target_lacks_the_stakeholder(client, admin_token):
    org, project, token = _setup(client, admin_token, "Visibility Bundle Co")
    h = auth_headers(token)
    hidden = _create_org_stakeholder(client, token, org["id"], name="Hidden Regulator")
    shown = _create_org_stakeholder(client, token, org["id"], name="Re-shown Sponsor")
    _hide(client, token, project["id"], hidden["id"])
    _hide(client, token, project["id"], shown["id"], hidden=False)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert {(v["org_stakeholder_name"], v["hidden"]) for v in exported["project_stakeholder_visibility"]} == {
        ("Hidden Regulator", True), ("Re-shown Sponsor", False),
    }

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Visibility Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_id = imported.json()["project"]["id"]
    assert _names(client, token, new_id) == ["Re-shown Sponsor"]
    assert set(_names(client, token, new_id, "?include_hidden=true")) == {"Hidden Regulator", "Re-shown Sponsor"}

    other, _, other_token = _setup(client, admin_token, "Visibility Bundle Target Co")
    foreign = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Visibility Foreign"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert foreign.status_code == 201, foreign.text
    assert sum("visibility override was skipped" in w for w in foreign.json()["warnings"]) == 2
