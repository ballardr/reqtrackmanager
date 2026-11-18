"""Tests for the boundary coverage report (AR1): which connections cross an element's boundary and whether an inner
connection realises each. Every test builds its own organisation."""

from __future__ import annotations

from app.modules.architecture.tests._helpers import make_connection, make_element, project_base, setup
from tests.conftest import auth_headers


def _report(client, token, project_id, **params):
    resp = client.get(f"{project_base(project_id)}/reports/boundary-coverage", params={"format": "json", **params}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _sections(report) -> dict[str, list[list[str]]]:
    return {s["key"]: s["rows"] for s in report["sections"]}


def _scene(client, token, project_id):
    scope = make_element(client, token, project_id, "Telemetry")
    a = make_element(client, token, project_id, "Encoder", parent_id=scope["id"])
    outside = make_element(client, token, project_id, "Cloud")
    outer = make_connection(client, token, project_id, scope["id"], outside["id"])
    other = make_connection(client, token, project_id, outside["id"], a["id"])
    return scope, a, outside, outer, other


def test_every_crossing_connection_is_listed_and_uncovered_ones_are_flagged(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch report open")
    scope, _a, outside, outer, other = _scene(client, token, project["id"])
    report = _report(client, token, project["id"])
    rows = _sections(report)["outer"]
    by_code = {r[1]: r for r in rows}
    assert set(by_code) == {outer["unique_code"], other["unique_code"]}
    first = by_code[outer["unique_code"]]
    assert first[0].startswith(scope["unique_code"]) and first[4] == "Output" and first[5].startswith(outside["unique_code"])
    assert first[6] == "Not covered" and by_code[other["unique_code"]][4] == "Input"
    assert report["data"] == {"outer": 2, "covered": 0, "not_covered": 2}
    assert len(_sections(report)["not_covered"]) == 2


def test_a_realising_connection_covers_the_outer_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch report covered")
    scope, a, _outside, outer, other = _scene(client, token, project["id"])
    inner = make_connection(client, token, project["id"], a["id"], scope["id"])
    resp = client.put(
        f"{project_base(project['id'])}/connections/{inner['id']}/realisations",
        json={"version": inner["version"], "outer_connection_ids": [outer["id"]]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    report = _report(client, token, project["id"])
    row = {r[1]: r for r in _sections(report)["outer"]}[outer["unique_code"]]
    assert (row[6], row[7]) == ("Covered", inner["unique_code"])
    assert report["data"] == {"outer": 2, "covered": 1, "not_covered": 1}
    assert [r[1] for r in _sections(report)["not_covered"]] == [other["unique_code"]]


def test_the_element_parameter_limits_the_report_and_childless_elements_are_not_scopes(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch report scope")
    scope, _a, outside, outer, _other = _scene(client, token, project["id"])
    unrelated = make_element(client, token, project["id"], "Island")
    make_connection(client, token, project["id"], outside["id"], unrelated["id"])
    assert {r[0].split(" ")[0] for r in _sections(_report(client, token, project["id"]))["outer"]} == {scope["unique_code"]}
    limited = _sections(_report(client, token, project["id"], element=outside["unique_code"]))["outer"]
    assert {r[1] for r in limited} >= {outer["unique_code"]}
    by_name = _sections(_report(client, token, project["id"], element="telemetry"))["outer"]
    assert {r[0].split(" ")[0] for r in by_name} == {scope["unique_code"]}
