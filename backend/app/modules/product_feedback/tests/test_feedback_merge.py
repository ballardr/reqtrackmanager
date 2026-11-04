"""Tests for merging duplicate enhancement requests: the status and history it records, demand as a union that
unmerging reverses, the rules that keep it one level deep, the triager gate, the triage-move guard, the inbox
tier, the audit trail and tenant isolation. Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.product_feedback.tests._helpers import (
    add_member,
    add_requester,
    create_inbox_request,
    create_persona,
    create_request,
    create_stakeholder,
    get_demand,
    get_request,
    grant_project_role,
    org_base,
    project_base,
    setup,
    setup_with_people,
    transition,
)
from tests.conftest import auth_headers


def _merge(client, token, base, duplicate_id, canonical_id, note=""):
    return client.post(
        f"{base}/requests/{duplicate_id}/merge", json={"canonical_id": canonical_id, "note": note}, headers=auth_headers(token),
    )


def _unmerge(client, token, base, duplicate_id):
    return client.post(f"{base}/requests/{duplicate_id}/unmerge", headers=auth_headers(token))


def test_merging_marks_the_duplicate_and_unions_demand_and_unmerging_reverses_both(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Merge Co")
    pid, base = project["id"], project_base(project["id"])
    canonical = create_request(client, token, pid, title="Export to CSV")
    duplicate = create_request(client, token, pid, title="CSV download please")
    ann = create_stakeholder(client, token, pid, "Ann", influence="High", org_id=org["id"])
    bob = create_stakeholder(client, token, pid, "Bob")
    tech = create_persona(client, token, pid, "Technician", weight=2)
    asked = (
        (canonical, "stakeholder", ann), (duplicate, "stakeholder", ann), (duplicate, "stakeholder", bob),
        (duplicate, "persona", tech),
    )
    for request, kind, record in asked:
        assert add_requester(client, token, org["id"], pid, request["id"], kind, record["id"]).status_code == 201
    transition(client, token, base, duplicate["id"], "under_review")

    assert get_request(client, token, pid, canonical["id"])["requester_count"] == 1
    merged = _merge(client, token, base, duplicate["id"], canonical["id"], "Same ask.")
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["status"] == "duplicate" and body["allowed_next_statuses"] == []
    assert body["merged_into"]["id"] == canonical["id"] and body["merged_into"]["unique_code"] == canonical["unique_code"]
    assert body["version_number"] == 3  # created, under review, merged

    shown = get_request(client, token, pid, canonical["id"])
    assert shown["merged_count"] == 1 and shown["requester_count"] == 3 and shown["weighted_demand"] == 3 + 1 + 2
    demand = get_demand(client, token, pid, canonical["id"])
    assert {r["label"]: r["from_merge"] for r in demand["requesters"]} == {"Ann": False, "Bob": True, "Technician": True}
    assert [d["id"] for d in demand["merged_duplicates"]] == [duplicate["id"]]

    undone = _unmerge(client, token, base, duplicate["id"])
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "under_review" and undone.json()["merged_into"] is None  # its status before
    after = get_request(client, token, pid, canonical["id"])
    assert after["merged_count"] == 0 and after["requester_count"] == 1 and after["weighted_demand"] == 3

    history = client.get(f"{base}/requests/{canonical['id']}/merges", headers=auth_headers(token)).json()
    assert len(history) == 1 and history[0]["active"] is False and history[0]["prior_status"] == "under_review"
    assert history[0]["canonical"]["unique_code"] == canonical["unique_code"] and history[0]["unmerged_at"] is not None

    # The same pair can merge again, and the history keeps both rows.
    assert _merge(client, token, base, duplicate["id"], canonical["id"]).status_code == 200
    again = client.get(f"{base}/requests/{duplicate['id']}/merges", headers=auth_headers(token)).json()
    assert [m["active"] for m in again] == [True, False]


def test_a_requester_added_to_a_merged_duplicate_counts_while_the_merge_lasts(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Late Requester Co")
    pid, base = project["id"], project_base(project["id"])
    canonical, duplicate = create_request(client, token, pid), create_request(client, token, pid, title="Dup")
    assert _merge(client, token, base, duplicate["id"], canonical["id"]).status_code == 200
    late = create_stakeholder(client, token, pid, "Late Larry")
    assert add_requester(client, token, org["id"], pid, duplicate["id"], "stakeholder", late["id"]).status_code == 201
    assert get_request(client, token, pid, canonical["id"])["requester_count"] == 1
    assert _unmerge(client, token, base, duplicate["id"]).status_code == 200
    assert get_request(client, token, pid, canonical["id"])["requester_count"] == 0
    assert get_request(client, token, pid, duplicate["id"])["requester_count"] == 1  # its own link is untouched


def test_the_merge_rules_keep_it_one_level_deep(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Merge Rules Co")
    pid, base = project["id"], project_base(project["id"])
    a, b, c = (create_request(client, token, pid, title=t) for t in ("A", "B", "C"))

    assert _merge(client, token, base, a["id"], a["id"]).status_code == 409  # into itself
    assert _merge(client, token, base, b["id"], a["id"]).status_code == 200
    assert _merge(client, token, base, b["id"], c["id"]).status_code == 409  # already a duplicate (not open)
    assert _merge(client, token, base, c["id"], b["id"]).status_code == 409  # canonical is itself a duplicate
    assert _merge(client, token, base, a["id"], c["id"]).status_code == 409  # it has duplicates merged into it
    assert _unmerge(client, token, base, c["id"]).status_code == 409  # not merged

    delivered = create_request(client, token, pid, title="Shipped")
    for step in ("under_review", "accepted", "delivered"):
        assert transition(client, token, base, delivered["id"], step).status_code == 200
    declined = create_request(client, token, pid, title="Declined")
    assert transition(client, token, base, declined["id"], "declined", "No.").status_code == 200
    assert _merge(client, token, base, delivered["id"], c["id"]).status_code == 409
    assert _merge(client, token, base, declined["id"], c["id"]).status_code == 409

    archived = create_request(client, token, pid, title="Archived")
    client.post(f"{base}/requests/{archived['id']}/archive", headers=auth_headers(token))
    assert _merge(client, token, base, archived["id"], c["id"]).status_code == 409
    assert _merge(client, token, base, c["id"], archived["id"]).status_code == 409

    # A duplicate cannot be moved on by a transition either.
    assert transition(client, token, base, b["id"], "new").status_code == 409


def test_only_a_triager_may_merge_or_unmerge(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Merge Gate Co")
    pid, base = project["id"], project_base(project["id"])
    a, b = create_request(client, token, pid, title="A"), create_request(client, token, pid, title="B")
    member_id, member_token = add_member(client, token, org["id"], pid, "merge-member@example.com")
    assert _merge(client, member_token, base, b["id"], a["id"]).status_code == 403
    grant_project_role(client, token, pid, member_id, "feedback_triager")
    assert _merge(client, member_token, base, b["id"], a["id"]).status_code == 200
    other_id, other_token = add_member(client, token, org["id"], pid, "merge-other@example.com")
    assert _unmerge(client, other_token, base, b["id"]).status_code == 403
    assert client.get(f"{base}/requests/{a['id']}/merges", headers=auth_headers(other_token)).status_code == 200


def test_a_canonical_from_another_project_or_organisation_looks_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Merge Tenant Co")
    pid, base = project["id"], project_base(project["id"])
    other_project = client.post(
        "/api/v1/projects", json={"name": "Second", "organization_id": org["id"]}, headers=auth_headers(token),
    ).json()
    foreign = create_request(client, token, other_project["id"], title="Elsewhere")
    mine = create_request(client, token, pid, title="Mine")
    assert _merge(client, token, base, mine["id"], foreign["id"]).status_code == 404
    assert _merge(client, token, base, mine["id"], str(uuid.uuid4())).status_code == 404

    other_org, other_proj, other_token = setup(client, admin_token, "Feedback Merge Tenant Other Co")
    theirs = create_request(client, other_token, other_proj["id"], title="Theirs")
    assert _merge(client, token, base, mine["id"], theirs["id"]).status_code == 404
    assert get_request(client, token, pid, mine["id"])["status"] == "new"


def test_merge_and_unmerge_are_audited_with_codes_and_the_note_but_never_titles(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Merge Audit Co")
    pid, base = project["id"], project_base(project["id"])
    a = create_request(client, token, pid, title="Secret roadmap idea")
    b = create_request(client, token, pid, title="Same idea again")
    assert _merge(client, token, base, b["id"], a["id"], "Confidential reason").status_code == 200
    assert _unmerge(client, token, base, b["id"]).status_code == 200
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "enhancement_request")).all()
    by_action = {(e.action, str(e.entity_id)): e.detail for e in events}
    assert {action for action, _ in by_action} >= {"merged", "duplicate_merged_in", "unmerged", "duplicate_unmerged"}
    merged = by_action[("merged", b["id"])]
    assert merged is not None
    assert merged["canonical"] == a["unique_code"] and merged["duplicate"] == b["unique_code"]
    merge_events = [d for (action, _), d in by_action.items() if action != "created"]
    assert "Secret roadmap idea" not in str(merge_events) and "Same idea again" not in str(merge_events)
    assert merged["note"] == "Confidential reason"  # like a transition's comment, the triager's own words


def test_inbox_requests_merge_within_the_inbox_and_a_merged_request_cannot_be_triaged(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Inbox Merge Co")
    base = org_base(org["id"])
    keep = create_inbox_request(client, token, org["id"], title="Dark mode")
    dup = create_inbox_request(client, token, org["id"], title="Night theme")
    assert _merge(client, token, base, dup["id"], keep["id"]).status_code == 200
    shown = client.get(f"{base}/requests/{keep['id']}", headers=auth_headers(token)).json()
    assert shown["merged_count"] == 1 and shown["requester_count"] == 0

    for request in (keep, dup):
        blocked = client.post(
            f"{base}/requests/{request['id']}/move-to-project", json={"project_id": project["id"]}, headers=auth_headers(token),
        )
        assert blocked.status_code == 409 and "merge" in blocked.json()["detail"].lower()
    assert _unmerge(client, token, base, dup["id"]).status_code == 200
    moved = client.post(
        f"{base}/requests/{dup['id']}/move-to-project", json={"project_id": project["id"]}, headers=auth_headers(token),
    )
    assert moved.status_code == 200, moved.text

    # A project request is not an inbox request, so it cannot be merged across tiers.
    project_request = create_request(client, token, project["id"], title="In project")
    cross = _merge(client, token, base, keep["id"], project_request["id"])
    assert cross.status_code == 404
