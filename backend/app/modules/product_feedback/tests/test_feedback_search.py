"""Tests for Product Feedback's contribution to the global search: a request is found by title and code, by its
description only when that field is searched, an inbox request only at organisation level while the inbox is on, and
not once the module is off. Each test builds its own organisation."""

from __future__ import annotations

from app.modules.product_feedback.tests._helpers import create_inbox_request, create_request, set_org_inbox, setup
from tests.conftest import auth_headers


def _search(client, token, body):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_request_is_found_by_title_code_and_a_declared_field_when_searched(client, admin_token):
    _, project, token = setup(client, admin_token, "Search Feedback Co")
    request = create_request(client, token, project["id"], title="Exporter fbzq wanted", description="needs the fbdescq format")
    scope = {"scope": "project", "project_id": project["id"]}

    hit = _search(client, token, {"q": "fbzq", **scope})["hits"][0]
    assert hit["id"] == request["id"] and hit["type"] == "enhancement_request" and hit["status_label"] == "New"
    assert [h["id"] for h in _search(client, token, {"q": hit["code"], **scope})["hits"]] == [request["id"]]

    assert _search(client, token, {"q": "fbdescq", **scope})["hits"] == []
    by_description = _search(client, token, {"q": "fbdescq", "fields": ["id", "title", "description"], **scope})
    assert [h["id"] for h in by_description["hits"]] == [request["id"]]
    assert by_description["hits"][0]["snippet"]["field_label"] == "Description"


def test_a_request_is_not_found_once_the_module_is_off(client, admin_token):
    org, project, token = setup(client, admin_token, "Search Feedback Off Co")
    create_request(client, token, project["id"], title="Vanishing offfbzq request")
    scope = {"scope": "project", "project_id": project["id"]}
    assert len(_search(client, token, {"q": "offfbzq", **scope})["hits"]) == 1
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/product_feedback", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert _search(client, token, {"q": "offfbzq", **scope})["hits"] == []


def test_an_inbox_request_is_found_at_organisation_level_only_while_the_inbox_is_on(client, admin_token):
    org, _, token = setup(client, admin_token, "Search Inbox Co")
    inbox = create_inbox_request(client, token, org["id"], title="Inbox inboxfbzq idea")
    scope = {"scope": "all", "organization_ids": [org["id"]]}
    hits = _search(client, token, {"q": "inboxfbzq", **scope})["hits"]
    assert [h["id"] for h in hits] == [inbox["id"]]
    set_org_inbox(client, token, org["id"], False)
    assert _search(client, token, {"q": "inboxfbzq", **scope})["hits"] == []
