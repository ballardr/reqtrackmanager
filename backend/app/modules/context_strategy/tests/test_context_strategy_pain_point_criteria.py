"""Tests for Pain Point scoring beyond Severity, Frequency and Confidence: the General row with per-persona
overrides, criteria scored per persona or for the whole Pain Point, the Cost of Delay and WSJF models (a weighted
sum that divides), organisation and project criteria (hiding, custom axes, a custom model) and their travel in a
project bundle. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.modules.context_strategy.models import PainPointScore
from app.modules.context_strategy.pain_point_scores import score_level_ids
from app.modules.context_strategy.tests.test_context_strategy_export_import import _export, _import
from app.modules.context_strategy.tests.test_context_strategy_pain_point_scoring import (
    _entry,
    _get,
    _levels,
    _pain_point,
    _persona,
    _put,
    _setup,
)
from tests.conftest import auth_headers

SCHEME = "pain_point"


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


def test_the_built_in_criteria_say_which_are_scored_per_persona(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Criteria Scope Co")
    scheme = _call(client, token, "get", _project_url(project["id"])).json()
    per_persona = {a["key"] for a in scheme["axes"] if a["per_target"]}
    assert per_persona == {"severity", "frequency", "confidence", "value"}
    assert scheme["target_label"] == "persona" and scheme["allow_custom_criteria"] is True
    assert {"cod", "wsjf"} <= {m["key"] for m in scheme["models"]}


def test_a_persona_row_overrides_per_persona_criteria_over_general(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Criteria Override Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    tech = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)

    resp = _put(client, token, pid, pp["id"], [
        _entry(levels, None, severity="Minor", frequency="Frequent", confidence="High"),
        _entry(levels, tech, severity="Major"),
    ], model_key="sxfxc")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    entries = {e["status"]: e for e in body["entries"]}
    # General: 2 x 3 x 1 = 6. Tech takes General's frequency and confidence: 4 x 3 x 1 = 12 (of a possible 20).
    assert entries["general"]["score"]["raw"] == 6 and entries["active"]["score"]["raw"] == 12
    assert entries["active"]["levels"] == {"severity": levels["severity"]["Major"]}
    assert entries["active"]["effective_levels"] == {
        "severity": levels["severity"]["Major"], "frequency": levels["frequency"]["Frequent"],
        "confidence": levels["confidence"]["High"],
    }
    # The persona rows are what counts once there are any; General alone is the score otherwise.
    assert body["scope"] == "per_persona" and body["counted"] == 1 and body["score"]["raw"] == 12
    only_general = _put(client, token, pid, pp["id"], [_entry(levels, None, severity="Minor", frequency="Frequent", confidence="High")])
    assert only_general.json()["scope"] == "general" and only_general.json()["score"]["raw"] == 6


def test_a_whole_pain_point_criterion_is_refused_on_a_persona_row(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Criteria Whole Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    tech = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)

    refused = _put(client, token, pid, pp["id"], [_entry(levels, tech, job_size="Small")])
    assert refused.status_code == 400 and "whole Pain Point" in refused.json()["detail"]
    assert _put(client, token, pid, pp["id"], [_entry(levels, None, job_size="Small")]).status_code == 200
    # A per-persona criterion is accepted on a persona row.
    assert _put(client, token, pid, pp["id"], [_entry(levels, tech, value="High")]).status_code == 200


def test_cost_of_delay_and_wsjf_score_a_weighted_sum_over_job_size(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Criteria WSJF Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    entry = _entry(levels, None, value="High", time_criticality="Moderate", risk_reduction="Low", job_size="Small")
    assert _put(client, token, pid, pp["id"], [entry]).status_code == 200

    # Relative scale 1, 2, 3, 5, 8, 13, 20: High = 8, Moderate = 3, Low = 2, Small = 2.
    cod = _get(client, token, pid, pp["id"], model_key="cod")["score"]
    assert cod["normalised"] == pytest.approx((8 + 3 + 2) / 3 / 20, rel=1e-3)
    wsjf = _get(client, token, pid, pp["id"], model_key="wsjf")["score"]
    assert wsjf["normalised"] == pytest.approx((8 + 3 + 2) / 3 / 20 / 2, rel=1e-3)
    assert wsjf["normalised"] < cod["normalised"]
    # No job size: WSJF is not scored, Cost of Delay still is.
    no_size = _entry(levels, None, value="High", time_criticality="Moderate", risk_reduction="Low")
    assert _put(client, token, pid, pp["id"], [no_size]).status_code == 200
    assert _get(client, token, pid, pp["id"], model_key="wsjf")["score"] is None
    assert _get(client, token, pid, pp["id"], model_key="cod")["score"] is not None


def test_a_hidden_criterion_is_not_offered_and_keeps_its_stored_level(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Criteria Hide Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    assert _put(client, token, pid, pp["id"], [
        _entry(levels, None, severity="Minor", frequency="Rare", confidence="High"),
    ]).status_code == 200

    hidden = _call(client, token, "post", _org_url(org["id"], "/hidden-criteria"), json={"kind": "axis", "key": "confidence"}).json()
    assert "confidence" not in {a["key"] for a in hidden["axes"]}
    refused = _put(client, token, pid, pp["id"], [_entry(levels, None, severity="Minor", confidence="High")])
    assert refused.status_code == 400
    assert _put(client, token, pid, pp["id"], [_entry(levels, None, severity="Major", frequency="Rare")]).status_code == 200

    db = SessionLocal()
    try:
        row = db.scalars(select(PainPointScore).where(PainPointScore.pain_point_id == uuid.UUID(pp["id"]))).one()
        assert set(score_level_ids(row)) == {"severity", "frequency", "confidence"}  # the hidden level is kept
    finally:
        db.close()
    _call(client, token, "delete", _org_url(org["id"], "/hidden-criteria"), params={"kind": "axis", "key": "confidence"})
    assert _get(client, token, pid, pp["id"], model_key="sxfxc")["score"] is not None


def test_a_custom_axis_chooses_per_persona_or_whole_and_scores_in_a_custom_model(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Criteria Custom Co")
    pid = project["id"]
    spec = [{"name": "Low", "weight": 1}, {"name": "High", "weight": 4}]
    _call(client, token, "post", _org_url(org["id"], "/axes"), json={"label": "Revenue risk", "levels": spec, "per_target": True})
    scheme = _call(client, token, "post", _org_url(org["id"], "/axes"), json={"label": "Legal exposure", "levels": spec}).json()
    assert _axis(scheme, "c_revenue_risk")["per_target"] is True and _axis(scheme, "c_legal_exposure")["per_target"] is False
    # A weighted sum can divide by an axis, as WSJF does.
    scheme = _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Exposure per effort", "combination": "weighted_sum", "axes": [
            {"axis_key": "c_revenue_risk", "role": "sum", "importance": 50},
            {"axis_key": "c_legal_exposure", "role": "sum", "importance": 50},
            {"axis_key": "job_size", "role": "divide"},
        ],
    }).json()
    model = next(m for m in scheme["models"] if m["key"] == "m_exposure_per_effort")
    assert model["divisor_axis_keys"] == ["job_size"] and model["combination"] == "weighted_sum"

    levels = _levels(client, token, pid)
    tech = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)
    assert _put(client, token, pid, pp["id"], [_entry(levels, tech, c_revenue_risk="High")]).status_code == 200
    refused = _put(client, token, pid, pp["id"], [_entry(levels, tech, c_legal_exposure="High")])
    assert refused.status_code == 400 and "General row" in refused.json()["detail"]
    resp = _put(client, token, pid, pp["id"], [
        _entry(levels, None, c_revenue_risk="Low", c_legal_exposure="High", job_size="Tiny"),
        _entry(levels, tech, c_revenue_risk="High"),
    ], model_key="m_exposure_per_effort")
    assert resp.status_code == 200, resp.text
    # Tech: revenue High (4 of 4) and legal High (4 of 4) = 100, over job size Tiny (1, the lowest): normalised 1.
    assert resp.json()["score"]["normalised"] == pytest.approx(1.0)


def test_a_scheme_without_targets_refuses_a_per_persona_axis(client, admin_token):
    from app.modules.product_feedback.tests._helpers import setup as feedback_setup

    org, _, token = feedback_setup(client, admin_token, "PP Criteria No Target Co")
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/scoring-schemes/enhancement_request/axes", headers=auth_headers(token),
        json={"label": "Per team", "per_target": True, "levels": [{"name": "Low", "weight": 1}, {"name": "High", "weight": 2}]},
    )
    assert resp.status_code == 400 and "no targets" in resp.json()["detail"]


def test_custom_criteria_and_scores_travel_in_the_project_bundle(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Criteria Bundle Co")
    pid = project["id"]
    _call(client, token, "post", _project_url(pid, "/axes"), json={
        "label": "Brand harm", "per_target": True, "levels": [{"name": "Low", "weight": 1}, {"name": "High", "weight": 3}],
    })
    levels = _levels(client, token, pid)
    tech = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)
    assert _put(client, token, pid, pp["id"], [
        _entry(levels, None, severity="Minor", job_size="Small", c_brand_harm="Low"),
        _entry(levels, tech, severity="Major", c_brand_harm="High"),
    ]).status_code == 200

    bundle = _export(client, token, pid)
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    definitions = exported["pain_point_scoring_definitions"]
    assert [(a["label"], a["per_target"]) for a in definitions["axes"]] == [("Brand harm", True)]

    imported = _import(client, token, org["id"], bundle, "PP Criteria Restored")
    assert not [w for w in imported["warnings"] if "score" in w.lower()]
    new_id = imported["project"]["id"]
    scheme = _call(client, token, "get", _project_url(new_id)).json()
    axis = next(a for a in scheme["axes"] if a["label"] == "Brand harm" and a["owner_project_id"] == new_id)
    new_pp = next(
        p for p in _call(client, token, "get", f"/api/v1/projects/{new_id}/modules/context_strategy/pain-points").json()
        if p["title"] == pp["title"]
    )
    restored = _get(client, token, new_id, new_pp["id"], model_key="sxfxc")
    by_status = {e["status"]: e for e in restored["entries"]}
    assert set(by_status["general"]["levels"]) == {"severity", "job_size", axis["key"]}
    assert set(by_status["active"]["levels"]) == {"severity", axis["key"]}



# --- the report's scoring model is chosen from the models on offer --------------------------------------------


def _model_param(client, token, url: str) -> dict:
    """The first report in a catalogue that takes a scoring model, and its `model_key` parameter."""
    entries = _call(client, token, "get", url).json()
    return next(p for e in entries for p in e["params"] if p["name"] == "model_key")


def test_the_reports_scoring_model_is_a_list_of_the_models_the_project_offers(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Report Models Co")
    pid = project["id"]
    param = _model_param(client, token, f"/api/v1/projects/{pid}/report-catalogue")
    # Named models, not a key typed from memory: the built-in ones, with their names.
    assert {"sxf", "sxc", "sxfxc", "cod", "wsjf"} <= set(param["choices"])
    assert param["choice_labels"]["sxf"] == "Severity × Frequency"
    assert param["choice_labels"]["wsjf"] != "wsjf"

    # A model the organisation defines is offered in its projects and in the organisation's own list.
    spec = [{"name": "Low", "weight": 1}, {"name": "High", "weight": 4}]
    _call(client, token, "post", _org_url(org["id"], "/axes"), json={"label": "Revenue risk", "levels": spec})
    _call(client, token, "post", _org_url(org["id"], "/models"), json={
        "label": "Revenue first", "combination": "weighted_sum", "axes": [{"axis_key": "c_revenue_risk", "role": "sum", "importance": 100}],
    })
    in_project = _model_param(client, token, f"/api/v1/projects/{pid}/report-catalogue")
    assert in_project["choice_labels"]["m_revenue_first"] == "Revenue first"
    in_org = _model_param(client, token, f"/api/v1/orgs/{org['id']}/report-catalogue")
    assert "m_revenue_first" in in_org["choices"]
    # The report still runs with a chosen key, and an unknown one is still refused by the report, not by the list.
    ok = client.get(
        f"/api/v1/projects/{pid}/modules/context_strategy/reports/pain-point-prioritisation", params={"model_key": "sxf"},
        headers=auth_headers(token),
    )
    assert ok.status_code == 200, ok.text
    assert client.get(
        f"/api/v1/projects/{pid}/modules/context_strategy/reports/pain-point-prioritisation", params={"model_key": "nope"},
        headers=auth_headers(token),
    ).status_code == 400


def test_a_model_only_one_project_defines_is_offered_in_that_project_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Report Models Project Co")
    from tests.conftest import create_project

    other = create_project(client, token, org["id"], "PP Report Models Other")
    spec = [{"name": "Low", "weight": 1}, {"name": "High", "weight": 4}]
    _call(client, token, "post", _project_url(project["id"], "/axes"), json={"label": "Local risk", "levels": spec})
    _call(client, token, "post", _project_url(project["id"], "/models"), json={
        "label": "Local first", "combination": "weighted_sum", "axes": [{"axis_key": "c_local_risk", "role": "sum", "importance": 100}],
    })
    mine = _model_param(client, token, f"/api/v1/projects/{project['id']}/report-catalogue")
    theirs = _model_param(client, token, f"/api/v1/projects/{other['id']}/report-catalogue")
    assert "m_local_first" in mine["choices"] and "m_local_first" not in theirs["choices"]


def test_a_provider_that_fails_leaves_a_text_box_instead_of_breaking_the_catalogue(client, admin_token):
    from app.modules.context_strategy import reports

    _, project, token = _setup(client, admin_token, "PP Report Models Failure Co")

    def broken(db, organization_id, project_id):
        raise RuntimeError("boom")

    from dataclasses import replace

    from app.services import report_framework

    param = replace(reports._MODEL_KEY, choices_for=broken)
    out = report_framework.param_out(param, db=None, organization_id=None)
    assert out.choices is None  # no session means no provider call at all
    from app.database import SessionLocal

    with SessionLocal() as db:
        failed = report_framework.param_out(param, db, uuid.UUID(project["organization_id"]), uuid.UUID(project["id"]))
    assert failed.choices is None and failed.choice_labels is None and failed.name == "model_key"


def test_a_parameter_cannot_declare_both_fixed_choices_and_a_provider():
    from app.modules.registry import ReportParamDefinition, _report_param_problem

    both = ReportParamDefinition("m", "string", choices=("a",), choices_for=lambda db, org, project: [("a", "A")])
    assert _report_param_problem(both) is not None
    assert _report_param_problem(ReportParamDefinition("m", "integer", choices_for=lambda db, org, project: [])) is not None
    assert _report_param_problem(ReportParamDefinition("m", "string", choices_for=lambda db, org, project: [])) is None
