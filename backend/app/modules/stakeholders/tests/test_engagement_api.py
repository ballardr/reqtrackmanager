"""Tests for the Stakeholders & Personas module's Phase 4 backend API
(docs/plans/module-02-stakeholders-and-personas-plan.md — Engagements), through
the real HTTP endpoints.

Covers: CRUD and validation, the quick log, participants / covered personas /
audience groups (snapshot expansion, hide-aware, group deletion), raised and
answered outcomes, the derived "last engaged", list filters and retention,
RBAC (owner role, FGAC grant, view-only members), module gating (the log needs
only the module), cross-tenant isolation, comments/files, hard-delete
completeness, erasure of a participating Stakeholder, audit contents and
registration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.models.file import FileAsset
from app.models.relationship import ArtefactLink
from app.modules.registry import build_mcp_tool_manifest, get_all_link_type_seeds, get_all_registered_artefact_types, get_module
from app.modules.stakeholders.models import (
    Engagement,
    EngagementAnonymousParticipant,
    EngagementComment,
    EngagementCommentFile,
    EngagementFacilitator,
    EngagementFile,
    EngagementPrompt,
    ResearchFinding,
)
from app.modules.stakeholders.tests.test_persona_api import (
    MODULE_KEY,
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _grant_project_role,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_relationship_api import _create_pain_point
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from app.services.files import get_storage_backend
from app.services.permissions import encode_permission
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
)

TODAY = datetime.now(UTC).date()


def _engagements(project_id) -> str:
    return _project_base(project_id) + "/engagements"


def _payload(**extra) -> dict:
    return {"title": "Kick-off call", "channel": "call", "engagement_date": TODAY.isoformat(), **extra}


def _create(client, token, project_id, **extra) -> dict:
    resp = client.post(_engagements(project_id), json=_payload(**extra), headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _group(client, token, project_id, name, parent=None, **extra) -> dict:
    resp = client.post(
        _project_base(project_id) + "/stakeholder-groups",
        json={"name": name, "parent_group_id": parent, **extra}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_to_group(client, token, project_id, group_id, stakeholder_id) -> None:
    resp = client.post(
        f"{_project_base(project_id)}/stakeholder-groups/{group_id}/members", json={"stakeholder_id": stakeholder_id},
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 201, 204), resp.text


def _create_open_question(client, token, org_id, project_id, question="Which regions first?") -> dict:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/context_strategy", json={"enabled": True}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/context_strategy/open-questions",
        json={"question": question}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_need(client, token, project_id, name="Diagnose faults quickly") -> dict:
    resp = client.post(_project_base(project_id) + "/needs", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _participants(client, token, project_id, engagement_id) -> list[str]:
    resp = client.get(f"{_engagements(project_id)}/{engagement_id}/participants", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [p["name"] for p in resp.json()]


def _stakeholder(client, token, project_id, name) -> dict:
    return _create_project_stakeholder(client, token, project_id, name=name)


def _count(db, model, **where) -> int:
    return db.scalar(select(func.count()).select_from(model).filter_by(**where))


# --- CRUD, validation, retention ---------------------------------------------


def test_engagement_crud_partial_update_and_clearing(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Crud Co")
    h = auth_headers(token)
    other_org, other_token = create_org_admin_in(client, admin_token, "Engagement Crud Other Co")
    outsider = create_org_user(client, other_token, other_org["id"], "outsider@engagement-crud.example.com")
    retain = (TODAY + timedelta(days=30)).isoformat()
    created = _create(
        client, token, project["id"], purpose="Agree scope", summary="Went well", notes="Wants weekly updates",
        consent_recorded=True, retain_until=retain,
    )
    assert created["project_id"] == project["id"] and created["channel"] == "call"
    assert created["consent_recorded"] is True and created["retain_until"] == retain and created["retention_due"] is False
    assert created["participant_count"] == 0 and created["anonymous_participant_count"] == 0
    url = f"{_engagements(project['id'])}/{created['id']}"

    resp = client.put(url, json={"summary": "Revised"}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "Revised" and body["notes"] == "Wants weekly updates" and body["title"] == "Kick-off call"
    assert client.put(url, json={"retain_until": None}, headers=h).json()["retain_until"] is None
    assert client.put(url, json={"notes": None}, headers=h).json()["notes"] == ""

    assert client.put(url, json={"title": None}, headers=h).status_code == 422
    assert client.put(url, json={"channel": None}, headers=h).status_code == 422
    assert client.put(url, json={"engagement_date": None}, headers=h).status_code == 422
    assert client.put(url, json={"channel": "carrier_pigeon"}, headers=h).status_code == 422
    assert client.put(url, json={"facilitators": [{"type": "user", "id": outsider}]}, headers=h).status_code == 400
    assert client.post(_engagements(project["id"]), json=_payload(title=""), headers=h).status_code == 422
    assert client.post(_engagements(project["id"]), json={"title": "x"}, headers=h).status_code == 422

    assert client.get(url, headers=h).json()["id"] == created["id"]
    assert [e["id"] for e in client.get(_engagements(project["id"]), headers=h).json()] == [created["id"]]


def test_facilitators_may_be_several_users_and_groups_and_are_replaced_as_a_list(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Facilitator Co")
    h = auth_headers(token)
    user_id, _member = _add_member(client, token, org["id"], project["id"], "facilitator@engagement.example.com")
    squad = create_project_group(client, token, project["id"], "Research squad")
    guild = create_org_group(client, token, org["id"], "Research guild")
    user = {"type": "user", "id": user_id}
    engagement = _create(client, token, project["id"], facilitators=[user, {"type": "user", "id": user_id}])
    assert [f["id"] for f in engagement["facilitators"]] == [user_id]  # a repeat collapses
    ordered = _create(client, token, project["id"], title="Ordered", facilitators=[{"type": "org_group", "id": guild}, user])
    assert [f["id"] for f in ordered["facilitators"]] == [guild, user_id]  # the order given is kept
    url = f"{_engagements(project['id'])}/{engagement['id']}"
    assert _create(client, token, project["id"], title="Nobody ran it")["facilitators"] == []

    both = client.put(url, json={"facilitators": [user, {"type": "project_group", "id": squad}]}, headers=h)
    assert both.status_code == 200, both.text
    assert [(f["type"], f["label"]) for f in both.json()["facilitators"]][1] == ("project_group", "Research squad")
    assert len(both.json()["facilitators"]) == 2

    # An update that does not mention facilitators leaves them alone; a list replaces them.
    assert len(client.put(url, json={"summary": "x"}, headers=h).json()["facilitators"]) == 2
    swapped = client.put(url, json={"facilitators": [{"type": "org_group", "id": guild}]}, headers=h).json()
    assert [f["id"] for f in swapped["facilitators"]] == [guild]
    assert client.get(url, headers=h).json()["facilitators"][0]["label"] == "Research guild"
    assert [f["id"] for f in client.get(_engagements(project["id"]), headers=h).json() if f["id"] == engagement["id"]]
    assert client.put(url, json={"facilitators": []}, headers=h).json()["facilitators"] == []
    assert client.put(url, json={"facilitators": [user]}, headers=h).json()["facilitators"][0]["id"] == user_id
    assert client.put(url, json={"facilitators": None}, headers=h).json()["facilitators"] == []

    other_org, other_token = create_org_admin_in(client, admin_token, "Engagement Facilitator Other Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign guild")
    assert client.put(url, json={"facilitators": [{"type": "org_group", "id": foreign_group}]}, headers=h).status_code == 400
    assert client.put(url, json={"facilitators": [user, {"type": "org_group", "id": foreign_group}]}, headers=h).status_code == 400
    assert client.get(url, headers=h).json()["facilitators"] == []  # nothing was half-applied


def test_a_facilitating_group_guards_its_deletion_and_is_reassigned_or_dropped_without_duplicates(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Facilitator Group Co")
    h = auth_headers(token)
    user_id, _member = _add_member(client, token, org["id"], project["id"], "lead@engagement-group.example.com")
    squad = create_project_group(client, token, project["id"], "Research squad")
    guild = create_org_group(client, token, org["id"], "Research guild")
    user = {"type": "user", "id": user_id}
    squad_ref, guild_ref = {"type": "project_group", "id": squad}, {"type": "org_group", "id": guild}
    alone = _create(client, token, project["id"], title="Squad only", facilitators=[squad_ref])
    both = _create(client, token, project["id"], title="Squad and guild", facilitators=[squad_ref, guild_ref, user])
    group_url = f"/api/v1/projects/{project['id']}/groups/{squad}"
    assert client.delete(group_url, headers=h).status_code == 409  # a facilitator is in use

    done = client.delete(group_url, params={"replacement_type": "org_group", "replacement_id": guild}, headers=h)
    assert done.status_code == 204, done.text
    moved = client.get(f"{_engagements(project['id'])}/{alone['id']}", headers=h).json()["facilitators"]
    assert [(f["type"], f["id"]) for f in moved] == [("org_group", guild)]
    # The guild already facilitated the second engagement: its squad entry goes, rather than listing the guild twice.
    kept = client.get(f"{_engagements(project['id'])}/{both['id']}", headers=h).json()["facilitators"]
    assert sorted(f["id"] for f in kept) == sorted([guild, user_id])

    # With no replacement, an optional list entry is simply dropped.
    squad_two = create_project_group(client, token, project["id"], "Second squad")
    only = _create(client, token, project["id"], title="Second squad only", facilitators=[{"type": "project_group", "id": squad_two}, user])
    cleared = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{squad_two}", params={"clear_optional": "true"}, headers=h
    )
    assert cleared.status_code == 204, cleared.text
    left = client.get(f"{_engagements(project['id'])}/{only['id']}", headers=h).json()["facilitators"]
    assert [f["id"] for f in left] == [user_id]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(EngagementFacilitator).where(
            EngagementFacilitator.facilitator_id.in_([uuid.UUID(squad), uuid.UUID(squad_two)])
        )) == 0


def test_migration_0088_moves_the_single_facilitator_into_the_list_and_back(client, admin_token):
    """Runs the real 0088 migration both ways: the first-listed facilitator survives a downgrade (the old single
    columns), and an engagement written in that shape comes back with it as a one-entry list."""
    org, project, token = _setup(client, admin_token, "Engagement Migration Co")
    user_id, _member = _add_member(client, token, org["id"], project["id"], "mig@engagement.example.com")
    guild = create_org_group(client, token, org["id"], "Migrating guild")
    two = _create(client, token, project["id"], title="Two", facilitators=[{"type": "user", "id": user_id}, {"type": "org_group", "id": guild}])
    none = _create(client, token, project["id"], title="None")
    command.downgrade(build_alembic_config(), "0087")
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT facilitator_type, facilitator_id FROM engagements WHERE id = :i"), {"i": two["id"]}).one()
            assert (row[0], str(row[1])) == ("user", user_id)
            blank = conn.execute(text("SELECT facilitator_id FROM engagements WHERE id = :i"), {"i": none["id"]}).scalar()
            assert blank is None
            assert conn.execute(text("SELECT to_regclass('engagement_facilitators')")).scalar() is None
    finally:
        command.upgrade(build_alembic_config(), "head")
    with SessionLocal() as db:
        rows = db.scalars(select(EngagementFacilitator).where(EngagementFacilitator.engagement_id == uuid.UUID(two["id"]))).all()
        assert [(r.facilitator_type, str(r.facilitator_id)) for r in rows] == [("user", user_id)]
        assert _count(db, EngagementFacilitator, engagement_id=uuid.UUID(none["id"])) == 0


def test_retention_due_flag_and_filter(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement Retention Co")
    h = auth_headers(token)
    due = _create(client, token, project["id"], title="Old", retain_until=(TODAY - timedelta(days=1)).isoformat())
    on_day = _create(client, token, project["id"], title="Today", retain_until=TODAY.isoformat())
    later = _create(client, token, project["id"], title="Later", retain_until=(TODAY + timedelta(days=5)).isoformat())
    never = _create(client, token, project["id"], title="Never")
    assert (due["retention_due"], on_day["retention_due"], later["retention_due"], never["retention_due"]) == (
        True, True, False, False,
    )
    base = _engagements(project["id"])
    assert {e["id"] for e in client.get(base + "?retention_due=true", headers=h).json()} == {due["id"], on_day["id"]}
    assert {e["id"] for e in client.get(base + "?retention_due=false", headers=h).json()} == {later["id"], never["id"]}


def test_list_filters_and_order(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement Filter Co")
    h = auth_headers(token)
    base = _engagements(project["id"])
    alice, bob = _stakeholder(client, token, project["id"], "Alice"), _stakeholder(client, token, project["id"], "Bob")
    persona = _create_project_persona(client, token, project["id"])
    old = _create(client, token, project["id"], title="Old", channel="email", engagement_date="2026-01-10",
                  stakeholder_ids=[alice["id"]])
    mid = _create(client, token, project["id"], title="Mid", channel="workshop", engagement_date="2026-03-10",
                  stakeholder_ids=[alice["id"], bob["id"]], persona_ids=[persona["id"]])
    new = _create(client, token, project["id"], title="New", channel="email", engagement_date="2026-05-10")

    def ids(query: str) -> list[str]:
        resp = client.get(base + query, headers=h)
        assert resp.status_code == 200, resp.text
        return [e["id"] for e in resp.json()]

    assert ids("") == [new["id"], mid["id"], old["id"]]  # most recent first
    assert ids("?channel=email") == [new["id"], old["id"]]
    assert ids(f"?stakeholder_id={alice['id']}") == [mid["id"], old["id"]]
    assert ids(f"?stakeholder_id={bob['id']}") == [mid["id"]]
    assert ids(f"?persona_id={persona['id']}") == [mid["id"]]
    assert ids("?date_from=2026-02-01&date_to=2026-04-01") == [mid["id"]]
    assert ids(f"?channel=email&stakeholder_id={alice['id']}") == [old["id"]]
    assert client.get(base + "?channel=bogus", headers=h).status_code == 422
    assert client.get(base + f"?stakeholder_id={uuid.uuid4()}", headers=h).status_code == 404
    counts = {e["title"]: e["participant_count"] for e in client.get(base, headers=h).json()}
    assert counts == {"Old": 1, "Mid": 2, "New": 0}


# --- Participants, personas ---------------------------------------------------


def test_quick_log_with_participants_and_covered_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Quick Co")
    h = auth_headers(token)
    own = _stakeholder(client, token, project["id"], "Own Stakeholder")
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared Regulator")
    persona = _create_org_persona(client, token, org["id"], name="Technician")
    created = _create(
        client, token, project["id"], channel="email", stakeholder_ids=[own["id"], shared["id"], own["id"]],
        persona_ids=[persona["id"]],
    )
    assert created["participant_count"] == 2  # a repeated id is added once
    assert sorted(_participants(client, token, project["id"], created["id"])) == ["Own Stakeholder", "Shared Regulator"]
    personas = client.get(f"{_engagements(project['id'])}/{created['id']}/personas", headers=h).json()
    assert [p["name"] for p in personas] == ["Technician"] and personas[0]["scope"] == "organization"

    # A bad reference anywhere fails the whole request before anything is written.
    before = len(client.get(_engagements(project["id"]), headers=h).json())
    resp = client.post(
        _engagements(project["id"]), json=_payload(stakeholder_ids=[own["id"], str(uuid.uuid4())]), headers=h
    )
    assert resp.status_code == 404
    assert len(client.get(_engagements(project["id"]), headers=h).json()) == before


def test_participant_add_remove_duplicate_and_visibility(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Participant Co")
    other_project = create_project(client, token, org["id"], "Engagement Participant Sibling")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    url = f"{_engagements(project['id'])}/{engagement['id']}/participants"
    stakeholder = _stakeholder(client, token, project["id"], "Visible")
    foreign = _create_project_stakeholder(client, token, other_project["id"], name="Sibling-only")
    shared = _create_org_stakeholder(client, token, org["id"], name="Hideable")

    resp = client.post(url, json={"stakeholder_id": stakeholder["id"]}, headers=h)
    assert resp.status_code == 201 and resp.json()["name"] == "Visible" and resp.json()["scope"] == "project"
    assert client.post(url, json={"stakeholder_id": stakeholder["id"]}, headers=h).status_code == 409
    assert client.post(url, json={"stakeholder_id": foreign["id"]}, headers=h).status_code == 404

    assert client.post(url, json={"stakeholder_id": shared["id"]}, headers=h).status_code == 201
    hide = client.put(
        f"{_project_base(project['id'])}/stakeholders/{shared['id']}/visibility", json={"hidden": True}, headers=h
    )
    assert hide.status_code == 200, hide.text
    # Hidden from the project: dropped from the list and the count, and not addable again.
    assert _participants(client, token, project["id"], engagement["id"]) == ["Visible"]
    assert client.get(f"{_engagements(project['id'])}/{engagement['id']}", headers=h).json()["participant_count"] == 1
    assert client.post(url, json={"stakeholder_id": shared["id"]}, headers=h).status_code == 404

    assert client.delete(f"{url}/{stakeholder['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{stakeholder['id']}", headers=h).status_code == 404
    assert _participants(client, token, project["id"], engagement["id"]) == []
    # Only the link went.
    assert client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", headers=h).status_code == 200


def test_covered_personas_add_remove_and_visibility(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Persona Co")
    other_project = create_project(client, token, org["id"], "Engagement Persona Sibling")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    url = f"{_engagements(project['id'])}/{engagement['id']}/personas"
    persona = _create_project_persona(client, token, project["id"])
    foreign = _create_project_persona(client, token, other_project["id"], name="Elsewhere")
    assert client.post(url, json={"persona_id": persona["id"]}, headers=h).status_code == 201
    assert client.post(url, json={"persona_id": persona["id"]}, headers=h).status_code == 409
    assert client.post(url, json={"persona_id": foreign["id"]}, headers=h).status_code == 404
    assert [p["persona_id"] for p in client.get(url, headers=h).json()] == [persona["id"]]
    assert client.delete(f"{url}/{persona['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{persona['id']}", headers=h).status_code == 404
    assert client.get(url, headers=h).json() == []


# --- Audience groups ----------------------------------------------------------


def test_audience_group_expands_to_a_snapshot_of_current_members(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Audience Co")
    h = auth_headers(token)
    pid = project["id"]
    acme = _group(client, token, pid, "Acme")
    finance = _group(client, token, pid, "Acme Finance", parent=acme["id"])
    ann, ben, cat = (_stakeholder(client, token, pid, n) for n in ("Ann", "Ben", "Cat"))
    gone, outsider = _stakeholder(client, token, pid, "Archived"), _stakeholder(client, token, pid, "Outside")
    _add_to_group(client, token, pid, acme["id"], ann["id"])
    _add_to_group(client, token, pid, finance["id"], ben["id"])  # in a child group, so transitively in Acme
    _add_to_group(client, token, pid, acme["id"], gone["id"])
    assert client.post(f"{_project_base(pid)}/stakeholders/{gone['id']}/archive", headers=h).status_code == 200

    engagement = _create(client, token, pid, stakeholder_ids=[ann["id"]])  # Ann is already in
    url = f"{_engagements(pid)}/{engagement['id']}/audiences"
    resp = client.post(url, json={"group_id": acme["id"]}, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["audience"]["name"] == "Acme" and body["audience"]["scope"] == "project"
    assert [p["name"] for p in body["participants_added"]] == ["Ben"] and body["already_participating"] == 1
    assert sorted(_participants(client, token, pid, engagement["id"])) == ["Ann", "Ben"]

    # Later membership changes never alter who the engagement involved.
    _add_to_group(client, token, pid, acme["id"], cat["id"])
    assert client.delete(
        f"{_project_base(pid)}/stakeholder-groups/{acme['id']}/members/{ann['id']}", headers=h
    ).status_code == 204
    assert sorted(_participants(client, token, pid, engagement["id"])) == ["Ann", "Ben"]
    assert outsider["id"] not in {p["stakeholder_id"] for p in client.get(url.replace("audiences", "participants"), headers=h).json()}

    assert client.post(url, json={"group_id": acme["id"]}, headers=h).status_code == 409
    assert client.post(url, json={"group_id": str(uuid.uuid4())}, headers=h).status_code == 404
    assert [a["name"] for a in client.get(url, headers=h).json()] == ["Acme"]

    # Removing the audience keeps the participants it added.
    assert client.delete(f"{url}/{acme['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{acme['id']}", headers=h).status_code == 404
    assert client.get(url, headers=h).json() == []
    assert sorted(_participants(client, token, pid, engagement["id"])) == ["Ann", "Ben"]


def test_audience_skips_hidden_members_and_rejects_other_projects_groups(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Audience Hidden Co")
    sibling = create_project(client, token, org["id"], "Engagement Audience Sibling")
    h = auth_headers(token)
    pid = project["id"]
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared Member")
    own = _create_org_stakeholder(client, token, org["id"], name="Open Member")
    org_group = client.post(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/stakeholder-groups", json={"name": "Everyone"}, headers=h
    ).json()
    org_groups = f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/stakeholder-groups"
    for member in (shared, own):  # an organisation group holds organisation stakeholders only
        resp = client.post(f"{org_groups}/{org_group['id']}/members", json={"stakeholder_id": member["id"]}, headers=h)
        assert resp.status_code in (200, 201, 204), resp.text
    client.put(f"{_project_base(pid)}/stakeholders/{shared['id']}/visibility", json={"hidden": True}, headers=h)
    sibling_group = _group(client, token, sibling["id"], "Sibling group")

    engagement = _create(client, token, pid, group_ids=[org_group["id"]])
    assert _participants(client, token, pid, engagement["id"]) == ["Open Member"]  # the hidden one is not copied
    url = f"{_engagements(pid)}/{engagement['id']}/audiences"
    assert client.post(url, json={"group_id": sibling_group["id"]}, headers=h).status_code == 404
    assert client.post(_engagements(pid), json=_payload(group_ids=[sibling_group["id"]]), headers=h).status_code == 404


def test_deleting_a_group_removes_its_audience_links(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement Group Delete Co")
    h = auth_headers(token)
    pid = project["id"]
    group = _group(client, token, pid, "Short lived")
    engagement = _create(client, token, pid, group_ids=[group["id"]])
    assert client.delete(f"{_project_base(pid)}/stakeholder-groups/{group['id']}", headers=h).status_code == 204
    assert client.get(f"{_engagements(pid)}/{engagement['id']}/audiences", headers=h).json() == []
    with SessionLocal() as db:
        assert _count(db, ArtefactLink, target_id=uuid.UUID(group["id"])) == 0


# --- Last engaged and the timeline -------------------------------------------


def test_last_engaged_is_the_latest_past_engagement_in_this_project_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Last Co")
    other_project = create_project(client, token, org["id"], "Engagement Last Sibling")
    h = auth_headers(token)
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared Contact")
    never = _stakeholder(client, token, project["id"], "Never contacted")
    _create(client, token, project["id"], engagement_date="2026-02-01", stakeholder_ids=[shared["id"]])
    _create(client, token, project["id"], engagement_date="2026-04-15", stakeholder_ids=[shared["id"]])
    future = (TODAY + timedelta(days=10)).isoformat()
    _create(client, token, project["id"], title="Planned", engagement_date=future, stakeholder_ids=[shared["id"]])
    _create(client, token, other_project["id"], engagement_date="2026-09-30", stakeholder_ids=[shared["id"]])

    def last(project_id, stakeholder_id):
        return client.get(f"{_project_base(project_id)}/stakeholders/{stakeholder_id}", headers=h).json()["last_engaged"]

    assert last(project["id"], shared["id"]) == "2026-04-15"  # not the future one, not the sibling's later one
    assert last(other_project["id"], shared["id"]) == "2026-09-30"
    assert last(project["id"], never["id"]) is None
    listed = {s["name"]: s["last_engaged"] for s in client.get(_project_base(project["id"]) + "/stakeholders", headers=h).json()}
    assert listed["Shared Contact"] == "2026-04-15" and listed["Never contacted"] is None
    # The org-scoped view has no project, so no engagement history.
    org_view = client.get(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/stakeholders", headers=h).json()
    assert all(s["last_engaged"] is None for s in org_view)


def test_stakeholder_timeline(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Timeline Co")
    h = auth_headers(token)
    person = _stakeholder(client, token, project["id"], "Timeline Person")
    other = _stakeholder(client, token, project["id"], "Someone else")
    first = _create(client, token, project["id"], title="First", engagement_date="2026-01-05", stakeholder_ids=[person["id"]])
    second = _create(client, token, project["id"], title="Second", channel="meeting", engagement_date="2026-03-05",
                     stakeholder_ids=[person["id"], other["id"]])
    _create(client, token, project["id"], title="Not them", stakeholder_ids=[other["id"]])
    url = f"{_project_base(project['id'])}/stakeholders/{person['id']}/engagements"
    rows = client.get(url, headers=h).json()
    assert [(r["id"], r["channel"]) for r in rows] == [(second["id"], "meeting"), (first["id"], "call")]
    assert set(rows[0]) == {"id", "title", "channel", "engagement_date"}  # no notes in the timeline
    assert client.get(f"{_project_base(project['id'])}/stakeholders/{uuid.uuid4()}/engagements", headers=h).status_code == 404


# --- Raised / answered --------------------------------------------------------


def test_outcome_targets_list_the_projects_records_by_type(client, admin_token):
    """The outcome picker offers the project's own Pain Points, Needs and Open Questions, and nothing else."""
    org, project, token = _setup(client, admin_token, "Engagement Target Co")
    sibling = create_project(client, token, org["id"], "Engagement Target Sibling")
    h = auth_headers(token)
    pid = project["id"]
    pain = _create_pain_point(client, token, org["id"], pid)
    _create_pain_point(client, token, org["id"], sibling["id"], title="Elsewhere")
    question = _create_open_question(client, token, org["id"], pid)
    need = _create_need(client, token, pid)
    url = _project_base(pid) + "/engagement-outcome-targets"

    for target_type, record in (("pain_point", pain), ("stakeholder_need", need), ("open_question", question)):
        resp = client.get(f"{url}?target_type={target_type}", headers=h)
        assert resp.status_code == 200, resp.text
        assert [t["id"] for t in resp.json()] == [record["id"]]  # not the sibling project's Pain Point
    # A type no outcome kind targets is absent, as is an unknown one.
    for bad in ("requirement", "stakeholder", "nonsense"):
        assert client.get(f"{url}?target_type={bad}", headers=h).status_code == 404




def test_outcomes_raised_and_answered(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Outcome Co")
    sibling = create_project(client, token, org["id"], "Engagement Outcome Sibling")
    h = auth_headers(token)
    pid = project["id"]
    pain = _create_pain_point(client, token, org["id"], pid)
    foreign_pain = _create_pain_point(client, token, org["id"], sibling["id"], title="Elsewhere")
    question = _create_open_question(client, token, org["id"], pid)
    need = _create_need(client, token, pid)
    engagement = _create(client, token, pid)
    url = f"{_engagements(pid)}/{engagement['id']}/outcomes"

    def post(kind, target_type, target_id):
        return client.post(url, json={"kind": kind, "target_type": target_type, "target_id": target_id}, headers=h)

    for target_type, target in (("pain_point", pain), ("stakeholder_need", need), ("open_question", question)):
        resp = post("raised", target_type, target["id"])
        assert resp.status_code == 201, resp.text
        assert resp.json()["kind"] == "raised" and resp.json()["target_type"] == target_type
    assert post("answered", "open_question", question["id"]).status_code == 201
    assert post("raised", "pain_point", pain["id"]).status_code == 409  # duplicate
    assert post("answered", "pain_point", pain["id"]).status_code == 422  # only an open question can be answered
    assert post("raised", "requirement", pain["id"]).status_code == 422
    assert post("raised", "pain_point", str(uuid.uuid4())).status_code == 404
    assert post("raised", "pain_point", foreign_pain["id"]).status_code == 404  # another project's record

    listed = client.get(url, headers=h).json()
    assert {(o["kind"], o["target_type"]) for o in listed} == {
        ("raised", "pain_point"), ("raised", "stakeholder_need"), ("raised", "open_question"),
        ("answered", "open_question"),
    }
    answered = next(o for o in listed if o["kind"] == "answered")
    assert client.delete(f"{url}/{answered['link_id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{answered['link_id']}", headers=h).status_code == 404
    assert len(client.get(url, headers=h).json()) == 3
    # The target survives, and sees the engagement through the generic link graph.
    assert client.get(f"/api/v1/projects/{pid}/modules/context_strategy/pain-points/{pain['id']}", headers=h).status_code == 200


# --- RBAC and gating ----------------------------------------------------------


def test_rbac_owner_role_fgac_grant_and_view_only_member(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Rbac Co")
    pid = project["id"]
    engagement = _create(client, token, pid)
    url = f"{_engagements(pid)}/{engagement['id']}"
    viewer_id, viewer = _add_member(client, token, org["id"], pid, "viewer@engagement.example.com")
    owner_id, owner = _add_member(client, token, org["id"], pid, "owner@engagement.example.com")
    fgac_id, fgac = _add_member(client, token, org["id"], pid, "fgac@engagement.example.com")
    wrong_id, wrong_role = _add_member(client, token, org["id"], pid, "wrong@engagement.example.com")
    _grant_project_role(client, token, pid, owner_id, "engagement_owner")
    for role in ("stakeholder_owner", "persona_owner", "stakeholder_need_owner"):
        _grant_project_role(client, token, pid, wrong_id, role)
    with SessionLocal() as db:
        role = CustomRoleDefinition(organization_id=uuid.UUID(org["id"]), name="Engagement editors", description="T.", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("engagement", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(fgac_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()

    for member in (viewer, wrong_role):  # reading and commenting need view only; changing needs the role
        h = auth_headers(member)
        assert client.get(url, headers=h).status_code == 200
        assert client.get(_engagements(pid), headers=h).status_code == 200
        assert client.post(url + "/comments", json={"body": "A thought"}, headers=h).status_code == 201
        assert client.post(_engagements(pid), json=_payload(), headers=h).status_code == 403
        assert client.put(url, json={"summary": "x"}, headers=h).status_code == 403
        assert client.delete(url, headers=h).status_code == 403
        assert client.post(url + "/participants", json={"stakeholder_id": str(uuid.uuid4())}, headers=h).status_code == 403
        assert client.post(url + "/files", files={"file": ("a.txt", b"a", "text/plain")}, headers=h).status_code == 403
    for member in (owner, fgac):
        h = auth_headers(member)
        assert client.post(_engagements(pid), json=_payload(title="By holder"), headers=h).status_code == 201
        assert client.put(url, json={"summary": "Edited"}, headers=h).status_code == 200


def test_the_log_needs_only_the_module_not_the_other_sub_components(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Engagement Gate Co")
    project = create_project(client, token, org["id"], "Engagement Gate Project")
    h = auth_headers(token)
    assert client.get(_engagements(project["id"]), headers=h).status_code == 404  # module off

    enable = client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}", json={"enabled": True}, headers=h)
    assert enable.status_code == 200, enable.text
    for sub in ("persona", "stakeholder", "stakeholder_need"):
        resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/{sub}", json={"enabled": False}, headers=h)
        assert resp.status_code == 200, resp.text
    assert client.post(_engagements(project["id"]), json=_payload(), headers=h).status_code == 201
    assert client.get(_engagements(project["id"]), headers=h).status_code == 200
    # Without the stakeholder sub-component there is nobody to add, but the log itself works.
    assert client.get(_project_base(project["id"]) + "/stakeholders", headers=h).status_code == 404


def test_cross_tenant_and_sibling_engagements_are_404(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Engagement Iso A Co")
    _, project_b, token_b = _setup(client, admin_token, "Engagement Iso B Co")
    sibling = create_project(client, token_a, org_a["id"], "Engagement Iso Sibling")
    engagement = _create(client, token_a, project_a["id"])
    suffixes = ("", "/participants", "/personas", "/audiences", "/outcomes", "/comments", "/files")
    for token, project_id in ((token_b, project_b["id"]), (token_a, sibling["id"])):
        for suffix in suffixes:
            resp = client.get(f"{_engagements(project_id)}/{engagement['id']}{suffix}", headers=auth_headers(token))
            assert resp.status_code == 404, suffix
        h = auth_headers(token)
        assert client.put(f"{_engagements(project_id)}/{engagement['id']}", json={"summary": "x"}, headers=h).status_code == 404
        assert client.delete(f"{_engagements(project_id)}/{engagement['id']}", headers=h).status_code == 404
    assert client.get(f"{_engagements(project_a['id'])}/{engagement['id']}", headers=auth_headers(token_a)).status_code == 200


# --- Comments, files, hard delete --------------------------------------------


def test_comments_and_files(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Files Co")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    url = f"{_engagements(project['id'])}/{engagement['id']}"
    comment = client.post(url + "/comments", json={"body": "Follow up on pricing"}, headers=h)
    assert comment.status_code == 201, comment.text
    comment_id = comment.json()["id"]
    edited = client.patch(f"{url}/comments/{comment_id}", json={"body": "Follow up on rollout"}, headers=h)
    assert edited.status_code == 200 and edited.json()["body"] == "Follow up on rollout" and edited.json()["edited_at"]
    attached = client.post(
        f"{url}/comments/{comment_id}/files", files={"file": ("export.eml", b"mail", "message/rfc822")}, headers=h
    )
    assert attached.status_code == 201, attached.text
    assert client.get(url + "/comments", headers=h).json()[0]["attachments"][0]["id"] == attached.json()["id"]
    direct = client.post(url + "/files", files={"file": ("thread.txt", b"thread", "text/plain")}, headers=h)
    assert direct.status_code == 201, direct.text
    assert [f["id"] for f in client.get(url + "/files", headers=h).json()] == [direct.json()["id"]]
    assert client.delete(f"{url}/comments/{comment_id}/files/{attached.json()['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/files/{direct.json()['id']}", headers=h).status_code == 204
    assert client.get(url + "/files", headers=h).json() == []


def test_files_resolve_to_their_project(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement File Owner Co")
    h = auth_headers(token)
    engagement = _create(client, token, project["id"])
    url = f"{_engagements(project['id'])}/{engagement['id']}"
    direct = client.post(url + "/files", files={"file": ("a.txt", b"a", "text/plain")}, headers=h).json()
    comment = client.post(url + "/comments", json={"body": "c"}, headers=h).json()
    via_comment = client.post(f"{url}/comments/{comment['id']}/files", files={"file": ("b.txt", b"b", "text/plain")}, headers=h).json()
    definition = get_module(MODULE_KEY)
    with SessionLocal() as db:
        for file in (direct, via_comment):
            assert definition.resolve_file_owner_project_id(db, uuid.UUID(file["id"])) == uuid.UUID(project["id"])
        assert definition.resolve_file_owner_project_id(db, uuid.uuid4()) is None


def test_erase_leaves_no_rows_files_links_or_personal_data(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Erase Co")
    h = auth_headers(token)
    pid = project["id"]
    client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/research_extras", json={"enabled": True}, headers=h
    )
    person = _stakeholder(client, token, pid, "Participant Who Must Stay")
    persona = _create_project_persona(client, token, pid)
    group = _group(client, token, pid, "Audience Group")
    group_ref = create_project_group(client, token, pid, "Facilitating Group")
    pain = _create_pain_point(client, token, org["id"], pid)
    victim = _create(client, token, pid, title="Secret Interview With Jane Doe", notes="Jane said something private",
                     stakeholder_ids=[person["id"]], persona_ids=[persona["id"]], group_ids=[group["id"]])
    bystander = _create(client, token, pid, title="Unrelated", stakeholder_ids=[person["id"]])
    eid = victim["id"]
    url = f"{_engagements(pid)}/{eid}"
    assert client.post(url + "/outcomes", json={"kind": "raised", "target_type": "pain_point", "target_id": pain["id"]}, headers=h).status_code == 201
    client.post(url + "/prompts", json={"prompt": "What slows you down?", "response_notes": "Jane: the forms"}, headers=h)
    client.post(url + "/anonymous-participants", json={"label": "Participant 1", "persona_id": persona["id"]}, headers=h)
    finding = client.post(url + "/findings", json={"title": "Forms are slow", "description": "Quote from Jane"}, headers=h).json()
    client.post(
        f"{_project_base(pid)}/findings/{finding['id']}/outcomes",
        json={"kind": "raised", "target_type": "pain_point", "target_id": pain["id"]}, headers=h,
    )
    assert client.put(url, json={"facilitators": [{"type": "project_group", "id": group_ref}]}, headers=h).status_code == 200
    comment = client.post(url + "/comments", json={"body": "private note"}, headers=h).json()
    comment_file = client.post(
        f"{url}/comments/{comment['id']}/files", files={"file": ("jane-letter.txt", b"c", "text/plain")}, headers=h
    ).json()
    direct_file = client.post(url + "/files", files={"file": ("jane-email.txt", b"d", "text/plain")}, headers=h).json()
    with SessionLocal() as db:
        keys = [db.get(FileAsset, uuid.UUID(f["id"])).storage_key for f in (comment_file, direct_file)]
    for key in keys:
        assert get_storage_backend().read(key)
    touched = {uuid.UUID(eid), uuid.UUID(finding["id"])}

    assert client.delete(url, headers=h).status_code == 204
    assert client.get(url, headers=h).status_code == 404
    assert client.delete(url, headers=h).status_code == 404
    assert client.get(f"{_project_base(pid)}/findings/{finding['id']}", headers=h).status_code == 404

    with SessionLocal() as db:
        e = uuid.UUID(eid)
        assert _count(db, Engagement, id=e) == 0
        for model in (
            EngagementComment, EngagementFile, EngagementPrompt, EngagementAnonymousParticipant, ResearchFinding,
            EngagementFacilitator,
        ):
            assert _count(db, model, engagement_id=e) == 0, model.__name__
        assert _count(db, EngagementCommentFile, comment_id=uuid.UUID(comment["id"])) == 0
        for f in (comment_file, direct_file):
            assert _count(db, FileAsset, id=uuid.UUID(f["id"])) == 0
        assert db.scalars(select(ArtefactLink).where(
            ArtefactLink.source_id.in_(touched) | ArtefactLink.target_id.in_(touched)
        )).all() == []
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id.in_([eid, finding["id"]]))).all()
        assert "erased" in {ev.action for ev in events}
        blob = " ".join(f"{ev.action} {ev.detail}" for ev in events).lower()
        for needle in ("secret", "jane", "private", "forms", ".txt", "participant 1"):
            assert needle not in blob, needle
    for key in keys:
        try:
            get_storage_backend().read(key)
        except FileNotFoundError:
            continue
        raise AssertionError("file bytes survived erasure")
    # Everything else survives: the stakeholder, the persona, the group, the pain point and the other engagement.
    assert client.get(f"{_project_base(pid)}/stakeholders/{person['id']}", headers=h).status_code == 200
    assert client.get(f"{_project_base(pid)}/personas/{persona['id']}", headers=h).status_code == 200
    assert client.get(f"{_project_base(pid)}/stakeholder-groups", headers=h).status_code == 200
    assert client.get(f"{_engagements(pid)}/{bystander['id']}", headers=h).json()["participant_count"] == 1
    assert client.get(f"/api/v1/projects/{pid}/modules/context_strategy/pain-points/{pain['id']}", headers=h).status_code == 200


def test_erasing_a_participating_stakeholder_keeps_the_engagement_but_not_the_link(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement Stakeholder Erase Co")
    h = auth_headers(token)
    pid = project["id"]
    leaving, staying = _stakeholder(client, token, pid, "Leaving"), _stakeholder(client, token, pid, "Staying")
    engagement = _create(client, token, pid, stakeholder_ids=[leaving["id"], staying["id"]])
    assert client.delete(f"{_project_base(pid)}/stakeholders/{leaving['id']}", headers=h).status_code == 204
    assert _participants(client, token, pid, engagement["id"]) == ["Staying"]
    assert client.get(f"{_engagements(pid)}/{engagement['id']}", headers=h).json()["participant_count"] == 1
    with SessionLocal() as db:
        assert _count(db, ArtefactLink, target_id=uuid.UUID(leaving["id"])) == 0


# --- Audit and registration ---------------------------------------------------


def test_audit_events_carry_ids_only(client, admin_token):
    _, project, token = _setup(client, admin_token, "Engagement Audit Co")
    h = auth_headers(token)
    person = _stakeholder(client, token, project["id"], "Audited Person")
    engagement = _create(client, token, project["id"], title="Call with Audited Person", notes="Sensitive notes")
    url = f"{_engagements(project['id'])}/{engagement['id']}"
    client.put(url, json={"summary": "Sensitive summary"}, headers=h)
    client.post(url + "/participants", json={"stakeholder_id": person["id"]}, headers=h)
    client.post(url + "/files", files={"file": ("audited-person.txt", b"x", "text/plain")}, headers=h)
    client.delete(f"{url}/participants/{person['id']}", headers=h)
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == engagement["id"])).all()
        assert {"created", "updated", "participant_added", "participant_removed"} <= {e.action for e in events}
        assert all(e.project_id == uuid.UUID(project["id"]) for e in events)
        blob = " ".join(f"{e.action} {e.detail}" for e in events).lower()
        for needle in ("audited", "sensitive", ".txt", "call with"):
            assert needle not in blob, needle


def test_registration():
    definition = get_module(MODULE_KEY)
    assert {"engagement", "research_finding"} <= set(definition.artefact_types)
    assert {"engagement", "research_finding"} <= get_all_registered_artefact_types()
    assert {"engagement", "research_finding"} <= set(definition.artefact_summary_providers)
    assert definition.artefact_type_labels["engagement"] == "Engagement"
    role = next(r for r in definition.roles if r.role_key == "engagement_owner")
    assert role.scope == "project" and role.permissions == (encode_permission("engagement", "manage"),)
    sub = next(s for s in definition.sub_components if s.key == "research_extras")
    assert sub.default_enabled is False
    seeds = get_all_link_type_seeds()
    for forward in ("Has participant", "Covers persona", "Is aimed at", "Raised", "Answered"):
        assert forward in seeds, forward
    assert seeds["Answered"].allowed_target_types == ("open_question",)
    assert set(seeds["Raised"].allowed_source_types) == {"engagement", "research_finding"}
    tools = {t.name for t in build_mcp_tool_manifest()}
    assert {"stakeholders_create_engagement", "stakeholders_list_engagements", "stakeholders_add_engagement_outcome",
            "stakeholders_add_anonymous_participant", "stakeholders_create_research_finding"} <= tools
    assert not {t for t in tools if "delete" in t and ("engagement" in t or "finding" in t)}  # erasure stays human
    reference = next(r for r in definition.principal_references if r.field == "facilitator")
    assert reference.audit_entity_type == "engagement" and reference.multi_valued is True
    assert reference.model is EngagementFacilitator and reference.record_id_field == "engagement_id"


def test_summary_providers_label_and_scope_engagements_and_findings(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Summary Co")
    sibling = create_project(client, token, org["id"], "Engagement Summary Sibling")
    h = auth_headers(token)
    client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/research_extras", json={"enabled": True}, headers=h
    )
    engagement = _create(client, token, project["id"], title="Summary call", channel="workshop")
    finding = client.post(
        f"{_engagements(project['id'])}/{engagement['id']}/findings", json={"title": "A finding"}, headers=h
    ).json()
    providers = get_module(MODULE_KEY).artefact_summary_providers
    with SessionLocal() as db:
        summary = providers["engagement"].get(db, uuid.UUID(engagement["id"]))
        assert summary.label == "Summary call" and summary.facets["channel"] == ("workshop", "Workshop")
        found = providers["research_finding"].get(db, uuid.UUID(finding["id"]))
        assert found.label == "A finding" and found.facets["engagement"] == (engagement["id"], "Summary call")
        for kind, record in (("engagement", engagement), ("research_finding", finding)):
            provider, record_id = providers[kind], uuid.UUID(record["id"])
            assert [s.id for s in provider.list_for_project(db, uuid.UUID(project["id"]))] == [record_id]
            assert provider.list_for_project(db, uuid.UUID(sibling["id"])) == []
            assert provider.get_many_in_project(db, uuid.UUID(sibling["id"]), [record_id]) == []
            assert [s.id for s in provider.get_many_in_project(db, uuid.UUID(project["id"]), [record_id])] == [record_id]
        assert providers["engagement"].get(db, uuid.uuid4()) is None


def test_organisation_deletion_removes_engagements_findings_and_their_links(client, admin_token):
    org, project, token = _setup(client, admin_token, "Engagement Org Delete Co")
    h = auth_headers(token)
    pid = project["id"]
    client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/research_extras", json={"enabled": True}, headers=h
    )
    person = _stakeholder(client, token, pid, "Soon gone")
    group = _group(client, token, pid, "Soon gone group")
    engagement = _create(client, token, pid, stakeholder_ids=[person["id"]], group_ids=[group["id"]])
    url = f"{_engagements(pid)}/{engagement['id']}"
    finding = client.post(url + "/findings", json={"title": "F"}, headers=h).json()
    attached = client.post(url + "/files", files={"file": ("x.txt", b"x", "text/plain")}, headers=h).json()
    ids = {uuid.UUID(engagement["id"]), uuid.UUID(finding["id"])}
    with SessionLocal() as db:
        assert db.scalars(select(ArtefactLink).where(ArtefactLink.source_id.in_(ids))).all()

    resp = client.request("DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    with SessionLocal() as db:
        assert db.scalars(select(ArtefactLink).where(ArtefactLink.source_id.in_(ids) | ArtefactLink.target_id.in_(ids))).all() == []
        assert _count(db, Engagement, id=uuid.UUID(engagement["id"])) == 0
        assert _count(db, ResearchFinding, id=uuid.UUID(finding["id"])) == 0
        assert _count(db, FileAsset, id=uuid.UUID(attached["id"])) == 0
