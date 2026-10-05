"""Tests for the 2026-10-04 list-endpoint efficiency fixes (found while
root-causing e2e timeouts: the backend saturated a CPU on N+1 queries in the
project and requirements lists).

Covers:
- `GET /projects/{id}/requirements` batching (`_prefetch_for_list`): the
  batched per-row fields match the single-requirement endpoint exactly, and
  the query count no longer grows with the number of requirements.
- `GET /projects/{id}/my-roles`: the caller's roles on one project, including
  an archived project, an org admin without a project role, and a refused
  outsider.
- `rbac.memoize_user_lookups`: caches only inside its scope, so code outside
  it (e.g. a mutation followed by a re-check) always reads fresh data.
- `GET /projects` role batching (`rbac.prefetch_project_roles`): each row's
  `my_roles` matches unbatched per-project resolution across every role
  source, and the query count no longer grows with the number of projects.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.enums import ProjectRole, ProjectRoleInheritanceMode, ProjectVisibility
from app.models.organization import OrgGroup, OrgGroupMember
from app.models.project import (
    OrgGroupProjectRole,
    Project,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    UserProjectRole,
)
from app.services.rbac import get_effective_project_roles, memoize_user_lookups
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


class _QueryCounter:
    """Counts SQL statements executed while active."""

    def __init__(self):
        self.count = 0

    def __call__(self, *_args, **_kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *_exc):
        event.remove(engine, "before_cursor_execute", self)


def _create_requirements(client, token, project_id, component_id, category_id, count, prefix):
    ids = []
    for i in range(count):
        resp = client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"name": f"{prefix} {i}", "component_id": component_id, "category_id": category_id,
                  "keywords": [f"kw{i}", "shared"]},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


def test_requirements_list_matches_detail_and_query_count_is_flat(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "List Efficiency Co")
    project = create_project(client, token, org["id"], "Efficiency Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"

    ids = _create_requirements(client, token, project["id"], component_id, category_id, 3, "First")
    # Give the rows differing engagement state: a subscription, comments, an
    # open change request.
    assert client.put(f"{base}/{ids[0]}/subscription", headers=auth_headers(token)).status_code == 204
    for body in ("one", "two"):
        resp = client.post(f"{base}/{ids[1]}/comments", json={"body": body}, headers=auth_headers(token))
        assert resp.status_code == 201, resp.text
    # A change request needs an approved (locked) requirement.
    assert client.post(f"{base}/{ids[2]}/approve", headers=auth_headers(token)).status_code == 200
    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "modify_requirement", "requirement_id": ids[2], "proposed_name": "Renamed",
              "changed_fields": ["name"], "reason": "because"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    # Only submitted/in-review change requests count as open.
    submitted = client.post(f"/api/v1/projects/{project['id']}/change-requests/{resp.json()['id']}/submit",
                            headers=auth_headers(token))
    assert submitted.status_code == 200, submitted.text

    with _QueryCounter() as small:
        listed = client.get(base, headers=auth_headers(token))
    assert listed.status_code == 200
    by_id = {r["id"]: r for r in listed.json()}
    fields = ("keywords", "is_subscribed", "comment_count", "has_open_change_request", "name", "status")
    for requirement_id in ids:
        detail = client.get(f"{base}/{requirement_id}", headers=auth_headers(token)).json()
        for field in fields:
            got, want = by_id[requirement_id][field], detail[field]
            if field == "keywords":
                got, want = sorted(got), sorted(want)
            assert got == want, (field, requirement_id)
    assert by_id[ids[0]]["is_subscribed"] and by_id[ids[1]]["comment_count"] == 2
    assert by_id[ids[2]]["has_open_change_request"]

    _create_requirements(client, token, project["id"], component_id, category_id, 7, "More")
    with _QueryCounter() as large:
        assert len(client.get(base, headers=auth_headers(token)).json()) == 10
    # Batched: more rows, same number of queries (was ~5 extra per row).
    assert large.count == small.count, (small.count, large.count)


def test_my_roles_endpoint(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "My Roles Co")
    project = create_project(client, token, org["id"], "My Roles Project")
    member_id = create_org_user(client, token, org["id"], "my_roles_member@example.com")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": member_id, "role": "stakeholder"},
                headers=auth_headers(token))
    member = login(client, "my_roles_member@example.com", "Password123!")
    url = f"/api/v1/projects/{project['id']}/my-roles"

    resp = client.get(url, headers=auth_headers(member))
    assert resp.status_code == 200 and resp.json() == {"roles": ["member", "stakeholder"]}
    # The creating org admin is the project manager, which implies the rest.
    assert client.get(url, headers=auth_headers(token)).json()["roles"] == [
        "member", "project_administrator", "project_manager", "stakeholder",
    ]

    # Archived projects still report roles (the old list-based lookup didn't).
    assert client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers(token)).status_code == 200
    assert client.get(url, headers=auth_headers(member)).json() == {"roles": ["member", "stakeholder"]}

    # An org admin with no project role may read it (empty); an outsider can't.
    create_org_user(client, token, org["id"], "my_roles_admin@example.com", role="org_admin")
    org_admin = login(client, "my_roles_admin@example.com", "Password123!")
    assert client.get(url, headers=auth_headers(org_admin)).json() == {"roles": []}
    _, outsider = create_org_admin_in(client, admin_token, "My Roles Other Co")
    assert client.get(url, headers=auth_headers(outsider)).status_code in (403, 404)


def test_memoize_user_lookups_is_scoped(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Memo Scope Co")
    project = create_project(client, token, org["id"], "Memo Project")
    user_id = uuid.UUID(create_org_user(client, token, org["id"], "memo_user@example.com"))
    project_id = uuid.UUID(project["id"])

    db = SessionLocal()
    try:
        assert get_effective_project_roles(db, user_id, project_id) == set()
        with memoize_user_lookups():
            assert get_effective_project_roles(db, user_id, project_id) == set()
            db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=ProjectRole.STAKEHOLDER))
            db.flush()
            # Inside the scope the earlier result is reused (by design, for
            # read-only bulk callers only).
            assert get_effective_project_roles(db, user_id, project_id) == set()
        # Outside it, resolution is always fresh.
        assert ProjectRole.STAKEHOLDER in get_effective_project_roles(db, user_id, project_id)
        db.rollback()
    finally:
        db.close()


def _grant_via_project_group(db, project_id, role, *, user_id=None, org_group_id=None, source_project_id=None):
    group = ProjectGroup(project_id=project_id, name=f"Group {uuid.uuid4().hex[:6]}")
    db.add(group)
    db.flush()
    db.add(ProjectGroupRole(project_group_id=group.id, role=role))
    db.add(ProjectGroupMember(
        project_group_id=group.id, user_id=user_id, org_group_id=org_group_id, source_project_id=source_project_id,
    ))


def test_project_list_roles_match_unbatched_resolution_for_every_source(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Role Batch Co")
    user_id = uuid.UUID(create_org_user(client, token, org["id"], "role_batch@example.com"))
    names = ("direct", "project_group", "nested_org_group", "org_group_role", "project_ref", "org_wide",
             "forward_child", "mirror_role_child", "member_source", "mirror_all_source", "no_access")
    pid = {n: uuid.UUID(create_project(client, token, org["id"], f"Batch {n}")["id"]) for n in names}

    db = SessionLocal()
    try:
        org_group = OrgGroup(organization_id=uuid.UUID(org["id"]), name="Batch Team")
        db.add(org_group)
        db.flush()
        db.add(OrgGroupMember(org_group_id=org_group.id, user_id=user_id))
        db.add(UserProjectRole(user_id=user_id, project_id=pid["direct"], role=ProjectRole.STAKEHOLDER))
        _grant_via_project_group(db, pid["project_group"], ProjectRole.PROJECT_ADMINISTRATOR, user_id=user_id)
        _grant_via_project_group(db, pid["nested_org_group"], ProjectRole.STAKEHOLDER, org_group_id=org_group.id)
        db.add(OrgGroupProjectRole(org_group_id=org_group.id, project_id=pid["org_group_role"],
                                   role=ProjectRole.STAKEHOLDER))
        _grant_via_project_group(db, pid["project_ref"], ProjectRole.PROJECT_ADMINISTRATOR,
                                 source_project_id=pid["direct"])
        projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(pid.values()))}
        projects[pid["org_wide"]].visibility = ProjectVisibility.ORG_WIDE
        # Forward inheritance needs a role of the user's own on the child to
        # be listed at all, so give each child a direct stakeholder role too.
        for child, parent, mode in (("forward_child", "project_group", ProjectRoleInheritanceMode.MIRROR_ALL),
                                    ("mirror_role_child", "direct", ProjectRoleInheritanceMode.MIRROR_ROLE)):
            projects[pid[child]].parent_project_id = pid[parent]
            projects[pid[child]].role_inheritance_mode = mode
            db.add(UserProjectRole(user_id=user_id, project_id=pid[child], role=ProjectRole.MEMBER))
        projects[pid["mirror_role_child"]].role_inheritance_filter_role = ProjectRole.STAKEHOLDER
        db.add(ProjectMemberSource(project_id=pid["member_source"], source_project_id=pid["direct"],
                                   mirror_mode=ProjectRoleInheritanceMode.MEMBER_ONLY))
        db.add(ProjectMemberSource(project_id=pid["mirror_all_source"], source_project_id=pid["project_group"],
                                   mirror_mode=ProjectRoleInheritanceMode.MIRROR_ALL))
        db.commit()

        member = login(client, "role_batch@example.com", "Password123!")
        listed = {uuid.UUID(p["id"]): p["my_roles"] for p in client.get("/api/v1/projects",
                                                                          headers=auth_headers(member)).json()}
        assert pid["no_access"] not in listed
        for name in names[:-1]:
            # Fresh, unmemoized resolution is the reference.
            expected = sorted(r.value for r in get_effective_project_roles(db, user_id, pid[name]))
            assert expected, name  # every source really grants something
            assert listed.get(pid[name]) == expected, name
    finally:
        db.close()


def test_project_list_query_count_is_flat(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Project Batch Co")
    user_id = uuid.UUID(create_org_user(client, token, org["id"], "project_batch@example.com"))
    member = login(client, "project_batch@example.com", "Password123!")

    def grant(count, prefix):
        db = SessionLocal()
        try:
            for i in range(count):
                project_id = uuid.UUID(create_project(client, token, org["id"], f"{prefix} {i}")["id"])
                db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=ProjectRole.STAKEHOLDER))
            db.commit()
        finally:
            db.close()

    grant(2, "Few")
    with _QueryCounter() as small:
        assert len(client.get("/api/v1/projects", headers=auth_headers(member)).json()) == 2
    grant(6, "Many")
    with _QueryCounter() as large:
        assert len(client.get("/api/v1/projects", headers=auth_headers(member)).json()) == 8
    # Batched: was ~8 extra queries per project.
    assert large.count == small.count, (small.count, large.count)


def test_user_access_query_count_is_flat(client, admin_token):
    """`GET /orgs/{id}/users/{user_id}/access` batches role resolution and
    project-group lookups too (2026-10-05: it timed out the UI for an org
    with ~70 projects), and still lists exactly the projects with a role."""
    org, token = create_org_admin_in(client, admin_token, "Access Batch Co")
    user_id = uuid.UUID(create_org_user(client, token, org["id"], "access_batch@example.com"))
    url = f"/api/v1/orgs/{org['id']}/users/{user_id}/access"

    def grant(count, prefix):
        db = SessionLocal()
        try:
            for i in range(count):
                project_id = uuid.UUID(create_project(client, token, org["id"], f"{prefix} {i}")["id"])
                db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=ProjectRole.STAKEHOLDER))
            db.commit()
        finally:
            db.close()

    grant(2, "Few")
    with _QueryCounter() as small:
        assert len(client.get(url, headers=auth_headers(token)).json()["projects"]) == 2
    grant(6, "Many")
    create_project(client, token, org["id"], "No role here")
    with _QueryCounter() as large:
        listed = client.get(url, headers=auth_headers(token)).json()["projects"]
    assert len(listed) == 8 and all(p["roles"] == ["member", "stakeholder"] for p in listed)
    assert large.count == small.count, (small.count, large.count)
