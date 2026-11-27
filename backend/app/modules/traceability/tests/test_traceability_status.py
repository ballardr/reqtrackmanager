"""
Traceability enforcement and status: where a Required rule refuses a baseline or an approval, a record's status against
each rule, and carried-over links reading as inherited until they are confirmed.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

from httpx import Response
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.modules.decisions.models import Decision
from app.modules.decisions.service import propose_decision, submit_decision_for_review
from app.modules.decisions.tests.test_decisions_api import _base as _decision_base
from app.modules.decisions.tests.test_decisions_workflow import _create_decision, _first_decision_type_id
from app.modules.traceability import bundle, health
from app.modules.traceability.models import GovernanceHealthSnapshot
from app.modules.traceability.tests.test_governance_baseline_policy import (
    _baseline_count,
    _lock,
    _manual,
    _set_project,
    _settings,
    _stage_id,
    _status,
)
from app.modules.traceability.tests.test_traceability_rules import (
    Scenario,
    _add_rule,
    _body,
    _leaf,
    _member,
    _rules,
)
from app.services.stages import auto_approve_overdue_stage_reviews
from tests.conftest import auth_headers
from tests.link_world import ACTION, REQ
from tests.stage_helpers import move_stage

CHECK = "traceability:traceability_rules"
PROJECT = "/api/v1/projects/{project}/modules/traceability"


def _derived_rule(scenario: Scenario, level="required", name="Projects derive from stakeholders") -> dict:
    return _add_rule(scenario.client, scenario.world.token, scenario.project["id"], _body(
        name, subtype="Project Requirement", level=level, requires=_leaf(subtype="Stakeholder Requirement"),
    ))


def _enforce(scenario: Scenario, *, stage=False, manual=False, approvals="off") -> None:
    _set_project(
        scenario.client, scenario.world.token, scenario.project["id"],
        _settings(checks=[CHECK], stage=stage, manual=manual, approvals=approvals),
    )


def _record(scenario: Scenario, record_id, artefact_type=REQ, status=200) -> dict:
    resp = scenario.client.get(
        PROJECT.format(project=scenario.project["id"]) + f"/status/{artefact_type}/{record_id}",
        headers=auth_headers(scenario.world.token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _approve(scenario: Scenario, record_id):
    return scenario.client.post(
        f"/api/v1/projects/{scenario.project['id']}/requirements/{record_id}/approve",
        headers=auth_headers(scenario.world.token),
    )


def _carry(link_id, note="Copied from REQ-900") -> None:
    with SessionLocal() as db:
        link = db.get(ArtefactLink, link_id)
        assert link is not None
        link.note = note
        db.commit()


def _note(link_id) -> str | None:
    with SessionLocal() as db:
        link = db.get(ArtefactLink, link_id)
        assert link is not None
        return link.note


def _confirm(scenario: Scenario, record_id, link_id, *, artefact_type=REQ, token=None):
    return scenario.client.post(
        f"/api/v1/projects/{scenario.project['id']}/artefacts/{artefact_type}/{record_id}/links/{link_id}/confirm",
        headers=auth_headers(token or scenario.world.token),
    )


def _pair(scenario: Scenario) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A project requirement linked to a stakeholder requirement; returns (project requirement, stakeholder, link)."""
    stakeholder = scenario.requirement("Stakeholder Requirement", "S1")
    project = scenario.requirement("Project Requirement", "P1")
    link = scenario.world.link((REQ, project), (REQ, stakeholder), scenario.derives)
    return project, stakeholder, link


# --- status ---------------------------------------------------------------------------------------


def test_a_record_shows_each_rule_with_a_result_per_requirement(client, admin_token):
    scenario = Scenario(client, admin_token, "Status Org")
    _derived_rule(scenario, level="warning")
    project, stakeholder, _ = _pair(scenario)
    lonely = scenario.requirement("Project Requirement", "P2")

    met = _record(scenario, project)
    assert (met["status"], met["highest_level"]) == ("complete", None)
    assert [(r["state"], r["leaves"][0]["count"], r["leaves"][0]["state"]) for r in met["rules"]] == [("met", 1, "met")]

    unmet = _record(scenario, lonely)
    assert (unmet["status"], unmet["highest_level"]) == ("incomplete", "warning")
    assert unmet["rules"][0]["leaves"][0] == {
        "path": "", "label": "Links to Requirement (Stakeholder Requirement)", "count": 0, "confirmed": 0, "minimum": 1,
        "maximum": None, "state": "unmet",
    }
    assert _record(scenario, stakeholder)["status"] == "not_applicable"

    listed = client.get(PROJECT.format(project=scenario.project["id"]) + "/status/requirement", headers=auth_headers(scenario.world.token))
    assert listed.status_code == 200, listed.text
    by_id = {r["record_id"]: r for r in listed.json()["records"]}
    assert (by_id[str(project)]["status"], by_id[str(lonely)]["unmet"], by_id[str(stakeholder)]["applicable"]) == ("complete", 1, 0)
    named = client.get(
        PROJECT.format(project=scenario.project["id"]) + f"/status/requirement?record_id={lonely}",
        headers=auth_headers(scenario.world.token),
    ).json()
    assert [r["record_id"] for r in named["records"]] == [str(lonely)]


def test_a_status_needs_the_view_permission_and_a_record_of_the_project(client, admin_token, monkeypatch):
    scenario = Scenario(client, admin_token, "Status Access Org")
    project, _, _ = _pair(scenario)
    _record(scenario, uuid.uuid4(), status=404)
    _record(scenario, project, artefact_type="no_such_type", status=404)
    outsider = Scenario(client, admin_token, "Status Outsider Org")
    resp = client.get(
        PROJECT.format(project=scenario.project["id"]) + f"/status/requirement/{project}",
        headers=auth_headers(outsider.world.token),
    )
    assert resp.status_code in (403, 404), resp.text
    monkeypatch.setattr("app.modules.traceability.rules_router.permission_satisfied", lambda *_: False)
    _record(scenario, project, status=403)


def test_a_required_rule_says_where_it_is_enforced_or_why_it_is_not(client, admin_token):
    scenario = Scenario(client, admin_token, "Enforcement Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _derived_rule(scenario)
    _derived_rule(scenario, level="warning", name="Warned")
    lonely = scenario.requirement("Project Requirement", "P2")

    def listed() -> dict[str, tuple]:
        return {r["name"]: (r["enforced_at"], r["not_enforced_reason"]) for r in _rules(client, token, pid)}

    assert listed() == {"Projects derive from stakeholders": ([], "check_not_enabled"), "Warned": ([], None)}
    _enforce(scenario, stage=True)
    assert listed()["Projects derive from stakeholders"] == (["stage_baseline", "automated_approval"], None)
    _enforce(scenario, manual=True, approvals="manual")
    assert listed()["Projects derive from stakeholders"] == (["manual_baseline", "manual_approval"], None)
    shown = {r["name"]: r for r in _record(scenario, lonely)["rules"]}
    assert shown["Projects derive from stakeholders"]["enforced_at"] == ["manual_baseline", "manual_approval"]
    assert shown["Warned"]["enforced_at"] == []

    resp = client.put(
        f"/api/v1/orgs/{scenario.world.org['id']}/modules/traceability/subcomponents/baseline_policies",
        json={"enabled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert listed()["Projects derive from stakeholders"] == ([], "baseline_policies_off")


# --- baselines ------------------------------------------------------------------------------------


def test_a_required_rule_refuses_a_stage_and_a_manual_baseline_and_a_warning_does_not(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Baseline Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _derived_rule(scenario, level="warning", name="Warned")
    lonely = scenario.requirement("Project Requirement", "P2")
    _enforce(scenario, stage=True, manual=True)
    assert _manual(client, token, pid).status_code == 201
    _derived_rule(scenario)

    refused = _manual(client, token, pid)
    assert refused.status_code == 409, refused.text
    failures = refused.json()["detail"]["failures"]
    code = client.get(f"/api/v1/projects/{pid}/requirements/{lonely}", headers=auth_headers(token)).json()["unique_code"]
    assert [(f["check_key"], f["artefact_id"], f["code"]) for f in failures] == [(CHECK, str(lonely), code)]
    assert failures[0]["message"] == (
        'Traceability rule "Projects derive from stakeholders" is not met: '
        "Links to Requirement (Stakeholder Requirement) (found 0, at least 1 needed)."
    )
    count = _baseline_count(pid)
    assert _lock(client, token, pid).status_code == 409
    assert (_baseline_count(pid), _status(client, token, pid, lonely)) == (count, "draft")
    assert _approve(scenario, lonely).status_code == 200, "approvals are not checked unless the policy says so"


# --- approvals ------------------------------------------------------------------------------------


def test_approvals_are_checked_only_when_the_policy_says_manual(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Approval Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _derived_rule(scenario)
    lonely = scenario.requirement("Project Requirement", "P2")
    project, _, _ = _pair(scenario)
    _enforce(scenario, approvals="manual")

    refused = _approve(scenario, lonely)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["message"].startswith('The approval was refused. Traceability rule')
    assert _status(client, token, pid, lonely) == "draft"
    assert _approve(scenario, project).status_code == 200
    assert _lock(client, token, pid).status_code == 200, "the stage baseline is not checked"

    for approvals in ("off", "automated"):
        _enforce(scenario, stage=True, approvals=approvals)
        other = scenario.requirement("Project Requirement", f"Other {approvals}")
        assert _approve(scenario, other).status_code == 200


def test_an_edit_to_approved_is_checked_as_the_record_it_becomes(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Edit Approval Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _derived_rule(scenario)
    record = scenario.requirement("Business Requirement", "B1")
    _enforce(scenario, approvals="manual")
    current = client.get(f"/api/v1/projects/{pid}/requirements/{record}", headers=auth_headers(token)).json()
    body = {
        "name": current["name"], "reasoning": current["reasoning"], "clarification": current["clarification"],
        "description": current["description"], "component_id": current["component_id"],
        "category_id": current["category_id"], "owner": current["owner"], "status": "approved",
        "type_id": scenario.types["Project Requirement"],
    }
    refused = client.put(f"/api/v1/projects/{pid}/requirements/{record}", json=body, headers=auth_headers(token))
    assert refused.status_code == 409, refused.text
    after = client.get(f"/api/v1/projects/{pid}/requirements/{record}", headers=auth_headers(token)).json()
    assert (after["status"], after["type_id"]) == ("draft", current["type_id"])


def test_a_change_request_that_would_approve_an_untraced_requirement_is_refused(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule CR Approval Org")
    token, pid = scenario.world.token, scenario.project["id"]
    headers = auth_headers(token)
    project, _, _ = _pair(scenario)
    lonely = scenario.requirement("Project Requirement", "P2")
    for record in (project, lonely):
        assert _approve(scenario, record).status_code == 200
    _derived_rule(scenario)
    _enforce(scenario, approvals="manual")

    def decide(requirement_id) -> Response:
        created = client.post(
            f"/api/v1/projects/{pid}/change-requests",
            json={
                "kind": "modify_requirement", "requirement_id": str(requirement_id), "reason": "r",
                "changed_fields": ["name"], "proposed_name": "Renamed",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        cr = created.json()["id"]
        assert client.post(f"/api/v1/projects/{pid}/change-requests/{cr}/submit", headers=headers).status_code == 200
        return client.post(f"/api/v1/projects/{pid}/change-requests/{cr}/decide", json={"approve": True}, headers=headers)

    refused = decide(lonely)
    assert refused.status_code == 409, refused.text
    assert client.get(f"/api/v1/projects/{pid}/requirements/{lonely}", headers=headers).json()["name"] == "P2"
    assert decide(project).status_code == 200


def test_the_review_deadline_approval_is_checked_when_the_policy_says_automated(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Sweep Org")
    token, pid = scenario.world.token, scenario.project["id"]
    headers = auth_headers(token)
    _derived_rule(scenario)
    lonely = scenario.requirement("Project Requirement", "P2")
    _enforce(scenario, approvals="automated")
    stage_id = _stage_id(client, token, pid)
    assert move_stage(client, pid, stage_id, "review", headers=headers).status_code == 200
    resp = client.post(
        f"/api/v1/projects/{pid}/stages/{stage_id}/review-deadline",
        json={"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}, headers=headers,
    )
    assert resp.status_code == 200, resp.text

    def sweep() -> str:
        with SessionLocal() as db:
            auto_approve_overdue_stage_reviews(db)
        return _status(client, token, pid, lonely)

    assert sweep() == "draft"
    _enforce(scenario, approvals="manual")
    assert sweep() == "approved"


def test_the_required_approvals_check_does_not_judge_the_approval_being_made(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Required Approvals Org")
    record = scenario.requirement("Project Requirement", "P1")
    _set_project(
        client, scenario.world.token, scenario.project["id"],
        _settings(checks=["traceability:required_approvals"], stage=False, approvals="manual"),
    )
    assert _approve(scenario, record).status_code == 200


# --- carried-over links ---------------------------------------------------------------------------


def test_a_rule_met_only_by_carried_over_links_is_inherited_and_blocks_until_confirmed(client, admin_token):
    scenario = Scenario(client, admin_token, "Inherited Org")
    rule = _derived_rule(scenario)
    project, _, link = _pair(scenario)
    _carry(link)
    _enforce(scenario, approvals="manual")

    status = _record(scenario, project)
    leaf = status["rules"][0]["leaves"][0]
    assert (status["status"], status["highest_level"], leaf["state"], leaf["count"], leaf["confirmed"]) == (
        "inherited", "required", "inherited", 1, 0,
    )
    assert scenario.evaluation(rule)["inherited"] == 1
    refused = _approve(scenario, project)
    assert refused.status_code == 409, refused.text
    assert "met only by links carried over" in refused.json()["detail"]["message"]

    assert _confirm(scenario, project, link).status_code == 204
    assert _note(link) is None
    assert _record(scenario, project)["status"] == "complete"
    assert _approve(scenario, project).status_code == 200
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(link), AuditEvent.action == "link_confirmed")).all()
        assert [e.detail["note"] for e in events if e.detail] == ["Copied from REQ-900"]
    assert _confirm(scenario, project, link).status_code == 409
    assert _confirm(scenario, project, uuid.uuid4()).status_code == 404


def test_one_confirmed_link_is_enough_where_the_minimum_is_one(client, admin_token):
    scenario = Scenario(client, admin_token, "Inherited Partial Org")
    _derived_rule(scenario)
    project, _, link = _pair(scenario)
    second = scenario.requirement("Stakeholder Requirement", "S2")
    scenario.world.link((REQ, project), (REQ, second), scenario.derives)
    _carry(link)
    assert _record(scenario, project)["status"] == "complete"


def test_a_carried_over_action_link_is_inherited_and_can_be_confirmed_from_the_requirement(client, admin_token):
    scenario = Scenario(client, admin_token, "Inherited Action Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _add_rule(client, token, pid, _body(
        "Verified", subtype="Project Requirement",
        requires=_leaf(ACTION, direction="incoming", link_types={"mode": "untyped"}),
    ))
    record = scenario.requirement("Project Requirement", "P1")
    action = scenario.world.action(scenario.project)
    link = scenario.world.link((ACTION, action), (REQ, record))
    _carry(link)
    assert _record(scenario, record)["status"] == "inherited"
    listed = client.get(f"/api/v1/projects/{pid}/requirements/{record}/actions", headers=auth_headers(token)).json()
    assert [(a["link_id"], a["link_note"]) for a in listed] == [(str(link), "Copied from REQ-900")]
    assert _confirm(scenario, record, link).status_code == 204
    assert _record(scenario, record)["status"] == "complete"


def test_confirming_needs_the_right_to_change_the_link(client, admin_token):
    scenario = Scenario(client, admin_token, "Confirm Rights Org")
    project, _, link = _pair(scenario)
    _carry(link)
    org_id, pid = scenario.world.org["id"], scenario.project["id"]
    viewer = _member(client, scenario.world.token, org_id, pid, "member")
    assert _confirm(scenario, project, link, token=viewer).status_code == 403
    stakeholder = _member(client, scenario.world.token, org_id, pid, "stakeholder")
    assert _approve(scenario, project).status_code == 200
    assert _confirm(scenario, project, link, token=stakeholder).status_code == 403
    assert _note(link) == "Copied from REQ-900"


# --- bundles --------------------------------------------------------------------------------------


def test_the_approval_setting_travels_in_the_project_bundle(client, admin_token):
    scenario = Scenario(client, admin_token, "Approval Bundle Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _enforce(scenario, approvals="manual_and_automated")
    exported = client.get(f"/api/v1/projects/{pid}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    assert data[bundle.BASELINE_POLICY_KEY]["approval_checks"] == "manual_and_automated"
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": scenario.world.org["id"], "name": "Approval Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    own = client.get(
        PROJECT.format(project=imported.json()["project"]["id"]) + "/baseline-policy", headers=auth_headers(token),
    ).json()["own"]
    assert (own["approval_checks"], own["applies_to_stage"], own["checks"]) == ("manual_and_automated", False, [CHECK])


def test_a_policy_must_check_something(client, admin_token):
    scenario = Scenario(client, admin_token, "Empty Policy Org")
    _set_project(client, scenario.world.token, scenario.project["id"], _settings(checks=[CHECK], stage=False), status=422)


def test_a_module_types_approval_runs_the_check_through_the_shared_approval_rules(client, admin_token):
    scenario = Scenario(client, admin_token, "Decision Rule Org")
    token, pid = scenario.world.token, scenario.project["id"]
    scenario.world.enable("decisions")
    resp = client.put(
        f"/api/v1/projects/{pid}/modules/decisions/enablement", json={"enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code in (200, 204), resp.text
    decision_id = _create_decision(
        project_id=uuid.UUID(pid), decision_type_id=_first_decision_type_id(uuid.UUID(pid)),
        user_id=scenario.world.user_id, code="DEC-001",
    )
    with SessionLocal() as db:
        decision = db.get(Decision, decision_id)
        assert decision is not None
        propose_decision(db, decision, scenario.world.user_id)
        submit_decision_for_review(db, decision, scenario.world.user_id)
        db.commit()
    _add_rule(client, token, pid, _body("Decisions cite a requirement", source="decision", level="required", requires=_leaf()))
    _enforce(scenario, approvals="manual")
    url = f"{_decision_base(pid)}/{decision_id}/approve"

    refused = client.post(url, json={"comment": "Fine."}, headers=auth_headers(token))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["failures"][0]["code"] == "DEC-001"
    scenario.world.link(("decision", decision_id), (REQ, scenario.requirement("Project Requirement", "P1")), scenario.relates)
    approved = client.post(url, json={"comment": "Fine."}, headers=auth_headers(token))
    assert approved.status_code == 200, approved.text


def test_an_on_change_health_snapshot_notices_a_new_link_and_a_confirmation(client, admin_token):
    scenario = Scenario(client, admin_token, "Rule Health Org")
    pid = scenario.project["id"]
    _derived_rule(scenario)
    _enforce(scenario, approvals="manual")
    project, _, link = _pair(scenario)
    _carry(link)
    with SessionLocal() as db:
        snapshot = GovernanceHealthSnapshot(project_id=uuid.UUID(pid), computed_at=datetime.now(UTC), payload={})
        row = db.get(Project, uuid.UUID(pid))
        assert row is not None
        assert health.is_stale(db, row, snapshot) is False
    assert _confirm(scenario, project, link).status_code == 204
    with SessionLocal() as db:
        row = db.get(Project, uuid.UUID(pid))
        assert row is not None
        assert health.is_stale(db, row, snapshot) is True
