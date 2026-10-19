"""Hide and restore of organisation defaults in one project, for every typed
vocabulary that has an organisation tier (Pain Point, Persona, Stakeholder and
Risk types): "delete" on an organisation default hides it in that project only,
the hidden list and restore bring it back, existing records keep the type, and a
project-local type still deletes for real."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.definition_suppression import ProjectDefinitionSuppression
from app.services import definition_suppression
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

# (module key, URL segment, project-type audit entity)
FAMILIES = [
    pytest.param("context_strategy", "pain-point-types", "project_pain_point_type", id="pain_point"),
    pytest.param("stakeholders", "persona-types", "project_persona_type", id="persona"),
    pytest.param("stakeholders", "stakeholder-types", "project_stakeholder_type", id="stakeholder"),
    pytest.param("risk_management", "risk-types", "project_risk_type", id="risk"),
]


def _world(client, admin_token, module_key: str, name: str):
    """An org with a real admin, the module enabled, and two projects."""
    org, token = create_org_admin_in(client, admin_token, name)
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    first = create_project(client, token, org["id"], f"{name} One")
    second = create_project(client, token, org["id"], f"{name} Two")
    return org, first, second, token


def _base(project_id, module_key: str, segment: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/{module_key}/{segment}"


def _names(client, token, url: str) -> list[str]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [t["name"] for t in resp.json()]


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_delete_hides_an_org_default_in_one_project_and_restore_brings_it_back(
    client, admin_token, module_key, segment, entity,
):
    org, one, two, token = _world(client, admin_token, module_key, f"Hide {segment}")
    url = _base(one["id"], module_key, segment)
    rows = client.get(url, headers=auth_headers(token)).json()
    target, other = rows[0], rows[1]
    assert target["source"] == "org"

    resp = client.delete(f"{url}/{target['id']}", headers=auth_headers(token))
    assert resp.status_code == 204, resp.text

    assert target["name"] not in _names(client, token, url)
    assert other["name"] in _names(client, token, url)
    # Another project of the same organisation still sees it.
    assert target["name"] in _names(client, token, _base(two["id"], module_key, segment))

    hidden = client.get(f"{url}/hidden", headers=auth_headers(token)).json()
    assert [h["name"] for h in hidden] == [target["name"]]

    restored = client.post(f"{url}/restore", json={}, headers=auth_headers(token))
    assert restored.status_code == 200, restored.text
    assert [r["name"] for r in restored.json()["restored"]] == [target["name"]]
    assert target["name"] in _names(client, token, url)
    assert client.get(f"{url}/hidden", headers=auth_headers(token)).json() == []

    with SessionLocal() as db:
        actions = {
            e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == entity, AuditEvent.project_id == one["id"]))
        }
    assert {"hidden", "restored"} <= actions


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_restore_can_bring_back_a_chosen_subset(client, admin_token, module_key, segment, entity):
    org, one, _two, token = _world(client, admin_token, module_key, f"Subset {segment}")
    url = _base(one["id"], module_key, segment)
    rows = client.get(url, headers=auth_headers(token)).json()
    first, second = rows[0], rows[1]
    for row in (first, second):
        assert client.delete(f"{url}/{row['id']}", headers=auth_headers(token)).status_code == 204

    hidden = {h["name"]: h["id"] for h in client.get(f"{url}/hidden", headers=auth_headers(token)).json()}
    assert set(hidden) == {first["name"], second["name"]}

    resp = client.post(f"{url}/restore", json={"org_type_ids": [hidden[second["name"]]]}, headers=auth_headers(token))
    assert [r["name"] for r in resp.json()["restored"]] == [second["name"]]
    assert second["name"] in _names(client, token, url)
    assert first["name"] not in _names(client, token, url)


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_hiding_an_overridden_default_keeps_the_override_and_a_hidden_default_cannot_be_newly_chosen(
    client, admin_token, module_key, segment, entity,
):
    org, one, _two, token = _world(client, admin_token, module_key, f"Override {segment}")
    url = _base(one["id"], module_key, segment)
    target = client.get(url, headers=auth_headers(token)).json()[0]

    renamed = client.put(f"{url}/{target['id']}", json={"name": "Renamed here"}, headers=auth_headers(token))
    assert renamed.status_code == 200, renamed.text
    override_id = renamed.json()["id"]

    assert client.delete(f"{url}/{override_id}", headers=auth_headers(token)).status_code == 204
    assert "Renamed here" not in _names(client, token, url)

    # The override row survives, so records pointing at it are unaffected; restoring shows the rename again.
    assert client.post(f"{url}/restore", json={}, headers=auth_headers(token)).status_code == 200
    assert "Renamed here" in _names(client, token, url)


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_hidden_default_with_no_row_cannot_be_overridden_or_newly_chosen(client, admin_token, module_key, segment, entity):
    org, one, _two, token = _world(client, admin_token, module_key, f"Chosen {segment}")
    url = _base(one["id"], module_key, segment)
    target = client.get(url, headers=auth_headers(token)).json()[0]
    assert client.delete(f"{url}/{target['id']}", headers=auth_headers(token)).status_code == 204

    resp = client.put(f"{url}/{target['id']}", json={"is_enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 400, resp.text
    assert "hidden" in resp.json()["detail"].lower()


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_project_local_type_is_still_deleted_not_hidden(client, admin_token, module_key, segment, entity):
    org, one, _two, token = _world(client, admin_token, module_key, f"Local {segment}")
    url = _base(one["id"], module_key, segment)
    local = client.post(url, json={"name": "Only here"}, headers=auth_headers(token)).json()

    assert client.delete(f"{url}/{local['id']}", headers=auth_headers(token)).status_code == 204
    assert client.get(f"{url}/hidden", headers=auth_headers(token)).json() == []
    with SessionLocal() as db:
        assert db.scalar(select(ProjectDefinitionSuppression).where(ProjectDefinitionSuppression.project_id == one["id"])) is None


@pytest.mark.parametrize(("module_key", "segment", "entity"), FAMILIES)
def test_unknown_type_is_404_and_a_plain_member_cannot_hide_list_or_restore(client, admin_token, module_key, segment, entity):
    org, one, _two, token = _world(client, admin_token, module_key, f"Gate {segment}")
    url = _base(one["id"], module_key, segment)
    target = client.get(url, headers=auth_headers(token)).json()[0]

    missing = client.delete(f"{url}/00000000-0000-0000-0000-000000000000", headers=auth_headers(token))
    assert missing.status_code == 404, missing.text

    email = f"member-{segment}@example.com"
    user_id = create_org_user(client, token, org["id"], email)
    assert client.post(
        f"/api/v1/projects/{one['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token),
    ).status_code == 204
    member = login(client, email, "Password123!")
    assert client.delete(f"{url}/{target['id']}", headers=auth_headers(member)).status_code == 403
    assert client.get(f"{url}/hidden", headers=auth_headers(member)).status_code == 403
    assert client.post(f"{url}/restore", json={}, headers=auth_headers(member)).status_code == 403


def test_another_organisations_type_cannot_be_hidden(client, admin_token):
    _org_a, one, _two, token_a = _world(client, admin_token, "stakeholders", "Isolation A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Isolation B")
    client.put(f"/api/v1/orgs/{org_b['id']}/modules/stakeholders", json={"enabled": True}, headers=auth_headers(token_b))
    foreign = client.get(
        f"/api/v1/orgs/{org_b['id']}/modules/stakeholders/persona-types", headers=auth_headers(token_b),
    ).json()[0]

    url = _base(one["id"], "stakeholders", "persona-types")
    assert client.delete(f"{url}/{foreign['id']}", headers=auth_headers(token_a)).status_code == 404
    assert client.get(f"{url}/hidden", headers=auth_headers(token_a)).json() == []


def test_deleting_an_org_type_removes_the_tombstones_pointing_at_it(client, admin_token):
    org, one, _two, token = _world(client, admin_token, "stakeholders", "Forget")
    org_url = f"/api/v1/orgs/{org['id']}/modules/stakeholders/persona-types"
    created = client.post(org_url, json={"name": "Short lived"}, headers=auth_headers(token)).json()
    url = _base(one["id"], "stakeholders", "persona-types")
    assert client.delete(f"{url}/{created['id']}", headers=auth_headers(token)).status_code == 204

    assert client.delete(f"{org_url}/{created['id']}", headers=auth_headers(token)).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(
            select(ProjectDefinitionSuppression).where(ProjectDefinitionSuppression.org_definition_id == created["id"])
        ) is None


def test_hide_and_restore_reject_an_unregistered_kind():
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            definition_suppression.hide_definition(db, uuid.uuid4(), "no_such_kind", uuid.uuid4())
        with pytest.raises(ValueError):
            definition_suppression.restore_definitions(db, uuid.uuid4(), "no_such_kind")
    assert {"pain_point_type", "persona_type", "stakeholder_type", "risk_type"} <= definition_suppression.get_registered_definition_kinds()


@pytest.mark.parametrize(
    ("module_key", "segment"),
    [
        pytest.param("stakeholders", "persona-types", id="persona"),
        pytest.param("stakeholders", "stakeholder-types", id="stakeholder"),
        pytest.param("risk_management", "risk-types", id="risk"),
    ],
)
def test_hidden_defaults_travel_with_a_project_bundle(client, admin_token, module_key, segment):
    org, one, _two, token = _world(client, admin_token, module_key, f"Bundle {segment}")
    url = _base(one["id"], module_key, segment)
    target = client.get(url, headers=auth_headers(token)).json()[0]
    assert client.delete(f"{url}/{target['id']}", headers=auth_headers(token)).status_code == 204

    exported = client.get(f"/api/v1/projects/{one['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": f"Imported {segment}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []

    copy_url = _base(imported.json()["project"]["id"], module_key, segment)
    assert target["name"] not in _names(client, token, copy_url)
    assert [h["name"] for h in client.get(f"{copy_url}/hidden", headers=auth_headers(token)).json()] == [target["name"]]
