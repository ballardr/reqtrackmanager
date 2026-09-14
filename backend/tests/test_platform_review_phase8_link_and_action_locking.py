"""Tests for Platform review 2026-09, Phase 8:

1. `unlink_action` (`DELETE .../actions/{action_id}`) previously had no lock
   check at all, an asymmetry with the already-gated add side (item 514,
   `test_requirement_action_change_requests.py`). It's now gated the same
   way, unconditionally across every project, via a new `REMOVE_ACTION`
   change request kind.

2. A project (or an org-wide force, minus a per-project exemption) can now
   opt into requiring the same change-request-only-once-locked treatment
   for `RequirementLink` add/remove, via `ADD_LINK`/`REMOVE_LINK` change
   requests. Links stay ungated by default (`RequirementLink`'s own model
   docstring) — this is a deliberately narrower, opt-in sibling of the
   action gate, not a blanket extension of C-G-12's lock to every field.

See `services.requirements.requires_change_request_for_links` for the
formula this file's formula tests pin, and `routers.change_requests
.decide_change_request`'s REMOVE_ACTION/ADD_LINK/REMOVE_LINK branches for
the apply-on-approval behaviour.
"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def _link_types(client, token, org_id):
    return {lt["forward_name"]: lt["id"] for lt in client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()}


def _action_types(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve_requirement(client, token, project_id, requirement_id):
    resp = client.post(f"/api/v1/projects/{project_id}/requirements/{requirement_id}/approve", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit_and_decide(client, token, project_id, cr_id, approve=True):
    submitted = client.post(f"/api/v1/projects/{project_id}/change-requests/{cr_id}/submit", headers=auth_headers(token))
    assert submitted.status_code == 200, submitted.text
    decision = client.post(
        f"/api/v1/projects/{project_id}/change-requests/{cr_id}/decide",
        json={"approve": approve, "note": ""}, headers=auth_headers(token),
    )
    assert decision.status_code == 200, decision.text
    return decision.json()


def _set_project_link_lock(client, token, project_id, *, require=None, exempt=None):
    payload = {}
    if require is not None:
        payload["require_change_request_for_approved_links"] = require
    if exempt is not None:
        payload["exempt_from_org_link_lock"] = exempt
    resp = client.patch(f"/api/v1/projects/{project_id}", json=payload, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_org_force_link_lock(client, token, org_id, force: bool):
    resp = client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings",
        json={"force_require_change_request_for_approved_links": force},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit_events(entity_type, entity_id, action=None):
    db = SessionLocal()
    try:
        query = select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == str(entity_id))
        if action is not None:
            query = query.where(AuditEvent.action == action)
        return list(db.scalars(query))
    finally:
        db.close()


def _setup_locked_requirement(client, token, org_id):
    project = create_project(client, token, org_id)
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id)
    _approve_requirement(client, token, project["id"], requirement["id"])
    return project, requirement


# --- REMOVE_ACTION: unconditional, every project -------------------------


def test_unlink_action_directly_rejected_once_locked(client, admin_token, org_id):
    project, requirement = _setup_locked_requirement(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    # Link it via a change request (already gated), approve.
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    ).json()
    _submit_and_decide(client, admin_token, project["id"], cr["id"])

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/{action['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_unlink_action_still_works_directly_while_unlocked(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]}, headers=auth_headers(admin_token),
    )

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions/{action['id']}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def test_remove_action_change_request_unlinks_on_approval_and_is_audited(client, admin_token, org_id):
    project, requirement = _setup_locked_requirement(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    add_cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    ).json()
    _submit_and_decide(client, admin_token, project["id"], add_cr["id"])

    remove_cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "remove_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "superseded",
        },
        headers=auth_headers(admin_token),
    )
    assert remove_cr.status_code == 201, remove_cr.text
    cr_id = remove_cr.json()["id"]

    before = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert len(before) == 1

    _submit_and_decide(client, admin_token, project["id"], cr_id, approve=True)

    after = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions", headers=auth_headers(admin_token)
    ).json()
    assert after == []

    events = _audit_events("requirement_action_link", action["id"], action="unlinked")
    assert len(events) == 1
    assert events[0].detail["via"] == "change_request"
    assert events[0].detail["change_request_id"] == cr_id


def test_remove_action_change_request_rejected_against_still_draft_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Shared review", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]}, headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "remove_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_remove_action_change_request_rejected_when_action_not_linked(client, admin_token, org_id):
    project, requirement = _setup_locked_requirement(client, admin_token, org_id)
    action_type_id = _action_types(client, admin_token, project["id"])[0]["id"]
    action = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Never linked", "action_type_id": action_type_id},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "remove_action", "requirement_id": requirement["id"],
            "proposed_action_link_id": action["id"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


# --- Links: opt-in, formula --------------------------------------------


def test_create_link_ungated_by_default_even_when_locked(client, admin_token, org_id):
    """`require_change_request_for_approved_links` defaults false and the
    org's own force defaults false too — links stay ungated by default,
    matching `RequirementLink`'s existing design even once locked."""
    org, token = create_org_admin_in(client, admin_token, "Link Lock Default Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    _approve_requirement(client, token, project["id"], a["id"])
    link_types = _link_types(client, token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def test_create_link_rejected_when_project_requires_cr_and_locked(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Link Lock Project Opt-in Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    _approve_requirement(client, token, project["id"], a["id"])
    link_types = _link_types(client, token, org["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 409, resp.text


def test_create_link_allowed_directly_when_locked_for_links_but_requirement_unlocked(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Link Lock Unlocked Requirement Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def test_delete_link_rejected_when_project_requires_cr_and_locked(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Link Lock Delete Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])
    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    ).json()
    _approve_requirement(client, token, project["id"], a["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links/{link['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 409, resp.text


def test_requires_change_request_for_links_formula_all_four_combinations(client, admin_token, org_id):
    """`requires_change_request_for_links`: project's own opt-in always
    wins when set; otherwise the org's force applies unless this project
    is marked exempt; otherwise ungated. Pinned directly against
    `create_link`'s 409 rather than re-deriving the formula in the test."""
    org, token = create_org_admin_in(client, admin_token, "Link Lock Formula Org")

    def make_locked_pair(name):
        project = create_project(client, token, org["id"], name)
        component_id, category_id = create_component_and_category(client, token, project["id"])
        a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
        b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
        _approve_requirement(client, token, project["id"], a["id"])
        return project, a, b

    link_types = _link_types(client, token, org["id"])

    def try_link(project, a, b):
        return client.post(
            f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
            json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
            headers=auth_headers(token),
        )

    # project=off, org=off -> ungated (201).
    _set_org_force_link_lock(client, token, org["id"], False)
    project, a, b = make_locked_pair("Formula Off Off")
    _set_project_link_lock(client, token, project["id"], require=False, exempt=False)
    assert try_link(project, a, b).status_code == 201

    # project=on, org=off -> gated (409) by the project's own opt-in.
    project, a, b = make_locked_pair("Formula On Off")
    _set_project_link_lock(client, token, project["id"], require=True, exempt=False)
    assert try_link(project, a, b).status_code == 409

    # project=off, org=on, not exempt -> gated (409) by the org force.
    _set_org_force_link_lock(client, token, org["id"], True)
    project, a, b = make_locked_pair("Formula Off On NotExempt")
    _set_project_link_lock(client, token, project["id"], require=False, exempt=False)
    assert try_link(project, a, b).status_code == 409

    # project=off, org=on, exempt -> ungated (201) via the exemption.
    project, a, b = make_locked_pair("Formula Off On Exempt")
    _set_project_link_lock(client, token, project["id"], require=False, exempt=True)
    assert try_link(project, a, b).status_code == 201

    _set_org_force_link_lock(client, token, org["id"], False)


def test_add_link_change_request_creates_link_on_approval_and_is_audited(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Add Link CR Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    _approve_requirement(client, token, project["id"], a["id"])
    link_types = _link_types(client, token, org["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": a["id"],
            "proposed_link_target_requirement_id": b["id"], "proposed_link_type_id": link_types["Related to"],
            "reason": "traceability gap",
        },
        headers=auth_headers(token),
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]

    before = client.get(f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)).json()
    assert before == []

    _submit_and_decide(client, token, project["id"], cr_id, approve=True)

    after = client.get(f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)).json()
    assert len(after) == 1
    assert after[0]["other_requirement_id"] == b["id"]

    events = _audit_events("requirement_link", after[0]["id"], action="created")
    assert len(events) == 1
    assert events[0].detail["via"] == "change_request"
    assert events[0].detail["change_request_id"] == cr_id


def test_remove_link_change_request_deletes_link_on_approval_and_is_audited(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Remove Link CR Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])
    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    ).json()
    _approve_requirement(client, token, project["id"], a["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "remove_link", "requirement_id": a["id"], "proposed_link_id": link["id"], "reason": "created in error"},
        headers=auth_headers(token),
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]

    _submit_and_decide(client, token, project["id"], cr_id, approve=True)

    after = client.get(f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links", headers=auth_headers(token)).json()
    assert after == []

    events = _audit_events("requirement_link", link["id"], action="deleted")
    assert len(events) == 1
    assert events[0].detail["via"] == "change_request"
    assert events[0].detail["change_request_id"] == cr_id


def test_add_link_change_request_rejected_when_project_does_not_require_it(client, admin_token, org_id):
    """Once locked, `create_link` (direct) stays ungated by default — so a
    caller has no reason to route through a change request, and the
    endpoint rejects the attempt rather than silently accepting a CR that
    would never be forced anyway."""
    org, token = create_org_admin_in(client, admin_token, "Add Link CR Not Required Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    _approve_requirement(client, token, project["id"], a["id"])
    link_types = _link_types(client, token, org["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": a["id"],
            "proposed_link_target_requirement_id": b["id"], "proposed_link_type_id": link_types["Related to"],
            "reason": "x",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


def test_add_link_change_request_rejected_against_still_draft_requirement(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Add Link CR Draft Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    link_types = _link_types(client, token, org["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": a["id"],
            "proposed_link_target_requirement_id": b["id"], "proposed_link_type_id": link_types["Related to"],
            "reason": "x",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


def test_add_link_change_request_rejects_target_from_another_project(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Add Link CR Cross Project Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    _approve_requirement(client, token, project["id"], a["id"])
    _set_project_link_lock(client, token, project["id"], require=True)
    link_types = _link_types(client, token, org["id"])

    other_project = create_project(client, token, org["id"], "Other Project")
    other_component_id, other_category_id = create_component_and_category(client, token, other_project["id"])
    other_requirement = _create_requirement(client, token, other_project["id"], other_component_id, other_category_id, "Elsewhere")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": a["id"],
            "proposed_link_target_requirement_id": other_requirement["id"], "proposed_link_type_id": link_types["Related to"],
            "reason": "x",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


def test_remove_link_change_request_rejects_a_link_not_touching_the_requirement(client, admin_token, org_id):
    org, token = create_org_admin_in(client, admin_token, "Remove Link CR IDOR Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    a = _create_requirement(client, token, project["id"], component_id, category_id, "A")
    b = _create_requirement(client, token, project["id"], component_id, category_id, "B")
    c = _create_requirement(client, token, project["id"], component_id, category_id, "C")
    link_types = _link_types(client, token, org["id"])
    link = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{a['id']}/links",
        json={"target_requirement_id": b["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(token),
    ).json()
    _approve_requirement(client, token, project["id"], c["id"])
    _set_project_link_lock(client, token, project["id"], require=True)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "remove_link", "requirement_id": c["id"], "proposed_link_id": link["id"], "reason": "x"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text
