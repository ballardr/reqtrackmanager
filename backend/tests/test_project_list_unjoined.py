"""Tests for `GET /projects?include_unjoined=true`: an organisation administrator also lists the projects of the
organisations they administer that they hold no role in, as identity-only rows. Each test builds its own organisations.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.enums import OrgRole
from app.models.organization import UserOrgRole
from app.models.user import User
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

IDENTITY_KEYS = {
    "id", "organization_id", "organization_name", "name", "code", "is_archived", "is_template",
    "parent_project_id", "parent_project_name", "is_member",
}


def _list(client, token, **params):
    return client.get("/api/v1/projects", params={"archived": "false", **params}, headers=auth_headers(token))


def _setup(client, admin_token, org_name):
    """An organisation with an administrator holding no role in the creator's project."""
    org, admin = create_org_admin_in(client, admin_token, org_name)
    slug = org_name.lower().replace(" ", "_")
    create_org_user(client, admin_token, org["id"], f"{slug}_creator@example.com", role="project_creator")
    creator = login(client, f"{slug}_creator@example.com", "Password123!")
    project = create_project(client, creator, org["id"], f"{org_name} Hidden")
    return org, admin, creator, project


def test_default_list_is_unchanged_and_flags_the_filter(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Default")
    resp = _list(client, admin)
    assert project["id"] not in {p["id"] for p in resp.json()}
    assert resp.headers["x-can-include-unjoined"] == "true"
    assert _list(client, creator).headers["x-can-include-unjoined"] == "false"


def test_administrator_sees_unjoined_projects_as_identity_only(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Rows")
    client.patch(f"/api/v1/projects/{project['id']}", json={"summary": "Confidential summary"}, headers=auth_headers(creator))

    rows = {p["id"]: p for p in _list(client, admin, include_unjoined="true").json()}
    row = rows[project["id"]]
    assert row["is_member"] is False
    assert set(row) == IDENTITY_KEYS
    assert row["organization_name"] == org["name"]
    # The wider list gives no access to the project's content.
    assert client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin)).status_code == 403


def test_member_and_project_creator_get_the_flag_ignored(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Ignored")
    create_org_user(client, admin_token, org["id"], "unjoined_ignored_member@example.com", role="member")
    member = login(client, "unjoined_ignored_member@example.com", "Password123!")
    other = create_project(client, creator, org["id"], "Creator Other")
    for token in (creator, member):
        resp = _list(client, token, include_unjoined="true")
        assert resp.status_code == 200
        assert resp.headers["x-can-include-unjoined"] == "false"
        assert all(p["is_member"] is True for p in resp.json())
    assert {p["id"] for p in _list(client, creator, include_unjoined="true").json()} == {project["id"], other["id"]}
    assert _list(client, member, include_unjoined="true").json() == []


def test_a_joined_project_is_not_duplicated(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Joined")
    own = create_project(client, admin, org["id"], "Administrator Own")
    rows = _list(client, admin, include_unjoined="true").json()
    ids = [p["id"] for p in rows]
    assert ids.count(own["id"]) == 1
    assert next(p for p in rows if p["id"] == own["id"])["is_member"] is True
    assert next(p for p in rows if p["id"] == project["id"])["is_member"] is False


def test_only_organisations_the_person_administers_are_widened(client, admin_token):
    org_a, admin_a, _, project_a = _setup(client, admin_token, "Unjoined Org A")
    org_b, _, _, project_b = _setup(client, admin_token, "Unjoined Org B")
    # The first administrator is only a plain member of the second organisation.
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.email == "unjoined_org_a_admin@example.com"))
        db.add(UserOrgRole(user_id=user_id, organization_id=org_b["id"], role=OrgRole.MEMBER))
        db.commit()
    ids = {p["id"] for p in _list(client, admin_a, include_unjoined="true").json()}
    assert project_a["id"] in ids
    assert project_b["id"] not in ids


def test_filters_apply_to_the_combined_set(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Filters")
    own = create_project(client, admin, org["id"], "Filters Own")
    template = create_project(client, creator, org["id"], "Filters Template")
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(creator))
    archived = create_project(client, creator, org["id"], "Filters Archived")
    client.post(f"/api/v1/projects/{archived['id']}/archive", headers=auth_headers(creator))

    def ids(**params):
        return [p["id"] for p in _list(client, admin, include_unjoined="true", **params).json()]

    names = [p["name"].lower() for p in _list(client, admin, include_unjoined="true").json()]
    assert names == sorted(names)
    assert template["id"] not in ids() and archived["id"] not in ids()
    assert template["id"] in ids(include_templates="true")
    assert ids(templates_only="true") == [template["id"]]
    assert ids(search="hidden") == [project["id"]]
    assert ids(archived="true") == [archived["id"]]
    assert ids(organization_id=org["id"], search="own") == [own["id"]]
    # Membership-only filters leave the extra rows out.
    assert project["id"] not in ids(role="project_manager")
    assert project["id"] not in ids(favorite_only="true")


def test_paging_and_totals_cover_the_combined_set(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Paging")
    create_project(client, admin, org["id"], "Paging Own")
    resp = _list(client, admin, include_unjoined="true", limit="1")
    assert resp.headers["x-total-count"] == "2"
    assert resp.headers["x-total-unfiltered-count"] == "2"
    assert len(resp.json()) == 1
    plain = _list(client, admin)
    assert plain.headers["x-total-count"] == "1"


def test_hierarchy_of_an_unjoined_child_is_shown_to_the_administrator(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Parent")
    client.patch(f"/api/v1/projects/{project['id']}", json={"can_be_parent": True}, headers=auth_headers(creator))
    child = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Unjoined Child", "summary": "", "parent_project_id": project["id"]},
        headers=auth_headers(creator),
    ).json()
    row = next(p for p in _list(client, admin, include_unjoined="true").json() if p["id"] == child["id"])
    assert row["parent_project_id"] == project["id"]
    assert row["parent_project_name"] == project["name"]


def test_the_members_endpoints_still_refuse_a_non_administrator(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Gear")
    create_org_user(client, admin_token, org["id"], "unjoined_gear_member@example.com", role="member")
    member = login(client, "unjoined_gear_member@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin)).status_code == 200
    assert client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(member)).status_code == 403


def test_default_template_read_still_lists_templates_without_a_role(client, admin_token):
    org, admin, creator, project = _setup(client, admin_token, "Unjoined Template")
    template = create_project(client, creator, org["id"], "Unjoined Template One")
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(creator))
    listed = client.get(f"/api/v1/orgs/{org['id']}/projects", headers=auth_headers(admin)).json()
    assert next(p for p in listed if p["id"] == template["id"])["is_template"] is True
