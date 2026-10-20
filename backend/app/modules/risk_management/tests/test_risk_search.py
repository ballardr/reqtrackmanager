"""Tests for Risk Management's contribution to the global search: a risk is found by title and code, by a
declared text field only when that field is searched, and not once its module or the project role is gone."""

from __future__ import annotations

from app.modules.risk_management.tests._helpers import create_risk, setup
from tests.conftest import auth_headers


def _search(client, token, body):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_risk_is_found_by_title_code_and_a_declared_field_when_searched(client, admin_token):
    _, project, token = setup(client, admin_token, "Search Risk Co")
    risk = create_risk(client, token, project["id"], title="Gearbox riskzq failure", cause="worn riskcausezq bearing")
    scope = {"scope": "project", "project_id": project["id"]}

    hit = _search(client, token, {"q": "riskzq", **scope})["hits"][0]
    assert hit["id"] == risk["id"] and hit["type"] == "risk" and hit["status_label"] == "Identified"
    assert [h["id"] for h in _search(client, token, {"q": hit["code"], **scope})["hits"]] == [risk["id"]]

    assert _search(client, token, {"q": "riskcausezq", **scope})["hits"] == []
    by_cause = _search(client, token, {"q": "riskcausezq", "fields": ["id", "title", "cause"], **scope})
    assert [h["id"] for h in by_cause["hits"]] == [risk["id"]]
    assert by_cause["hits"][0]["snippet"]["field_label"] == "Cause"


def test_a_risk_is_not_found_once_the_module_is_off(client, admin_token):
    org, project, token = setup(client, admin_token, "Search Risk Off Co")
    create_risk(client, token, project["id"], title="Vanishing offzq risk")
    scope = {"scope": "project", "project_id": project["id"]}
    assert len(_search(client, token, {"q": "offzq", **scope})["hits"]) == 1
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/risk_management", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert _search(client, token, {"q": "offzq", **scope})["hits"] == []
