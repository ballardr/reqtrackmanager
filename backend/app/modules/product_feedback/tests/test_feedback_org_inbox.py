"""Tests for the organisation's request inbox: requests the organisation owns (their own `ENH` sequence), the
organisation triager role, tenant isolation between the inbox and projects, and the organisation administrator's
switch that turns the inbox off (`organization_requests` sub-component) without touching project requests. Each test
builds its own organisation."""

from __future__ import annotations

from app.modules.product_feedback.tests._helpers import (
    create_inbox_request,
    create_request,
    grant_org_role,
    org_base,
    project_base,
    set_org_inbox,
    setup,
    transition,
)
from tests.conftest import auth_headers, create_org_user, login


def test_an_inbox_request_is_owned_by_the_organisation_with_its_own_numbering(client, admin_token):
    org, project, token = setup(client, admin_token, "Inbox Create Co")
    request = create_inbox_request(client, token, org["id"])
    assert request["scope"] == "organization" and request["organization_id"] == org["id"]
    assert request["project_id"] is None and request["unique_code"] == "ENH-001" and request["status"] == "new"
    assert create_request(client, token, project["id"])["unique_code"] == "ENH-001"
    assert create_inbox_request(client, token, org["id"], title="Second")["unique_code"] == "ENH-002"


def test_the_inbox_and_a_project_do_not_see_each_others_requests(client, admin_token):
    org, project, token = setup(client, admin_token, "Inbox Isolation Co")
    inbox = create_inbox_request(client, token, org["id"])
    in_project = create_request(client, token, project["id"])
    inbox_ids = {r["id"] for r in client.get(org_base(org["id"]) + "/requests", headers=auth_headers(token)).json()}
    project_ids = {r["id"] for r in client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).json()}
    assert inbox_ids == {inbox["id"]} and project_ids == {in_project["id"]}
    assert client.get(f"{project_base(project['id'])}/requests/{inbox['id']}", headers=auth_headers(token)).status_code == 404
    assert client.get(f"{org_base(org['id'])}/requests/{in_project['id']}", headers=auth_headers(token)).status_code == 404


def test_another_organisations_inbox_looks_absent(client, admin_token):
    org, _, token = setup(client, admin_token, "Inbox Tenant A Co")
    other_org, _, other_token = setup(client, admin_token, "Inbox Tenant B Co")
    request = create_inbox_request(client, token, org["id"])
    assert client.get(f"{org_base(other_org['id'])}/requests/{request['id']}", headers=auth_headers(other_token)).status_code == 404
    assert client.get(f"{org_base(org['id'])}/requests", headers=auth_headers(other_token)).status_code in (403, 404)


def test_a_member_submits_but_only_an_organisation_triager_edits_and_moves(client, admin_token):
    org, _, admin = setup(client, admin_token, "Inbox Gate Co")
    member_id = create_org_user(client, admin, org["id"], "member.inbox@example.com")
    member = login(client, "member.inbox@example.com", "Password123!")
    request = create_inbox_request(client, member, org["id"], title="From a member")
    path = f"{org_base(org['id'])}/requests/{request['id']}"
    assert client.put(path, json={"title": "Hijack"}, headers=auth_headers(member)).status_code == 403
    assert transition(client, member, org_base(org["id"]), request["id"], "under_review").status_code == 403
    assert client.post(f"{path}/comments", json={"body": "Me too"}, headers=auth_headers(member)).status_code == 201

    grant_org_role(client, admin, org["id"], member_id, "org_feedback_triager")
    assert client.put(path, json={"title": "Reworded"}, headers=auth_headers(member)).status_code == 200
    moved = transition(client, member, org_base(org["id"]), request["id"], "under_review")
    assert moved.status_code == 200 and moved.json()["status"] == "under_review"


def test_an_inbox_request_runs_the_same_lifecycle_and_versioning(client, admin_token):
    org, _, token = setup(client, admin_token, "Inbox Lifecycle Co")
    base = org_base(org["id"])
    request = create_inbox_request(client, token, org["id"])
    assert transition(client, token, base, request["id"], "declined").status_code == 409
    assert transition(client, token, base, request["id"], "declined", "Not for us.").json()["decline_reason"] == "Not for us."
    versions = client.get(f"{base}/requests/{request['id']}/versions", headers=auth_headers(token)).json()
    assert [v["status"] for v in versions] == ["new", "declined"]
    archived = client.post(f"{base}/requests/{request['id']}/archive", headers=auth_headers(token))
    assert archived.status_code == 200 and archived.json()["is_archived"] is True
    assert client.get(base + "/requests", headers=auth_headers(token)).json() == []


def test_inbox_files_are_organisation_resources_that_members_can_download(client, admin_token):
    org, _, admin = setup(client, admin_token, "Inbox Files Co")
    create_org_user(client, admin, org["id"], "reader.inbox@example.com")
    reader = login(client, "reader.inbox@example.com", "Password123!")
    request = create_inbox_request(client, admin, org["id"])
    path = f"{org_base(org['id'])}/requests/{request['id']}/files"
    resp = client.post(path, files={"file": ("note.txt", b"inbox evidence", "text/plain")}, headers=auth_headers(admin))
    assert resp.status_code == 201, resp.text
    download = client.get(f"/api/v1/files/{resp.json()['id']}", headers=auth_headers(reader))
    assert download.status_code == 200 and download.content == b"inbox evidence"


def test_switching_the_inbox_off_hides_it_but_leaves_project_requests_working(client, admin_token):
    org, project, token = setup(client, admin_token, "Inbox Switch Co")
    request = create_inbox_request(client, token, org["id"])
    in_project = create_request(client, token, project["id"])
    set_org_inbox(client, token, org["id"], False)
    assert client.get(org_base(org["id"]) + "/requests", headers=auth_headers(token)).status_code == 404
    assert client.get(f"{org_base(org['id'])}/requests/{request['id']}", headers=auth_headers(token)).status_code == 404
    assert client.post(org_base(org["id"]) + "/requests", json={"title": "x"}, headers=auth_headers(token)).status_code == 404
    assert client.get(f"{project_base(project['id'])}/requests/{in_project['id']}", headers=auth_headers(token)).status_code == 200
    set_org_inbox(client, token, org["id"], True)
    assert client.get(f"{org_base(org['id'])}/requests/{request['id']}", headers=auth_headers(token)).status_code == 200


def test_the_inbox_is_on_by_default_and_listed_as_a_sub_component(client, admin_token):
    org, _, token = setup(client, admin_token, "Inbox Default Co")
    resp = client.get(f"/api/v1/orgs/{org['id']}/modules/product_feedback/subcomponents", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    by_key = {s["subcomponent_key"]: s for s in resp.json()}
    assert set(by_key) == {"enhancement_request", "organization_requests"}
    assert by_key["organization_requests"]["enabled"] is True
