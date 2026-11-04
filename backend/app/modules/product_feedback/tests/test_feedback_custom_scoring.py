"""Tests for organisation- and project-defined scoring criteria on enhancement requests: custom axes and models
(a product with divisors and exponents, or a weighted sum), the additive project layer with nested-project
inheritance, hiding and restoring registered criteria, deleting with and without scores, the effective scheme in
validation, record tables and bundles. Every test builds its own organisation."""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.product_feedback.tests._helpers import (
    create_inbox_request,
    create_request,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project

SCHEME = "enhancement_request"


def _org_url(org_id, tail: str = "") -> str:
    return f"/api/v1/orgs/{org_id}/scoring-schemes/{SCHEME}{tail}"


def _project_url(project_id, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/scoring-schemes/{SCHEME}{tail}"


def _call(client, token, method: str, url: str, expect: int | tuple[int, ...] = (200, 201, 204), **kwargs):
    resp = getattr(client, method)(url, headers=auth_headers(token), **kwargs)
    ok = (expect,) if isinstance(expect, int) else expect
    assert resp.status_code in ok, f"{method.upper()} {url}: {resp.status_code} {resp.text}"
    return resp


def _axis(scheme: dict, key: str) -> dict:
    return next(a for a in scheme["axes"] if a["key"] == key)


def _model(scheme: dict, key: str) -> dict:
    return next(m for m in scheme["models"] if m["key"] == key)


def _ids(scheme: dict, axis_key: str) -> dict[str, str]:
    return {lv["name"]: lv["id"] for lv in _axis(scheme, axis_key)["levels"]}


FIT_LEVELS = [{"name": "Low", "weight": 1}, {"name": "Medium", "weight": 2}, {"name": "High", "weight": 4}]


def _fit_axis(client, token, url: str, label: str = "Strategic fit") -> dict:
    return _call(client, token, "post", url + "/axes", json={"label": label, "levels": FIT_LEVELS}).json()


def _sum_model(label: str = "Balanced", **overrides) -> dict:
    payload = {
        "label": label, "combination": "weighted_sum",
        "axes": [
            {"axis_key": "impact", "role": "sum", "importance": 60},
            {"axis_key": "c_strategic_fit", "role": "sum", "importance": 40},
        ],
    }
    return payload | overrides


def test_an_organisation_axis_scores_a_request_in_a_weighted_sum_model(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Sum Co")
    pid = project["id"]
    scheme = _fit_axis(client, token, _org_url(org["id"]))
    fit = _axis(scheme, "c_strategic_fit")
    assert fit["origin"] == "org" and fit["owner_project_id"] is None and [lv["name"] for lv in fit["levels"]] == ["Low", "Medium", "High"]
    scheme = _call(client, token, "post", _org_url(org["id"], "/models"), json=_sum_model()).json()
    balanced = _model(scheme, "m_balanced")
    assert balanced["combination"] == "weighted_sum" and balanced["importance"] == {"impact": 60, "c_strategic_fit": 40}
    assert balanced["origin"] == "org" and [b["label"] for b in balanced["bands"]] == ["Low", "Medium", "High"]

    impact, fit_ids = _ids(scheme, "impact"), _ids(scheme, "c_strategic_fit")
    request = create_request(client, token, pid, levels={"impact": impact["High"], "c_strategic_fit": fit_ids["Medium"]})
    # Impact High is 2 of a top 3, fit Medium is 2 of a top 4: 60 x 2/3 + 40 x 1/2 = 60 out of 100.
    score = request["scores"]["m_balanced"]
    assert score["raw"] == pytest.approx(60) and score["normalised"] == pytest.approx(0.6) and score["label"] == "Medium"
    assert request["levels"]["c_strategic_fit"] == fit_ids["Medium"]
    # The registered models still score; this request is unscored under RICE (no Reach).
    assert request["scores"]["rice"] is None


def test_a_weighted_sum_can_invert_an_axis_and_a_product_can_weight_one_with_an_exponent(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Maths Co")
    pid = project["id"]
    _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Cheap and valuable", "combination": "weighted_sum", "axes": [
            {"axis_key": "impact", "role": "sum", "importance": 50},
            {"axis_key": "effort", "role": "sum", "importance": 50, "lower_is_better": True},
        ],
    })
    scheme = _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Impact squared", "combination": "product", "axes": [
            {"axis_key": "impact", "role": "multiply", "exponent": 2}, {"axis_key": "confidence", "role": "multiply"},
            {"axis_key": "effort", "role": "divide"},
        ],
    }).json()
    squared = _model(scheme, "m_impact_squared")
    assert squared["exponents"] == {"impact": 2} and squared["divisor_axis_keys"] == ["effort"]
    levels = {a["key"]: _ids(scheme, a["key"]) for a in scheme["axes"]}
    request = create_request(client, token, pid, levels={
        "impact": levels["impact"]["High"], "confidence": levels["confidence"]["High"], "effort": levels["effort"]["Medium"],
    })
    cheap = request["scores"]["m_cheap_and_valuable"]
    # Impact High 2/3 scaled; Effort Medium (2) inverted is the lowest weight 0.5 / 2 = 0.25: 50 x 2/3 + 50 x 1/4.
    assert cheap["raw"] == pytest.approx(50 * 2 / 3 + 50 * 0.25)
    # (2^2 x 1 / 2) = 2 out of a best case of (3^2 x 1 / 0.5) = 18.
    squared = request["scores"]["m_impact_squared"]
    assert squared["raw"] == pytest.approx(2) and squared["normalised"] == pytest.approx(2 / 18)
    cheaper = create_request(client, token, pid, title="Cheaper", levels={
        "impact": levels["impact"]["High"], "effort": levels["effort"]["Trivial"]})
    assert cheaper["scores"]["m_cheap_and_valuable"]["raw"] > cheap["raw"]


@pytest.mark.parametrize("payload, message", [
    ({"label": "x", "combination": "weighted_sum", "axes": [{"axis_key": "impact", "role": "sum", "importance": 50}]}, "total 100"),
    ({"label": "x", "combination": "weighted_sum", "axes": [{"axis_key": "impact", "role": "multiply"}]}, "roles"),
    ({"label": "x", "combination": "product", "axes": [{"axis_key": "impact", "role": "divide"}]}, "multiplied"),
    ({"label": "x", "combination": "product", "axes": [{"axis_key": "nope", "role": "multiply"}]}, "nope"),
    ({"label": "x", "combination": "product", "axes": [
        {"axis_key": "impact", "role": "multiply"}, {"axis_key": "impact", "role": "divide"}]}, "once"),
    ({"label": "RICE (Reach × Impact × Confidence ÷ Effort)", "combination": "product", "axes": [
        {"axis_key": "impact", "role": "multiply"}]}, "already exists"),
])
def test_a_model_must_be_valid_and_use_visible_axes(client, admin_token, payload, message):
    org, _, token = setup(client, admin_token, "Custom Model Rules Co")
    resp = _call(client, token, "post", _org_url(org["id"], "/models"), expect=400, json=payload)
    assert message in resp.text


def test_an_axis_needs_two_unique_levels_and_a_new_name(client, admin_token):
    org, _, token = setup(client, admin_token, "Custom Axis Rules Co")
    url = _org_url(org["id"], "/axes")
    assert client.post(url, json={"label": "A", "levels": [{"name": "Only", "weight": 1}]}, headers=auth_headers(token)).status_code == 422
    same_weight = {"label": "A", "levels": [{"name": "X", "weight": 1}, {"name": "Y", "weight": 1}]}
    assert _call(client, token, "post", url, expect=400, json=same_weight)
    assert _call(client, token, "post", url, expect=400, json={"label": "impact", "levels": FIT_LEVELS})  # a registered axis's name
    _fit_axis(client, token, _org_url(org["id"]))
    assert _call(client, token, "post", url, expect=400, json={"label": "strategic FIT", "levels": FIT_LEVELS})
    again = _fit_axis(client, token, _org_url(org["id"]), "Strategic fit 2")
    assert {a["key"] for a in again["axes"]} >= {"c_strategic_fit", "c_strategic_fit_2"}


def test_a_project_adds_its_own_criteria_on_top_of_the_organisations_and_children_inherit_them(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Layer Co")
    parent = create_project(client, token, org["id"], "Layer Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Layer Child", parent_project_id=parent["id"])
    sibling = create_project(client, token, org["id"], "Layer Sibling")
    _fit_axis(client, token, _org_url(org["id"]), "Org fit")
    scheme = _call(client, token, "post", _project_url(parent["id"], "/axes"), json={
        "label": "Hardware risk", "levels": [{"name": "Low", "weight": 1}, {"name": "High", "weight": 3}],
    }).json()
    own = _axis(scheme, "c_hardware_risk")
    assert own["origin"] == "project" and own["owner_project_id"] == parent["id"]
    assert _axis(scheme, "c_org_fit")["origin"] == "org" and _axis(scheme, "impact")["origin"] == "built_in"  # additive
    model = _call(client, token, "post", _project_url(parent["id"], "/models"), json={
        "label": "Hardware view", "combination": "product", "axes": [
            {"axis_key": "impact", "role": "multiply"}, {"axis_key": "c_hardware_risk", "role": "divide"}],
    }).json()
    assert _model(model, "m_hardware_view")["origin"] == "project"

    def keys(project_id):
        config = _call(client, token, "get", _project_url(project_id)).json()
        return {a["key"] for a in config["axes"]}, {m["key"] for m in config["models"]}

    assert "c_hardware_risk" in keys(child["id"])[0] and "m_hardware_view" in keys(child["id"])[1]  # inherited down
    assert "c_hardware_risk" not in keys(sibling["id"])[0] and "c_org_fit" in keys(sibling["id"])[0]
    org_config = _call(client, token, "get", _org_url(org["id"])).json()
    assert "c_hardware_risk" not in {a["key"] for a in org_config["axes"]}  # the organisation never sees a project's own

    # A level of a project's axis belongs to that tier alone.
    level_id = own["levels"][0]["id"]
    assert _call(client, token, "patch", _org_url(org["id"], f"/levels/{level_id}"), expect=403, json={"name": "Tiny"})
    assert _call(client, token, "patch", _project_url(parent["id"], f"/levels/{level_id}"), json={"name": "Tiny"}).json()["name"] == "Tiny"
    registered_level = _axis(org_config, "impact")["levels"][0]["id"]
    assert _call(client, token, "patch", _project_url(parent["id"], f"/levels/{registered_level}"), expect=403, json={"name": "Tiny"})
    added = _call(client, token, "post", _project_url(parent["id"], "/axes/c_hardware_risk/levels"), json={"name": "Medium", "weight": 2})
    assert added.json()["name"] == "Medium"
    assert _call(client, token, "post", _project_url(sibling["id"], "/axes/c_hardware_risk/levels"), expect=403, json={"name": "M", "weight": 2})


def test_a_request_can_only_use_axes_its_project_can_see(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Visible Co")
    other = create_project(client, token, org["id"], "Custom Visible Other")
    scheme = _call(client, token, "post", _project_url(project["id"], "/axes"), json={
        "label": "Local axis", "levels": [{"name": "Low", "weight": 1}, {"name": "High", "weight": 3}],
    }).json()
    level = _ids(scheme, "c_local_axis")["High"]
    request = create_request(client, token, project["id"], levels={"c_local_axis": level})
    assert request["levels"] == {"c_local_axis": level}
    body = {"title": "x", "levels": {"c_local_axis": level}}
    assert _call(client, token, "post", project_base(other["id"]) + "/requests", expect=400, json=body)
    assert _call(client, token, "post", org_base(org["id"]) + "/requests", expect=400, json=body)


def test_hiding_a_registered_axis_drops_the_models_that_need_it_for_that_project_only(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Hide Co")
    other = create_project(client, token, org["id"], "Custom Hide Other")
    pid = project["id"]
    request = create_request(client, token, pid)
    assert "ice" in request["scores"]
    hidden = _call(client, token, "post", _project_url(pid, "/hidden-criteria"), json={"kind": "axis", "key": "ease"}).json()
    assert "ease" not in {a["key"] for a in hidden["axes"]} and "ice" not in {m["key"] for m in hidden["models"]}
    assert hidden["hidden_criteria"] == [{"kind": "axis", "key": "ease", "label": "Ease"}]
    shown = _call(client, token, "get", project_base(pid) + f"/requests/{request['id']}").json()
    assert "ice" not in shown["scores"] and "rice" in shown["scores"]
    scheme = _call(client, token, "get", _project_url(other["id"])).json()
    assert "ease" in {a["key"] for a in scheme["axes"]}  # another project still sees it
    levels = {a["key"]: _ids(scheme, a["key"]) for a in scheme["axes"]}
    assert _call(client, token, "put", project_base(pid) + f"/requests/{request['id']}", expect=400,
                 json={"levels": {"ease": levels["ease"]["Easy"]}})
    restored = _call(client, token, "delete", _project_url(pid, "/hidden-criteria"), params={"kind": "axis", "key": "ease"}).json()
    assert "ice" in {m["key"] for m in restored["models"]} and restored["hidden_criteria"] == []


def test_hiding_a_model_and_the_organisations_own_hiding(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Org Hide Co")
    pid = project["id"]
    _call(client, token, "post", _org_url(org["id"], "/hidden-criteria"), json={"kind": "model", "key": "rice_demand"})
    config = _call(client, token, "get", _project_url(pid)).json()
    assert "rice_demand" not in {m["key"] for m in config["models"]}
    # A project cannot restore what the organisation hid, and the organisation sees what it hid.
    assert _call(client, token, "get", _org_url(org["id"])).json()["hidden_criteria"][0]["key"] == "rice_demand"
    _call(client, token, "post", _org_url(org["id"], "/hidden-criteria"), json={"kind": "model", "key": "ice"})
    # The default model (RICE) cannot be hidden if it is the last one standing.
    _call(client, token, "post", _project_url(pid, "/hidden-criteria"), json={"kind": "model", "key": "rice"}, expect=409)
    _call(client, token, "delete", _org_url(org["id"], "/hidden-criteria"), params={"kind": "model", "key": "rice_demand"})
    assert "rice_demand" in {m["key"] for m in _call(client, token, "get", _org_url(org["id"])).json()["models"]}
    # Hiding the default model moves the default to the next model.
    hidden = _call(client, token, "post", _project_url(pid, "/hidden-criteria"), json={"kind": "model", "key": "rice"}).json()
    assert hidden["default_model_key"] == "rice_demand"
    # A criterion a tier defined is deleted, not hidden.
    _fit_axis(client, token, _org_url(org["id"]))
    _call(client, token, "post", _org_url(org["id"], "/hidden-criteria"), expect=400, json={"kind": "axis", "key": "c_strategic_fit"})
    _call(client, token, "post", _project_url(pid, "/hidden-criteria"), json={"kind": "axis", "key": "c_strategic_fit"})  # inherited: hideable


def test_deleting_an_axis_needs_it_unused_by_models_and_scores_or_an_explicit_clear(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Delete Co")
    pid = project["id"]
    scheme = _fit_axis(client, token, _org_url(org["id"]))
    _call(client, token, "post", _org_url(org["id"], "/models"), json=_sum_model())
    blocked = _call(client, token, "delete", _org_url(org["id"], "/axes/c_strategic_fit"), expect=409)
    assert "Balanced" in blocked.text
    _call(client, token, "delete", _org_url(org["id"], "/models/m_balanced"))
    request = create_request(client, token, pid, levels={"c_strategic_fit": _ids(scheme, "c_strategic_fit")["High"]})
    in_use = _call(client, token, "delete", _org_url(org["id"], "/axes/c_strategic_fit"), expect=409)
    assert "clear_scores" in in_use.text
    after = _call(client, token, "delete", _org_url(org["id"], "/axes/c_strategic_fit"), params={"clear_scores": "true"}).json()
    assert "c_strategic_fit" not in {a["key"] for a in after["axes"]}
    shown = _call(client, token, "get", project_base(pid) + f"/requests/{request['id']}").json()
    assert "c_strategic_fit" not in shown["levels"]
    # A registered axis is never deleted, and an unknown one is not found.
    _call(client, token, "delete", _org_url(org["id"], "/axes/impact"), expect=404)


def test_deleting_a_model_removes_its_bands_default_and_enabled_rows(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Delete Model Co")
    pid = project["id"]
    _fit_axis(client, token, _org_url(org["id"]))
    _call(client, token, "post", _org_url(org["id"], "/models"), json=_sum_model())
    _call(client, token, "put", _org_url(org["id"], "/default-model"), json={"model": "m_balanced"})
    _call(client, token, "put", _org_url(org["id"], "/enabled-models"), json={"models": ["m_balanced", "rice"]})
    _call(client, token, "put", _org_url(org["id"], "/models/m_balanced/bands"), json={"bands": [
        {"label": "Weak", "min_score": 0, "tone": "muted"}, {"label": "Strong", "min_score": 0.5, "tone": "accent"}]})
    after = _call(client, token, "delete", _org_url(org["id"], "/models/m_balanced")).json()
    assert after["default_model_key"] == "rice" and after["enabled_model_keys"] == ["rice"]
    assert "m_balanced" not in {m["key"] for m in after["models"]}
    assert "m_balanced" not in create_request(client, token, pid)["scores"]


def test_changing_a_models_axes_rescores_requests_and_drops_its_cell_ratings(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Edit Model Co")
    pid = project["id"]
    scheme = _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Simple", "combination": "product", "axes": [
            {"axis_key": "impact", "role": "multiply"}, {"axis_key": "confidence", "role": "multiply"}],
    }).json()
    levels = {a["key"]: _ids(scheme, a["key"]) for a in scheme["axes"]}
    request = create_request(client, token, pid, levels={"impact": levels["impact"]["High"], "confidence": levels["confidence"]["High"]})
    assert request["scores"]["m_simple"]["raw"] == 2
    cells = [{"first_level_id": levels["impact"]["High"], "second_level_id": levels["confidence"]["High"], "band_label": "High"}]
    _call(client, token, "put", _org_url(org["id"], "/models/m_simple/cell-ratings"), json={"cells": cells})
    updated = _call(client, token, "patch", _org_url(org["id"], "/models/m_simple"), json={
        "label": "Simple squared", "axes": [
            {"axis_key": "impact", "role": "multiply", "exponent": 2}, {"axis_key": "confidence", "role": "multiply"}],
    }).json()
    simple = _model(updated, "m_simple")
    assert simple["label"] == "Simple squared" and simple["exponents"] == {"impact": 2} and simple["cell_ratings"] == []
    shown = _call(client, token, "get", project_base(pid) + f"/requests/{request['id']}").json()
    assert shown["scores"]["m_simple"]["raw"] == 4
    assert simple["key"] == "m_simple"  # the key is stable across a rename


def test_the_inbox_scores_on_the_organisations_models_only(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Inbox Co")
    _call(client, token, "post", _project_url(project["id"], "/models"), json={
        "label": "Project only", "combination": "product", "axes": [{"axis_key": "impact", "role": "multiply"}],
    })
    _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Org wide", "combination": "product", "axes": [{"axis_key": "impact", "role": "multiply"}],
    })
    inbox = create_inbox_request(client, token, org["id"])
    assert "m_org_wide" in inbox["scores"] and "m_project_only" not in inbox["scores"]
    in_project = create_request(client, token, project["id"])
    assert {"m_org_wide", "m_project_only"} <= set(in_project["scores"])


def test_only_a_scheme_admin_may_define_criteria(client, admin_token):
    from app.modules.product_feedback.tests._helpers import add_member

    org, project, token = setup(client, admin_token, "Custom Gate Co")
    _, member = add_member(client, token, org["id"], project["id"], "custom_gate_member@example.com")
    body = {"label": "Nope", "levels": FIT_LEVELS}
    _call(client, member, "post", _org_url(org["id"], "/axes"), expect=403, json=body)
    _call(client, member, "post", _project_url(project["id"], "/axes"), expect=403, json=body)
    _call(client, member, "post", _org_url(org["id"], "/hidden-criteria"), expect=403, json={"kind": "axis", "key": "ease"})
    assert _call(client, member, "get", _project_url(project["id"])).json()["allow_custom_criteria"] is True


def _rows(response) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response.text)))


def test_a_custom_axis_is_an_export_and_import_column(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Table Co")
    pid = project["id"]
    _fit_axis(client, token, _project_url(pid))
    request = create_request(client, token, pid)
    export = f"/api/v1/projects/{pid}/records/enhancement_request/export"
    assert _rows(_call(client, token, "get", export))[0]["c_strategic_fit"] == ""
    text = "code,c_strategic_fit\n" + f"{request['unique_code']},High\n"
    applied = _call(client, token, "post", f"/api/v1/projects/{pid}/records/enhancement_request/import",
                    params={"dry_run": "false"}, files={"file": ("requests.csv", text.encode(), "text/csv")})
    assert applied.status_code == 200, applied.text
    assert _rows(_call(client, token, "get", export))[0]["c_strategic_fit"] == "High"


def test_the_unscored_filter_follows_a_custom_models_axes(client, admin_token):
    org, project, token = setup(client, admin_token, "Custom Filter Co")
    pid = project["id"]
    scheme = _fit_axis(client, token, _org_url(org["id"]))
    _call(client, token, "post", _org_url(org["id"], "/models"), json=_sum_model())
    fit = _ids(scheme, "c_strategic_fit")
    create_request(client, token, pid, title="Scored", levels={"impact": _ids(scheme, "impact")["High"], "c_strategic_fit": fit["High"]})
    create_request(client, token, pid, title="Unscored", levels={"impact": _ids(scheme, "impact")["High"]})
    listed = _call(client, token, "get", project_base(pid) + "/requests", params={"scored": "unscored", "scoring_model": "m_balanced"}).json()
    assert [r["title"] for r in listed] == ["Unscored"]
    missing = _call(client, token, "get", project_base(pid) + "/requests", params={"missing_axis": "c_strategic_fit"}).json()
    assert [r["title"] for r in missing] == ["Unscored"]


def test_custom_criteria_travel_in_the_project_bundle(client, admin_token):
    import io as _io
    import json
    import zipfile

    from app.modules.product_feedback.tests.test_feedback_export_import import _export, _import_project

    org, project, token = setup(client, admin_token, "Custom Bundle Co")
    pid = project["id"]
    scheme = _call(client, token, "post", _project_url(pid, "/axes"), json={
        "label": "Hardware risk", "levels": [{"name": "Low", "weight": 1}, {"name": "High", "weight": 3}],
    }).json()
    _call(client, token, "post", _project_url(pid, "/models"), json={
        "label": "Hardware view", "combination": "weighted_sum", "axes": [
            {"axis_key": "impact", "role": "sum", "importance": 70},
            {"axis_key": "c_hardware_risk", "role": "sum", "importance": 30, "lower_is_better": True}],
    })
    _call(client, token, "post", _project_url(pid, "/hidden-criteria"), json={"kind": "axis", "key": "ease"})
    create_request(client, token, pid, title="Scored", levels={
        "impact": _ids(scheme, "impact")["High"], "c_hardware_risk": _ids(scheme, "c_hardware_risk")["High"]})
    bundle = _export(client, token, f"/api/v1/projects/{pid}/export")
    with zipfile.ZipFile(_io.BytesIO(bundle)) as archive:
        document = json.loads(archive.read("project.json"))
    definitions = next(iter(v for k, v in _walk(document) if k == "scoring_definitions"))
    assert [a["label"] for a in definitions["axes"]] == ["Hardware risk"] and definitions["hidden"] == [{"kind": "axis", "key": "ease"}]

    imported = _import_project(client, token, org["id"], bundle, "Restored Custom")
    config = _call(client, token, "get", _project_url(imported["id"])).json()
    # The organisation already has an axis and a model with these keys (the original project's), so the copy's
    # get fresh keys and the imported requests are pointed at them.
    axis = next(a for a in config["axes"] if a["label"] == "Hardware risk" and a["owner_project_id"] == imported["id"])
    model = next(m for m in config["models"] if m["label"] == "Hardware view" and m["owner_project_id"] == imported["id"])
    assert axis["key"] != "c_hardware_risk" and model["importance"] == {"impact": 70, axis["key"]: 30}
    assert "ease" not in {a["key"] for a in config["axes"]}
    copy = _call(client, token, "get", project_base(imported["id"]) + "/requests").json()[0]
    assert copy["levels"][axis["key"]] == {lv["name"]: lv["id"] for lv in axis["levels"]}["High"]
    assert copy["scores"][model["key"]]["raw"] == pytest.approx(70 * 2 / 3 + 30 * 1 / 3)


def _walk(node):
    """Every `(key, value)` pair of a nested JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)
