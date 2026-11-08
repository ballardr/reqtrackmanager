"""Tests for the organisation Files page's API (`routers.orgs.files`): it lists exactly the files of the projects the
caller may open (never a blanket organisation read), labels each row with its project, applies the project Files
page's filters plus a project filter and archived projects, keeps the statement count flat as projects are added,
and never logs, audits or puts the searched file name in a URL.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World
from tests.test_project_files_page import attach, library


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Org Files Org")


def org_files(world: World, suffix: str = "", *, org_id: str | None = None):
    return f"/api/v1/orgs/{org_id or world.org['id']}/files{suffix}"


def search(world: World, body: dict | None = None, query: str = "", token: str | None = None, org_id: str | None = None):
    return world.client.post(
        org_files(world, f"/search{query}", org_id=org_id), json=body or {}, headers=auth_headers(token or world.token),
    )


def names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return sorted(r["file"]["filename"] for r in resp.json())


def member_of(world: World, *projects: dict) -> str:
    """A new organisation member holding the Member role on exactly the given projects; returns their token."""
    email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    for project in projects:
        role = world.client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
            headers=auth_headers(world.token),
        )
        assert role.status_code in (200, 201, 204), role.text
    return login(world.client, email, "Password123!")


def test_every_project_the_caller_can_open_is_listed_with_its_project(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    attach(world, alpha, "alpha-spec.txt")
    library(world, beta, "beta-logo.png")

    resp = search(world)

    assert names(resp) == ["alpha-spec.txt", "beta-logo.png"]
    labelled = {r["file"]["filename"]: (r["from_project_id"], r["from_project_name"], r["from_project_code"]) for r in resp.json()}
    assert labelled["alpha-spec.txt"] == (alpha["id"], "Alpha", alpha["code"])
    assert labelled["beta-logo.png"] == (beta["id"], "Beta", beta["code"])
    assert resp.headers["X-Total-Count"] == "2" and resp.headers["X-Projects-Truncated"] == "false"


def test_a_member_sees_only_the_projects_they_hold_a_role_in(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    attach(world, alpha, "alpha-spec.txt")
    attach(world, beta, "beta-spec.txt")
    token = member_of(world, alpha)

    assert names(search(world, token=token)) == ["alpha-spec.txt"]
    people = world.client.get(org_files(world, "/uploaders"), headers=auth_headers(token)).json()
    assert [p["id"] for p in people] == [str(world.user_id)]
    projects = world.client.get(org_files(world, "/projects"), headers=auth_headers(token)).json()
    assert [p["id"] for p in projects] == [alpha["id"]]


def test_a_member_with_no_project_role_gets_an_empty_list_not_an_error(world):
    attach(world, world.project("Alpha"), "alpha-spec.txt")
    token = member_of(world)

    resp = search(world, token=token)

    assert resp.status_code == 200 and resp.json() == [] and resp.headers["X-Total-Count"] == "0"
    assert world.client.get(org_files(world, "/projects"), headers=auth_headers(token)).json() == []


def test_a_person_outside_the_organisation_is_refused_and_another_organisations_files_never_appear(client, admin_token, world):
    attach(world, world.project("Alpha"), "alpha-spec.txt")
    other = World(client, admin_token, "Other Files Org")
    attach(other, other.project("Gamma"), "gamma-spec.txt")

    assert names(search(world)) == ["alpha-spec.txt"]
    assert search(world, token=other.token).status_code == 403  # an administrator of another organisation
    assert search(other, token=world.token, org_id=other.org["id"]).status_code == 403
    for suffix in ("/uploaders", "/projects"):
        assert world.client.get(org_files(world, suffix), headers=auth_headers(other.token)).status_code == 403


def test_a_confidential_picture_follows_the_librarys_rule_and_stays_listed_for_members(world):
    alpha = world.project("Alpha")
    picture = library(world, alpha, "secret.png")
    marked = world.client.patch(
        f"/api/v1/files/{picture}/confidential", json={"confidential": True}, headers=auth_headers(world.token),
    )
    assert marked.status_code == 200, marked.text
    token = member_of(world, alpha)

    rows = search(world, token=token).json()

    assert [(r["file"]["filename"], r["file"]["confidential"]) for r in rows] == [("secret.png", True)]


def test_organisation_shared_resources_and_another_projects_library_are_not_project_rows(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    library(world, beta, "beta-only.png")
    shared = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/resources", files={"file": ("handbook.txt", b"x", "text/plain")},
        headers=auth_headers(world.token),
    )
    assert shared.status_code == 201, shared.text
    token = member_of(world, alpha)

    assert names(search(world, token=token)) == []


def test_the_project_filter_narrows_and_never_widens_beyond_what_the_caller_may_open(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    attach(world, alpha, "alpha-spec.txt")
    attach(world, beta, "beta-spec.txt")
    token = member_of(world, alpha)

    assert names(search(world, {"project_ids": [beta["id"]]})) == ["beta-spec.txt"]
    assert names(search(world, {"project_ids": [alpha["id"], beta["id"]]})) == ["alpha-spec.txt", "beta-spec.txt"]
    assert names(search(world, {"project_ids": [beta["id"]]}, token=token)) == []
    assert names(search(world, {"project_ids": [str(uuid.uuid4())]})) == []


def test_archived_projects_are_left_out_unless_asked_for(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    attach(world, alpha, "alpha-spec.txt")
    attach(world, beta, "beta-spec.txt")
    archived = world.client.post(f"/api/v1/projects/{beta['id']}/archive", headers=auth_headers(world.token))
    assert archived.status_code == 200, archived.text

    assert names(search(world)) == ["alpha-spec.txt"]
    assert names(search(world, {"include_archived": True})) == ["alpha-spec.txt", "beta-spec.txt"]
    plain = world.client.get(org_files(world, "/projects"), headers=auth_headers(world.token)).json()
    wide = world.client.get(org_files(world, "/projects?include_archived=true"), headers=auth_headers(world.token)).json()
    assert [p["name"] for p in plain] == ["Alpha"]
    assert [(p["name"], p["is_archived"]) for p in wide] == [("Alpha", False), ("Beta", True)]


def test_the_page_filters_apply_and_paging_follows_them(world):
    alpha = world.project("Alpha")
    library(world, alpha, "logo.png")
    for index in range(3):
        attach(world, alpha, f"note-{index}.txt")

    only_documents = search(world, {"kind": "document"}, "?limit=2&offset=0")
    rest = search(world, {"kind": "document"}, "?limit=2&offset=2")
    by_name = search(world, {"search": "LOGO"})
    by_source = search(world, {"sources": ["report_image"]})

    assert len(only_documents.json()) == 2 and only_documents.headers["X-Total-Count"] == "3"
    assert len(rest.json()) == 1
    assert names(by_name) == ["logo.png"] and names(by_source) == ["logo.png"]


def test_a_token_scoped_to_one_project_lists_only_that_project(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    attach(world, alpha, "alpha-spec.txt")
    attach(world, beta, "beta-spec.txt")
    made = world.client.post(
        "/api/v1/me/pats",
        json={"name": "scoped", "allowed_organization_ids": [world.org["id"]], "allowed_project_ids": [alpha["id"]]},
        headers=auth_headers(world.token),
    )
    assert made.status_code == 201, made.text
    token = made.json()["token"]

    assert names(search(world, token=token)) == ["alpha-spec.txt"]


def test_the_number_of_statements_does_not_grow_with_the_number_of_projects(world):
    def statements_for_a_search() -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_rest):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert search(world).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    first = world.project("One")
    attach(world, first, "one.txt")
    library(world, first, "one.png")
    small = statements_for_a_search()
    for index in range(6):
        project = world.project(f"More {index}")
        attach(world, project, f"more-{index}.txt")
        library(world, project, f"more-{index}.png")
    large = statements_for_a_search()

    # Role resolution is bulk-loaded, so seven projects cost about what one does: allow a small constant slack.
    assert large <= small + 4, (small, large)


def test_the_search_text_is_never_logged_audited_or_put_in_a_url(world, caplog):
    attach(world, world.project("Alpha"), "payroll-merger.txt")
    needle = "zq-needle-5517"
    with SessionLocal() as db:
        before = len(db.scalars(select(AuditEvent)).all())

    with caplog.at_level(logging.DEBUG):
        resp = search(world, {"search": needle})

    assert resp.status_code == 200 and resp.json() == []
    assert needle not in caplog.text and needle not in str(resp.request.url)
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent)).all()
    assert len(events) == before and not any(needle in str(event_.detail) for event_ in events)

