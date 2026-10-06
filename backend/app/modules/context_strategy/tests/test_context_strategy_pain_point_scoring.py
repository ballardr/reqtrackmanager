"""Tests for per-persona Pain Point scoring and the intentional flag
(docs/plans/module-01-context-and-strategy-plan.md Phase 11), through the
real HTTP endpoints.

Covers: the `is_intentional` round trip, the either/or (all-personas XOR
per-persona) rule, level validation (wrong axis / other org), the three
roll-up methods and their maths, the Blocker flag surviving an average,
"not scored under this model" input gaps, retired and unavailable personas
(including Module 2 being switched off), RBAC and lock rules, level-usage
reassignment on delete, audit logging and model/roll-up parameter checks.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

CS = "context_strategy"
SH = "stakeholders"


def _cs(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{CS}"


def _enable(client, token, org_id, module, enabled=True) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module}", json={"enabled": enabled}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"], CS)
    _enable(client, token, org["id"], SH)
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _levels(client, token, project_id) -> dict[str, dict[str, str]]:
    """axis key -> level name -> level id for the project's org."""
    resp = client.get(f"/api/v1/projects/{project_id}/scoring-schemes/pain_point", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in resp.json()["axes"]}


def _persona(client, token, project_id, name, *, weight=None, activate=True) -> str:
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/{SH}/personas",
        json={"name": name, "description": name, "weight": weight}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    if activate:
        act = client.post(f"/api/v1/projects/{project_id}/modules/{SH}/personas/{pid}/activate", headers=auth_headers(token))
        assert act.status_code == 200, act.text
    return pid


def _pain_point(client, token, project_id, **extra) -> dict:
    types = client.get(_cs(project_id) + "/pain-point-types", headers=auth_headers(token)).json()
    resp = client.post(
        _cs(project_id) + "/pain-points",
        json={"pain_point_type_id": types[0]["id"], "title": "Slow reports", **extra}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _put(client, token, project_id, pp_id, scores, **params):
    return client.put(
        f"{_cs(project_id)}/pain-points/{pp_id}/scores", json={"scores": scores}, params=params, headers=auth_headers(token),
    )


def _get(client, token, project_id, pp_id, **params):
    resp = client.get(f"{_cs(project_id)}/pain-points/{pp_id}/scores", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(levels, target_id=None, severity=None, frequency=None, confidence=None) -> dict:
    return {
        "target_id": target_id,
        "severity_level_id": levels["severity"][severity] if severity else None,
        "frequency_level_id": levels["frequency"][frequency] if frequency else None,
        "confidence_level_id": levels["confidence"][confidence] if confidence else None,
    }


# --- Intentional flag --------------------------------------------------------


def test_is_intentional_round_trip_and_unchanged_when_omitted(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Intentional Co")
    pid = project["id"]
    pp = _pain_point(client, token, pid, is_intentional=True)
    assert pp["is_intentional"] is True
    assert _pain_point(client, token, pid)["is_intentional"] is False

    base = {"pain_point_type_id": pp["pain_point_type_id"], "title": "Renamed", "priority": "medium"}
    url = f"{_cs(pid)}/pain-points/{pp['id']}"
    # Omitting the flag on a full update leaves it alone (e.g. owner assignment).
    assert client.put(url, json=base, headers=auth_headers(token)).json()["is_intentional"] is True
    assert client.put(url, json={**base, "is_intentional": False}, headers=auth_headers(token)).json()["is_intentional"] is False


# --- Writing scores ----------------------------------------------------------


def test_all_personas_score_and_blocker(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score All Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)

    empty = _get(client, token, pid, pp["id"])
    assert empty["scope"] == "none" and empty["score"] is None and empty["is_blocker"] is False

    resp = _put(client, token, pid, pp["id"], [_entry(levels, severity="Blocker", frequency="Rare", confidence="High")], model_key="sxf")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "all_personas" and body["is_blocker"] is True and body["counted"] == 1
    # 5 x 1 = 5, of a possible 5 x 4 = 20 -> 0.25, the "Medium" band.
    assert body["score"]["raw"] == 5 and body["score"]["normalised"] == 0.25 and body["score"]["band_label"] == "Medium"
    assert body["entries"][0]["status"] == "all" and body["entries"][0]["label"] is None
    # Re-reading under another model: S x F x C = 5 x 1 x 1 of 20.
    assert _get(client, token, pid, pp["id"], model_key="sxfxc")["score"]["raw"] == 5

    cleared = _put(client, token, pid, pp["id"], [])
    assert cleared.json()["scope"] == "none"


def test_cannot_mix_all_personas_with_persona_rows_or_duplicate_a_persona(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Mix Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    persona = _persona(client, token, pid, "Tech")
    pp = _pain_point(client, token, pid)

    mixed = _put(client, token, pid, pp["id"], [
        _entry(levels, None, severity="Minor"), _entry(levels, persona, severity="Minor"),
    ])
    assert mixed.status_code == 400 and "not both" in mixed.json()["detail"]
    dup = _put(client, token, pid, pp["id"], [_entry(levels, persona, severity="Minor"), _entry(levels, persona, severity="Major")])
    assert dup.status_code == 400
    # Entries with no level chosen are dropped, so a blank all-personas row doesn't conflict.
    ok = _put(client, token, pid, pp["id"], [_entry(levels, None), _entry(levels, persona, severity="Minor")])
    assert ok.status_code == 200 and ok.json()["scope"] == "per_persona"


def test_level_validation(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Levels Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    other_org, other_project, other_token = _setup(client, admin_token, "PP Score Levels Other Co")
    other_levels = _levels(client, other_token, other_project["id"])
    pp = _pain_point(client, token, pid)

    wrong_axis = {**_entry(levels), "severity_level_id": levels["frequency"]["Rare"]}
    assert _put(client, token, pid, pp["id"], [wrong_axis]).status_code == 400
    foreign = {**_entry(levels), "severity_level_id": other_levels["severity"]["Minor"]}
    assert _put(client, token, pid, pp["id"], [foreign]).status_code == 400
    unknown_persona = _entry(levels, "00000000-0000-0000-0000-000000000001", severity="Minor")
    assert _put(client, token, pid, pp["id"], [unknown_persona]).status_code == 400
    assert other_org["id"] != project["organization_id"]


def test_oversized_score_payload_is_rejected(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Cap Co")
    pid = project["id"]
    pp = _pain_point(client, token, pid)
    blank = {"target_id": None, "severity_level_id": None, "frequency_level_id": None, "confidence_level_id": None}
    assert _put(client, token, pid, pp["id"], [blank] * 501).status_code == 422


# --- Roll-up maths -----------------------------------------------------------


def _two_persona_setup(client, admin_token, name):
    _, project, token = _setup(client, admin_token, name)
    pid = project["id"]
    levels = _levels(client, token, pid)
    heavy = _persona(client, token, pid, "Heavy", weight=3)
    light = _persona(client, token, pid, "Light", weight=1)
    return pid, token, levels, heavy, light, _pain_point(client, token, pid)


def test_rollup_methods(client, admin_token):
    pid, token, levels, heavy, light, pp = _two_persona_setup(client, admin_token, "PP Rollup Co")
    resp = _put(client, token, pid, pp["id"], [
        _entry(levels, heavy, severity="Major", frequency="Constant"),  # 4 x 4 = 16
        _entry(levels, light, severity="Minor", frequency="Rare"),  # 2 x 1 = 2
    ], model_key="sxf")
    assert resp.status_code == 200, resp.text

    def raw(method):
        body = _get(client, token, pid, pp["id"], model_key="sxf", rollup=method)
        return body["score"]["raw"], body["score"]["band_label"]

    assert raw("weighted_average") == (12.5, "Critical")  # (3x16 + 1x2) / 4 = 12.5 of 20 = 0.625
    assert raw("worst_case") == (16, "Critical")
    assert raw("average") == (9, "High")  # 0.45


def test_unweighted_personas_count_equally(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Rollup Equal Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    a, b = _persona(client, token, pid, "A"), _persona(client, token, pid, "B")
    pp = _pain_point(client, token, pid)
    _put(client, token, pid, pp["id"], [
        _entry(levels, a, severity="Major", frequency="Constant"), _entry(levels, b, severity="Minor", frequency="Rare"),
    ])
    assert _get(client, token, pid, pp["id"], model_key="sxf")["score"]["raw"] == 9


def test_unscored_persona_is_excluded_not_zero(client, admin_token):
    pid, token, levels, heavy, light, pp = _two_persona_setup(client, admin_token, "PP Rollup Gap Co")
    # `light` has no Frequency, so under S x F it is not scored and must not drag the average down.
    _put(client, token, pid, pp["id"], [
        _entry(levels, heavy, severity="Major", frequency="Constant"), _entry(levels, light, severity="Minor"),
    ])
    body = _get(client, token, pid, pp["id"], model_key="sxf")
    assert body["score"]["raw"] == 16 and body["counted"] == 2
    unscored = next(e for e in body["entries"] if e["label"] == "Light")
    assert unscored["score"] is None
    # No row can be scored under a model needing an input nobody supplied.
    assert _get(client, token, pid, pp["id"], model_key="sxfxc")["score"] is None


def test_blocker_survives_an_average(client, admin_token):
    pid, token, levels, heavy, light, pp = _two_persona_setup(client, admin_token, "PP Blocker Co")
    _put(client, token, pid, pp["id"], [
        _entry(levels, heavy, severity="Cosmetic", frequency="Rare"),
        _entry(levels, light, severity="Blocker", frequency="Rare"),
    ])
    body = _get(client, token, pid, pp["id"], model_key="sxf", rollup="weighted_average")
    assert body["score"]["band_label"] == "Low"  # the heavy persona dominates the average
    assert body["is_blocker"] is True and body["blocker_labels"] == ["Light"]


# --- Persona availability ----------------------------------------------------


def test_retired_persona_is_shown_but_not_counted(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Retired Persona Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    keep, gone = _persona(client, token, pid, "Keep"), _persona(client, token, pid, "Gone")
    pp = _pain_point(client, token, pid)
    _put(client, token, pid, pp["id"], [
        _entry(levels, keep, severity="Minor", frequency="Rare"), _entry(levels, gone, severity="Blocker", frequency="Constant"),
    ])
    retire = client.post(f"/api/v1/projects/{pid}/modules/{SH}/personas/{gone}/retire", json={"comment": "obsolete"}, headers=auth_headers(token))
    assert retire.status_code == 200, retire.text

    body = _get(client, token, pid, pp["id"], model_key="sxf")
    assert body["counted"] == 1 and body["score"]["raw"] == 2 and body["is_blocker"] is False
    assert {e["label"]: e["status"] for e in body["entries"]} == {"Keep": "active", "Gone": "inactive"}
    # A retired persona can't be newly scored.
    other = _pain_point(client, token, pid)
    assert _put(client, token, pid, other["id"], [_entry(levels, gone, severity="Minor")]).status_code == 400


def test_module_2_off_degrades_to_unlabelled_rows(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Persona Off Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    a, b = _persona(client, token, pid, "A", weight=5), _persona(client, token, pid, "B", weight=1)
    pp = _pain_point(client, token, pid)
    _put(client, token, pid, pp["id"], [
        _entry(levels, a, severity="Major", frequency="Constant"), _entry(levels, b, severity="Minor", frequency="Rare"),
    ])
    _enable(client, token, org["id"], SH, enabled=False)

    body = _get(client, token, pid, pp["id"], model_key="sxf")
    assert body["personas_degraded"] is True and body["available_targets"] == []
    assert {e["status"] for e in body["entries"]} == {"unavailable"}
    assert all(e["label"] is None for e in body["entries"])
    assert body["score"]["raw"] == 9  # still counted, equally weighted
    # All-personas scoring keeps working without personas.
    assert _put(client, token, pid, pp["id"], [_entry(levels, severity="Minor", frequency="Rare")]).status_code == 200


# --- RBAC, locking, audit ----------------------------------------------------


def test_member_can_read_but_not_write_scores(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Score RBAC Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    user_id = create_org_user(client, token, org["id"], "pp_score_member@example.com")
    assert client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token)).status_code == 204
    member = login(client, "pp_score_member@example.com", "Password123!")

    assert _put(client, member, pid, pp["id"], [_entry(levels, severity="Minor")]).status_code == 403
    assert _get(client, member, pid, pp["id"])["scope"] == "none"
    assert client.get(_cs(pid) + "/pain-point-scores", headers=auth_headers(member)).status_code == 200


def test_locked_pain_point_cannot_be_rescored(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Locked Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    base = f"{_cs(pid)}/pain-points/{pp['id']}"
    assert client.post(base + "/triage", json={}, headers=auth_headers(token)).status_code == 200
    assert client.post(base + "/reject", json={"comment": "no"}, headers=auth_headers(token)).status_code == 200
    assert _put(client, token, pid, pp["id"], [_entry(levels, severity="Minor")]).status_code == 409


def test_cross_project_pain_point_is_404(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Scope Co")
    other_project = create_project(client, token, project["organization_id"], "Other Project")
    pp = _pain_point(client, token, project["id"])
    assert client.get(f"{_cs(other_project['id'])}/pain-points/{pp['id']}/scores", headers=auth_headers(token)).status_code == 404


def test_scoring_is_audit_logged_once_per_real_change(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Audit Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    entries = [_entry(levels, severity="Minor", frequency="Rare")]
    _put(client, token, pid, pp["id"], entries)
    _put(client, token, pid, pp["id"], entries)  # no change -> no second event
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == pp["id"], AuditEvent.action == "scored")).all()
    assert len(events) == 1 and events[0].detail == {"all_personas": True, "scored_targets": 0}


# --- Parameters, list, defaults ----------------------------------------------


def test_unknown_model_or_rollup_is_400(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score Params Co")
    pid = project["id"]
    pp = _pain_point(client, token, pid)
    h = auth_headers(token)
    assert client.get(f"{_cs(pid)}/pain-points/{pp['id']}/scores", params={"model_key": "nope"}, headers=h).status_code == 400
    assert client.get(f"{_cs(pid)}/pain-points/{pp['id']}/scores", params={"rollup": "nope"}, headers=h).status_code == 400
    assert client.get(_cs(pid) + "/pain-point-scores", params={"model_key": "nope"}, headers=h).status_code == 400


def test_list_uses_project_default_model_and_respects_archive(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Score List Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    scored, archived = _pain_point(client, token, pid), _pain_point(client, token, pid, title="Old")
    _put(client, token, pid, scored["id"], [_entry(levels, severity="Blocker", frequency="Constant", confidence="High")])
    assert client.post(f"{_cs(pid)}/pain-points/{archived['id']}/archive", headers=auth_headers(token)).status_code == 200

    default = client.get(_cs(pid) + "/pain-point-scores", headers=auth_headers(token)).json()
    assert default["model_key"] == "sxfxc" and default["model_source"] == "system"
    assert [i["pain_point_id"] for i in default["items"]] == [scored["id"]]
    assert default["items"][0]["score"]["normalised"] == 1.0 and default["items"][0]["score"]["band_label"] == "Critical"

    resp = client.put(f"/api/v1/projects/{pid}/scoring-schemes/pain_point/default-model", json={"model": "sxc"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    overridden = client.get(_cs(pid) + "/pain-point-scores", params={"include_archived": "true"}, headers=auth_headers(token)).json()
    assert overridden["model_key"] == "sxc" and overridden["model_source"] == "project"
    assert len(overridden["items"]) == 2
    chosen = client.get(_cs(pid) + "/pain-point-scores", params={"model_key": "sxf"}, headers=auth_headers(token)).json()
    assert chosen["model_source"] == "chosen"


# --- Level usage -------------------------------------------------------------


def test_deleting_an_in_use_level_requires_and_performs_reassignment(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Score Level Use Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    pp = _pain_point(client, token, pid)
    _put(client, token, pid, pp["id"], [_entry(levels, severity="Minor", frequency="Rare")])
    h = auth_headers(token)
    url = f"/api/v1/orgs/{org['id']}/scoring-schemes/pain_point/levels/{levels['severity']['Minor']}"

    blocked = client.delete(url, headers=h)
    assert blocked.status_code == 409 and "used by 1" in blocked.json()["detail"]
    moved = client.delete(url, params={"reassign_to_id": levels["severity"]["Moderate"]}, headers=h)
    assert moved.status_code == 204, moved.text
    entry = _get(client, token, pid, pp["id"])["entries"][0]
    assert entry["severity_level_id"] == levels["severity"]["Moderate"]
