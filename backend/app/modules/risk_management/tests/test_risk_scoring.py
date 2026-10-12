"""Tests for the Risk Management module's scoring: the registered `risk` scheme,
the derived inherent/residual rating (default model, three-axis model, missing
inputs, per-cell overrides that are not monotonic in the product), level
deletion with reassignment, and the `risk_type_admin` gate on org configuration.

The scoring core itself is covered by `tests/test_scoring_matrix.py`.
"""

from __future__ import annotations

from app.modules.risk_management.tests._helpers import (
    add_member,
    create_risk,
    grant_org_role,
    levels,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

SCHEME = "risk"


def _risk(client, token, project_id, lv, **named_levels) -> dict:
    """A risk with levels given by readable names, e.g. `inherent_likelihood="Rare"`."""
    body = {}
    for field, name in named_levels.items():
        _, axis = field.split("_", 1)
        body[f"{field}_level_id"] = lv[axis][name]
    return create_risk(client, token, project_id, **body)


def _rating(risk: dict, which: str = "inherent") -> dict | None:
    return risk[f"{which}_rating"]


def test_scheme_registration_and_seeded_defaults(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Scheme Co")
    resp = client.get(f"/api/v1/projects/{project['id']}/scoring-schemes/{SCHEME}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    scheme = resp.json()
    axes = {a["key"]: [lvl["name"] for lvl in a["levels"]] for a in scheme["axes"]}
    assert axes["likelihood"] == ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"]
    assert axes["consequence"] == ["Insignificant", "Minor", "Moderate", "Major", "Catastrophic"]
    assert axes["detectability"][0] == "Detected immediately" and axes["detectability"][-1] == "Undetectable"
    assert [m["key"] for m in scheme["models"]] == ["lxc", "lxcxd"] and scheme["default_model_key"] == "lxc"
    assert [b["label"] for b in scheme["models"][0]["bands"]] == ["Low", "Medium", "High", "Critical"]


def test_inherent_and_residual_ratings_follow_the_default_matrix(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Rating Co")
    lv = levels(client, token, project["id"])
    risk = _risk(
        client, token, project["id"], lv, inherent_likelihood="Almost certain", inherent_consequence="Catastrophic",
        residual_likelihood="Unlikely", residual_consequence="Minor",
    )
    assert _rating(risk)["label"] == "Critical" and _rating(risk)["normalised"] == 1.0 and _rating(risk)["raw"] == 25
    assert _rating(risk)["scoring_model_key"] == "lxc" and _rating(risk)["tone"] == "danger"
    assert _rating(risk, "residual")["label"] == "Low" and _rating(risk, "residual")["raw"] == 4

    expected = {("Possible", "Moderate"): "Medium", ("Likely", "Major"): "High", ("Almost certain", "Major"): "Critical"}
    for (likelihood, consequence), label in expected.items():
        scored = _risk(client, token, project["id"], lv, inherent_likelihood=likelihood, inherent_consequence=consequence)
        assert _rating(scored)["label"] == label, (likelihood, consequence)


def test_a_risk_missing_an_axis_is_not_scored_and_rating_updates_with_the_levels(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Unscored Co")
    h = auth_headers(token)
    lv = levels(client, token, project["id"])
    risk = _risk(client, token, project["id"], lv, inherent_likelihood="Likely")
    assert _rating(risk) is None and _rating(risk, "residual") is None
    url = f"{project_base(project['id'])}/risks/{risk['id']}"
    scored = client.put(url, json={"inherent_consequence_level_id": lv["consequence"]["Major"]}, headers=h).json()
    assert _rating(scored)["label"] == "High"
    cleared = client.put(url, json={"inherent_likelihood_level_id": None}, headers=h).json()
    assert _rating(cleared) is None
    listed = client.get(project_base(project["id"]) + "/risks", headers=h).json()
    assert [r["inherent_rating"] for r in listed] == [None]


def test_three_axis_model_needs_detectability(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Fmea Co")
    h = auth_headers(token)
    lv = levels(client, token, project["id"])
    risk = _risk(client, token, project["id"], lv, inherent_likelihood="Almost certain", inherent_consequence="Catastrophic")
    assert _rating(risk)["label"] == "Critical"

    resp = client.put(f"/api/v1/projects/{project['id']}/scoring-schemes/{SCHEME}/default-model", json={"model": "lxcxd"}, headers=h)
    assert resp.status_code == 200, resp.text
    url = f"{project_base(project['id'])}/risks/{risk['id']}"
    assert _rating(client.get(url, headers=h).json()) is None  # no detectability yet
    scored = client.put(url, json={"inherent_detectability_level_id": lv["detectability"]["Undetectable"]}, headers=h).json()
    assert _rating(scored)["raw"] == 125 and _rating(scored)["label"] == "Critical" and _rating(scored)["scoring_model_key"] == "lxcxd"
    easy = client.put(url, json={"inherent_detectability_level_id": lv["detectability"]["Detected immediately"]}, headers=h).json()
    assert _rating(easy)["raw"] == 25 and _rating(easy)["label"] == "High"  # 25/125 = 0.2


def test_per_cell_override_makes_the_matrix_non_monotonic(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Cell Co")
    h = auth_headers(token)
    lv = levels(client, token, project["id"])
    rare_catastrophic = dict(inherent_likelihood="Rare", inherent_consequence="Catastrophic")
    # 1 x 5 = 5 of 25 = 0.2: "Medium" by threshold, while 2 x 3 = 6 is also Medium.
    risk = _risk(client, token, project["id"], lv, **rare_catastrophic)
    other = _risk(client, token, project["id"], lv, inherent_likelihood="Unlikely", inherent_consequence="Major")
    assert _rating(risk)["label"] == "Medium" and _rating(other)["label"] == "Medium"

    resp = client.put(
        f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/models/lxc/cell-ratings",
        json={"cells": [{"first_level_id": lv["likelihood"]["Rare"], "second_level_id": lv["consequence"]["Catastrophic"], "band_label": "High"}]},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    listed = {r["id"]: r for r in client.get(project_base(project["id"]) + "/risks", headers=h).json()}
    assert listed[risk["id"]]["inherent_rating"]["label"] == "High"
    assert listed[risk["id"]]["inherent_rating"]["normalised"] == 0.2  # only the label changes, never the score
    assert listed[other["id"]]["inherent_rating"]["label"] == "Medium"  # every other cell keeps its threshold band


def test_deleting_an_in_use_level_needs_a_reassignment(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Level Delete Co")
    h = auth_headers(token)
    lv = levels(client, token, project["id"])
    risk = _risk(client, token, project["id"], lv, inherent_likelihood="Rare", residual_likelihood="Rare")
    base = f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/levels/{lv['likelihood']['Rare']}"
    assert client.delete(base, headers=h).status_code == 409
    moved = client.delete(base, params={"reassign_to_id": lv["likelihood"]["Unlikely"]}, headers=h)
    assert moved.status_code == 204, moved.text
    after = client.get(f"{project_base(project['id'])}/risks/{risk['id']}", headers=h).json()
    assert after["inherent_likelihood_level_id"] == lv["likelihood"]["Unlikely"]
    assert after["residual_likelihood_level_id"] == lv["likelihood"]["Unlikely"]
    unused = lv["likelihood"]["Almost certain"]
    assert client.delete(f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/levels/{unused}", headers=h).status_code == 204


def test_only_a_type_admin_configures_the_org_scheme(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Scoring Admin Co")
    user_id, member = add_member(client, token, org["id"], project["id"], "member@risk-scoring.example.com")
    url = f"/api/v1/orgs/{org['id']}/scoring-schemes/{SCHEME}/default-model"
    assert client.put(url, json={"model": "lxcxd"}, headers=auth_headers(member)).status_code == 403
    grant_org_role(client, token, org["id"], user_id, "risk_type_admin")
    assert client.put(url, json={"model": "lxcxd"}, headers=auth_headers(member)).status_code == 200


def test_scheme_is_hidden_when_the_module_is_disabled_and_across_orgs(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Risk Scheme Off Co")
    project = create_project(client, token, org["id"], "Risk Scheme Off Project")
    assert client.get(f"/api/v1/projects/{project['id']}/scoring-schemes/{SCHEME}", headers=auth_headers(token)).status_code == 404

    _, project_a, token_a = setup(client, admin_token, "Risk Scheme Iso A Co")
    _, _, token_b = setup(client, admin_token, "Risk Scheme Iso B Co")
    # Core project endpoints answer a non-member with 403 (or 404); either way, never the configuration.
    assert client.get(f"/api/v1/projects/{project_a['id']}/scoring-schemes/{SCHEME}", headers=auth_headers(token_b)).status_code in (403, 404)
    assert client.get(f"/api/v1/projects/{project_a['id']}/scoring-schemes/{SCHEME}", headers=auth_headers(token_a)).status_code == 200
