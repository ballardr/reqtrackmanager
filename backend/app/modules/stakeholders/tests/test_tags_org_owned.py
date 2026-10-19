"""Tags on organisation-owned records (a persona or stakeholder owned by the organisation, not a
project) use the organisation's vocabulary, and the project list filter finds them."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.tag import ArtefactTag, Tag
from app.modules.stakeholders.tests.test_persona_api import (
    _create_org_persona,
    _create_project_persona,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder
from tests.conftest import auth_headers

PERSONA = "persona"


def _tags_url(project_id: str, persona_id: str) -> str:
    return f"/api/v1/projects/{project_id}/artefacts/{PERSONA}/{persona_id}/tags"


def test_an_org_owned_persona_takes_organisation_tags_not_project_tags(client, admin_token):
    org, project, token = _setup(client, admin_token, "Org Owned Tags Co")
    persona = _create_org_persona(client, token, org["id"])
    resp = client.put(_tags_url(project["id"], persona["id"]), json={"tags": ["Strategic"]}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    db = SessionLocal()
    try:
        tag = db.scalar(select(Tag).where(Tag.organization_id == uuid.UUID(org["id"]), Tag.name == "Strategic"))
        assert tag is not None and tag.project_id is None, "the tag lives in the organisation's vocabulary"
        row = db.scalar(select(ArtefactTag).where(ArtefactTag.artefact_id == uuid.UUID(persona["id"])))
        assert row.project_id is None
    finally:
        db.close()
    # It is not in the project's own vocabulary.
    vocab = client.get(f"/api/v1/projects/{project['id']}/tags", headers=auth_headers(token)).json()
    assert [t["name"] for t in vocab["tags"]] == []
    org_vocab = client.get(f"/api/v1/orgs/{org['id']}/tags", headers=auth_headers(token)).json()
    assert [t["name"] for t in org_vocab["tags"]] == ["Strategic"]


def test_the_organisations_restricted_mode_applies_to_its_own_records(client, admin_token):
    org, project, token = _setup(client, admin_token, "Org Restricted Tags Co")
    persona = _create_org_persona(client, token, org["id"])
    client.put(f"/api/v1/orgs/{org['id']}/tags/settings", json={"mode": "restricted"}, headers=auth_headers(token))
    assert client.put(
        _tags_url(project["id"], persona["id"]), json={"tags": ["nope"]}, headers=auth_headers(token)
    ).status_code == 422
    client.post(f"/api/v1/orgs/{org['id']}/tags", json={"name": "listed"}, headers=auth_headers(token))
    assert client.put(
        _tags_url(project["id"], persona["id"]), json={"tags": ["Listed"]}, headers=auth_headers(token)
    ).status_code == 200
    # The project's own mode is unaffected: a project record can still coin a tag.
    own = _create_project_persona(client, token, project["id"])
    assert client.put(
        _tags_url(project["id"], own["id"]), json={"tags": ["coined"]}, headers=auth_headers(token)
    ).status_code == 200


def test_the_project_persona_list_finds_org_and_project_personas_by_tag(client, admin_token):
    org, project, token = _setup(client, admin_token, "Persona Tag Filter Co")
    org_persona = _create_org_persona(client, token, org["id"], name="Org one")
    own = _create_project_persona(client, token, project["id"], name="Own one")
    _create_project_persona(client, token, project["id"], name="Untagged")
    client.put(_tags_url(project["id"], org_persona["id"]), json={"tags": ["vip"]}, headers=auth_headers(token))
    client.put(_tags_url(project["id"], own["id"]), json={"tags": ["VIP"]}, headers=auth_headers(token))
    listed = client.get(f"{_project_base(project['id'])}/personas", params={"tag": "vip"}, headers=auth_headers(token))
    assert sorted(p["name"] for p in listed.json()) == ["Org one", "Own one"]


def test_the_org_vocabulary_tools_work_and_stay_in_the_organisation(client, admin_token):
    org, project, token = _setup(client, admin_token, "Org Vocabulary Co")
    a = _create_org_persona(client, token, org["id"], name="A")
    b = _create_org_stakeholder(client, token, org["id"], name="B")
    client.put(_tags_url(project["id"], a["id"]), json={"tags": ["x", "y"]}, headers=auth_headers(token))
    client.put(
        f"/api/v1/projects/{project['id']}/artefacts/stakeholder/{b['id']}/tags", json={"tags": ["x"]},
        headers=auth_headers(token),
    )
    base = f"/api/v1/orgs/{org['id']}/tags"
    ids = {t["name"]: t["id"] for t in client.get(base, headers=auth_headers(token)).json()["tags"]}
    usage = client.get(f"{base}/usage", headers=auth_headers(token)).json()
    counts = {t["artefact_type"]: {r["name"]: r["count"] for r in t["rows"]} for t in usage["tables"]}
    assert counts == {"persona": {"x": 1, "y": 1}, "stakeholder": {"x": 1}}
    preview = client.post(f"{base}/reclassify", json={"from_tag_id": ids["x"], "add": [ids["y"]]}, headers=auth_headers(token))
    assert preview.json()["matched"] == 2 and preview.json()["added"] == 1
    merged = client.post(f"{base}/{ids['y']}/merge", json={"into_tag_id": ids["x"]}, headers=auth_headers(token))
    assert merged.status_code == 200
    deleted = client.delete(f"{base}/{ids['x']}", headers=auth_headers(token))
    assert deleted.json()["records_untagged"] == 2
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(ArtefactTag).where(ArtefactTag.artefact_id == uuid.UUID(a["id"]))) == 0
    finally:
        db.close()


def test_a_plain_member_can_read_but_not_change_the_org_vocabulary(client, admin_token):
    from app.modules.stakeholders.tests.test_persona_api import _add_member

    org, project, token = _setup(client, admin_token, "Org Vocabulary Authority Co")
    _, member = _add_member(client, token, org["id"], project["id"], f"m-{uuid.uuid4().hex[:6]}@example.com")
    base = f"/api/v1/orgs/{org['id']}/tags"
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    assert client.post(base, json={"name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.put(f"{base}/settings", json={"mode": "restricted"}, headers=auth_headers(member)).status_code == 403
    assert client.get(f"{base}/usage", headers=auth_headers(member)).status_code == 403
