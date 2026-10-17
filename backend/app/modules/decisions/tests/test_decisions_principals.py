"""Tests for groups as Decision owners and decision makers (users and groups
on parity).

Covers: each principal kind on create and update, cross-organisation and
cross-project rejection, the owner gate for a direct owner / org-group member /
nested-group member / project-group member / non-member / removed member (and
that a group confers no approval right), the owner and decision-maker filters
including "mine", deleting a group that owns Decisions (blocked, then
reassigned, optional maker cleared), the D1/D2/D3 reports naming a group, and
the migration backfill of existing rows to `user`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from alembic import command
from app.database import SessionLocal, engine
from app.modules.decisions.models import Decision
from app.modules.decisions.tests.test_decisions_api import (
    _add_plain_member,
    _advance_to_under_review,
    _base,
    _create_decision,
    _first_decision_type_id,
    _setup,
)
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
)


def _user_ref(user_id) -> dict:
    return {"type": "user", "id": str(user_id)}


def _decision(client, token, project_id, type_id, **extra) -> dict:
    return _create_decision(client, token, project_id, type_id, **extra)


def _put(client, token, project_id, decision: dict, **overrides):
    payload = {
        "title": decision["title"], "decision_statement": decision["decision_statement"],
        "decision_type_id": decision["decision_type_id"],
        "owner": {"type": decision["owner"]["type"], "id": decision["owner"]["id"]},
        "decision_maker": (
            {"type": decision["decision_maker"]["type"], "id": decision["decision_maker"]["id"]}
            if decision["decision_maker"] else None
        ),
        **overrides,
    }
    return client.put(f"{_base(project_id)}/{decision['id']}", json=payload, headers=auth_headers(token))


# --- Create and update: each principal kind ------------------------------------------------------


def test_create_with_each_principal_kind_and_group_display(client, admin_token):
    org, project, token = _setup(client, admin_token, "Decision Principal Kinds Co")
    type_id = _first_decision_type_id(client, token, project["id"])
    member = create_org_user(client, token, org["id"], "kinds_member@example.com")
    team = create_org_group(client, token, org["id"], "Platform Team", users=[member])
    squad = create_project_group(client, token, project["id"], "Squad", users=[member])

    by_user = _decision(client, token, project["id"], type_id, owner=_user_ref(member))
    assert by_user["owner"]["type"] == "user" and by_user["owner"]["id"] == member
    assert by_user["decision_maker"] is None

    by_org_group = _decision(
        client, token, project["id"], type_id, owner={"type": "org_group", "id": team},
        decision_maker={"type": "project_group", "id": squad},
    )
    assert by_org_group["owner"] == {
        "type": "org_group", "id": team, "label": "Platform Team", "member_count": 1, "exists": True,
    }
    assert by_org_group["decision_maker"]["label"] == "Squad"
    assert by_org_group["decision_maker"]["type"] == "project_group"

    listed = client.get(_base(project["id"]), headers=auth_headers(token)).json()
    assert {d["id"]: d["owner"]["label"] for d in listed}[by_org_group["id"]] == "Platform Team"


def test_owner_defaults_to_the_creator(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision Principal Default Co")
    created = _decision(client, token, project["id"], _first_decision_type_id(client, token, project["id"]))
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    assert created["owner"]["type"] == "user" and created["owner"]["id"] == me


def test_update_switches_owner_to_a_group_and_clears_the_decision_maker(client, admin_token):
    org, project, token = _setup(client, admin_token, "Decision Principal Update Co")
    type_id = _first_decision_type_id(client, token, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    team = create_org_group(client, token, org["id"], "Owners")
    decision = _decision(client, token, project["id"], type_id, decision_maker=_user_ref(me))

    resp = _put(client, token, project["id"], decision, owner={"type": "org_group", "id": team}, decision_maker=None)
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner"]["label"] == "Owners"
    assert resp.json()["decision_maker"] is None

    back = _put(client, token, project["id"], resp.json(), owner=_user_ref(me))
    assert back.status_code == 200 and back.json()["owner"]["type"] == "user"


def test_update_round_trips_the_response_as_the_request(client, admin_token):
    """A client may PUT back what it GET (extra display fields on the principal are ignored)."""
    org, project, token = _setup(client, admin_token, "Decision Principal Round Trip Co")
    team = create_org_group(client, token, org["id"], "Round Trip Team")
    decision = _decision(
        client, token, project["id"], _first_decision_type_id(client, token, project["id"]),
        owner={"type": "org_group", "id": team},
    )
    resp = client.put(f"{_base(project['id'])}/{decision['id']}", json={**decision, "title": "Renamed"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner"]["id"] == team


# --- Validation ---------------------------------------------------------------------------------


def test_foreign_and_wrong_project_principals_are_rejected(client, admin_token):
    org, project, token = _setup(client, admin_token, "Decision Principal Reject Co")
    type_id = _first_decision_type_id(client, token, project["id"])
    other_project = create_project(client, token, org["id"], "Other Project")
    elsewhere = create_project_group(client, token, other_project["id"], "Elsewhere")
    other_org, other_token = create_org_admin_in(client, admin_token, "Decision Principal Foreign Org")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "foreign_owner@example.com")

    for bad in (
        {"type": "org_group", "id": foreign_group},
        {"type": "user", "id": foreign_user},
        {"type": "project_group", "id": elsewhere},
        {"type": "org_group", "id": str(uuid.uuid4())},
    ):
        for field in ("owner", "decision_maker"):
            resp = client.post(
                _base(project["id"]),
                json={"title": "T", "decision_statement": "S", "decision_type_id": type_id, field: bad},
                headers=auth_headers(token),
            )
            assert resp.status_code == 400, (field, bad, resp.text)

    good = _decision(client, token, project["id"], type_id)
    resp = _put(client, token, project["id"], good, owner={"type": "org_group", "id": foreign_group})
    assert resp.status_code == 400
    assert client.get(f"{_base(project['id'])}/{good['id']}", headers=auth_headers(token)).json()["owner"]["type"] == "user"


def test_a_decision_requires_an_owner_on_update(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision Principal Mandatory Co")
    decision = _decision(client, token, project["id"], _first_decision_type_id(client, token, project["id"]))
    resp = _put(client, token, project["id"], decision, owner=None)
    assert resp.status_code == 422


# --- The owner gate -----------------------------------------------------------------------------


def _propose(client, token, project_id, decision_id):
    return client.post(f"{_base(project_id)}/{decision_id}/propose", headers=auth_headers(token))


def test_owner_group_members_pass_the_propose_gate_and_non_members_do_not(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Gate Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    direct_id, direct = _add_plain_member(client, admin, org["id"], project["id"], "gate_direct@example.com")
    nested_id, nested = _add_plain_member(client, admin, org["id"], project["id"], "gate_nested@example.com")
    squad_id, squad = _add_plain_member(client, admin, org["id"], project["id"], "gate_squad@example.com")
    _outsider_id, outsider = _add_plain_member(client, admin, org["id"], project["id"], "gate_outsider@example.com")

    inner = create_org_group(client, admin, org["id"], "Inner", users=[nested_id])
    team = create_org_group(client, admin, org["id"], "Team", users=[direct_id], nested=[inner])
    squad_group = create_project_group(client, admin, project["id"], "Squad", users=[squad_id])

    cases = [
        (direct, {"type": "org_group", "id": team}, True),
        (nested, {"type": "org_group", "id": team}, True),
        (squad, {"type": "project_group", "id": squad_group}, True),
        (outsider, {"type": "org_group", "id": team}, False),
        (outsider, {"type": "project_group", "id": squad_group}, False),
    ]
    for token, owner, allowed in cases:
        decision = _decision(client, admin, project["id"], type_id, owner=owner)
        resp = _propose(client, token, project["id"], decision["id"])
        assert resp.status_code == (200 if allowed else 403), (owner, resp.text)


def test_removed_group_member_loses_the_owner_gate(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Removed Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    member_id, member = _add_plain_member(client, admin, org["id"], project["id"], "gate_removed@example.com")
    team = create_org_group(client, admin, org["id"], "Removable", users=[member_id])
    decision = _decision(client, admin, project["id"], type_id, owner={"type": "org_group", "id": team})

    removed = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}/members/{member_id}", headers=auth_headers(admin))
    assert removed.status_code == 204, removed.text
    assert _propose(client, member, project["id"], decision["id"]).status_code == 403


def test_a_group_owner_confers_no_approval_or_edit_right(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal No Approval Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    member_id, member = _add_plain_member(client, admin, org["id"], project["id"], "gate_noapprove@example.com")
    team = create_org_group(client, admin, org["id"], "Owners", users=[member_id])
    decision = _decision(client, admin, project["id"], type_id, owner={"type": "org_group", "id": team})
    _advance_to_under_review(client, admin, project["id"], decision["id"])

    assert client.post(f"{_base(project['id'])}/{decision['id']}/approve", json={}, headers=auth_headers(member)).status_code == 403
    assert _put(client, member, project["id"], decision).status_code == 403


# --- Filters ------------------------------------------------------------------------------------


def test_owner_and_decision_maker_filters_including_mine(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Filter Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    member_id, member = _add_plain_member(client, admin, org["id"], project["id"], "filter_member@example.com")
    other_id, _other = _add_plain_member(client, admin, org["id"], project["id"], "filter_other@example.com")
    team = create_org_group(client, admin, org["id"], "Filter Team", users=[member_id])
    squad = create_project_group(client, admin, project["id"], "Filter Squad", users=[member_id])

    mine_direct = _decision(client, admin, project["id"], type_id, owner=_user_ref(member_id))
    mine_org = _decision(client, admin, project["id"], type_id, owner={"type": "org_group", "id": team})
    mine_maker = _decision(
        client, admin, project["id"], type_id, owner=_user_ref(other_id), decision_maker={"type": "project_group", "id": squad},
    )
    theirs = _decision(client, admin, project["id"], type_id, owner=_user_ref(other_id))

    def ids(token, **params) -> set[str]:
        resp = client.get(_base(project["id"]), params=params, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return {d["id"] for d in resp.json()}

    assert ids(member, owner_mine="true") == {mine_direct["id"], mine_org["id"]}
    assert ids(member, decision_maker_mine="true") == {mine_maker["id"]}
    assert ids(admin, owner_type="org_group", owner_id=team) == {mine_org["id"]}
    assert ids(admin, owner_id=other_id) == {mine_maker["id"], theirs["id"]}
    assert ids(admin, decision_maker_type="project_group", decision_maker_id=squad) == {mine_maker["id"]}


# --- Deleting a group that owns Decisions -------------------------------------------------------


def test_deleting_an_owner_group_is_blocked_then_reassigns_and_clears(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Delete Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin)).json()["id"]
    team = create_org_group(client, admin, org["id"], "Doomed Team")
    owned = _decision(client, admin, project["id"], type_id, owner={"type": "org_group", "id": team})
    made = _decision(client, admin, project["id"], type_id, decision_maker={"type": "org_group", "id": team})
    group_url = f"/api/v1/orgs/{org['id']}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=auth_headers(admin)).json()
    assert usage["total"] == 2 and usage["mandatory_total"] == 1
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("decision owners", 1, True), ("decision makers", 1, False),
    }

    blocked = client.delete(group_url, headers=auth_headers(admin))
    assert blocked.status_code == 409
    clear_only = client.delete(group_url, params={"clear_optional": "true"}, headers=auth_headers(admin))
    assert clear_only.status_code == 409, "a mandatory owner still needs a replacement"

    done = client.delete(
        group_url, params={"replacement_type": "user", "replacement_id": me}, headers=auth_headers(admin),
    )
    assert done.status_code == 204, done.text

    after_owned = client.get(f"{_base(project['id'])}/{owned['id']}", headers=auth_headers(admin)).json()
    after_made = client.get(f"{_base(project['id'])}/{made['id']}", headers=auth_headers(admin)).json()
    assert after_owned["owner"]["type"] == "user" and after_owned["owner"]["id"] == me
    assert after_made["decision_maker"]["id"] == me


def test_clear_optional_empties_only_decision_makers(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Clear Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    team = create_org_group(client, admin, org["id"], "Maker Team")
    made = _decision(client, admin, project["id"], type_id, decision_maker={"type": "org_group", "id": team})

    resp = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}", params={"clear_optional": "true"}, headers=auth_headers(admin))
    assert resp.status_code == 204, resp.text
    assert client.get(f"{_base(project['id'])}/{made['id']}", headers=auth_headers(admin)).json()["decision_maker"] is None


def test_deleting_a_project_group_owner_requires_replacement(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Project Group Delete Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    squad = create_project_group(client, admin, project["id"], "Doomed Squad")
    decision = _decision(client, admin, project["id"], type_id, owner={"type": "project_group", "id": squad})
    url = f"/api/v1/projects/{project['id']}/groups/{squad}"

    assert client.delete(url, headers=auth_headers(admin)).status_code == 409
    replacement = create_org_group(client, admin, org["id"], "Successor")
    done = client.delete(
        url, params={"replacement_type": "org_group", "replacement_id": replacement}, headers=auth_headers(admin),
    )
    assert done.status_code == 204, done.text
    owner = client.get(f"{_base(project['id'])}/{decision['id']}", headers=auth_headers(admin)).json()["owner"]
    assert owner["type"] == "org_group" and owner["id"] == replacement


# --- Reports ------------------------------------------------------------------------------------


def test_reports_name_a_group_with_its_kind(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Decision Principal Reports Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    team = create_org_group(client, admin, org["id"], "Review Board")
    squad = create_project_group(client, admin, project["id"], "Delivery Squad")
    decision = _decision(
        client, admin, project["id"], type_id, owner={"type": "org_group", "id": team},
        decision_maker={"type": "project_group", "id": squad}, decision_date="2026-01-05",
    )
    _advance_to_under_review(client, admin, project["id"], decision["id"])

    def section(slug, key) -> dict:
        resp = client.get(f"{_base(project['id'])}/reports/{slug}", headers=auth_headers(admin))
        assert resp.status_code == 200, resp.text
        return next(s for s in resp.json()["sections"] if s["key"] == key)

    d1 = section("decision-register", "register")
    row = d1["rows"][0]
    assert row[d1["columns"].index("Owner")] == "Review Board (Org group)"
    assert row[d1["columns"].index("Decision maker")] == "Delivery Squad (Project group)"

    d2 = section("approval-ageing", "awaiting")
    row = d2["rows"][0]
    assert row[d2["columns"].index("Owner")] == "Review Board (Org group)"
    assert row[d2["columns"].index("Decision maker")] == "Delivery Squad (Project group)"


# --- Migration backfill -------------------------------------------------------------------------


def test_migration_backfills_existing_rows_to_user(client, admin_token):
    """Runs the real 0076 migration: a row written in the pre-migration shape (no `*_type`
    columns) ends up with `user` for its owner and, when set, its decision maker."""
    org, project, admin = _setup(client, admin_token, "Decision Principal Migration Co")
    type_id = _first_decision_type_id(client, admin, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin)).json()["id"]
    decision_id = uuid.uuid4()
    command.downgrade(build_alembic_config(), "0075")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO decisions (id, created_at, updated_at, project_id, unique_code, title, decision_statement, "
                    "decision_type_id, status, owner_id, decision_maker_id, creator_id, is_archived) VALUES "
                    "(:id, now(), now(), :project, 'DEC-MIG', 'Legacy', 'Legacy row', :type, 'draft', :me, :me, :me, false)"
                ),
                {"id": decision_id, "project": project["id"], "type": type_id, "me": me},
            )
    finally:
        command.upgrade(build_alembic_config(), "head")

    db = SessionLocal()
    try:
        row = db.get(Decision, decision_id)
        assert (row.owner_type, str(row.owner_id)) == ("user", me)
        assert (row.decision_maker_type, str(row.decision_maker_id)) == ("user", me)
    finally:
        db.close()
    resp = client.get(f"{_base(project['id'])}/{decision_id}", headers=auth_headers(admin))
    assert resp.status_code == 200 and resp.json()["owner"]["type"] == "user"
