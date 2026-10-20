"""Tests for the `project_scope` list filter: a list widened to the parent and/or child projects
the caller can open (`services.project_scope`).

Every test builds its own organisation (`tests.link_world.World`), so none depends on state left by
another test or run. Time is not involved: the filter reads structure and permissions only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import event

from app.database import engine
from app.main import app
from app.services import project_scope as project_scope_service
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

#: Every project-scoped list that offers the filter, as `(path under the project, module to enable)`.
SCOPED_LISTS = [
    ("/requirements", None),
    ("/actions", None),
    ("/change-requests", None),
    ("/modules/decisions", "decisions"),
    ("/modules/risk_management/risks", "risk_management"),
    ("/modules/compliance/evidence", "compliance"),
    ("/modules/context_strategy/strategies", "context_strategy"),
    ("/modules/context_strategy/future-states", "context_strategy"),
    ("/modules/context_strategy/pain-points", "context_strategy"),
    ("/modules/context_strategy/guiding-principles", "context_strategy"),
    ("/modules/context_strategy/open-questions", "context_strategy"),
    ("/modules/stakeholders/personas", "stakeholders"),
    ("/modules/stakeholders/stakeholders", "stakeholders"),
    ("/modules/stakeholders/needs", "stakeholders"),
    ("/modules/stakeholders/stakeholder-groups", "stakeholders"),
    ("/modules/stakeholders/engagements", "stakeholders"),
    ("/modules/stakeholders/findings", "stakeholders"),
    ("/files", None),
    ("/modules/compliance/status", "compliance"),
]

#: Tagged lists that deliberately do not take `project_scope`, with the reason.
NOT_SCOPED = {
    # One standard assignment's own requirements: the list is inside a single project's assignment.
    "/api/v1/projects/{project_id}/modules/compliance/project-compliance/{project_compliance_id}/requirements",
}


@dataclass
class Tree:
    """root > child > grandchild, plus a sibling of child; one requirement in each."""

    world: World
    root: dict
    child: dict
    grandchild: dict
    sibling: dict


@pytest.fixture
def tree(client, admin_token) -> Tree:
    world = World(client, admin_token, "Scope Org", decisions=True, context_strategy=True)
    root = world.project("Root")
    child = world.project("Child", parent=root)
    grandchild = world.project("Grandchild", parent=child)
    sibling = world.project("Sibling", parent=root)
    for project in (root, child, grandchild, sibling):
        world.requirement(project, f"Req {project['name']}")
    return Tree(world, root, child, grandchild, sibling)


def _names(tree: Tree, project: dict, scope: str | None, *, token: str | None = None) -> list[str]:
    """The requirement names listed for `project` under `scope` (no parameter when `None`)."""
    suffix = f"?project_scope={scope}" if scope else ""
    resp = tree.world.client.get(
        f"/api/v1/projects/{project['id']}/requirements{suffix}", headers=auth_headers(token or tree.world.token)
    )
    assert resp.status_code == 200, resp.text
    return [row["name"] for row in resp.json()]


def _member(world: World, project: dict, role: str = "member") -> str:
    """A token for a user who holds only `role` on `project`."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def test_each_option_lists_the_expected_projects(tree):
    assert _names(tree, tree.child, None) == ["Req Child"]
    assert _names(tree, tree.child, "this") == ["Req Child"]
    assert _names(tree, tree.child, "parents") == ["Req Child", "Req Root"]
    assert _names(tree, tree.child, "children") == ["Req Child", "Req Grandchild"]
    assert _names(tree, tree.child, "both") == ["Req Child", "Req Root", "Req Grandchild"]


def test_parents_and_children_walk_the_whole_chain_and_skip_siblings(tree):
    assert _names(tree, tree.grandchild, "parents") == ["Req Grandchild", "Req Child", "Req Root"]
    assert _names(tree, tree.root, "children") == ["Req Root", "Req Child", "Req Sibling", "Req Grandchild"]
    assert "Req Sibling" not in _names(tree, tree.child, "both")


def test_rows_from_another_project_carry_its_label_and_own_rows_carry_none(tree):
    resp = tree.world.client.get(
        f"/api/v1/projects/{tree.child['id']}/requirements?project_scope=parents", headers=auth_headers(tree.world.token)
    )
    own, parent = resp.json()
    assert own["from_project_id"] is None and own["from_project_name"] is None and own["from_project_code"] is None
    assert parent["from_project_id"] == tree.root["id"]
    assert parent["from_project_name"] == "Root" and parent["from_project_code"] == tree.root["code"]


def test_a_project_without_relatives_is_unchanged_by_any_scope(client, admin_token):
    world = World(client, admin_token, "Lone Org")
    project = world.project("Lone")
    world.requirement(project, "Only")
    for scope in ("this", "parents", "children", "both"):
        resp = client.get(
            f"/api/v1/projects/{project['id']}/requirements?project_scope={scope}", headers=auth_headers(world.token)
        )
        assert [r["name"] for r in resp.json()] == ["Only"]


def test_an_unknown_scope_is_rejected(tree):
    resp = tree.world.client.get(
        f"/api/v1/projects/{tree.child['id']}/requirements?project_scope=siblings", headers=auth_headers(tree.world.token)
    )
    assert resp.status_code == 422


def test_a_project_the_caller_cannot_open_is_omitted_not_redacted(tree):
    """Access to the parent only: the child's rows never appear, and nothing says they exist."""
    parent_only = _member(tree.world, tree.root)

    listed = _names(tree, tree.root, "children", token=parent_only)

    assert listed == ["Req Root"]


def _pat(world: World, project_ids: list[str] | None) -> dict:
    """Headers for a Personal Access Token of the org admin, scoped to the org and (optionally) to projects."""
    payload = {"name": f"scope-{uuid.uuid4().hex[:6]}", "allowed_organization_ids": [world.org["id"]]}
    if project_ids is not None:
        payload["allowed_project_ids"] = project_ids
    resp = world.client.post("/api/v1/me/pats", json=payload, headers=auth_headers(world.token))
    assert resp.status_code == 201, resp.text
    return auth_headers(resp.json()["token"])


def test_a_token_scoped_to_one_project_does_not_reach_its_parent_through_the_scope(tree):
    """The token's project scope holds for a related project read on the caller's behalf."""
    world = tree.world
    child_only = _pat(world, [tree.child["id"]])
    whole_org = _pat(world, None)
    url = f"/api/v1/projects/{tree.child['id']}/requirements?project_scope=both"

    narrow = world.client.get(url, headers=child_only)
    wide = world.client.get(url, headers=whole_org)

    assert [r["name"] for r in narrow.json()] == ["Req Child"]
    assert [r["name"] for r in wide.json()] == ["Req Child", "Req Root", "Req Grandchild"]
    options = world.client.get(f"/api/v1/projects/{tree.child['id']}/scope-options", headers=child_only).json()
    assert options["has_parents"] is False and options["has_children"] is False


def test_the_walk_up_stops_at_the_first_unopenable_ancestor(tree):
    """A grandchild member who cannot open the child sees neither the child nor the root above it."""
    grandchild_only = _member(tree.world, tree.grandchild)

    assert _names(tree, tree.grandchild, "parents", token=grandchild_only) == ["Req Grandchild"]


def test_a_module_disabled_in_the_source_project_omits_its_rows(tree):
    world = tree.world
    world.decision(tree.root, "DEC-ROOT")
    world.decision(tree.child, "DEC-CHILD")
    url = f"/api/v1/projects/{tree.child['id']}/modules/decisions?project_scope=parents"

    codes = {row["unique_code"] for row in world.client.get(url, headers=auth_headers(world.token)).json()}
    assert codes == {"DEC-ROOT", "DEC-CHILD"}

    off = world.client.put(
        f"/api/v1/projects/{tree.root['id']}/modules/decisions/enablement", json={"enabled": False},
        headers=auth_headers(world.token),
    )
    assert off.status_code == 200, off.text
    codes = {row["unique_code"] for row in world.client.get(url, headers=auth_headers(world.token)).json()}
    assert codes == {"DEC-CHILD"}


def test_a_record_type_the_caller_cannot_view_in_the_source_project_is_omitted(monkeypatch, tree):
    world = tree.world
    world.decision(tree.root, "DEC-ROOT")
    world.decision(tree.child, "DEC-CHILD")
    real = project_scope_service.get_effective_permissions
    monkeypatch.setattr(
        project_scope_service, "get_effective_permissions",
        lambda *args, **kwargs: {p for p in real(*args, **kwargs) if not p.startswith("decision:view")},
    )

    resp = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/modules/decisions?project_scope=parents", headers=auth_headers(world.token)
    )

    assert {row["unique_code"] for row in resp.json()} == {"DEC-CHILD"}


def test_an_archived_related_project_is_left_out(tree):
    world = tree.world
    resp = world.client.post(f"/api/v1/projects/{tree.grandchild['id']}/archive", headers=auth_headers(world.token))
    assert resp.status_code in (200, 204), resp.text

    assert "Req Grandchild" not in _names(tree, tree.child, "children")


def test_another_organisations_projects_never_appear(client, admin_token, tree):
    other = World(client, admin_token, "Foreign Org")
    foreign = other.project("Foreign")
    other.requirement(foreign, "Foreign req")

    for scope in ("parents", "children", "both"):
        assert "Foreign req" not in _names(tree, tree.child, scope)


def test_filters_still_apply_in_each_project(tree):
    world = tree.world
    resp = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/requirements?project_scope=both&search=Root",
        headers=auth_headers(world.token),
    )
    assert [r["name"] for r in resp.json()] == ["Req Root"]


def test_requirement_counts_and_paging_cover_every_listed_project(tree):
    world = tree.world
    url = f"/api/v1/projects/{tree.child['id']}/requirements?project_scope=both"

    page = world.client.get(f"{url}&limit=2&offset=1", headers=auth_headers(world.token))

    assert page.headers["X-Total-Count"] == "3" and page.headers["X-Total-Unfiltered-Count"] == "3"
    assert [r["name"] for r in page.json()] == ["Req Root", "Req Grandchild"]


def test_an_organisation_record_is_listed_once_and_unlabelled(client, admin_token):
    world = World(client, admin_token, "Org Persona Org")
    world.enable("stakeholders")
    root = world.project("Root")
    child = world.project("Child", parent=root)
    auth = auth_headers(world.token)
    org_persona = client.post(
        f"/api/v1/orgs/{world.org['id']}/modules/stakeholders/personas", json={"name": "Org persona"}, headers=auth
    )
    assert org_persona.status_code == 201, org_persona.text
    client.post(f"/api/v1/projects/{root['id']}/modules/stakeholders/personas", json={"name": "Root persona"}, headers=auth)

    rows = client.get(
        f"/api/v1/projects/{child['id']}/modules/stakeholders/personas?project_scope=parents", headers=auth
    ).json()

    assert sorted((r["name"], r["from_project_id"]) for r in rows) == [
        ("Org persona", None), ("Root persona", root["id"]),
    ]


def test_actions_from_related_projects_are_listed_and_labelled(tree):
    world = tree.world
    world.action(tree.root, "Root action")
    world.action(tree.child, "Child action")

    resp = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/actions?project_scope=parents", headers=auth_headers(world.token)
    )

    assert [(r["title"], r["from_project_id"]) for r in resp.json()] == [
        ("Child action", None), ("Root action", tree.root["id"]),
    ]


def test_query_count_does_not_grow_with_the_rows_of_a_related_project(tree):
    """One resolution of the project set and one query set per project: more rows add no queries."""
    world = tree.world
    url = f"/api/v1/projects/{tree.child['id']}/actions?project_scope=parents"
    world.action(tree.root, "First")

    def count_statements() -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert world.client.get(url, headers=auth_headers(world.token)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    few = count_statements()
    for index in range(5):
        world.action(tree.root, f"More {index}")

    assert count_statements() == few


def test_scope_options_report_openable_relatives_only(tree):
    world = tree.world

    def options(project: dict, token: str | None = None) -> dict:
        resp = world.client.get(
            f"/api/v1/projects/{project['id']}/scope-options", headers=auth_headers(token or world.token)
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert options(tree.root) == {"has_parents": False, "has_children": True, "truncated": False}
    assert options(tree.child)["has_parents"] and options(tree.child)["has_children"]
    assert options(tree.grandchild) == {"has_parents": True, "has_children": False, "truncated": False}
    assert options(tree.root, _member(world, tree.root))["has_children"] is False


@pytest.mark.parametrize(("path", "module"), SCOPED_LISTS)
def test_every_scoped_list_accepts_the_parameter(client, admin_token, path, module):
    world = World(client, admin_token, "Smoke Org", decisions=True, context_strategy=True)
    if module in ("risk_management", "compliance", "stakeholders"):
        world.enable(module)
    if path.endswith("/findings"):
        resp = client.put(
            f"/api/v1/orgs/{world.org['id']}/modules/stakeholders/subcomponents/research_extras",
            json={"enabled": True}, headers=auth_headers(world.token),
        )
        assert resp.status_code == 200, resp.text
    root = world.project("Root")
    child = world.project("Child", parent=root)

    for scope in ("this", "both"):
        resp = client.get(
            f"/api/v1/projects/{child['id']}{path}?project_scope={scope}", headers=auth_headers(world.token)
        )
        assert resp.status_code == 200, f"{path} {scope}: {resp.text}"


def _query_param_names(dependant) -> set[str]:
    """Every query parameter of a route, including those of its class dependencies."""
    names = {q.name for q in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _query_param_names(sub)
    return names


def test_every_tagged_list_also_takes_project_scope():
    """A new tagged list must offer the scope filter too (or be named in `NOT_SCOPED` with a reason)."""
    missing = []
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None or "GET" not in getattr(route, "methods", set()):
            continue
        params = _query_param_names(dependant)
        if "tag" in params and "project_scope" not in params and route.path not in NOT_SCOPED:
            missing.append(route.path)
    assert missing == []


def test_the_tag_finder_looks_in_related_projects_only_when_asked(tree):
    world = tree.world
    root_req = world.requirement(tree.root, "Tagged in the parent")
    child_req = world.requirement(tree.child, "Tagged in the child")
    for project, req in ((tree.root, root_req), (tree.child, child_req)):
        done = world.client.put(
            f"/api/v1/projects/{project['id']}/artefacts/requirement/{req}/tags", json={"tags": ["Shared"]},
            headers=auth_headers(world.token),
        )
        assert done.status_code == 200, done.text
    url = f"/api/v1/projects/{tree.child['id']}/tags/records?tag=Shared"

    own = world.client.get(url, headers=auth_headers(world.token)).json()["records"]
    wide = world.client.get(f"{url}&project_scope=parents", headers=auth_headers(world.token)).json()["records"]

    assert [r["id"] for r in own] == [str(child_req)]
    assert {r["id"] for r in wide} == {str(child_req), str(root_req)}
    parent_row = next(r for r in wide if r["id"] == str(root_req))
    assert (parent_row["project_id"], parent_row["project_name"]) == (tree.root["id"], "Root")
    parent_only = _member(world, tree.root)
    assert world.client.get(f"{url}&project_scope=both", headers=auth_headers(parent_only)).status_code == 403


def test_overview_metrics_sum_the_listed_projects_and_keep_stage_progress_per_project(tree):
    world = tree.world
    world.requirement(tree.child, "Second child requirement")
    base = f"/api/v1/projects/{tree.child['id']}/metrics"

    own = world.client.get(base, headers=auth_headers(world.token)).json()
    wide = world.client.get(f"{base}?project_scope=both", headers=auth_headers(world.token)).json()

    assert (own["requirement_count"], own["scope_project_count"]) == (2, 1)
    assert (wide["requirement_count"], wide["scope_project_count"]) == (4, 3)  # child 2, root 1, grandchild 1
    assert sum(wide["requirements_by_status"].values()) == 4
    assert [s["stage_id"] for s in wide["stage_progress"]] == [s["stage_id"] for s in own["stage_progress"]]
    only_child = _member(world, tree.child)
    narrow = world.client.get(f"{base}?project_scope=both", headers=auth_headers(only_child)).json()
    assert (narrow["requirement_count"], narrow["scope_project_count"]) == (2, 1)


def test_files_of_related_projects_are_listed_and_labelled(tree):
    world = tree.world
    for project, name in ((tree.root, "root.txt"), (tree.child, "child.txt")):
        req = world.requirement(project, f"Has {name}")
        done = world.client.post(
            f"/api/v1/projects/{project['id']}/requirements/{req}/files",
            files={"file": (name, b"data", "text/plain")}, headers=auth_headers(world.token),
        )
        assert done.status_code == 201, done.text
    url = f"/api/v1/projects/{tree.child['id']}/files"

    own = world.client.get(url, headers=auth_headers(world.token))
    wide = world.client.get(f"{url}?project_scope=parents", headers=auth_headers(world.token))

    assert [r["file"]["filename"] for r in own.json()] == ["child.txt"]
    assert [(r["file"]["filename"], r["from_project_id"]) for r in wide.json()] == [
        ("child.txt", None), ("root.txt", tree.root["id"]),
    ]
    assert wide.headers["X-Total-Count"] == "2"


def test_compliance_status_of_related_projects_is_listed_with_its_project(client, admin_token):
    world = World(client, admin_token, "Compliance Scope Org")
    world.enable("compliance")
    root = world.project("Root")
    child = world.project("Child", parent=root)

    for project in (root, child):
        resp = client.get(
            f"/api/v1/projects/{project['id']}/modules/compliance/status?project_scope=both",
            headers=auth_headers(world.token),
        )
        assert resp.status_code == 200 and resp.json() == []
