"""Tests for `POST .../artefacts/{type}/{id}/links/bulk`, the all-or-nothing call behind the create
forms' quick-link field: it must create what the single-link endpoint would, in order, and leave
nothing behind when any one link is refused.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by
another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.relationship import ArtefactLink
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

DEC = "decision"
PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Bulk Link Org", decisions=True, context_strategy=True)


def _item(link_type_id, other: tuple[str, uuid.UUID], direction: str = "outgoing") -> dict:
    return {"link_type_id": str(link_type_id), "direction": direction, "other_type": other[0], "other_id": str(other[1])}


def _bulk(world: World, project: dict, page: tuple[str, uuid.UUID], links: list[dict], token: str | None = None):
    return world.client.post(
        f"/api/v1/projects/{project['id']}/artefacts/{page[0]}/{page[1]}/links/bulk", json={"links": links},
        headers=auth_headers(token or world.token),
    )


def _stored(page: tuple[str, uuid.UUID]) -> int:
    """How many links touch `page`, read straight from the table."""
    db = SessionLocal()
    try:
        return db.scalar(
            select(func.count()).select_from(ArtefactLink).where(
                ((ArtefactLink.source_type == page[0]) & (ArtefactLink.source_id == page[1]))
                | ((ArtefactLink.target_type == page[0]) & (ArtefactLink.target_id == page[1]))
            )
        )
    finally:
        db.close()


def _scene(world: World):
    """A project with a pain point to link from and a requirement, a decision and a second requirement to link to."""
    project = world.project()
    page = (PAIN, world.pain_point(project))
    return project, page, (REQ, world.requirement(project, "A")), (DEC, world.decision(project)), (REQ, world.requirement(project, "B"))


def test_creates_every_link_in_request_order_and_audits_each(world):
    project, page, req_a, dec, req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    resp = _bulk(world, project, page, [_item(related, req_a), _item(related, dec), _item(related, req_b, "incoming")])
    assert resp.status_code == 201, resp.text
    items = resp.json()["items"]
    assert [i["other"]["id"] for i in items] == [str(req_a[1]), str(dec[1]), str(req_b[1])]
    assert [i["direction"] for i in items] == ["outgoing", "outgoing", "incoming"]
    assert _stored(page) == 3
    db = SessionLocal()
    try:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "artefact_link", AuditEvent.action == "created")
            .where(AuditEvent.entity_id.in_([i["id"] for i in items]))
        ).all()
        assert len(events) == 3
    finally:
        db.close()


def test_a_refused_link_creates_nothing_and_names_which_one(world):
    project, page, req_a, dec, req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    # "Supersedes" is dedicated: refused by the single-link endpoint, so it must be refused here.
    dedicated = world.link_types_by_name()["Supersedes"]["id"]
    resp = _bulk(world, project, page, [_item(related, req_a), _item(dedicated, dec), _item(related, req_b)])
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"].startswith("Link 2 of 3: ")
    assert _stored(page) == 0


def test_a_pair_repeated_within_the_request_is_a_duplicate_and_creates_nothing(world):
    project, page, req_a, _dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    resp = _bulk(world, project, page, [_item(related, req_a), _item(related, req_a)])
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("Link 2 of 2: ")
    assert _stored(page) == 0


def test_an_existing_link_makes_the_whole_request_a_conflict(world):
    project, page, req_a, dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    assert world.generic_link(project, page, related, req_a).status_code == 201
    resp = _bulk(world, project, page, [_item(related, dec), _item(related, req_a)])
    assert resp.status_code == 409
    assert _stored(page) == 1


def test_a_record_of_another_organisation_is_not_found_and_nothing_is_created(client, admin_token, world):
    project, page, req_a, _dec, _req_b = _scene(world)
    other = World(client, admin_token, "Other Bulk Org")
    foreign = (REQ, other.requirement(other.project(), "Foreign"))
    related = world.link_types_by_name()["Related to"]["id"]
    resp = _bulk(world, project, page, [_item(related, req_a), _item(related, foreign)])
    assert resp.status_code == 404
    assert resp.json()["detail"].startswith("Link 2 of 2: ")
    assert _stored(page) == 0


def test_a_view_only_member_is_refused_and_nothing_is_created(world):
    project, page, req_a, _dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    email = f"viewer-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    role = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(world.token),
    )
    assert role.status_code in (200, 201, 204), role.text
    token = login(world.client, email, "Password123!")
    resp = _bulk(world, project, page, [_item(related, req_a)], token=token)
    assert resp.status_code == 403
    assert _stored(page) == 0


def test_an_approved_requirement_still_needs_a_change_request_where_the_project_requires_it(world):
    project, page, req_a, _dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    approve = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req_a[1]}/approve", headers=auth_headers(world.token)
    )
    assert approve.status_code == 200, approve.text
    world.client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True},
        headers=auth_headers(world.token),
    )
    resp = _bulk(world, project, page, [_item(related, req_a)])
    assert resp.status_code == 409 and "change request" in resp.json()["detail"]
    assert _stored(page) == 0


def test_an_empty_or_oversized_request_is_rejected(world):
    project, page, req_a, _dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    assert _bulk(world, project, page, []).status_code == 422
    assert _bulk(world, project, page, [_item(related, req_a)] * 26).status_code == 422


def test_an_unknown_page_record_is_not_found(world):
    project, _page, req_a, _dec, _req_b = _scene(world)
    related = world.link_types_by_name()["Related to"]["id"]
    resp = _bulk(world, project, (PAIN, uuid.uuid4()), [_item(related, req_a)])
    assert resp.status_code == 404
