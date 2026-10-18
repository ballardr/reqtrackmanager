"""Tests for Engagement bundle export/import (`engagement_export.py`): a project's
engagements, their participants, covered personas, audience groups, raised and
answered links, research extras and attachments survive `GET /projects/{id}/export`
+ `POST /projects/import`; a participant or target the destination lacks is
skipped with a warning."""

from __future__ import annotations

import io
import json
import zipfile

from app.modules.stakeholders.tests.test_engagement_api import (
    _create,
    _create_need,
    _create_open_question,
    _engagements,
    _group,
    _participants,
)
from app.modules.stakeholders.tests.test_persona_api import MODULE_KEY, _add_member, _create_org_persona, _setup
from app.modules.stakeholders.tests.test_relationship_api import _create_pain_point
from app.modules.stakeholders.tests.test_stakeholder_api import _create_project_stakeholder
from tests.conftest import auth_headers, create_org_group


def test_project_export_import_round_trips_engagements(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Bundle Co")
    h = auth_headers(token)
    pid = project["id"]
    client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/research_extras", json={"enabled": True}, headers=h)
    persona = _create_org_persona(client, token, org["id"], name="Shared persona")
    person = _create_project_stakeholder(client, token, pid, name="Interviewed Person")
    group = _group(client, token, pid, "Acme")
    pain = _create_pain_point(client, token, org["id"], pid, title="Round trip pain")
    question = _create_open_question(client, token, org["id"], pid, question="Round trip question?")
    need = _create_need(client, token, pid, name="Round trip need")
    lead_id, _member = _add_member(client, token, org["id"], pid, "lead@engagement-bundle.example.com")
    guild = create_org_group(client, token, org["id"], "Research guild")
    engagement = _create(
        client, token, pid, title="Round trip interview", channel="interview", engagement_date="2026-03-02",
        purpose="Learn", summary="Learned", notes="Notes here", consent_recorded=True, retain_until="2027-03-02",
        stakeholder_ids=[person["id"]], persona_ids=[persona["id"]], group_ids=[group["id"]],
        facilitators=[{"type": "user", "id": lead_id}, {"type": "org_group", "id": guild}],
    )
    url = f"{_engagements(pid)}/{engagement['id']}"
    for kind, target_type, target in (
        ("raised", "pain_point", pain), ("raised", "stakeholder_need", need), ("answered", "open_question", question),
    ):
        body = {"kind": kind, "target_type": target_type, "target_id": target["id"]}
        assert client.post(url + "/outcomes", json=body, headers=h).status_code == 201
    client.post(url + "/prompts", json={"prompt": "What slows you down?", "response_notes": "Forms"}, headers=h)
    client.post(url + "/prompts", json={"prompt": "Anything else?"}, headers=h)
    client.post(url + "/anonymous-participants", json={"label": "Participant 1", "persona_id": persona["id"]}, headers=h)
    finding = client.post(url + "/findings", json={"title": "Forms are slow", "description": "d"}, headers=h).json()
    client.post(
        f"/api/v1/projects/{pid}/modules/{MODULE_KEY}/findings/{finding['id']}/outcomes",
        json={"kind": "raised", "target_type": "pain_point", "target_id": pain["id"]}, headers=h,
    )
    client.post(url + "/files", files={"file": ("export.eml", b"mail", "message/rfc822")}, headers=h)

    export = client.get(f"/api/v1/projects/{pid}/export", headers=h)
    assert export.status_code == 200
    exported = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert [e["title"] for e in exported["project_engagements"]] == ["Round trip interview"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Engagement Bundle Reimported"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    # Pain Points and Open Questions are Context & Strategy's records and do not travel in a project bundle yet,
    # so links to them are skipped with a warning (as the Stakeholder relationships are); a Need travels.
    warnings = imported.json()["warnings"]
    assert len(warnings) == 3 and all("not found or ambiguous" in w for w in warnings), warnings
    assert sum("pain_point 'Round trip pain'" in w for w in warnings) == 2
    assert sum("open_question 'Round trip question?'" in w for w in warnings) == 1
    new_id = imported.json()["project"]["id"]

    engagements = client.get(_engagements(new_id), headers=h).json()
    assert len(engagements) == 1
    copy = engagements[0]
    assert (copy["title"], copy["channel"], copy["engagement_date"], copy["retain_until"]) == (
        "Round trip interview", "interview", "2026-03-02", "2027-03-02",
    )
    assert copy["consent_recorded"] is True and copy["notes"] == "Notes here" and copy["purpose"] == "Learn"
    assert copy["anonymous_participant_count"] == 1
    assert sorted((f["type"], f["id"]) for f in copy["facilitators"]) == sorted([("user", lead_id), ("org_group", guild)])
    new_url = f"{_engagements(new_id)}/{copy['id']}"
    # The new project has its own copy of the project-scoped stakeholder, group and records.
    assert _participants(client, token, new_id, copy["id"]) == ["Interviewed Person"]
    assert [p["name"] for p in client.get(new_url + "/personas", headers=h).json()] == ["Shared persona"]
    assert [a["name"] for a in client.get(new_url + "/audiences", headers=h).json()] == ["Acme"]
    outcomes = client.get(new_url + "/outcomes", headers=h).json()
    assert [(o["kind"], o["target_type"], o["label"]) for o in outcomes] == [("raised", "stakeholder_need", "NEED-001 Round trip need")]
    prompts = client.get(new_url + "/prompts", headers=h).json()
    assert [(p["prompt"], p["response_notes"]) for p in prompts] == [("What slows you down?", "Forms"), ("Anything else?", "")]
    anonymous = client.get(new_url + "/anonymous-participants", headers=h).json()
    assert [(a["label"], a["persona_name"]) for a in anonymous] == [("Participant 1", "Shared persona")]
    findings = client.get(new_url + "/findings", headers=h).json()
    assert [f["title"] for f in findings] == ["Forms are slow"]
    finding_outcomes = client.get(
        f"/api/v1/projects/{new_id}/modules/{MODULE_KEY}/findings/{findings[0]['id']}/outcomes", headers=h
    ).json()
    assert finding_outcomes == []  # its only link was to a Pain Point, which did not travel
    assert [f["filename"] for f in client.get(new_url + "/files", headers=h).json()] == ["export.eml"]


def test_import_into_org_lacking_a_reference_warns_and_skips(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Bundle Warn Co")
    h = auth_headers(token)
    persona = _create_org_persona(client, token, org["id"], name="Only here")
    _create(client, token, project["id"], title="Needs a persona", persona_ids=[persona["id"]])
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)

    other, _, other_token = _setup(client, admin_token, "Engagement Bundle Warn Target Co")
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Engagement Warn Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert imported.status_code == 201, imported.text
    assert any("persona 'Only here' not found" in w for w in imported.json()["warnings"])
    new_id = imported.json()["project"]["id"]
    assert len(client.get(_engagements(new_id), headers=auth_headers(other_token)).json()) == 1
