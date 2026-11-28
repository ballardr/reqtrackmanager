"""Tests for the record categories other modules report to governance health (`decisions.health`, `risk_management.health`,
`context_strategy.health`): each type appears in the project's health once its module is on, counts only live records of
the project, and moves to done when its record reaches the settled outcome."""

from __future__ import annotations

from app.modules.decisions.tests.test_decisions_api import _create_decision, _first_decision_type_id
from app.modules.risk_management.tests._helpers import create_risk
from app.modules.traceability.tests.test_governance_health import _category, _get_health
from app.modules.traceability.tests.test_governance_profiles import _setup
from tests.conftest import auth_headers, create_project

MODULES = ("decisions", "risk_management", "context_strategy")


def _world(client, admin_token, name):
    """An organisation with Governance and the three content modules on, one project, and its administrator's token."""
    org, token = _setup(client, admin_token, name)
    for key in MODULES:
        resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{key}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
    return org, create_project(client, token, org["id"], f"{name} project"), token


def _post(client, token, url, body) -> dict:
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_each_content_module_reports_its_types_once_it_is_on(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Categories Org")
    keys = {c["key"] for c in _get_health(client, token, project["id"])["categories"]}
    assert {
        "requirement", "change_request", "decisions:decision", "risk_management:risk", "context_strategy:strategy",
        "context_strategy:future_state", "context_strategy:guiding_principle", "context_strategy:open_question",
    } <= keys

    other, other_token = _setup(client, admin_token, "Health Categories Bare Org")
    bare = create_project(client, other_token, other["id"], "Bare")
    bare_keys = {c["key"] for c in _get_health(client, other_token, bare["id"])["categories"]}
    assert bare_keys == {"requirement", "change_request", "project_stage", "traceability:traceability_exceptions"}


def test_a_new_record_counts_in_its_category_and_is_not_done(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Categories Counts Org")
    pid = project["id"]
    _create_decision(client, token, pid, _first_decision_type_id(client, token, pid))
    create_risk(client, token, pid)
    cs = f"/api/v1/projects/{pid}/modules/context_strategy"
    _post(client, token, cs + "/strategies", {"title": "Lead", "objective": "Win"})
    _post(client, token, cs + "/future-states", {"title": "Target", "description": "A state"})
    _post(client, token, cs + "/guiding-principles", {"name": "Be safe", "principle_statement": "Safety first"})
    _post(client, token, cs + "/open-questions", {"question": "Which vendor?"})
    view = _get_health(client, token, pid)
    for key in (
        "decisions:decision", "risk_management:risk", "context_strategy:strategy", "context_strategy:future_state",
        "context_strategy:guiding_principle", "context_strategy:open_question",
    ):
        figure = _category(view, key)
        assert (figure["total"], figure["done"]) == (1, 0), key
    assert _category(view, "context_strategy:open_question")["kind"] == "outstanding"
    assert _category(view, "context_strategy:open_question")["outstanding"] == 1


def test_a_resolved_question_and_a_withdrawn_one_are_done(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Categories Questions Org")
    pid = project["id"]
    base = f"/api/v1/projects/{pid}/modules/context_strategy/open-questions"
    first = _post(client, token, base, {"question": "Withdraw me"})
    _post(client, token, base, {"question": "Keep me open"})
    moved = client.post(f"{base}/{first['id']}/investigate", json={}, headers=auth_headers(token))
    assert moved.status_code == 200, moved.text
    resp = client.post(f"{base}/{first['id']}/withdraw", json={"comment": "Moot."}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    figure = _category(_get_health(client, token, pid), "context_strategy:open_question")
    assert (figure["total"], figure["done"], figure["outstanding"]) == (2, 1, 1)
