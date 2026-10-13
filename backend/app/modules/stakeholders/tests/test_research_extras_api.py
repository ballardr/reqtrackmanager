"""Tests for the Phase 4 research extras (docs/plans/module-02-stakeholders-and-
personas-plan.md): session prompts, anonymous participants and findings of an
Engagement, behind the `research_extras` sub-component (off by default).

Covers: the sub-component gate (the engagement log keeps working when it is off,
the extras 404, and their data survives being switched off), prompts (order,
edit, move, delete), anonymous participants (label plus an optional visible
persona), findings (CRUD, project list, raised/answered links) and RBAC.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.models.relationship import ArtefactLink
from app.modules.stakeholders.tests.test_engagement_api import (
    _create,
    _create_open_question,
    _engagements,
)
from app.modules.stakeholders.tests.test_persona_api import (
    MODULE_KEY,
    _add_member,
    _create_project_persona,
    _grant_project_role,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_relationship_api import _create_pain_point
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_project


def _set_extras(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}/subcomponents/research_extras", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _research_setup(client, admin_token, name):
    org, project, token = _setup(client, admin_token, name)
    _set_extras(client, token, org["id"], True)
    return org, project, token


def test_extras_are_off_by_default_and_hide_without_touching_the_log(client, admin_token):
    org, project, token = _setup(client, admin_token, "Research Gate Co")
    h = auth_headers(token)
    pid = project["id"]
    engagement = _create(client, token, pid)
    url = f"{_engagements(pid)}/{engagement['id']}"
    extras = (url + "/prompts", url + "/anonymous-participants", url + "/findings", _project_base(pid) + "/findings")
    for path in extras:
        assert client.get(path, headers=h).status_code == 404, path
    assert client.post(url + "/prompts", json={"prompt": "Why?"}, headers=h).status_code == 404
    assert client.get(url, headers=h).status_code == 200  # the log is unaffected

    _set_extras(client, token, org["id"], True)
    for path in extras:
        assert client.get(path, headers=h).status_code == 200, path
    assert client.post(url + "/prompts", json={"prompt": "Why?"}, headers=h).status_code == 201
    assert client.post(url + "/anonymous-participants", json={"label": "P1"}, headers=h).status_code == 201

    _set_extras(client, token, org["id"], False)
    assert client.get(url + "/prompts", headers=h).status_code == 404
    assert client.get(url, headers=h).json()["anonymous_participant_count"] == 1  # hidden, not deleted
    _set_extras(client, token, org["id"], True)
    assert [p["prompt"] for p in client.get(url + "/prompts", headers=h).json()] == ["Why?"]


def test_prompts_order_edit_move_and_delete(client, admin_token):
    _, project, token = _research_setup(client, admin_token, "Research Prompt Co")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    url = f"{_engagements(project['id'])}/{engagement['id']}/prompts"
    ids = {}
    for text in ("Warm-up", "Main task", "Wrap-up"):
        resp = client.post(url, json={"prompt": text}, headers=h)
        assert resp.status_code == 201, resp.text
        ids[text] = resp.json()["id"]

    def order():
        return [p["prompt"] for p in client.get(url, headers=h).json()]

    assert order() == ["Warm-up", "Main task", "Wrap-up"]
    edited = client.patch(f"{url}/{ids['Main task']}", json={"response_notes": "Struggled with the forms"}, headers=h)
    assert edited.status_code == 200 and edited.json()["response_notes"] == "Struggled with the forms"
    assert edited.json()["prompt"] == "Main task"
    assert client.patch(f"{url}/{ids['Main task']}", json={"prompt": None}, headers=h).status_code == 422
    assert client.patch(f"{url}/{ids['Main task']}", json={"response_notes": None}, headers=h).json()["response_notes"] == ""

    moved = client.post(f"{url}/{ids['Wrap-up']}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200 and [p["prompt"] for p in moved.json()] == ["Warm-up", "Wrap-up", "Main task"]
    client.post(f"{url}/{ids['Warm-up']}/move", json={"direction": "up"}, headers=h)  # already first: a no-op
    assert order() == ["Warm-up", "Wrap-up", "Main task"]
    assert client.post(f"{url}/{ids['Warm-up']}/move", json={"direction": "sideways"}, headers=h).status_code == 422

    assert client.delete(f"{url}/{ids['Wrap-up']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{ids['Wrap-up']}", headers=h).status_code == 404
    assert order() == ["Warm-up", "Main task"]
    other = _create(client, token, project["id"], title="Other")
    other_url = f"{_engagements(project['id'])}/{other['id']}/prompts"
    assert client.patch(f"{other_url}/{ids['Warm-up']}", json={"prompt": "x"}, headers=h).status_code == 404  # not this engagement's


def test_anonymous_participants_label_and_persona(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Research Anonymous Co")
    sibling = create_project(client, token, org["id"], "Research Anonymous Sibling")
    h = auth_headers(token)
    pid = project["id"]
    engagement = _create(client, token, pid, channel="focus_group")
    url = f"{_engagements(pid)}/{engagement['id']}/anonymous-participants"
    persona = _create_project_persona(client, token, pid, name="Field technician")
    foreign = _create_project_persona(client, token, sibling["id"], name="Elsewhere")

    with_persona = client.post(url, json={"label": " Participant 1 ", "persona_id": persona["id"]}, headers=h)
    assert with_persona.status_code == 201, with_persona.text
    assert with_persona.json()["label"] == "Participant 1" and with_persona.json()["persona_name"] == "Field technician"
    bare = client.post(url, json={"label": "Participant 2"}, headers=h).json()
    assert bare["persona_id"] is None and bare["persona_name"] is None
    assert client.post(url, json={"label": ""}, headers=h).status_code == 422
    assert client.post(url, json={"label": "P3", "persona_id": foreign["id"]}, headers=h).status_code == 404

    assigned = client.patch(f"{url}/{bare['id']}", json={"persona_id": persona["id"]}, headers=h).json()
    assert assigned["persona_name"] == "Field technician"
    assert client.patch(f"{url}/{bare['id']}", json={"persona_id": None}, headers=h).json()["persona_id"] is None
    assert client.patch(f"{url}/{bare['id']}", json={"label": None}, headers=h).status_code == 422
    assert client.patch(f"{url}/{bare['id']}", json={"persona_id": foreign["id"]}, headers=h).status_code == 404
    assert client.get(f"{_engagements(pid)}/{engagement['id']}", headers=h).json()["anonymous_participant_count"] == 2
    assert [p["label"] for p in client.get(url, headers=h).json()] == ["Participant 1", "Participant 2"]

    assert client.delete(f"{url}/{bare['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{bare['id']}", headers=h).status_code == 404
    assert len(client.get(url, headers=h).json()) == 1


def test_findings_crud_project_list_and_outcomes(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Research Finding Co")
    sibling = create_project(client, token, org["id"], "Research Finding Sibling")
    h = auth_headers(token)
    pid = project["id"]
    first = _create(client, token, pid, title="Session A")
    second = _create(client, token, pid, title="Session B")
    other_engagement = _create(client, token, sibling["id"], title="Elsewhere")
    pain = _create_pain_point(client, token, org["id"], pid)
    question = _create_open_question(client, token, org["id"], pid)

    created = client.post(
        f"{_engagements(pid)}/{first['id']}/findings", json={"title": "Forms are slow", "description": "3 of 5 said so"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    finding = created.json()
    assert finding["engagement_id"] == first["id"] and finding["project_id"] == pid
    other = client.post(f"{_engagements(pid)}/{second['id']}/findings", json={"title": "Search is fine"}, headers=h).json()
    assert client.post(f"{_engagements(pid)}/{first['id']}/findings", json={"title": ""}, headers=h).status_code == 422
    assert client.post(
        f"{_engagements(sibling['id'])}/{other_engagement['id']}/findings", json={"title": "x"}, headers=h
    ).status_code == 201  # its own project's engagement is fine
    assert client.post(f"{_engagements(pid)}/{other_engagement['id']}/findings", json={"title": "x"}, headers=h).status_code == 404

    assert [f["id"] for f in client.get(f"{_engagements(pid)}/{first['id']}/findings", headers=h).json()] == [finding["id"]]
    assert {f["id"] for f in client.get(_project_base(pid) + "/findings", headers=h).json()} == {finding["id"], other["id"]}
    url = f"{_project_base(pid)}/findings/{finding['id']}"
    updated = client.put(url, json={"description": "4 of 5 said so"}, headers=h)
    assert updated.status_code == 200 and updated.json()["description"] == "4 of 5 said so"
    assert updated.json()["title"] == "Forms are slow"
    assert client.put(url, json={"title": None}, headers=h).status_code == 422
    assert client.get(url, headers=auth_headers(token)).json()["id"] == finding["id"]

    def post(kind, target_type, target_id):
        return client.post(url + "/outcomes", json={"kind": kind, "target_type": target_type, "target_id": target_id}, headers=h)

    assert post("raised", "pain_point", pain["id"]).status_code == 201
    assert post("answered", "open_question", question["id"]).status_code == 201
    assert post("raised", "pain_point", pain["id"]).status_code == 409
    assert post("answered", "pain_point", pain["id"]).status_code == 422
    listed = client.get(url + "/outcomes", headers=h).json()
    assert {(o["kind"], o["target_type"]) for o in listed} == {("raised", "pain_point"), ("answered", "open_question")}
    assert client.delete(f"{url}/outcomes/{listed[0]['link_id']}", headers=h).status_code == 204
    assert len(client.get(url + "/outcomes", headers=h).json()) == 1
    # The finding's links are separate from its engagement's.
    assert client.get(f"{_engagements(pid)}/{first['id']}/outcomes", headers=h).json() == []

    assert client.delete(url, headers=h).status_code == 204
    assert client.get(url, headers=h).status_code == 404
    with SessionLocal() as db:
        links = db.scalars(select(ArtefactLink).where(ArtefactLink.source_id == uuid.UUID(finding["id"]))).all()
        assert links == []
    assert client.get(f"/api/v1/projects/{pid}/modules/context_strategy/pain-points/{pain['id']}", headers=h).status_code == 200


def test_findings_are_404_across_projects(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Research Iso Co")
    sibling = create_project(client, token, org["id"], "Research Iso Sibling")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    finding = client.post(
        f"{_engagements(project['id'])}/{engagement['id']}/findings", json={"title": "Private"}, headers=h
    ).json()
    for suffix in ("", "/outcomes"):
        assert client.get(f"{_project_base(sibling['id'])}/findings/{finding['id']}{suffix}", headers=h).status_code == 404
    assert client.delete(f"{_project_base(sibling['id'])}/findings/{finding['id']}", headers=h).status_code == 404
    assert client.get(_project_base(sibling["id"]) + "/findings", headers=h).json() == []


def test_extras_need_the_engagement_manage_gate_to_change(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Research Rbac Co")
    pid = project["id"]
    engagement = _create(client, token, pid)
    url = f"{_engagements(pid)}/{engagement['id']}"
    finding = client.post(url + "/findings", json={"title": "F"}, headers=auth_headers(token)).json()
    prompt = client.post(url + "/prompts", json={"prompt": "P"}, headers=auth_headers(token)).json()
    _, viewer = _add_member(client, token, org["id"], pid, "viewer@research.example.com")
    owner_id, owner = _add_member(client, token, org["id"], pid, "owner@research.example.com")
    _grant_project_role(client, token, pid, owner_id, "engagement_owner")

    h = auth_headers(viewer)
    assert client.get(url + "/prompts", headers=h).status_code == 200
    assert client.get(url + "/findings", headers=h).status_code == 200
    assert client.post(url + "/prompts", json={"prompt": "x"}, headers=h).status_code == 403
    assert client.patch(f"{url}/prompts/{prompt['id']}", json={"prompt": "x"}, headers=h).status_code == 403
    assert client.post(url + "/anonymous-participants", json={"label": "x"}, headers=h).status_code == 403
    assert client.post(url + "/findings", json={"title": "x"}, headers=h).status_code == 403
    assert client.put(f"{_project_base(pid)}/findings/{finding['id']}", json={"title": "x"}, headers=h).status_code == 403
    assert client.delete(f"{_project_base(pid)}/findings/{finding['id']}", headers=h).status_code == 403
    h = auth_headers(owner)
    assert client.post(url + "/prompts", json={"prompt": "x"}, headers=h).status_code == 201
    assert client.post(url + "/findings", json={"title": "x"}, headers=h).status_code == 201


def test_finding_manage_grant_is_honoured_without_conferring_engagement_management(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Research Fgac Co")
    pid = project["id"]
    engagement = _create(client, token, pid)
    url = f"{_engagements(pid)}/{engagement['id']}"
    user_id, member = _add_member(client, token, org["id"], pid, "finding-editor@research.example.com")
    with SessionLocal() as db:
        role = CustomRoleDefinition(organization_id=uuid.UUID(org["id"]), name="Finding editors", description="T.", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("research_finding", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    h = auth_headers(member)
    created = client.post(url + "/findings", json={"title": "By grant"}, headers=h)
    assert created.status_code == 201, created.text
    finding_url = f"{_project_base(pid)}/findings/{created.json()['id']}"
    assert client.put(finding_url, json={"description": "Edited"}, headers=h).status_code == 200
    assert client.delete(finding_url, headers=h).status_code == 204
    # The finding atom is not engagement management.
    assert client.post(url + "/prompts", json={"prompt": "x"}, headers=h).status_code == 403
    assert client.put(url, json={"summary": "x"}, headers=h).status_code == 403
    assert client.post(_engagements(pid), json={"title": "x", "channel": "call", "engagement_date": "2026-01-01"}, headers=h).status_code == 403
