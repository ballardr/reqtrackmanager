"""Tests for Product Feedback scoring: the `enhancement_request` scheme (Reach, Impact, Confidence, Ease, Effort,
derived Demand), per-axis level storage and validation, the ICE, RICE and demand-based RICE scores derived on read
(Effort as a divisor), several models at once, the derived demand axis and its override, enabled models per tier, the
unscored filter, project and organisation tiers and level reassignment on delete. Every test builds its own
organisation."""

from __future__ import annotations

import pytest

from app.modules.product_feedback.tests._helpers import (
    add_requester,
    create_inbox_request,
    create_persona,
    create_request,
    create_stakeholder,
    org_base,
    project_base,
    setup,
    setup_with_people,
)
from tests.conftest import auth_headers, create_org_admin_in


def _scheme(client, token, project_id) -> dict:
    resp = client.get(project_base(project_id) + "/scoring-scheme", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _levels(scheme: dict) -> dict[str, dict[str, str]]:
    """`{axis: {level name: id}}`."""
    return {a["key"]: {lv["name"]: lv["id"] for lv in a["levels"]} for a in scheme["axes"]}


def _scored(levels: dict, *, reach="Many", impact="High", confidence="High", ease="Moderate", effort="Medium") -> dict:
    """A `levels` payload."""
    chosen = {"reach": reach, "impact": impact, "confidence": confidence, "ease": ease, "effort": effort}
    return {"levels": {axis: levels[axis][name] for axis, name in chosen.items() if name is not None}}


def _get(client, token, pid, request_id, query: str = "") -> dict:
    return client.get(project_base(pid) + f"/requests/{request_id}{query}", headers=auth_headers(token)).json()


def test_scheme_has_the_axes_and_the_three_models_with_effort_as_a_divisor(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Scheme Co")
    scheme = _scheme(client, token, project["id"])
    assert [a["key"] for a in scheme["axes"]] == ["reach", "impact", "confidence", "ease", "effort", "demand"]
    models = {m["key"]: m for m in scheme["models"]}
    assert models["ice"]["axis_keys"] == ["impact", "confidence", "ease"] and models["ice"]["divisor_axis_keys"] == []
    assert models["rice"]["axis_keys"] == ["reach", "impact", "confidence"]
    assert models["rice"]["divisor_axis_keys"] == ["effort"]
    assert models["rice_demand"]["axis_keys"] == ["demand", "impact", "confidence"]
    assert models["rice"]["cell_ratings"] == [] and scheme["default_model_key"] == "rice"
    demand = next(a for a in scheme["axes"] if a["key"] == "demand")
    assert demand["derived_source"] == "weighted_demand" and [lv["threshold"] for lv in demand["levels"]] == [0, 3, 8, 15, 30]
    assert next(a for a in scheme["axes"] if a["key"] == "reach")["derived_source"] is None


def test_score_is_derived_and_effort_lowers_it(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Score Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels, effort="Medium"))
    assert request["scoring_model_key"] == "rice"
    # Many (3) x High (2) x High (1) / Medium (2) = 3, out of a best case of 5 x 3 x 1 / 0.5 = 30.
    assert request["score"]["raw"] == 3 and request["score"]["normalised"] == 0.1
    assert request["score"]["label"] == "High"

    cheap = create_request(client, token, pid, title="Cheap", **_scored(levels, effort="Trivial"))
    costly = create_request(client, token, pid, title="Costly", **_scored(levels, effort="Huge"))
    assert cheap["score"]["raw"] > request["score"]["raw"] > costly["score"]["raw"]
    assert costly["score"]["label"] == "Low"


def test_ice_multiplies_by_ease_so_a_higher_ease_raises_it(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Ease Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    easy = create_request(client, token, pid, **_scored(levels, ease="Very easy"))
    hard = create_request(client, token, pid, title="Hard", **_scored(levels, ease="Very hard"))
    ice = "?scoring_model=ice"
    # High (2) x High (1) x Very easy (5) = 10 of a best case 3 x 1 x 5 = 15; Very hard (1) gives 2.
    assert _get(client, token, pid, easy["id"], ice)["score"]["raw"] == 10
    assert _get(client, token, pid, easy["id"], ice)["score"]["normalised"] == pytest.approx(10 / 15)
    assert _get(client, token, pid, hard["id"], ice)["score"]["raw"] == 2


def test_several_models_are_scored_side_by_side_and_the_data_is_left_alone(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Model Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels))
    base = project_base(pid) + f"/requests/{request['id']}"
    plain = client.get(base, headers=auth_headers(token)).json()
    # Every enabled model by default, the default (RICE) first and shown as `score`.
    assert list(plain["scores"]) == ["rice", "ice", "rice_demand"]
    assert (plain["scoring_model_key"], plain["score"]["raw"]) == ("rice", 3)
    assert plain["scores"]["ice"]["raw"] == 6  # 2 x 1 x Moderate (3)
    # No requesters, so Demand is the lowest level (1): 1 x 2 x 1 / 2.
    assert plain["scores"]["rice_demand"]["raw"] == 1

    chosen = client.get(base + "?scoring_model=ice,rice", headers=auth_headers(token)).json()
    assert list(chosen["scores"]) == ["ice", "rice"] and chosen["scoring_model_key"] == "ice" and chosen["score"]["raw"] == 6
    repeated = client.get(base + "?scoring_model=ice&scoring_model=rice", headers=auth_headers(token)).json()
    assert list(repeated["scores"]) == ["ice", "rice"]
    listed = client.get(project_base(pid) + "/requests?scoring_model=ice", headers=auth_headers(token)).json()
    assert listed[0]["scoring_model_key"] == "ice" and list(listed[0]["scores"]) == ["ice"]
    assert chosen["levels"] == plain["levels"]  # nothing was written
    assert client.get(base + "?scoring_model=nope", headers=auth_headers(token)).status_code == 400


def test_a_request_is_not_scored_until_every_manual_axis_the_model_needs_is_set(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Partial Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels, reach=None, ease=None, effort=None))
    assert request["score"] is None and request["scores"] == {"rice": None, "ice": None, "rice_demand": None}
    base = project_base(pid) + f"/requests/{request['id']}"
    updated = client.put(base, json={"levels": {"effort": levels["effort"]["Small"]}}, headers=auth_headers(token)).json()
    assert updated["score"] is None  # RICE still needs Reach
    assert updated["scores"]["rice_demand"]["raw"] == 2  # Demand is derived: 1 x 2 x 1 / 1
    ice_missing = updated["scores"]["ice"]
    assert ice_missing is None  # ICE needs Ease
    ice = client.put(base, json={"levels": {"ease": levels["ease"]["Easy"]}}, headers=auth_headers(token)).json()
    assert ice["scores"]["ice"]["raw"] == 8
    cleared = client.put(base, json={"levels": {"ease": None}}, headers=auth_headers(token)).json()
    assert "ease" not in cleared["levels"] and cleared["scores"]["ice"] is None
    assert cleared["levels"]["effort"] == levels["effort"]["Small"]  # an axis not mentioned is kept


def test_levels_are_versioned_and_carried_through_other_edits_and_transitions(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Version Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels))
    base = project_base(pid) + f"/requests/{request['id']}"
    client.put(base, json={"title": "Renamed"}, headers=auth_headers(token))
    client.post(base + "/transition", json={"status": "under_review"}, headers=auth_headers(token))
    client.put(base, json={"levels": {"impact": levels["impact"]["Low"]}}, headers=auth_headers(token))
    current = client.get(base, headers=auth_headers(token)).json()
    assert current["levels"]["reach"] == levels["reach"]["Many"] and current["levels"]["impact"] == levels["impact"]["Low"]
    versions = client.get(base + "/versions", headers=auth_headers(token)).json()
    assert [v["levels"]["impact"] for v in versions] == [levels["impact"]["High"]] * 3 + [levels["impact"]["Low"]]
    assert all(v["levels"]["effort"] == levels["effort"]["Medium"] for v in versions)


def test_a_level_must_be_the_organisations_own_on_the_right_axis(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Level Co")
    _, other_project, other_token = setup(client, admin_token, "Feedback Level Other Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    foreign = _levels(_scheme(client, other_token, other_project["id"]))
    wrong_axis = client.post(
        project_base(pid) + "/requests", json={"title": "x", "levels": {"reach": levels["impact"]["High"]}},
        headers=auth_headers(token),
    )
    assert wrong_axis.status_code == 400
    other_org = client.post(
        project_base(pid) + "/requests", json={"title": "x", "levels": {"reach": foreign["reach"]["Many"]}},
        headers=auth_headers(token),
    )
    assert other_org.status_code == 400
    unknown_axis = client.post(
        project_base(pid) + "/requests", json={"title": "x", "levels": {"gravity": levels["impact"]["High"]}},
        headers=auth_headers(token),
    )
    assert unknown_axis.status_code == 400
    request = create_request(client, token, pid)
    update = client.put(
        project_base(pid) + f"/requests/{request['id']}", json={"levels": {"effort": foreign["effort"]["Small"]}},
        headers=auth_headers(token),
    )
    assert update.status_code == 400


def test_the_inbox_scores_on_the_organisation_scale(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Inbox Score Co")
    levels = _levels(_scheme(client, token, project["id"]))
    scheme = client.get(org_base(org["id"]) + "/scoring-scheme", headers=auth_headers(token))
    assert scheme.status_code == 200 and _levels(scheme.json()) == levels
    request = create_inbox_request(client, token, org["id"], **_scored(levels))
    assert request["score"]["raw"] == 3 and request["project_id"] is None
    listed = client.get(org_base(org["id"]) + "/requests?scoring_model=ice", headers=auth_headers(token)).json()
    assert listed[0]["score"]["raw"] == 6


def test_a_project_default_model_leads_until_a_model_is_chosen(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Default Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels))
    put = client.put(
        f"/api/v1/projects/{pid}/scoring-schemes/enhancement_request/default-model", json={"model": "ice"},
        headers=auth_headers(token),
    )
    assert put.status_code == 200, put.text
    shown = _get(client, token, pid, request["id"])
    assert (shown["scoring_model_key"], shown["score"]["raw"]) == ("ice", 6)
    assert list(shown["scores"])[0] == "ice"
    chosen = _get(client, token, pid, request["id"], "?scoring_model=rice")
    assert chosen["score"]["raw"] == 3


def test_deleting_an_in_use_level_forces_a_reassignment_of_current_versions(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Reassign Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels, effort="Large"))
    url = f"/api/v1/orgs/{org['id']}/scoring-schemes/enhancement_request/levels/{levels['effort']['Large']}"
    blocked = client.delete(url, headers=auth_headers(token))
    assert blocked.status_code == 409, blocked.text
    moved = client.delete(f"{url}?reassign_to_id={levels['effort']['Huge']}", headers=auth_headers(token))
    assert moved.status_code == 204, moved.text
    assert _get(client, token, pid, request["id"])["levels"]["effort"] == levels["effort"]["Huge"]


# --- Derived demand ----------------------------------------------------------------------------------------------


def _three_requesters(client, org, token, pid, request_id) -> None:
    """Requesters worth 7.5 of weighted demand: Influence High (3) and Low (1), an unrated stakeholder (1) and a
    persona of weight 2.5."""
    high = create_stakeholder(client, token, pid, "Hana High", influence="High", org_id=org["id"])
    low = create_stakeholder(client, token, pid, "Lou Low", influence="Low", org_id=org["id"])
    unrated = create_stakeholder(client, token, pid, "Una Unrated")
    heavy = create_persona(client, token, pid, "Heavy user", weight=2.5)
    for kind, record in (("stakeholder", high), ("stakeholder", low), ("stakeholder", unrated), ("persona", heavy)):
        assert add_requester(client, token, org["id"], pid, request_id, kind, record["id"]).status_code == 201


def test_demand_is_bucketed_into_a_level_by_the_thresholds_and_a_chosen_level_wins(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Derived Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels, effort="Small"))
    none_yet = _get(client, token, pid, request["id"])
    assert none_yet["derived_levels"]["demand"] == levels["demand"]["Single voice"] and "demand" not in none_yet["levels"]

    _three_requesters(client, org, token, pid, request["id"])  # weighted demand 7.5
    shown = _get(client, token, pid, request["id"], "?scoring_model=rice_demand")
    assert shown["weighted_demand"] == 7.5 and shown["derived_levels"]["demand"] == levels["demand"]["A few"]
    # A few (2) x High (2) x High (1) / Small (1) = 4.
    assert shown["score"]["raw"] == 4

    # The thresholds are the organisation's: moving "Several" down to 7 re-buckets it, nothing is stored.
    lowered = client.patch(
        f"/api/v1/orgs/{org['id']}/scoring-schemes/enhancement_request/levels/{levels['demand']['Several']}",
        json={"threshold": 7}, headers=auth_headers(token),
    )
    assert lowered.status_code == 200 and lowered.json()["threshold"] == 7
    rebucketed = _get(client, token, pid, request["id"], "?scoring_model=rice_demand")
    assert rebucketed["derived_levels"]["demand"] == levels["demand"]["Several"] and rebucketed["score"]["raw"] == 6

    # A level chosen by hand wins, and is then not listed as derived.
    chosen = client.put(
        project_base(pid) + f"/requests/{request['id']}", json={"levels": {"demand": levels["demand"]["Widespread"]}},
        headers=auth_headers(token),
    ).json()
    assert "demand" not in chosen["derived_levels"] and chosen["scores"]["rice_demand"]["raw"] == 10
    cleared = client.put(
        project_base(pid) + f"/requests/{request['id']}", json={"levels": {"demand": None}}, headers=auth_headers(token),
    ).json()
    assert cleared["derived_levels"]["demand"] == levels["demand"]["Several"]


def test_an_inbox_request_has_no_requesters_so_its_demand_is_the_lowest_level(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Inbox Demand Co")
    levels = _levels(_scheme(client, token, project["id"]))
    request = create_inbox_request(client, token, org["id"], **_scored(levels, effort="Small"))
    assert request["derived_levels"]["demand"] == levels["demand"]["Single voice"] and request["weighted_demand"] == 0


def test_only_a_derived_axis_takes_a_threshold_and_thresholds_are_unique(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Threshold Co")
    levels = _levels(_scheme(client, token, project["id"]))
    base = f"/api/v1/orgs/{org['id']}/scoring-schemes/enhancement_request"
    ordinary = client.patch(f"{base}/levels/{levels['reach']['Many']}", json={"threshold": 5}, headers=auth_headers(token))
    assert ordinary.status_code == 400
    duplicate = client.patch(f"{base}/levels/{levels['demand']['Many']}", json={"threshold": 3}, headers=auth_headers(token))
    assert duplicate.status_code == 400
    no_threshold = client.post(
        f"{base}/axes/demand/levels", json={"name": "Huge", "weight": 6}, headers=auth_headers(token),
    )
    assert no_threshold.status_code == 400
    added = client.post(
        f"{base}/axes/demand/levels", json={"name": "Huge", "weight": 6, "threshold": 60}, headers=auth_headers(token),
    )
    assert added.status_code == 201 and added.json()["threshold"] == 60
    on_ordinary = client.post(
        f"{base}/axes/reach/levels", json={"name": "Huge", "weight": 6, "threshold": 60}, headers=auth_headers(token),
    )
    assert on_ordinary.status_code == 400


# --- Enabled models ----------------------------------------------------------------------------------------------


def test_the_enabled_models_resolve_project_then_organisation_then_every_model(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Enabled Co")
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels))
    org_url = f"/api/v1/orgs/{org['id']}/scoring-schemes/enhancement_request/enabled-models"
    project_url = f"/api/v1/projects/{pid}/scoring-schemes/enhancement_request/enabled-models"
    assert _scheme(client, token, pid)["enabled_model_keys"] == ["rice", "ice", "rice_demand"]
    assert _scheme(client, token, pid)["enabled_models_source"] == "system"

    organisation = client.put(org_url, json={"models": ["rice", "ice"]}, headers=auth_headers(token))
    assert organisation.status_code == 200 and organisation.json()["enabled_model_keys"] == ["rice", "ice"]
    assert list(_get(client, token, pid, request["id"])["scores"]) == ["rice", "ice"]

    own = client.put(project_url, json={"models": ["ice"]}, headers=auth_headers(token))
    assert own.status_code == 200 and own.json()["enabled_models_source"] == "project"
    # The default model is always shown, and first, even when a set leaves it out.
    assert own.json()["enabled_model_keys"] == ["rice", "ice"]
    inbox = client.get(org_base(org["id"]) + "/scoring-scheme", headers=auth_headers(token)).json()
    assert inbox["enabled_model_keys"] == ["rice", "ice"] and inbox["enabled_models_source"] == "org"

    reset = client.put(project_url, json={"models": None}, headers=auth_headers(token))
    assert reset.json()["enabled_models_source"] == "org"
    assert client.put(org_url, json={"models": []}, headers=auth_headers(token)).status_code == 400
    assert client.put(org_url, json={"models": ["nope"]}, headers=auth_headers(token)).status_code == 400
    assert client.put(org_url, json={"models": ["ice", "ice"]}, headers=auth_headers(token)).status_code == 400


# --- The unscored filter -----------------------------------------------------------------------------------------


def _filter_fixture(client, admin_token, name):
    org, project, token = setup(client, admin_token, name)
    pid = project["id"]
    levels = _levels(_scheme(client, token, pid))
    full = create_request(client, token, pid, title="Full", **_scored(levels))
    no_ease = create_request(client, token, pid, title="No ease", **_scored(levels, ease=None))
    no_reach = create_request(client, token, pid, title="No reach", **_scored(levels, reach=None))
    bare = create_request(client, token, pid, title="Bare")
    return org, pid, token, {"full": full, "no_ease": no_ease, "no_reach": no_reach, "bare": bare}


def _titles(client, token, pid, query: str) -> list[str]:
    resp = client.get(project_base(pid) + "/requests?" + query, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return sorted(r["title"] for r in resp.json())


def test_the_unscored_filter_reads_the_first_models_manual_axes(client, admin_token):
    _, pid, token, _ = _filter_fixture(client, admin_token, "Feedback Unscored Co")
    # Default (RICE): needs Reach, Impact, Confidence and Effort.
    assert _titles(client, token, pid, "scored=unscored") == ["Bare", "No reach"]
    assert _titles(client, token, pid, "scored=scored") == ["Full", "No ease"]
    # ICE needs Ease instead of Reach and Effort.
    assert _titles(client, token, pid, "scored=unscored&scoring_model=ice") == ["Bare", "No ease"]
    # The first chosen model decides.
    assert _titles(client, token, pid, "scored=unscored&scoring_model=ice&scoring_model=rice") == ["Bare", "No ease"]
    # A derived axis is never missing, so RICE with derived demand needs only Impact, Confidence and Effort.
    assert _titles(client, token, pid, "scored=unscored&scoring_model=rice_demand") == ["Bare"]


def test_missing_axis_finds_who_lacks_one_criterion(client, admin_token):
    _, pid, token, _ = _filter_fixture(client, admin_token, "Feedback Missing Axis Co")
    assert _titles(client, token, pid, "missing_axis=ease") == ["Bare", "No ease"]
    assert _titles(client, token, pid, "missing_axis=reach") == ["Bare", "No reach"]
    assert _titles(client, token, pid, "missing_axis=impact") == ["Bare"]
    assert _titles(client, token, pid, "missing_axis=demand") == []  # derived: never missing
    assert _titles(client, token, pid, "missing_axis=reach&scored=unscored") == ["Bare", "No reach"]
    # `any` is "not rated on every criterion": a request lacking at least one manual criterion (a derived one never counts).
    assert _titles(client, token, pid, "missing_axis=any") == ["Bare", "No ease", "No reach"]
    # Combined with Unscored it also needs the first model (RICE) to lack a level, which "No ease" does not.
    assert _titles(client, token, pid, "missing_axis=any&scored=unscored") == ["Bare", "No reach"]
    bad = client.get(project_base(pid) + "/requests?missing_axis=gravity", headers=auth_headers(token))
    assert bad.status_code == 400
    assert client.get(project_base(pid) + "/requests?scored=maybe", headers=auth_headers(token)).status_code == 422


def test_the_filter_follows_the_current_version_and_applies_to_the_inbox_and_the_export(client, admin_token):
    org, pid, token, made = _filter_fixture(client, admin_token, "Feedback Filter Follow Co")
    levels = _levels(_scheme(client, token, pid))
    base = project_base(pid) + f"/requests/{made['no_reach']['id']}"
    client.put(base, json={"levels": {"reach": levels["reach"]["Few"]}}, headers=auth_headers(token))
    assert _titles(client, token, pid, "scored=unscored") == ["Bare"]  # the new version has Reach

    create_inbox_request(client, token, org["id"], title="Inbox bare")
    create_inbox_request(client, token, org["id"], title="Inbox full", **_scored(levels))
    inbox = client.get(org_base(org["id"]) + "/requests?scored=unscored", headers=auth_headers(token)).json()
    assert [r["title"] for r in inbox] == ["Inbox bare"]

    export = client.get(
        f"/api/v1/projects/{pid}/records/enhancement_request/export", params={"scored": "unscored"},
        headers=auth_headers(token),
    )
    assert export.status_code == 200, export.text
    assert "Bare" in export.text and "Full" not in export.text and "No reach" not in export.text


def _preview(client, token, base: str, levels: dict, request_id: str | None = None):
    body = {"levels": levels, **({"request_id": request_id} if request_id else {})}
    return client.post(f"{base}/score-preview", json=body, headers=auth_headers(token))


def test_score_preview_scores_unsaved_levels_exactly_as_a_saved_request_would_be(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Preview Co")
    pid, base = project["id"], project_base(project["id"])
    levels = _levels(_scheme(client, token, pid))
    payload = _scored(levels, effort="Medium", ease=None)
    saved = create_request(client, token, pid, **payload)

    resp = _preview(client, token, base, payload["levels"])
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["scores"] == saved["scores"]  # the same derivation, nothing stored
    assert preview["scores"]["ice"] is None  # Ease is missing, so ICE is not scored (never zero)
    assert preview["weighted_demand"] == 0 and set(preview["derived_levels"]) == {"demand"}
    assert len(client.get(base + "/requests", headers=auth_headers(token)).json()) == 1  # the preview created nothing

    # Nothing chosen: nothing scores, and a null level is the same as an absent one.
    empty = _preview(client, token, base, {"reach": None}).json()
    assert empty["scores"]["rice"] is None and empty["scores"]["ice"] is None


def test_score_preview_reads_an_existing_requests_demand_and_refuses_bad_levels(client, admin_token):
    _, project, token = setup_with_people(client, admin_token, "Feedback Preview Demand Co")
    pid, base = project["id"], project_base(project["id"])
    levels = _levels(_scheme(client, token, pid))
    request = create_request(client, token, pid, **_scored(levels))
    for name in ("Ann", "Bob", "Cy", "Dee"):
        person = create_stakeholder(client, token, pid, name)
        assert add_requester(client, token, project["organization_id"], pid, request["id"], "stakeholder", person["id"]).status_code == 201

    with_demand = _preview(client, token, base, _scored(levels)["levels"], request["id"]).json()
    without = _preview(client, token, base, _scored(levels)["levels"]).json()
    assert with_demand["weighted_demand"] == 4 and without["weighted_demand"] == 0
    assert with_demand["derived_levels"]["demand"] != without["derived_levels"]["demand"]
    assert with_demand["scores"]["rice_demand"]["normalised"] > without["scores"]["rice_demand"]["normalised"]

    # A level on the wrong axis, an unknown axis and a request of another project are refused.
    assert _preview(client, token, base, {"impact": levels["reach"]["Many"]}).status_code == 400
    assert _preview(client, token, base, {"no_such_axis": levels["reach"]["Many"]}).status_code == 400
    assert _preview(client, token, base, {}, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_score_preview_works_for_the_inbox_and_needs_membership(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Preview Inbox Co")
    outsider_org, outsider = create_org_admin_in(client, admin_token, "Feedback Preview Outsider Co")
    levels = _levels(_scheme(client, token, project["id"]))
    body = _scored(levels)["levels"]
    resp = _preview(client, token, org_base(org["id"]), body)
    assert resp.status_code == 200 and resp.json()["scores"]["rice"] is not None
    assert _preview(client, outsider, org_base(org["id"]), body).status_code in (403, 404)
    assert _preview(client, outsider, project_base(project["id"]), body).status_code in (403, 404)
