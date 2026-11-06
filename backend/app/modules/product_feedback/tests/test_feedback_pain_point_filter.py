"""Tests for the request list's Pain Points filter: `pain_points=none|some` keeps requests that address no Pain Point,
or at least one (a merged duplicate's links count, as on the row), on the list endpoint and the record-table export,
and refuses an unknown value. Every test builds its own organisation."""

from __future__ import annotations

import csv
import io

from app.modules.product_feedback.tests._helpers import (
    add_link,
    create_pain_point,
    create_request,
    enable_other_module,
    project_base,
    setup,
)
from tests.conftest import auth_headers


def _titles(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return sorted(r["title"] for r in resp.json())


def test_the_filter_keeps_requests_with_or_without_a_pain_point(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Pain Filter Co")
    enable_other_module(client, token, org["id"], "context_strategy")
    pid = project["id"]
    linked = create_request(client, token, pid, title="Linked")
    create_request(client, token, pid, title="Bare")
    pain_point = create_pain_point(client, token, pid)
    assert add_link(client, token, org["id"], pid, linked["id"], "Addresses", "pain_point", pain_point["id"]).status_code == 201

    url = project_base(pid) + "/requests"
    h = auth_headers(token)
    assert _titles(client.get(url, params={"pain_points": "none"}, headers=h)) == ["Bare"]
    assert _titles(client.get(url, params={"pain_points": "some"}, headers=h)) == ["Linked"]
    assert _titles(client.get(url, headers=h)) == ["Bare", "Linked"]
    assert client.get(url, params={"pain_points": "maybe"}, headers=h).status_code == 422


def test_the_export_takes_the_same_filter(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Pain Export Co")
    enable_other_module(client, token, org["id"], "context_strategy")
    pid = project["id"]
    linked = create_request(client, token, pid, title="Linked")
    create_request(client, token, pid, title="Bare")
    pain_point = create_pain_point(client, token, pid)
    assert add_link(client, token, org["id"], pid, linked["id"], "Addresses", "pain_point", pain_point["id"]).status_code == 201

    export = f"/api/v1/projects/{pid}/records/enhancement_request/export"
    resp = client.get(export, params={"format": "csv", "pain_points": "none"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert [r["title"] for r in rows] == ["Bare"]
    bad = client.get(export, params={"format": "csv", "pain_points": "maybe"}, headers=auth_headers(token))
    assert bad.status_code == 422
