"""Tests for Decision Management bundle export/import (`export.py`).

A project's own Decision types, Decisions (content, status, decision maker, owner, tags, attachments) and
their links to Requirements and other Decisions survive `GET /projects/{id}/export` + `POST /projects/import`,
and an organisation's Decision templates survive `GET /orgs/{id}/export` + `POST /orgs/import`. A child project
that inherits its parent's Decision types exports its Decisions with the type names. Comments do not travel.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.modules.decisions.models import Decision, DecisionFile, DecisionTemplateDefinition, DecisionTypeDefinition
from app.modules.decisions.service import (
    DecisionDecisionLinkKind,
    DecisionRequirementLinkKind,
    create_decision_decision_link,
    create_decision_requirement_link,
    create_supersession,
)
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

MODULE_KEY = "decisions"


def _base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _post(client, token, url, body, status=201):
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _types(client, token, project_id) -> dict[str, str]:
    resp = client.get(_base(project_id) + "/decision-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {t["name"]: t["id"] for t in resp.json()}


def _import(client, token, org_id, bundle: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _export(client, token, project_id) -> bytes:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def test_project_export_import_round_trips_decisions(client, admin_token):
    org, project, token = _setup(client, admin_token, "Decision Bundle Co")
    h = auth_headers(token)
    base = _base(project["id"])
    me = uuid.UUID(client.get("/api/v1/auth/me", headers=h).json()["id"])
    _post(client, token, base + "/decision-types", {"name": "Regulatory"})
    types = _types(client, token, project["id"])

    first = _post(client, token, base, {
        "title": "Use Postgres", "decision_statement": "We use PostgreSQL.", "decision_type_id": types["Regulatory"],
        "decision_date": "2031-05-06", "context": "Needs ACID.", "rationale": "Known tech.",
        "decision_maker": {"type": "user", "id": str(me)},
    })
    assert client.post(f"{base}/{first['id']}/files", files={"file": ("adr.txt", b"adr", "text/plain")}, headers=h).status_code == 201
    second = _post(client, token, base, {
        "title": "Use Postgres 17", "decision_statement": "Upgrade.", "decision_type_id": types["Architecture"],
    })
    assert client.post(f"{base}/{second['id']}/propose", headers=h).status_code == 200
    dropped = _post(client, token, base, {"title": "Drop it", "decision_statement": "No.", "decision_type_id": types["Design"]})
    assert client.post(f"{base}/{dropped['id']}/archive", headers=h).status_code == 200
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _post(client, token, f"/api/v1/projects/{project['id']}/requirements", {
        "name": "Persistence", "component_id": component_id, "category_id": category_id,
    })
    db = SessionLocal()
    try:
        d1, d2 = db.get(Decision, uuid.UUID(first["id"])), db.get(Decision, uuid.UUID(second["id"]))
        create_decision_requirement_link(
            db, decision=d1, requirement=db.get(Requirement, uuid.UUID(requirement["id"])),
            kind=DecisionRequirementLinkKind.IMPLEMENTS, actor_id=me,
        )
        create_decision_decision_link(
            db, source_decision=d2, target_decision=d1, kind=DecisionDecisionLinkKind.DEPENDS_ON, actor_id=me,
        )
        create_supersession(db, new_decision=d2, old_decision=d1, actor_id=me)
        db.commit()
    finally:
        db.close()

    imported = _import(client, token, org["id"], _export(client, token, project["id"]), "Decision Bundle Reimported")
    assert imported["warnings"] == []
    new_id = uuid.UUID(imported["project"]["id"])

    db = SessionLocal()
    try:
        decisions = {d.title: d for d in db.scalars(select(Decision).where(Decision.project_id == new_id))}
        assert set(decisions) == {"Use Postgres", "Use Postgres 17", "Drop it"}
        one = decisions["Use Postgres"]
        assert one.decision_statement == "We use PostgreSQL." and one.context == "Needs ACID." and one.rationale == "Known tech."
        assert one.decision_date is not None and one.decision_date.isoformat() == "2031-05-06"
        assert one.decision_maker_id == me and one.owner_id == me
        assert db.get(DecisionTypeDefinition, one.decision_type_id).name == "Regulatory"
        assert decisions["Use Postgres 17"].status.value == "proposed"
        assert decisions["Drop it"].is_archived is True
        assert sorted(d.unique_code for d in decisions.values()) == ["DEC-001", "DEC-002", "DEC-003"]  # numbered afresh
        assert db.scalar(select(DecisionFile).where(DecisionFile.decision_id == one.id)) is not None

        ids = [d.id for d in decisions.values()]
        links = db.scalars(select(ArtefactLink).where(ArtefactLink.source_id.in_(ids))).all()
        assert {(lk.source_type, lk.target_type) for lk in links} == {("decision", "requirement"), ("decision", "decision")}
        assert len(links) == 3  # implements, depends on, supersedes
    finally:
        db.close()

    assert set(_types(client, token, new_id)) == set(types)  # the project's own types came across


def test_decision_using_an_inherited_type_gets_that_type_in_the_copy(client, admin_token):
    org, _, token = _setup(client, admin_token, "Decision Inherit Co")
    parent = create_project(client, token, org["id"], "Decision Inherit Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Decision Inherit Child", parent_project_id=parent["id"])
    inherited = _types(client, token, child["id"])  # resolved from the parent: the child has no types of its own
    assert "Architecture" in inherited
    _post(client, token, _base(child["id"]), {
        "title": "Inherited", "decision_statement": "Uses the parent's type.", "decision_type_id": inherited["Architecture"],
    })

    imported = _import(client, token, org["id"], _export(client, token, child["id"]), "Decision Inherit Copy")
    assert imported["warnings"] == []
    new_id = uuid.UUID(imported["project"]["id"])
    db = SessionLocal()
    try:
        decision = db.scalar(select(Decision).where(Decision.project_id == new_id))
        assert db.get(DecisionTypeDefinition, decision.decision_type_id).name == "Architecture"
    finally:
        db.close()


def test_org_export_import_round_trips_decision_templates(client, admin_token):
    org, project, token = _setup(client, admin_token, "Decision Template Bundle Co")
    _post(client, token, f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/templates", {
        "name": "Lightweight ADR", "description": "Short form.", "context_prompt": "What is the context?",
    })
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Decision Template Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    new_org = uuid.UUID(resp.json()["organization"]["id"])
    db = SessionLocal()
    try:
        template = db.scalar(select(DecisionTemplateDefinition).where(
            DecisionTemplateDefinition.organization_id == new_org, DecisionTemplateDefinition.name == "Lightweight ADR",
        ))
        assert template is not None and template.context_prompt == "What is the context?"
    finally:
        db.close()
