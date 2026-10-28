"""Tests for evaluating a layout tree (`services.report_layout_eval`).

Covers the worked example (requirements by component and category, their linked Pain Points, and
those Pain Points' Stakeholders), values never becoming markup, filtering, sorting and grouping,
conditions, the rule that a record the caller cannot see is counted and never named, link-type
names, the table family, the work/output/time caps, a bounded query count and the condition
comparisons at timezone boundaries. Each test builds its own organisation.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement import Requirement
from app.services import link_graph, report_layout_eval
from app.services.link_graph import ArtefactResolver
from app.services.report_framework import ReportContext
from app.services.report_layout_eval import (
    EMPTY_GROUP_LABEL,
    LayoutLimitError,
    LayoutTimeoutError,
    evaluate_layout,
    matches_value,
)
from app.services.report_layout_tree import BLOCK_SPECS, InvalidLayoutError
from app.services.report_model import Gap, Heading, Note, Paragraph, ReportDocument, Table
from tests.conftest import auth_headers
from tests.link_world import REQ, World

PAIN = "pain_point"
STAKEHOLDER = "stakeholder"


@pytest.fixture
def world(client, admin_token) -> World:
    w = World(client, admin_token, "Eval Org", context_strategy=True)
    w.enable("stakeholders")
    return w


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def doc(*nodes: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "family": "document", "nodes": list(nodes), **extra}


def run(db, world: World, project: dict, tree: dict[str, Any], **kwargs: Any):
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    resolver = ArtefactResolver(db, row, world.user_id, include_related=True)
    ctx = ReportContext(module_key="reporting", organization=org, projects=[row], root_project=row)
    kwargs.setdefault("title", "Report")
    return evaluate_layout(db, resolver, ctx, tree, **kwargs)


def lines(document: ReportDocument) -> list[str]:
    """The document as short comparable lines (spacing hints dropped, record codes masked)."""
    out = []
    for block in document.blocks:
        if isinstance(block, Gap):
            continue
        if isinstance(block, Heading):
            out.append(f"H{block.level} {block.text}")
        elif isinstance(block, Paragraph):
            out.append(f"P {block.text}")
        elif isinstance(block, Note):
            out.append(f"N {block.text}")
        elif isinstance(block, Table):
            out.append(f"T {'|'.join(block.columns)} :: {' / '.join('|'.join(r) for r in block.rows)}")
        else:
            out.append(type(block).__name__)
    return [re.sub(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3,}\b", "<code>", line) for line in out]


def each_title(**source: Any) -> dict[str, Any]:
    """A layout printing the title of every requirement its `source` options select."""
    return doc({"type": "each", "source": {"record_type": REQ, **source}, "children": [{"type": "text", "text": "{{record.title}}"}]})


def requirement(world: World, project: dict, name: str, component: str | None = None, category: str | None = None) -> uuid.UUID:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": name, "component_id": component or project["component_id"], "category_id": category or project["category_id"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def component_and_category(world: World, project: dict, component: str, category: str) -> tuple[str, str]:
    headers = auth_headers(world.token)
    comp = world.client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": component, "prefix": component[:3].upper()}, headers=headers,
    ).json()
    cat = world.client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": category, "prefix": category[:4].upper(), "component_id": comp["id"]}, headers=headers,
    ).json()
    return comp["id"], cat["id"]


def stakeholder(world: World, project: dict, name: str, role: str = "") -> uuid.UUID:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/modules/stakeholders/stakeholders", json={"name": name, "role": role},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def deny(monkeypatch, *prefixes: str) -> None:
    """Removes every permission starting with one of `prefixes` from what the link graph's resolver sees."""
    real = link_graph.get_effective_permissions
    monkeypatch.setattr(
        link_graph, "get_effective_permissions",
        lambda *a, **k: {p for p in real(*a, **k) if not p.startswith(prefixes)},
    )


EXAMPLE = doc(
    {"type": "heading", "text": "{{report_title}} for {{project_name}}"},
    {
        "type": "group", "source": {"record_type": REQ}, "by": "component", "as": "comp",
        "children": [
            {"type": "heading", "text": "{{comp.value}} ({{comp.count}})"},
            {
                "type": "group", "source": {"group": "comp"}, "by": "category", "as": "cat",
                "children": [
                    {"type": "heading", "level": 2, "text": "{{cat.value}}"},
                    {
                        "type": "each", "source": {"group": "cat", "sort": [{"field": "title"}]}, "as": "req",
                        "children": [
                            {"type": "heading", "level": 3, "text": "{{req.code}} {{req.title}}"},
                            {
                                "type": "each", "as": "pain",
                                "source": {"record_type": PAIN, "linked_from": "req", "sort": [{"field": "title"}]},
                                "children": [
                                    {"type": "text", "text": "**Pain point** {{pain.title}}"},
                                    {
                                        "type": "table", "source": {"record_type": STAKEHOLDER, "linked_from": "pain"},
                                        "columns": [{"field": "title", "label": "Stakeholder"}, {"field": "role"}],
                                        "empty_text": "No stakeholders affected.",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    },
)


# --- the worked example -----------------------------------------------------------------------


def test_requirements_by_component_and_category_with_linked_pain_points_and_stakeholders(world, db):
    project = world.project("Example P")
    hardware, reliability = component_and_category(world, project, "Hardware", "Reliability")
    r1 = requirement(world, project, "Checkout is slow")
    requirement(world, project, "Search is wrong")
    r3 = requirement(world, project, "Disk fails", hardware, reliability)
    p1, p2, p3 = (world.pain_point(project, t) for t in ("Late reports", "Lost orders", "Noisy fans"))
    pat = stakeholder(world, project, "Pat", "Analyst")
    for req, pain in ((r1, p2), (r1, p1), (r3, p3)):
        world.link((REQ, req), (PAIN, pain))
    world.link((STAKEHOLDER, pat), (PAIN, p1))

    result = run(db, world, project, EXAMPLE, title="Impact")

    assert lines(result.document) == [
        "H1 Impact for Example P",
        "H1 Hardware (1)",
        "H2 Reliability",
        "H3 <code> Disk fails",
        "P Pain point Noisy fans",
        "N No stakeholders affected.",
        "H1 Software (2)",
        "H2 Performance",
        "H3 <code> Checkout is slow",
        "P Pain point Late reports",
        "T Stakeholder|Role :: Pat|Analyst",
        "P Pain point Lost orders",
        "N No stakeholders affected.",
        "H3 <code> Search is wrong",
    ]
    assert result.warnings == [] and result.sheets == [] and not result.document.landscape
    assert result.stats.records_read["requirement"] == 3 and result.stats.hidden == 0


def test_the_number_of_queries_does_not_grow_with_the_number_of_records(world, db):
    tree = doc({
        "type": "each", "source": {"record_type": REQ}, "as": "req", "children": [
            {"type": "each", "source": {"record_type": PAIN, "linked_from": "req"}, "as": "pain", "children": [
                {"type": "text", "text": "{{req.title}} {{pain.title}}"},
            ]},
        ],
    })

    def statements(records: int) -> int:
        project = world.project(f"Count P {records}")
        for i in range(records):
            world.link((REQ, requirement(world, project, f"R{i}")), (PAIN, world.pain_point(project, f"P{i}")))
        seen: list[str] = []

        def record(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            out = run(db, world, project, tree)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len([x for x in lines(out.document) if x.startswith("P ")]) == records
        return len(seen)

    assert statements(6) == statements(2)


# --- values are never markup ------------------------------------------------------------------


def test_a_record_value_never_becomes_markup_or_a_placeholder(world, db):
    project = world.project("Inject P")
    hostile = "# Boom {{record.code}} <img src=\"file:///etc/passwd\"> - item"
    requirement(world, project, hostile)
    tree = doc({"type": "each", "source": {"record_type": REQ}, "children": [
        {"type": "text", "text": "{{record.title}}"},
        {"type": "text", "text": "- {{record.title}}"},
        {"type": "heading", "text": "{{record.title}}"},
    ]})

    blocks = [b for b in run(db, world, project, tree).document.blocks if not isinstance(b, Gap)]

    assert blocks[0] == Paragraph(hostile)                   # not a heading, not a substituted code
    assert type(blocks[1]).__name__ == "BulletList" and blocks[1].items == [hostile]
    assert blocks[2] == Heading(hostile, 1)
    assert not any(isinstance(b, Heading) and b.text != hostile for b in blocks)


def test_a_title_that_looks_like_a_placeholder_is_not_substituted_again(world, db):
    project = world.project("Twice P")
    requirement(world, project, "{{project_name}}")
    tree = doc({"type": "each", "source": {"record_type": REQ}, "children": [{"type": "text", "text": "{{record.title}}"}]})

    assert lines(run(db, world, project, tree).document) == ["P {{project_name}}"]


def test_global_placeholders_and_overrides(world, db):
    project = world.project("Global P")
    tree = doc({"type": "text", "text": "{{report_title}} | {{project_name}} | {{organisation}} | {{generated_on}}"})

    default = lines(run(db, world, project, tree, title="Quarterly").document)[0]
    custom = lines(run(db, world, project, tree, title="Quarterly", placeholders={"generated_on": "26 Oct"}).document)[0]

    assert default.startswith(f"P Quarterly | Global P | {world.org['name']} | 20") and custom.endswith("| 26 Oct")


def test_orientation_is_carried_to_the_document(world, db):
    project = world.project("Wide P")
    assert run(db, world, project, doc(orientation="landscape")).document.landscape is True


# --- filter, sort, group, if ------------------------------------------------------------------


def test_where_sort_and_descending(world, db):
    project = world.project("Sort P")
    for name in ("banana", "Apple", "cherry", "apricot"):
        requirement(world, project, name)
    each = each_title

    assert lines(run(db, world, project, each(sort=[{"field": "title"}])).document) == ["P Apple", "P apricot", "P banana", "P cherry"]
    assert lines(run(db, world, project, each(sort=[{"field": "title", "descending": True}])).document)[0] == "P cherry"
    filtered = each(where=[{"field": "title", "op": "contains", "value": "AP"}], sort=[{"field": "title"}])
    assert lines(run(db, world, project, filtered).document) == ["P Apple", "P apricot"]


def test_records_without_a_value_sort_last_in_both_directions(world, db):
    project = world.project("Blank P")
    requirement(world, project, "no review date")

    def each(desc: bool) -> dict[str, Any]:
        return each_title(sort=[{"field": "review_date", "descending": desc}, {"field": "title"}])

    requirement(world, project, "another")

    assert lines(run(db, world, project, each(False)).document) == ["P another", "P no review date"]
    assert lines(run(db, world, project, each(True)).document) == ["P another", "P no review date"]


def test_groups_are_ordered_and_the_empty_group_comes_last(world, db):
    project = world.project("Group P")
    alpha_c, alpha_k = component_and_category(world, project, "Alpha", "Core")
    requirement(world, project, "one")
    requirement(world, project, "two", alpha_c, alpha_k)
    tree = doc({"type": "group", "source": {"record_type": REQ}, "by": "reviewer", "children": [
        {"type": "text", "text": "{{group.value}}={{group.count}}"},
    ]})
    assert lines(run(db, world, project, tree).document) == [f"P {EMPTY_GROUP_LABEL}=2"]

    by_component = doc({"type": "group", "source": {"record_type": REQ}, "by": "component", "children": [
        {"type": "text", "text": "{{group.value}}={{group.count}}"},
    ]})
    assert lines(run(db, world, project, by_component).document) == ["P Alpha=1", "P Software=1"]


def test_if_chooses_a_branch_on_a_field_and_on_a_groups_count(world, db):
    project = world.project("If P")
    requirement(world, project, "Open one")
    done = requirement(world, project, "Done one")
    db.query(Requirement).filter(Requirement.id == done).update({"is_completed": True})
    db.commit()
    tree = doc({"type": "each", "source": {"record_type": REQ, "sort": [{"field": "title"}]}, "children": [
        {"type": "if", "when": {"ref": "record.is_completed", "op": "eq", "value": True},
         "children": [{"type": "text", "text": "{{record.title}} is done"}],
         "else_children": [{"type": "text", "text": "{{record.title}} is open"}]},
    ]})
    assert lines(run(db, world, project, tree).document) == ["P Done one is done", "P Open one is open"]

    by_state = doc({"type": "group", "source": {"record_type": REQ}, "by": "is_completed", "children": [
        {"type": "if", "when": {"ref": "group.count", "op": "gte", "value": 1},
         "children": [{"type": "text", "text": "{{group.value}}: {{group.count}}"}]},
    ]})
    assert lines(run(db, world, project, by_state).document) == ["P No: 1", "P Yes: 1"]


def test_archived_records_need_include_archived(world, db):
    project = world.project("Archive P")
    requirement(world, project, "live")
    old = requirement(world, project, "old")
    db.query(Requirement).filter(Requirement.id == old).update({"is_archived": True})
    db.commit()

    def tree(**source: Any) -> dict[str, Any]:
        return each_title(sort=[{"field": "title"}], **source)

    assert lines(run(db, world, project, tree()).document) == ["P live"]
    assert lines(run(db, world, project, tree(include_archived=True)).document) == ["P live", "P old"]


# --- what the caller cannot see ---------------------------------------------------------------


def test_records_the_caller_cannot_see_are_counted_and_never_named(world, db, monkeypatch):
    project = world.project("Hidden P")
    req = requirement(world, project, "Visible requirement")
    world.link((REQ, req), (PAIN, world.pain_point(project, "Secret pain A")))
    world.link((REQ, req), (PAIN, world.pain_point(project, "Secret pain B")))
    deny(monkeypatch, "pain_point:view")
    tree = doc({"type": "each", "source": {"record_type": REQ}, "as": "req", "children": [
        {"type": "each", "as": "pain", "source": {"record_type": PAIN, "linked_from": "req"},
         "children": [{"type": "text", "text": "{{pain.title}}"}]},
    ]})

    result = run(db, world, project, tree)

    assert lines(result.document) == ["N 2 records not shown (not accessible to you, or not available)."]
    assert "Secret" not in repr(result.document) and result.stats.hidden == 2


def test_a_filtered_block_says_up_to(world, db, monkeypatch):
    project = world.project("Upto P")
    world.pain_point(project, "Secret")
    deny(monkeypatch, "pain_point:view")
    where = [{"field": "title", "op": "contains", "value": "x"}]
    tree = doc({"type": "table", "source": {"record_type": PAIN, "where": where}, "columns": [{"field": "title"}]})

    assert lines(run(db, world, project, tree).document) == ["N Up to 1 records not shown (not accessible to you, or not available)."]


def test_a_singular_count_reads_naturally(world, db, monkeypatch):
    project = world.project("One P")
    world.pain_point(project, "Secret")
    deny(monkeypatch, "pain_point:view")
    tree = doc({"type": "table", "source": {"record_type": PAIN}, "columns": [{"field": "title"}]})

    assert lines(run(db, world, project, tree).document) == ["N 1 record not shown (not accessible to you, or not available)."]


# --- link types -------------------------------------------------------------------------------


def test_link_types_are_followed_by_name_in_either_reading(world, db):
    project = world.project("Types P")
    req = requirement(world, project, "R")
    kept, dropped = world.pain_point(project, "Kept"), world.pain_point(project, "Dropped")
    raises = world.link_type("Raises", "Raised by")
    mentions = world.link_type("Mentions", "Mentioned by")
    world.link((REQ, req), (PAIN, kept), raises)
    world.link((REQ, req), (PAIN, dropped), mentions)
    names = world.link_types_by_name()
    forward = next(n for n in names if n.startswith("Raises "))

    def tree(link_types):
        return doc({"type": "each", "source": {"record_type": REQ}, "as": "req", "children": [
            {"type": "each", "as": "pain", "children": [{"type": "text", "text": "{{pain.title}}"}],
             "source": {"record_type": PAIN, "linked_from": "req", "link_types": link_types, "sort": [{"field": "title"}]}},
        ]})

    assert lines(run(db, world, project, tree([forward])).document) == ["P Kept"]
    assert lines(run(db, world, project, tree(["RAISED BY"])).document) == ["P Kept"]  # the reverse name, any case
    assert lines(run(db, world, project, tree([])).document) == ["P Dropped", "P Kept"]
    missing = run(db, world, project, tree(["No such type"]))
    assert lines(missing.document) == [] and missing.warnings == ['No link type is named "No such type" in this project, so it matches nothing.']


def test_direction_limits_which_links_are_followed(world, db):
    project = world.project("Direction P")
    req = requirement(world, project, "R")
    out_pain, in_pain = world.pain_point(project, "Out"), world.pain_point(project, "In")
    world.link((REQ, req), (PAIN, out_pain))
    world.link((PAIN, in_pain), (REQ, req))

    def tree(direction):
        return doc({"type": "each", "source": {"record_type": REQ}, "as": "req", "children": [
            {"type": "each", "as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "direction": direction},
             "children": [{"type": "text", "text": "{{pain.title}}"}]},
        ]})

    assert lines(run(db, world, project, tree("outgoing")).document) == ["P Out"]
    assert lines(run(db, world, project, tree("incoming")).document) == ["P In"]


# --- the table family -------------------------------------------------------------------------


def test_a_table_layout_yields_sheets(world, db):
    project = world.project("Sheets P")
    for name in ("b", "a"):
        requirement(world, project, name)
    tree = {"schema_version": 1, "family": "table", "nodes": [
        {"type": "sheet", "name": "Requirements", "source": {"record_type": REQ, "sort": [{"field": "title"}]},
         "columns": [{"field": "code", "label": "ID"}, {"field": "title"}, {"field": "status"}]},
        {"type": "sheet", "name": "Pain", "source": {"record_type": PAIN}, "columns": [{"field": "title"}]},
    ]}

    result = run(db, world, project, tree)

    assert result.document is None and [s.name for s in result.sheets] == ["Requirements", "Pain"]
    first = result.sheets[0]
    assert first.columns == ["ID", "Title", "Status"] and [r[1] for r in first.rows] == ["a", "b"]
    assert all(re.fullmatch(r"[A-Z0-9-]+-\d+", r[0]) for r in first.rows)
    assert result.sheets[1].rows == [] and result.stats.rows == 2


def test_a_sheet_reports_unseen_records_as_a_warning(world, db, monkeypatch):
    project = world.project("Sheet hidden P")
    world.pain_point(project, "Secret")
    deny(monkeypatch, "pain_point:view")
    tree = {"schema_version": 1, "family": "table", "nodes": [
        {"type": "sheet", "name": "Pain", "source": {"record_type": PAIN}, "columns": [{"field": "title"}]},
    ]}

    result = run(db, world, project, tree)

    assert result.sheets[0].rows == []
    assert result.warnings == ['Sheet "Pain": 1 record(s) not shown (not accessible to you, or not available).']


def impact_sheet(**overrides: Any) -> dict[str, Any]:
    sheet = {
        "type": "sheet", "name": "Impact", "source": {"record_type": REQ, "sort": [{"field": "title"}]}, "as": "req",
        "joins": [
            {"as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "sort": [{"field": "title"}]}},
            {"as": "who", "source": {"record_type": STAKEHOLDER, "linked_from": "pain", "sort": [{"field": "title"}]}},
        ],
        "columns": [
            {"field": "title", "label": "Requirement"}, {"field": "title", "from": "pain", "label": "Pain point"},
            {"field": "title", "from": "who", "label": "Stakeholder"}, {"field": "role", "from": "who"},
        ],
    }
    return {"schema_version": 1, "family": "table", "nodes": [{**sheet, **overrides}]}


def test_a_sheet_joins_requirements_pain_points_and_stakeholders_one_row_per_combination(world, db):
    project = world.project("Join P")
    a, b, c = (requirement(world, project, t) for t in ("A req", "B req", "C req"))
    late, lost, noisy = (world.pain_point(project, t) for t in ("Late", "Lost", "Noisy"))
    pat, sam = stakeholder(world, project, "Pat", "Analyst"), stakeholder(world, project, "Sam", "Buyer")
    for req, pain in ((a, late), (a, lost), (b, noisy)):
        world.link((REQ, req), (PAIN, pain))
    world.link((STAKEHOLDER, pat), (PAIN, late))
    world.link((STAKEHOLDER, sam), (PAIN, late))
    world.link((STAKEHOLDER, sam), (PAIN, noisy))

    sheet = run(db, world, project, impact_sheet()).sheets[0]

    assert sheet.columns == ["Requirement", "Pain point", "Stakeholder", "Role"]
    assert sheet.rows == [
        ["A req", "Late", "Pat", "Analyst"],     # a pain point with two stakeholders: two rows
        ["A req", "Late", "Sam", "Buyer"],
        ["A req", "Lost", "", ""],               # no stakeholders: kept, blank (left join)
        ["B req", "Noisy", "Sam", "Buyer"],
        ["C req", "", "", ""],                   # no pain points: kept, everything downstream blank
    ]
    assert c  # created, linked to nothing


def test_a_join_filters_and_hides_like_any_other_source(world, db, monkeypatch):
    project = world.project("Join filter P")
    req = requirement(world, project, "R")
    world.link((REQ, req), (PAIN, world.pain_point(project, "Keep")))
    world.link((REQ, req), (PAIN, world.pain_point(project, "Drop")))
    where = [{"field": "title", "op": "eq", "value": "keep"}]
    tree = impact_sheet(joins=[{"as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "where": where}}],
                        columns=[{"field": "title"}, {"field": "title", "from": "pain"}])
    assert run(db, world, project, tree).sheets[0].rows == [["R", "Keep"]]

    deny(monkeypatch, "pain_point:view")
    result = run(db, world, project, tree)
    assert result.sheets[0].rows == [["R", ""]]
    assert result.warnings == ['Sheet "Impact": 2 record(s) not shown (not accessible to you, or not available).']
    assert "Keep" not in repr(result.sheets)


def test_a_parent_in_many_rows_has_its_unseen_records_counted_once(world, db, monkeypatch):
    project = world.project("Join count P")
    req = requirement(world, project, "R")
    for title in ("One", "Two"):
        world.link((REQ, req), (PAIN, world.pain_point(project, title)))
    world.link((STAKEHOLDER, stakeholder(world, project, "Hidden Sam")), (REQ, req))
    deny(monkeypatch, "stakeholder")
    tree = impact_sheet(joins=[
        {"as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "sort": [{"field": "title"}]}},
        {"as": "who", "source": {"record_type": STAKEHOLDER, "linked_from": "req"}},
    ], columns=[{"field": "title"}, {"field": "title", "from": "pain"}, {"field": "title", "from": "who"}])

    result = run(db, world, project, tree)

    # The requirement is in two rows (two Pain Points) but its one unseen Stakeholder is counted once.
    assert result.sheets[0].rows == [["R", "One", ""], ["R", "Two", ""]]
    assert result.warnings == ['Sheet "Impact": 1 record(s) not shown (not accessible to you, or not available).']
    assert "Hidden Sam" not in repr(result.sheets)


def test_a_join_that_explodes_is_stopped(world, db, monkeypatch):
    project = world.project("Explode P")
    req = requirement(world, project, "R")
    for i in range(4):
        world.link((REQ, req), (PAIN, world.pain_point(project, f"P{i}")))
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 3)

    with pytest.raises(LayoutLimitError, match="too large"):
        run(db, world, project, impact_sheet(joins=[{"as": "pain", "source": {"record_type": PAIN, "linked_from": "req"}}],
                                             columns=[{"field": "title"}, {"field": "title", "from": "pain"}]))


# --- limits and refusals ----------------------------------------------------------------------


def test_too_many_record_visits_stop_the_run(world, db, monkeypatch):
    project = world.project("Work P")
    for i in range(5):
        requirement(world, project, f"R{i}")
    monkeypatch.setattr(report_layout_eval, "MAX_WORK", 6)
    tree = doc({"type": "each", "source": {"record_type": REQ}, "children": [{"type": "text", "text": "{{record.title}}"}]})

    with pytest.raises(LayoutLimitError, match="too many records"):
        run(db, world, project, tree)


def test_too_much_output_stops_the_run(world, db, monkeypatch):
    project = world.project("Output P")
    for i in range(5):
        requirement(world, project, f"R{i}")
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 4)
    tree = doc({"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "title"}]})

    with pytest.raises(LayoutLimitError, match="too large"):
        run(db, world, project, tree)


def test_a_slow_run_times_out(world, db):
    project = world.project("Slow P")
    with pytest.raises(LayoutTimeoutError):
        run(db, world, project, doc({"type": "page_break"}), timeout_seconds=-1)


def test_a_tree_that_is_no_longer_valid_is_refused_at_run_time(world, db):
    project = world.project("Stale P")
    with pytest.raises(InvalidLayoutError):
        run(db, world, project, doc({"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "removed_field"}]}))


def test_a_layout_needs_a_project_to_run_for(world, db):
    project = world.project("Orgwide P")
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    ctx = ReportContext(module_key="reporting", organization=org, projects=[row], root_project=None)
    with pytest.raises(ValueError, match="one project"):
        evaluate_layout(db, ArtefactResolver(db, row, world.user_id), ctx, doc(), title="T")


def test_every_block_type_can_be_validated_and_evaluated():
    assert set(BLOCK_SPECS) == set(report_layout_eval._EVALUATORS)


# --- condition comparisons --------------------------------------------------------------------


@pytest.mark.parametrize(("kind", "actual", "op", "expected", "result"), [
    ("text", "Slow Reports", "contains", "slow", True),
    ("text", "Slow", "eq", "SLOW", True),
    ("text", None, "ne", "x", True),
    ("text", "", "empty", None, True),
    ("text", "a", "not_empty", None, True),
    ("enum", "Draft", "in", ["approved", "draft"], True),
    ("enum", "Draft", "in", ["approved"], False),
    ("number", 3, "gt", 2, True),
    ("number", 0, "empty", None, False),
    ("number", None, "gt", 0, False),
    ("bool", False, "eq", False, True),
    ("bool", True, "ne", False, True),
    ("date", date(2026, 10, 26), "eq", "2026-10-26", True),
    ("date", date(2026, 10, 26), "lt", "2026-10-26", False),
    ("date", date(2026, 10, 25), "lt", "2026-10-26", True),
])
def test_condition_comparisons(kind, actual, op, expected, result):
    assert matches_value(actual, kind, op, expected) is result


def test_instants_compare_as_utc_whatever_zone_the_literal_is_written_in():
    nine_at_plus_10 = datetime(2026, 10, 25, 23, 0, tzinfo=UTC)  # 09:00 on 26 Oct at UTC+10
    assert matches_value(nine_at_plus_10, "instant", "gte", "2026-10-26T09:00:00+10:00")
    assert matches_value(nine_at_plus_10, "instant", "lte", "2026-10-26T09:00:00+10:00")
    assert not matches_value(nine_at_plus_10, "instant", "gt", "2026-10-26T09:00:00+10:00")
    # 23:00 on 25 Oct at UTC-8 is 07:00 UTC on the 26th: eight hours after the instant above.
    assert matches_value(nine_at_plus_10, "instant", "lt", "2026-10-25T23:00:00-08:00")
    assert matches_value(nine_at_plus_10, "instant", "lt", "2026-10-25T23:00:01Z")
    assert not matches_value(nine_at_plus_10, "instant", "lt", "2026-10-25T23:00:00Z")


# ---- an `if` on a module ---------------------------------------------------------------------------------------


def module_if(module: str) -> dict[str, Any]:
    return doc({
        "type": "if", "when": {"module": module},
        "children": [{"type": "text", "text": "module on"}], "else_children": [{"type": "text", "text": "module off"}],
    })


def test_an_if_on_a_module_shows_its_children_where_the_module_is_available(db, world):
    project = world.project("Has the module")

    assert lines(run(db, world, project, module_if("context_strategy")).document) == ["P module on"]


def test_an_if_on_a_module_shows_the_else_children_where_the_module_is_off(db, world):
    project = world.project("Lacks the module")

    assert lines(run(db, world, project, module_if("risk_management")).document) == ["P module off"]


def test_an_if_on_a_module_combines_with_not(db, world):
    project = world.project("Negated")
    tree = doc({"type": "if", "when": {"not": {"module": "risk_management"}}, "children": [{"type": "text", "text": "no risk module"}]})

    assert lines(run(db, world, project, tree).document) == ["P no risk module"]
