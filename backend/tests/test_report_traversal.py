"""Tests for how a custom report layout reaches records (`services.report_traversal`).

Covers root selection, link traversal in each direction and through chosen link types, the rule that
a record the caller cannot see is counted and never named or traversed through (the link graph's
resolver is the one authorisation point), the caps, and a bounded query count. Each test builds its
own organisation, so none depends on state left by another.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.project import Project
from app.models.requirement import Requirement
from app.services import link_graph, report_traversal
from app.services.link_graph import ArtefactResolver
from app.services.report_fields import UnknownReportFieldError, load_records
from app.services.report_traversal import LinkDirection, linked_records, root_records
from tests.link_world import REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Traversal Org", decisions=True, context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _resolver(db, world: World, project: dict) -> tuple[ArtefactResolver, Project]:
    row = db.get(Project, uuid.UUID(project["id"]))
    return ArtefactResolver(db, row, world.user_id, include_related=True), row


def _ids(summaries) -> list[uuid.UUID]:
    return [s.id for s in summaries]


# --- roots ------------------------------------------------------------------------------------


def test_roots_are_the_projects_visible_records_in_code_order(world, db):
    project = world.project("Roots P")
    other = world.project("Roots Other")
    first, second = world.requirement(project, "First"), world.requirement(project, "Second")
    world.requirement(other, "Elsewhere")
    resolver, row = _resolver(db, world, project)

    roots = root_records(db, resolver, row, REQ, [row.id])

    assert _ids(roots.summaries) == [first, second]
    assert roots.hidden == 0 and roots.unavailable == 0 and not roots.truncated


def test_archived_roots_need_the_flag(world, db):
    project = world.project("Archive P")
    live, archived = world.requirement(project, "Live"), world.requirement(project, "Old")
    db.query(Requirement).filter(Requirement.id == archived).update({"is_archived": True})
    db.commit()
    resolver, row = _resolver(db, world, project)

    assert _ids(root_records(db, resolver, row, REQ, [row.id]).summaries) == [live]
    assert set(_ids(root_records(db, resolver, row, REQ, [row.id], include_archived=True).summaries)) == {live, archived}


def test_roots_of_a_type_the_caller_cannot_view_are_counted_not_listed(world, db, monkeypatch):
    project = world.project("Denied P")
    world.pain_point(project, "A")
    world.pain_point(project, "B")
    real = link_graph.get_effective_permissions
    monkeypatch.setattr(
        link_graph, "get_effective_permissions",
        lambda *args, **kwargs: {p for p in real(*args, **kwargs) if not p.startswith("pain_point:view")},
    )
    resolver, row = _resolver(db, world, project)

    roots = root_records(db, resolver, row, PAIN, [row.id])

    assert roots.summaries == [] and roots.hidden == 2


def test_roots_of_a_disabled_module_are_not_listed(client, admin_token, db):
    plain = World(client, admin_token, "No Decisions Roots")  # decisions off
    project = plain.project()
    plain.decision(project)
    resolver, row = _resolver(db, plain, project)

    roots = root_records(db, resolver, row, "decision", [row.id])

    assert roots.summaries == [] and roots.hidden == 1


def test_the_root_cap_truncates_instead_of_failing(world, db, monkeypatch):
    project = world.project("Cap P")
    for i in range(3):
        world.requirement(project, f"R{i}")
    monkeypatch.setattr(report_traversal, "MAX_ROOTS", 2)
    resolver, row = _resolver(db, world, project)

    roots = root_records(db, resolver, row, REQ, [row.id])

    assert len(roots.summaries) == 2 and roots.truncated


def test_an_unreportable_type_is_refused(world, db):
    project = world.project("Refuse P")
    resolver, row = _resolver(db, world, project)
    with pytest.raises(UnknownReportFieldError):
        root_records(db, resolver, row, "no_such_type", [row.id])
    with pytest.raises(UnknownReportFieldError):
        linked_records(db, resolver, [(REQ, uuid.uuid4())], "no_such_type")


# --- linked records ---------------------------------------------------------------------------


def test_linked_records_are_grouped_per_parent_in_both_directions(world, db):
    project = world.project("Linked P")
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    p1, p2, p3 = (world.pain_point(project, t) for t in ("One", "Two", "Three"))
    world.link((REQ, a), (PAIN, p1))   # requirement -> pain point
    world.link((PAIN, p2), (REQ, a))   # pain point -> requirement
    world.link((REQ, b), (PAIN, p3))
    resolver, _row = _resolver(db, world, project)
    parents = [(REQ, a), (REQ, b)]

    both = linked_records(db, resolver, parents, PAIN)
    out = linked_records(db, resolver, parents, PAIN, direction=LinkDirection.OUTGOING)
    incoming = linked_records(db, resolver, parents, PAIN, direction=LinkDirection.INCOMING)

    assert set(_ids(both.by_parent[(REQ, a)])) == {p1, p2} and _ids(both.by_parent[(REQ, b)]) == [p3]
    assert _ids(out.by_parent[(REQ, a)]) == [p1] and _ids(incoming.by_parent[(REQ, a)]) == [p2]
    assert both.hidden == {} and both.unavailable == {} and not both.truncated


def test_every_parent_is_a_key_even_with_nothing_linked(world, db):
    project = world.project("Empty P")
    a = world.requirement(project, "A")
    resolver, _row = _resolver(db, world, project)
    assert linked_records(db, resolver, [(REQ, a)], PAIN).by_parent == {(REQ, a): []}
    assert linked_records(db, resolver, [], PAIN).by_parent == {}


def test_only_the_wanted_type_and_link_types_are_followed(world, db):
    project = world.project("Filter P")
    a, other = world.requirement(project, "A"), world.requirement(project, "B")
    p_kept, p_dropped = world.pain_point(project, "Kept"), world.pain_point(project, "Dropped")
    kept_type, dropped_type = world.link_type("Raises", "Raised by"), world.link_type("Mentions", "Mentioned by")
    world.link((REQ, a), (PAIN, p_kept), kept_type)
    world.link((REQ, a), (PAIN, p_dropped), dropped_type)
    world.link((REQ, a), (REQ, other), kept_type)
    resolver, _row = _resolver(db, world, project)

    result = linked_records(db, resolver, [(REQ, a)], PAIN, link_type_ids={kept_type})

    assert _ids(result.by_parent[(REQ, a)]) == [p_kept]
    assert _ids(linked_records(db, resolver, [(REQ, a)], PAIN).by_parent[(REQ, a)]) == [p_kept, p_dropped]


def test_the_same_neighbour_through_two_links_appears_once(world, db):
    project = world.project("Dedupe P")
    a, p = world.requirement(project, "A"), world.pain_point(project, "P")
    world.link((REQ, a), (PAIN, p), world.link_type("First", "First back"))
    world.link((PAIN, p), (REQ, a), world.link_type("Second", "Second back"))
    resolver, _row = _resolver(db, world, project)

    assert _ids(linked_records(db, resolver, [(REQ, a)], PAIN).by_parent[(REQ, a)]) == [p]


def test_a_record_in_another_project_is_counted_and_never_named(world, db):
    project, other = world.project("Mine"), world.project("Theirs")
    a = world.requirement(project, "A")
    seen, foreign = world.pain_point(project, "Seen"), world.pain_point(other, "Secret")
    world.link((REQ, a), (PAIN, seen))
    world.link((REQ, a), (PAIN, foreign))
    resolver, _row = _resolver(db, world, project)

    result = linked_records(db, resolver, [(REQ, a)], PAIN)

    assert _ids(result.by_parent[(REQ, a)]) == [seen]
    assert result.hidden == {(REQ, a): 1}


def test_a_hidden_record_is_not_traversed_through(world, db, monkeypatch):
    project = world.project("Chain P")
    a, beyond = world.requirement(project, "A"), world.requirement(project, "Beyond")
    hidden_pain = world.pain_point(project, "Hidden")
    world.link((REQ, a), (PAIN, hidden_pain))
    world.link((PAIN, hidden_pain), (REQ, beyond))
    real = link_graph.get_effective_permissions
    monkeypatch.setattr(
        link_graph, "get_effective_permissions",
        lambda *args, **kwargs: {p for p in real(*args, **kwargs) if not p.startswith("pain_point:view")},
    )
    resolver, _row = _resolver(db, world, project)

    first = linked_records(db, resolver, [(REQ, a)], PAIN)
    # The hidden record is not a parent of anything: only visible records are handed on to the next step.
    second = linked_records(db, resolver, [], REQ)

    assert first.by_parent[(REQ, a)] == [] and first.hidden == {(REQ, a): 1}
    assert second.by_parent == {}


def test_a_type_no_module_can_display_is_unavailable_not_hidden(world, db, monkeypatch):
    project = world.project("Unavailable P")
    a = world.requirement(project, "A")
    world.link((REQ, a), (PAIN, uuid.uuid4()))
    monkeypatch.setattr(link_graph, "get_artefact_summaries_in_project", lambda *args, **kwargs: None)
    resolver, _row = _resolver(db, world, project)

    result = linked_records(db, resolver, [(REQ, a)], PAIN)

    assert result.unavailable == {(REQ, a): 1} and result.hidden == {}


def test_a_dormant_cross_project_link_is_unavailable(world, db):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    a, p = world.requirement(parent, "A"), world.pain_point(child, "P")
    world.link((REQ, a), (PAIN, p), source_project_id=uuid.UUID(parent["id"]), target_project_id=uuid.UUID(child["id"]))
    resolver, row = _resolver(db, world, parent)
    assert _ids(linked_records(db, resolver, [(REQ, a)], PAIN).by_parent[(REQ, a)]) == [p]

    # Detach the child: the two projects are no longer in one ancestry line, so the link is dormant.
    db.query(Project).filter(Project.id == uuid.UUID(child["id"])).update({"parent_project_id": None})
    db.commit()
    fresh, _row = _resolver(db, world, parent)
    result = linked_records(db, fresh, [(REQ, a)], PAIN)

    assert result.by_parent[(REQ, a)] == [] and result.unavailable == {(REQ, a): 1}


def test_the_linked_cap_truncates_instead_of_failing(world, db, monkeypatch):
    project = world.project("Linked Cap P")
    a = world.requirement(project, "A")
    for i in range(3):
        world.link((REQ, a), (PAIN, world.pain_point(project, f"P{i}")))
    monkeypatch.setattr(report_traversal, "MAX_LINKED", 2)
    resolver, _row = _resolver(db, world, project)

    result = linked_records(db, resolver, [(REQ, a)], PAIN)

    assert len(result.by_parent[(REQ, a)]) == 2 and result.truncated


def test_the_number_of_queries_does_not_grow_with_the_number_of_parents(world, db):
    project = world.project("Count P")
    requirements = []
    for i in range(6):
        req = world.requirement(project, f"R{i}")
        world.link((REQ, req), (PAIN, world.pain_point(project, f"P{i}")))
        requirements.append((REQ, req))

    def statements(parents) -> int:
        seen: list[str] = []

        def record(conn, cursor, statement, *args):
            seen.append(statement)

        resolver, _row = _resolver(db, world, project)
        event.listen(engine, "before_cursor_execute", record)
        try:
            linked_records(db, resolver, parents, PAIN)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    assert statements(requirements) == statements(requirements[:2])


# --- the layout example, end to end -----------------------------------------------------------


def test_requirements_by_component_with_their_linked_pain_points(world, db):
    """The shape the custom layout phase builds on: roots, their fields, then the linked records' fields."""
    project = world.project("Example P")
    a, b = world.requirement(project, "Checkout is slow"), world.requirement(project, "Search is wrong")
    p1, p2 = world.pain_point(project, "Late reports"), world.pain_point(project, "Lost orders")
    world.link((REQ, a), (PAIN, p1))
    world.link((REQ, a), (PAIN, p2))
    resolver, row = _resolver(db, world, project)

    roots = root_records(db, resolver, row, REQ, [row.id])
    requirements = load_records(db, REQ, _ids(roots.summaries), ["component", "category"])
    linked = linked_records(db, resolver, [(REQ, r.id) for r in roots.summaries], PAIN)
    pains = load_records(db, PAIN, {s.id for found in linked.by_parent.values() for s in found}, ["priority"])

    assert [requirements[i].title for i in _ids(roots.summaries)] == ["Checkout is slow", "Search is wrong"]
    assert requirements[a].values["component"] and requirements[a].values["category"]
    assert [pains[s.id].title for s in linked.by_parent[(REQ, a)]] == ["Late reports", "Lost orders"]
    assert linked.by_parent[(REQ, b)] == []
