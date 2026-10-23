"""Tests for the project overview's total records by type (`services.record_counts`, `GET .../metrics`).

Every test builds its own organisation (`tests.link_world.World`), so none depends on state left by another
test or run.
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_record_table_providers
from app.services import record_counts
from app.services.permissions import encode_permission
from app.services.project_scope import ProjectScope
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Counts Org", decisions=True, context_strategy=True)


def _metrics(world: World, project: dict, scope: str | None = None, token: str | None = None) -> dict:
    suffix = f"?project_scope={scope}" if scope else ""
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/metrics{suffix}", headers=auth_headers(token or world.token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _counts(metrics: dict) -> dict[str, int]:
    return {row["type"]: row["count"] for row in metrics["records_by_type"]}


def test_each_type_is_counted_and_the_total_is_their_sum(world):
    project = world.project("Counted")
    world.requirement(project, "A")
    world.requirement(project, "B")
    world.action(project, "Do it")
    world.decision(project)
    world.pain_point(project)

    metrics = _metrics(world, project)

    assert _counts(metrics) == {"requirement": 2, "requirement_action": 1, "decision": 1, "pain_point": 1}
    assert metrics["record_total"] == 5 == sum(_counts(metrics).values())
    assert [r["count"] for r in metrics["records_by_type"]] == [2, 1, 1, 1]  # largest first
    labels = {r["type"]: r["label"] for r in metrics["records_by_type"]}
    assert labels["requirement"] == "Requirements" and labels["pain_point"] == "Pain points"


def test_a_project_with_no_records_has_an_empty_split(world):
    metrics = _metrics(world, world.project("Empty"))
    assert metrics["records_by_type"] == [] and metrics["record_total"] == 0


def test_an_archived_requirement_is_not_counted(world):
    project = world.project("Archive")
    keep = world.requirement(project, "Keep")
    gone = world.requirement(project, "Gone")
    resp = world.client.delete(f"/api/v1/projects/{project['id']}/requirements/{gone}", headers=auth_headers(world.token))
    assert resp.status_code == 204, resp.text
    assert _counts(_metrics(world, project)) == {"requirement": 1}
    assert keep


def test_a_type_of_a_disabled_module_is_omitted(world):
    project = world.project("Toggle")
    world.decision(project)
    assert "decision" in _counts(_metrics(world, project))

    off = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/modules/decisions", json={"enabled": False}, headers=auth_headers(world.token)
    )
    assert off.status_code == 200, off.text

    assert "decision" not in _counts(_metrics(world, project))


def test_a_type_the_caller_cannot_view_is_omitted_not_shown_as_zero(world, monkeypatch):
    project = world.project("Hidden")
    world.requirement(project, "Visible")
    world.decision(project)
    decision_view = encode_permission("decision", "view")
    real = record_counts.permission_satisfied
    monkeypatch.setattr(record_counts, "permission_satisfied", lambda held, needed: needed != decision_view and real(held, needed))

    db = SessionLocal()
    try:
        user = db.get(User, world.user_id)
        found = record_counts.count_records_by_type(db, user, db.get(Project, uuid.UUID(project["id"])), ProjectScope("this"))
    finally:
        db.close()

    assert {c.type for c in found} == {"requirement"}


def test_nested_scope_widens_the_count_and_respects_what_the_caller_can_open(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    world.requirement(root, "Root req")
    world.requirement(child, "Child req")
    world.decision(root)

    own = _metrics(world, child)
    parents = _metrics(world, child, "parents")

    assert (_counts(own), own["record_total"]) == ({"requirement": 1}, 1)
    assert (_counts(parents), parents["record_total"]) == ({"requirement": 2, "decision": 1}, 3)

    email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    role = world.client.post(
        f"/api/v1/projects/{child['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(world.token)
    )
    assert role.status_code in (200, 201, 204), role.text
    narrow = _metrics(world, child, "parents", token=login(world.client, email, "Password123!"))
    assert (_counts(narrow), narrow["record_total"]) == ({"requirement": 1}, 1)


def test_another_projects_records_never_leak_into_a_count(world):
    mine = world.project("Mine")
    other = world.project("Other")
    world.requirement(other, "Theirs")
    assert _metrics(world, mine)["record_total"] == 0


def test_rows_derived_from_a_standard_do_not_count_as_project_records():
    derived = {t for t, p in get_record_table_providers().items() if not p.in_overview}
    assert derived == {"compliance_requirement", "project_compliance_requirement", "compliance_required_action_assessment"}
