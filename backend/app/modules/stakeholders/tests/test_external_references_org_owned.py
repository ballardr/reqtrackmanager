"""External references on organisation-owned records (a persona or stakeholder owned by the organisation, not a
project) use the organisation's systems, and are removed with the record when it is deleted."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.external_reference import ExternalReference
from app.modules.stakeholders.tests.test_persona_api import _create_org_persona, _setup
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder
from tests.conftest import auth_headers


def _url(project_id: str, artefact_type: str, record_id: str) -> str:
    return f"/api/v1/projects/{project_id}/artefacts/{artefact_type}/{record_id}/external-references"


def test_an_org_owned_persona_takes_references_in_the_organisations_systems(client, admin_token):
    org, project, token = _setup(client, admin_token, "Org Owned Refs Co")
    persona = _create_org_persona(client, token, org["id"])
    h = auth_headers(token)
    seen = client.get(_url(project["id"], "persona", persona["id"]), headers=h).json()
    jira = next(s for s in seen["systems"] if s["name"] == "Jira")
    resp = client.post(
        _url(project["id"], "persona", persona["id"]), json={"system_id": jira["id"], "key": "ORG-1"}, headers=h,
    )
    assert resp.status_code == 201, resp.text
    with SessionLocal() as db:
        row = db.scalars(select(ExternalReference).where(ExternalReference.artefact_id == uuid.UUID(persona["id"]))).one()
        assert row.project_id is None and row.project_system_id is None and str(row.org_system_id) == jira["id"]
        assert str(row.organization_id) == org["id"]


def test_deleting_a_stakeholder_removes_its_references(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Refs Co")
    stakeholder = _create_org_stakeholder(client, token, org["id"])
    h = auth_headers(token)
    systems = client.get(_url(project["id"], "stakeholder", stakeholder["id"]), headers=h).json()["systems"]
    assert client.post(
        _url(project["id"], "stakeholder", stakeholder["id"]), json={"system_id": systems[0]["id"], "key": "S-1"}, headers=h,
    ).status_code == 201
    deleted = client.delete(f"/api/v1/orgs/{org['id']}/modules/stakeholders/stakeholders/{stakeholder['id']}", headers=h)
    assert deleted.status_code == 204, deleted.text
    with SessionLocal() as db:
        assert db.scalar(select(ExternalReference.id).where(ExternalReference.artefact_id == uuid.UUID(stakeholder["id"]))) is None
