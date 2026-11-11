"""Stage workflows: custom phases with kinds, the two tiers, hide and restore, kind-driven behaviour,
free movement with the locked-phase approver rule, nesting and bundles."""

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.services.report_fields import load_records
from app.services.stages import auto_approve_overdue_stage_reviews
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login
from tests.stage_helpers import move_stage

OUTSOURCED = {
    "name": "Outsourced work",
    "phases": [
        {"name": "Scoping", "kind": "open"},
        {"name": "Technical scoping", "kind": "open"},
        {"name": "Review board", "kind": "review"},
        {"name": "Tendering", "kind": "on_hold"},
        {"name": "Awarded", "kind": "locked"},
        {"name": "In progress", "kind": "locked"},
        {"name": "Completion", "kind": "closed"},
    ],
}


def _org_url(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/stage-workflows"


def _project_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/stage-workflows"


def _stages(client, token, project_id) -> list[dict]:
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()


def _make_workflow(client, token, org_id, body=OUTSOURCED) -> dict:
    resp = client.post(_org_url(org_id), json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _phase_id(workflow: dict, name: str) -> str:
    return next(p["id"] for p in workflow["phases"] if p["name"] == name)


def test_a_new_organisation_starts_with_the_standard_workflow(client, admin_token, org_id):
    workflows = client.get(_org_url(org_id), headers=auth_headers(admin_token)).json()
    assert [w["name"] for w in workflows] == ["Standard"]
    assert [(p["name"], p["kind"]) for p in workflows[0]["phases"]] == [
        ("Scoping", "open"), ("Review", "review"), ("Approved", "locked"), ("Completed", "closed"), ("Archived", "on_hold"),
    ]
    project = create_project(client, admin_token, org_id)
    stage = _stages(client, admin_token, project["id"])[0]
    assert (stage["workflow_name"], stage["phase_name"], stage["phase_kind"]) == ("Standard", "Scoping", "open")


def test_workflow_validation(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    assert client.post(_org_url(org_id), json={"name": "Empty", "phases": []}, headers=headers).status_code == 400
    duplicate = {"name": "Dup", "phases": [{"name": "A", "kind": "open"}, {"name": "a", "kind": "closed"}]}
    assert client.post(_org_url(org_id), json=duplicate, headers=headers).status_code == 400
    blank = {"name": "  ", "phases": [{"name": "A", "kind": "open"}]}
    assert client.post(_org_url(org_id), json=blank, headers=headers).status_code == 400
    bad_kind = {"name": "Odd", "phases": [{"name": "A", "kind": "finished"}]}
    assert client.post(_org_url(org_id), json=bad_kind, headers=headers).status_code == 422
    assert client.post(_org_url(org_id), json={"name": "standard", "phases": [{"name": "A", "kind": "open"}]}, headers=headers).status_code == 409


def test_only_organisation_administrators_manage_organisation_workflows(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "plain@example.com")
    token = login(client, "plain@example.com", "Password123!")
    assert client.get(_org_url(org_id), headers=auth_headers(token)).status_code == 403
    assert client.post(_org_url(org_id), json=OUTSOURCED, headers=auth_headers(token)).status_code == 403


def test_a_stage_follows_a_chosen_workflow_from_its_starting_phase(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    created = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    assert (created.json()["workflow_name"], created.json()["phase_name"]) == ("Outsourced work", "Scoping")
    unknown = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Other", "workflow_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(admin_token),
    )
    assert unknown.status_code == 400


def test_a_custom_locked_phase_baselines_whatever_it_is_called(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Deliver on time", "component_id": component_id, "category_id": category_id}, headers=headers,
    ).json()
    stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]}, headers=headers,
    ).json()

    # A review-kind phase and an on-hold phase change nothing about the requirements.
    assert move_stage(client, project["id"], stage["id"], "Review board", headers=headers).status_code == 200
    assert move_stage(client, project["id"], stage["id"], "Tendering", headers=headers).status_code == 200
    unchanged = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=headers).json()
    assert unchanged["status"] == "draft"

    awarded = move_stage(client, project["id"], stage["id"], "Awarded", headers=headers)
    assert awarded.status_code == 200, awarded.text
    assert awarded.json()["phase_kind"] == "locked" and awarded.json()["approved_at"] is not None
    locked = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=headers).json()
    assert locked["status"] == "approved"

    # Moving between two locked phases is another baseline-free step but still a locked entry.
    assert move_stage(client, project["id"], stage["id"], "In progress", headers=headers).status_code == 200
    done = move_stage(client, project["id"], stage["id"], "Completion", headers=headers)
    assert done.status_code == 200 and done.json()["completed_at"] is not None
    reopened = move_stage(client, project["id"], stage["id"], "In progress", headers=headers)
    assert reopened.status_code == 200 and reopened.json()["completed_at"] is None


def test_locked_phases_need_a_project_manager_to_enter_or_leave(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_org_user(client, admin_token, org_id, "pa@example.com")
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    user_id = next(u["user_id"] for u in users if u["email"] == "pa@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_administrator"},
        headers=auth_headers(admin_token),
    )
    admin_only = login(client, "pa@example.com", "Password123!")
    stage_id = _stages(client, admin_token, project["id"])[0]["id"]

    assert move_stage(client, project["id"], stage_id, "approved", headers=auth_headers(admin_only)).status_code == 403
    assert move_stage(client, project["id"], stage_id, "approved", headers=auth_headers(admin_token)).status_code == 200
    # Leaving a locked phase would unlock requirements outside the change-request process.
    assert move_stage(client, project["id"], stage_id, "scoping", headers=auth_headers(admin_only)).status_code == 403
    assert move_stage(client, project["id"], stage_id, "scoping", headers=auth_headers(admin_token)).status_code == 200
    # Everything else is free for a manager.
    assert move_stage(client, project["id"], stage_id, "archived", headers=auth_headers(admin_only)).status_code == 200
    assert move_stage(client, project["id"], stage_id, "review", headers=auth_headers(admin_only)).status_code == 200


def test_a_phase_of_another_workflow_is_refused(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    stage_id = _stages(client, admin_token, project["id"])[0]["id"]
    resp = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition",
        json={"phase_id": _phase_id(workflow, "Awarded")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_review_deadline_and_responses_follow_the_review_kind(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]}, headers=headers,
    ).json()
    deadline = {"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    url = f"/api/v1/projects/{project['id']}/stages/{stage['id']}/review-deadline"
    assert client.post(url, json=deadline, headers=headers).status_code == 409
    move_stage(client, project["id"], stage["id"], "Review board", headers=headers)
    assert client.post(url, json=deadline, headers=headers).status_code == 200

    db = SessionLocal()
    try:
        auto_approve_overdue_stage_reviews(db)
    finally:
        db.close()
    after = next(s for s in _stages(client, admin_token, project["id"]) if s["id"] == stage["id"])
    # The sweep moves a review stage into the workflow's next locked phase, here "Awarded".
    assert (after["phase_name"], after["phase_kind"]) == ("Awarded", "locked")


def test_a_review_phase_with_no_locked_phase_to_enter_is_left_alone(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id, {
        "name": "Review only", "phases": [{"name": "Draft", "kind": "open"}, {"name": "Reviewing", "kind": "review"}],
    })
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Docs", "workflow_id": workflow["id"]}, headers=headers,
    ).json()
    move_stage(client, project["id"], stage["id"], "Reviewing", headers=headers)
    client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}/review-deadline",
        json={"review_deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()}, headers=headers,
    )
    db = SessionLocal()
    try:
        auto_approve_overdue_stage_reviews(db)
    finally:
        db.close()
    after = next(s for s in _stages(client, admin_token, project["id"]) if s["id"] == stage["id"])
    assert after["phase_name"] == "Reviewing"


def test_editing_a_workflow_in_use(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]}, headers=headers,
    ).json()
    move_stage(client, project["id"], stage["id"], "Awarded", headers=headers)

    def phases_with(**changes):
        out = []
        for p in workflow["phases"]:
            entry = {"id": p["id"], "name": p["name"], "kind": p["kind"]}
            if p["name"] == "Awarded":
                entry.update(changes)
            out.append(entry)
        return out

    url = f"{_org_url(org_id)}/{workflow['id']}"

    def save(phases):
        return client.put(url, json={"name": "Outsourced work", "phases": phases}, headers=headers)

    renamed = save(phases_with(name="Contract awarded"))
    assert renamed.status_code == 200, renamed.text
    assert any(p["name"] == "Contract awarded" for p in renamed.json()["phases"])
    assert renamed.json()["in_use"] is True

    # A phase a stage is in cannot become another kind (it would silently unlock the stage) or be removed.
    assert save(phases_with(kind="open")).status_code == 409
    without = [p for p in phases_with() if p["name"] != "Awarded"]
    assert save(without).status_code == 409
    assert client.delete(f"{_org_url(org_id)}/{workflow['id']}", headers=headers).status_code == 409

    # An unused phase can be removed, and the order is kept as given.
    kept = [p for p in phases_with() if p["name"] != "Tendering"]
    resp = save(kept)
    assert resp.status_code == 200, resp.text
    assert [p["name"] for p in resp.json()["phases"]] == [p["name"] for p in kept]


def test_an_unused_workflow_can_be_deleted(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    assert client.delete(f"{_org_url(org_id)}/{workflow['id']}", headers=headers).status_code == 204
    assert [w["name"] for w in client.get(_org_url(org_id), headers=headers).json()] == ["Standard"]


def test_a_project_hides_and_restores_an_organisation_workflow(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    assert {w["name"] for w in client.get(_project_url(project["id"]), headers=headers).json()} == {"Standard", "Outsourced work"}

    assert client.delete(f"{_project_url(project['id'])}/{workflow['id']}", headers=headers).status_code == 204
    assert [w["name"] for w in client.get(_project_url(project["id"]), headers=headers).json()] == ["Standard"]
    assert [w["name"] for w in client.get(f"{_project_url(project['id'])}/hidden", headers=headers).json()] == ["Outsourced work"]
    # A hidden workflow cannot be chosen for a new stage; the organisation still lists it.
    refused = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]}, headers=headers,
    )
    assert refused.status_code == 400
    assert len(client.get(_org_url(org_id), headers=headers).json()) == 2

    # The last usable workflow cannot be hidden.
    standard = next(w for w in client.get(_project_url(project["id"]), headers=headers).json() if w["name"] == "Standard")
    assert client.delete(f"{_project_url(project['id'])}/{standard['id']}", headers=headers).status_code == 409

    restored = client.post(f"{_project_url(project['id'])}/restore", json={}, headers=headers)
    assert [w["name"] for w in restored.json()] == ["Outsourced work"]
    assert {w["name"] for w in client.get(_project_url(project["id"]), headers=headers).json()} == {"Standard", "Outsourced work"}

    # Deleting the organisation workflow drops no stage, and clears any hidden marker with it.
    client.delete(f"{_project_url(project['id'])}/{workflow['id']}", headers=headers)
    assert client.delete(f"{_org_url(org_id)}/{workflow['id']}", headers=headers).status_code == 204
    assert client.get(f"{_project_url(project['id'])}/hidden", headers=headers).json() == []


def test_project_workflows_are_the_projects_own_and_children_fall_back_to_the_nearest_ancestor(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    parent = create_project(client, admin_token, org_id, name="Parent", can_be_parent=True)
    created = client.post(_project_url(parent["id"]), json=OUTSOURCED, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "project"
    child = create_project(client, admin_token, org_id, name="Child", parent_project_id=parent["id"])
    assert {w["name"] for w in client.get(_project_url(child["id"]), headers=headers).json()} == {"Standard", "Outsourced work"}

    own = client.post(_project_url(child["id"]), json={"name": "Child only", "phases": [{"name": "Go", "kind": "open"}]}, headers=headers)
    assert own.status_code == 201
    assert {w["name"] for w in client.get(_project_url(child["id"]), headers=headers).json()} == {"Standard", "Child only"}

    # An organisation workflow is read-only inside a project, and another project's workflow is not reachable.
    standard_id = next(w["id"] for w in client.get(_org_url(org_id), headers=headers).json())
    body = {"name": "Standard", "phases": [{"name": "Only", "kind": "open"}]}
    assert client.put(f"{_project_url(child['id'])}/{standard_id}", json=body, headers=headers).status_code == 404
    assert client.put(f"{_project_url(child['id'])}/{created.json()['id']}", json=body, headers=headers).status_code == 404


def test_a_stage_changes_workflow_only_while_open_and_unbaselined(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    stage = _stages(client, admin_token, project["id"])[0]
    url = f"/api/v1/projects/{project['id']}/stages/{stage['id']}"
    moved = client.patch(url, json={"name": stage["name"], "workflow_id": workflow["id"]}, headers=headers)
    assert moved.status_code == 200, moved.text
    assert (moved.json()["workflow_name"], moved.json()["phase_name"]) == ("Outsourced work", "Scoping")

    move_stage(client, project["id"], stage["id"], "Awarded", headers=headers)
    standard_id = next(w["id"] for w in client.get(_org_url(org_id), headers=headers).json() if w["name"] == "Standard")
    refused = client.patch(url, json={"name": stage["name"], "workflow_id": standard_id}, headers=headers)
    assert refused.status_code == 409


def test_workflows_and_stage_phases_round_trip_through_the_project_bundle(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id, name="Bundle source")
    own = client.post(
        _project_url(project["id"]), json={"name": "Local", "phases": [{"name": "Go", "kind": "open"}, {"name": "Hold", "kind": "on_hold"}]},
        headers=headers,
    ).json()
    client.delete(f"{_project_url(project['id'])}/{workflow['id']}", headers=headers)
    stage = _stages(client, admin_token, project["id"])[0]
    client.patch(
        f"/api/v1/projects/{project['id']}/stages/{stage['id']}", json={"name": stage["name"], "workflow_id": own["id"]}, headers=headers,
    )
    move_stage(client, project["id"], stage["id"], "Hold", headers=headers)

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)
    zf = zipfile.ZipFile(io.BytesIO(export.content))
    assert b"Local" in zf.read("project.json")

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Bundle copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    assert imported.json()["warnings"] == []
    assert {w["name"] for w in client.get(_project_url(new_id), headers=headers).json()} == {"Standard", "Local"}
    assert [w["name"] for w in client.get(f"{_project_url(new_id)}/hidden", headers=headers).json()] == ["Outsourced work"]
    copied = _stages(client, admin_token, new_id)[0]
    assert (copied["workflow_name"], copied["phase_name"], copied["phase_kind"]) == ("Local", "Hold", "on_hold")


def test_an_imported_stage_never_arrives_in_a_locked_phase(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    project = create_project(client, admin_token, org_id, name="Locked source")
    stage_id = _stages(client, admin_token, project["id"])[0]["id"]
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Locked copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    assert any("Approved" in w for w in imported.json()["warnings"])
    copied = _stages(client, admin_token, imported.json()["project"]["id"])[0]
    assert (copied["phase_name"], copied["phase_kind"]) == ("Scoping", "open")


def test_workflows_round_trip_through_the_organisation_bundle(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    _make_workflow(client, admin_token, org_id)
    export = client.get(f"/api/v1/orgs/{org_id}/export", headers=headers)
    assert export.status_code == 200, export.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Org copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    new_org_id = imported.json()["organization"]["id"]
    names = {w["name"]: [p["kind"] for p in w["phases"]] for w in client.get(_org_url(new_org_id), headers=headers).json()}
    assert set(names) == {"Standard", "Outsourced work"}
    assert names["Outsourced work"] == ["open", "open", "review", "on_hold", "locked", "locked", "closed"]


def test_requirements_report_the_phase_and_kind_of_their_target_stage(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    workflow = _make_workflow(client, admin_token, org_id)
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stage = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Build", "workflow_id": workflow["id"]}, headers=headers,
    ).json()
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Reported", "component_id": component_id, "category_id": category_id, "target_stage_id": stage["id"]},
        headers=headers,
    ).json()
    assert move_stage(client, project["id"], stage["id"], "Tendering", headers=headers).status_code == 200

    db = SessionLocal()
    try:
        values = load_records(
            db, "requirement", [uuid.UUID(requirement["id"])], ["target_stage_phase", "target_stage_phase_kind"],
        )[uuid.UUID(requirement["id"])].values
    finally:
        db.close()
    assert values["target_stage_phase"] == "Tendering"
    assert values["target_stage_phase_kind"] == "On hold"


def test_a_workflow_reports_who_follows_it_without_naming_another_projects_stages(client, admin_token, org_id):
    workflow = _make_workflow(client, admin_token, org_id)
    mine = create_project(client, admin_token, org_id, "Usage Mine")
    other = create_project(client, admin_token, org_id, "Usage Other")
    for project, stage_name in ((mine, "Design stage"), (other, "Secret stage")):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/stages", json={"name": stage_name, "workflow_id": workflow["id"]},
            headers=auth_headers(admin_token),
        )
        assert resp.status_code == 201, resp.text

    in_project = next(
        w for w in client.get(_project_url(mine["id"]), headers=auth_headers(admin_token)).json() if w["id"] == workflow["id"]
    )["used_by"]
    assert in_project["stage_names"] == ["Design stage"]
    assert (in_project["stage_count"], in_project["project_count"]) == (1, 1)

    across = next(
        w for w in client.get(_org_url(org_id), headers=auth_headers(admin_token)).json() if w["id"] == workflow["id"]
    )["used_by"]
    assert across["stage_names"] == []  # the organisation tier reports counts, never stage names
    assert (across["stage_count"], across["project_count"]) == (2, 2)

    unused = _make_workflow(client, admin_token, org_id, {"name": "Unused", "phases": [{"name": "Only", "kind": "open"}]})
    assert unused["used_by"] == {"stage_names": [], "stage_count": 0, "track_count": 0, "project_count": 0}


def test_the_stage_list_says_whether_the_caller_may_use_locked_phases(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Lock Flag")
    create_org_user(client, admin_token, org_id, "lock_flag_pa@example.com")
    users = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    user_id = next(u["user_id"] for u in users if u["email"] == "lock_flag_pa@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_administrator"},
        headers=auth_headers(admin_token),
    )
    administrator = login(client, "lock_flag_pa@example.com", "Password123!")
    can_lock = lambda token: [s["can_lock"] for s in _stages(client, token, project["id"])]  # noqa: E731
    assert can_lock(admin_token) == [True]
    assert can_lock(administrator) == [False]
