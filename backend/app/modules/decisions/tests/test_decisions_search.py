"""Tests for Decision Management's contribution to the global search: a decision is found by title and code,
by a declared record section only when that field is searched, and with its status labelled."""

from __future__ import annotations

from app.modules.decisions.tests.test_decisions_api import _create_decision, _first_decision_type_id, _setup
from tests.conftest import auth_headers


def _search(client, token, body):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_decision_is_found_by_title_code_and_a_declared_section_when_searched(client, admin_token):
    _, project, token = _setup(client, admin_token, "Search Decision Co")
    decision = _create_decision(
        client, token, project["id"], _first_decision_type_id(client, token, project["id"]),
        title="Adopt decisionzq queue", rationale="because of ratiozq throughput",
    )
    scope = {"scope": "project", "project_id": project["id"]}

    hit = _search(client, token, {"q": "decisionzq", **scope})["hits"][0]
    assert hit["id"] == decision["id"] and hit["type"] == "decision" and hit["status_label"] == "Draft"
    assert [h["id"] for h in _search(client, token, {"q": hit["code"], **scope})["hits"]] == [decision["id"]]

    assert _search(client, token, {"q": "ratiozq", **scope})["hits"] == []
    by_rationale = _search(client, token, {"q": "ratiozq", "fields": ["id", "title", "rationale"], **scope})
    assert [h["id"] for h in by_rationale["hits"]] == [decision["id"]]
    assert by_rationale["hits"][0]["snippet"]["field_label"] == "Rationale"
