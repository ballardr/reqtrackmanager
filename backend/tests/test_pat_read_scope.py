"""A Personal Access Token's organisation and project scope applies to the personal read routes as well as to the
organisation and project routes: lists, the organisation record, memberships, reviews due and notifications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.database import SessionLocal
from app.models.enums import OrgRole
from app.models.notification import Notification
from app.models.organization import UserOrgRole
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _two_orgs(client, admin_token):
    org_a, token_a = create_org_admin_in(client, admin_token, "Scope Alpha")
    org_b, _ = create_org_admin_in(client, admin_token, "Scope Beta")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token_a)).json()["id"]
    db = SessionLocal()
    try:
        db.add(UserOrgRole(user_id=uuid.UUID(me), organization_id=uuid.UUID(org_b["id"]), role=OrgRole.ORG_ADMIN))
        db.commit()
    finally:
        db.close()
    project_a = create_project(client, token_a, org_a["id"], name="Alpha Project")
    project_b = create_project(client, token_a, org_b["id"], name="Beta Project")
    pat = client.post(
        "/api/v1/me/pats", json={"name": "scoped", "allowed_organization_ids": [org_a["id"]]}, headers=auth_headers(token_a)
    ).json()["token"]
    return org_a, org_b, project_a, project_b, token_a, pat, me


def test_lists_and_records_outside_the_token_scope_are_hidden(client, admin_token):
    org_a, org_b, project_a, project_b, session, pat, _ = _two_orgs(client, admin_token)

    assert {o["id"] for o in client.get("/api/v1/orgs", headers=auth_headers(session)).json()} >= {org_a["id"], org_b["id"]}
    assert {o["id"] for o in client.get("/api/v1/orgs", headers=auth_headers(pat)).json()} == {org_a["id"]}
    assert client.get(f"/api/v1/orgs/{org_a['id']}", headers=auth_headers(pat)).status_code == 200
    assert client.get(f"/api/v1/orgs/{org_b['id']}", headers=auth_headers(pat)).status_code == 403

    session_projects = {p["id"] for p in client.get("/api/v1/projects", headers=auth_headers(session)).json()}
    assert {project_a["id"], project_b["id"]} <= session_projects
    assert {p["id"] for p in client.get("/api/v1/projects", headers=auth_headers(pat)).json()} == {project_a["id"]}

    memberships = client.get("/api/v1/auth/me/memberships", headers=auth_headers(pat)).json()["organizations"]
    assert [m["organization_id"] for m in memberships] == [org_a["id"]]
    assert [p["id"] for p in memberships[0]["projects"]] == [project_a["id"]]


def test_notifications_follow_the_token_scope(client, admin_token):
    org_a, org_b, project_a, project_b, session, pat, me = _two_orgs(client, admin_token)
    db = SessionLocal()
    try:
        for project, title in ((project_a, "in scope"), (project_b, "out of scope"), (None, "account level")):
            db.add(Notification(
                user_id=uuid.UUID(me), type="mention", title=title, body="",
                project_id=uuid.UUID(project["id"]) if project else None, created_at=datetime.now(UTC),
            ))
        db.commit()
    finally:
        db.close()

    assert {n["title"] for n in client.get("/api/v1/notifications", headers=auth_headers(session)).json()} == {
        "in scope", "out of scope", "account level",
    }
    assert [n["title"] for n in client.get("/api/v1/notifications", headers=auth_headers(pat)).json()] == ["in scope"]


def test_a_token_that_names_a_project_reaches_only_that_project(client, admin_token):
    org_a, _org_b, project_a, _project_b, session, _pat, _ = _two_orgs(client, admin_token)
    other = create_project(client, session, org_a["id"], name="Alpha Second")
    pat = client.post(
        "/api/v1/me/pats",
        json={"name": "one", "allowed_organization_ids": [org_a["id"]], "allowed_project_ids": [project_a["id"]]},
        headers=auth_headers(session),
    ).json()["token"]
    listed = {p["id"] for p in client.get("/api/v1/projects", headers=auth_headers(pat)).json()}
    assert listed == {project_a["id"]} and other["id"] not in listed
