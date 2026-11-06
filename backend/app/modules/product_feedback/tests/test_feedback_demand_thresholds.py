"""Tests for a project's own thresholds on the derived Demand axis: what weighted demand reaches each level can differ
between projects while the level names and weights stay the organisation's. Set semantics (every level or none),
validation, nested-project inheritance, the effect on a request's derived level, and what happens when the
organisation adds or removes a level. Every test builds its own organisation."""

from __future__ import annotations

from collections.abc import Mapping

from app.modules.product_feedback.tests._helpers import (
    add_member,
    add_requester,
    create_persona,
    create_request,
    get_request,
    project_base,
    setup_with_people,
)
from tests.conftest import auth_headers, create_project

SCHEME = "enhancement_request"


def _url(project_id, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/scoring-schemes/{SCHEME}{tail}"


def _demand_axis(client, token, project_id) -> dict:
    resp = client.get(_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return next(a for a in resp.json()["axes"] if a["key"] == "demand")


def _set(client, token, project_id, thresholds, axis: str = "demand"):
    return client.put(_url(project_id, f"/axes/{axis}/thresholds"), json={"thresholds": thresholds}, headers=auth_headers(token))


def _by_name(axis: dict, values: Mapping[str, float]) -> dict[str, float]:
    ids = {lv["name"]: lv["id"] for lv in axis["levels"]}
    return {ids[name]: value for name, value in values.items()}


BIG_PRODUCT = {"Single voice": 0, "A few": 30, "Several": 60, "Many": 100, "Widespread": 200}


def _level_name(axis: dict, level_id: str) -> str:
    return next(lv["name"] for lv in axis["levels"] if lv["id"] == level_id)


def test_a_project_sets_its_own_demand_thresholds_and_the_organisation_values_stay_visible(client, admin_token):
    _, project, token = setup_with_people(client, admin_token, "Feedback Thresholds Co")
    before = _demand_axis(client, token, project["id"])
    assert before["thresholds_source"] == "organisation"
    assert [lv["threshold"] for lv in before["levels"]] == [0, 3, 8, 15, 30]

    resp = _set(client, token, project["id"], _by_name(before, BIG_PRODUCT))
    assert resp.status_code == 200, resp.text
    after = next(a for a in resp.json()["axes"] if a["key"] == "demand")
    assert after["thresholds_source"] == "project"
    assert [lv["threshold"] for lv in after["levels"]] == [0, 30, 60, 100, 200]
    assert [lv["org_threshold"] for lv in after["levels"]] == [0, 3, 8, 15, 30]  # still shown
    assert [lv["weight"] for lv in after["levels"]] == [lv["weight"] for lv in before["levels"]]  # weights untouched

    cleared = _set(client, token, project["id"], None)
    assert cleared.status_code == 200, cleared.text
    assert next(a for a in cleared.json()["axes"] if a["key"] == "demand")["thresholds_source"] == "organisation"


def test_the_override_changes_the_level_a_request_resolves_to_in_that_project_only(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Thresholds Effect Co")
    other = create_project(client, token, org["id"], "Other product")
    persona = create_persona(client, token, project["id"], "Heavy user", weight=20)
    request = create_request(client, token, project["id"])
    assert add_requester(client, token, org["id"], project["id"], request["id"], "persona", persona["id"]).status_code == 201

    axis = _demand_axis(client, token, project["id"])
    shown = get_request(client, token, project["id"], request["id"])
    assert _level_name(axis, shown["derived_levels"]["demand"]) == "Many"  # 20 reaches the organisation's 15

    assert _set(client, token, project["id"], _by_name(axis, BIG_PRODUCT)).status_code == 200
    shown = get_request(client, token, project["id"], request["id"])
    assert _level_name(axis, shown["derived_levels"]["demand"]) == "Single voice"  # 20 is below this project's 30
    listed = client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).json()
    assert listed[0]["derived_levels"]["demand"] == shown["derived_levels"]["demand"]

    # Another project of the organisation still reads the organisation's thresholds.
    assert _demand_axis(client, token, other["id"])["thresholds_source"] == "organisation"


def test_a_set_must_name_every_level_rise_with_the_weights_and_suit_a_derived_axis(client, admin_token):
    _, project, token = setup_with_people(client, admin_token, "Feedback Thresholds Bad Co")
    axis = _demand_axis(client, token, project["id"])
    ids = {lv["name"]: lv["id"] for lv in axis["levels"]}

    assert _set(client, token, project["id"], {ids["A few"]: 5}).status_code == 400  # not every level
    assert _set(client, token, project["id"], _by_name(axis, {**BIG_PRODUCT, "Single voice": -1})).status_code == 400
    assert _set(client, token, project["id"], _by_name(axis, {**BIG_PRODUCT, "Several": 30})).status_code == 400  # not rising
    assert _set(client, token, project["id"], _by_name(axis, {**BIG_PRODUCT, "Many": 50})).status_code == 400  # 60 then 50
    assert _set(client, token, project["id"], {}, axis="impact").status_code == 400  # an ordinary axis
    assert _set(client, token, project["id"], {}, axis="nope").status_code == 404
    assert _demand_axis(client, token, project["id"])["thresholds_source"] == "organisation"  # none of those was stored


def test_a_child_project_inherits_the_nearest_set_and_its_own_wins(client, admin_token):
    org, _, token = setup_with_people(client, admin_token, "Feedback Thresholds Nest Co")
    parent = create_project(client, token, org["id"], "Parent product", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child product", parent_project_id=parent["id"])
    axis = _demand_axis(client, token, parent["id"])

    assert _set(client, token, parent["id"], _by_name(axis, BIG_PRODUCT)).status_code == 200
    inherited = _demand_axis(client, token, child["id"])
    assert inherited["thresholds_source"] == "ancestor" and [lv["threshold"] for lv in inherited["levels"]] == [0, 30, 60, 100, 200]

    own = {"Single voice": 0, "A few": 1, "Several": 2, "Many": 3, "Widespread": 4}
    assert _set(client, token, child["id"], _by_name(axis, own)).status_code == 200
    mine = _demand_axis(client, token, child["id"])
    assert mine["thresholds_source"] == "project" and [lv["threshold"] for lv in mine["levels"]] == [0, 1, 2, 3, 4]

    assert _set(client, token, child["id"], None).status_code == 200
    assert _demand_axis(client, token, child["id"])["thresholds_source"] == "ancestor"


def test_adding_or_deleting_an_organisation_level_drops_the_projects_sets(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Thresholds Level Co")
    axis = _demand_axis(client, token, project["id"])
    assert _set(client, token, project["id"], _by_name(axis, BIG_PRODUCT)).status_code == 200

    added = client.post(
        f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/axes/demand/levels",
        json={"name": "Everyone", "weight": 6, "threshold": 500}, headers=auth_headers(token),
    )
    assert added.status_code == 201, added.text
    axis = _demand_axis(client, token, project["id"])
    assert axis["thresholds_source"] == "organisation"  # the set no longer covers the axis

    assert _set(client, token, project["id"], _by_name(axis, {**BIG_PRODUCT, "Everyone": 500})).status_code == 200
    removed = client.delete(
        f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/levels/{added.json()['id']}", headers=auth_headers(token),
    )
    assert removed.status_code == 204, removed.text
    assert _demand_axis(client, token, project["id"])["thresholds_source"] == "organisation"


def test_only_someone_who_manages_the_project_may_set_thresholds(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Thresholds Access Co")
    axis = _demand_axis(client, token, project["id"])
    _, member = add_member(client, token, org["id"], project["id"], "member.thresholds@example.com")
    assert _set(client, member, project["id"], _by_name(axis, BIG_PRODUCT)).status_code == 403
    assert client.get(_url(project["id"]), headers=auth_headers(member)).status_code == 200  # reading is open
