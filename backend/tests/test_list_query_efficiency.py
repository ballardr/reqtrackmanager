"""Tests for the 2026-10-04 list-endpoint efficiency fixes (found while
root-causing e2e timeouts: the backend saturated a CPU on N+1 queries in the
project and requirements lists).

Covers:
- `GET /projects/{id}/requirements` batching (`prefetch_for_list`): the
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


class _FullVersionRows:
    """Counts the rows fetched by statements that read whole requirement versions (their long text columns) and
    whole requirement records, as opposed to the few columns the list reads to filter and order a project."""

    def __init__(self):
        self.rows = 0
        self.records = 0

    def __call__(self, _conn, cursor, statement, *_args, **_kwargs):
        text = statement.lstrip()
        if "requirement_versions.description" in text and text.upper().startswith("SELECT"):
            self.rows += max(cursor.rowcount, 0)
        # A whole `Requirement` record (the mapped entity starts with `project_id`; the list's plain-column read
        # starts with `id`).
        if text.startswith("SELECT requirements.project_id,"):
            self.records += max(cursor.rowcount, 0)

    def __enter__(self):
        event.listen(engine, "after_cursor_execute", self)
        return self

    def __exit__(self, *_exc):
        event.remove(engine, "after_cursor_execute", self)


def test_requirements_page_cost_does_not_grow_with_the_project(client, admin_token):
    """A page of N costs the same in a small and a large project: the same number of statements, only the
    page's own versions loaded in full, and a response that is the page and nothing more."""
    org, token = create_org_admin_in(client, admin_token, "Page Cost Co")
    project = create_project(client, token, org["id"], "Page Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"
    page = {"limit": 5, "offset": 0}

    _create_requirements(client, token, project["id"], component_id, category_id, 8, "Small")
    with _QueryCounter() as small, _FullVersionRows() as small_rows:
        small_resp = client.get(base, params=page, headers=auth_headers(token))
    _create_requirements(client, token, project["id"], component_id, category_id, 22, "Large")
    with _QueryCounter() as large, _FullVersionRows() as large_rows:
        large_resp = client.get(base, params=page, headers=auth_headers(token))

    assert small_resp.headers["X-Total-Count"] == "8" and large_resp.headers["X-Total-Count"] == "30"
    assert len(small_resp.json()) == len(large_resp.json()) == 5
    assert large.count == small.count, (small.count, large.count)
    assert small_rows.rows == large_rows.rows == 5, (small_rows.rows, large_rows.rows)
    assert small_rows.records == large_rows.records == 5, (small_rows.records, large_rows.records)


def test_requirements_sorted_page_matches_the_full_sorted_list(client, admin_token):
    """Sorting and paging before serialising returns exactly the slice of the full sorted list, for every
    sortable column and direction."""
    org, token = create_org_admin_in(client, admin_token, "Page Sort Co")
    project = create_project(client, token, org["id"], "Page Sort Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"
    for name in ("delta", "Alpha", "charlie", "Bravo", "echo", "Foxtrot", "golf"):
        resp = client.post(base, json={"name": name, "component_id": component_id, "category_id": category_id},
                           headers=auth_headers(token))
        assert resp.status_code == 201, resp.text

    for sort in ("name", "unique_code", "status", "created_at"):
        for order in ("asc", "desc"):
            params = {"sort": sort, "order": order}
            full = client.get(base, params=params, headers=auth_headers(token)).json()
            got = client.get(base, params={**params, "limit": 3, "offset": 2}, headers=auth_headers(token)).json()
            assert [r["id"] for r in got] == [r["id"] for r in full[2:5]], (sort, order)
            assert got == full[2:5]


def test_project_metrics_query_count_does_not_grow_with_the_project(client, admin_token):
    """The overview's counts are database aggregates and its per-type totals read module state once per
    module, so statements per request stay the same as requirements, comments and change requests grow."""
    org, token = create_org_admin_in(client, admin_token, "Metrics Cost Co")
    project = create_project(client, token, org["id"], "Metrics Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    url = f"/api/v1/projects/{project['id']}/metrics"

    ids = _create_requirements(client, token, project["id"], component_id, category_id, 2, "Few")
    with _QueryCounter() as small:
        small_body = client.get(url, headers=auth_headers(token)).json()
    ids += _create_requirements(client, token, project["id"], component_id, category_id, 8, "Many")
    base = f"/api/v1/projects/{project['id']}/requirements/{ids[0]}"
    assert client.post(f"{base}/approve", headers=auth_headers(token)).status_code == 200
    done = client.post(f"{base}/complete", headers=auth_headers(token))
    assert done.status_code == 200, done.text
    with _QueryCounter() as large:
        large_body = client.get(url, headers=auth_headers(token)).json()

    assert (small_body["requirement_count"], large_body["requirement_count"]) == (2, 10)
    assert large_body["requirement_completed_percent"] == 10.0
    assert sum(large_body["requirements_by_status"].values()) == 10
    assert large.count == small.count, (small.count, large.count)


def test_requirement_links_query_count_does_not_grow_with_the_link_count(client, admin_token):
    """A hub requirement's link list resolves its link types, other requirements and their names in a fixed
    number of statements, in both directions, with the same fields a single link shows."""
    org, token = create_org_admin_in(client, admin_token, "Link Cost Co")
    project = create_project(client, token, org["id"], "Link Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"
    ids = _create_requirements(client, token, project["id"], component_id, category_id, 14, "Linked")
    hub, others = ids[0], ids[1:]
    link_type = client.get(f"/api/v1/orgs/{org['id']}/link-types", headers=auth_headers(token)).json()[0]

    def link(source, target):
        resp = client.post(f"{base}/{source}/links", json={"target_requirement_id": target, "link_type_id": link_type["id"]},
                           headers=auth_headers(token))
        assert resp.status_code == 201, resp.text
        return resp.json()

    for other in others[:2]:
        link(hub, other)
    with _QueryCounter() as small:
        few = client.get(f"{base}/{hub}/links", headers=auth_headers(token)).json()
    for other in others[2:7]:
        link(hub, other)
    for other in others[7:]:
        link(other, hub)
    with _QueryCounter() as large:
        many = client.get(f"{base}/{hub}/links", headers=auth_headers(token)).json()

    assert (len(few), len(many)) == (2, len(others))
    assert large.count == small.count, (small.count, large.count)
    assert {item["direction"] for item in many} == {"outgoing", "incoming"}
    by_other = {item["other_requirement_id"]: item for item in many}
    for other_id in others:
        detail = client.get(f"{base}/{other_id}", headers=auth_headers(token)).json()
        got = by_other[other_id]
        assert (got["other_requirement_name"], got["other_requirement_unique_code"]) == (detail["name"], detail["unique_code"])
        assert got["display_name"] == (link_type["forward_name"] if got["direction"] == "outgoing" else link_type["reverse_name"])


def test_requirements_list_filters_and_default_order_are_unchanged(client, admin_token):
    """Status, stage and text filters, and the component / category / manual order, as the list applies them
    (the database does the status and stage filters and the structural ordering)."""
    org, token = create_org_admin_in(client, admin_token, "List Filter Co")
    project = create_project(client, token, org["id"], "List Filter Project")
    headers = auth_headers(token)
    base = f"/api/v1/projects/{project['id']}"

    def structure(name, prefix, second_category=False):
        component = client.post(f"{base}/components", json={"name": name, "prefix": prefix}, headers=headers).json()
        category = client.post(f"{base}/categories", json={"name": f"{name} cat", "prefix": f"{prefix}C", "component_id": component["id"]},
                               headers=headers).json()
        return component["id"], category["id"]

    first = structure("Alpha", "AL")
    second = structure("Beta", "BE")

    def add(name, where):
        resp = client.post(f"{base}/requirements", json={"name": name, "component_id": where[0], "category_id": where[1]}, headers=headers)
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    # Created out of structural order: the list returns component Alpha's before Beta's, then manual order.
    b1, a1, b2, a2 = add("beta one", second), add("alpha one", first), add("beta two", second), add("alpha two", first)
    ordered = [r["name"] for r in client.get(f"{base}/requirements", headers=headers).json()]
    assert ordered == ["alpha one", "alpha two", "beta one", "beta two"]

    assert client.post(f"{base}/requirements/{a2}/approve", headers=headers).status_code == 200
    approved = client.get(f"{base}/requirements", params={"status": "approved"}, headers=headers)
    assert [r["id"] for r in approved.json()] == [a2]
    assert approved.headers["X-Total-Count"] == "1" and approved.headers["X-Total-Unfiltered-Count"] == "4"
    drafts = {r["id"] for r in client.get(f"{base}/requirements", params={"status": "draft"}, headers=headers).json()}
    assert drafts == {a1, b1, b2}

    stage_id = client.get(f"{base}/requirements/{a1}", headers=headers).json()["target_stage_id"]
    on_stage = client.get(f"{base}/requirements", params={"target_stage_id": stage_id}, headers=headers).json()
    assert len(on_stage) == 4
    assert client.get(f"{base}/requirements", params={"target_stage_id": str(uuid.uuid4())}, headers=headers).json() == []

    found = client.get(f"{base}/requirements", params={"search": "BETA", "status": "draft"}, headers=headers).json()
    assert [r["name"] for r in found] == ["beta one", "beta two"]


def test_requirements_sql_filters_and_sort_match_what_python_would_return(client, admin_token):
    """Search, comments, watched, keyword and every sort column, with paging, return exactly the records an
    independent computation selects, including names whose order differs between a locale collation and a
    plain lower-cased comparison (accents, punctuation, mixed case)."""
    org, token = create_org_admin_in(client, admin_token, "SQL Filter Co")
    project = create_project(client, token, org["id"], "SQL Filter Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    headers = auth_headers(token)
    base = f"/api/v1/projects/{project['id']}/requirements"
    names = ["résumé flow", "Zeta", "alpha_b", "alpha-a", "Alpha c", "émile", "Beta (x)", "beta y"]
    made = {}
    for i, name in enumerate(names):
        resp = client.post(base, json={"name": name, "component_id": component_id, "category_id": category_id,
                                       "keywords": ["even"] if i % 2 == 0 else ["odd"]}, headers=headers)
        assert resp.status_code == 201, resp.text
        made[name] = resp.json()
    assert client.post(f"{base}/{made['Zeta']['id']}/comments", json={"body": "c"}, headers=headers).status_code == 201
    assert client.put(f"{base}/{made['beta y']['id']}/subscription", headers=headers).status_code == 204

    def listed(**params):
        resp = client.get(base, params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp, [r["name"] for r in resp.json()]

    for column, key in (("name", lambda r: r["name"].lower()), ("unique_code", lambda r: r["unique_code"].lower()),
                        ("created_at", lambda r: r["created_at"]), ("status", lambda r: r["status"])):
        everything = client.get(base, headers=headers).json()
        for order in ("asc", "desc"):
            expected = [r["name"] for r in sorted(everything, key=key, reverse=order == "desc")]
            _, got = listed(sort=column, order=order)
            if column == "status":
                assert sorted(got) == sorted(expected)  # one status: ties are broken by creation time
            else:
                assert got == expected, (column, order)
            _, page = listed(sort=column, order=order, limit=3, offset=2)
            assert page == got[2:5], (column, order)

    resp, got = listed(search="ALPHA")
    assert sorted(got) == ["Alpha c", "alpha-a", "alpha_b"] and resp.headers["X-Total-Count"] == "3"
    code = made["Zeta"]["unique_code"]
    assert listed(search=code.lower())[1] == ["Zeta"] and listed(search="no such text")[1] == []
    assert listed(has_comments="true")[1] == ["Zeta"]
    assert listed(only_watched="true")[1] == ["beta y"]
    resp, got = listed(keyword="EVEN", sort="name", limit=2, offset=1)
    even = sorted((n for i, n in enumerate(names) if i % 2 == 0), key=str.lower)
    assert got == even[1:3] and resp.headers["X-Total-Count"] == str(len(even))


def test_export_report_and_record_import_statements_do_not_grow_with_the_requirements(client, admin_token):
    """The project export, the requirements report and a record import update read their people, versions, tags
    and structure in a fixed number of statements, not one or more per requirement."""
    org, token = create_org_admin_in(client, admin_token, "Bulk Cost Co")
    project = create_project(client, token, org["id"], "Bulk Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    headers = auth_headers(token)
    base = f"/api/v1/projects/{project['id']}"

    def measure():
        with _QueryCounter() as export:
            exported = client.get(f"{base}/export", headers=headers)
        with _QueryCounter() as report:
            report_resp = client.post(f"{base}/reports", json={"format": "csv"}, headers=headers)
        records_csv = client.get(f"{base}/records/requirement/export", headers=headers).content
        with _QueryCounter() as imported:
            applied = client.post(f"{base}/records/requirement/import", params={"dry_run": "false"},
                                  files={"file": ("r.csv", records_csv, "text/csv")}, headers=headers)
        for resp in (exported, report_resp, applied):
            assert resp.status_code == 200, resp.text
        return export.count, report.count, imported.count

    _create_requirements(client, token, project["id"], component_id, category_id, 3, "Few")
    small = measure()
    _create_requirements(client, token, project["id"], component_id, category_id, 12, "Many")
    large = measure()

    export_small, report_small, import_small = small
    export_large, report_large, import_large = large
    assert export_large == export_small, ("export", small, large)
    assert report_large == report_small, ("report", small, large)
    # The import still finds each named record with one lookup, so it may grow by that much and no more.
    assert import_large - import_small <= 12, ("record import", small, large)


def test_requirement_comments_statements_do_not_grow_with_the_thread(client, admin_token):
    """A thread's authors, reaction counts and attachments are read in one statement each, with the same fields
    a single comment shows."""
    org, token = create_org_admin_in(client, admin_token, "Comment Cost Co")
    project = create_project(client, token, org["id"], "Comment Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement_id = _create_requirements(client, token, project["id"], component_id, category_id, 1, "Thread")[0]
    headers = auth_headers(token)
    url = f"/api/v1/projects/{project['id']}/requirements/{requirement_id}/comments"

    def post(count, first):
        ids = []
        for i in range(count):
            resp = client.post(url, json={"body": f"comment {first + i}"}, headers=headers)
            assert resp.status_code == 201, resp.text
            ids.append(resp.json()["id"])
        return ids

    ids = post(2, 0)
    assert client.put(f"{url}/{ids[0]}/reaction", headers=headers).status_code in (200, 204)
    with _QueryCounter() as small:
        few = client.get(url, headers=headers).json()
    post(10, 2)
    with _QueryCounter() as large:
        many = client.get(url, headers=headers).json()

    assert (len(few), len(many)) == (2, 12)
    assert large.count == small.count, (small.count, large.count)
    assert [c["body"] for c in many] == [f"comment {i}" for i in range(12)]
    assert (many[0]["reaction_count"], many[0]["reacted_by_me"]) == (1, True)
    assert (many[1]["reaction_count"], many[1]["reacted_by_me"]) == (0, False)
    assert all(c["author_display_name"] and c["attachments"] == [] for c in many)


def test_creating_a_requirement_does_not_read_the_projects_requirement_ids(client, admin_token):
    """Numbering a new requirement counts the project's rows in the database; reading every id back to count
    them cost 0.4 s at 5,000 requirements."""
    org, token = create_org_admin_in(client, admin_token, "Create Cost Co")
    project = create_project(client, token, org["id"], "Create Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    base = f"/api/v1/projects/{project['id']}/requirements"
    _create_requirements(client, token, project["id"], component_id, category_id, 12, "Existing")

    rows = []

    def count_id_rows(_conn, cursor, statement, *_args, **_kwargs):
        if statement.lstrip().startswith("SELECT requirements.id FROM requirements WHERE requirements.project_id"):
            rows.append(cursor.rowcount)

    event.listen(engine, "after_cursor_execute", count_id_rows)
    try:
        resp = client.post(base, json={"name": "One more", "component_id": component_id, "category_id": category_id},
                           headers=auth_headers(token))
    finally:
        event.remove(engine, "after_cursor_execute", count_id_rows)
    assert resp.status_code == 201, resp.text
    assert resp.json()["sort_order"] == 12
    assert sum(rows) == 0, rows


def test_project_import_statements_per_requirement_stay_small(client, admin_token):
    """Importing a bundle reads each organisation role and each tag list once, so statements per requirement
    stay at the few the import must write (versions, audit events, tags), not a dozen."""
    org, token = create_org_admin_in(client, admin_token, "Import Cost Co")
    project = create_project(client, token, org["id"], "Import Cost Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    headers = auth_headers(token)
    _create_requirements(client, token, project["id"], component_id, category_id, 30, "Bundled")
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)
    assert exported.status_code == 200

    with _QueryCounter() as counter:
        resp = client.post("/api/v1/projects/import", data={"organization_id": org["id"], "name": "Copy"},
                           files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=headers)
    assert resp.status_code == 201, resp.text
    imported = client.get(f"/api/v1/projects/{resp.json()['project']['id']}/requirements", headers=headers).json()
    assert sorted(r["name"] for r in imported) == sorted(f"Bundled {i}" for i in range(30))
    assert all(sorted(r["keywords"]) == sorted(["shared", f"kw{r['name'].split()[1]}"]) for r in imported)
    assert counter.count / 30 < 9, counter.count


def test_requirements_total_count_is_right_for_every_page_shape(client, admin_token):
    """`X-Total-Count` for the first page, a full page, a short last page, a page past the end, an unpaged list and a
    filtered list, whether it is taken from the rows read or counted separately."""
    org, token = create_org_admin_in(client, admin_token, "Total Count Co")
    project = create_project(client, token, org["id"], "Total Count Project")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    headers = auth_headers(token)
    base = f"/api/v1/projects/{project['id']}/requirements"
    _create_requirements(client, token, project["id"], component_id, category_id, 7, "Counted")

    def total(**params):
        resp = client.get(base, params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.headers["X-Total-Count"], len(resp.json())

    assert total() == ("7", 7)
    assert total(limit=3) == ("7", 3), "a full first page: counted separately"
    assert total(limit=3, offset=3) == ("7", 3)
    assert total(limit=3, offset=6) == ("7", 1), "the short last page"
    assert total(limit=50) == ("7", 7), "a first page that is not full"
    assert total(limit=3, offset=30) == ("7", 0), "a page past the end still reports the real total"
    assert total(limit=50, search="counted 1") == ("1", 1)
    assert total(limit=2, search="counted") == ("7", 2)
    assert total(limit=50, search="nothing like this") == ("0", 0)


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
