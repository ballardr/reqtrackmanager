"""Tests for groups as Pain Point, Guiding Principle and Open Question owners
(users and groups on parity, Phase 4 — docs/plans/users-and-groups-parity-plan.md).

Covers: each principal kind on create/update/clear and the display fields of a
group; Guiding Principle versions carrying the owner so history shows who owned
each version; validation (a foreign organisation's group or user, another
project's group, a project group on an organisation-scoped Guiding Principle);
deleting a group that owns records (usage counts, blocked, reassigned, cleared,
the audit event names the principle not its version row, older versions keep a
deleted group); the Open Question register and Guiding Principle usage report
printing and grouping by owner principal; and the migration backfilling
existing rows to `user`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.modules.context_strategy.models import OpenQuestion
from app.modules.context_strategy.tests.test_context_strategy_guiding_principle_api import (
    _PAYLOAD as _GP_PAYLOAD,
)
from app.modules.context_strategy.tests.test_context_strategy_guiding_principle_api import (
    _create_org_guiding_principle,
    _create_project_guiding_principle,
)
from app.modules.context_strategy.tests.test_context_strategy_guiding_principle_api import _org_base as _gp_org_base
from app.modules.context_strategy.tests.test_context_strategy_open_question_api import _PAYLOAD_FIELDS as _OQ_PAYLOAD
from app.modules.context_strategy.tests.test_context_strategy_open_question_api import (
    _create_open_question,
    _project_base,
    _setup,
)
from app.modules.context_strategy.tests.test_context_strategy_pain_point_api import _PAYLOAD_FIELDS as _PP_PAYLOAD
from app.modules.context_strategy.tests.test_context_strategy_pain_point_api import _create_pain_point
from tests.conftest import auth_headers, build_alembic_config, create_org_admin_in, create_org_user, create_project


def _user(user_id) -> dict:
    return {"type": "user", "id": str(user_id)}


def _org_group(client, token, org_id, name, *, users=()) -> str:
    h = auth_headers(token)
    resp = client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=h)
    assert resp.status_code in (200, 201), resp.text
    gid = resp.json()["id"]
    for user_id in users:
        r = client.post(f"/api/v1/orgs/{org_id}/groups/{gid}/members", json={"user_id": str(user_id)}, headers=h)
        assert r.status_code == 204, r.text
    return gid


def _project_group(client, token, project_id, name, *, users=()) -> str:
    h = auth_headers(token)
    resp = client.post(f"/api/v1/projects/{project_id}/groups", json={"name": name}, headers=h)
    assert resp.status_code in (200, 201), resp.text
    gid = resp.json()["id"]
    for user_id in users:
        r = client.post(f"/api/v1/projects/{project_id}/groups/{gid}/members", json={"user_id": str(user_id)}, headers=h)
        assert r.status_code == 204, r.text
    return gid


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def _update_pain_point(client, token, project_id, pain_point, **extra):
    """PUT a Pain Point as a full replace of its own current content plus `extra`."""
    payload = {
        **_PP_PAYLOAD, "pain_point_type_id": pain_point["pain_point_type_id"], "title": pain_point["title"], **extra,
    }
    return client.put(f"{_project_base(project_id)}/pain-points/{pain_point['id']}", json=payload, headers=auth_headers(token))


def _update_open_question(client, token, project_id, open_question_id, **extra):
    return client.put(
        f"{_project_base(project_id)}/open-questions/{open_question_id}", json={**_OQ_PAYLOAD, **extra},
        headers=auth_headers(token),
    )


# --- Create, update, clear: each principal kind --------------------------------------------------------


def test_each_artefact_takes_each_principal_kind_and_shows_a_group_by_name(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Kinds Co")
    member = create_org_user(client, token, org["id"], "cs_kinds_member@sp.example.com")
    team = _org_group(client, token, org["id"], "Platform Team", users=[member])
    squad = _project_group(client, token, project["id"], "Squad", users=[member])
    h = auth_headers(token)

    pain_point = _create_pain_point(client, token, project["id"])
    assert pain_point["owner"] is None
    updated = _update_pain_point(client, token, project["id"], pain_point, owner={"type": "org_group", "id": team})
    assert updated.status_code == 200, updated.text
    assert updated.json()["owner"] == {
        "type": "org_group", "id": team, "label": "Platform Team", "member_count": 1, "exists": True,
    }
    second_pp = _create_pain_point(client, token, project["id"], title="Second")
    _update_pain_point(client, token, project["id"], second_pp, owner={"type": "project_group", "id": squad})

    principle = _create_project_guiding_principle(client, token, project["id"], owner={"type": "project_group", "id": squad})
    assert principle["owner"]["label"] == "Squad" and principle["owner"]["type"] == "project_group"
    by_user = _create_project_guiding_principle(client, token, project["id"], name="By user", owner=_user(member))
    assert by_user["owner"]["type"] == "user" and by_user["owner"]["id"] == member

    question = _create_open_question(client, token, project["id"])
    assert question["owner"] is None
    assigned = _update_open_question(client, token, project["id"], question["id"], owner={"type": "org_group", "id": team})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["owner"]["label"] == "Platform Team"

    listed_pp = {p["id"]: p for p in client.get(_project_base(project["id"]) + "/pain-points", headers=h).json()}
    assert listed_pp[pain_point["id"]]["owner"]["label"] == "Platform Team"
    assert listed_pp[second_pp["id"]]["owner"]["label"] == "Squad"
    listed_gp = {p["id"]: p for p in client.get(_project_base(project["id"]) + "/guiding-principles", headers=h).json()}
    assert listed_gp[principle["id"]]["owner"]["label"] == "Squad"
    assert listed_gp[by_user["id"]]["owner"]["id"] == member
    assert client.get(_project_base(project["id"]) + "/open-questions", headers=h).json()[0]["owner"]["label"] == "Platform Team"


def test_update_switches_and_clears_owners_and_a_response_is_a_valid_request_body(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Update Co")
    me = _me(client, token)
    team = _org_group(client, token, org["id"], "Owners")
    h = auth_headers(token)

    pain_point = _create_pain_point(client, token, project["id"])
    switched = _update_pain_point(client, token, project["id"], pain_point, owner=_user(me))
    assert switched.json()["owner"]["id"] == me
    regroup = _update_pain_point(client, token, project["id"], pain_point, owner={"type": "org_group", "id": team})
    assert regroup.status_code == 200 and regroup.json()["owner"]["label"] == "Owners"
    cleared = _update_pain_point(client, token, project["id"], pain_point, owner=None)
    assert cleared.status_code == 200 and cleared.json()["owner"] is None

    question = _create_open_question(client, token, project["id"], owner=None)
    on = _update_open_question(client, token, project["id"], question["id"], owner={"type": "org_group", "id": team})
    off = _update_open_question(client, token, project["id"], question["id"], owner=None)
    assert on.json()["owner"]["id"] == team and off.json()["owner"] is None

    principle = _create_project_guiding_principle(client, token, project["id"], owner=_user(me))
    url = f"{_project_base(project['id'])}/guiding-principles/{principle['id']}"
    to_group = client.put(url, json={**_GP_PAYLOAD, "owner": {"type": "org_group", "id": team}}, headers=h)
    assert to_group.status_code == 200, to_group.text
    to_none = client.put(url, json={**_GP_PAYLOAD, "owner": None}, headers=h)
    assert to_none.json()["owner"] is None
    # A response is a valid request body (the display fields on the principal are ignored).
    again = client.put(url, json={**_GP_PAYLOAD, "owner": to_group.json()["owner"]}, headers=h)
    assert again.status_code == 200 and again.json()["owner"]["id"] == team

    versions = client.get(url + "/versions", headers=h).json()
    assert [(v["owner"] or {}).get("type") for v in versions] == ["user", "org_group", None, "org_group"]
    assert versions[1]["owner"]["label"] == "Owners"


def test_an_organisation_guiding_principle_takes_user_and_org_group_owners(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Org GP Co")
    team = _org_group(client, token, org["id"], "Org Wide")
    principle = _create_org_guiding_principle(client, token, org["id"], owner={"type": "org_group", "id": team})
    assert principle["owner"]["label"] == "Org Wide"
    h = auth_headers(token)
    listed = client.get(_gp_org_base(org["id"]) + "/guiding-principles", headers=h).json()
    assert listed[0]["owner"]["label"] == "Org Wide"
    history = client.get(f"{_gp_org_base(org['id'])}/guiding-principles/{principle['id']}/versions", headers=h).json()
    assert history[0]["owner"]["type"] == "org_group"


# --- Validation ----------------------------------------------------------------------------------------


def test_foreign_and_wrong_scope_principals_are_rejected(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Reject Co")
    other_project = create_project(client, token, org["id"], "Other Project")
    elsewhere = _project_group(client, token, other_project["id"], "Elsewhere")
    own = _project_group(client, token, project["id"], "Own Squad")
    other_org, other_token = create_org_admin_in(client, admin_token, "CS Principal Foreign Co")
    foreign_group = _org_group(client, other_token, other_org["id"], "Foreign Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "cs_foreign_owner@sp.example.com")
    h = auth_headers(token)
    pain_point = _create_pain_point(client, token, project["id"])
    question = _create_open_question(client, token, project["id"])
    principle = _create_project_guiding_principle(client, token, project["id"])

    for bad in (
        {"type": "org_group", "id": foreign_group}, {"type": "user", "id": foreign_user},
        {"type": "project_group", "id": elsewhere}, {"type": "org_group", "id": str(uuid.uuid4())},
    ):
        assert _update_pain_point(client, token, project["id"], pain_point, owner=bad).status_code == 400, bad
        assert _update_open_question(client, token, project["id"], question["id"], owner=bad).status_code == 400, bad
        assert client.post(
            _project_base(project["id"]) + "/guiding-principles", json={**_GP_PAYLOAD, "owner": bad}, headers=h,
        ).status_code == 400, bad
        assert client.put(
            f"{_project_base(project['id'])}/guiding-principles/{principle['id']}", json={**_GP_PAYLOAD, "owner": bad},
            headers=h,
        ).status_code == 400, bad

    # An organisation-scoped principle is shared by every project, so it cannot name a project group.
    org_url = _gp_org_base(org["id"]) + "/guiding-principles"
    project_group_owner = {"type": "project_group", "id": own}
    assert client.post(org_url, json={**_GP_PAYLOAD, "owner": project_group_owner}, headers=h).status_code == 400
    good = _create_org_guiding_principle(client, token, org["id"], owner={"type": "org_group", "id": _org_group(client, token, org["id"], "Good")})
    assert client.put(f"{org_url}/{good['id']}", json={**_GP_PAYLOAD, "owner": project_group_owner}, headers=h).status_code == 400
    assert _update_pain_point(client, token, project["id"], pain_point, owner=project_group_owner).status_code == 200
    assert _update_open_question(client, token, project["id"], question["id"], owner=project_group_owner).status_code == 200


# --- Deleting a group that owns records -----------------------------------------------------------------


def test_deleting_an_owner_group_counts_current_versions_blocks_reassigns_and_audits_the_record(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Delete Co")
    me = _me(client, token)
    team = _org_group(client, token, org["id"], "Doomed Team")
    h = auth_headers(token)
    group = {"type": "org_group", "id": team}
    pain_point = _create_pain_point(client, token, project["id"])
    _update_pain_point(client, token, project["id"], pain_point, owner=group)
    question = _create_open_question(client, token, project["id"])
    _update_open_question(client, token, project["id"], question["id"], owner=group)
    principle = _create_project_guiding_principle(client, token, project["id"], owner=group)
    gp_url = f"{_project_base(project['id'])}/guiding-principles/{principle['id']}"
    client.put(gp_url, json={**_GP_PAYLOAD, "owner": _user(me)}, headers=h)  # version 1 keeps the group, version 2 does not
    client.put(gp_url, json={**_GP_PAYLOAD, "owner": group}, headers=h)  # version 3 names it again
    group_url = f"/api/v1/orgs/{org['id']}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("pain point owners", 1, False), ("open question owners", 1, False), ("guiding principle owners", 1, False),
    }, "older versions are not counted"
    assert usage["total"] == 3 and usage["mandatory_total"] == 0

    assert client.delete(group_url, headers=h).status_code == 409
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    base = _project_base(project["id"])
    assert client.get(f"{base}/pain-points/{pain_point['id']}", headers=h).json()["owner"]["id"] == me
    assert client.get(f"{base}/open-questions/{question['id']}", headers=h).json()["owner"]["id"] == me
    assert client.get(gp_url, headers=h).json()["owner"]["id"] == me
    history = client.get(gp_url + "/versions", headers=h).json()
    assert history[0]["owner"]["label"] == "Deleted group" and history[0]["owner"]["exists"] is False

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        assert {str(e.entity_id) for e in events} >= {pain_point["id"], question["id"], principle["id"]}


def test_clear_optional_empties_owners_and_a_project_group_can_be_replaced(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal Clear Co")
    h = auth_headers(token)
    team = _org_group(client, token, org["id"], "Clear Team")
    question = _create_open_question(client, token, project["id"])
    _update_open_question(client, token, project["id"], question["id"], owner={"type": "org_group", "id": team})
    resp = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}", params={"clear_optional": "true"}, headers=h)
    assert resp.status_code == 204, resp.text
    assert client.get(f"{_project_base(project['id'])}/open-questions/{question['id']}", headers=h).json()["owner"] is None

    squad = _project_group(client, token, project["id"], "Doomed Squad")
    pain_point = _create_pain_point(client, token, project["id"])
    _update_pain_point(client, token, project["id"], pain_point, owner={"type": "project_group", "id": squad})
    successor = _org_group(client, token, org["id"], "Successor")
    url = f"/api/v1/projects/{project['id']}/groups/{squad}"
    assert client.delete(url, headers=h).status_code == 409
    done = client.delete(url, params={"replacement_type": "org_group", "replacement_id": successor}, headers=h)
    assert done.status_code == 204, done.text
    owner = client.get(f"{_project_base(project['id'])}/pain-points/{pain_point['id']}", headers=h).json()["owner"]
    assert owner["type"] == "org_group" and owner["id"] == successor


# --- Reports -------------------------------------------------------------------------------------------


def _report(client, token, project_id, slug) -> dict:
    resp = client.get(f"{_project_base(project_id)}/reports/{slug}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _section(report, key) -> dict:
    return next(s for s in report["sections"] if s["key"] == key)


def test_open_question_register_prints_and_groups_by_owner_principal(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Principal R4 Co")
    team = _org_group(client, token, org["id"], "Triage Team")
    group = {"type": "org_group", "id": team}
    for text_ in ("First?", "Second?"):
        created = _create_open_question(client, token, project["id"], question=text_)
        _update_open_question(client, token, project["id"], created["id"], question=text_, owner=group)
    _create_open_question(client, token, project["id"], question="Nobody?")

    report = _report(client, token, project["id"], "open-question-register")

    owners_column = _section(report, "open")["columns"].index("Owner")
    assert sorted(row[owners_column] for row in _section(report, "open")["rows"]) == [
        "Triage Team (Org group)", "Triage Team (Org group)", "Unowned",
    ]
    assert dict(_section(report, "by_owner")["rows"]) == {"Triage Team (Org group)": "2", "Unowned": "1"}
    assert [r[0] for r in _section(report, "unowned")["rows"]] == ["Nobody?"]


def test_guiding_principle_usage_report_prints_a_group_owner(client, admin_token):
    from sqlalchemy import update

    from app.modules.context_strategy.enums import GuidingPrincipleStatus
    from app.modules.context_strategy.models import GuidingPrincipleVersion

    org, project, token = _setup(client, admin_token, "CS Principal R6 Co")
    team = _org_group(client, token, org["id"], "Principle Stewards")
    principle = _create_project_guiding_principle(client, token, project["id"], owner={"type": "org_group", "id": team})
    with SessionLocal() as db:
        db.execute(update(GuidingPrincipleVersion).where(
            GuidingPrincipleVersion.guiding_principle_id == principle["id"], GuidingPrincipleVersion.valid_to.is_(None),
        ).values(status=GuidingPrincipleStatus.ACTIVE))
        db.commit()

    register = _section(_report(client, token, project["id"], "guiding-principle-usage"), "register")

    assert register["rows"][0][register["columns"].index("Owner")] == "Principle Stewards (Org group)"


# --- Migration backfill ---------------------------------------------------------------------------------


def test_migration_backfills_existing_rows_to_user(client, admin_token):
    """Runs the real 0078 migration: an Open Question written in the pre-migration shape (no `owner_type`
    column) ends up with `user` for its owner, and an unowned one stays unowned."""
    org, project, token = _setup(client, admin_token, "CS Principal Migration Co")
    me = _me(client, token)
    unowned = _create_open_question(client, token, project["id"])
    owned_id = uuid.uuid4()
    with engine.begin() as conn:  # the backfill labels every owner a user, so leave no other test's group owner behind
        for table in ("pain_points", "guiding_principle_versions", "open_questions"):
            conn.execute(text(f"UPDATE {table} SET owner_id = NULL, owner_type = NULL WHERE owner_type <> 'user'"))
    command.downgrade(build_alembic_config(), "0077")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO open_questions (id, project_id, question, context, evidence, priority, status, owner_id, "
                    "creator_id, is_archived, created_at, updated_at) VALUES (:id, :p, 'Legacy?', '', '', 'medium', 'open', "
                    ":me, :me, false, now(), now())"
                ),
                {"id": owned_id, "p": project["id"], "me": me},
            )
    finally:
        command.upgrade(build_alembic_config(), "head")

    with SessionLocal() as db:
        row = db.get(OpenQuestion, owned_id)
        assert (row.owner_type, str(row.owner_id)) == ("user", me)
        other = db.get(OpenQuestion, uuid.UUID(unowned["id"]))
        assert other.owner_type is None and other.owner_id is None
    resp = client.get(f"{_project_base(project['id'])}/open-questions/{owned_id}", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["owner"]["id"] == me
