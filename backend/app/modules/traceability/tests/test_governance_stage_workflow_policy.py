"""Tests for the stage workflow policy of governance profiles (`modules.traceability.stage_workflow_policy`, the routes under
`/profiles/{id}/stage-workflow`): who may set it and what it validates, that a required workflow starts new stages and cannot
be hidden or deleted, that a restricting profile leaves a project only the required workflows, how several profiles merge,
how Enforced, exempt, Default and opted-out profiles bind, that existing stages stay where they are, what switching the part
off does, the audit events and the organisation bundle round trip."""

from __future__ import annotations

import io
import json
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.traceability.models import GovernanceStageWorkflowPolicy
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _exempt, _setup
from tests.conftest import auth_headers, create_org_user, create_project, login

BASE = "/api/v1/orgs/{org}/modules/traceability/profiles/{profile}/stage-workflow"


def _url(org_id, profile_id) -> str:
    return BASE.format(org=org_id, profile=profile_id)


def _workflow(client, token, org_id, name) -> dict:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/stage-workflows",
        json={"name": name, "phases": [{"name": "Start", "kind": "open"}, {"name": "Done", "kind": "closed"}]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _require(client, token, org_id, profile_id, workflow_id, mode="default", status=200):
    resp = client.put(
        _url(org_id, profile_id), json={"workflow_id": workflow_id, "mode": mode}, headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _usable(client, token, project_id) -> list[str]:
    resp = client.get(f"/api/v1/projects/{project_id}/stage-workflows", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [w["name"] for w in resp.json()]


def _new_stage(client, token, project_id, name, workflow_id=None):
    body = {"name": name} if workflow_id is None else {"name": name, "workflow_id": workflow_id}
    return client.post(f"/api/v1/projects/{project_id}/stages", json=body, headers=auth_headers(token))


def _world(client, admin_token, name):
    org, token = _setup(client, admin_token, name)
    return org, create_project(client, token, org["id"], f"{name} project"), token


def _audit(profile_id: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "governance_profile", AuditEvent.entity_id == profile_id,
        ).order_by(AuditEvent.created_at)))


# --- gating and validation ------------------------------------------------------------------


def test_a_profile_reads_and_sets_its_required_workflow_and_clears_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Routes Org")
    profile = _create(client, token, org["id"], "Regulated")
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    empty = client.get(_url(org["id"], profile["id"]), headers=auth_headers(token)).json()
    assert (empty["workflow_id"], empty["mode"]) == (None, "default")
    assert "Regulated delivery" in [o["name"] for o in empty["options"]]

    set_ = _require(client, token, org["id"], profile["id"], regulated["id"], "restrict")
    assert (set_["workflow_id"], set_["workflow_name"], set_["mode"]) == (regulated["id"], "Regulated delivery", "restrict")
    cleared = client.delete(_url(org["id"], profile["id"]), headers=auth_headers(token))
    assert cleared.status_code == 200 and cleared.json()["workflow_id"] is None
    kinds = [e.action for e in _audit(profile["id"])]
    assert "stage_workflow_updated" in kinds and "stage_workflow_cleared" in kinds
    detail = next(e.detail for e in _audit(profile["id"]) if e.action == "stage_workflow_updated")
    assert detail == {"workflow_id": regulated["id"], "mode": "restrict"}


def test_a_workflow_of_another_organisation_or_a_project_is_not_found_and_only_a_manager_may_set_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Validation Org")
    other, other_token = _setup(client, admin_token, "Workflow Policy Other Org")
    profile = _create(client, token, org["id"], "Regulated")
    foreign = _workflow(client, other_token, other["id"], "Foreign")
    _require(client, token, org["id"], profile["id"], foreign["id"], status=404)
    own = client.post(
        f"/api/v1/projects/{project['id']}/stage-workflows",
        json={"name": "Mine", "phases": [{"name": "Start", "kind": "open"}]}, headers=auth_headers(token),
    )
    assert own.status_code == 201, own.text
    _require(client, token, org["id"], profile["id"], own.json()["id"], status=404)

    create_org_user(client, token, org["id"], "workflow_policy_member@example.com")
    member = login(client, "workflow_policy_member@example.com", "Password123!")
    shown = _workflow(client, token, org["id"], "Allowed")
    resp = client.put(_url(org["id"], profile["id"]), json={"workflow_id": shown["id"]}, headers=auth_headers(member))
    assert resp.status_code in (403, 404)


def test_the_routes_are_not_found_while_the_lifecycle_part_is_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Part Off Org")
    profile = _create(client, token, org["id"], "Regulated")
    off = client.put(
        f"/api/v1/orgs/{org['id']}/modules/traceability/subcomponents/lifecycle_policies", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert client.get(_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 404


# --- what it does to a project ------------------------------------------------------------------


def test_a_required_workflow_starts_new_stages_cannot_be_hidden_and_leaves_existing_stages_alone(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Default Org")
    pid = project["id"]
    first = client.get(f"/api/v1/projects/{pid}/stages", headers=auth_headers(token)).json()[0]
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], regulated["id"])

    created = _new_stage(client, token, pid, "Release 1")
    assert created.status_code == 201, created.text
    assert created.json()["workflow_name"] == "Regulated delivery"
    still = client.get(f"/api/v1/projects/{pid}/stages", headers=auth_headers(token)).json()
    assert next(s for s in still if s["id"] == first["id"])["workflow_name"] == "Standard"  # untouched

    other = _new_stage(client, token, pid, "Release 2", next(w for w in client.get(
        f"/api/v1/projects/{pid}/stage-workflows", headers=auth_headers(token)).json() if w["name"] == "Standard")["id"])
    assert other.status_code == 201 and other.json()["workflow_name"] == "Standard"  # default mode does not restrict

    listed = next(w for w in client.get(f"/api/v1/projects/{pid}/stage-workflows", headers=auth_headers(token)).json()
                  if w["name"] == "Regulated delivery")
    assert listed["required_by"] == ["Regulated"]
    hidden = client.delete(f"/api/v1/projects/{pid}/stage-workflows/{regulated['id']}", headers=auth_headers(token))
    assert hidden.status_code == 409 and "Regulated" in hidden.text


def test_a_workflow_the_project_hid_is_available_again_while_a_profile_requires_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Hidden Org")
    pid = project["id"]
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    assert client.delete(f"/api/v1/projects/{pid}/stage-workflows/{regulated['id']}", headers=auth_headers(token)).status_code == 204
    assert "Regulated delivery" not in _usable(client, token, pid)
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], regulated["id"])
    assert "Regulated delivery" in _usable(client, token, pid)


def test_a_restricting_profile_leaves_only_its_workflows(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Restrict Org")
    pid = project["id"]
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    profile = _create(client, token, org["id"], "Regulated")
    assert "Standard" in _usable(client, token, pid)
    _require(client, token, org["id"], profile["id"], regulated["id"], "restrict")
    assert _usable(client, token, pid) == ["Regulated delivery"]
    standard = next(w for w in client.get(f"/api/v1/orgs/{org['id']}/stage-workflows", headers=auth_headers(token)).json()
                    if w["name"] == "Standard")
    refused = _new_stage(client, token, pid, "Wrong", standard["id"])
    assert refused.status_code == 400
    allowed = _new_stage(client, token, pid, "Right")
    assert allowed.status_code == 201 and allowed.json()["workflow_name"] == "Regulated delivery"


def test_several_profiles_merge_by_precedence_and_one_restriction_limits_to_every_named_workflow(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Merge Org")
    pid = project["id"]
    first = _workflow(client, token, org["id"], "First workflow")
    second = _workflow(client, token, org["id"], "Second workflow")
    a = _create(client, token, org["id"], "A profile")
    b = _create(client, token, org["id"], "B profile")
    _require(client, token, org["id"], a["id"], first["id"])
    _require(client, token, org["id"], b["id"], second["id"], "restrict")
    assert sorted(_usable(client, token, pid)) == ["First workflow", "Second workflow"]
    created = _new_stage(client, token, pid, "Next")
    assert created.json()["workflow_name"] == "First workflow"  # the first profile by name in the same tier


def test_an_exemption_and_an_opt_out_lift_the_requirement(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Lift Org")
    pid = project["id"]
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    enforced = _create(client, token, org["id"], "Enforced", mode="enforced")
    _require(client, token, org["id"], enforced["id"], regulated["id"], "restrict")
    assert _usable(client, token, pid) == ["Regulated delivery"]
    _exempt(client, token, org["id"], enforced["id"], pid, reason="Pilot")
    assert "Standard" in _usable(client, token, pid)

    optional = _create(client, token, org["id"], "Optional", mode="default")
    _require(client, token, org["id"], optional["id"], regulated["id"], "restrict")
    assert _usable(client, token, pid) == ["Regulated delivery"]
    _choose(client, token, pid, optional["id"], False)
    assert "Standard" in _usable(client, token, pid)


def test_the_requirement_is_ignored_while_the_lifecycle_part_is_off_and_kept(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Ignored Org")
    pid = project["id"]
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], regulated["id"], "restrict")
    part = f"/api/v1/orgs/{org['id']}/modules/traceability/subcomponents/lifecycle_policies"
    assert client.put(part, json={"enabled": False}, headers=auth_headers(token)).status_code == 200
    assert "Standard" in _usable(client, token, pid)
    assert client.put(part, json={"enabled": True}, headers=auth_headers(token)).status_code == 200
    assert _usable(client, token, pid) == ["Regulated delivery"]


def test_a_workflow_a_profile_requires_cannot_be_deleted(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Delete Org")
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], regulated["id"])
    refused = client.delete(f"/api/v1/orgs/{org['id']}/stage-workflows/{regulated['id']}", headers=auth_headers(token))
    assert refused.status_code == 409 and "Regulated" in refused.text
    client.delete(_url(org["id"], profile["id"]), headers=auth_headers(token))
    assert client.delete(f"/api/v1/orgs/{org['id']}/stage-workflows/{regulated['id']}", headers=auth_headers(token)).status_code == 204


# --- counts and bundles -------------------------------------------------------------------------


def test_the_requirement_is_counted_beside_the_profile_and_travels_in_the_organisation_bundle(client, admin_token):
    org, project, token = _world(client, admin_token, "Workflow Policy Bundle Org")
    regulated = _workflow(client, token, org["id"], "Regulated delivery")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], regulated["id"], "restrict")
    listed = client.get(f"/api/v1/orgs/{org['id']}/modules/traceability/profiles", headers=auth_headers(token)).json()
    entry = next(p for p in listed if p["name"] == "Regulated")
    assert any(c["key"].endswith("stage_workflow") and c["count"] == 1 for c in entry["contributions"])

    exported = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    carried = json.dumps(data)
    assert "Regulated delivery" in carried
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Workflow Policy Imported Org"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    imported_id = resp.json().get("id") or resp.json()["organization"]["id"]
    with SessionLocal() as db:
        rows = list(db.scalars(select(GovernanceStageWorkflowPolicy)))
        assert [r.mode for r in rows].count("restrict") == 2  # the source and the imported organisation
    assert imported_id != org["id"]
