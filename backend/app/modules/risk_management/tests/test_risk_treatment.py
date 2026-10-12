"""Tests for the Risk Management module's Phase 3 relationships and treatment
assessments (docs/plans/module-03-risk-management-plan.md), through the real HTTP
endpoints.

Covers: the link-type seeds and the Risk summary provider, which treatment links
a risk lists (and which it ignores), the verdict API and who may give it, the
rationale rule, the effective count / `is_effectively_treated` flag and its list
filter, the `Mitigated` guard, link deletion dropping its verdict, audit logging,
and tenant isolation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.registry import get_artefact_summary, get_link_type_seed_owners
from app.modules.risk_management.tests._helpers import (
    add_effective_treatment,
    add_member,
    assess,
    create_action,
    create_requirement,
    create_risk,
    generic_link,
    grant_project_role,
    levels,
    link_type_id,
    mitigate_with_requirement,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_user, create_project


def _treatments(client, token, project_id, risk_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/risks/{risk_id}/treatments", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _risk(client, token, project_id, risk_id) -> dict:
    return client.get(f"{project_base(project_id)}/risks/{risk_id}", headers=auth_headers(token)).json()


# --- Seeds and provider -------------------------------------------------------


def test_the_module_seeds_its_own_link_types_and_leaves_core_ones_alone(client, admin_token):
    org, _project, token = setup(client, admin_token, "Risk Treat Seeds Co")
    rows = {r["forward_name"]: r for r in client.get(f"/api/v1/orgs/{org['id']}/link-types", headers=auth_headers(token)).json()}
    assert rows["Treated by"]["reverse_name"] == "Treats"
    assert rows["Treated by"]["allowed_source_types"] == ["risk"]
    assert rows["Treated by"]["allowed_target_types"] == ["requirement_action"]
    assert rows["Impacts"]["allowed_source_types"] == ["risk"]
    assert "requirement" in rows["Impacts"]["allowed_target_types"]
    # "Mitigates", "Verified by" and "Related to" are core defaults and stay unrestricted.
    for name in ("Mitigates", "Verified by", "Related to"):
        assert rows[name]["allowed_source_types"] is None and rows[name]["allowed_target_types"] is None
    assert "risk_management" in get_link_type_seed_owners()["Addresses"]


def test_a_decision_may_address_a_risk_through_the_merged_addresses_type(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Addresses Co")
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/decisions", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    addresses = next(
        r for r in client.get(f"/api/v1/orgs/{org['id']}/link-types", headers=auth_headers(token)).json()
        if r["forward_name"] == "Addresses"
    )
    assert "risk" in addresses["allowed_target_types"] and "pain_point" in addresses["allowed_target_types"]
    assert addresses["allowed_source_types"] == ["decision"]


def test_a_risk_has_a_summary_for_the_link_system(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Treat Summary Co")
    risk = create_risk(client, token, project["id"])
    db = SessionLocal()
    try:
        summary = get_artefact_summary(db, "risk", uuid.UUID(risk["id"]))
    finally:
        db.close()
    assert summary is not None
    assert summary.label == f"{risk['unique_code']} {risk['title']}"
    assert summary.status == "identified" and summary.project_id == uuid.UUID(project["id"])
    assert summary.facets["status"] == ("identified", "Identified")


def test_a_risk_appears_in_the_link_graph_of_what_mitigates_it(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Graph Co")
    risk = create_risk(client, token, project["id"])
    _link, requirement = mitigate_with_requirement(client, token, org, project, risk["id"])
    graph = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/requirement/{requirement}/link-graph", headers=auth_headers(token),
    ).json()
    risk_nodes = [n for n in graph["nodes"] if n["type"] == "risk"]
    assert [n["id"] for n in risk_nodes] == [risk["id"]]
    assert risk_nodes[0]["label"].startswith(risk["unique_code"])


# --- Listing treatment links --------------------------------------------------


def test_a_linked_treatment_is_proposed_until_assessed(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat List Co")
    risk = create_risk(client, token, project["id"])
    link_id, requirement = mitigate_with_requirement(client, token, org, project, risk["id"], "Dual-source the board")
    body = _treatments(client, token, project["id"], risk["id"])
    assert body["effective_count"] == 0 and body["hidden_count"] == 0
    [item] = body["items"]
    assert item["link_id"] == link_id and item["other_id"] == requirement and item["other_type"] == "requirement"
    assert item["relationship"] == "Is mitigated by" and item["other_type_label"] == "Requirement"
    assert "Dual-source the board" in item["label"]
    assert item["status"] == "proposed" and item["rationale"] == "" and item["assessed_by"] is None


def test_an_action_treats_a_risk_from_the_risk_side(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Action Co")
    risk = create_risk(client, token, project["id"])
    action = create_action(client, token, project["id"])
    resp = generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Treated by"), "outgoing",
        "requirement_action", action,
    )
    assert resp.status_code == 201, resp.text
    [item] = _treatments(client, token, project["id"], risk["id"])["items"]
    assert item["relationship"] == "Treated by" and item["other_type"] == "requirement_action"


def test_verification_and_impact_links_are_not_treatments(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat NotTreat Co")
    risk = create_risk(client, token, project["id"])
    action = create_action(client, token, project["id"], "Run the thermal test")
    requirement = create_requirement(client, token, project["id"], "Thermal limit")
    assert generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Verified by"), "outgoing",
        "requirement_action", action,
    ).status_code == 201
    assert generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Impacts"), "outgoing",
        "requirement", requirement,
    ).status_code == 201
    assert generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Related to"), "outgoing",
        "requirement", requirement,
    ).status_code == 201
    assert _treatments(client, token, project["id"], risk["id"])["items"] == []


def test_a_mitigates_link_in_the_wrong_direction_is_not_a_treatment(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Reversed Co")
    risk = create_risk(client, token, project["id"])
    requirement = create_requirement(client, token, project["id"])
    # "Risk Mitigates Requirement" inverts the type's meaning.
    assert generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Mitigates"), "outgoing",
        "requirement", requirement,
    ).status_code == 201
    assert _treatments(client, token, project["id"], risk["id"])["items"] == []


def test_the_impacts_type_refuses_a_target_it_does_not_cover(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Restrict Co")
    risk = create_risk(client, token, project["id"])
    action = create_action(client, token, project["id"])
    resp = generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Impacts"), "outgoing",
        "requirement_action", action,
    )
    assert resp.status_code == 400


# --- Assessing ---------------------------------------------------------------


def test_assessing_a_treatment_effective_counts_it_and_flags_the_risk(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Assess Co")
    risk = create_risk(client, token, project["id"])
    assert risk["effective_treatment_count"] == 0 and risk["is_effectively_treated"] is False
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    resp = assess(client, token, project["id"], risk["id"], link_id, "effective", "Dual sourcing removes the single point of failure.")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "effective" and body["rationale"].startswith("Dual sourcing")
    assert body["assessed_by"] and body["assessed_at"]
    after = _risk(client, token, project["id"], risk["id"])
    assert after["effective_treatment_count"] == 1 and after["is_effectively_treated"] is True
    assert _treatments(client, token, project["id"], risk["id"])["effective_count"] == 1


def test_only_an_effective_verdict_counts(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Verdicts Co")
    risk = create_risk(client, token, project["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    for verdict in ("ineffective", "needs_reassessment", "proposed"):
        assert assess(client, token, project["id"], risk["id"], link_id, verdict, "Because.").status_code == 200
        assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is False
    assert assess(client, token, project["id"], risk["id"], link_id, "effective").status_code == 200
    assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is True
    # The verdict is replaced, not duplicated.
    assert assess(client, token, project["id"], risk["id"], link_id, "ineffective", "Test failed.").status_code == 200
    [item] = _treatments(client, token, project["id"], risk["id"])["items"]
    assert item["status"] == "ineffective" and item["rationale"] == "Test failed."
    assert _risk(client, token, project["id"], risk["id"])["effective_treatment_count"] == 0


def test_effective_and_ineffective_need_a_rationale(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Rationale Co")
    risk = create_risk(client, token, project["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    for verdict in ("effective", "ineffective"):
        resp = assess(client, token, project["id"], risk["id"], link_id, verdict, "   ")
        assert resp.status_code == 409 and "rationale" in resp.text
    assert _treatments(client, token, project["id"], risk["id"])["items"][0]["status"] == "proposed"
    assert assess(client, token, project["id"], risk["id"], link_id, "proposed", "").status_code == 200


def test_unknown_verdict_is_422(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat BadVerdict Co")
    risk = create_risk(client, token, project["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id, "great").status_code == 422


def test_the_owner_and_a_risk_manager_may_assess_but_a_plain_member_may_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Authz Co")
    owner_id, owner_token = add_member(client, token, org["id"], project["id"], "owner@risk-treat-authz.example.com")
    _, member_token = add_member(client, token, org["id"], project["id"], "member@risk-treat-authz.example.com")
    manager_id, manager_token = add_member(client, token, org["id"], project["id"], "manager@risk-treat-authz.example.com")
    grant_project_role(client, token, project["id"], manager_id, "risk_manager")
    risk = create_risk(client, token, project["id"], owner_id=owner_id)
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])

    assert assess(client, member_token, project["id"], risk["id"], link_id).status_code == 403
    assert assess(client, owner_token, project["id"], risk["id"], link_id).status_code == 200
    assert assess(client, manager_token, project["id"], risk["id"], link_id, "ineffective", "Superseded.").status_code == 200
    # A plain member can still read the verdicts.
    [item] = _treatments(client, member_token, project["id"], risk["id"])["items"]
    assert item["status"] == "ineffective"


def test_a_link_that_is_not_this_risks_treatment_is_404(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Foreign Co")
    risk = create_risk(client, token, project["id"])
    other = create_risk(client, token, project["id"], title="Another risk")
    other_link, _ = mitigate_with_requirement(client, token, org, project, other["id"])
    assert assess(client, token, project["id"], risk["id"], other_link).status_code == 404
    assert assess(client, token, project["id"], risk["id"], str(uuid.uuid4())).status_code == 404
    # A verification link on this very risk is not a treatment link either.
    action = create_action(client, token, project["id"])
    verified = generic_link(
        client, token, project["id"], risk["id"], link_type_id(client, token, org["id"], "Verified by"), "outgoing",
        "requirement_action", action,
    ).json()["id"]
    assert assess(client, token, project["id"], risk["id"], verified).status_code == 404
    assert _risk(client, token, project["id"], other["id"])["effective_treatment_count"] == 0


def test_an_archived_risk_cannot_be_assessed(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Archived Co")
    risk = create_risk(client, token, project["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    client.post(f"{project_base(project['id'])}/risks/{risk['id']}/archive", headers=auth_headers(token))
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 409


def test_deleting_the_link_drops_its_verdict(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Delete Co")
    risk = create_risk(client, token, project["id"])
    link_id = add_effective_treatment(client, token, org, project, risk["id"])
    assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is True
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/risk/{risk['id']}/links/{link_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 204, resp.text
    assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is False
    assert _treatments(client, token, project["id"], risk["id"])["items"] == []


def test_each_assessment_is_audit_logged_with_the_old_and_new_verdict(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Audit Co")
    risk = create_risk(client, token, project["id"])
    link_id, requirement = mitigate_with_requirement(client, token, org, project, risk["id"])
    assess(client, token, project["id"], risk["id"], link_id, "effective")
    assess(client, token, project["id"], risk["id"], link_id, "ineffective", "Regressed.")
    db = SessionLocal()
    try:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == risk["id"],AuditEvent.action == "treatment_assessed")
            .order_by(AuditEvent.created_at)
        ).all()
        details = [e.detail for e in events]
    finally:
        db.close()
    assert [(d["from"], d["to"]) for d in details] == [("proposed", "effective"), ("effective", "ineffective")]
    assert details[0]["other_id"] == requirement and details[0]["link_id"] == link_id


# --- Register view -----------------------------------------------------------


def test_the_list_can_be_filtered_to_risks_without_an_effective_treatment(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Filter Co")
    treated = create_risk(client, token, project["id"], title="Treated")
    untreated = create_risk(client, token, project["id"], title="Untreated")
    proposed_only = create_risk(client, token, project["id"], title="Only proposed")
    add_effective_treatment(client, token, org, project, treated["id"])
    mitigate_with_requirement(client, token, org, project, proposed_only["id"])

    def ids(**params):
        resp = client.get(f"{project_base(project['id'])}/risks", params=params, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return {r["id"] for r in resp.json()}

    assert ids() == {treated["id"], untreated["id"], proposed_only["id"]}
    assert ids(effectively_treated="false") == {untreated["id"], proposed_only["id"]}
    assert ids(effectively_treated="true") == {treated["id"]}


# --- The Mitigated guard ------------------------------------------------------


def _ready_for_mitigated(client, token, project, risk, org) -> None:
    lv = levels(client, token, project["id"])
    owner = create_org_user(client, token, org["id"], f"owner-{uuid.uuid4().hex[:8]}@risk-treat-guard.example.com")
    body = {
        "inherent_likelihood_level_id": next(iter(lv["likelihood"].values())),
        "inherent_consequence_level_id": next(iter(lv["consequence"].values())),
        "residual_likelihood_level_id": next(iter(lv["likelihood"].values())),
        "residual_consequence_level_id": next(iter(lv["consequence"].values())),
        "owner_id": owner, "treatment_strategy": "mitigate",
    }
    assert client.put(f"{project_base(project['id'])}/risks/{risk['id']}", json=body, headers=auth_headers(token)).status_code == 200
    for status in ("assessed", "treatment_planned", "treatment_in_progress"):
        resp = client.post(
            f"{project_base(project['id'])}/risks/{risk['id']}/transition", json={"status": status}, headers=auth_headers(token)
        )
        assert resp.status_code == 200, resp.text


def _to_mitigated(client, token, project_id, risk_id):
    return client.post(
        f"{project_base(project_id)}/risks/{risk_id}/transition", json={"status": "mitigated"}, headers=auth_headers(token)
    )


def test_mitigated_needs_an_effective_treatment_not_just_a_link(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Guard Co")
    risk = create_risk(client, token, project["id"])
    _ready_for_mitigated(client, token, project, risk, org)

    resp = _to_mitigated(client, token, project["id"], risk["id"])
    assert resp.status_code == 409 and "treatment assessed effective" in resp.text

    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    resp = _to_mitigated(client, token, project["id"], risk["id"])
    assert resp.status_code == 409 and "treatment assessed effective" in resp.text

    assess(client, token, project["id"], risk["id"], link_id, "ineffective", "Does not address the cause.")
    assert _to_mitigated(client, token, project["id"], risk["id"]).status_code == 409

    assess(client, token, project["id"], risk["id"], link_id, "effective")
    resp = _to_mitigated(client, token, project["id"], risk["id"])
    assert resp.status_code == 200 and resp.json()["status"] == "mitigated"


def test_a_treatment_flagged_for_reassessment_no_longer_satisfies_the_guard(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Stale Co")
    risk = create_risk(client, token, project["id"])
    _ready_for_mitigated(client, token, project, risk, org)
    link_id = add_effective_treatment(client, token, org, project, risk["id"])
    assess(client, token, project["id"], risk["id"], link_id, "needs_reassessment", "")
    assert _to_mitigated(client, token, project["id"], risk["id"]).status_code == 409


# --- Tenancy -----------------------------------------------------------------


def test_another_projects_or_tenants_risk_has_no_treatments_for_you(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Treat Tenant A Co")
    other_org, other_project, other_token = setup(client, admin_token, "Risk Treat Tenant B Co")
    risk = create_risk(client, token, project["id"])
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])

    base = f"{project_base(other_project['id'])}/risks/{risk['id']}/treatments"
    assert client.get(base, headers=auth_headers(other_token)).status_code == 404
    assert client.put(f"{base}/{link_id}", json={"status": "effective", "rationale": "x"}, headers=auth_headers(other_token)).status_code == 404
    # And the real project refuses a user from the other organisation outright.
    own = f"{project_base(project['id'])}/risks/{risk['id']}/treatments"
    assert client.get(own, headers=auth_headers(other_token)).status_code in (403, 404)
    assert other_org["id"] != org["id"]


# --- Cross-level (parent/child project) treatments -----------------------------


def _risk_with_parent_requirement(client, admin_token, org_name):
    """A child-project risk mitigated by a requirement in its parent project.

    Returns:
        `(org, parent, child, org admin token, risk, link id, requirement id)`.
    """
    org, parent, token = setup(client, admin_token, org_name)
    client.patch(f"/api/v1/projects/{parent['id']}", json={"can_be_parent": True}, headers=auth_headers(token))
    child = create_project(client, token, org["id"], f"{org_name} Child", parent_project_id=parent["id"])
    risk = create_risk(client, token, child["id"])
    requirement = create_requirement(client, token, parent["id"], "Parent mitigation")
    resp = client.post(
        f"/api/v1/projects/{child['id']}/artefacts/risk/{risk['id']}/links",
        json={
            "link_type_id": link_type_id(client, token, org["id"], "Mitigates"), "direction": "incoming",
            "other_type": "requirement", "other_id": requirement, "other_project_id": parent["id"],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return org, parent, child, token, risk, resp.json()["id"], requirement


def test_a_parent_projects_requirement_can_be_assessed_as_a_childs_risk_treatment(client, admin_token):
    _org, _parent, child, token, risk, link_id, requirement = _risk_with_parent_requirement(
        client, admin_token, "Risk Treat Nested Co"
    )
    [item] = _treatments(client, token, child["id"], risk["id"])["items"]
    assert item["link_id"] == link_id and item["other_id"] == requirement and "Parent mitigation" in item["label"]
    assert assess(client, token, child["id"], risk["id"], link_id).status_code == 200
    body = _treatments(client, token, child["id"], risk["id"])
    assert body["effective_count"] == 1 and body["hidden_count"] == 0


def test_a_cross_level_treatment_is_hidden_from_a_user_who_cannot_open_the_parent(client, admin_token):
    org, _parent, child, token, risk, _link_id, _req = _risk_with_parent_requirement(
        client, admin_token, "Risk Treat Nested Hidden Co"
    )
    _user_id, member_token = add_member(client, token, org["id"], child["id"], "nested-child-only@example.com")
    body = _treatments(client, member_token, child["id"], risk["id"])
    assert body["items"] == [] and body["hidden_count"] == 1 and body["effective_count"] == 0


def test_a_cross_level_treatment_goes_dormant_when_the_projects_are_unnested(client, admin_token):
    _org, _parent, child, token, risk, link_id, _req = _risk_with_parent_requirement(
        client, admin_token, "Risk Treat Nested Dormant Co"
    )
    assert assess(client, token, child["id"], risk["id"], link_id).status_code == 200
    resp = client.patch(f"/api/v1/projects/{child['id']}", json={"parent_project_id": None}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = _treatments(client, token, child["id"], risk["id"])
    assert body["items"] == [] and body["effective_count"] == 0
