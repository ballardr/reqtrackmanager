"""Tests for links proposed on change requests (docs/plans/platform-enhancements-2026-10-plan.md
Phase 6b): proposing links on new / modify / add-link requests, the merge preview that
re-validates each link at read time, approval merging all (the default), a subset or none,
the recorded outcome per link, the audit trail, the notification counts, the finder accepting a
record that does not exist yet, and the migration of old ADD_LINK requests.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left
by another test or run.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.relationship import ArtefactLink
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, build_alembic_config, create_org_user, login
from tests.link_world import REQ, World

DEC = "decision"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "CR Links Org", decisions=True)


def _cr_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/change-requests{suffix}"


def _approved(world: World, project: dict, name: str = "Target") -> uuid.UUID:
    req = world.requirement(project, name)
    resp = world.client.post(f"/api/v1/projects/{project['id']}/requirements/{req}/approve", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return req


def _proposal(link_type_id, other_type: str, other_id, *, direction: str = "outgoing", other_project: dict | None = None) -> dict:
    body = {"link_type_id": str(link_type_id), "direction": direction, "other_type": other_type, "other_id": str(other_id)}
    if other_project is not None:
        body["other_project_id"] = other_project["id"]
    return body


def _modify(world: World, project: dict, req: uuid.UUID, links: list[dict], token: str | None = None):
    """POSTs a modify-requirement change request (renaming it) carrying `links`."""
    return world.client.post(
        _cr_url(project),
        json={
            "kind": "modify_requirement", "requirement_id": str(req), "changed_fields": ["name"],
            "proposed_name": "Renamed by request", "reason": "needs traceability", "proposed_links": links,
        },
        headers=auth_headers(token or world.token),
    )


def _submit(world: World, project: dict, cr_id: str, token: str | None = None):
    resp = world.client.post(_cr_url(project, f"/{cr_id}/submit"), headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text


def _decide(world: World, project: dict, cr_id: str, *, approve: bool = True, merge: list[str] | None = None, token=None):
    body: dict = {"approve": approve, "note": ""}
    if merge is not None:
        body["merge_link_ids"] = merge
    return world.client.post(_cr_url(project, f"/{cr_id}/decide"), json=body, headers=auth_headers(token or world.token))


def _preview(world: World, project: dict, cr_id: str, token: str | None = None):
    return world.client.get(_cr_url(project, f"/{cr_id}/link-merge-preview"), headers=auth_headers(token or world.token))


def _cr(world: World, project: dict, cr_id: str) -> dict:
    resp = world.client.get(_cr_url(project, f"/{cr_id}"), headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _links_of(*artefact_ids: uuid.UUID) -> list[ArtefactLink]:
    db = SessionLocal()
    try:
        return list(db.scalars(
            select(ArtefactLink).where(ArtefactLink.source_id.in_(artefact_ids) | ArtefactLink.target_id.in_(artefact_ids))
        ).all())
    finally:
        db.close()


def _audit(entity_type: str, action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == entity_type, AuditEvent.action == action
        )).all())
    finally:
        db.close()


def _member(world: World, project: dict, role: str = "member") -> tuple[str, str]:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return user_id, login(world.client, email, "Password123!")


def _linker(world: World, project: dict) -> tuple[str, str, str]:
    """A project member who may link requirements (`requirement:link` through a custom role);
    returns `(user_id, token, role_id)`."""
    user_id, token = _member(world, project)
    role = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-roles",
        json={
            "name": f"Linker {uuid.uuid4().hex[:6]}", "description": "", "scope": "project",
            "permissions": [encode_permission(REQ, "link")],
        },
        headers=auth_headers(world.token),
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]
    grant = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-roles/{role_id}/users/{user_id}", json={"project_id": project["id"]},
        headers=auth_headers(world.token),
    )
    assert grant.status_code == 204, grant.text
    return user_id, token, role_id


@pytest.fixture
def scene(world):
    """A project with an approved requirement, two other requirements, a decision and two link types."""
    project = world.project("P")
    return {
        "project": project,
        "target": _approved(world, project),
        "b": world.requirement(project, "B"),
        "c": world.requirement(project, "C"),
        "dec": world.decision(project),
        "related": world.link_types_by_name()["Related to"]["id"],
        "depends": world.link_types_by_name()["Depends on"]["id"],
    }


# --- proposing ----------------------------------------------------------------------------------


def test_a_modify_request_carries_proposed_links_that_read_back_with_their_phrase_and_far_end(world, scene):
    p = scene["project"]
    resp = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]),
        _proposal(scene["depends"], DEC, scene["dec"], direction="incoming"),
    ])
    assert resp.status_code == 201, resp.text
    body = _cr(world, p, resp.json()["id"])
    assert body["proposed_link_count"] == 2
    first, second = body["proposed_links"]
    assert (first["phrase"], first["outcome"]) == ("Related to", "pending") and first["other_label"].endswith(" B")
    assert second["direction"] == "incoming" and second["phrase"] == "Is a dependency of"  # the reverse name, read from the requirement
    assert second["other_type_label"] == "Decision"

    listed = world.client.get(_cr_url(p), headers=auth_headers(world.token)).json()
    assert listed[0]["proposed_link_count"] == 2 and listed[0]["proposed_links"] == []  # the list view carries only the count


def test_nothing_changes_until_approval(world, scene):
    p = scene["project"]
    assert _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).status_code == 201
    assert _links_of(scene["target"]) == []
    graph = world.graph(p, (REQ, scene["target"])).json()
    assert graph["edges"] == []  # a proposed link is not a link, so it never shows in the panel or the graph


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda s: _proposal(s["related"], REQ, s["target"]), id="self-link"),
        pytest.param(lambda s: _proposal(s["related"], REQ, uuid.uuid4()), id="missing record"),
        pytest.param(lambda s: _proposal(s["related"], "no_such_type", s["b"]), id="unregistered type"),
        pytest.param(lambda s: _proposal(uuid.uuid4(), REQ, s["b"]), id="unknown link type"),
    ],
)
def test_an_invalid_proposed_link_is_refused_at_creation(world, scene, build):
    resp = _modify(world, scene["project"], scene["target"], [build(scene)])
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"].startswith("Proposed link 1:")


def test_a_repeated_link_in_one_request_is_refused(world, scene):
    link = _proposal(scene["related"], REQ, scene["b"])
    resp = _modify(world, scene["project"], scene["target"], [link, link])
    assert resp.status_code == 400 and "repeats" in resp.json()["detail"]


def test_an_already_existing_link_is_refused_at_creation(world, scene):
    p = scene["project"]
    assert world.generic_link(p, (REQ, scene["target"]), scene["related"], (REQ, scene["b"])).status_code == 201
    resp = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])])
    assert resp.status_code == 400 and "already linked" in resp.json()["detail"]


def test_a_hidden_link_type_cannot_be_proposed(world, scene):
    p = scene["project"]
    hide = world.client.put(
        f"/api/v1/projects/{p['id']}/link-types/{scene['related']}/visibility", json={"hidden": True},
        headers=auth_headers(world.token),
    )
    assert hide.status_code == 200, hide.text
    resp = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])])
    assert resp.status_code == 400 and "hidden" in resp.json()["detail"]


def test_links_are_refused_on_kinds_that_do_not_create_them(world, scene):
    p = scene["project"]
    types = world.client.get(f"/api/v1/projects/{p['id']}/action-types", headers=auth_headers(world.token)).json()
    resp = world.client.post(
        _cr_url(p),
        json={
            "kind": "add_action", "requirement_id": str(scene["target"]), "proposed_action_title": "Do it",
            "proposed_action_type_id": types[0]["id"], "reason": "x",
            "proposed_links": [_proposal(scene["related"], REQ, scene["b"])],
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 400 and "new, modify or add-link" in resp.json()["detail"]


def test_an_add_link_request_needs_at_least_one_link(world, scene):
    p = scene["project"]
    world.client.patch(f"/api/v1/projects/{p['id']}", json={"require_change_request_for_approved_links": True}, headers=auth_headers(world.token))
    resp = world.client.post(
        _cr_url(p), json={"kind": "add_link", "requirement_id": str(scene["target"]), "reason": "x"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 400 and "proposed_links" in resp.json()["detail"]


def test_a_user_who_cannot_link_requirements_cannot_propose_links(world, scene):
    p = scene["project"]
    _user, token = _member(world, p)  # a plain member may submit a request but holds no role or permission to link
    resp = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])], token=token)
    assert resp.status_code == 400 and "can no longer link requirements" in resp.json()["detail"]
    assert _modify(world, p, scene["target"], [], token=token).status_code == 201  # a plain request is unaffected


def test_a_stakeholder_can_propose_links_on_an_approved_requirement(world, scene):
    p = scene["project"]
    _user, token = _member(world, p, "stakeholder")  # approved requirements are changed through requests, which they may make
    resp = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])], token=token)
    assert resp.status_code == 201, resp.text


def test_a_far_end_the_creator_cannot_see_reads_as_not_found(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    mine = _approved(world, child)
    theirs = world.requirement(root, "Root req")
    _user, token = _member(world, child, "project_manager")  # no role on the parent
    related = world.link_types_by_name()["Related to"]["id"]
    resp = _modify(world, child, mine, [_proposal(related, REQ, theirs, other_project=root)], token=token)
    assert resp.status_code == 400 and "was not found" in resp.json()["detail"]
    unrelated = world.project("Unrelated")
    other_req = world.requirement(unrelated, "Elsewhere")
    resp = _modify(world, child, mine, [_proposal(related, REQ, other_req, other_project=unrelated)])
    assert resp.status_code == 400 and "was not found" in resp.json()["detail"]  # even for an admin: not in the chain


# --- the finder accepts a record that does not exist yet ----------------------------------------


def test_the_finder_reads_accept_the_draft_id_for_someone_who_may_link(world, scene):
    p = scene["project"]
    draft = f"/api/v1/projects/{p['id']}/artefacts/{REQ}/{uuid.UUID(int=0)}"
    types = world.client.get(f"{draft}/link-types", headers=auth_headers(world.token))
    assert types.status_code == 200 and any(o["forward_name"] == "Related to" for o in types.json())
    found = world.client.get(f"{draft}/link-candidates", params={"other_type": REQ}, headers=auth_headers(world.token))
    assert found.status_code == 200 and found.json()["items"]
    browse = world.client.get(f"{draft}/link-browse", params={"other_type": REQ}, headers=auth_headers(world.token))
    assert browse.status_code == 200


def test_the_draft_id_is_refused_to_someone_who_may_not_link_and_never_accepted_by_a_write(world, scene):
    p = scene["project"]
    draft = f"/api/v1/projects/{p['id']}/artefacts/{REQ}/{uuid.UUID(int=0)}"
    _user, token = _member(world, p)
    assert world.client.get(f"{draft}/link-types", headers=auth_headers(token)).status_code == 403
    write = world.generic_link(p, (REQ, uuid.UUID(int=0)), scene["related"], (REQ, scene["b"]))
    assert write.status_code == 404  # a write needs a real record


# --- approving ----------------------------------------------------------------------------------


def test_approving_merges_every_valid_link_by_default_and_records_the_outcomes(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]), _proposal(scene["depends"], DEC, scene["dec"], direction="incoming"),
    ]).json()
    _submit(world, p, cr["id"])
    decided = _decide(world, p, cr["id"])
    assert decided.status_code == 200, decided.text
    assert {link["outcome"] for link in decided.json()["proposed_links"]} == {"merged"}

    links = _links_of(scene["target"])
    pairs = {(link.source_id, link.target_id) for link in links}
    assert pairs == {(scene["target"], scene["b"]), (scene["dec"], scene["target"])}  # directions as proposed
    assert {link.created_by for link in links} == {uuid.UUID(cr["creator_id"])}  # attributed to the person who proposed

    created = [e for e in _audit("artefact_link", "created") if e.detail.get("change_request_id") == cr["id"]]
    assert len(created) == 2 and all(e.detail["via"] == "change_request" for e in created)
    approved = [e for e in _audit("change_request", "approved") if e.entity_id == cr["id"]][0]
    assert approved.detail["links"] == {"merged": 2, "declined": 0, "skipped": 0}
    assert _cr(world, p, cr["id"])["status"] == "approved"


def test_the_approver_can_merge_a_subset_and_the_rest_end_declined(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]), _proposal(scene["related"], REQ, scene["c"]),
    ]).json()
    ids = [link["id"] for link in _cr(world, p, cr["id"])["proposed_links"]]
    _submit(world, p, cr["id"])
    decided = _decide(world, p, cr["id"], merge=[ids[1]])
    assert decided.status_code == 200, decided.text
    assert [link["outcome"] for link in decided.json()["proposed_links"]] == ["declined", "merged"]
    assert {(link.source_id, link.target_id) for link in _links_of(scene["target"])} == {(scene["target"], scene["c"])}


def test_approving_with_none_ticked_still_applies_the_field_changes(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    decided = _decide(world, p, cr["id"], merge=[])
    assert decided.status_code == 200, decided.text
    assert [link["outcome"] for link in decided.json()["proposed_links"]] == ["declined"]
    assert _links_of(scene["target"]) == []
    req = world.client.get(f"/api/v1/projects/{p['id']}/requirements/{scene['target']}", headers=auth_headers(world.token)).json()
    assert req["name"] == "Renamed by request"
    approved = [e for e in _audit("change_request", "approved") if e.entity_id == cr["id"]][0]
    assert approved.detail["links"] == {"merged": 0, "declined": 1, "skipped": 0}


def test_a_chosen_link_that_became_invalid_returns_409_with_a_fresh_preview_and_writes_nothing(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]), _proposal(scene["related"], REQ, scene["c"]),
    ]).json()
    ids = [link["id"] for link in _cr(world, p, cr["id"])["proposed_links"]]
    _submit(world, p, cr["id"])
    assert world.generic_link(p, (REQ, scene["target"]), scene["related"], (REQ, scene["b"])).status_code == 201  # now a duplicate

    refused = _decide(world, p, cr["id"], merge=ids)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    rows = {row["link"]["id"]: row for row in detail["preview"]["rows"]}
    assert rows[ids[0]]["selectable"] is False and rows[ids[0]]["already_linked"] is True
    assert rows[ids[1]]["selectable"] is True
    assert _cr(world, p, cr["id"])["status"] == "submitted"  # nothing applied, nothing recorded
    assert {link.target_id for link in _links_of(scene["target"])} == {scene["b"]}  # only the one made directly
    req = world.client.get(f"/api/v1/projects/{p['id']}/requirements/{scene['target']}", headers=auth_headers(world.token)).json()
    assert req["name"] != "Renamed by request"
    assert all(link["outcome"] == "pending" for link in _cr(world, p, cr["id"])["proposed_links"])


def test_with_no_selection_given_an_invalid_link_is_skipped_with_its_reason_and_the_rest_merge(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]), _proposal(scene["related"], REQ, scene["c"]),
    ]).json()
    _submit(world, p, cr["id"])
    assert world.generic_link(p, (REQ, scene["target"]), scene["related"], (REQ, scene["b"])).status_code == 201
    decided = _decide(world, p, cr["id"])
    assert decided.status_code == 200, decided.text
    first, second = decided.json()["proposed_links"]
    assert first["outcome"] == "skipped" and "already linked" in first["outcome_reason"]
    assert second["outcome"] == "merged"
    approved = [e for e in _audit("change_request", "approved") if e.entity_id == cr["id"]][0]
    assert approved.detail["links"] == {"merged": 1, "declined": 0, "skipped": 1}


def test_a_selection_naming_a_link_the_request_does_not_propose_is_a_400(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    assert _decide(world, p, cr["id"], merge=[str(uuid.uuid4())]).status_code == 400


def test_rejecting_merges_nothing_and_marks_every_link_declined(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    rejected = _decide(world, p, cr["id"], approve=False)
    assert rejected.status_code == 200
    assert [link["outcome"] for link in rejected.json()["proposed_links"]] == ["declined"]
    assert _links_of(scene["target"]) == []


def test_withdrawing_marks_every_link_declined(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    withdrawn = world.client.post(_cr_url(p, f"/{cr['id']}/withdraw"), headers=auth_headers(world.token))
    assert withdrawn.status_code == 200
    assert [link["outcome"] for link in _cr(world, p, cr["id"])["proposed_links"]] == ["declined"]


def test_a_decided_request_cannot_be_decided_again(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    assert _decide(world, p, cr["id"]).status_code == 200
    assert _decide(world, p, cr["id"]).status_code == 409
    assert len(_links_of(scene["target"])) == 1  # merged once


def test_the_creator_is_told_how_many_links_merged_and_how_many_did_not(world, scene):
    p = scene["project"]
    _user, creator_token, _role = _linker(world, p)
    cr = _modify(world, p, scene["target"], [
        _proposal(scene["related"], REQ, scene["b"]), _proposal(scene["related"], REQ, scene["c"]),
    ], token=creator_token).json()
    ids = [link["id"] for link in _cr(world, p, cr["id"])["proposed_links"]]
    _submit(world, p, cr["id"], token=creator_token)
    assert _decide(world, p, cr["id"], merge=[ids[0]]).status_code == 200
    notes = world.client.get("/api/v1/notifications", headers=auth_headers(creator_token)).json()
    approved = next(n for n in notes if n["title"].startswith("Your change request was approved"))
    assert "1 of 2 proposed links merged (1 left out)" in approved["body"]


def test_only_a_project_manager_can_preview_or_decide(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    _user, token = _member(world, p, "stakeholder")
    assert _preview(world, p, cr["id"], token=token).status_code == 403
    assert _decide(world, p, cr["id"], token=token).status_code == 403


# --- the preview re-validates at read time ------------------------------------------------------


def _single_row(world: World, project: dict, cr_id: str, token: str | None = None) -> dict:
    resp = _preview(world, project, cr_id, token=token)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    return rows[0]


def test_preview_marks_a_valid_link_selectable(world, scene):
    cr = _modify(world, scene["project"], scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    row = _single_row(world, scene["project"], cr["id"])
    assert row["selectable"] is True and row["reason"] is None and row["link"]["other_label"].endswith(" B")


def test_preview_reason_the_type_became_hidden(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    world.client.put(
        f"/api/v1/projects/{p['id']}/link-types/{scene['related']}/visibility", json={"hidden": True}, headers=auth_headers(world.token),
    )
    row = _single_row(world, p, cr["id"])
    assert row["selectable"] is False and "hidden" in row["reason"]


def test_preview_reason_an_artefact_rule_now_forbids_it(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    rule = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [str(scene["depends"])]},
        headers=auth_headers(world.token),
    )
    assert rule.status_code == 200, rule.text
    row = _single_row(world, p, cr["id"])
    assert row["selectable"] is False and "limited to specific link types" in row["reason"]


def test_preview_reason_the_far_end_was_deleted(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], DEC, scene["dec"])]).json()
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM decisions WHERE id = :id"), {"id": str(scene["dec"])})
        db.commit()
    finally:
        db.close()
    row = _single_row(world, p, cr["id"])
    assert row["selectable"] is False and "was not found" in row["reason"]
    assert row["link"]["other_label"] is None  # nothing about the missing record is shown


def test_preview_reason_the_link_already_exists(world, scene):
    p = scene["project"]
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])]).json()
    assert world.generic_link(p, (REQ, scene["target"]), scene["related"], (REQ, scene["b"])).status_code == 201
    row = _single_row(world, p, cr["id"])
    assert row["selectable"] is False and row["already_linked"] is True


def test_preview_reason_the_creator_lost_the_right_to_link(world, scene):
    p = scene["project"]
    _user, token, role_id = _linker(world, p)
    cr = _modify(world, p, scene["target"], [_proposal(scene["related"], REQ, scene["b"])], token=token).json()
    assert _single_row(world, p, cr["id"])["selectable"] is True
    assert world.client.delete(
        f"/api/v1/orgs/{world.org['id']}/custom-roles/{role_id}", headers=auth_headers(world.token)
    ).status_code in (200, 204)
    row = _single_row(world, p, cr["id"])
    assert row["selectable"] is False and "can no longer link requirements" in row["reason"]


def test_preview_reason_the_project_left_the_chain(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    other = world.project("Elsewhere")
    mine, theirs = _approved(world, child), world.requirement(root, "Root req")
    related = world.link_type("Either way", "Reverse", "none", "ancestor_either_way")
    cr = _modify(world, child, mine, [_proposal(related, REQ, theirs, other_project=root)]).json()
    assert _single_row(world, child, cr["id"])["selectable"] is True
    resp = world.client.patch(f"/api/v1/projects/{child['id']}", json={"parent_project_id": other["id"]}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    row = _single_row(world, child, cr["id"])
    assert row["selectable"] is False and "was not found" in row["reason"]


def test_preview_reason_the_nesting_scope_was_narrowed(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    mine, theirs = _approved(world, child), world.requirement(root, "Root req")
    related = world.link_type("Either way", "Reverse", "none", "ancestor_either_way")
    cr = _modify(world, child, mine, [_proposal(related, REQ, theirs, other_project=root)]).json()
    base = f"/api/v1/orgs/{world.org['id']}/link-types/{related}"
    types = world.client.get(f"/api/v1/orgs/{world.org['id']}/link-types", headers=auth_headers(world.token)).json()
    current = next(t for t in types if t["id"] == str(related))
    patch = world.client.patch(
        base, json={"forward_name": current["forward_name"], "reverse_name": "r", "nesting_scope": "same_project"},
        headers=auth_headers(world.token),
    )
    assert patch.status_code == 200, patch.text
    row = _single_row(world, child, cr["id"])
    assert row["selectable"] is False and row["reason"]


def test_an_approver_who_cannot_view_the_far_end_cannot_merge_it_and_it_is_not_revealed(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    mine, theirs = _approved(world, child), world.requirement(root, "Hidden root requirement")
    related = world.link_type("Either way", "Reverse", "none", "ancestor_either_way")
    cr = _modify(world, child, mine, [_proposal(related, REQ, theirs, other_project=root)]).json()  # an admin proposes it
    _submit(world, child, cr["id"])
    _user, approver = _member(world, child, "project_manager")  # manages the child only

    row = _single_row(world, child, cr["id"], token=approver)
    assert row["selectable"] is False and "cannot view the linked record" in row["reason"]
    assert row["link"]["other_label"] is None and row["link"]["other_project_name"] is None  # the title is not shown
    assert row["link"]["other_id"] is None and row["link"]["other_project_id"] is None  # nor the record's identity

    refused = _decide(world, child, cr["id"], merge=[row["link"]["id"]], token=approver)
    assert refused.status_code == 409
    assert _links_of(mine) == []

    decided = _decide(world, child, cr["id"], token=approver)  # no selection: the unviewable link is skipped, the rest applies
    assert decided.status_code == 200, decided.text
    assert decided.json()["proposed_links"][0]["outcome"] == "skipped"
    assert _links_of(mine) == []


# --- cross-level links are audited in both projects ---------------------------------------------


def test_a_merged_cross_level_link_is_audited_in_both_projects(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    mine, theirs = _approved(world, child), world.requirement(root, "Root req")
    related = world.link_type("Either way", "Reverse", "none", "ancestor_either_way")
    cr = _modify(world, child, mine, [_proposal(related, REQ, theirs, other_project=root)]).json()
    _submit(world, child, cr["id"])
    assert _decide(world, child, cr["id"]).status_code == 200
    (link,) = _links_of(mine)
    assert link.source_project_id == child["id"] or str(link.source_project_id) == child["id"]
    assert str(link.target_project_id) == root["id"]
    events = [e for e in _audit("artefact_link", "created") if e.detail.get("change_request_id") == cr["id"]]
    assert {str(e.project_id) for e in events} == {child["id"], root["id"]}


# --- new requirements ---------------------------------------------------------------------------


def test_a_new_requirement_request_creates_its_links_against_the_new_requirement_in_the_proposed_direction(world, scene):
    p = scene["project"]
    resp = world.client.post(
        _cr_url(p),
        json={
            "kind": "new_requirement", "proposed_name": "Brand new", "proposed_component_id": p["component_id"],
            "proposed_category_id": p["category_id"], "reason": "gap",
            "proposed_links": [
                _proposal(scene["depends"], REQ, scene["b"]),
                _proposal(scene["depends"], DEC, scene["dec"], direction="incoming"),
            ],
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    cr_id = resp.json()["id"]
    assert _links_of(scene["b"]) == []  # nothing yet
    _submit(world, p, cr_id)
    assert _decide(world, p, cr_id).status_code == 200
    new_id = uuid.UUID(_cr(world, p, cr_id)["requirement_id"])
    assert {(link.source_id, link.target_id) for link in _links_of(new_id)} == {(new_id, scene["b"]), (scene["dec"], new_id)}


def test_a_new_requirement_request_validates_its_links_against_the_project(world, scene):
    p = scene["project"]
    resp = world.client.post(
        _cr_url(p),
        json={
            "kind": "new_requirement", "proposed_name": "Brand new", "proposed_component_id": p["component_id"],
            "proposed_category_id": p["category_id"], "reason": "gap",
            "proposed_links": [_proposal(scene["related"], REQ, uuid.uuid4())],
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 400 and "was not found" in resp.json()["detail"]


# --- add-link requests are the one-link case ---------------------------------------------------


def test_an_add_link_request_merges_through_the_same_decision_and_may_apply_nothing(world, scene):
    p = scene["project"]
    world.client.patch(f"/api/v1/projects/{p['id']}", json={"require_change_request_for_approved_links": True}, headers=auth_headers(world.token))
    cr = world.client.post(
        _cr_url(p),
        json={
            "kind": "add_link", "requirement_id": str(scene["target"]), "reason": "gap",
            "proposed_links": [_proposal(scene["related"], REQ, scene["b"])],
        },
        headers=auth_headers(world.token),
    ).json()
    _submit(world, p, cr["id"])
    decided = _decide(world, p, cr["id"], merge=[])
    assert decided.status_code == 200 and [link["outcome"] for link in decided.json()["proposed_links"]] == ["declined"]
    assert _links_of(scene["target"]) == []


# --- deleting a link type that a pending request proposes --------------------------------------


def test_a_pending_proposal_blocks_removal_of_its_link_type_and_follows_a_move(world, scene):
    p = scene["project"]
    mine = world.link_type("Custom verb", "Custom reverse")
    cr = _modify(world, p, scene["target"], [_proposal(mine, REQ, scene["b"])]).json()
    base = f"/api/v1/orgs/{world.org['id']}/link-types/{mine}"
    usage = world.client.get(f"{base}/usage", headers=auth_headers(world.token)).json()
    assert usage["pending_change_requests"] == 1
    blocked = world.client.delete(base, params={"mode": "remove_links"}, headers=auth_headers(world.token))
    assert blocked.status_code == 409 and "pending change request" in blocked.json()["detail"]
    moved = world.client.delete(
        base, params={"mode": "reassign", "reassign_to_id": str(scene["related"])}, headers=auth_headers(world.token),
    )
    assert moved.status_code == 200, moved.text
    link = _cr(world, p, cr["id"])["proposed_links"][0]
    assert link["link_type_id"] == str(scene["related"]) and link["outcome"] == "pending"


def test_a_resolved_proposal_keeps_its_outcome_when_its_type_is_later_deleted(world, scene):
    p = scene["project"]
    mine = world.link_type("Custom verb", "Custom reverse")
    cr = _modify(world, p, scene["target"], [_proposal(mine, REQ, scene["b"])]).json()
    _submit(world, p, cr["id"])
    assert _decide(world, p, cr["id"]).status_code == 200
    removed = world.client.delete(
        f"/api/v1/orgs/{world.org['id']}/link-types/{mine}", params={"mode": "remove_links"}, headers=auth_headers(world.token),
    )
    assert removed.status_code == 200, removed.text
    link = _cr(world, p, cr["id"])["proposed_links"][0]
    assert link["outcome"] == "merged" and link["link_type_id"] is None and link["phrase"] is None


# --- migration of old ADD_LINK requests ---------------------------------------------------------


@contextmanager
def _downgraded_to_0069():
    """Reverts the live test database to revision 0069 (the two ADD_LINK columns exist, the proposed
    links table does not) for the block, then always upgrades back to head."""
    command.downgrade(build_alembic_config(), "0069")
    try:
        yield
    finally:
        command.upgrade(build_alembic_config(), "head")


def test_the_migration_turns_old_add_link_requests_into_proposed_links_with_reconstructed_outcomes(world, scene):
    p = scene["project"]
    target, b = scene["target"], scene["b"]
    creator = world.user_id
    related = scene["related"]
    ids = {name: uuid.uuid4() for name in ("open", "approved_made", "approved_lost", "rejected")}
    # an approved request whose link exists, and one whose link was dropped at approval
    world.generic_link(p, (REQ, target), related, (REQ, b))

    def insert_request(conn, cr_id, status, target_id, link_type_id):
        conn.execute(text(
            "INSERT INTO change_requests (id, created_at, updated_at, project_id, requirement_id, kind, status, creator_id, decision_note) "
            "VALUES (:id, now(), now(), :p, :r, 'add_link', :s, :u, '')"
        ), {"id": str(cr_id), "p": p["id"], "r": str(target), "s": status, "u": str(creator)})
        conn.execute(text(
            "INSERT INTO change_request_versions (id, change_request_id, version_number, reason, changed_fields, "
            "proposed_attachment_file_ids, custom_fields, created_by, created_at, proposed_link_target_requirement_id, proposed_link_type_id) "
            "VALUES (:id, :cr, 1, 'x', '[]', '[]', '{}', :u, now(), :t, :lt)"
        ), {"id": str(uuid.uuid4()), "cr": str(cr_id), "u": str(creator), "t": str(target_id), "lt": link_type_id and str(link_type_id)})

    c = scene["c"]
    with _downgraded_to_0069():
        with engine.begin() as conn:
            insert_request(conn, ids["open"], "submitted", c, related)
            insert_request(conn, ids["approved_made"], "approved", b, related)
            insert_request(conn, ids["approved_lost"], "approved", c, related)
            insert_request(conn, ids["rejected"], "rejected", c, related)

    rows = {}
    with engine.begin() as conn:
        for name, cr_id in ids.items():
            rows[name] = conn.execute(text(
                "SELECT link.outcome, link.outcome_reason, link.direction, link.other_type, link.other_id, link.link_type_id, link.other_project_id "
                "FROM change_request_proposed_links link JOIN change_request_versions v ON v.id = link.change_request_version_id "
                "WHERE v.change_request_id = :cr"
            ), {"cr": str(cr_id)}).one()
        columns = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'change_request_versions'"
        ))}
    assert "proposed_link_type_id" not in columns and "proposed_link_target_requirement_id" not in columns
    assert rows["open"].outcome == "pending" and rows["open"].direction == "outgoing" and rows["open"].other_type == "requirement"
    assert rows["open"].other_id == c and str(rows["open"].link_type_id) == str(related) and rows["open"].other_project_id is None
    assert rows["approved_made"].outcome == "merged"
    assert rows["approved_lost"].outcome == "skipped" and "approved" in rows["approved_lost"].outcome_reason
    assert rows["rejected"].outcome == "declined"
