"""Tests for the Risk Management module's Phase 2 lifecycle
(docs/plans/module-03-risk-management-plan.md), through the real HTTP endpoints.

Covers: the full transition table (legal and illegal moves, the offered
`allowed_next_statuses`), the per-target guards (inherent rating, owner and
strategy, residual rating, acceptance criteria), the distinct Risk Acceptor role
and FGAC atom, the AI-approval gate for MCP-reached acceptance, the `ACCEPTED`
content lock, versioning and audit logging of each move, archived and
cross-tenant behaviour.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.modules.risk_management.enums import RiskStatus
from app.modules.risk_management.service import RISK_ALLOWED_TRANSITIONS
from app.modules.risk_management.tests._helpers import (
    add_effective_treatment,
    add_member,
    create_risk,
    grant_project_role,
    levels,
    project_base,
    setup,
    user_ref,
)
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project
from tests.test_ai_approvals_via_mcp import _mcp_headers, _set_org_ai_approvals, _set_project_ai_approvals


def _url(project_id, risk_id) -> str:
    return f"{project_base(project_id)}/risks/{risk_id}"


def _move(client, token, project_id, risk_id, status, comment="", headers=None):
    return client.post(
        _url(project_id, risk_id) + "/transition", json={"status": status, "comment": comment},
        headers=headers or auth_headers(token),
    )


def _score(client, token, project, risk, *, residual: bool = False) -> dict:
    """Sets the (inherent or residual) Likelihood and Consequence levels."""
    lv = levels(client, token, project["id"])
    prefix = "residual" if residual else "inherent"
    body = {
        f"{prefix}_likelihood_level_id": next(iter(lv["likelihood"].values())),
        f"{prefix}_consequence_level_id": next(iter(lv["consequence"].values())),
    }
    resp = client.put(_url(project["id"], risk["id"]), json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ready(client, token, org, project, risk, *, owner: str | None = None) -> dict:
    """Fills everything every guard needs: both ratings, owner, strategy, criteria
    and one effective treatment."""
    add_effective_treatment(client, token, org, project, risk["id"])
    _score(client, token, project, risk)
    _score(client, token, project, risk, residual=True)
    owner = owner or create_owner(client, token, org)
    resp = client.put(
        _url(project["id"], risk["id"]),
        json={"owner": user_ref(owner), "treatment_strategy": "mitigate", "acceptance_criteria": "Residual is Low."},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_owner(client, token, org) -> str:
    return create_org_user(client, token, org["id"], f"owner-{uuid.uuid4().hex[:8]}@risk-life.example.com")


def _walk(client, token, project_id, risk_id, *statuses) -> None:
    for status in statuses:
        resp = _move(client, token, project_id, risk_id, status)
        assert resp.status_code == 200, f"{status}: {resp.text}"


# --- Transition table --------------------------------------------------------


def test_table_covers_every_status_and_never_loops_to_itself():
    assert set(RISK_ALLOWED_TRANSITIONS) == set(RiskStatus)
    for source, targets in RISK_ALLOWED_TRANSITIONS.items():
        assert source not in targets
        # Every non-closed state can eventually reach CLOSED (no dead ends).
    seen, frontier = set(), [RiskStatus.IDENTIFIED]
    while frontier:
        state = frontier.pop()
        if state not in seen:
            seen.add(state)
            frontier.extend(RISK_ALLOWED_TRANSITIONS[state])
    assert seen == set(RiskStatus)
    for state in RiskStatus:
        if state != RiskStatus.CLOSED:
            reachable, frontier = set(), [state]
            while frontier:
                s = frontier.pop()
                if s not in reachable:
                    reachable.add(s)
                    frontier.extend(RISK_ALLOWED_TRANSITIONS[s])
            assert RiskStatus.CLOSED in reachable, state


def test_main_line_to_mitigated_and_closed_records_each_version(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Main Co")
    risk = create_risk(client, token, project["id"])
    assert risk["allowed_next_statuses"] == ["assessed", "rejected"]
    _ready(client, token, org, project, risk)

    for target in ("assessed", "treatment_planned", "treatment_in_progress", "mitigated", "closed"):
        resp = _move(client, token, project["id"], risk["id"], target, comment=f"to {target}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == target
    body = resp.json()
    assert body["allowed_next_statuses"] == ["assessed"]

    versions = client.get(_url(project["id"], risk["id"]) + "/versions", headers=auth_headers(token)).json()
    moves = [v for v in versions if v["change_note"].startswith("to ")]
    assert [v["status"] for v in moves] == ["assessed", "treatment_planned", "treatment_in_progress", "mitigated", "closed"]
    assert versions[-1]["valid_to"] is None and all(v["valid_to"] for v in versions[:-1])


def test_default_change_note_describes_the_move(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Note Co")
    risk = _score_and_create(client, token, project)
    assert _move(client, token, project["id"], risk["id"], "assessed").status_code == 200
    versions = client.get(_url(project["id"], risk["id"]) + "/versions", headers=auth_headers(token)).json()
    assert versions[-1]["change_note"] == "Status: Identified -> Assessed."


def _score_and_create(client, token, project):
    risk = create_risk(client, token, project["id"])
    _score(client, token, project, risk)
    return risk


@pytest.mark.parametrize("outcome", ["transferred", "avoided", "realised"])
def test_outcomes_from_assessed_lead_to_closed(client, admin_token, outcome):
    _, project, token = setup(client, admin_token, f"Risk Life {outcome} Co")
    risk = _score_and_create(client, token, project)
    _walk(client, token, project["id"], risk["id"], "assessed", outcome, "closed")


def test_rejected_from_identified_then_closed_or_back_to_identified(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Reject Co")
    risk = create_risk(client, token, project["id"])
    _walk(client, token, project["id"], risk["id"], "rejected", "identified", "rejected", "closed")


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        ((), "closed"),
        ((), "mitigated"),
        ((), "treatment_planned"),
        (("assessed",), "mitigated"),
        (("assessed",), "treatment_in_progress"),
        (("assessed",), "closed"),
        (("assessed",), "identified"),
        (("rejected",), "assessed"),
    ],
)
def test_illegal_moves_are_409_and_leave_the_risk_alone(client, admin_token, path, bad):
    org, project, token = setup(client, admin_token, f"Risk Life Bad {len(path)}{bad[:3]} Co")
    risk = create_risk(client, token, project["id"])
    _ready(client, token, org, project, risk)
    _walk(client, token, project["id"], risk["id"], *path)
    before = client.get(_url(project["id"], risk["id"]), headers=auth_headers(token)).json()
    resp = _move(client, token, project["id"], risk["id"], bad)
    assert resp.status_code == 409 and "Cannot move" in resp.text
    after = client.get(_url(project["id"], risk["id"]), headers=auth_headers(token)).json()
    assert after["status"] == before["status"] and after["version_number"] == before["version_number"]


def test_a_reassessment_moves_a_risk_back_and_closed_reopens(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Back Co")
    risk = create_risk(client, token, project["id"])
    _ready(client, token, org, project, risk)
    _walk(client, token, project["id"], risk["id"], "assessed", "treatment_planned", "treatment_in_progress", "mitigated")
    _walk(client, token, project["id"], risk["id"], "treatment_in_progress", "treatment_planned", "assessed")
    _walk(client, token, project["id"], risk["id"], "treatment_planned", "treatment_in_progress", "mitigated", "closed", "assessed")


def test_a_settled_risk_can_still_be_realised(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Realised Co")
    risk = create_risk(client, token, project["id"])
    _ready(client, token, org, project, risk)
    _walk(client, token, project["id"], risk["id"], "assessed", "treatment_planned", "treatment_in_progress", "mitigated", "realised")


def test_unknown_status_is_422(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Unknown Co")
    risk = create_risk(client, token, project["id"])
    assert _move(client, token, project["id"], risk["id"], "done").status_code == 422


# --- Guards ------------------------------------------------------------------


def test_assessed_needs_an_inherent_rating(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Guard Assessed Co")
    risk = create_risk(client, token, project["id"])
    resp = _move(client, token, project["id"], risk["id"], "assessed")
    assert resp.status_code == 409 and "inherent rating" in resp.text
    _score(client, token, project, risk)
    assert _move(client, token, project["id"], risk["id"], "assessed").status_code == 200


def test_treatment_planned_needs_owner_and_strategy(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Guard Plan Co")
    risk = _score_and_create(client, token, project)
    _walk(client, token, project["id"], risk["id"], "assessed")
    resp = _move(client, token, project["id"], risk["id"], "treatment_planned")
    assert resp.status_code == 409 and "an owner and a treatment strategy" in resp.text
    owner = create_owner(client, token, org)
    client.put(_url(project["id"], risk["id"]), json={"owner": user_ref(owner)}, headers=auth_headers(token))
    assert "a treatment strategy" in _move(client, token, project["id"], risk["id"], "treatment_planned").text
    client.put(_url(project["id"], risk["id"]), json={"treatment_strategy": "mitigate"}, headers=auth_headers(token))
    assert _move(client, token, project["id"], risk["id"], "treatment_planned").status_code == 200


def test_mitigated_needs_a_residual_rating(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Guard Mitigated Co")
    risk = _score_and_create(client, token, project)
    owner = create_owner(client, token, org)
    client.put(_url(project["id"], risk["id"]), json={"owner": user_ref(owner), "treatment_strategy": "mitigate"}, headers=auth_headers(token))
    _walk(client, token, project["id"], risk["id"], "assessed", "treatment_planned", "treatment_in_progress")
    resp = _move(client, token, project["id"], risk["id"], "mitigated")
    assert resp.status_code == 409 and "residual rating" in resp.text
    _score(client, token, project, risk, residual=True)
    add_effective_treatment(client, token, org, project, risk["id"])
    assert _move(client, token, project["id"], risk["id"], "mitigated").status_code == 200


def test_a_three_axis_model_needs_detectability_before_assessed(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Three Axis Co")
    h = auth_headers(token)
    risk = _score_and_create(client, token, project)
    resp = client.put(f"/api/v1/orgs/{org['id']}/scoring-schemes/risk/default-model", json={"model": "lxcxd"}, headers=h)
    assert resp.status_code == 200, resp.text
    resp = _move(client, token, project["id"], risk["id"], "assessed")
    assert resp.status_code == 409 and "inherent rating" in resp.text
    detect = next(iter(levels(client, token, project["id"])["detectability"].values()))
    client.put(_url(project["id"], risk["id"]), json={"inherent_detectability_level_id": detect}, headers=h)
    assert _move(client, token, project["id"], risk["id"], "assessed").status_code == 200


# --- Acceptance --------------------------------------------------------------


def _assessed_and_ready(client, token, org, project):
    risk = create_risk(client, token, project["id"])
    _ready(client, token, org, project, risk)
    _walk(client, token, project["id"], risk["id"], "assessed")
    return risk


def test_accepted_needs_residual_rating_and_criteria(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Accept Guard Co")
    risk = _score_and_create(client, token, project)
    _walk(client, token, project["id"], risk["id"], "assessed")
    resp = _move(client, token, project["id"], risk["id"], "accepted")
    assert resp.status_code == 409 and "residual rating" in resp.text and "acceptance criteria" in resp.text
    _score(client, token, project, risk, residual=True)
    assert "acceptance criteria" in _move(client, token, project["id"], risk["id"], "accepted").text
    client.put(_url(project["id"], risk["id"]), json={"acceptance_criteria": "  "}, headers=auth_headers(token))
    assert _move(client, token, project["id"], risk["id"], "accepted").status_code == 409
    client.put(_url(project["id"], risk["id"]), json={"acceptance_criteria": "Within appetite."}, headers=auth_headers(token))
    assert _move(client, token, project["id"], risk["id"], "accepted", comment="Signed off").json()["status"] == "accepted"


def test_only_a_risk_acceptor_may_accept_and_a_manager_may_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Acceptor Co")
    risk = _assessed_and_ready(client, token, org, project)
    manager_id, manager = add_member(client, token, org["id"], project["id"], "manager@risk-life.example.com")
    grant_project_role(client, token, project["id"], manager_id, "risk_manager")
    assert _move(client, manager, project["id"], risk["id"], "accepted").status_code == 403
    assert _move(client, manager, project["id"], risk["id"], "treatment_planned").status_code == 200  # manager moves

    acceptor_id, acceptor = add_member(client, token, org["id"], project["id"], "acceptor@risk-life.example.com")
    grant_project_role(client, token, project["id"], acceptor_id, "risk_acceptor")
    # An acceptor is not thereby a manager.
    assert _move(client, acceptor, project["id"], risk["id"], "treatment_in_progress").status_code == 403
    assert client.put(_url(project["id"], risk["id"]), json={"title": "x"}, headers=auth_headers(acceptor)).status_code == 403
    resp = _move(client, acceptor, project["id"], risk["id"], "accepted")
    assert resp.status_code == 200 and resp.json()["status"] == "accepted"


def test_plain_member_cannot_move_a_risk(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Member Co")
    risk = _assessed_and_ready(client, token, org, project)
    _, member = add_member(client, token, org["id"], project["id"], "member@risk-life.example.com")
    for target in ("treatment_planned", "accepted", "rejected"):
        assert _move(client, member, project["id"], risk["id"], target).status_code == 403


def test_fgac_approve_grant_satisfies_the_acceptor_gate(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Fgac Co")
    risk = _assessed_and_ready(client, token, org, project)
    user_id, member = add_member(client, token, org["id"], project["id"], "fgac@risk-life.example.com")
    assert _move(client, member, project["id"], risk["id"], "accepted").status_code == 403
    with SessionLocal() as db:
        role = CustomRoleDefinition(organization_id=uuid.UUID(org["id"]), name="Risk approver", description="Test.", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("risk", "approve_baseline")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    assert _move(client, member, project["id"], risk["id"], "accepted").status_code == 200


def test_mcp_acceptance_needs_the_ai_approval_flags_but_other_moves_do_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Mcp Co")
    risk = _assessed_and_ready(client, token, org, project)
    mcp = _mcp_headers(token)
    resp = _move(client, token, project["id"], risk["id"], "accepted", headers=mcp)
    assert resp.status_code == 403 and "AI approval is not enabled" in resp.text

    _set_org_ai_approvals(client, token, org["id"], True)
    assert _move(client, token, project["id"], risk["id"], "accepted", headers=mcp).status_code == 403  # project flag still off
    assert _move(client, token, project["id"], risk["id"], "treatment_planned", headers=mcp).status_code == 200

    _set_project_ai_approvals(client, token, project["id"], True)
    # Back to a state from which acceptance is legal, then accept through MCP.
    assert _move(client, token, project["id"], risk["id"], "assessed", headers=mcp).status_code == 200
    resp = _move(client, token, project["id"], risk["id"], "accepted", comment="AI-assisted", headers=mcp)
    assert resp.status_code == 200 and resp.json()["status"] == "accepted"

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == risk["id"], AuditEvent.action == "status_changed")
        ).all()
    accepted = [e for e in events if e.detail["to"] == "accepted"]
    assert len(accepted) == 1 and accepted[0].detail["via"] == "mcp" and accepted[0].detail["comment"] == "AI-assisted"
    assert all("via" not in e.detail for e in events if e.detail["to"] != "accepted")


def test_ui_acceptance_ignores_the_ai_flags(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Ui Co")
    risk = _assessed_and_ready(client, token, org, project)
    assert _move(client, token, project["id"], risk["id"], "accepted").status_code == 200


# --- Accepted lock -----------------------------------------------------------


def test_an_accepted_assessment_cannot_be_edited_in_place(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Life Lock Co")
    risk = _assessed_and_ready(client, token, org, project)
    _walk(client, token, project["id"], risk["id"], "accepted")
    url, h = _url(project["id"], risk["id"]), auth_headers(token)
    lv = levels(client, token, project["id"])
    other = [i for i in lv["likelihood"].values() if i != risk_value(client, token, project, risk, "residual_likelihood_level_id")][0]

    for body in (
        {"residual_likelihood_level_id": other}, {"acceptance_criteria": "Weaker."}, {"treatment_strategy": "transfer"},
        {"inherent_likelihood_level_id": None},
    ):
        resp = client.put(url, json=body, headers=h)
        assert resp.status_code == 409 and "accepted" in resp.text.lower(), body

    # Re-sending an unchanged value, and unlocked fields, are fine.
    same = risk_value(client, token, project, risk, "residual_likelihood_level_id")
    assert client.put(url, json={"residual_likelihood_level_id": same, "title": "Renamed"}, headers=h).status_code == 200
    assert client.put(url, json={"review_date": "2027-01-01"}, headers=h).status_code == 200

    _walk(client, token, project["id"], risk["id"], "assessed")
    assert client.put(url, json={"residual_likelihood_level_id": other}, headers=h).status_code == 200


def risk_value(client, token, project, risk, field):
    return client.get(_url(project["id"], risk["id"]), headers=auth_headers(token)).json()[field]


# --- Archive, tenancy, audit -------------------------------------------------


def test_an_archived_risk_cannot_change_status(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Archived Co")
    risk = _score_and_create(client, token, project)
    client.post(_url(project["id"], risk["id"]) + "/archive", headers=auth_headers(token))
    resp = _move(client, token, project["id"], risk["id"], "assessed")
    assert resp.status_code == 409 and "unarchive" in resp.text
    client.post(_url(project["id"], risk["id"]) + "/unarchive", headers=auth_headers(token))
    assert _move(client, token, project["id"], risk["id"], "assessed").status_code == 200


def test_other_tenants_and_projects_get_404(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Tenant A Co")
    risk = _score_and_create(client, token, project)
    _, other_token = create_org_admin_in(client, admin_token, "Risk Life Tenant B Co")
    assert _move(client, other_token, project["id"], risk["id"], "assessed").status_code == 404

    org_a_project_2 = create_project(client, token, project["organization_id"], "Risk Life Second")
    assert _move(client, token, org_a_project_2["id"], risk["id"], "assessed").status_code == 404


def test_each_move_is_audit_logged_with_from_to_and_comment(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life Audit Co")
    risk = _score_and_create(client, token, project)
    _move(client, token, project["id"], risk["id"], "assessed", comment="Reviewed with the owner")
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == risk["id"], AuditEvent.action == "status_changed")
        ).one()
    assert event.detail == {"from": "identified", "to": "assessed", "comment": "Reviewed with the owner"}
    assert str(event.project_id) == project["id"]


def test_a_failed_move_writes_no_audit_event(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Life No Audit Co")
    risk = create_risk(client, token, project["id"])
    assert _move(client, token, project["id"], risk["id"], "assessed").status_code == 409
    with SessionLocal() as db:
        assert db.scalars(select(AuditEvent).where(AuditEvent.entity_id == risk["id"], AuditEvent.action == "status_changed")).first() is None


def test_acceptor_role_is_registered_with_the_approve_atom():
    from app.modules.risk_management.module import MODULE_DEFINITION

    role = {r.role_key: r for r in MODULE_DEFINITION.roles}["risk_acceptor"]
    assert role.scope == "project" and role.permissions == (encode_permission("risk", "approve_baseline"),)
