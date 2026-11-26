"""Parity tests for the types whose approval and lifecycle already run on the engine seams: Decisions, Future States, Guiding
Principles and Strategies. Each decision-making path is refused to a person the type's own rule does not admit, whether
Governance is off, on with no policy or on with an unrelated policy, and is admitted by the role a policy names. The
default approvers, approval separation and the lifecycle moves of each type are pinned by the type's own suites."""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.modules.decisions.models import Decision
from app.modules.decisions.service import propose_decision, submit_decision_for_review
from app.modules.decisions.tests.test_decisions_api import _base as decision_base
from app.modules.decisions.tests.test_decisions_workflow import _create_decision, _current_user_id, _first_decision_type_id
from app.modules.traceability.tests.test_governance_approval_policy import MEMBER, _enable, _member, _set_project, _world
from tests.conftest import auth_headers
from tests.test_approval_separation import _project_base


def _under_review_decision(client, token, project_id) -> str:
    user_id = _current_user_id(client, token)
    decision_id = _create_decision(
        project_id=uuid.UUID(project_id), decision_type_id=_first_decision_type_id(uuid.UUID(project_id)),
        user_id=user_id, code="DEC-001",
    )
    with SessionLocal() as db:
        decision = db.get(Decision, decision_id)
        assert decision is not None
        propose_decision(db, decision, user_id)
        submit_decision_for_review(db, decision, user_id)
        db.commit()
    return str(decision_id)


def _post(client, token, url, body=None):
    return client.post(url, json=body or {"comment": "Checked."}, headers=auth_headers(token))


def _create(client, token, url, payload):
    resp = client.post(url, json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _advance(client, token, url):
    for step in ("propose", "submit-for-review"):
        assert client.post(f"{url}/{step}", headers=auth_headers(token)).status_code == 200


def test_a_decision_rejection_follows_the_approval_policy(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Parity Decision Reject Org")
    _enable(client, token, org["id"], "decisions")
    _, holder = _member(client, token, org["id"], project["id"], "member")
    base = decision_base(project["id"])
    decision_id = _under_review_decision(client, token, project["id"])

    assert _post(client, holder, f"{base}/{decision_id}/reject").status_code == 403
    _set_project(client, token, project["id"], "decision", [MEMBER])
    assert _post(client, holder, f"{base}/{decision_id}/reject").status_code == 200


def test_a_future_state_and_a_guiding_principle_follow_the_approval_policy(client, admin_token):
    org, project, token, _, _ = _world(client, admin_token, "Parity Strategy Types Org")
    _enable(client, token, org["id"], "context_strategy")
    _, holder = _member(client, token, org["id"], project["id"], "member")
    base = _project_base(project["id"])

    future_state = _create(client, token, base + "/future-states", {"title": "Future", "target_date": "2031-03-31", "outcomes": "More"})
    _advance(client, token, f"{base}/future-states/{future_state}")
    principle = _create(client, token, base + "/guiding-principles", {"name": "Principle", "principle_statement": "Always"})
    assert client.post(f"{base}/guiding-principles/{principle}/propose", headers=auth_headers(token)).status_code == 200

    future_state_url = f"{base}/future-states/{future_state}/approve"
    principle_url = f"{base}/guiding-principles/{principle}/approve"
    assert _post(client, holder, future_state_url).status_code == 403
    assert _post(client, holder, principle_url).status_code == 403
    # A policy for another type admits neither.
    _set_project(client, token, project["id"], "strategy", [MEMBER])
    assert _post(client, holder, future_state_url).status_code == 403
    _set_project(client, token, project["id"], "future_state", [MEMBER])
    _set_project(client, token, project["id"], "guiding_principle", [MEMBER])
    assert _post(client, holder, future_state_url).status_code == 200
    assert _post(client, holder, principle_url).status_code == 200


def test_accepting_a_pain_point_is_an_approval_step_for_policy_and_separation(client, admin_token):
    from app.modules.context_strategy.tests.test_context_strategy_pain_point_api import (
        _advance_to_triaged,
        _create_pain_point,
    )

    org, project, token, _, _ = _world(client, admin_token, "Parity Pain Point Org")
    _enable(client, token, org["id"], "context_strategy")
    _, holder = _member(client, token, org["id"], project["id"], "member")
    base = _project_base(project["id"])
    pain_point = _create_pain_point(client, token, project["id"])
    _advance_to_triaged(client, token, project["id"], pain_point["id"])
    accept = f"{base}/pain-points/{pain_point['id']}/accept"

    assert _post(client, holder, accept).status_code == 403
    _set_project(client, token, project["id"], "pain_point", [MEMBER])
    # A policy role admits accepting only; the other decision steps keep the decide-tier right.
    assert _post(client, holder, f"{base}/pain-points/{pain_point['id']}/address").status_code == 403
    separate = client.put(
        f"/api/v1/projects/{project['id']}/approval-separation/pain_point", json={"separate_approver": True}, headers=auth_headers(token),
    )
    assert separate.status_code == 200, separate.text
    refused = _post(client, token, accept)  # the submitter may not accept it when a separate approver is required
    assert refused.status_code == 403 and "separate approver" in refused.json()["detail"]
    assert _post(client, holder, accept).status_code == 200
