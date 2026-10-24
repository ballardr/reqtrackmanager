"""Tests for Context & Strategy bundle export/import (`export.py`).

A project's Pain Point types (overrides, local types, hidden defaults, definitions), Strategies, Future
States, Guiding Principles, Pain Points (with attachments and per-persona scores), Open Questions and the
links between them survive `GET /projects/{id}/export` + `POST /projects/import`; an organisation's Pain
Point type vocabulary and organisation-scoped records survive `GET /orgs/{id}/export` + `POST /orgs/import`.
Version history and comments do not travel (see `export.py`). Every test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date

from sqlalchemy import select

from app.database import SessionLocal
from app.models.relationship import ArtefactLink
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleVersion,
    OpenQuestion,
    PainPoint,
    PainPointFile,
    PainPointScore,
    PainPointTypeDefinition,
    ProjectPainPointType,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.service import PainPointLinkKind, StrategyLinkKind, create_pain_point_link, create_strategy_link
from tests.conftest import auth_headers, create_org_admin_in, create_project

CS = "context_strategy"
SH = "stakeholders"


def _cs(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{CS}"


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    for module in (CS, SH):
        resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{module}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _post(client, token, url, json_body, status=201):
    resp = client.post(url, json=json_body, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _export(client, token, project_id) -> bytes:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import(client, token, org_id, bundle: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _levels(client, token, project_id) -> dict[str, dict[str, str]]:
    resp = client.get(f"/api/v1/projects/{project_id}/scoring-schemes/pain_point", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in resp.json()["axes"]}


def _first(levels: dict[str, dict[str, str]], axis: str) -> str:
    """The id of the first level of a scoring axis."""
    return next(iter(levels[axis].values()))


def _persona(client, token, project_id, name) -> str:
    body = _post(client, token, f"/api/v1/projects/{project_id}/modules/{SH}/personas", {"name": name, "description": name})
    resp = client.post(f"/api/v1/projects/{project_id}/modules/{SH}/personas/{body['id']}/activate", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return body["id"]


def _build(client, token, org, project) -> dict[str, str]:
    """A project with every Context & Strategy record kind, a local and an overridden type, a hidden default,
    a persona-scored and an all-personas-scored Pain Point (the first with an attachment), and links."""
    h = auth_headers(token)
    base, pid = _cs(project["id"]), project["id"]
    local = _post(client, token, base + "/pain-point-types", {"name": "Project-only", "definition": "Only here."})
    types = {t["name"]: t for t in client.get(base + "/pain-point-types", headers=h).json()}
    assert client.put(
        f"{base}/pain-point-types/{types['Market']['id']}", json={"name": "Customer", "definition": "People who pay."}, headers=h,
    ).status_code == 200
    assert client.delete(f"{base}/pain-point-types/{types['Operator']['id']}", headers=h).status_code == 204  # hides it

    strategy = _post(client, token, base + "/strategies", {"title": "Grow", "objective": "Double usage", "rationale": "Market"})
    assert client.post(f"{base}/strategies/{strategy['id']}/propose", headers=h).status_code == 200
    _post(client, token, base + "/future-states", {"title": "Future A", "target_date": "2031-03-31", "outcomes": "More"})
    me = client.get("/api/v1/auth/me", headers=h).json()["id"]
    _post(client, token, base + "/guiding-principles", {
        "name": "Be simple", "principle_statement": "Prefer simple.", "owner": {"type": "user", "id": me},
    })
    question = _post(client, token, base + "/open-questions", {"question": "Who pays?", "due_date": "2031-01-02"})

    lv = _levels(client, token, pid)
    persona = _persona(client, token, pid, "Ada Operator")
    scored = _post(client, token, base + "/pain-points", {"pain_point_type_id": local["id"], "title": "Slow reports", "source": "Support"})
    assert client.put(
        f"{base}/pain-points/{scored['id']}/scores", headers=h,
        json={"scores": [{
            "target_id": persona, "severity_level_id": _first(lv, "severity"),
            "frequency_level_id": _first(lv, "frequency"), "confidence_level_id": _first(lv, "confidence"),
        }]},
    ).status_code == 200
    assert client.post(
        f"{base}/pain-points/{scored['id']}/files", files={"file": ("evidence.txt", b"proof", "text/plain")}, headers=h,
    ).status_code == 201
    plain = _post(client, token, base + "/pain-points", {"pain_point_type_id": types["User"]["id"], "title": "Confusing menu"})
    assert client.put(
        f"{base}/pain-points/{plain['id']}/scores", headers=h,
        json={"scores": [{"target_id": None, "severity_level_id": _first(lv, "severity")}]},
    ).status_code == 200

    db = SessionLocal()
    try:
        s_id, pp_id = uuid.UUID(strategy["id"]), uuid.UUID(scored["id"])
        create_pain_point_link(
            db, pain_point=db.get(PainPoint, pp_id), kind=PainPointLinkKind.DRIVES_STRATEGY, target_id=s_id,
            actor_id=uuid.UUID(me),
        )
        create_strategy_link(
            db, strategy=db.get(Strategy, s_id), kind=StrategyLinkKind.REQUIRES_RESOLUTION_OF_OPEN_QUESTION,
            target_id=uuid.UUID(question["id"]), actor_id=uuid.UUID(me),
        )
        db.commit()
    finally:
        db.close()
    return {"persona": persona}


def test_project_export_import_round_trips_context_and_strategy(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Bundle Co")
    _build(client, token, org, project)
    bundle = _export(client, token, project["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    assert len(exported["pain_points"]) == 2 and exported["pain_point_hidden_org_types"] == ["Operator"]

    imported = _import(client, token, org["id"], bundle, "CS Bundle Reimported")
    assert imported["warnings"] == []
    new_id = uuid.UUID(imported["project"]["id"])

    db = SessionLocal()
    try:
        types = {r.name_override or None: r for r in db.scalars(select(ProjectPainPointType).where(ProjectPainPointType.project_id == new_id))}
        assert types["Project-only"].definition_override == "Only here." and types["Project-only"].org_type_id is None
        assert types["Customer"].definition_override == "People who pay." and types["Customer"].org_type_id is not None

        pps = {p.title: p for p in db.scalars(select(PainPoint).where(PainPoint.project_id == new_id))}
        assert set(pps) == {"Slow reports", "Confusing menu"}
        assert pps["Slow reports"].source == "Support" and pps["Slow reports"].pain_point_type_id == types["Project-only"].id
        assert sorted(p.unique_code for p in pps.values()) == ["PP-001", "PP-002"]  # numbered afresh
        assert db.scalar(select(PainPointFile).where(PainPointFile.pain_point_id == pps["Slow reports"].id)) is not None

        persona_score = db.scalar(select(PainPointScore).where(PainPointScore.pain_point_id == pps["Slow reports"].id))
        assert persona_score.target_type == "persona" and persona_score.target_id is not None
        assert persona_score.severity_level_id is not None and persona_score.confidence_level_id is not None
        all_score = db.scalar(select(PainPointScore).where(PainPointScore.pain_point_id == pps["Confusing menu"].id))
        assert all_score.target_id is None and all_score.severity_level_id is not None and all_score.frequency_level_id is None

        strategy = db.scalar(select(Strategy).where(Strategy.project_id == new_id))
        version = db.scalar(select(StrategyVersion).where(StrategyVersion.strategy_id == strategy.id))
        assert (version.title, version.objective, version.status.value) == ("Grow", "Double usage", "proposed")
        future = db.scalar(select(FutureStateVersion).join(FutureState).where(FutureState.project_id == new_id))
        assert future.target_date == date(2031, 3, 31) and future.outcomes == "More"
        principle = db.scalar(select(GuidingPrincipleVersion).join(GuidingPrinciple).where(GuidingPrinciple.project_id == new_id))
        assert principle.name == "Be simple" and principle.owner_id is not None
        question = db.scalar(select(OpenQuestion).where(OpenQuestion.project_id == new_id))
        assert question.question == "Who pays?" and question.due_date == date(2031, 1, 2)

        links = db.scalars(select(ArtefactLink).where(ArtefactLink.source_id.in_([strategy.id, pps["Slow reports"].id]))).all()
        assert {(lk.source_type, lk.target_type) for lk in links} == {
            ("pain_point", "strategy"), ("strategy", "open_question"),
        }
    finally:
        db.close()

    # The hidden default stays hidden in the copy, and the new Pain Point codes continue after the imported ones.
    effective = client.get(_cs(new_id) + "/pain-point-types", headers=auth_headers(token)).json()
    types_now = {t["name"] for t in effective}
    assert "Operator" not in types_now and {"Customer", "Project-only"} <= types_now
    customer = next(t["id"] for t in effective if t["name"] == "Customer")
    again = _post(client, token, _cs(new_id) + "/pain-points", {"pain_point_type_id": customer, "title": "Newer"})
    assert again["unique_code"] == "PP-003"


def test_score_against_a_persona_the_copy_lacks_is_skipped_with_a_warning(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Bundle Persona Co")
    _build(client, token, org, project)
    bundle = _export(client, token, project["id"])

    def drop_personas(doc):
        doc["project_personas"] = []

    source = zipfile.ZipFile(io.BytesIO(bundle))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "project.json":
                doc = json.loads(data)
                drop_personas(doc)
                data = json.dumps(doc).encode()
            target.writestr(item, data)
    imported = _import(client, token, org["id"], out.getvalue(), "CS Bundle No Persona")
    assert any("persona 'Ada Operator' not found" in w for w in imported["warnings"])
    db = SessionLocal()
    try:
        pp = db.scalar(select(PainPoint).where(PainPoint.project_id == uuid.UUID(imported["project"]["id"]), PainPoint.title == "Slow reports"))
        assert db.scalar(select(PainPointScore).where(PainPointScore.pain_point_id == pp.id)) is None
    finally:
        db.close()


def test_org_export_import_round_trips_types_and_org_scoped_records(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Org Bundle Co")
    h = auth_headers(token)
    org_base = f"/api/v1/orgs/{org['id']}/modules/{CS}"
    _post(client, token, org_base + "/pain-point-types", {"name": "Regulatory", "definition": "Legal duties."})
    _post(client, token, org_base + "/strategies", {"title": "Org strategy", "objective": "Be great"})
    _post(client, token, org_base + "/future-states", {"title": "Org future", "target_date": "2032-01-01"})
    _post(client, token, org_base + "/guiding-principles", {"name": "Org principle", "principle_statement": "Always"})

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "CS Org Bundle Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    new_org = uuid.UUID(resp.json()["organization"]["id"])

    db = SessionLocal()
    try:
        type_ = db.scalar(select(PainPointTypeDefinition).where(
            PainPointTypeDefinition.organization_id == new_org, PainPointTypeDefinition.name == "Regulatory",
        ))
        assert type_ is not None and type_.definition == "Legal duties."
        strategy = db.scalar(select(Strategy).where(Strategy.organization_id == new_org))
        assert db.scalar(select(StrategyVersion).where(StrategyVersion.strategy_id == strategy.id)).title == "Org strategy"
        future = db.scalar(select(FutureState).where(FutureState.organization_id == new_org))
        assert db.scalar(select(FutureStateVersion).where(FutureStateVersion.future_state_id == future.id)).target_date == date(2032, 1, 1)
        principle = db.scalar(select(GuidingPrinciple).where(GuidingPrinciple.organization_id == new_org))
        assert db.scalar(select(GuidingPrincipleVersion).where(GuidingPrincipleVersion.guiding_principle_id == principle.id)).name == "Org principle"
    finally:
        db.close()
