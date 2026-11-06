"""Tests for Product Feedback relationships and closing the loop: the "Addresses" (Pain Point) and "Realised by"
(Requirement) link types, the link counts on a request, the informed-requester record, the close-the-loop readout and
the project's open-loop list, merge union, visibility, gates, audit and the bundle round trip. Every test builds its
own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.product_feedback.tests._helpers import (
    add_link,
    add_member,
    add_requester,
    create_core_requirement,
    create_pain_point,
    create_persona,
    create_request,
    create_stakeholder,
    enable_module,
    enable_other_module,
    get_loop,
    get_request,
    mark_informed,
    mark_requirement_completed,
    project_base,
    transition,
)
from app.modules.registry import get_all_link_type_seeds
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _world(client, admin_token, name: str):
    """An org with Product Feedback, People and Context & Strategy on, a project and its admin token."""
    org, token = create_org_admin_in(client, admin_token, name)
    for key in ("product_feedback", "stakeholders", "context_strategy"):
        enable_other_module(client, token, org["id"], key)
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _deliver(client, token, pid, request_id) -> None:
    base = project_base(pid)
    for status in ("under_review", "accepted", "delivered"):
        assert transition(client, token, base, request_id, status).status_code == 200


def test_addresses_and_realised_by_are_seeded_for_requests_and_addresses_merges_with_decisions():
    seeds = get_all_link_type_seeds()
    addresses, realised = seeds["Addresses"], seeds["Realised by"]
    assert addresses.reverse_name == "Is addressed by" and set(addresses.allowed_source_types or ()) >= {"enhancement_request", "decision"}
    assert "pain_point" in (addresses.allowed_target_types or ())
    assert realised.reverse_name == "Realises"
    assert realised.allowed_source_types == ("enhancement_request",) and realised.allowed_target_types == ("requirement",)


def test_a_request_counts_the_pain_points_and_requirements_linked_and_a_merged_duplicates_too(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Links Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    canonical = create_request(client, token, pid, title="Canonical")
    duplicate = create_request(client, token, pid, title="Duplicate")
    pain = create_pain_point(client, token, pid)
    requirement = create_core_requirement(client, token, pid)
    assert get_request(client, token, pid, canonical["id"])["pain_point_count"] == 0

    assert add_link(client, token, org["id"], pid, duplicate["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
    assert add_link(client, token, org["id"], pid, canonical["id"], "Realised by", "requirement", requirement["id"]).status_code == 201
    assert get_request(client, token, pid, canonical["id"])["pain_point_count"] == 0  # the duplicate is not merged yet
    assert client.post(f"{base}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h).status_code == 200

    shown = get_request(client, token, pid, canonical["id"])
    assert (shown["pain_point_count"], shown["requirement_count"]) == (1, 1)
    listed = {r["title"]: r for r in client.get(base + "/requests", headers=h).json()}
    assert (listed["Canonical"]["pain_point_count"], listed["Canonical"]["requirement_count"]) == (1, 1)
    assert client.post(f"{base}/requests/{duplicate['id']}/unmerge", headers=h).status_code == 200
    assert get_request(client, token, pid, canonical["id"])["pain_point_count"] == 0

    loop = get_loop(client, token, pid, duplicate["id"])
    assert [p["id"] for p in loop["pain_points"]] == [pain["id"]] and loop["pain_points"][0]["label"].endswith(pain["title"])


def test_a_request_can_only_address_a_pain_point_and_be_realised_by_a_requirement(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Link Rules Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    requirement = create_core_requirement(client, token, pid)
    pain = create_pain_point(client, token, pid)
    assert add_link(client, token, org["id"], pid, request["id"], "Addresses", "requirement", requirement["id"]).status_code in (400, 409, 422)
    assert add_link(client, token, org["id"], pid, request["id"], "Realised by", "pain_point", pain["id"]).status_code in (400, 409, 422)


def test_the_loop_cannot_be_recorded_until_the_request_is_delivered_or_declined(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Gate Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201

    loop = get_loop(client, token, pid, request["id"])
    assert loop["can_record"] is False and loop["open_count"] == 0 and loop["informed_count"] == 0
    assert [r["label"] for r in loop["requesters"]] == ["Ann"]
    assert get_request(client, token, pid, request["id"])["loop_open_count"] == 0
    resp = mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])])
    assert resp.status_code == 409 and "no outcome" in resp.json()["detail"]
    # Withdrawing a record is always allowed (nothing to withdraw here, so nothing changes).
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], informed=False).status_code == 200


def test_requesters_are_ticked_off_one_by_one_on_a_delivered_request_and_the_open_loop_list_follows(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid, title="Export")
    ann = create_stakeholder(client, token, pid, "Ann", influence="High", org_id=org["id"])
    tech = create_persona(client, token, pid, "Technician", weight=2)
    for kind, record in (("stakeholder", ann), ("persona", tech)):
        assert add_requester(client, token, org["id"], pid, request["id"], kind, record["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])

    shown = get_request(client, token, pid, request["id"])
    assert (shown["informed_count"], shown["loop_open_count"]) == (0, 2)
    opened = client.get(project_base(pid) + "/close-the-loop", headers=h).json()
    assert [(o["request"]["id"], o["open_count"], o["requester_count"]) for o in opened] == [(request["id"], 2, 2)]
    assert {u["label"] for u in opened[0]["uninformed"]} == {"Ann", "Technician"}

    resp = mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], note="Told by email")
    assert resp.status_code == 200, resp.text
    loop = resp.json()
    told = {r["label"]: r for r in loop["requesters"]}
    assert told["Ann"]["informed"] and told["Ann"]["note"] == "Told by email" and told["Ann"]["informed_at"] and told["Ann"]["informed_by"]
    assert not told["Technician"]["informed"] and (loop["informed_count"], loop["open_count"]) == (1, 1)
    assert [o["open_count"] for o in client.get(project_base(pid) + "/close-the-loop", headers=h).json()] == [1]

    assert mark_informed(client, token, pid, request["id"], [("persona", tech["id"])]).status_code == 200
    assert client.get(project_base(pid) + "/close-the-loop", headers=h).json() == []
    after = get_request(client, token, pid, request["id"])
    assert (after["informed_count"], after["loop_open_count"]) == (2, 0)

    withdrawn = mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], informed=False).json()
    assert (withdrawn["informed_count"], withdrawn["open_count"]) == (1, 1)
    assert len(client.get(project_base(pid) + "/close-the-loop", headers=h).json()) == 1


def test_a_declined_request_has_a_loop_too_and_an_archived_one_is_left_out_and_cannot_be_changed(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Declined Loop Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    assert transition(client, token, base, request["id"], "declined", "Out of scope.").status_code == 200
    loop = get_loop(client, token, pid, request["id"])
    assert loop["can_record"] and loop["decline_reason"] == "Out of scope." and loop["open_count"] == 1
    assert client.get(base + "/close-the-loop", headers=h).json()[0]["decline_reason"] == "Out of scope."

    assert client.post(f"{base}/requests/{request['id']}/archive", headers=h).status_code == 200
    assert client.get(base + "/close-the-loop", headers=h).json() == []
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])]).status_code == 409


def test_only_a_current_requester_can_be_ticked_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Party Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    stranger = create_stakeholder(client, token, pid, "Stranger")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])

    for party in (("stakeholder", stranger["id"]), ("stakeholder", str(uuid.uuid4())), ("decision", ann["id"])):
        assert mark_informed(client, token, pid, request["id"], [party]).status_code == 409
    # One bad party fails the whole call: the good one is not recorded.
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"]), ("stakeholder", stranger["id"])]).status_code == 409
    assert get_loop(client, token, pid, request["id"])["informed_count"] == 0


def test_a_requester_reached_through_a_merged_duplicate_is_told_on_the_canonical_request_and_unmerging_hides_the_record(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Merge Co")
    pid, base, h = project["id"], project_base(project["id"]), auth_headers(token)
    canonical = create_request(client, token, pid, title="Canonical")
    duplicate = create_request(client, token, pid, title="Duplicate")
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, duplicate["id"], "stakeholder", ann["id"]).status_code == 201
    assert client.post(f"{base}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h).status_code == 200
    _deliver(client, token, pid, canonical["id"])

    assert get_loop(client, token, pid, canonical["id"])["requesters"][0]["label"] == "Ann"
    assert mark_informed(client, token, pid, canonical["id"], [("stakeholder", ann["id"])]).status_code == 200
    assert get_request(client, token, pid, canonical["id"])["informed_count"] == 1

    assert client.post(f"{base}/requests/{duplicate['id']}/unmerge", headers=h).status_code == 200
    assert get_loop(client, token, pid, canonical["id"])["requesters"] == []
    assert get_request(client, token, pid, canonical["id"])["informed_count"] == 0
    assert client.post(f"{base}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h).status_code == 200
    assert get_request(client, token, pid, canonical["id"])["informed_count"] == 1  # the record returns with the party


def test_the_delivered_prompt_appears_only_when_an_accepted_request_has_only_completed_requirements(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Delivered Prompt Co")
    pid, base = project["id"], project_base(project["id"])
    request = create_request(client, token, pid)
    first = create_core_requirement(client, token, pid, "First")
    second = create_core_requirement(client, token, pid, "Second")
    for status in ("under_review", "accepted"):
        assert transition(client, token, base, request["id"], status).status_code == 200
    assert get_loop(client, token, pid, request["id"])["suggest_delivered"] is False
    assert get_loop(client, token, pid, request["id"])["all_requirements_complete"] is None

    for requirement in (first, second):
        assert add_link(client, token, org["id"], pid, request["id"], "Realised by", "requirement", requirement["id"]).status_code == 201
    mark_requirement_completed(first["id"])
    loop = get_loop(client, token, pid, request["id"])
    assert loop["suggest_delivered"] is False and loop["all_requirements_complete"] is False
    assert {r["is_completed"] for r in loop["realising_requirements"]} == {True, False}

    mark_requirement_completed(second["id"])
    loop = get_loop(client, token, pid, request["id"])
    assert loop["suggest_delivered"] is True and loop["all_requirements_complete"] is True
    assert get_request(client, token, pid, request["id"])["status"] == "accepted"  # a prompt, never a transition
    assert transition(client, token, base, request["id"], "delivered").status_code == 200
    assert get_loop(client, token, pid, request["id"])["suggest_delivered"] is False


def test_a_plain_member_can_read_the_loop_but_not_record_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Gate Roles Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])
    _, member = add_member(client, token, org["id"], pid, "loop-member@example.com")
    assert get_loop(client, member, pid, request["id"])["open_count"] == 1
    assert mark_informed(client, member, pid, request["id"], [("stakeholder", ann["id"])]).status_code == 403
    assert get_loop(client, token, pid, request["id"])["informed_count"] == 0


def test_a_stakeholder_hidden_from_the_project_drops_out_of_the_loop_and_cannot_be_ticked(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Hidden Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    shared = client.post(
        f"/api/v1/orgs/{org['id']}/modules/stakeholders/stakeholders", json={"name": "Shared Regulator"}, headers=h,
    ).json()
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", shared["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])
    assert get_loop(client, token, pid, request["id"])["open_count"] == 1
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", shared["id"])]).status_code == 200

    hidden = client.put(
        f"/api/v1/projects/{pid}/modules/stakeholders/stakeholders/{shared['id']}/visibility", json={"hidden": True}, headers=h,
    )
    assert hidden.status_code == 200, hidden.text
    loop = get_loop(client, token, pid, request["id"])
    assert loop["requesters"] == [] and loop["open_count"] == 0 and loop["informed_count"] == 0
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", shared["id"])]).status_code == 409
    assert client.get(project_base(pid) + "/close-the-loop", headers=h).json() == []


def test_recording_is_audited_with_the_parties_and_never_the_note(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Audit Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], note="Phoned Ann at home").status_code == 200
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], informed=False).status_code == 200
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == request["id"], AuditEvent.action.in_(["requesters_informed", "requesters_informed_withdrawn"]),
        ).order_by(AuditEvent.created_at)))
    assert [e.action for e in events] == ["requesters_informed", "requesters_informed_withdrawn"]
    detail = events[0].detail or {}
    assert detail["parties"] == [{"type": "stakeholder", "id": ann["id"]}] and detail["changed"] == 1
    assert "Phoned" not in str(detail)


def test_another_projects_request_is_not_reachable_through_this_projects_loop(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Tenancy Co")
    other = create_project(client, token, org["id"], "Other project")
    request = create_request(client, token, other["id"])
    assert client.get(f"{project_base(project['id'])}/requests/{request['id']}/close-the-loop", headers=auth_headers(token)).status_code == 404
    assert mark_informed(client, token, project["id"], request["id"], [("stakeholder", str(uuid.uuid4()))]).status_code == 404


def test_the_module_off_hides_the_loop_endpoints(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Feedback Loop Off Co")
    project = create_project(client, token, org["id"], "Off Project")
    assert client.get(project_base(project["id"]) + "/close-the-loop", headers=auth_headers(token)).status_code == 404
    enable_module(client, token, org["id"])
    assert client.get(project_base(project["id"]) + "/close-the-loop", headers=auth_headers(token)).status_code == 200


def test_the_list_reads_links_and_informed_requesters_in_a_fixed_number_of_statements(client, admin_token):
    from sqlalchemy import event

    from app.database import engine

    org, project, token = _world(client, admin_token, "Feedback Flat Loop Co")
    pid, h = project["id"], auth_headers(token)
    ann = create_stakeholder(client, token, pid, "Ann")
    pain = create_pain_point(client, token, pid)

    def statements() -> int:
        url = project_base(pid) + "/requests"
        assert client.get(url, headers=h).status_code == 200
        seen: list[str] = []

        def count(_conn, _cursor, statement, *_args, **_kwargs) -> None:
            if "generated_reports" not in statement:
                seen.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            assert client.get(url, headers=h).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    def add(n: int) -> None:
        for i in range(n):
            made = create_request(client, token, pid, title=f"Request {i}")
            assert add_requester(client, token, org["id"], pid, made["id"], "stakeholder", ann["id"]).status_code == 201
            assert add_link(client, token, org["id"], pid, made["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
            _deliver(client, token, pid, made["id"])
            assert mark_informed(client, token, pid, made["id"], [("stakeholder", ann["id"])]).status_code == 200

    add(2)
    few = statements()
    add(4)
    assert statements() == few


def test_links_and_informed_requesters_round_trip_through_a_project_bundle(client, admin_token):
    org, project, token = _world(client, admin_token, "Feedback Loop Bundle Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid, title="Delivered ask")
    open_ask = create_request(client, token, pid, title="Open ask")
    ann = create_stakeholder(client, token, pid, "Ann")
    ben = create_stakeholder(client, token, pid, "Ben")
    pain = create_pain_point(client, token, pid, "Reports are late")
    requirement = create_core_requirement(client, token, pid, "Fast reports")
    for made, person in ((request, ann), (request, ben), (open_ask, ben)):
        assert add_requester(client, token, org["id"], pid, made["id"], "stakeholder", person["id"]).status_code == 201
    assert add_link(client, token, org["id"], pid, request["id"], "Addresses", "pain_point", pain["id"]).status_code == 201
    assert add_link(client, token, org["id"], pid, request["id"], "Realised by", "requirement", requirement["id"]).status_code == 201
    _deliver(client, token, pid, request["id"])
    assert mark_informed(client, token, pid, request["id"], [("stakeholder", ann["id"])], note="Told in person").status_code == 200

    bundle = client.get(f"/api/v1/projects/{pid}/export", headers=h)
    assert bundle.status_code == 200, bundle.text
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Restored Loop"},
        files={"file": ("bundle.zip", bundle.content, "application/zip")}, headers=h,
    )
    assert resp.status_code == 201, resp.text
    imported = resp.json()["project"]["id"]
    got = {r["title"]: r for r in client.get(project_base(imported) + "/requests", headers=h).json()}
    delivered = got["Delivered ask"]
    assert (delivered["pain_point_count"], delivered["requirement_count"]) == (1, 1)
    assert (delivered["requester_count"], delivered["informed_count"], delivered["loop_open_count"]) == (2, 1, 1)
    assert got["Open ask"]["pain_point_count"] == 0
    loop = get_loop(client, token, imported, delivered["id"])
    told = {r["label"]: r for r in loop["requesters"]}
    assert told["Ann"]["informed"] and told["Ann"]["note"] == "Told in person" and not told["Ben"]["informed"]
    assert loop["realising_requirements"][0]["label"].endswith("Fast reports")
    # The original project is untouched.
    assert get_request(client, token, pid, request["id"])["informed_count"] == 1
