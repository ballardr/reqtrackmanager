"""Tests for the approval policy of governance (`modules.traceability.approval_policy`, the routes under
`/profiles/{id}/approval` and `/approval-policies`, the core check in `services.approval_policy`): who may set it, what it
validates, how a project's roles are merged from profiles, its own row and the nearest ancestor's, that a role holder may
approve through every approval path (requirement, change request, decision, risk, strategy, stage lock) while approval
separation and the default approvers are unchanged, what switching the part off does, the audit events, and the bundles."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.traceability import bundle
from app.modules.traceability.models import GovernanceApprovalPolicy, GovernanceApprovalPolicyRole, GovernanceProfile
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _exempt, _setup
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_group, create_org_user, create_project, login
from tests.stage_helpers import move_stage
from tests.test_approval_separation import _SCOPES, _approve_requirement, _put_project, _requirement

ORG = "/api/v1/orgs/{org}/modules/traceability"
PROJECT = "/api/v1/projects/{project}/modules/traceability"
STAKEHOLDER = {"kind": "project", "key": "stakeholder"}
MEMBER = {"kind": "project", "key": "member"}


def _profile_url(org_id, profile_id, suffix="") -> str:
    return ORG.format(org=org_id) + f"/profiles/{profile_id}/approval{suffix}"


def _project_url(project_id, suffix="") -> str:
    return PROJECT.format(project=project_id) + f"/approval-policies{suffix}"


def _set_profile(client, token, org_id, profile_id, artefact_type, roles, status=200):
    resp = client.put(
        _profile_url(org_id, profile_id, f"/{artefact_type}"), json={"roles": roles}, headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _set_project(client, token, project_id, artefact_type, roles, status=200):
    resp = client.put(_project_url(project_id, f"/{artefact_type}"), json={"roles": roles}, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _policy(client, token, project_id) -> dict:
    resp = client.get(_project_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(payload: dict, artefact_type: str) -> dict:
    return next(t for t in payload["types"] if t["artefact_type"] == artefact_type)


def _effective(client, token, project_id, artefact_type) -> list[tuple[str, str, tuple[str, ...]]]:
    return [
        (e["role"]["kind"], e["role"]["key"], tuple(e["sources"]))
        for e in _entry(_policy(client, token, project_id), artefact_type)["effective"]
    ]


def _member(client, token, org_id, project_id, role="stakeholder") -> tuple[str, str]:
    email = f"approval_policy_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _custom_role(client, token, org_id, scope="project") -> str:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles",
        json={"name": f"Approver {uuid.uuid4().hex[:8]}", "description": "", "scope": scope, "permissions": []},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _enable(client, token, org_id, key) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _part(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability/subcomponents/approval_policies", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _audit(entity_type: str, entity_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id,
        ).order_by(AuditEvent.created_at)))
    finally:
        db.close()


def _world(client, admin_token, name):
    """An organisation with Governance on, a project, a stakeholder of it and a Draft requirement."""
    org, token = _setup(client, admin_token, name)
    project = create_project(client, token, org["id"], f"{name} project")
    user_id, stakeholder = _member(client, token, org["id"], project["id"])
    return org, project, token, user_id, stakeholder


# --- gating, permissions and validation ----------------------------------------------------------


def test_the_routes_are_not_found_while_the_part_is_off(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Part Off Org")
    project = create_project(client, token, org["id"], "Part off project")
    profile = _create(client, token, org["id"], "Regulated")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 200
    assert client.get(_project_url(project["id"]), headers=auth_headers(token)).status_code == 200
    _part(client, token, org["id"], False)
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(
        _profile_url(org["id"], profile["id"], "/requirement"), json={"roles": []}, headers=auth_headers(token),
    ).status_code == 404
    assert client.get(_project_url(project["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(
        _project_url(project["id"], "/requirement"), json={"roles": []}, headers=auth_headers(token),
    ).status_code == 404


def test_only_a_holder_of_the_organisation_atom_sets_a_profiles_roles(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Org Permission Org")
    profile = _create(client, token, org["id"], "Regulated")
    create_org_user(client, token, org["id"], "approval_org_member@example.com")
    member = login(client, "approval_org_member@example.com", "Password123!")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(member)).status_code == 403
    assert client.put(
        _profile_url(org["id"], profile["id"], "/requirement"), json={"roles": [STAKEHOLDER]}, headers=auth_headers(member),
    ).status_code == 403


def test_a_profile_of_another_organisation_is_not_found(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Own Org")
    other, other_token = _setup(client, admin_token, "Approval Other Org")
    foreign = _create(client, other_token, other["id"], "Foreign")
    assert client.get(_profile_url(org["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(
        _profile_url(org["id"], foreign["id"], "/requirement"), json={"roles": []}, headers=auth_headers(token),
    ).status_code == 404


def test_only_a_holder_of_the_project_atom_sets_a_projects_roles_and_any_member_reads_them(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Project Permission Org")
    assert _policy(client, stakeholder, project["id"])["can_manage"] is False
    assert _policy(client, token, project["id"])["can_manage"] is True
    refused = client.put(_project_url(project["id"], "/requirement"), json={"roles": [STAKEHOLDER]}, headers=auth_headers(stakeholder))
    assert refused.status_code == 403
    # A person with no role in the project cannot read it either (the part is not found for them).
    outsider_email = "approval_outsider@example.com"
    create_org_user(client, token, org["id"], outsider_email)
    outsider = login(client, outsider_email, "Password123!")
    assert client.get(_project_url(project["id"]), headers=auth_headers(outsider)).status_code == 404


def test_a_server_administrator_holds_no_governance_bypass(client, admin_token):
    org, project, _, _, _ = _world(client, admin_token, "Approval Server Admin Org")
    # Not a member of the project, the server administrator does not even find the part.
    assert client.put(
        _project_url(project["id"], "/requirement"), json={"roles": [STAKEHOLDER]}, headers=auth_headers(admin_token),
    ).status_code == 404


def test_the_policy_lists_the_types_with_an_approval_gate_and_the_roles_it_may_name(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Vocabulary Org")
    profile = _create(client, token, org["id"], "Regulated")
    custom = _custom_role(client, token, org["id"])
    before = client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).json()
    types = {t["artefact_type"]: t for t in before["types"]}
    assert {"requirement", "change_request"} <= set(types) and "decision" not in types
    assert types["requirement"]["label"] == "Requirement" and types["requirement"]["module_key"] == ""
    options = {(o["kind"], o["key"]): o for o in before["role_options"]}
    assert options[("project", "project_manager")]["label"] == "Project Manager"
    assert options[("project", "stakeholder")]["scope"] == "project"
    assert options[("custom", custom)]["scope"] == "project"
    assert not any(kind == "module" and key.startswith("decisions:") for kind, key in options)

    _enable(client, token, org["id"], "decisions")
    after = client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).json()
    assert "decision" in {t["artefact_type"] for t in after["types"]}
    assert any(o["kind"] == "module" and o["key"].startswith("decisions:") for o in after["role_options"])


def test_a_policy_names_only_a_type_with_an_approval_gate_and_roles_the_organisation_offers(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Validation Org")
    other, other_token = _setup(client, admin_token, "Approval Validation Other Org")
    profile = _create(client, token, org["id"], "Regulated")
    foreign_role = _custom_role(client, other_token, other["id"])
    _set_profile(client, token, org["id"], profile["id"], "no_such_type", [], status=404)
    _set_profile(client, token, org["id"], profile["id"], "action", [], status=404)  # a record type with no approval gate
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "project", "key": "not_a_role"}], status=422)
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "module", "key": "decisions:decision_approver"}], status=422)
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "custom", "key": foreign_role}], status=422)
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "custom", "key": "not-an-id"}], status=422)
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "other", "key": "x"}], status=422)
    _set_profile(client, token, org["id"], profile["id"], "requirement", [{"kind": "project", "key": ""}], status=422)


def test_a_role_list_without_duplicates_is_stored_and_read_back_with_labels(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Roundtrip Org")
    profile = _create(client, token, org["id"], "Regulated")
    custom = _custom_role(client, token, org["id"])
    result = _set_profile(
        client, token, org["id"], profile["id"], "requirement",
        [STAKEHOLDER, STAKEHOLDER, {"kind": "custom", "key": custom}],
    )
    roles = next(t for t in result["types"] if t["artefact_type"] == "requirement")["roles"]
    assert sorted((r["kind"], r["key"]) for r in roles) == sorted([("project", "stakeholder"), ("custom", custom)])
    assert {r["label"] for r in roles if r["kind"] == "project"} == {"Stakeholder"}
    cleared = _set_profile(client, token, org["id"], profile["id"], "requirement", [])
    assert next(t for t in cleared["types"] if t["artefact_type"] == "requirement")["roles"] == []
    db = SessionLocal()
    try:
        assert db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.profile_id == uuid.UUID(profile["id"]))).all() == []
    finally:
        db.close()


def test_deleting_a_custom_role_removes_it_from_a_policy(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Custom Delete Org")
    custom = _custom_role(client, token, org["id"])
    _set_project(client, token, project["id"], "requirement", [{"kind": "custom", "key": custom}])
    assert client.delete(f"/api/v1/orgs/{org['id']}/custom-roles/{custom}", headers=auth_headers(token)).status_code == 204
    assert _entry(_policy(client, token, project["id"]), "requirement")["own"] == []
    assert _effective(client, token, project["id"], "requirement") == []


def test_every_change_writes_one_audit_event_with_keys_only(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Audit Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], "requirement", [STAKEHOLDER])
    _set_project(client, token, project["id"], "change_request", [MEMBER])
    _set_project(client, token, project["id"], "change_request", None)
    profile_events = [e for e in _audit("governance_profile", profile["id"]) if e.action == "approval_updated"]
    assert len(profile_events) == 1
    assert profile_events[0].detail == {"artefact_type": "requirement", "roles": ["project:stakeholder"]}
    project_events = _audit("governance_approval_policy", project["id"])
    assert [e.detail for e in project_events] == [
        {"artefact_type": "change_request", "roles": ["project:member"]},
        {"artefact_type": "change_request", "roles": None},
    ]
    assert all(e.project_id is not None and e.action == "updated" for e in project_events)


# --- the check, path by path ---------------------------------------------------------------------


def test_a_role_named_in_a_project_policy_lets_its_holder_approve_a_requirement(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Requirement Org")
    requirement = _requirement(client, token, project["id"])
    refused = _approve_requirement(client, stakeholder, project["id"], requirement)
    assert refused.status_code == 403 and refused.json()["detail"] == "Only a project manager can approve a requirement."

    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    approved = _approve_requirement(client, stakeholder, project["id"], requirement, "Checked against the plan.")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_the_policy_reaches_the_edit_path_and_the_change_request_decision(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Paths Org")
    requirement = _requirement(client, token, project["id"])
    approved_one = _requirement(client, token, project["id"], "Second")
    assert _approve_requirement(client, token, project["id"], approved_one).status_code == 200
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": approved_one, "changed_fields": ["name"],
            "proposed_name": "Renamed", "reason": "Reason",
        },
        headers=auth_headers(token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(token))
    decide = lambda: client.post(  # noqa: E731
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide", json={"approve": True, "note": "ok"},
        headers=auth_headers(stakeholder),
    )
    assert decide().status_code == 403

    _set_project(client, token, project["id"], "change_request", [STAKEHOLDER])
    assert decide().status_code == 200
    # The requirement policy is separate from the change request policy: this one is still refused.
    current = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement}", headers=auth_headers(token)).json()
    component_id, category_id = _SCOPES[project["id"]]
    body = {
        "name": current["name"], "component_id": component_id, "category_id": category_id, "owner": current["owner"],
        "status": "approved", "change_note": "Approving through the edit form.",
    }
    url = f"/api/v1/projects/{project['id']}/requirements/{requirement}"
    assert client.put(url, json=body, headers=auth_headers(stakeholder)).status_code == 403
    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    assert client.put(url, json=body, headers=auth_headers(stakeholder)).status_code == 200


def test_a_policy_never_skips_approval_separation(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Separation Org")
    _requirement(client, token, project["id"], "Sets up the component and category")
    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    assert _put_project(client, token, project["id"], "requirement", True).status_code == 200
    # The stakeholder writes a requirement and holds the policy role, yet is still its creator.
    own = _requirement(client, stakeholder, project["id"], "Written by the stakeholder")
    refused = _approve_requirement(client, stakeholder, project["id"], own, "Mine.")
    assert refused.status_code == 403 and "different person" in refused.json()["detail"]
    assert _approve_requirement(client, token, project["id"], own).status_code == 200


def test_the_default_approvers_are_unchanged_by_a_policy(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Default Kept Org")
    _set_project(client, token, project["id"], "requirement", [])
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200
    other = _requirement(client, token, project["id"], "Second")
    assert _approve_requirement(client, stakeholder, project["id"], other).status_code == 403


def test_a_module_role_a_custom_role_and_a_group_held_role_each_admit_their_holders(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Role Kinds Org")
    _enable(client, token, org["id"], "context_strategy")
    module_user, module_token = _member(client, token, org["id"], project["id"], "member")
    granted = client.post(
        f"/api/v1/projects/{project['id']}/members/{module_user}/module-roles",
        json={"module_key": "context_strategy", "role_key": "strategy_approver"}, headers=auth_headers(token),
    )
    assert granted.status_code == 204, granted.text
    custom_user, custom_token = _member(client, token, org["id"], project["id"], "member")
    custom = _custom_role(client, token, org["id"])
    assert client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{custom}/users/{custom_user}", json={"project_id": project["id"]},
        headers=auth_headers(token),
    ).status_code == 204
    group_user, group_token = _member(client, token, org["id"], project["id"], "member")
    group_role = _custom_role(client, token, org["id"], scope="org")
    group = create_org_group(client, token, org["id"], "Approvers", users=[group_user])
    assert client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{group_role}/groups/{group}", json={}, headers=auth_headers(token),
    ).status_code == 204
    _, bystander_token = _member(client, token, org["id"], project["id"], "member")

    requirement = _requirement(client, token, project["id"])
    tokens = {"module": module_token, "custom": custom_token, "group": group_token, "bystander": bystander_token}
    for name in tokens:
        assert _approve_requirement(client, tokens[name], project["id"], requirement).status_code == 403, name

    _set_project(client, token, project["id"], "requirement", [
        {"kind": "module", "key": "context_strategy:strategy_approver"},
        {"kind": "custom", "key": custom}, {"kind": "custom", "key": group_role},
    ])
    assert _approve_requirement(client, tokens["bystander"], project["id"], requirement).status_code == 403
    for index, name in enumerate(("module", "custom", "group")):
        record = _requirement(client, token, project["id"], f"Record {index}")
        approved = _approve_requirement(client, tokens[name], project["id"], record, "Checked.")
        assert approved.status_code == 200, (name, approved.text)


def test_a_role_of_a_module_that_is_off_for_the_project_admits_nobody(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Module Off Org")
    _enable(client, token, org["id"], "context_strategy")
    user_id, holder = _member(client, token, org["id"], project["id"], "member")
    assert client.post(
        f"/api/v1/projects/{project['id']}/members/{user_id}/module-roles",
        json={"module_key": "context_strategy", "role_key": "strategy_approver"}, headers=auth_headers(token),
    ).status_code == 204
    _set_project(client, token, project["id"], "requirement", [{"kind": "module", "key": "context_strategy:strategy_approver"}])
    requirement = _requirement(client, token, project["id"])
    off = client.put(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/enablement", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert _approve_requirement(client, holder, project["id"], requirement).status_code == 403


def test_switching_the_part_off_stops_the_policy_applying_and_keeps_its_rows(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Off Keeps Org")
    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    requirement = _requirement(client, token, project["id"])
    _part(client, token, org["id"], False)
    assert _approve_requirement(client, stakeholder, project["id"], requirement).status_code == 403
    _part(client, token, org["id"], True)
    assert _approve_requirement(client, stakeholder, project["id"], requirement).status_code == 200


def test_a_policy_with_the_module_off_changes_nothing(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Module Off Whole Org")
    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    requirement = _requirement(client, token, project["id"])
    assert client.put(
        f"/api/v1/orgs/{org['id']}/modules/traceability", json={"enabled": False}, headers=auth_headers(token),
    ).status_code == 200
    assert _approve_requirement(client, stakeholder, project["id"], requirement).status_code == 403


# --- the module types ----------------------------------------------------------------------------


def test_a_decision_a_risk_acceptance_and_a_strategy_follow_the_policy(client, admin_token):
    from app.modules.decisions.models import Decision
    from app.modules.decisions.service import propose_decision, submit_decision_for_review
    from app.modules.decisions.tests.test_decisions_api import _base as decision_base
    from app.modules.decisions.tests.test_decisions_workflow import _create_decision, _current_user_id, _first_decision_type_id
    from app.modules.risk_management.tests._helpers import create_risk
    from app.modules.risk_management.tests.test_risk_lifecycle import _move, _score, _url, _walk
    from tests.test_approval_separation import (
        _advance_project_strategy_to_under_review,
        _create_project_strategy,
        _project_base,
    )

    org, project, token, _, _ = _world(client, admin_token, "Approval Module Types Org")
    for key in ("context_strategy", "decisions", "risk_management"):
        _enable(client, token, org["id"], key)
    _, holder = _member(client, token, org["id"], project["id"], "member")

    user_id = _current_user_id(client, token)
    decision_id = _create_decision(
        project_id=uuid.UUID(project["id"]), decision_type_id=_first_decision_type_id(uuid.UUID(project["id"])),
        user_id=user_id, code="DEC-001",
    )
    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        assert decision is not None
        propose_decision(db, decision, user_id)
        submit_decision_for_review(db, decision, user_id)
        db.commit()
    finally:
        db.close()
    decision_url = f"{decision_base(project['id'])}/{decision_id}/approve"

    risk = create_risk(client, token, project["id"])
    _score(client, token, project, risk)
    _score(client, token, project, risk, residual=True)
    client.put(_url(project["id"], risk["id"]), json={"acceptance_criteria": "Within appetite."}, headers=auth_headers(token))
    _walk(client, token, project["id"], risk["id"], "assessed")

    strategy = _create_project_strategy(client, token, project["id"])
    _advance_project_strategy_to_under_review(client, token, project["id"], strategy["id"])
    strategy_url = f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve"

    assert client.post(decision_url, json={"comment": "Fine."}, headers=auth_headers(holder)).status_code == 403
    assert _move(client, holder, project["id"], risk["id"], "accepted", comment="Signed off").status_code == 403
    assert client.post(strategy_url, json={"comment": "Fine."}, headers=auth_headers(holder)).status_code == 403

    for artefact_type in ("decision", "risk", "strategy"):
        _set_project(client, token, project["id"], artefact_type, [MEMBER])
    assert client.post(decision_url, json={"comment": "Fine."}, headers=auth_headers(holder)).status_code == 200
    assert _move(client, holder, project["id"], risk["id"], "accepted", comment="Signed off").status_code == 200
    assert client.post(strategy_url, json={"comment": "Fine."}, headers=auth_headers(holder)).status_code == 200


def test_a_decision_role_scoped_to_one_decision_type_still_applies_beside_a_policy(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Subtype Org")
    _enable(client, token, org["id"], "decisions")
    user_id, member = _member(client, token, org["id"], project["id"], "member")
    role = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={
            "name": f"Architecture approver {uuid.uuid4().hex[:6]}", "description": "", "scope": "project",
            "permissions": [encode_permission("decision", "approve_baseline", "Architecture")],
        },
        headers=auth_headers(token),
    )
    assert role.status_code == 201, role.text
    assert client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role.json()['id']}/users/{user_id}", json={"project_id": project["id"]},
        headers=auth_headers(token),
    ).status_code == 204
    # The sub-type atom is the type's own permission, consulted by the same check as the policy.
    from app.models.user import User
    from app.services import approval_policy

    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(user_id))
        assert user is not None
        org_id, project_id = uuid.UUID(org["id"]), uuid.UUID(project["id"])
        assert approval_policy.may_approve(
            db, user, artefact_type="decision", subtype="Architecture", organization_id=org_id, project_id=project_id,
        ) is True
        assert approval_policy.may_approve(
            db, user, artefact_type="decision", subtype="Design", organization_id=org_id, project_id=project_id,
        ) is False
    finally:
        db.close()


# --- profiles, nested projects and sources -------------------------------------------------------


def test_the_roles_of_the_profiles_that_apply_are_merged_and_each_source_is_named(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Profiles Org")
    project = create_project(client, token, org["id"], "Profiles project")
    exempt = create_project(client, token, org["id"], "Exempt project")
    enforced = _create(client, token, org["id"], "Regulated", mode="enforced")
    default = _create(client, token, org["id"], "Shared defaults", mode="default")
    offered = _create(client, token, org["id"], "Offered", mode="opt_in")
    _set_profile(client, token, org["id"], enforced["id"], "requirement", [STAKEHOLDER])
    _set_profile(client, token, org["id"], default["id"], "requirement", [STAKEHOLDER, MEMBER])
    _set_profile(client, token, org["id"], offered["id"], "requirement", [{"kind": "project", "key": "project_administrator"}])
    _exempt(client, token, org["id"], enforced["id"], exempt["id"])

    got = _effective(client, token, project["id"], "requirement")
    assert ("project", "stakeholder", ("Regulated", "Shared defaults")) in got
    assert ("project", "member", ("Shared defaults",)) in got
    assert all(role[1] != "project_administrator" for role in got)  # opt-in, not chosen

    _choose(client, token, project["id"], offered["id"], True)
    assert ("project", "project_administrator", ("Offered",)) in _effective(client, token, project["id"], "requirement")

    _choose(client, token, project["id"], default["id"], False)
    got = _effective(client, token, project["id"], "requirement")
    assert ("project", "stakeholder", ("Regulated",)) in got and all(r[1] != "member" for r in got)

    exempt_roles = _effective(client, token, exempt["id"], "requirement")
    assert ("project", "stakeholder", ("Shared defaults",)) in exempt_roles  # exempt from the enforced profile only


def test_an_enforced_profile_admits_its_role_holders_and_an_exempt_project_does_not(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Enforced Org")
    bound = create_project(client, token, org["id"], "Bound")
    exempt = create_project(client, token, org["id"], "Exempt")
    _, bound_holder = _member(client, token, org["id"], bound["id"])
    _, exempt_holder = _member(client, token, org["id"], exempt["id"])
    profile = _create(client, token, org["id"], "Regulated", mode="enforced")
    _set_profile(client, token, org["id"], profile["id"], "requirement", [STAKEHOLDER])
    _exempt(client, token, org["id"], profile["id"], exempt["id"])
    bound_requirement = _requirement(client, token, bound["id"])
    exempt_requirement = _requirement(client, token, exempt["id"])
    assert _approve_requirement(client, bound_holder, bound["id"], bound_requirement).status_code == 200
    assert _approve_requirement(client, exempt_holder, exempt["id"], exempt_requirement).status_code == 403


def test_a_child_follows_its_parents_row_until_it_sets_its_own(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Nested Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _, child_holder = _member(client, token, org["id"], child["id"])
    _set_project(client, token, parent["id"], "requirement", [STAKEHOLDER])

    entry = _entry(_policy(client, token, child["id"]), "requirement")
    assert entry["own"] is None and entry["inherited_from"] == "Parent"
    assert [(e["role"]["key"], e["sources"]) for e in entry["effective"]] == [("stakeholder", ["parent_project"])]
    assert _approve_requirement(client, child_holder, child["id"], _requirement(client, token, child["id"])).status_code == 200

    _set_project(client, token, child["id"], "requirement", [])  # a choice of no extra approvers
    entry = _entry(_policy(client, token, child["id"]), "requirement")
    assert entry["own"] == [] and entry["inherited_from"] is None and entry["effective"] == []
    assert _approve_requirement(client, child_holder, child["id"], _requirement(client, token, child["id"], "Second")).status_code == 403

    _set_project(client, token, child["id"], "requirement", [MEMBER])
    assert _effective(client, token, child["id"], "requirement") == [("project", "member", ("project",))]
    _set_project(client, token, child["id"], "requirement", None)  # follows the parent again
    assert _entry(_policy(client, token, child["id"]), "requirement")["inherited_from"] == "Parent"


def test_a_project_and_a_profile_union_their_roles(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Union Org")
    project = create_project(client, token, org["id"], "Union project")
    profile = _create(client, token, org["id"], "Regulated", mode="enforced")
    _set_profile(client, token, org["id"], profile["id"], "requirement", [STAKEHOLDER])
    _set_project(client, token, project["id"], "requirement", [MEMBER])
    assert sorted(r[:2] for r in _effective(client, token, project["id"], "requirement")) == [
        ("project", "member"), ("project", "stakeholder"),
    ]
    # An empty project row never takes an enforced profile's role away.
    _set_project(client, token, project["id"], "requirement", [])
    assert _effective(client, token, project["id"], "requirement") == [("project", "stakeholder", ("Regulated",))]


def test_the_contributor_counts_the_types_a_profile_names_roles_for(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Count Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], "requirement", [STAKEHOLDER])
    _set_profile(client, token, org["id"], profile["id"], "change_request", [MEMBER])
    listed = client.get(ORG.format(org=org["id"]) + "/profiles", headers=auth_headers(token)).json()
    entry = next(p for p in listed if p["id"] == profile["id"])
    assert {(c["key"], c["count"]) for c in entry["contributions"]} >= {("traceability:approval", 2)}


# --- stage locking -------------------------------------------------------------------------------


def _stage_id(client, token, project_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()[0]["id"]


def test_a_role_named_for_requirements_may_enter_and_leave_a_locked_phase_only(client, admin_token):
    org, project, token, _, stakeholder = _world(client, admin_token, "Approval Stage Lock Org")
    stage = _stage_id(client, token, project["id"])
    requirement = _requirement(client, token, project["id"])
    assert move_stage(client, project["id"], stage, "approved", headers=auth_headers(stakeholder)).status_code == 403
    assert client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(stakeholder)).json()[0]["can_lock"] is False

    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    assert client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(stakeholder)).json()[0]["can_lock"] is True
    # A move that touches no locked phase stays a manager's.
    assert move_stage(client, project["id"], stage, "review", headers=auth_headers(stakeholder)).status_code == 403
    locked = move_stage(client, project["id"], stage, "approved", headers=auth_headers(stakeholder))
    assert locked.status_code == 200, locked.text
    assert client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}", headers=auth_headers(token),
    ).json()["status"] == "approved"
    assert move_stage(client, project["id"], stage, "scoping", headers=auth_headers(stakeholder)).status_code == 200


def test_the_atom_alone_does_not_admit_a_person_to_the_locked_phases(client, admin_token):
    org, project, token, user_id, stakeholder = _world(client, admin_token, "Approval Stage Atom Org")
    role = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={
            "name": f"Requirement approver {uuid.uuid4().hex[:6]}", "description": "", "scope": "project",
            "permissions": [encode_permission("requirement", "approve_baseline")],
        },
        headers=auth_headers(token),
    )
    assert client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles/{role.json()['id']}/users/{user_id}", json={"project_id": project["id"]},
        headers=auth_headers(token),
    ).status_code == 204
    stage = _stage_id(client, token, project["id"])
    assert move_stage(client, project["id"], stage, "approved", headers=auth_headers(stakeholder)).status_code == 403


def test_a_component_track_follows_the_same_rule(client, admin_token):
    from tests.test_component_stages import _move, _turn_on, _workflow
    from tests.test_component_stages import _world as track_world

    org, token = _setup(client, admin_token, "Approval Track Org")
    project, first, _second, stage_one, _stage_two, _reqs = track_world(client, token, org["id"])
    _turn_on(client, token, project["id"])
    standard = _workflow(client, token, project["id"])
    _, stakeholder = _member(client, token, org["id"], project["id"])
    assert _move(client, stakeholder, project["id"], first["id"], stage_one["id"], standard, "Approved").status_code == 403

    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER])
    assert _move(client, stakeholder, project["id"], first["id"], stage_one["id"], standard, "Review").status_code == 403
    assert _move(client, stakeholder, project["id"], first["id"], stage_one["id"], standard, "Approved").status_code == 200


# --- bundles -------------------------------------------------------------------------------------


def test_a_projects_own_rows_travel_in_its_bundle_with_a_custom_role_by_name(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Approval Project Bundle Org")
    custom = _custom_role(client, token, org["id"])
    _set_project(client, token, project["id"], "requirement", [STAKEHOLDER, {"kind": "custom", "key": custom}])
    _set_project(client, token, project["id"], "change_request", [])
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    rows = {r["artefact_type"]: r["roles"] for r in data[bundle.APPROVAL_POLICIES_KEY]}
    assert rows["change_request"] == []
    assert {"kind": "project", "key": "stakeholder"} in rows["requirement"]
    assert any(r["kind"] == "custom" and "name" in r and "key" not in r for r in rows["requirement"])

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copied = _policy(client, token, imported.json()["project"]["id"])
    assert sorted((r["role"]["kind"], r["role"]["key"]) for r in _entry(copied, "requirement")["effective"]) == sorted(
        [("project", "stakeholder"), ("custom", custom)]
    )
    assert _entry(copied, "change_request")["own"] == []


def test_a_project_import_leaves_out_a_role_the_organisation_cannot_use_and_says_so(client, admin_token):
    from app.models.project import Project
    from app.modules.traceability import approval_policy

    _, project, _, _, _ = _world(client, admin_token, "Approval Import Warning Org")
    warnings: list[str] = []
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        assert row is not None
        approval_policy.import_project_rows(
            db, row,
            [
                {"artefact_type": "requirement", "roles": [{"kind": "project", "key": "not_a_role"}]},
                {"artefact_type": "no_such_type", "roles": []},
            ],
            warnings.append,
        )
        assert len(warnings) == 2 and "not available" in warnings[0] and "no approval gate" in warnings[1]
        # Nothing usable was named, so no "no extra approvers" row replaces an inherited policy.
        assert db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.project_id == row.id)).all() == []
    finally:
        db.rollback()
        db.close()


def test_a_profiles_rows_travel_in_the_organisation_bundle(client, admin_token):
    org, token = _setup(client, admin_token, "Approval Org Bundle Org")
    profile = _create(client, token, org["id"], "Regulated")
    custom = _custom_role(client, token, org["id"])
    _set_profile(client, token, org["id"], profile["id"], "requirement", [STAKEHOLDER, {"kind": "custom", "key": custom}])
    exported = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    entry = next(e for e in data["governance_profiles"] if e["name"] == "Regulated")
    approval = entry["contributions"]["traceability:approval"]
    assert approval[0]["kind"] == "approval" and approval[0]["artefact_type"] == "requirement"

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Approval Org Bundle Imported Org"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code in (200, 201), imported.text
    new_org = imported.json().get("id") or imported.json()["organization"]["id"]
    db = SessionLocal()
    try:
        new_profile = db.scalars(select(GovernanceProfile).where(
            GovernanceProfile.organization_id == uuid.UUID(new_org), GovernanceProfile.name == "Regulated",
        )).one()
        policy = db.scalars(select(GovernanceApprovalPolicy).where(GovernanceApprovalPolicy.profile_id == new_profile.id)).one()
        roles = db.scalars(select(GovernanceApprovalPolicyRole).where(GovernanceApprovalPolicyRole.policy_id == policy.id)).all()
        assert policy.artefact_type == "requirement"
        # The custom role belongs to the source organisation and is not recreated, so only the project role came across.
        assert sorted((r.role_kind, r.role_key) for r in roles) == [("project", "stakeholder")]
    finally:
        db.close()


def test_the_approval_rows_are_template_configuration():
    from app.modules.registry import get_module

    module = get_module("traceability")
    assert module is not None and module.project_bundle_hooks is not None
    hooks = module.project_bundle_hooks
    assert {bundle.CHOICES_KEY, bundle.APPROVAL_POLICIES_KEY} <= set(hooks.template_configuration_keys)
