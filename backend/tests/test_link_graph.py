"""Tests for the artefact link graph (docs/plans/platform-enhancements-2026-10-plan.md
Phase 5): link-type `flow`, `services.link_graph` and
`GET /projects/{id}/artefacts/{type}/{id}/link-graph`.

Covers flow resolution for each `flow` value from both ends of a link, untyped
and symmetric links, cross-project / cross-org / disabled-module / permission
isolation (a hidden record is counted, never shown and never traversed
through), depth, the node cap, cycles and self-links, archived nodes, a bounded
query count, and the registry extension points the graph relies on. Each test
builds its own organisation, so none depends on state left by another.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.enums import ArtefactType
from app.models.requirement import Requirement
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.registry import (
    get_all_registered_artefact_types,
    get_artefact_summaries_in_project,
    get_artefact_type_label,
    get_module_registry,
)
from app.services import link_graph, relationships
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

REQ = ArtefactType.REQUIREMENT.value
ACTION = ArtefactType.REQUIREMENT_ACTION.value


class World:
    """One organisation with an admin and helpers to build artefacts and links in it."""

    def __init__(self, client, admin_token, name: str, *, decisions: bool = False) -> None:
        self.client = client
        self.org, self.token = create_org_admin_in(client, admin_token, f"{name} {uuid.uuid4().hex[:6]}")
        if decisions:
            resp = client.put(
                f"/api/v1/orgs/{self.org['id']}/modules/decisions", json={"enabled": True},
                headers=auth_headers(self.token),
            )
            assert resp.status_code == 200, resp.text
        self.user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(self.token)).json()["id"])

    def project(self, name: str = "P") -> dict:
        project = create_project(self.client, self.token, self.org["id"], name)
        project["component_id"], project["category_id"] = create_component_and_category(
            self.client, self.token, project["id"]
        )
        return project

    def requirement(self, project: dict, name: str = "Req") -> uuid.UUID:
        resp = self.client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": project["component_id"], "category_id": project["category_id"]},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def action(self, project: dict, title: str = "Act") -> uuid.UUID:
        types = self.client.get(f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(self.token)).json()
        resp = self.client.post(
            f"/api/v1/projects/{project['id']}/actions", json={"title": title, "action_type_id": types[0]["id"]},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def decision(self, project: dict, code: str = "DEC-1") -> uuid.UUID:
        db = SessionLocal()
        try:
            type_id = db.query(DecisionTypeDefinition.id).filter(
                DecisionTypeDefinition.project_id == project["id"]
            ).first()[0]
            decision = Decision(
                project_id=project["id"], unique_code=code, title=f"Decision {code}", decision_statement="S",
                decision_type_id=type_id, owner_id=self.user_id, creator_id=self.user_id,
            )
            db.add(decision)
            db.commit()
            return decision.id
        finally:
            db.close()

    def link_type(self, forward: str, reverse: str, flow: str = "none") -> uuid.UUID:
        resp = self.client.post(
            f"/api/v1/orgs/{self.org['id']}/link-types",
            json={"forward_name": f"{forward} {uuid.uuid4().hex[:4]}", "reverse_name": reverse, "flow": flow},
            headers=auth_headers(self.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def link(self, source: tuple[str, uuid.UUID], target: tuple[str, uuid.UUID], link_type_id=None) -> uuid.UUID:
        db = SessionLocal()
        try:
            row = relationships.create_link(
                db, source_type=source[0], source_id=source[1], target_type=target[0], target_id=target[1],
                link_type_id=link_type_id, created_by=self.user_id,
            )
            db.commit()
            return row.id
        finally:
            db.close()

    def graph(self, project: dict, artefact: tuple[str, uuid.UUID], token=None, **params):
        return self.client.get(
            f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-graph", params=params,
            headers=auth_headers(token or self.token),
        )


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Graph Org")


def _ids(graph: dict) -> set[str]:
    return {n["id"] for n in graph["nodes"]}


# --- link-type flow ---------------------------------------------------------------------


def test_link_type_flow_defaults_to_none_and_can_be_set_and_kept(client, world):
    created = client.post(
        f"/api/v1/orgs/{world.org['id']}/link-types", json={"forward_name": "Plain", "reverse_name": "Plain rev"},
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201 and created.json()["flow"] == "none"
    url = f"/api/v1/orgs/{world.org['id']}/link-types/{created.json()['id']}"

    renamed = client.patch(
        url, json={"forward_name": "Plain2", "reverse_name": "Plain rev", "flow": "forward_is_upstream"},
        headers=auth_headers(world.token),
    )
    assert renamed.status_code == 200 and renamed.json()["flow"] == "forward_is_upstream"

    kept = client.patch(url, json={"forward_name": "Plain3", "reverse_name": "x"}, headers=auth_headers(world.token))
    assert kept.json()["flow"] == "forward_is_upstream"

    bad = client.patch(url, json={"forward_name": "P", "reverse_name": "x", "flow": "sideways"}, headers=auth_headers(world.token))
    assert bad.status_code == 422


def test_seeded_link_types_carry_flow_and_ambiguous_ones_stay_none(client, world):
    listed = {
        t["forward_name"]: t["flow"]
        for t in client.get(f"/api/v1/orgs/{world.org['id']}/link-types", headers=auth_headers(world.token)).json()
    }
    assert listed["Derives from"] == "forward_is_upstream"
    assert listed["Verified by"] == "forward_is_downstream"
    assert listed["Related to"] == "none"
    assert listed["Mitigates"] == "none"


# --- flow resolution --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flow", "from_source", "from_target"),
    [
        ("forward_is_upstream", "upstream", "downstream"),
        ("forward_is_downstream", "downstream", "upstream"),
        ("none", "related", "related"),
    ],
)
def test_edge_flow_is_resolved_from_either_end_of_the_link(world, flow, from_source, from_target):
    project = world.project()
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    world.link((REQ, a), (REQ, b), world.link_type("Derives", "Source of", flow))

    from_a = world.graph(project, (REQ, a)).json()
    from_b = world.graph(project, (REQ, b)).json()

    assert [e["flow"] for e in from_a["edges"]] == [from_source]
    assert from_a["edges"][0]["outgoing"] is True
    assert from_a["edges"][0]["phrase"].startswith("Derives")
    assert [e["flow"] for e in from_b["edges"]] == [from_target]
    assert from_b["edges"][0]["outgoing"] is False
    assert from_b["edges"][0]["phrase"] == "Source of"


def test_untyped_link_is_related_with_no_phrase(world):
    project = world.project()
    requirement, action = world.requirement(project), world.action(project)
    world.link((ACTION, action), (REQ, requirement))

    graph = world.graph(project, (REQ, requirement)).json()

    assert [(e["flow"], e["phrase"], e["link_type_id"]) for e in graph["edges"]] == [("related", None, None)]
    assert {n["type"] for n in graph["nodes"]} == {REQ, ACTION}
    assert {n["type_label"] for n in graph["nodes"]} == {"Requirement", "Action"}


def test_unconfigured_type_is_related_not_hidden(world):
    project = world.project()
    a, b = world.requirement(project), world.requirement(project)
    world.link((REQ, a), (REQ, b), world.link_type("Plain", "Plain rev"))

    graph = world.graph(project, (REQ, a)).json()

    assert _ids(graph) == {str(a), str(b)}
    assert graph["edges"][0]["flow"] == "related" and graph["hidden_count"] == 0


def test_node_fields_carry_label_status_and_archived_flag(client, world):
    project = world.project()
    a, b = world.requirement(project, "Alpha"), world.requirement(project, "Beta")
    world.link((REQ, a), (REQ, b))
    db = SessionLocal()
    try:
        row = db.get(Requirement, b)
        row.is_archived = True
        db.commit()
        code = db.get(Requirement, a).unique_code
    finally:
        db.close()

    graph = world.graph(project, (REQ, a)).json()
    nodes = {n["id"]: n for n in graph["nodes"]}

    assert graph["root"]["id"] == str(a) and graph["root"]["depth"] == 0
    assert nodes[str(a)]["label"] == f"{code} Alpha"
    assert nodes[str(a)]["status"] == "draft" and nodes[str(a)]["is_archived"] is False
    assert nodes[str(b)]["is_archived"] is True and nodes[str(b)]["depth"] == 1


# --- traversal --------------------------------------------------------------------------


def test_depth_limits_hops_and_direction_limits_orientation(world):
    project = world.project()
    a, b, c, d = (world.requirement(project, n) for n in "ABCD")
    world.link((REQ, a), (REQ, b))
    world.link((REQ, b), (REQ, c))
    world.link((REQ, c), (REQ, d))

    assert _ids(world.graph(project, (REQ, a), depth=1).json()) == {str(a), str(b)}
    assert _ids(world.graph(project, (REQ, a), depth=2).json()) == {str(a), str(b), str(c)}
    assert _ids(world.graph(project, (REQ, a), depth=3).json()) == {str(a), str(b), str(c), str(d)}
    assert _ids(world.graph(project, (REQ, b), depth=1, direction="outgoing").json()) == {str(b), str(c)}
    assert _ids(world.graph(project, (REQ, b), depth=1, direction="incoming").json()) == {str(b), str(a)}


def test_cycles_and_self_links_terminate_with_each_link_once(world):
    project = world.project()
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    world.link((REQ, a), (REQ, b), world.link_type("Fwd", "Rev", "forward_is_upstream"))
    world.link((REQ, b), (REQ, a), world.link_type("Back", "Rev2"))
    world.link((REQ, a), (REQ, a), world.link_type("Self", "Self rev"))

    graph = world.graph(project, (REQ, a), depth=3).json()

    assert _ids(graph) == {str(a), str(b)}
    assert len(graph["edges"]) == 3 and len({e["id"] for e in graph["edges"]}) == 3
    assert graph["truncated"] is False


def test_node_cap_truncates_and_reports_it(monkeypatch, world):
    monkeypatch.setattr(link_graph, "MAX_NODES", 3)
    project = world.project()
    hub = world.requirement(project, "Hub")
    for i in range(5):
        world.link((REQ, hub), (REQ, world.requirement(project, f"Leaf{i}")))

    graph = world.graph(project, (REQ, hub)).json()

    assert len(graph["nodes"]) == 3 and graph["truncated"] is True
    included = _ids(graph)
    assert all(e["from_id"] in included and e["to_id"] in included for e in graph["edges"])


def test_link_queries_are_bounded_per_level(world):
    project = world.project()
    hub = world.requirement(project, "Hub")
    leaves = [world.requirement(project, f"L{i}") for i in range(6)]
    for leaf in leaves:
        world.link((REQ, hub), (REQ, leaf))
    for leaf in leaves:
        world.link((REQ, leaf), (REQ, world.requirement(project, "Far")))
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_rest):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert world.graph(project, (REQ, hub), depth=2).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert sum("FROM artefact_links" in s for s in statements) <= 2


# --- isolation --------------------------------------------------------------------------


def test_other_project_record_is_hidden_and_not_traversed(world):
    first, second = world.project("First"), world.project("Second")
    a, foreign, beyond = world.requirement(first, "A"), world.requirement(second, "Foreign"), world.requirement(first, "Beyond")
    world.link((REQ, a), (REQ, foreign))
    world.link((REQ, foreign), (REQ, beyond))

    graph = world.graph(first, (REQ, a), depth=3).json()

    assert _ids(graph) == {str(a)}
    assert graph["hidden_count"] == 1 and graph["edges"] == []
    # The foreign record is not a valid root in this project either.
    assert world.graph(first, (REQ, foreign)).status_code == 404


def test_other_organisation_record_is_hidden(client, admin_token, world):
    project = world.project()
    other = World(client, admin_token, "Other Graph Org")
    other_project = other.project()
    mine, theirs = world.requirement(project), other.requirement(other_project)
    world.link((REQ, mine), (REQ, theirs))

    graph = world.graph(project, (REQ, mine)).json()

    assert _ids(graph) == {str(mine)} and graph["hidden_count"] == 1
    assert other.graph(other_project, (REQ, theirs), token=other.token).json()["hidden_count"] == 1


def test_disabled_module_record_is_hidden_and_not_traversed(client, admin_token):
    world = World(client, admin_token, "No Decisions Org")  # decisions module off by default
    project = world.project()
    a, beyond = world.requirement(project, "A"), world.requirement(project, "Beyond")
    decision = world.decision(project)
    world.link((REQ, a), ("decision", decision))
    world.link(("decision", decision), (REQ, beyond))

    graph = world.graph(project, (REQ, a), depth=3).json()

    assert _ids(graph) == {str(a)} and graph["hidden_count"] == 1
    assert world.graph(project, ("decision", decision)).status_code == 404


def test_enabled_module_record_is_shown_with_its_label_and_status(client, admin_token):
    world = World(client, admin_token, "Decisions Org", decisions=True)
    project = world.project()
    a = world.requirement(project, "A")
    decision = world.decision(project, "DEC-7")
    world.link((REQ, a), ("decision", decision))

    graph = world.graph(project, (REQ, a)).json()

    node = next(n for n in graph["nodes"] if n["type"] == "decision")
    assert node["label"] == "DEC-7 Decision DEC-7" and node["type_label"] == "Decision"
    assert node["status"] and graph["hidden_count"] == 0
    assert world.graph(project, ("decision", decision)).json()["root"]["label"] == node["label"]


def test_record_without_view_permission_is_hidden_and_not_traversed(monkeypatch, client, admin_token):
    world = World(client, admin_token, "Denied Org", decisions=True)
    project = world.project()
    a, beyond = world.requirement(project, "A"), world.requirement(project, "Beyond")
    decision = world.decision(project)
    world.link((REQ, a), ("decision", decision))
    world.link(("decision", decision), (REQ, beyond))
    real = link_graph.get_effective_permissions
    monkeypatch.setattr(
        link_graph, "get_effective_permissions",
        lambda *args, **kwargs: {p for p in real(*args, **kwargs) if not p.startswith("decision:view")},
    )

    graph = world.graph(project, (REQ, a), depth=3).json()

    assert _ids(graph) == {str(a)} and graph["hidden_count"] == 1
    assert world.graph(project, ("decision", decision)).status_code == 404


def test_type_no_module_can_display_counts_as_unavailable_not_hidden(monkeypatch, world):
    project = world.project()
    a = world.requirement(project)
    world.link((REQ, a), ("decision", uuid.uuid4()))
    monkeypatch.setattr(link_graph, "get_artefact_summaries_in_project", lambda *args, **kwargs: None)

    graph = world.graph(project, (REQ, a)).json()

    assert graph["unavailable_count"] == 1 and graph["hidden_count"] == 0


# --- endpoint ---------------------------------------------------------------------------


def test_endpoint_rejects_unknown_type_unknown_id_non_member_and_bad_params(client, admin_token, world):
    project = world.project()
    a = world.requirement(project)

    assert world.graph(project, ("nonsense", a)).status_code == 404
    assert world.graph(project, (REQ, uuid.uuid4())).status_code == 404
    assert world.graph(project, (REQ, a), depth=4).status_code == 422
    assert world.graph(project, (REQ, a), direction="sideways").status_code == 422
    outsider = World(client, admin_token, "Outsider Org")
    assert world.graph(project, (REQ, a), token=outsider.token).status_code == 403
    assert client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{a}/link-graph"
    ).status_code == 401


def test_graph_of_unlinked_artefact_is_just_the_root(world):
    project = world.project()
    a = world.requirement(project)

    graph = world.graph(project, (REQ, a)).json()

    assert _ids(graph) == {str(a)} and graph["edges"] == [] and graph["hidden_count"] == 0


# --- registry extension points ------------------------------------------------------------


def test_every_registered_artefact_type_has_a_provider_and_label():
    providers = {
        t for definition in get_module_registry().values() for t in definition.artefact_summary_providers
    }
    for artefact_type in get_all_registered_artefact_types() - {REQ, ACTION}:
        assert artefact_type in providers, f"{artefact_type} cannot be shown in the link graph"
        label = get_artefact_type_label(artefact_type)
        assert label and "_" not in label


def test_type_label_falls_back_to_title_cased_type():
    assert get_artefact_type_label("requirement") == "Requirement"
    assert get_artefact_type_label("some_new_kind") == "Some new kind"


def test_summaries_in_project_distinguishes_unprovided_from_none_visible(client, admin_token):
    world = World(client, admin_token, "Summaries Org", decisions=True)
    project = world.project()
    other = world.project("Other")
    mine, theirs = world.decision(project, "DEC-1"), world.decision(other, "DEC-2")
    db = SessionLocal()
    try:
        got = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), "decision", [mine, theirs, uuid.uuid4()])
        assert set(got) == {mine}
        assert get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), "decision", []) == {}
        assert get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), "no_such_type", [mine]) is None
    finally:
        db.close()
