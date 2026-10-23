"""Tests for links between a project and its ancestors/descendants
: each link type's
`nesting_scope` decides whether and in which direction such a link is allowed;
every end is authorised in its own project; a cross-level link never reaches a
reader that assumes both ends share a project; and reparenting makes a link
dormant rather than deleting it.

Each test builds its own organisation (`tests.link_world.World`), so none depends
on state left by another test or run.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.relationship import ArtefactLink
from app.services.relationships import get_all_links, get_links_from
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Link Nesting Org")


@dataclass
class Tree:
    """root > child > grandchild, root > sibling, plus an unrelated root; one requirement in each."""

    root: dict
    child: dict
    grandchild: dict
    sibling: dict
    other: dict
    req: dict[str, uuid.UUID]


@pytest.fixture
def tree(world) -> Tree:
    root = world.project("Root")
    child = world.project("Child", parent=root)
    grandchild = world.project("Grandchild", parent=child)
    sibling = world.project("Sibling", parent=root)
    other = world.project("Other root")
    projects = {"root": root, "child": child, "grandchild": grandchild, "sibling": sibling, "other": other}
    return Tree(
        root=root, child=child, grandchild=grandchild, sibling=sibling, other=other,
        req={name: world.requirement(project, f"Req {name}") for name, project in projects.items()},
    )


def _scoped(world: World, scope: str, flow: str = "none") -> uuid.UUID:
    """An organisation-wide link type with the given nesting scope."""
    return world.link_type("Scoped", "Reverse scoped", flow, scope)


def _member(world: World, project: dict, role: str = "member") -> str:
    """A user holding only `role` on `project`."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _links_of(*artefact_ids: uuid.UUID) -> list[ArtefactLink]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(ArtefactLink).where(
                    ArtefactLink.source_id.in_(artefact_ids) | ArtefactLink.target_id.in_(artefact_ids)
                )
            ).all()
        )
    finally:
        db.close()


def _set_parent(world: World, project: dict, parent: dict | None) -> None:
    resp = world.client.patch(
        f"/api/v1/projects/{project['id']}", json={"parent_project_id": parent["id"] if parent else None},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text


def _options(world: World, project: dict, artefact: tuple[str, uuid.UUID], other_project: dict, token=None):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-types",
        params={"other_project_id": other_project["id"]}, headers=auth_headers(token or world.token),
    )


# --- the nesting-scope matrix -------------------------------------------------------------


def test_either_way_type_links_a_project_to_its_parent_and_child_from_both_ends(world, tree):
    related = _scoped(world, "ancestor_either_way")
    up = world.generic_link(tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root)
    down = world.generic_link(
        tree.root, (REQ, tree.req["root"]), related, (REQ, tree.req["grandchild"]), other_project=tree.grandchild,
    )
    assert up.status_code == 201, up.text
    assert up.json()["other"]["project_id"] == tree.root["id"]
    assert down.status_code == 201, down.text  # a grandchild is a descendant, not only a direct child

    stored = {(link.source_id, link.target_id): link for link in _links_of(tree.req["child"], tree.req["root"])}
    cross = stored[(tree.req["child"], tree.req["root"])]
    assert str(cross.source_project_id) == tree.child["id"] and str(cross.target_project_id) == tree.root["id"]


def test_same_project_type_refuses_cross_level_but_still_links_within_a_project(world, tree):
    same_only = _scoped(world, "same_project")
    refused = world.generic_link(
        tree.child, (REQ, tree.req["child"]), same_only, (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert refused.status_code == 400
    assert "within one project" in refused.json()["detail"]

    sibling_req = world.requirement(tree.child, "Another in child")
    ok = world.generic_link(tree.child, (REQ, tree.req["child"]), same_only, (REQ, sibling_req))
    assert ok.status_code == 201
    assert [link.source_project_id for link in _links_of(sibling_req)] == [None]  # an ordinary link stays unmarked


@pytest.mark.parametrize(
    ("flow", "upstream_is_target"),
    [("forward_is_upstream", True), ("forward_is_downstream", False)],
)
def test_directional_type_needs_the_upstream_end_in_the_same_or_a_parent_project(world, tree, flow, upstream_is_target):
    directional = _scoped(world, "upstream_in_ancestor", flow)
    root_req, child_req = (REQ, tree.req["root"]), (REQ, tree.req["child"])
    # With forward_is_upstream the target is upstream, so the parent must be the target.
    parent_is_source = not upstream_is_target
    allowed = (
        world.generic_link(tree.root, root_req, directional, child_req, other_project=tree.child)
        if parent_is_source
        else world.generic_link(tree.child, child_req, directional, root_req, other_project=tree.root)
    )
    refused = (
        world.generic_link(tree.child, child_req, directional, root_req, other_project=tree.root)
        if parent_is_source
        else world.generic_link(tree.root, root_req, directional, child_req, other_project=tree.child)
    )
    assert allowed.status_code == 201, allowed.text
    assert refused.status_code == 400
    assert "upstream end" in refused.json()["detail"]


def test_directional_scope_needs_a_flow_on_create_and_on_a_flow_change(world, tree):
    base = f"/api/v1/orgs/{world.org['id']}/link-types"
    bad = world.client.post(
        base, json={"forward_name": "No dir", "reverse_name": "x", "flow": "none", "nesting_scope": "upstream_in_ancestor"},
        headers=auth_headers(world.token),
    )
    assert bad.status_code == 422

    directional = _scoped(world, "upstream_in_ancestor", "forward_is_upstream")
    current = next(t for t in world.client.get(base, headers=auth_headers(world.token)).json() if t["id"] == str(directional))
    flow_none = world.client.patch(
        f"{base}/{directional}", json={"forward_name": current["forward_name"], "reverse_name": "r", "flow": "none"},
        headers=auth_headers(world.token),
    )
    assert flow_none.status_code == 422
    # Widening the scope and clearing the flow together is fine.
    ok = world.client.patch(
        f"{base}/{directional}",
        json={"forward_name": current["forward_name"], "reverse_name": "r", "flow": "none", "nesting_scope": "ancestor_either_way"},
        headers=auth_headers(world.token),
    )
    assert ok.status_code == 200 and ok.json()["nesting_scope"] == "ancestor_either_way"


def test_new_and_existing_types_default_to_either_way(world):
    assert all(t["nesting_scope"] == "ancestor_either_way" for t in world.link_types_by_name().values())


@pytest.mark.parametrize("target", ["sibling", "other"])
def test_siblings_and_unrelated_projects_cannot_be_linked_and_are_not_disclosed(world, tree, target):
    related = _scoped(world, "ancestor_either_way")
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req[target]), other_project=getattr(tree, target),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Linked record not found."


def test_a_project_of_another_organisation_is_not_found(client, admin_token, world, tree):
    foreign = World(client, admin_token, "Foreign Org")
    foreign_project = foreign.project("Foreign")
    foreign_req = foreign.requirement(foreign_project)
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), _scoped(world, "ancestor_either_way"), (REQ, foreign_req),
        other_project=foreign_project,
    )
    assert resp.status_code == 404


def test_the_other_end_must_belong_to_the_named_project(world, tree):
    related = _scoped(world, "ancestor_either_way")
    # The grandchild's requirement named as if it lived in the root.
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["grandchild"]), other_project=tree.root,
    )
    assert resp.status_code == 404


def test_a_same_project_link_is_unchanged_when_the_project_is_named_explicitly(world, tree):
    related = _scoped(world, "ancestor_either_way")
    other = world.requirement(tree.root, "Second root req")
    resp = world.generic_link(tree.root, (REQ, tree.req["root"]), related, (REQ, other), other_project=tree.root)
    assert resp.status_code == 201
    assert _links_of(other)[0].source_project_id is None


# --- authorisation per end -----------------------------------------------------------------


def test_a_child_only_member_cannot_link_to_or_learn_about_the_parent(world, tree):
    related = _scoped(world, "ancestor_either_way")
    child_member = _member(world, tree.child, "project_manager")
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), token=child_member,
        other_project=tree.root,
    )
    assert resp.status_code == 404  # no role on the parent: same answer as "does not exist"
    assert _options(world, tree.child, (REQ, tree.req["child"]), tree.root, token=child_member).status_code == 404

    candidates = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/link-candidate-projects", headers=auth_headers(child_member),
    ).json()
    assert [c["id"] for c in candidates["items"]] == [tree.child["id"]]  # the parent's existence is not hinted at


def test_view_on_the_other_end_is_not_enough_without_manage_on_the_page_artefact(world, tree):
    related = _scoped(world, "ancestor_either_way")
    both_viewer = _member(world, tree.child, "member")
    world.client.post(
        f"/api/v1/projects/{tree.root['id']}/roles",
        json={"user_id": next(iter(_user_ids(world, both_viewer))), "role": "member"}, headers=auth_headers(world.token),
    )
    # A plain member can view but not manage requirement links in the page's project.
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), token=both_viewer,
        other_project=tree.root,
    )
    assert resp.status_code == 403


def _user_ids(world: World, token: str) -> set[str]:
    return {world.client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]}


def test_a_member_of_both_projects_with_manage_can_link(world, tree):
    related = _scoped(world, "ancestor_either_way")
    manager = _member(world, tree.child, "project_manager")
    world.client.post(
        f"/api/v1/projects/{tree.root['id']}/roles",
        json={"user_id": next(iter(_user_ids(world, manager))), "role": "member"}, headers=auth_headers(world.token),
    )
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), token=manager, other_project=tree.root,
    )
    assert resp.status_code == 201, resp.text


# --- link type usability and artefact rules, per end -----------------------------------------


def _local_type(world: World, project: dict, name: str, **extra) -> dict:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/link-types",
        json={"forward_name": name, "reverse_name": f"Reverse {name}", **extra}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_an_ancestor_local_type_works_from_the_child_but_a_descendant_local_type_cannot_reach_up(world, tree):
    parents_type = _local_type(world, tree.root, "Parent only")
    childs_type = _local_type(world, tree.child, "Child only")
    up = world.generic_link(
        tree.child, (REQ, tree.req["child"]), parents_type["id"], (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert up.status_code == 201, up.text
    refused = world.generic_link(
        tree.child, (REQ, tree.req["child"]), childs_type["id"], (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert refused.status_code == 400  # the parent side cannot use a type its descendant defined
    assert "available to this project" in refused.json()["detail"]

    offered_up = {o["forward_name"] for o in _options(world, tree.child, (REQ, tree.req["child"]), tree.root).json()}
    assert "Parent only" in offered_up and "Child only" not in offered_up
    # Within the child itself both are offered.
    same = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/artefacts/{REQ}/{tree.req['child']}/link-types", headers=auth_headers(world.token),
    ).json()
    assert {"Parent only", "Child only"} <= {o["forward_name"] for o in same}


def test_a_type_hidden_in_the_creating_project_is_refused(world, tree):
    related = _scoped(world, "ancestor_either_way")
    hide = world.client.put(
        f"/api/v1/projects/{tree.child['id']}/link-types/{related}/visibility", json={"hidden": True},
        headers=auth_headers(world.token),
    )
    assert hide.status_code == 200, hide.text
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert resp.status_code == 400
    assert "hidden" in resp.json()["detail"]


def test_each_end_applies_its_own_projects_artefact_rule(world, tree):
    allowed = _scoped(world, "ancestor_either_way")
    other = _scoped(world, "ancestor_either_way")
    # The parent's project limits requirements to `allowed` only; the child has no rule.
    rule = world.client.put(
        f"/api/v1/projects/{tree.root['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [str(allowed)]},
        headers=auth_headers(world.token),
    )
    assert rule.status_code == 200, rule.text
    vetoed = world.generic_link(
        tree.child, (REQ, tree.req["child"]), other, (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert vetoed.status_code == 400
    assert "limited to specific link types" in vetoed.json()["detail"]
    ok = world.generic_link(
        tree.child, (REQ, tree.req["child"]), allowed, (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert ok.status_code == 201, ok.text
    # The child's own rule replaces the parent's for the child's end, but the parent's end still vetoes.
    child_rule = world.client.put(
        f"/api/v1/projects/{tree.child['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [str(other)]},
        headers=auth_headers(world.token),
    )
    assert child_rule.status_code == 200, child_rule.text
    still_vetoed = world.generic_link(
        tree.child, (REQ, tree.req["child"]), other, (REQ, tree.req["root"]), other_project=tree.root,
    )
    assert still_vetoed.status_code == 400
    neighbour = world.requirement(tree.child, "Second")
    assert world.generic_link(tree.child, (REQ, tree.req["child"]), other, (REQ, neighbour)).status_code == 201


def test_link_type_options_follow_the_nesting_scope_and_orientation(world, tree):
    directional = world.link_type("Derives", "Is source of", "forward_is_upstream", "upstream_in_ancestor")
    same_only = _scoped(world, "same_project")
    child_page = (REQ, tree.req["child"])
    from_child = {o["link_type_id"]: o for o in _options(world, tree.child, child_page, tree.root).json()}
    # On the child's page the parent is upstream: only the incoming orientation (parent is the target) fits.
    assert str(directional) in from_child
    assert from_child[str(directional)]["direction"] == "outgoing"
    assert str(same_only) not in from_child

    from_root = {
        o["link_type_id"]: o
        for o in _options(world, tree.root, (REQ, tree.req["root"]), tree.child).json()
    }
    # From the parent's page, the parent must be the *target* of a forward-upstream link: incoming.
    assert from_root[str(directional)]["direction"] == "incoming"
    assert from_root[str(directional)]["nesting_scope"] == "upstream_in_ancestor"

    assert _options(world, tree.child, child_page, tree.sibling).status_code == 404


# --- candidate projects -----------------------------------------------------------------------


def test_candidate_projects_list_self_ancestors_and_descendants_with_relationship_labels(world, tree):
    resp = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/link-candidate-projects", headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [(i["id"], i["relation"], i["distance"], i["label"]) for i in items] == [
        (tree.child["id"], "same", 0, "This project"),
        (tree.root["id"], "ancestor", 1, "Parent project"),
        (tree.grandchild["id"], "descendant", 1, "Child project"),
    ]
    assert resp.json()["truncated"] is False
    # Siblings and unrelated projects are never offered.
    assert not {tree.sibling["id"], tree.other["id"]} & {i["id"] for i in items}


def test_candidate_projects_stop_at_the_first_ancestor_the_caller_cannot_open(world, tree):
    # A member of the grandchild and the root, but not the child between them.
    token = _member(world, tree.grandchild)
    user_id = next(iter(_user_ids(world, token)))
    world.client.post(
        f"/api/v1/projects/{tree.root['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(world.token),
    )
    items = world.client.get(
        f"/api/v1/projects/{tree.grandchild['id']}/link-candidate-projects", headers=auth_headers(token)
    ).json()["items"]
    assert [i["id"] for i in items] == [tree.grandchild["id"]]  # the hole at the child hides the root too


def test_archived_projects_are_not_offered_as_targets_and_refuse_new_links(world, tree):
    related = _scoped(world, "ancestor_either_way")
    archive = world.client.post(f"/api/v1/projects/{tree.grandchild['id']}/archive", headers=auth_headers(world.token))
    assert archive.status_code in (200, 204), archive.text
    items = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/link-candidate-projects", headers=auth_headers(world.token)
    ).json()["items"]
    assert tree.grandchild["id"] not in {i["id"] for i in items}
    resp = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["grandchild"]), other_project=tree.grandchild,
    )
    assert resp.status_code == 400


# --- the link graph ---------------------------------------------------------------------------


def _graph_ids(graph: dict) -> set[str]:
    return {n["id"] for n in graph["nodes"]}


def test_a_cross_level_link_shows_in_the_graph_from_both_pages_with_project_labels(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201

    from_child = world.graph(tree.child, (REQ, tree.req["child"])).json()
    from_root = world.graph(tree.root, (REQ, tree.req["root"])).json()
    assert str(tree.req["root"]) in _graph_ids(from_child) and str(tree.req["child"]) in _graph_ids(from_root)
    parent_node = next(n for n in from_child["nodes"] if n["id"] == str(tree.req["root"]))
    assert (parent_node["project_id"], parent_node["project_name"]) == (tree.root["id"], "Root")
    assert from_child["edges"][0]["cross_project"] is True and from_child["edges"][0]["nesting_permitted"] is True


def test_a_token_scoped_to_the_child_does_not_see_the_parent_through_the_graph_or_link_options(world, tree):
    """A Personal Access Token limited to one project does not reach the parent through a read of
    related projects, even though its user holds a role on both."""
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    pat = world.client.post(
        "/api/v1/me/pats",
        json={"name": "child-only", "allowed_organization_ids": [world.org["id"]], "allowed_project_ids": [tree.child["id"]]},
        headers=auth_headers(world.token),
    )
    assert pat.status_code == 201, pat.text
    narrow = pat.json()["token"]

    scoped = world.graph(tree.child, (REQ, tree.req["child"]), token=narrow).json()
    full = world.graph(tree.child, (REQ, tree.req["child"])).json()

    assert str(tree.req["root"]) in _graph_ids(full)
    assert str(tree.req["root"]) not in _graph_ids(scoped)
    assert scoped["hidden_count"] == 1
    refused = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), token=narrow, other_project=tree.root,
    )
    assert refused.status_code == 404  # the same answer as "does not exist"


def test_siblings_are_out_of_scope_even_through_a_shared_parent(world, tree):
    related = _scoped(world, "ancestor_either_way")
    # Parent's requirement linked down to both children.
    for name, project in (("child", tree.child), ("sibling", tree.sibling)):
        assert world.generic_link(
            tree.root, (REQ, tree.req["root"]), related, (REQ, tree.req[name]), other_project=project,
        ).status_code == 201

    from_child = world.graph(tree.child, (REQ, tree.req["child"]), depth=3).json()
    assert str(tree.req["sibling"]) not in _graph_ids(from_child)
    assert from_child["hidden_count"] == 1  # counted, never named
    from_root = world.graph(tree.root, (REQ, tree.req["root"])).json()
    assert {str(tree.req["child"]), str(tree.req["sibling"])} <= _graph_ids(from_root)


def test_a_graph_can_be_rooted_at_a_record_in_an_ancestor_read_through_the_child_without_reaching_siblings(world, tree):
    """The trace tree opens a branch by re-rooting at a record, which may live in a parent project."""
    related = _scoped(world, "ancestor_either_way")
    for name, project in (("child", tree.child), ("sibling", tree.sibling)):
        assert world.generic_link(
            tree.root, (REQ, tree.req["root"]), related, (REQ, tree.req[name]), other_project=project,
        ).status_code == 201

    rooted_above = world.graph(tree.child, (REQ, tree.req["root"]), depth=1)
    assert rooted_above.status_code == 200, rooted_above.text
    graph = rooted_above.json()
    assert graph["root"]["id"] == str(tree.req["root"]) and graph["root"]["project_id"] == tree.root["id"]
    assert {e["to_id"] for e in graph["edges"]} == {str(tree.req["child"])}
    assert graph["hidden_count"] == 1  # the sibling's record: counted, never named
    assert str(tree.req["sibling"]) not in _graph_ids(graph)

    # A record outside the child's ancestry line is not a valid root, whatever its links.
    assert world.graph(tree.child, (REQ, tree.req["sibling"])).status_code == 404
    assert world.graph(tree.child, (REQ, tree.req["other"])).status_code == 404


def test_a_node_in_a_project_the_caller_cannot_open_is_hidden_and_not_traversed(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    child_only = _member(world, tree.child)
    graph = world.graph(tree.child, (REQ, tree.req["child"]), token=child_only).json()
    assert _graph_ids(graph) == {str(tree.req["child"])}
    assert graph["hidden_count"] == 1


def test_a_link_goes_dormant_on_reparent_and_returns_when_the_chain_is_restored(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201

    _set_parent(world, tree.child, tree.other)  # child leaves the root's tree
    dormant = world.graph(tree.child, (REQ, tree.req["child"])).json()
    assert str(tree.req["root"]) not in _graph_ids(dormant) and dormant["edges"] == []
    assert len(_links_of(tree.req["child"])) == 1  # kept

    _set_parent(world, tree.child, tree.root)
    restored = world.graph(tree.child, (REQ, tree.req["child"])).json()
    assert str(tree.req["root"]) in _graph_ids(restored)


def test_a_link_between_projects_that_stopped_being_related_is_dormant_from_a_common_ancestor(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.root, (REQ, tree.req["root"]), related, (REQ, tree.req["child"]), other_project=tree.child,
    ).status_code == 201
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["grandchild"]), other_project=tree.grandchild,
    ).status_code == 201
    assert str(tree.req["grandchild"]) in _graph_ids(world.graph(tree.root, (REQ, tree.req["root"]), depth=3).json())

    _set_parent(world, tree.grandchild, tree.sibling)  # now both are descendants of the root, but not of each other
    graph = world.graph(tree.root, (REQ, tree.req["root"]), depth=3).json()
    assert str(tree.req["child"]) in _graph_ids(graph)
    assert str(tree.req["grandchild"]) not in _graph_ids(graph)
    assert graph["unavailable_count"] == 1  # dormant, not hidden for lack of access


def test_narrowing_a_type_flags_existing_links_without_deleting_them(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    base = f"/api/v1/orgs/{world.org['id']}/link-types/{related}"
    impact = world.client.get(f"{base}/nesting-impact", params={"nesting_scope": "same_project"}, headers=auth_headers(world.token))
    assert impact.json() == {"flagged_link_count": 1}
    keeps = world.client.get(f"{base}/nesting-impact", params={"nesting_scope": "ancestor_either_way"}, headers=auth_headers(world.token))
    assert keeps.json() == {"flagged_link_count": 0}

    all_types = world.client.get(f"/api/v1/orgs/{world.org['id']}/link-types", headers=auth_headers(world.token)).json()
    current = next(t for t in all_types if t["id"] == str(related))
    patch = world.client.patch(
        base, json={"forward_name": current["forward_name"], "reverse_name": "r", "nesting_scope": "same_project"},
        headers=auth_headers(world.token),
    )
    assert patch.status_code == 200
    graph = world.graph(tree.child, (REQ, tree.req["child"])).json()
    assert graph["edges"][0]["nesting_permitted"] is False  # flagged, still shown
    assert len(_links_of(tree.req["child"])) == 1


# --- readers that assume one project never see a cross-level link --------------------------------


def test_legacy_readers_exclude_cross_level_links_by_default(world, tree):
    related = _scoped(world, "ancestor_either_way")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    db = SessionLocal()
    try:
        assert get_all_links(db, REQ, tree.req["child"]) == []
        assert get_links_from(db, REQ, tree.req["child"]) == []
        assert len(get_all_links(db, REQ, tree.req["child"], include_cross_project=True)) == 1
    finally:
        db.close()

    listed = world.client.get(
        f"/api/v1/projects/{tree.child['id']}/requirements/{tree.req['child']}/links", headers=auth_headers(world.token)
    )
    assert listed.status_code == 200 and listed.json() == []


def test_the_legacy_requirement_endpoint_cannot_delete_a_cross_level_link(world, tree):
    related = _scoped(world, "ancestor_either_way")
    created = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    )
    resp = world.client.delete(
        f"/api/v1/projects/{tree.child['id']}/requirements/{tree.req['child']}/links/{created.json()['id']}",
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 404
    assert len(_links_of(tree.req["child"])) == 1


def test_export_leaves_cross_level_links_out_and_reports_how_many(world, tree):
    related = _scoped(world, "ancestor_either_way")
    same = world.requirement(tree.child, "Neighbour")
    assert world.generic_link(tree.child, (REQ, tree.req["child"]), related, (REQ, same)).status_code == 201
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201

    resp = world.client.get(f"/api/v1/projects/{tree.child['id']}/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        project_json = json.loads(zf.read("project.json"))
    assert manifest["excluded_cross_project_links"] == 1
    assert len(project_json["requirement_links"]) == 1  # only the same-project link
    assert "Req root" not in json.dumps(project_json["requirement_links"])


def test_csv_export_never_names_another_projects_requirement(world, tree):
    related = _scoped(world, "ancestor_either_way")
    # Codes restart per project, so link to the root's second requirement: SW-PERF-002 exists only there.
    second_root = world.requirement(tree.root, "Second root req")
    root_code = _code_of(second_root)
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, second_root), other_project=tree.root,
    ).status_code == 201
    resp = world.client.get(f"/api/v1/projects/{tree.child['id']}/requirements/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    assert root_code not in resp.text


def _code_of(requirement_id: uuid.UUID) -> str:
    from app.models.requirement import Requirement

    db = SessionLocal()
    try:
        return db.get(Requirement, requirement_id).unique_code
    finally:
        db.close()


# --- deleting a cross-level link --------------------------------------------------------------


def test_a_cross_level_link_can_be_removed_from_either_end_and_is_audited_in_both_projects(world, tree):
    related = _scoped(world, "ancestor_either_way")
    created = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    )
    link_id = created.json()["id"]
    db = SessionLocal()
    try:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == link_id, AuditEvent.action == "created")
        ).all()
        assert {str(e.project_id) for e in events} == {tree.child["id"], tree.root["id"]}
        assert all(e.detail["cross_project"] is True for e in events)
    finally:
        db.close()

    # The parent's page can remove it, and the child-side page cannot see it afterwards.
    gone = world.client.delete(
        f"/api/v1/projects/{tree.root['id']}/artefacts/{REQ}/{tree.req['root']}/links/{link_id}",
        headers=auth_headers(world.token),
    )
    assert gone.status_code == 204, gone.text
    assert _links_of(tree.req["child"]) == []


def test_a_wrong_project_page_cannot_remove_a_cross_level_link(world, tree):
    related = _scoped(world, "ancestor_either_way")
    created = world.generic_link(
        tree.child, (REQ, tree.req["child"]), related, (REQ, tree.req["root"]), other_project=tree.root,
    )
    # The grandchild's page does not hold either end.
    resp = world.client.delete(
        f"/api/v1/projects/{tree.grandchild['id']}/artefacts/{REQ}/{tree.req['grandchild']}/links/{created.json()['id']}",
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 404


# --- link-type usage counts cross-level links and their authority --------------------------------


def test_link_type_usage_counts_cross_level_links_and_both_projects(world, tree):
    local = _local_type(world, tree.root, "Counted")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), local["id"], (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    usage = world.client.get(
        f"/api/v1/projects/{tree.root['id']}/link-types/{local['id']}/usage", headers=auth_headers(world.token)
    ).json()
    assert usage["link_count"] == 1
    assert usage["project_count"] == 2  # the link touches the root and the child


def test_a_project_admin_cannot_remove_links_that_reach_a_project_they_do_not_manage(world, tree):
    local = _local_type(world, tree.root, "Authority")
    assert world.generic_link(
        tree.child, (REQ, tree.req["child"]), local["id"], (REQ, tree.req["root"]), other_project=tree.root,
    ).status_code == 201
    root_manager = _member(world, tree.root, "project_manager")
    resp = world.client.delete(
        f"/api/v1/projects/{tree.root['id']}/link-types/{local['id']}", params={"mode": "remove_links"},
        headers=auth_headers(root_manager),
    )
    assert resp.status_code == 409
    assert "cannot manage" in resp.text
    assert len(_links_of(tree.req["child"])) == 1


# --- seeds ------------------------------------------------------------------------------------


def test_decision_seeds_use_the_directional_scope(client, admin_token):
    world = World(client, admin_token, "Seed Nesting Org", decisions=True)
    types = world.link_types_by_name()
    for name in ("Addresses", "Resolves", "Supports", "Guided by", "Constrained by"):
        assert types[name]["nesting_scope"] == "upstream_in_ancestor", name
        assert types[name]["flow"] == "forward_is_upstream"
    assert types["Related to"]["nesting_scope"] == "ancestor_either_way"


def test_decision_in_the_parent_cannot_address_a_pain_point_below_it_but_the_reverse_works(client, admin_token):
    world = World(client, admin_token, "Pain Point Nesting Org", decisions=True, context_strategy=True)
    parent = world.project("Product")
    child = world.project("Hardware", parent=parent)
    types = world.link_types_by_name()
    pain_point_child = world.pain_point(child, "Connector wear")
    pain_point_parent = world.pain_point(parent, "Product wear")
    decision_parent = world.decision(parent, "DEC-P")
    decision_child = world.decision(child, "DEC-C")
    addresses = types["Addresses"]["id"]

    # Pain point (upstream) in the parent, decision in the child: allowed.
    ok = world.generic_link(
        child, ("decision", decision_child), addresses, ("pain_point", pain_point_parent), other_project=parent,
    )
    assert ok.status_code == 201, ok.text
    # Decision in the parent addressing a pain point in the child: the upstream end sits below.
    refused = world.generic_link(
        parent, ("decision", decision_parent), addresses, ("pain_point", pain_point_child), other_project=child,
    )
    assert refused.status_code == 400
    assert "upstream end" in refused.json()["detail"]


# --- the reader audit, kept as a guard -----------------------------------------------------------

# Files reviewed for how they treat cross-level links (docs/decisions.md): each either asks
# for them deliberately (the graph, usage counts, deletion, the export count) or filters them out.
# A new file that queries `ArtefactLink` directly, or asks `services.relationships` for cross-level
# links, must be reviewed against the "another project's artefact" rule and added here.
_REVIEWED_LINK_READERS = {
    "services/bundle_links.py": "same-project links only (source_project_id is null); a cross-level link is not exported",
    "services/link_graph.py": "authorises every end in its own project",
    "services/link_nesting.py": "counts links a type's scope would flag",
    "modules/compliance/export.py": "same-project requirement -> clause links only (source_project_id is null)",
    "modules/stakeholders/engagements.py": (
        "same-project participant/covers/outcome links only (source_project_id is null); erasure deliberately removes "
        "every link, cross-level included"
    ),
    "modules/stakeholders/groups.py": "deleting a group removes every link, cross-level included",
    "modules/stakeholders/reports.py": "same-project links only (source_project_id is null)",
    "modules/stakeholders/service.py": "erasing a stakeholder removes every link, cross-level included",
    "modules/stakeholders/_research_shared.py": "deleting a finding removes every link, cross-level included",
    "modules/risk_management/treatment.py": (
        "deliberately includes cross-level treatment links; dormant ones are skipped (is_link_live) and the far end "
        "is shown only if ArtefactResolver says the caller can see it, else counted as hidden"
    ),
    "services/link_type_usage.py": "counts and moves links of a type; authority covers both ends",
    "services/org_deletion.py": "removes every link of a deleted organisation",
    "services/project_export.py": "same-project links only; counts the rest for the manifest",
    "services/relationships.py": "default-deny: excludes cross-level links unless asked",
    "services/requirement_csv.py": "same-project links only",
}


def test_only_reviewed_modules_query_artefact_links_directly():
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    pattern = re.compile(
        r"select\(\s*ArtefactLink|ArtefactLink\.__table__|get_links_touching_many\(|include_cross_project=True"
        r"|db\.(?:query|scalars|execute)\([^)]*ArtefactLink"
    )
    found = {
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if "tests" not in path.parts and pattern.search(path.read_text())
    }
    assert found <= set(_REVIEWED_LINK_READERS), (
        f"New direct readers of artefact links: {sorted(found - set(_REVIEWED_LINK_READERS))}. "
        "Review them against cross-level links (use services.relationships, which excludes them by default) "
        "and add them to _REVIEWED_LINK_READERS."
    )


def test_the_demo_scenario_a_child_decision_addresses_a_parents_pain_point_and_a_parent_decision_implements_a_child_requirement(
    client, admin_token
):
    """Mirrors `scripts/seed_demo_data.py`: the decision is created through the API in the child with the
    parent's decision type (types fall back to the nearest ancestor), then linked across the nesting."""
    world = World(client, admin_token, "Demo Scenario Org", decisions=True, context_strategy=True)
    parent = world.project("Falcon")
    child = world.project("Avionics", parent=parent)
    types = world.link_types_by_name()
    parent_types = client.get(
        f"/api/v1/projects/{parent['id']}/modules/decisions/decision-types", headers=auth_headers(world.token)
    ).json()
    created = client.post(
        f"/api/v1/projects/{child['id']}/modules/decisions",
        json={
            "title": "Fuse sensors", "decision_statement": "Two estimators.", "decision_type_id": parent_types[0]["id"],
            "owner_id": str(world.user_id), "context": "",
        },
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    child_decision = uuid.UUID(created.json()["id"])
    pain_point = world.pain_point(parent, "Parent pain")
    parent_decision = world.decision(parent, "DEC-P")
    child_req = world.requirement(child, "Child req")

    addresses = world.generic_link(
        child, ("decision", child_decision), types["Addresses"]["id"], ("pain_point", pain_point), other_project=parent,
    )
    implements = world.generic_link(
        parent, ("decision", parent_decision), types["Implements"]["id"], (REQ, child_req), other_project=child,
    )
    assert addresses.status_code == 201, addresses.text
    assert implements.status_code == 201, implements.text
