"""Tests for the project History timeline: paging, filters (type, kind, person or group, time), record labels,
facets, export and the statement count.

The timeline merges four sources (`services.changes`); these tests write audit events directly so the actor, time
and action of each are exact, and use the API for the version-derived entries and the labelled records.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.user import User
from app.modules.registry import get_module_registry
from app.services.activity_kinds import CORE_ACTION_KINDS, KIND_LABELS, kind_of
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
)

BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
TYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "types.ts"


def _changes(client, token, project_id, **params):
    resp = client.get(f"/api/v1/projects/{project_id}/changes", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json(), int(resp.headers["X-Total-Count"])


def _event(project_id: str, action: str, *, actor_id=None, at: datetime = BASE, entity_type: str = "project_stage") -> None:
    db = SessionLocal()
    try:
        db.add(AuditEvent(
            entity_type=entity_type, entity_id=str(uuid.uuid4()), action=action, actor_id=actor_id,
            project_id=uuid.UUID(project_id), created_at=at,
        ))
        db.commit()
    finally:
        db.close()


def _user_id(email: str) -> uuid.UUID:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).one().id
    finally:
        db.close()


def test_every_core_action_kind_is_a_known_kind_and_module_kinds_are_too():
    assert set(CORE_ACTION_KINDS.values()) <= set(KIND_LABELS)
    for definition in get_module_registry().values():
        assert set(definition.activity_action_kinds.values()) <= set(KIND_LABELS), definition.key


def test_an_unclassified_action_is_other():
    assert kind_of("a_module_action_nobody_classified") == "other"
    assert kind_of("approved") == "status"


@pytest.mark.skipif(not TYPES_TS.exists(), reason="frontend sources are not available (backend-only image)")
def test_the_frontend_kind_labels_match_the_backend_kinds():
    source = TYPES_TS.read_text()
    block = re.search(r"ACTIVITY_KIND_LABEL[^{]*\{(.*?)\};", source, re.S)
    assert block, "ACTIVITY_KIND_LABEL is missing from frontend/src/api/types.ts"
    assert dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", block.group(1))) == KIND_LABELS


def test_pages_cover_the_whole_timeline_once_in_a_stable_order(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for i in range(12):  # every third event shares a timestamp, so paging must break ties the same way each time
        _event(project["id"], "updated", at=BASE + timedelta(minutes=i // 3))
    everything, total = _changes(client, admin_token, project["id"], limit=200)
    paged: list[dict] = []
    for offset in range(0, total, 5):
        page, page_total = _changes(client, admin_token, project["id"], limit=5, offset=offset)
        assert page_total == total
        paged += page
    assert total == len(everything) >= 12
    assert paged == everything
    assert [e["timestamp"] for e in everything] == sorted((e["timestamp"] for e in everything), reverse=True)


def test_oldest_first_reverses_the_order_and_pages_the_same_way(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for i in range(7):
        _event(project["id"], "updated", at=BASE + timedelta(minutes=i // 2))
    newest, total = _changes(client, admin_token, project["id"], limit=200)
    oldest, _ = _changes(client, admin_token, project["id"], limit=200, order="oldest")
    assert oldest == list(reversed(newest))
    paged: list[dict] = []
    for offset in range(0, total, 3):
        paged += _changes(client, admin_token, project["id"], limit=3, offset=offset, order="oldest")[0]
    assert paged == oldest


def test_kind_filter_matches_the_actions_of_the_kind_and_other_catches_the_rest(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for action in ("approved", "submitted", "tagged", "member_added", "unheard_of_action"):
        _event(project["id"], action)
    status_only, _ = _changes(client, admin_token, project["id"], kind="status", entity_type="project_stage")
    assert {e["action"] for e in status_only} == {"approved", "submitted"}
    assert all(e["kind"] == "status" for e in status_only)
    two, _ = _changes(client, admin_token, project["id"], kind=["tags", "access"], entity_type="project_stage")
    assert {e["action"] for e in two} == {"tagged", "member_added"}
    other, _ = _changes(client, admin_token, project["id"], kind="other", entity_type="project_stage")
    assert [e["action"] for e in other] == ["unheard_of_action"]


def test_version_derived_entries_follow_the_created_and_edited_kinds(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=auth_headers(admin_token),
    ).json()
    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Req renamed", "component_id": component_id, "category_id": category_id,
            "owner": {"type": requirement["owner"]["type"], "id": requirement["owner"]["id"]},
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    created, _ = _changes(client, admin_token, project["id"], kind="created", entity_type="requirement")
    edited, _ = _changes(client, admin_token, project["id"], kind="edited", entity_type="requirement")
    assert [e["action"] for e in created] == ["created"]
    assert [e["action"] for e in edited] == ["updated"]
    assert created[0]["detail"]["name"] == "Req renamed"


def test_person_filter_narrows_to_one_user_and_a_group_means_its_members(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    ana = create_org_user(client, admin_token, org_id, "history_ana@example.com")
    ben = create_org_user(client, admin_token, org_id, "history_ben@example.com")
    cy = create_org_user(client, admin_token, org_id, "history_cy@example.com")
    for user, action in ((ana, "approved"), (ben, "rejected"), (cy, "withdrawn")):
        _event(project["id"], action, actor_id=uuid.UUID(user))
    _event(project["id"], "submitted", actor_id=None)

    one, _ = _changes(client, admin_token, project["id"], actor=f"user:{ana}", entity_type="project_stage")
    assert [e["action"] for e in one] == ["approved"]

    inner = create_org_group(client, admin_token, org_id, "History inner", users=[ben])
    outer = create_org_group(client, admin_token, org_id, "History outer", users=[ana], nested=[inner])
    nested, _ = _changes(client, admin_token, project["id"], actor=f"org_group:{outer}", entity_type="project_stage")
    assert {e["action"] for e in nested} == {"approved", "rejected"}

    team = create_project_group(client, admin_token, project["id"], "History team", users=[cy])
    both, _ = _changes(
        client, admin_token, project["id"], actor=[f"project_group:{team}", f"user:{ana}"], entity_type="project_stage",
    )
    assert {e["action"] for e in both} == {"withdrawn", "approved"}

    empty = create_org_group(client, admin_token, org_id, "History empty")
    nobody, total = _changes(client, admin_token, project["id"], actor=f"org_group:{empty}")
    assert nobody == [] and total == 0  # an empty group matches nothing; it is not "no filter"


def test_a_user_who_has_left_can_still_be_filtered_by(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    gone = uuid.uuid4()
    _event(project["id"], "approved", actor_id=None)
    found, _ = _changes(client, admin_token, project["id"], actor=f"user:{gone}")
    assert found == []


def test_a_group_of_another_organisation_or_project_is_refused(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other = create_project(client, admin_token, org_id, "History other")
    other_team = create_project_group(client, admin_token, other["id"], "Other team")
    resp = client.get(
        f"/api/v1/projects/{project['id']}/changes", params={"actor": f"project_group:{other_team}"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422
    for bad in ("nonsense", "user:not-a-uuid", f"robot:{uuid.uuid4()}", f"org_group:{uuid.uuid4()}"):
        resp = client.get(f"/api/v1/projects/{project['id']}/changes", params={"actor": bad}, headers=auth_headers(admin_token))
        assert resp.status_code == 422, bad
    resp = client.get(f"/api/v1/projects/{project['id']}/changes", params={"kind": "bogus"}, headers=auth_headers(admin_token))
    assert resp.status_code == 422


def test_the_upper_time_bound_is_inclusive_and_the_lower_bound_too(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for minute in (0, 1, 2):
        _event(project["id"], "reordered", at=BASE + timedelta(minutes=minute))
    kwargs = {"entity_type": "project_stage"}
    window, _ = _changes(
        client, admin_token, project["id"], since=BASE.isoformat(), until=(BASE + timedelta(minutes=1)).isoformat(), **kwargs,
    )
    assert len(window) == 2


def test_comments_appear_with_the_flag_or_the_comments_kind_only(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "discussion"}, headers=auth_headers(admin_token),
    )
    plain, _ = _changes(client, admin_token, project["id"])
    assert not any(e["action"] == "comment_added" for e in plain)
    kind_only, _ = _changes(client, admin_token, project["id"], kind="comments")
    assert [e["action"] for e in kind_only] == ["comment_added"]
    flagged, _ = _changes(client, admin_token, project["id"], include_comments=True)
    assert any(e["action"] == "comment_added" for e in flagged)
    narrowed, _ = _changes(client, admin_token, project["id"], include_comments=True, kind="created")
    assert not any(e["action"] == "comment_added" for e in narrowed)


def test_an_action_record_is_named_by_its_code_and_title(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    types = client.get(f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(admin_token)).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/actions", json={"title": "Audit supplier", "action_type_id": types[0]["id"]},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    entries, _ = _changes(client, admin_token, project["id"], entity_type="requirement_action")
    assert entries and all(re.fullmatch(r"[A-Z]+-\d+ Audit supplier", e["record_label"]) for e in entries)


def test_facets_list_only_the_types_the_project_has_events_for(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _event(project["id"], "created", entity_type="tag")
    resp = client.get(f"/api/v1/projects/{project['id']}/changes/facets", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    types = resp.json()["entity_types"]
    assert "tag" in types and "change_request" not in types and "requirement" not in types
    assert resp.json()["total"] >= 1


def test_actors_endpoint_names_filter_chips_and_withholds_strangers(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    ana = create_org_user(client, admin_token, org_id, "history_chip@example.com")
    team = create_project_group(client, admin_token, project["id"], "Chip team", users=[ana])
    stranger = uuid.uuid4()
    resp = client.get(
        f"/api/v1/projects/{project['id']}/changes/actors",
        params={"actor": [f"user:{ana}", f"project_group:{team}", f"user:{stranger}"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    labels = [(p["type"], p["label"]) for p in resp.json()]
    assert labels[0] == ("user", "history_chip")
    assert labels[1] == ("project_group", "Chip team")
    assert labels[2][0] == "user" and labels[2][1] == "Unknown user"  # an id that is nobody known here is not named
    bad = client.get(
        f"/api/v1/projects/{project['id']}/changes/actors", params={"actor": f"org_group:{uuid.uuid4()}"},
        headers=auth_headers(admin_token),
    )
    assert bad.status_code == 422


def test_export_respects_the_filters_guards_formulas_and_audits_without_values(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    ana = create_org_user(client, admin_token, org_id, "history_export@example.com")
    _event(project["id"], "approved", actor_id=uuid.UUID(ana))
    _event(project["id"], "rejected", actor_id=uuid.UUID(ana))
    db = SessionLocal()
    try:
        db.add(AuditEvent(
            entity_type="=cmd", entity_id=str(uuid.uuid4()), action="approved", actor_id=None,
            project_id=uuid.UUID(project["id"]), created_at=BASE,
        ))
        db.commit()
    finally:
        db.close()
    resp = client.get(
        f"/api/v1/projects/{project['id']}/changes/export", params={"kind": "status", "format": "csv"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0].startswith("Time (UTC),Type,Event,Action,Record code,Record")
    assert len(lines) == 4  # header and the three status events
    assert "'=cmd" in text or "'=Cmd" in text  # the formula guard prefixed the cell
    assert "Status changes" in text
    assert "history_export" not in text  # the Person column is left out until the policy and permission allow it
    audit = SessionLocal()
    try:
        row = (
            audit.query(AuditEvent).filter(AuditEvent.project_id == uuid.UUID(project["id"]), AuditEvent.action == "records_exported")
            .one()
        )
        assert row.detail["rows"] == 3 and row.detail["filters"] == ["kind"] and "history_export" not in str(row.detail)
    finally:
        audit.close()


def test_export_in_a_document_format_returns_a_file(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _event(project["id"], "approved")
    resp = client.get(
        f"/api/v1/projects/{project['id']}/changes/export", params={"format": "pdf"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF")


class _Statements:
    """Counts the statements executed while active."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args, **_kwargs) -> None:
        self.count += 1

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(engine, "before_cursor_execute", self)


def test_a_page_costs_the_same_statements_however_large_the_project_history_is(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    url = f"/api/v1/projects/{project['id']}/changes"
    headers = auth_headers(admin_token)

    def measure() -> int:
        assert client.get(url, params={"limit": 20}, headers=headers).status_code == 200
        with _Statements() as statements:
            assert client.get(url, params={"limit": 20}, headers=headers).status_code == 200
        return statements.count

    for i in range(25):
        _event(project["id"], "updated", at=BASE + timedelta(seconds=i))
    small = measure()
    for i in range(25, 400):
        _event(project["id"], "updated", at=BASE + timedelta(seconds=i))
    assert measure() == small
