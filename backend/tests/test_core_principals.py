"""Tests for groups on core fields (users and groups on parity), through the real HTTP endpoints.

A change request task's assignee (a member of an assigned group may mark
the task done, a non-member or removed member may not; project bundle round trip; the
`0083` migration).

A requirement action's assignee and a change
request's proposed action assignee — each principal kind on create, update,
clear and list; validation (a foreign organisation's group or user, another
project's group, an unknown id — the assignee was not validated at all before);
a proposal carried through approval into the new action; deleting a group that
is assigned actions (usage counts, blocked, reassigned, cleared, open proposals
rewritten and decided ones left as history); and the real `0082` migration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.requirement_action import RequirementAction
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_component_and_category,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
    login,
)


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def _user(user_id) -> dict:
    return {"type": "user", "id": str(user_id)}


def _org(group_id) -> dict:
    return {"type": "org_group", "id": str(group_id)}


def _project(group_id) -> dict:
    return {"type": "project_group", "id": str(group_id)}


# --- 6a: action assignee ---------------------------------------------------------------------------------


def _action_type(client, token, project_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()[0]["id"]


def _create_action(client, token, project_id, **extra):
    return client.post(
        f"/api/v1/projects/{project_id}/actions",
        json={"title": "Run regression suite", "action_type_id": _action_type(client, token, project_id), **extra},
        headers=auth_headers(token),
    )


def _update_action(client, token, project_id, action, **extra):
    body = {"title": action["title"], "action_type_id": action["action_type_id"], **extra}
    return client.patch(f"/api/v1/projects/{project_id}/actions/{action['id']}", json=body, headers=auth_headers(token))


def test_an_action_takes_each_principal_kind_and_shows_a_group_by_name(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    member = create_org_user(client, admin_token, org_id, "act_kinds_member@core.example.com")
    team = create_org_group(client, admin_token, org_id, "QA Team", users=[member])
    squad = create_project_group(client, admin_token, project["id"], "Test Squad", users=[member])
    pid = project["id"]

    unassigned = _create_action(client, admin_token, pid)
    assert unassigned.status_code == 201 and unassigned.json()["assignee"] is None
    by_org = _create_action(client, admin_token, pid, assignee=_org(team))
    assert by_org.json()["assignee"] == {
        "type": "org_group", "id": team, "label": "QA Team", "member_count": 1, "exists": True,
    }
    by_project = _create_action(client, admin_token, pid, assignee=_project(squad))
    assert by_project.json()["assignee"]["label"] == "Test Squad"
    by_user = _create_action(client, admin_token, pid, assignee=_user(member))
    assert by_user.json()["assignee"]["type"] == "user" and by_user.json()["assignee"]["id"] == member

    listed = {a["id"]: a for a in client.get(f"/api/v1/projects/{pid}/actions", headers=auth_headers(admin_token)).json()}
    assert listed[by_org.json()["id"]]["assignee"]["label"] == "QA Team"
    assert listed[by_project.json()["id"]]["assignee"]["type"] == "project_group"
    assert listed[unassigned.json()["id"]]["assignee"] is None


def test_update_switches_and_clears_the_assignee_and_a_response_is_a_valid_request(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    team = create_org_group(client, admin_token, org_id, "Switchers")
    pid = project["id"]
    action = _create_action(client, admin_token, pid, assignee=_user(_me(client, admin_token))).json()

    to_group = _update_action(client, admin_token, pid, action, assignee=_org(team))
    assert to_group.status_code == 200 and to_group.json()["assignee"]["label"] == "Switchers"
    again = _update_action(client, admin_token, pid, action, assignee=to_group.json()["assignee"])
    assert again.status_code == 200 and again.json()["assignee"]["id"] == team
    cleared = _update_action(client, admin_token, pid, action, assignee=None)
    assert cleared.status_code == 200 and cleared.json()["assignee"] is None


def test_foreign_and_wrong_scope_assignees_are_rejected_on_every_action_write_path(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other Project")
    elsewhere = create_project_group(client, admin_token, other_project["id"], "Elsewhere")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core Action Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "core_action_foreign@core.example.com")
    pid = project["id"]
    action = _create_action(client, admin_token, pid).json()
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    requirement = client.post(
        f"/api/v1/projects/{pid}/requirements", json={"name": "R", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    for bad in (_org(foreign_group), _user(foreign_user), _project(elsewhere), _org(uuid.uuid4())):
        assert _create_action(client, admin_token, pid, assignee=bad).status_code == 400, bad
        assert _update_action(client, admin_token, pid, action, assignee=bad).status_code == 400, bad
        linked = client.post(
            f"/api/v1/projects/{pid}/requirements/{requirement['id']}/actions/create-and-link",
            json={"title": "T", "action_type_id": action["action_type_id"], "assignee": bad}, headers=auth_headers(admin_token),
        )
        assert linked.status_code == 400, bad


def test_create_and_link_takes_a_group_assignee(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    team = create_org_group(client, admin_token, org_id, "Linkers")
    pid = project["id"]
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    requirement = client.post(
        f"/api/v1/projects/{pid}/requirements", json={"name": "R", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    resp = client.post(
        f"/api/v1/projects/{pid}/requirements/{requirement['id']}/actions/create-and-link",
        json={"title": "T", "action_type_id": _action_type(client, admin_token, pid), "assignee": _org(team)},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201 and resp.json()["assignee"]["label"] == "Linkers"
    listed = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)).json()
    assert listed[0]["assignee"]["label"] == "Linkers"


def _locked_requirement(client, token, project_id) -> dict:
    component_id, category_id = create_component_and_category(client, token, project_id)
    requirement = client.post(
        f"/api/v1/projects/{project_id}/requirements", json={"name": "R", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()
    approved = client.post(f"/api/v1/projects/{project_id}/requirements/{requirement['id']}/approve", headers=auth_headers(token))
    assert approved.status_code == 200, approved.text
    return requirement


def _propose_action(client, token, project_id, requirement_id, **extra):
    return client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement_id, "reason": "gap",
            "proposed_action_title": "Proposed action", "proposed_action_type_id": _action_type(client, token, project_id), **extra,
        },
        headers=auth_headers(token),
    )


def _decide(client, token, project_id, cr_id, approve=True):
    base = f"/api/v1/projects/{project_id}/change-requests/{cr_id}"
    assert client.post(f"{base}/submit", headers=auth_headers(token)).status_code == 200
    resp = client.post(f"{base}/decide", json={"approve": approve, "note": ""}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_proposed_action_assignee_is_validated_shown_and_carried_into_the_created_action(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    team = create_org_group(client, admin_token, org_id, "Proposal Team")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core CR Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign CR Team")
    pid = project["id"]
    requirement = _locked_requirement(client, admin_token, pid)

    assert _propose_action(client, admin_token, pid, requirement["id"], proposed_action_assignee=_org(foreign_group)).status_code == 400
    created = _propose_action(client, admin_token, pid, requirement["id"], proposed_action_assignee=_org(team))
    assert created.status_code == 201, created.text
    assert created.json()["proposed_action_assignee"]["label"] == "Proposal Team"

    _decide(client, admin_token, pid, created.json()["id"])
    actions = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)).json()
    assert [a["assignee"]["id"] for a in actions] == [team]


def test_a_proposal_whose_group_was_deleted_is_approved_with_no_assignee(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    squad = create_project_group(client, admin_token, project["id"], "Vanishing Squad")
    pid = project["id"]
    requirement = _locked_requirement(client, admin_token, pid)
    created = _propose_action(client, admin_token, pid, requirement["id"], proposed_action_assignee=_project(squad)).json()
    # Remove the group the cheap way: clear what names it (the open proposal), then delete it.
    deleted = client.delete(f"/api/v1/projects/{pid}/groups/{squad}", params={"clear_optional": "true"}, headers=auth_headers(admin_token))
    assert deleted.status_code == 204, deleted.text

    _decide(client, admin_token, pid, created["id"])
    actions = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)).json()
    assert len(actions) == 1 and actions[0]["assignee"] is None


def test_deleting_a_group_counts_blocks_reassigns_and_audits_actions_and_open_proposals(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    team = create_org_group(client, admin_token, org_id, "Doomed Team")
    h = auth_headers(admin_token)
    pid = project["id"]
    action = _create_action(client, admin_token, pid, assignee=_org(team)).json()
    requirement = _locked_requirement(client, admin_token, pid)
    open_cr = _propose_action(client, admin_token, pid, requirement["id"], proposed_action_assignee=_org(team)).json()
    decided_cr = _propose_action(client, admin_token, pid, requirement["id"], proposed_action_assignee=_org(team)).json()
    _decide(client, admin_token, pid, decided_cr["id"])  # approving it also creates a second action naming the team
    group_url = f"/api/v1/orgs/{org_id}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("action assignees", 2, False), ("change request action assignees", 1, False),
    }, "the decided proposal is history and is not counted"
    assert client.delete(group_url, headers=h).status_code == 409
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    assert client.get(f"/api/v1/projects/{pid}/actions/{action['id']}", headers=h).json()["assignee"]["id"] == me
    reopened = client.get(f"/api/v1/projects/{pid}/change-requests/{open_cr['id']}", headers=h).json()
    assert reopened["proposed_action_assignee"]["id"] == me
    history = client.get(f"/api/v1/projects/{pid}/change-requests/{decided_cr['id']}", headers=h).json()
    assert history["proposed_action_assignee"]["label"] == "Deleted group"
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        assert {str(e.entity_id) for e in events} >= {action["id"], open_cr["id"]}


def test_clear_optional_empties_action_assignees(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    team = create_org_group(client, admin_token, org_id, "Clearable")
    action = _create_action(client, admin_token, project["id"], assignee=_org(team)).json()
    resp = client.delete(f"/api/v1/orgs/{org_id}/groups/{team}", params={"clear_optional": "true"}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    got = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}", headers=auth_headers(admin_token)).json()
    assert got["assignee"] is None


def test_migration_0082_backfills_existing_action_rows_to_user(client, admin_token, org_id):
    """Runs the real 0082 migration: an action written in the pre-migration shape (no `assignee_type` column) ends
    up with `user` for its assignee, and an unassigned one stays unassigned."""
    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    owned = _create_action(client, admin_token, project["id"], assignee=_user(me)).json()
    unowned = _create_action(client, admin_token, project["id"]).json()
    with engine.begin() as conn:  # the backfill labels every assignee a user, so leave no other test's group behind
        conn.execute(text(
            "UPDATE requirement_actions SET assignee_id = NULL, assignee_type = NULL WHERE assignee_type <> 'user'"
        ))
    command.downgrade(build_alembic_config(), "0081")
    try:
        with engine.begin() as conn:
            gone = conn.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'requirement_actions' AND column_name = 'assignee_type'"
            )).scalar()
            assert gone == 0
    finally:
        command.upgrade(build_alembic_config(), "head")
    with SessionLocal() as db:
        row = db.get(RequirementAction, uuid.UUID(owned["id"]))
        assert (row.assignee_type, str(row.assignee_id)) == ("user", me)
        other = db.get(RequirementAction, uuid.UUID(unowned["id"]))
        assert other.assignee_type is None and other.assignee_id is None


# --- 6b: change request task assignee -------------------------------------------------------------------


def _submitted_cr(client, token, project_id) -> dict:
    component_id, category_id = _scope(client, token, project_id)
    req = client.post(
        f"/api/v1/projects/{project_id}/requirements", json={"name": "Base", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()
    approved = client.post(f"/api/v1/projects/{project_id}/requirements/{req['id']}/approve", headers=auth_headers(token))
    assert approved.status_code == 200, approved.text
    cr = client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={"kind": "modify_requirement", "requirement_id": req["id"], "changed_fields": ["name"], "proposed_name": "Base v2", "reason": "r"},
        headers=auth_headers(token),
    ).json()
    client.post(f"/api/v1/projects/{project_id}/change-requests/{cr['id']}/submit", headers=auth_headers(token))
    return cr


def _tasks_url(project_id, cr_id) -> str:
    return f"/api/v1/projects/{project_id}/change-requests/{cr_id}/tasks"


def test_a_task_takes_each_principal_kind_and_a_response_is_a_valid_request(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    member = create_org_user(client, admin_token, org_id, "task_kinds@core.example.com")
    team = create_org_group(client, admin_token, org_id, "Task Team", users=[member])
    squad = create_project_group(client, admin_token, project["id"], "Task Squad", users=[member])
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    h = auth_headers(admin_token)

    none = client.post(url, json={"description": "Unassigned"}, headers=h).json()
    assert none["assignee"] is None
    by_org = client.post(url, json={"description": "Org", "assignee": _org(team)}, headers=h).json()
    assert by_org["assignee"] == {"type": "org_group", "id": team, "label": "Task Team", "member_count": 1, "exists": True}
    by_project = client.post(url, json={"description": "Project", "assignee": _project(squad)}, headers=h).json()
    assert by_project["assignee"]["label"] == "Task Squad"
    by_user = client.post(url, json={"description": "User", "assignee": _user(member)}, headers=h).json()
    assert by_user["assignee"]["id"] == member

    listed = {t["description"]: t for t in client.get(url, headers=h).json()}
    assert listed["Org"]["assignee"]["label"] == "Task Team" and listed["Unassigned"]["assignee"] is None
    again = client.patch(f"{url}/{by_user['id']}", json={"assignee": by_org["assignee"]}, headers=h)
    assert again.status_code == 200 and again.json()["assignee"]["id"] == team


def test_foreign_and_wrong_scope_task_assignees_are_rejected(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other Task Project")
    elsewhere = create_project_group(client, admin_token, other_project["id"], "Elsewhere Tasks")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core Task Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Task Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "core_task_foreign@core.example.com")
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    h = auth_headers(admin_token)
    task = client.post(url, json={"description": "Fine"}, headers=h).json()
    for bad in (_org(foreign_group), _user(foreign_user), _project(elsewhere), _org(uuid.uuid4())):
        assert client.post(url, json={"description": "Bad", "assignee": bad}, headers=h).status_code == 400, bad
        assert client.patch(f"{url}/{task['id']}", json={"assignee": bad}, headers=h).status_code == 400, bad


def test_any_member_of_the_assigned_group_may_mark_the_task_done_but_a_removed_member_may_not(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    emails = {name: f"task_gate_{name}@core.example.com" for name in ("insider", "outsider")}
    ids = {}
    for name, email in emails.items():
        ids[name] = create_org_user(client, admin_token, org_id, email, role="member")
        client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": ids[name], "role": "stakeholder"}, headers=h)
    tokens = {name: login(client, email, "Password123!") for name, email in emails.items()}
    team = create_org_group(client, admin_token, org_id, "Gate Team", users=[ids["insider"]])
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    task = client.post(url, json={"description": "Gate", "assignee": _org(team)}, headers=h).json()

    assert client.patch(f"{url}/{task['id']}", json={"is_done": True}, headers=auth_headers(tokens["outsider"])).status_code == 403
    done = client.patch(f"{url}/{task['id']}", json={"is_done": True}, headers=auth_headers(tokens["insider"]))
    assert done.status_code == 200 and done.json()["is_done"] is True
    # Marking done is all a group member may do: no reassigning or editing.
    assert client.patch(f"{url}/{task['id']}", json={"description": "x"}, headers=auth_headers(tokens["insider"])).status_code == 403
    removed = client.delete(f"/api/v1/orgs/{org_id}/groups/{team}/members/{ids['insider']}", headers=h)
    assert removed.status_code == 204, removed.text
    assert client.patch(f"{url}/{task['id']}", json={"is_done": False}, headers=auth_headers(tokens["insider"])).status_code == 403


def test_deleting_a_group_reassigns_open_tasks_and_leaves_done_ones_as_history(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    team = create_org_group(client, admin_token, org_id, "Task Doomed")
    h = auth_headers(admin_token)
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    open_task = client.post(url, json={"description": "Open", "assignee": _org(team)}, headers=h).json()
    done_task = client.post(url, json={"description": "Done", "assignee": _org(team)}, headers=h).json()
    client.patch(f"{url}/{done_task['id']}", json={"is_done": True}, headers=h)
    group_url = f"/api/v1/orgs/{org_id}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert [(i["label"], i["count"]) for i in usage["items"]] == [("change request task assignees", 1)]
    assert client.delete(group_url, headers=h).status_code == 409
    assert client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h).status_code == 204
    tasks = {t["id"]: t for t in client.get(url, headers=h).json()}
    assert tasks[open_task["id"]]["assignee"]["id"] == me
    assert tasks[done_task["id"]]["assignee"]["label"] == "Deleted group"


def test_project_bundle_round_trips_a_group_task_assignee_and_drops_an_unmatched_one(client, admin_token, org_id):
    import io
    import json
    import zipfile

    project = create_project(client, admin_token, org_id, "Task Bundle Source")
    h = auth_headers(admin_token)
    squad = create_project_group(client, admin_token, project["id"], "Bundle Task Squad")
    team = create_org_group(client, admin_token, org_id, "Bundle Task Team")
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    client.post(url, json={"description": "By team", "assignee": _org(team)}, headers=h)
    client.post(url, json={"description": "By squad", "assignee": _project(squad)}, headers=h)
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert exported.status_code == 200
    doc = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    assigned = {t["description"]: t["assignee"] for c in doc["change_requests"] for t in c["tasks"]}
    assert assigned == {
        "By team": {"type": "org_group", "name": "Bundle Task Team"},
        "By squad": {"type": "project_group", "name": "Bundle Task Squad"},
    }

    def reimport(bundle: bytes, name: str) -> dict:
        resp = client.post(
            "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
            files={"file": ("bundle.zip", bundle, "application/zip")}, headers=h,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    imported = reimport(exported.content, "Task Bundle Copy")
    new_id = imported["project"]["id"]
    new_cr = client.get(f"/api/v1/projects/{new_id}/change-requests", headers=h).json()[0]
    tasks = {t["description"]: t for t in client.get(_tasks_url(new_id, new_cr["id"]), headers=h).json()}
    assert tasks["By team"]["assignee"]["id"] == team
    assert tasks["By squad"]["assignee"]["type"] == "project_group" and tasks["By squad"]["assignee"]["id"] != squad

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported.content)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "project.json":
                edited = json.loads(data)
                for c in edited["change_requests"]:
                    for t in c["tasks"]:
                        t["assignee"]["name"] = "Missing Group"
                data = json.dumps(edited).encode()
            target.writestr(item, data)
    unmatched = reimport(out.getvalue(), "Task Bundle Unmatched")
    left_cr = client.get(f"/api/v1/projects/{unmatched['project']['id']}/change-requests", headers=h).json()[0]
    left = client.get(_tasks_url(unmatched["project"]["id"], left_cr["id"]), headers=h).json()
    assert all(t["assignee"] is None for t in left)
    assert sum("Missing Group" in w for w in unmatched["warnings"]) == 2, unmatched["warnings"]


def test_migration_0083_backfills_existing_task_rows_to_user(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    cr = _submitted_cr(client, admin_token, project["id"])
    url = _tasks_url(project["id"], cr["id"])
    h = auth_headers(admin_token)
    owned = client.post(url, json={"description": "Owned", "assignee": _user(me)}, headers=h).json()
    unowned = client.post(url, json={"description": "Unowned"}, headers=h).json()
    with engine.begin() as conn:
        conn.execute(text("UPDATE change_request_tasks SET assignee_id = NULL, assignee_type = NULL WHERE assignee_type <> 'user'"))
    command.downgrade(build_alembic_config(), "0082")
    try:
        with engine.begin() as conn:
            assert conn.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'change_request_tasks' AND column_name = 'assignee_type'"
            )).scalar() == 0
    finally:
        command.upgrade(build_alembic_config(), "head")
    tasks = {t["id"]: t for t in client.get(url, headers=h).json()}
    assert tasks[owned["id"]]["assignee"]["id"] == me and tasks[unowned["id"]]["assignee"] is None


# --- 6c: requirement owner and reviewer -----------------------------------------------------------------


def _requirement(client, token, project_id, **extra) -> dict:
    component_id, category_id = _scope(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": extra.pop("name", "R"), "component_id": component_id, "category_id": category_id, **extra},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


_SCOPES: dict[str, tuple[str, str]] = {}


def _scope(client, token, project_id) -> tuple[str, str]:
    """A project's component and category, created once per project."""
    if project_id not in _SCOPES:
        _SCOPES[project_id] = create_component_and_category(client, token, project_id)
    return _SCOPES[project_id]


def _put_requirement(client, token, project_id, requirement, **changes):
    body = {
        "name": requirement["name"], "component_id": requirement["component_id"], "category_id": requirement["category_id"],
        "owner": requirement["owner"], **changes,
    }
    return client.put(f"/api/v1/projects/{project_id}/requirements/{requirement['id']}", json=body, headers=auth_headers(token))


def _yesterday() -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=1)).isoformat()


def test_a_requirement_defaults_its_owner_to_the_creator_and_takes_each_principal_kind(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    member = create_org_user(client, admin_token, org_id, "req_kinds@core.example.com")
    team = create_org_group(client, admin_token, org_id, "Req Owners", users=[member])
    squad = create_project_group(client, admin_token, project["id"], "Req Squad", users=[member])
    pid = project["id"]
    me = _me(client, admin_token)

    default = _requirement(client, admin_token, pid)
    assert default["owner"]["type"] == "user" and default["owner"]["id"] == me and default["reviewer"] is None
    by_org = _requirement(client, admin_token, pid, owner=_org(team), reviewer=_project(squad))
    assert by_org["owner"] == {"type": "org_group", "id": team, "label": "Req Owners", "member_count": 1, "exists": True}
    assert by_org["reviewer"]["label"] == "Req Squad" and by_org["reviewer"]["type"] == "project_group"

    listed = {r["id"]: r for r in client.get(f"/api/v1/projects/{pid}/requirements", headers=auth_headers(admin_token)).json()}
    assert listed[by_org["id"]]["owner"]["label"] == "Req Owners" and listed[by_org["id"]]["reviewer"]["label"] == "Req Squad"
    assert listed[default["id"]]["owner"]["id"] == me

    # An edit switches both, a response is a valid request body, and the reviewer can be cleared.
    updated = _put_requirement(client, admin_token, pid, by_org, owner=_user(member), reviewer=by_org["reviewer"])
    assert updated.status_code == 200 and updated.json()["owner"]["id"] == member and updated.json()["reviewer"]["id"] == squad
    cleared = _put_requirement(client, admin_token, pid, updated.json(), reviewer=None)
    assert cleared.status_code == 200 and cleared.json()["reviewer"] is None

    history = client.get(f"/api/v1/projects/{pid}/requirements/{by_org['id']}/history", headers=auth_headers(admin_token)).json()
    assert [(v["owner"]["type"], v["owner"]["label"]) for v in history][0] == ("org_group", "Req Owners")
    assert history[1]["owner"]["id"] == member


def test_foreign_and_wrong_scope_requirement_people_are_rejected(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other Req Project")
    elsewhere = create_project_group(client, admin_token, other_project["id"], "Elsewhere Req")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core Req Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Req Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "core_req_foreign@core.example.com")
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid)
    component_id, category_id = _scope(client, admin_token, pid)

    for bad in (_org(foreign_group), _user(foreign_user), _project(elsewhere), _org(uuid.uuid4())):
        for field in ("owner", "reviewer"):
            created = client.post(
                f"/api/v1/projects/{pid}/requirements",
                json={"name": "Bad", "component_id": component_id, "category_id": category_id, field: bad},
                headers=auth_headers(admin_token),
            )
            assert created.status_code == 400, (field, bad)
            assert _put_requirement(client, admin_token, pid, requirement, **{field: bad}).status_code == 400, (field, bad)
    # An owner is mandatory on an edit.
    assert _put_requirement(client, admin_token, pid, requirement, owner=None).status_code == 422


def test_any_member_of_the_reviewer_group_may_record_the_review_but_a_non_member_may_not(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    emails = {name: f"req_review_{name}@core.example.com" for name in ("insider", "outsider")}
    ids = {}
    for name, email in emails.items():
        ids[name] = create_org_user(client, admin_token, org_id, email, role="member")
        client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": ids[name], "role": "stakeholder"}, headers=h)
    tokens = {name: login(client, email, "Password123!") for name, email in emails.items()}
    team = create_org_group(client, admin_token, org_id, "Review Group", users=[ids["insider"]])
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid, reviewer=_org(team), review_date=_yesterday())
    url = f"/api/v1/projects/{pid}/requirements/{requirement['id']}/reviews"

    assert client.post(url, json={"outcome": "met"}, headers=auth_headers(tokens["outsider"])).status_code == 403
    recorded = client.post(url, json={"outcome": "met"}, headers=auth_headers(tokens["insider"]))
    assert recorded.status_code == 201
    assert recorded.json()["reviewed_by"] == ids["insider"], "the member who acted is recorded, not the group"


def test_the_due_lists_show_a_group_reviewer_to_its_members_and_filter_by_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    emails = {name: f"req_due_{name}@core.example.com" for name in ("insider", "outsider")}
    ids = {}
    for name, email in emails.items():
        ids[name] = create_org_user(client, admin_token, org_id, email, role="member")
        client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": ids[name], "role": "stakeholder"}, headers=h)
    tokens = {name: login(client, email, "Password123!") for name, email in emails.items()}
    team = create_org_group(client, admin_token, org_id, "Due Org Group", users=[ids["insider"]])
    squad = create_project_group(client, admin_token, project["id"], "Due Squad", users=[ids["insider"]])
    pid = project["id"]
    by_org = _requirement(client, admin_token, pid, name="By org", reviewer=_org(team), review_date=_yesterday())
    by_squad = _requirement(client, admin_token, pid, name="By squad", reviewer=_project(squad), review_date=_yesterday())
    other = _requirement(client, admin_token, pid, name="Someone else", reviewer=_user(ids["outsider"]), review_date=_yesterday())

    mine = client.get("/api/v1/me/reviews/due", headers=auth_headers(tokens["insider"])).json()
    assert {r["requirement_id"] for r in mine} == {by_org["id"], by_squad["id"]}
    assert {r["reviewer"]["type"] for r in mine} == {"org_group", "project_group"}
    theirs = client.get("/api/v1/me/reviews/due", headers=auth_headers(tokens["outsider"])).json()
    assert {r["requirement_id"] for r in theirs} == {other["id"]}

    base = f"/api/v1/projects/{pid}/requirements/reviews/due"
    by_group = client.get(base, params={"reviewer_type": "org_group", "reviewer_id": team}, headers=h).json()
    assert {r["requirement_id"] for r in by_group} == {by_org["id"]}
    mine_only = client.get(base, params={"reviewer_mine": "true"}, headers=auth_headers(tokens["insider"])).json()
    assert {r["requirement_id"] for r in mine_only} == {by_org["id"], by_squad["id"]}


def test_the_review_reminder_reaches_every_group_member_and_falls_back_to_managers(client, admin_token, org_id):
    from app.services.reviews import send_due_review_reminders

    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    first = create_org_user(client, admin_token, org_id, "req_remind_first@core.example.com", role="member")
    second = create_org_user(client, admin_token, org_id, "req_remind_second@core.example.com", role="member")
    empty = create_org_group(client, admin_token, org_id, "Nobody Reviews")
    team = create_org_group(client, admin_token, org_id, "Reminder Team", users=[first, second])
    pid = project["id"]
    grouped = _requirement(client, admin_token, pid, name="Grouped", reviewer=_org(team), review_date=_yesterday())
    orphan = _requirement(client, admin_token, pid, name="Orphan", reviewer=_org(empty), review_date=_yesterday())

    with SessionLocal() as db:
        send_due_review_reminders(db)

    def titles(token):
        rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
        return [r["entity_id"] for r in rows if r["type"] == "requirement_review_due"]

    # A reminder is read out of any project's context, so it names the requirement by its qualified code.
    rows = client.get("/api/v1/notifications", headers=auth_headers(login(client, "req_remind_first@core.example.com", "Password123!"))).json()
    assert [r["body"].split(" ")[0] for r in rows if r["type"] == "requirement_review_due"] == [
        f"{project['code']}-{grouped['unique_code']}",
    ]
    for email in ("req_remind_first@core.example.com", "req_remind_second@core.example.com"):
        assert titles(login(client, email, "Password123!")) == [grouped["id"]]
    # The empty group has nobody to notify, so the project manager hears about it instead.
    assert orphan["id"] in titles(admin_token) and grouped["id"] not in titles(admin_token)
    assert client.get(f"/api/v1/projects/{pid}/requirements/{orphan['id']}", headers=h).status_code == 200


def test_deleting_a_group_needs_a_replacement_for_owners_and_clears_reviewers(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    team = create_org_group(client, admin_token, org_id, "Req Doomed")
    h = auth_headers(admin_token)
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid, owner=_org(team), reviewer=_org(team))
    # Version 2 names someone else, version 3 names the group again: history must keep version 1's group.
    second = _put_requirement(client, admin_token, pid, requirement, owner=_user(me), reviewer=None).json()
    _put_requirement(client, admin_token, pid, second, owner=_org(team), reviewer=_org(team))
    group_url = f"/api/v1/orgs/{org_id}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("requirement owners", 1, True), ("requirement reviewers", 1, False),
    }, "older versions are not counted"
    assert client.delete(group_url, params={"clear_optional": "true"}, headers=h).status_code == 409  # owner needs a replacement
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    current = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=h).json()
    assert current["owner"]["id"] == me and current["reviewer"]["id"] == me
    history = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/history", headers=h).json()
    assert history[0]["owner"]["label"] == "Deleted group" and history[0]["owner"]["exists"] is False
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        assert {str(e.entity_id) for e in events} == {requirement["id"]}


def test_csv_export_writes_a_group_and_the_same_file_imports_it_back(client, admin_token, org_id):
    import csv
    import io

    project = create_project(client, admin_token, org_id)
    me_email = "admin@example.com"
    team = create_org_group(client, admin_token, org_id, "Csv Team")
    squad = create_project_group(client, admin_token, project["id"], "Csv Squad")
    pid = project["id"]
    _requirement(client, admin_token, pid, name="Grouped", owner=_org(team), reviewer=_project(squad))
    _requirement(client, admin_token, pid, name="Personal", owner=_user(_me(client, admin_token)))
    h = auth_headers(admin_token)

    def run(project_id, text, *, apply=True):
        resp = client.post(
            f"/api/v1/projects/{project_id}/records/requirement/import", params={"dry_run": "false" if apply else "true"},
            files={"file": ("r.csv", text.encode(), "text/csv")}, headers=h,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    exported = client.get(f"/api/v1/projects/{pid}/records/requirement/export", headers=h)
    assert exported.status_code == 200
    text = exported.content.decode("utf-8-sig")
    rows = {r["name"]: r for r in csv.DictReader(io.StringIO(text))}
    assert rows["Grouped"]["owner"] == "Csv Team (Org group)" and rows["Grouped"]["reviewer"] == "Csv Squad (Project group)"
    assert rows["Personal"]["owner"] == me_email and rows["Personal"]["reviewer"] == ""

    target = create_project(client, admin_token, org_id, "Csv Target")
    create_project_group(client, admin_token, target["id"], "Csv Squad")
    _scope(client, admin_token, target["id"])
    # The codes belong to the source project; blanking them makes every row a new record here.
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["code", "name", "component", "category", "owner", "reviewer"])
    writer.writeheader()
    for row in rows.values():
        writer.writerow({"code": "", **{k: row[k] for k in ("name", "component", "category", "owner", "reviewer")}})
    imported = run(target["id"], out.getvalue())
    assert imported["created"] == 2, imported
    copied = {r["name"]: r for r in client.get(f"/api/v1/projects/{target['id']}/requirements", headers=h).json()}
    assert copied["Grouped"]["owner"]["label"] == "Csv Team" and copied["Grouped"]["reviewer"]["type"] == "project_group"
    assert copied["Personal"]["owner"]["type"] == "user"

    component, category = rows["Grouped"]["component"], rows["Grouped"]["category"]
    bad = run(pid, f"name,component,category,owner\nUnknown,{component},{category},No Such Group\n")
    assert bad["created"] == 0 and bad["failed"] == 1
    assert "No Such Group" in bad["rows"][0]["message"]

    good = run(pid, f"name,component,category,owner,reviewer\nBy name,{component},{category},Csv Team,Csv Squad\n")
    assert good["created"] == 1, good
    made = next(r for r in client.get(f"/api/v1/projects/{pid}/requirements", headers=h).json() if r["name"] == "By name")
    assert made["owner"]["type"] == "org_group" and made["reviewer"]["type"] == "project_group"


def test_a_project_bundle_round_trips_requirement_people_and_reads_a_legacy_bundle(client, admin_token, org_id):
    import io
    import json
    import zipfile

    project = create_project(client, admin_token, org_id, "Req Bundle Source")
    h = auth_headers(admin_token)
    team = create_org_group(client, admin_token, org_id, "Bundle Req Team")
    squad = create_project_group(client, admin_token, project["id"], "Bundle Req Squad")
    me = _me(client, admin_token)
    pid = project["id"]
    _requirement(client, admin_token, pid, name="Grouped", owner=_org(team), reviewer=_project(squad))
    _requirement(client, admin_token, pid, name="Personal", owner=_user(me))
    exported = client.get(f"/api/v1/projects/{pid}/export", headers=h)
    doc = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    versions = {r["versions"][0]["name"]: r["versions"][0] for r in doc["requirements"]}
    assert versions["Grouped"]["owner"] == {"type": "org_group", "name": "Bundle Req Team"}
    assert versions["Grouped"]["reviewer"] == {"type": "project_group", "name": "Bundle Req Squad"}
    assert versions["Personal"]["owner"]["type"] == "user" and versions["Personal"]["reviewer"] is None

    def reimport(bundle: bytes, name: str) -> dict:
        resp = client.post(
            "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
            files={"file": ("bundle.zip", bundle, "application/zip")}, headers=h,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def rewritten(edit) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(exported.content)) as source, zipfile.ZipFile(out, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "project.json":
                    edited = json.loads(data)
                    edit(edited)
                    data = json.dumps(edited).encode()
                target.writestr(item, data)
        return out.getvalue()

    copy = reimport(exported.content, "Req Bundle Copy")
    copied = {r["name"]: r for r in client.get(f"/api/v1/projects/{copy['project']['id']}/requirements", headers=h).json()}
    assert copied["Grouped"]["owner"]["id"] == team
    assert copied["Grouped"]["reviewer"]["type"] == "project_group" and copied["Grouped"]["reviewer"]["id"] != squad
    assert copied["Personal"]["owner"]["id"] == me

    def unmatched(doc):
        for r in doc["requirements"]:
            for v in r["versions"]:
                if v["owner"]["type"] != "user":
                    v["owner"]["name"] = "Missing Group"

    fallback = reimport(rewritten(unmatched), "Req Bundle Unmatched")
    fell = {r["name"]: r for r in client.get(f"/api/v1/projects/{fallback['project']['id']}/requirements", headers=h).json()}
    assert fell["Grouped"]["owner"]["type"] == "user" and fell["Grouped"]["owner"]["id"] == me, "a mandatory owner falls back"
    assert any("Missing Group" in w for w in fallback["warnings"])

    def legacy(doc):
        for r in doc["requirements"]:
            for v in r["versions"]:
                owner = v.pop("owner")
                v["owner_email"] = owner["email"] if owner["type"] == "user" else "admin@example.com"
                v["reviewer_email"] = None
                v.pop("reviewer")

    old = reimport(rewritten(legacy), "Req Bundle Legacy")
    olds = client.get(f"/api/v1/projects/{old['project']['id']}/requirements", headers=h).json()
    assert {r["owner"]["id"] for r in olds} == {me}


def test_cloning_a_template_maps_a_project_group_owner_to_the_copy(client, admin_token, org_id):
    template = create_project(client, admin_token, org_id, "Owner Template")
    h = auth_headers(admin_token)
    squad = create_project_group(client, admin_token, template["id"], "Template Squad")
    team = create_org_group(client, admin_token, org_id, "Template Org Team")
    tid = template["id"]
    _requirement(client, admin_token, tid, name="Squad owned", owner=_project(squad))
    _requirement(client, admin_token, tid, name="Team owned", owner=_org(team))
    client.patch(f"/api/v1/projects/{tid}", json={"is_template": True}, headers=h)

    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Owner Clone", "summary": "", "template_project_id": tid}, headers=h,
    )
    assert resp.status_code == 201, resp.text
    new_id = resp.json()["id"]
    cloned = {r["name"]: r for r in client.get(f"/api/v1/projects/{new_id}/requirements", headers=h).json()}
    assert cloned["Team owned"]["owner"]["id"] == team
    new_groups = {g["name"]: g["id"] for g in client.get(f"/api/v1/projects/{new_id}/groups", headers=h).json()}
    assert cloned["Squad owned"]["owner"]["type"] == "project_group"
    assert cloned["Squad owned"]["owner"]["id"] == new_groups["Template Squad"] != squad


def test_a_change_request_proposes_a_group_reviewer_and_approval_applies_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    team = create_org_group(client, admin_token, org_id, "Proposed Reviewers")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core CR Reviewer Foreign Co")
    foreign = create_org_group(client, other_token, other_org["id"], "Foreign Reviewers")
    pid = project["id"]
    h = auth_headers(admin_token)
    requirement = _requirement(client, admin_token, pid, name="Locked")
    assert client.post(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/approve", headers=h).status_code == 200

    def propose(**extra):
        return client.post(
            f"/api/v1/projects/{pid}/change-requests",
            json={"kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["reviewer_id"], "reason": "r", **extra},
            headers=h,
        )

    assert propose(proposed_reviewer=_org(foreign)).status_code == 400
    created = propose(proposed_reviewer=_org(team))
    assert created.status_code == 201, created.text
    assert created.json()["proposed_reviewer"]["label"] == "Proposed Reviewers"
    _decide(client, admin_token, pid, created.json()["id"])
    applied = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=h).json()
    assert applied["reviewer"]["id"] == team and applied["owner"]["id"] == requirement["owner"]["id"]

    # A new-requirement proposal carries the reviewer into the created requirement.
    component_id, category_id = _scope(client, admin_token, pid)
    new_cr = client.post(
        f"/api/v1/projects/{pid}/change-requests",
        json={
            "kind": "new_requirement", "proposed_name": "Proposed", "proposed_component_id": component_id,
            "proposed_category_id": category_id, "reason": "r", "proposed_reviewer": _org(team),
        },
        headers=h,
    )
    assert new_cr.status_code == 201, new_cr.text
    _decide(client, admin_token, pid, new_cr.json()["id"])
    made = next(r for r in client.get(f"/api/v1/projects/{pid}/requirements", headers=h).json() if r["name"] == "Proposed")
    assert made["reviewer"]["id"] == team


def test_migration_0084_backfills_requirement_people_to_user(client, admin_token, org_id):
    from app.models.requirement import RequirementVersion

    project = create_project(client, admin_token, org_id)
    me = _me(client, admin_token)
    reviewed = _requirement(client, admin_token, project["id"], name="Reviewed", reviewer=_user(me))
    plain = _requirement(client, admin_token, project["id"], name="Plain")
    with engine.begin() as conn:  # the backfill labels every person a user, so leave no other test's group behind
        conn.execute(text("UPDATE requirement_versions SET reviewer_id = NULL, reviewer_type = NULL WHERE reviewer_type <> 'user'"))
        conn.execute(text("DELETE FROM requirement_versions WHERE owner_type <> 'user'"))
    command.downgrade(build_alembic_config(), "0083")
    try:
        with engine.begin() as conn:
            columns = conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'requirement_versions' "
                "AND column_name IN ('owner_type', 'reviewer_type')"
            )).all()
            assert columns == []
    finally:
        command.upgrade(build_alembic_config(), "head")
    with SessionLocal() as db:
        row = db.scalar(select(RequirementVersion).where(RequirementVersion.requirement_id == uuid.UUID(reviewed["id"])))
        assert (row.owner_type, str(row.owner_id), row.reviewer_type, str(row.reviewer_id)) == ("user", me, "user", me)
        other = db.scalar(select(RequirementVersion).where(RequirementVersion.requirement_id == uuid.UUID(plain["id"])))
        assert other.owner_type == "user" and other.reviewer_type is None and other.reviewer_id is None


# --- 6d: groups watching a record ---------------------------------------------------------------------


def _watchers_url(project_id, kind: str, record_id) -> str:
    return f"/api/v1/projects/{project_id}/{kind}/{record_id}/watchers"


def _comment_notifications(client, token, record_id) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r for r in rows if r["type"] == "comment_added" and r["entity_id"] == record_id]


def test_a_watching_group_notifies_its_members_who_can_view_the_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    pid = project["id"]
    emails = {n: f"watch_{n}@core.example.com" for n in ("insider", "no_access", "direct")}
    ids = {n: create_org_user(client, admin_token, org_id, e, role="member") for n, e in emails.items()}
    for name in ("insider", "direct"):
        client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": ids[name], "role": "stakeholder"}, headers=h)
    tokens = {n: login(client, e, "Password123!") for n, e in emails.items()}
    team = create_org_group(client, admin_token, org_id, "Watch Team", users=[ids["insider"], ids["no_access"]])
    requirement = _requirement(client, admin_token, pid)
    url = _watchers_url(pid, "requirements", requirement["id"])

    added = client.post(url, json={"group": _org(team)}, headers=h)
    assert added.status_code == 201, added.text
    assert [(w["type"], w["label"], w["member_count"]) for w in added.json()] == [("org_group", "Watch Team", 2)]
    assert client.post(url, json={"group": _org(team)}, headers=h).json() == added.json(), "adding again is idempotent"
    direct = client.put(
        f"/api/v1/projects/{pid}/requirements/{requirement['id']}/subscription", headers=auth_headers(tokens["direct"]),
    )
    assert direct.status_code == 204

    posted = client.post(
        f"/api/v1/projects/{pid}/requirements/{requirement['id']}/comments", json={"body": "Ping the watchers"}, headers=h,
    )
    assert posted.status_code == 201
    assert len(_comment_notifications(client, tokens["insider"], requirement["id"])) == 1
    assert len(_comment_notifications(client, tokens["direct"], requirement["id"])) == 1
    assert _comment_notifications(client, tokens["no_access"], requirement["id"]) == [], "no project access, so nothing leaks"

    got = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=auth_headers(tokens["insider"])).json()
    assert got["is_subscribed"] is False, "is_subscribed means the caller subscribed themselves"
    assert client.get(url, headers=auth_headers(tokens["insider"])).json() == added.json()

    removed = client.delete(f"{url}/org_group/{team}", headers=h)
    assert removed.status_code == 200 and removed.json() == []
    client.post(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/comments", json={"body": "Second"}, headers=h)
    assert len(_comment_notifications(client, tokens["insider"], requirement["id"])) == 1


def test_only_managers_add_watchers_and_only_groups_of_this_project_and_organisation(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other Watch Project")
    elsewhere = create_project_group(client, admin_token, other_project["id"], "Elsewhere Watchers")
    squad = create_project_group(client, admin_token, project["id"], "Watch Squad")
    other_org, other_token = create_org_admin_in(client, admin_token, "Core Watch Foreign Co")
    foreign = create_org_group(client, other_token, other_org["id"], "Foreign Watchers")
    h = auth_headers(admin_token)
    pid = project["id"]
    member = create_org_user(client, admin_token, org_id, "watch_plain@core.example.com", role="member")
    client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": member, "role": "stakeholder"}, headers=h)
    member_token = login(client, "watch_plain@core.example.com", "Password123!")
    requirement = _requirement(client, admin_token, pid)
    cr = _submitted_cr(client, admin_token, pid)
    for kind, record in (("requirements", requirement["id"]), ("change-requests", cr["id"])):
        url = _watchers_url(pid, kind, record)
        assert client.post(url, json={"group": _project(squad)}, headers=h).status_code == 201, kind
        for bad in (_user(_me(client, admin_token)), _org(foreign), _project(elsewhere), _org(uuid.uuid4())):
            assert client.post(url, json={"group": bad}, headers=h).status_code == 400, (kind, bad)
        assert client.post(url, json={"group": _project(squad)}, headers=auth_headers(member_token)).status_code == 403
        assert client.delete(f"{url}/project_group/{squad}", headers=auth_headers(member_token)).status_code == 403
        assert client.get(url, headers=auth_headers(member_token)).status_code == 200


def test_a_change_request_has_watching_groups_too_and_deleting_a_group_removes_its_subscriptions(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    pid = project["id"]
    insider = create_org_user(client, admin_token, org_id, "watch_cr@core.example.com", role="member")
    client.post(f"/api/v1/projects/{pid}/roles", json={"user_id": insider, "role": "stakeholder"}, headers=h)
    token = login(client, "watch_cr@core.example.com", "Password123!")
    team = create_org_group(client, admin_token, org_id, "CR Watchers", users=[insider])
    cr = _submitted_cr(client, admin_token, pid)
    url = _watchers_url(pid, "change-requests", cr["id"])
    assert client.post(url, json={"group": _org(team)}, headers=h).status_code == 201

    client.post(f"/api/v1/projects/{pid}/change-requests/{cr['id']}/comments", json={"body": "Heads up"}, headers=h)
    assert len(_comment_notifications(client, token, cr["id"])) == 1

    # A group's subscriptions are not records it owns: deleting the group needs no replacement and removes them.
    group_url = f"/api/v1/orgs/{org_id}/groups/{team}"
    assert client.get(f"{group_url}/usage", headers=h).json()["total"] == 0
    assert client.delete(group_url, headers=h).status_code == 204
    with SessionLocal() as db:
        left = db.execute(text("SELECT count(*) FROM subscriptions WHERE subscriber_id = :g"), {"g": team}).scalar()
        assert left == 0


def test_migration_0085_renames_and_backfills_subscriptions(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    h = auth_headers(admin_token)
    requirement = _requirement(client, admin_token, project["id"])
    assert client.put(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/subscription", headers=h).status_code == 204
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM subscriptions WHERE subscriber_type <> 'user'"))
    command.downgrade(build_alembic_config(), "0084")
    try:
        with engine.begin() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'subscriptions'"
            ))}
            assert "user_id" in columns and "subscriber_type" not in columns
    finally:
        command.upgrade(build_alembic_config(), "head")
    got = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=h).json()
    assert got["is_subscribed"] is True
