"""Tests for "Save and activate": `activate: true` on a Persona, Stakeholder or Stakeholder Need create.

Covers: the record is created already `active` (project and organisation scope, and from a user); the
default stays `draft`; both the `created` and `activated` audit events are written by the same actor;
the flag grants nothing (a user who cannot create gets 403 and nothing is stored); and a failure during
activation stores neither the record nor either audit event.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.stakeholders import _need_shared, _shared, _stakeholder_shared
from app.modules.stakeholders.tests.test_need_api import _PAYLOAD as _NEED_PAYLOAD
from app.modules.stakeholders.tests.test_need_api import _needs
from app.modules.stakeholders.tests.test_persona_api import _PAYLOAD as _PERSONA_PAYLOAD
from app.modules.stakeholders.tests.test_persona_api import _add_member, _org_base, _project_base, _setup
from app.modules.stakeholders.tests.test_stakeholder_api import _PAYLOAD as _STAKEHOLDER_PAYLOAD
from tests.conftest import auth_headers, create_org_user


def _events(entity_id: str) -> list[tuple[str, str]]:
    """The (action, actor_id) audit rows of one record, oldest first."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == entity_id).order_by(AuditEvent.created_at)
        ).all()
        return [(e.action, str(e.actor_id)) for e in rows]


def _assert_created_then_activated(record: dict, creator_id: str) -> None:
    assert record["status"] == "active"
    events = _events(record["id"])
    assert [a for a, _ in events] == ["created", "activated"]
    assert {actor for _, actor in events} == {creator_id}


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def test_project_persona_save_and_activate(client, admin_token):
    _, project, token = _setup(client, admin_token, "Save Activate Persona Co")
    h = auth_headers(token)
    url = _project_base(project["id"]) + "/personas"

    draft = client.post(url, json=_PERSONA_PAYLOAD, headers=h).json()
    assert draft["status"] == "draft"

    resp = client.post(url, json={**_PERSONA_PAYLOAD, "activate": True}, headers=h)
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))
    assert resp.json()["version_number"] == 2


def test_org_persona_save_and_activate(client, admin_token):
    org, _, token = _setup(client, admin_token, "Save Activate Org Persona Co")
    resp = client.post(
        _org_base(org["id"]) + "/personas", json={**_PERSONA_PAYLOAD, "activate": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))


def test_project_stakeholder_save_and_activate(client, admin_token):
    _, project, token = _setup(client, admin_token, "Save Activate Stakeholder Co")
    h = auth_headers(token)
    url = _project_base(project["id"]) + "/stakeholders"

    assert client.post(url, json=_STAKEHOLDER_PAYLOAD, headers=h).json()["status"] == "draft"

    resp = client.post(url, json={**_STAKEHOLDER_PAYLOAD, "activate": True}, headers=h)
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))


def test_org_stakeholder_save_and_activate(client, admin_token):
    org, _, token = _setup(client, admin_token, "Save Activate Org Stakeholder Co")
    resp = client.post(
        _org_base(org["id"]) + "/stakeholders", json={**_STAKEHOLDER_PAYLOAD, "activate": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))


def test_stakeholder_from_user_save_and_activate(client, admin_token):
    org, project, token = _setup(client, admin_token, "Save Activate From User Co")
    user_id = create_org_user(client, token, org["id"], "colleague@save-activate.example.com")
    resp = client.post(
        _project_base(project["id"]) + "/stakeholders/from-user", json={"user_id": user_id, "activate": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))


def test_need_save_and_activate(client, admin_token):
    _, project, token = _setup(client, admin_token, "Save Activate Need Co")
    h = auth_headers(token)

    assert client.post(_needs(project["id"]), json=_NEED_PAYLOAD, headers=h).json()["status"] == "draft"

    resp = client.post(_needs(project["id"]), json={**_NEED_PAYLOAD, "activate": True}, headers=h)
    assert resp.status_code == 201, resp.text
    _assert_created_then_activated(resp.json(), _me(client, token))


def test_activate_flag_grants_nothing_to_a_user_who_cannot_create(client, admin_token):
    org, project, token = _setup(client, admin_token, "Save Activate Rbac Co")
    _, member = _add_member(client, token, org["id"], project["id"], "plain@save-activate.example.com")
    h = auth_headers(member)
    base = _project_base(project["id"])

    for url, payload in (
        (base + "/personas", _PERSONA_PAYLOAD),
        (base + "/stakeholders", _STAKEHOLDER_PAYLOAD),
        (_needs(project["id"]), _NEED_PAYLOAD),
    ):
        assert client.post(url, json={**payload, "activate": True}, headers=h).status_code == 403, url
        # Nothing was stored (the owner's own view of the list is still empty).
        assert client.get(url, headers=auth_headers(token)).json() == [], url


@pytest.mark.parametrize(
    ("module", "function", "path", "payload"),
    [
        (_shared, "transition_persona", "/personas", _PERSONA_PAYLOAD),
        (_stakeholder_shared, "transition_stakeholder", "/stakeholders", _STAKEHOLDER_PAYLOAD),
        (_need_shared, "transition_need", "/needs", _NEED_PAYLOAD),
    ],
)
def test_failed_activation_stores_neither_record_nor_events(
    client, admin_token, monkeypatch, module, function, path, payload,
):
    """Create and activate are one transaction: if the activation step fails, no record and no `created` event."""
    _, project, token = _setup(client, admin_token, f"Save Activate Atomic {function} Co")
    h = auth_headers(token)

    def explode(*args, **kwargs):
        raise RuntimeError("activation failed")

    with SessionLocal() as db:
        before = db.scalar(select(AuditEvent.id).order_by(AuditEvent.created_at.desc()).limit(1))

    monkeypatch.setattr(module, function, explode)
    with pytest.raises(RuntimeError):
        client.post(_project_base(project["id"]) + path, json={**payload, "activate": True}, headers=h)
    monkeypatch.undo()

    assert client.get(_project_base(project["id"]) + path, headers=h).json() == []
    with SessionLocal() as db:
        after = db.scalar(select(AuditEvent.id).order_by(AuditEvent.created_at.desc()).limit(1))
        assert after == before
