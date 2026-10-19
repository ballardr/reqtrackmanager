"""Tests that a Pain Point can be scored when it is created (the create form accepts what the
scoring panel does) and that creating without scores is unchanged.

Covers: scores persisted by `POST .../pain-points`, an invalid score leaving no Pain Point behind,
scoring at creation needing the manager tier while a plain create does not, and the scoring-targets
endpoint that tells a create form whether to offer scoring.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.database import SessionLocal
from app.modules.context_strategy.models import PainPoint
from app.modules.context_strategy.tests.test_context_strategy_pain_point_scoring import (
    _cs,
    _entry,
    _get,
    _levels,
    _persona,
    _setup,
)
from tests.conftest import auth_headers, create_org_user, login


def _create(client, token, project_id, **extra):
    types = client.get(_cs(project_id) + "/pain-point-types", headers=auth_headers(token)).json()
    return client.post(
        _cs(project_id) + "/pain-points",
        json={"pain_point_type_id": types[0]["id"], "title": "Slow reports", **extra}, headers=auth_headers(token),
    )


def _count(project_id) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PainPoint).where(PainPoint.project_id == project_id))


def test_create_persists_all_persona_scores(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Create Scores Co")
    pid = project["id"]
    levels = _levels(client, token, pid)

    resp = _create(client, token, pid, scores=[_entry(levels, severity="Blocker", frequency="Rare", confidence="High")])
    assert resp.status_code == 201, resp.text
    body = _get(client, token, pid, resp.json()["id"], model_key="sxf")
    assert body["scope"] == "all_personas" and body["is_blocker"] is True
    assert body["score"]["raw"] == 5


def test_create_persists_per_persona_scores(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Create Persona Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    heavy = _persona(client, token, pid, "Heavy", weight=3)
    light = _persona(client, token, pid, "Light", weight=1)

    resp = _create(client, token, pid, scores=[
        _entry(levels, heavy, severity="Blocker", frequency="Rare"), _entry(levels, light, severity="Minor", frequency="Rare"),
    ])
    assert resp.status_code == 201, resp.text
    body = _get(client, token, pid, resp.json()["id"])
    assert body["scope"] == "per_persona" and body["counted"] == 2


def test_create_without_scores_is_unscored(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Create Plain Co")
    resp = _create(client, token, project["id"])
    assert resp.status_code == 201, resp.text
    assert _get(client, token, project["id"], resp.json()["id"])["scope"] == "none"


def test_invalid_score_creates_nothing(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Create Invalid Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    before = _count(pid)

    wrong_axis = {**_entry(levels), "severity_level_id": levels["frequency"]["Rare"]}
    assert _create(client, token, pid, scores=[wrong_axis]).status_code == 400
    unknown = _entry(levels, "00000000-0000-0000-0000-000000000001", severity="Minor")
    assert _create(client, token, pid, scores=[unknown]).status_code == 400
    assert _count(pid) == before


def test_member_can_create_but_not_score_and_is_told_so(client, admin_token):
    org, project, token = _setup(client, admin_token, "PP Create RBAC Co")
    pid = project["id"]
    levels = _levels(client, token, pid)
    user_id = create_org_user(client, token, org["id"], "pp_create_scores_member@example.com")
    assert client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token)).status_code == 204
    member = login(client, "pp_create_scores_member@example.com", "Password123!")
    before = _count(pid)

    assert _create(client, member, pid).status_code == 201
    assert _create(client, member, pid, scores=[_entry(levels, severity="Minor")]).status_code == 403
    assert _count(pid) == before + 1

    targets = client.get(_cs(pid) + "/pain-point-scoring-targets", headers=auth_headers(member))
    assert targets.status_code == 200 and targets.json() == {"can_score": False, "available_targets": []}


def test_scoring_targets_lists_personas_for_a_manager(client, admin_token):
    _, project, token = _setup(client, admin_token, "PP Create Targets Co")
    pid = project["id"]
    persona = _persona(client, token, pid, "Heavy", weight=3)

    body = client.get(_cs(pid) + "/pain-point-scoring-targets", headers=auth_headers(token)).json()
    assert body["can_score"] is True
    assert [(t["id"], t["label"], t["is_active"]) for t in body["available_targets"]] == [(persona, "Heavy", True)]
