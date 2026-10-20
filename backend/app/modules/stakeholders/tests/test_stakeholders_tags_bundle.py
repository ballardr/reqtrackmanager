"""Tags travel in a project bundle with every Stakeholders & Personas record that has them (persona,
stakeholder, need, engagement and research finding): the new project's records carry the same tag
names, restored even when the new project is restricted to a tag list."""

from __future__ import annotations

import uuid

from app.modules.stakeholders.tests.test_engagement_api import _create as _create_engagement
from app.modules.stakeholders.tests.test_need_api import _create_need
from app.modules.stakeholders.tests.test_persona_api import _create_project_persona, _setup
from app.modules.stakeholders.tests.test_research_extras_api import _set_extras
from app.modules.stakeholders.tests.test_stakeholder_api import _create_project_stakeholder
from tests.conftest import auth_headers


def _tag(client, token, project_id, artefact_type, artefact_id, names) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/tags", json={"tags": names},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _tags_of(client, token, project_id, artefact_type, artefact_id) -> list[str]:
    resp = client.get(
        f"/api/v1/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/tags", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return sorted(t["name"] for t in resp.json()["tags"])


def test_every_record_kind_keeps_its_tags_through_a_project_bundle(client, admin_token):
    org, project, token = _setup(client, admin_token, "Tags Bundle Co")
    h = auth_headers(token)
    _set_extras(client, token, org["id"], True)
    pid = project["id"]
    persona = _create_project_persona(client, token, pid, name="Persona A")
    stakeholder = _create_project_stakeholder(client, token, pid, name="Stakeholder A")
    need = _create_need(client, token, pid, name="Need A")
    engagement = _create_engagement(client, token, pid, title="Engagement A")
    finding = client.post(
        f"/api/v1/projects/{pid}/modules/stakeholders/engagements/{engagement['id']}/findings",
        json={"title": "Finding A"}, headers=h,
    )
    assert finding.status_code == 201, finding.text
    records = {
        "persona": persona["id"], "stakeholder": stakeholder["id"], "stakeholder_need": need["id"],
        "engagement": engagement["id"], "research_finding": finding.json()["id"],
    }
    for artefact_type, artefact_id in records.items():
        _tag(client, token, pid, artefact_type, artefact_id, [f"{artefact_type} tag", "shared"])
    client.put(f"/api/v1/projects/{pid}/tag-settings", json={"mode": "restricted"}, headers=h)

    export = client.get(f"/api/v1/projects/{pid}/export", headers=h)
    assert export.status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Tags Bundle Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    base = f"/api/v1/projects/{new_id}/modules/stakeholders"
    def listed(segment: str, key: str, value: str, project_scoped: bool = False) -> str:
        rows = client.get(f"{base}/{segment}", headers=h).json()
        return next(r["id"] for r in rows if r[key] == value and (not project_scoped or r["project_id"] == new_id))

    new_ids = {
        "persona": listed("personas", "name", "Persona A", True),
        "stakeholder": listed("stakeholders", "name", "Stakeholder A", True),
        "stakeholder_need": listed("needs", "name", "Need A"),
        "engagement": listed("engagements", "title", "Engagement A"),
        "research_finding": listed("findings", "title", "Finding A"),
    }
    for artefact_type, artefact_id in new_ids.items():
        assert artefact_id != records[artefact_type]
        assert _tags_of(client, token, new_id, artefact_type, artefact_id) == sorted([f"{artefact_type} tag", "shared"]), artefact_type
    assert uuid.UUID(new_id)
