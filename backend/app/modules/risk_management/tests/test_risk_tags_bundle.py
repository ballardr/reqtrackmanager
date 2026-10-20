"""A Risk keeps its tags through a project bundle."""

from __future__ import annotations

from app.modules.risk_management.tests._helpers import create_risk, project_base, setup
from tests.conftest import auth_headers


def test_a_risk_keeps_its_tags_through_a_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Tags Bundle Co")
    h = auth_headers(token)
    risk = create_risk(client, token, project["id"], title="Tagged risk")
    tagged = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/risk/{risk['id']}/tags", json={"tags": ["Safety-critical", "Q4"]}, headers=h,
    )
    assert tagged.status_code == 200, tagged.text
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Risk Tags Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    copied = client.get(project_base(new_id) + "/risks", headers=h).json()
    assert [r["title"] for r in copied] == ["Tagged risk"]
    got = client.get(f"/api/v1/projects/{new_id}/artefacts/risk/{copied[0]['id']}/tags", headers=h)
    assert sorted(t["name"] for t in got.json()["tags"]) == ["Q4", "Safety-critical"]
