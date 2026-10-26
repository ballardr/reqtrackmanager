"""Tests for conditions in custom report layouts: `in` / `not_in` for every kind of field, `all` / `any` / `not` and
brackets (tree, text view, evaluator), and sorting a widget's table by column.

The validator, the text view and the sort need no database; the end-to-end runs build their own organisation.
"""

from __future__ import annotations

import copy
import itertools
import random
import uuid
from typing import Any

import pytest

from app.database import SessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.services import report_layout_eval
from app.services.link_graph import ArtefactResolver
from app.services.report_framework import ReportContext, ReportResult, ReportSection
from app.services.report_layout_eval import evaluate_layout, matches_condition, matches_value
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import MAX_CONDITION_DEPTH, MAX_CONDITIONS, TreeError, empty_tree, validate_tree
from app.services.report_model import Note, Table
from app.services.report_widget_run import cell_sort_key, part_blocks, sorted_order
from app.services.report_widgets import WidgetPart
from tests.link_world import World
from tests.test_report_layout_eval import component_and_category, lines, requirement

REQ = "requirement"
MATRIX = "context_strategy.pain-point-coverage.matrix"


def doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {**empty_tree("document"), "nodes": list(nodes)}


def leaf(field: str, op: str, value: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"field": field, "op": op}
    if value is not None:
        out["value"] = value
    return out


def where(*conds: dict[str, Any], record_type: str = REQ) -> dict[str, Any]:
    """A layout with one table over `record_type` filtered by `conds`."""
    return doc({"type": "table", "source": {"record_type": record_type, "where": list(conds)}, "columns": [{"field": "title"}]})


def errors_of(tree: dict[str, Any]) -> list[TreeError]:
    return validate_tree(tree).errors


def paths(tree: dict[str, Any]) -> dict[str, str]:
    return {e.path: e.message for e in errors_of(tree)}


# ---- in / not_in for every kind of field ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("record_type", "field", "values"),
    [
        (REQ, "category", ["Safety", "Security"]),  # text
        (REQ, "status", ["draft", "approved"]),  # enum
        (REQ, "owner", ["Ada", "Grace"]),  # principal
        ("persona", "weight", [1, 2.5]),  # number
        (REQ, "review_date", ["2026-10-01", "2026-11-01"]),  # date
    ],
)
@pytest.mark.parametrize("op", ["in", "not_in"])
def test_in_and_not_in_work_on_every_kind_that_has_a_list_of_values(record_type, field, values, op):
    assert errors_of(where(leaf(field, op, values), record_type=record_type)) == []


@pytest.mark.parametrize(("field", "kind"), [("is_completed", "bool"), ("completed_at", "instant")])
def test_in_is_refused_where_a_list_means_nothing(field, kind):
    assert paths(where(leaf(field, "in", [True])))["nodes[0].source.where[0].op"].startswith(f"A {kind} field accepts")


def test_the_values_of_in_are_checked_one_by_one_against_the_fields_kind():
    errors = paths(where(leaf("review_date", "in", ["2026-10-01", "soon"])))

    assert errors == {"nodes[0].source.where[0].value[1]": "Must be a date as YYYY-MM-DD."}
    assert paths(where(leaf("category", "in", [])))["nodes[0].source.where[0].value"] == "Must be a list of 1 to 20 values."
    assert paths(where(leaf("category", "not_in", ["x"] * 21)))["nodes[0].source.where[0].value"] == "Must be a list of 1 to 20 values."
    assert paths(where(leaf("category", "in", "Safety")))["nodes[0].source.where[0].value"] == "Must be a list of 1 to 20 values."
    assert "nodes[0].source.where[0].value[0]" in paths(where(leaf("category", "in", [5])))


def test_matching_in_and_not_in():
    assert matches_value("Safety", "text", "in", ["safety", "Security"]) is True  # text ignores case
    assert matches_value("Other", "text", "in", ["Safety"]) is False
    assert matches_value("Other", "text", "not_in", ["Safety"]) is True
    assert matches_value("Safety", "text", "not_in", ["safety"]) is False
    assert matches_value(2, "number", "in", [1, 2]) is True and matches_value(3, "number", "in", [1, 2]) is False
    assert matches_value(2.5, "number", "not_in", [1, 2]) is True
    from datetime import date

    assert matches_value(date(2026, 10, 1), "date", "in", ["2026-10-01"]) is True
    assert matches_value(date(2026, 10, 2), "date", "not_in", ["2026-10-01"]) is True


def test_an_empty_value_is_never_in_a_list_and_always_not_in_it():
    """Everything except General keeps the records with no category; "in" never matches an empty value."""
    for empty in (None, ""):
        assert matches_value(empty, "text", "in", ["General"]) is False
        assert matches_value(empty, "text", "not_in", ["General"]) is True
        assert matches_value(empty, "text", "ne", "General") is True


# ---- all / any / not in the tree -------------------------------------------------------------------------------


def test_a_where_may_hold_boolean_nodes_beside_plain_conditions():
    tree = where(
        {"any": [leaf("category", "in", ["A", "B"]), {"all": [leaf("status", "eq", "draft"), {"not": leaf("title", "contains", "x")}]}]},
        leaf("title", "not_empty"),
    )

    assert errors_of(tree) == []


def test_a_list_of_plain_conditions_is_still_valid_as_stored_before_boolean_nodes_existed():
    assert errors_of(where(leaf("status", "eq", "draft"), leaf("title", "contains", "x"))) == []


@pytest.mark.parametrize("key", ["all", "any"])
def test_all_and_any_need_two_or_more_conditions(key):
    one = paths(where({key: [leaf("title", "not_empty")]}))
    none = paths(where({key: []}))
    wrong = paths(where({key: leaf("title", "not_empty")}))

    for found in (one, none, wrong):
        assert found["nodes[0].source.where[0]." + key].startswith(f'"{key}" needs a list of two or more conditions')


def test_not_takes_one_condition_and_a_boolean_node_has_no_other_keys():
    assert errors_of(where({"not": leaf("title", "not_empty")})) == []
    assert paths(where({"not": [leaf("title", "not_empty")]}))["nodes[0].source.where[0].not"] == "Must be an object."
    assert paths(where({"not": leaf("title", "not_empty"), "extra": 1}))["nodes[0].source.where[0]"] == 'A "not" condition has no other keys.'
    assert paths(where({"all": [leaf("title", "not_empty")] * 2, "any": [leaf("title", "not_empty")] * 2}))[
        "nodes[0].source.where[0]"
    ].startswith('A "all" condition has no other keys')


def test_a_problem_inside_a_nested_condition_is_positioned_at_it():
    tree = where({"any": [leaf("title", "not_empty"), {"all": [leaf("nonsense", "eq", "x"), leaf("status", "eq", "bogus!")]}]})

    errors = paths(tree)

    assert "nodes[0].source.where[0].any[1].all[0].field" in errors


def test_conditions_may_nest_only_so_deep():
    def nested(levels: int) -> dict[str, Any]:
        node = leaf("title", "not_empty")
        for _ in range(levels):
            node = {"not": node}
        return node

    assert errors_of(where(nested(MAX_CONDITION_DEPTH))) == []
    (path, message), = paths(where(nested(MAX_CONDITION_DEPTH + 1))).items()
    assert "nested too deeply" in message and path.count(".not") == MAX_CONDITION_DEPTH


def test_the_leaf_limit_counts_every_test_in_a_where_however_nested():
    ok = [leaf("title", "contains", str(i)) for i in range(MAX_CONDITIONS)]

    assert errors_of(where({"any": ok})) == []
    assert "Too many conditions" in paths(where({"any": [*ok, leaf("title", "contains", "x")]}))["nodes[0].source.where"]
    assert "Too many conditions" in paths(where(*ok, {"all": [leaf("title", "contains", "a"), leaf("title", "contains", "b")]}))[
        "nodes[0].source.where"
    ]


def test_fields_used_inside_nested_conditions_are_loaded():
    tree = where({"any": [leaf("category", "in", ["A"]), {"not": leaf("review_date", "empty")}]})

    analysis = validate_tree(tree)

    assert analysis.ok
    (refs,) = (r for r in analysis.refs.values())
    assert ("requirement", "category") in refs and ("requirement", "review_date") in refs


def if_tree(when: dict[str, Any]) -> dict[str, Any]:
    return doc({
        "type": "each", "source": {"record_type": REQ}, "as": "req",
        "children": [{"type": "if", "when": when, "children": [{"type": "text", "text": "x"}]}],
    })


def test_an_if_may_combine_tests_too():
    ok = {"any": [{"ref": "req.status", "op": "in", "value": ["draft"]}, {"not": {"ref": "req.title", "op": "empty"}}]}

    assert errors_of(if_tree(ok)) == []
    assert errors_of(if_tree({"ref": "req.status", "op": "eq", "value": "draft"})) == []  # the old single test
    bad = paths(if_tree({"all": [{"ref": "req.status", "op": "eq", "value": "draft"}, {"ref": "nope.status", "op": "empty"}]}))
    assert "nodes[0].children[0].when.all[1].ref" in bad


# ---- truth tables ----------------------------------------------------------------------------------------------


def test_all_any_and_not_evaluate_as_logic_does():
    values = {"a": True, "b": False}

    def test(node: dict[str, Any]) -> bool:
        return values[node["field"]]

    a, b = {"field": "a"}, {"field": "b"}
    assert matches_condition({"all": [a, b]}, test) is False
    assert matches_condition({"all": [a, a]}, test) is True
    assert matches_condition({"any": [b, a]}, test) is True
    assert matches_condition({"any": [b, b]}, test) is False
    assert matches_condition({"not": b}, test) is True
    assert matches_condition({"not": {"any": [b, a]}}, test) is False
    assert matches_condition({"any": [{"all": [a, b]}, {"not": b}]}, test) is True


# ---- the text view ---------------------------------------------------------------------------------------------


def head(clause: str) -> str:
    return f"@layout document\n\n@table requirement {clause}\n  @column title\n@end\n"


def parsed_where(clause: str) -> list[dict[str, Any]]:
    result = parse_text(head(clause))
    assert result.ok, result.errors
    return result.tree["nodes"][0]["source"]["where"]


A, B, C = leaf("category", "eq", "A"), leaf("status", "eq", "draft"), leaf("title", "contains", "x")


def test_not_binds_tighter_than_and_which_binds_tighter_than_or():
    assert parsed_where("where category eq A or status eq draft and title contains x") == [{"any": [A, {"all": [B, C]}]}]
    assert parsed_where("where category eq A and status eq draft or title contains x") == [{"any": [{"all": [A, B]}, C]}]
    assert parsed_where("where not category eq A and status eq draft") == [{"all": [{"not": A}, B]}]
    assert parsed_where("where not not category eq A") == [{"not": {"not": A}}]


def test_brackets_group_and_are_kept_as_structure():
    assert parsed_where("where (category eq A or status eq draft) and title contains x") == [{"all": [{"any": [A, B]}, C]}]
    assert parsed_where("where not (category eq A or status eq draft)") == [{"not": {"any": [A, B]}}]
    assert parsed_where("where category eq A and (status eq draft and title contains x)") == [{"all": [A, {"all": [B, C]}]}]
    assert parsed_where("where category eq A and status eq draft and title contains x") == [{"all": [A, B, C]}]
    assert parsed_where("where (category eq A)") == [A]  # brackets round one test add nothing


def test_several_where_clauses_are_separate_entries_and_one_clause_with_and_is_one_entry():
    assert parsed_where("where category eq A where status eq draft") == [A, B]
    assert parsed_where("where category eq A and status eq draft") == [{"all": [A, B]}]


def test_in_and_not_in_read_a_comma_list_and_stop_at_the_next_word_of_logic():
    assert parsed_where("where category in Safety, Security or status not_in draft, rejected") == [
        {"any": [leaf("category", "in", ["Safety", "Security"]), leaf("status", "not_in", ["draft", "rejected"])]}
    ]
    persona = parse_text("@layout document\n\n@table persona where weight in 1, 2.5\n  @column title\n@end\n")
    assert persona.ok, persona.errors
    assert persona.tree["nodes"][0]["source"]["where"] == [leaf("weight", "in", [1, 2.5])]
    assert parsed_where("where category in A, B and (status eq draft)") == [{"all": [leaf("category", "in", ["A", "B"]), B]}]


def test_a_value_that_is_a_word_of_logic_or_has_a_bracket_must_be_quoted_and_is_written_so():
    tree = where(
        {"any": [leaf("title", "eq", "and"), leaf("title", "eq", "Or"), leaf("title", "in", ["not", "a (b)", "x)"])]},
        leaf("category", "ne", "or"),
    )
    text = format_tree(tree)

    assert 'title eq "and"' in text and 'title eq Or' in text and 'in "not", "a (b)", "x)"' in text and 'category ne "or"' in text
    assert parse_text(text).tree == tree


def test_syntax_errors_in_a_condition_are_positioned():
    def error(clause: str) -> str:
        result = parse_text(head(clause))
        assert result.tree is None, clause
        assert len(result.errors) == 1 and result.errors[0].line == 3
        return result.errors[0].message

    assert "never closed" in error("where (category eq A and status eq draft")
    assert "Unexpected )" in error("where category eq A)")
    assert 'A bare "and" is logic' in error("where title eq and")
    assert 'A bare "or" is logic' in error("where title in x, or")
    assert "Expected a field name" in error("where category eq A and")
    assert "Expected a field name" in error("where category eq A or or title eq x")
    assert "put the value in quotes" in error("where title eq a(b)")
    assert "Put text with brackets in quotes" in error("where title eq (")
    assert 'Only "in" and "not_in" take several values' in error("where category eq A, B")
    assert "Expected a value" in error("where category in")
    assert "Too many nots in a row" in error("where " + "not " * (MAX_CONDITION_DEPTH + 1) + "category eq A")
    assert "nested too deeply" in error("where " + "(" * 9 + "category eq A" + ")" * 9)


def test_a_condition_nested_past_the_limit_is_a_validator_error_at_its_line():
    clause = "where not (not (not (not (category eq A and status eq draft))))"
    result = parse_text(head(clause))

    assert result.tree is not None and not result.ok
    assert result.errors[0].line == 3 and "nested too deeply" in result.errors[0].message


def test_an_if_reads_and_writes_a_condition_too():
    text = (
        "@layout document\n\n@each requirement as req\n  @if req.status in draft, approved and not (req.title empty or req.level eq high)\n"
        "    ok\n  @else\n    no\n  @end\n@end\n"
    )
    result = parse_text(text)
    assert result.ok, result.errors
    when = result.tree["nodes"][0]["children"][0]["when"]

    assert when == {"all": [
        {"ref": "req.status", "op": "in", "value": ["draft", "approved"]},
        {"not": {"any": [{"ref": "req.title", "op": "empty"}, {"ref": "req.level", "op": "eq", "value": "high"}]}},
    ]}
    assert format_tree(result.tree) == text


def condition_trees() -> list[dict[str, Any]]:
    """Awkward conditions: every shape of nesting the writer must bracket correctly."""
    a, b, c, d = A, B, C, leaf("title", "in", ["x", "y z"])
    return [
        {"all": [a, b]}, {"any": [a, b]}, {"not": a}, {"not": {"not": a}},
        {"all": [a, {"all": [b, c]}]}, {"all": [{"all": [a, b]}, c]}, {"any": [a, {"any": [b, c]}]}, {"any": [{"any": [a, b]}, c]},
        {"any": [a, {"all": [b, c]}]}, {"any": [{"all": [a, b]}, {"all": [c, d]}]},
        {"all": [{"any": [a, b]}, c]}, {"all": [a, {"any": [b, c]}]}, {"all": [{"any": [a, b]}, {"any": [c, d]}]},
        {"not": {"all": [a, b]}}, {"not": {"any": [a, b]}}, {"all": [{"not": a}, b]}, {"any": [a, {"not": b}]},
        {"not": {"all": [{"not": a}, {"any": [b, {"not": c}]}]}},
        {"all": [a, {"not": {"any": [b, {"all": [c, d]}]}}]},
    ]


@pytest.mark.parametrize("cond", condition_trees())
def test_every_shape_of_condition_reads_back_exactly(cond):
    tree = where(cond, leaf("title", "not_empty"))
    assert validate_tree(tree).ok, validate_tree(tree).errors

    text = format_tree(tree)
    result = parse_text(text)

    assert result.ok, (text, result.errors)
    assert result.tree == tree, text
    assert format_tree(result.tree) == text


def test_a_hundred_random_conditions_read_back_exactly():
    rng = random.Random(20261026)
    leaves = [A, B, C, leaf("category", "in", ["A", "B c"]), leaf("review_date", "not_in", ["2026-10-01"]), leaf("owner", "empty"),
              leaf("title", "eq", "and"), leaf("is_completed", "eq", True)]

    def build(depth: int) -> dict[str, Any]:
        if depth >= MAX_CONDITION_DEPTH or rng.random() < 0.3:
            return copy.deepcopy(rng.choice(leaves))
        kind = rng.choice(["all", "any", "not"])
        if kind == "not":
            return {"not": build(depth + 1)}
        return {kind: [build(depth + 1) for _ in range(rng.randint(2, 3))]}

    made = 0
    while made < 100:
        cond = build(1)
        tree = where(cond)
        if not validate_tree(tree).ok:  # too many tests in one where; try another
            continue
        made += 1
        text = format_tree(tree)
        assert parse_text(text).tree == tree, text


def test_every_leaf_operator_and_kind_still_round_trips_as_before():
    tree = where(
        leaf("status", "in", ["draft"]), leaf("category", "contains", "x"), leaf("review_date", "gte", "2026-01-01"),
        leaf("owner", "not_empty"), leaf("is_completed", "eq", False),
    )

    assert parse_text(format_tree(tree)).tree == tree


# ---- evaluating conditions -------------------------------------------------------------------------------------


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Cond Org", context_strategy=True)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def run(db, world: World, project: dict, tree: dict[str, Any]):
    row = db.get(Project, uuid.UUID(project["id"]))
    org = db.get(Organization, uuid.UUID(world.org["id"]))
    resolver = ArtefactResolver(db, row, world.user_id, include_related=True)
    ctx = ReportContext(module_key="custom_reports", organization=org, projects=[row], root_project=row)
    return evaluate_layout(db, resolver, ctx, tree, title="Report")


@pytest.fixture
def requirements(world):
    """Alpha with Zed in General and Safety, plus two in Security and one in Legacy (all in one component)."""
    project = world.project("Alpha")
    for category in ("General", "Safety", "Security", "Legacy"):
        comp_id, cat_id = component_and_category(world, project, category, category)
        for name in {"General": ["Zed one"], "Safety": ["Zed two", "Brake rule"], "Security": ["Lock rule"], "Legacy": ["Old rule"]}[category]:
            requirement(world, project, name, comp_id, cat_id)
    return project


def titles(result) -> list[str]:
    out = []
    for block in result.document.blocks:
        if isinstance(block, Table):
            out += [row[0] for row in block.rows]
    return sorted(out)


def test_everything_except_one_category(db, world, requirements):
    result = run(db, world, requirements, where(leaf("category", "ne", "General")))

    assert titles(result) == sorted(["Zed two", "Brake rule", "Lock rule", "Old rule"])


def test_several_categories_combined_into_one_table(db, world, requirements):
    result = run(db, world, requirements, where(leaf("category", "in", ["Safety", "security"])))

    assert titles(result) == sorted(["Zed two", "Brake rule", "Lock rule"])


def test_not_in_excludes_several_categories(db, world, requirements):
    result = run(db, world, requirements, where(leaf("category", "not_in", ["General", "Legacy"])))

    assert titles(result) == sorted(["Zed two", "Brake rule", "Lock rule"])


def test_or_across_different_fields_and_brackets(db, world, requirements):
    either = where({"any": [leaf("category", "eq", "Legacy"), leaf("title", "contains", "Zed")]})
    zed_or_legacy = {"any": [leaf("category", "eq", "Legacy"), leaf("title", "contains", "Zed")]}
    narrowed = where({"all": [zed_or_legacy, {"not": leaf("category", "eq", "General")}]})

    assert titles(run(db, world, requirements, either)) == sorted(["Old rule", "Zed one", "Zed two"])
    assert titles(run(db, world, requirements, narrowed)) == sorted(["Old rule", "Zed two"])


def test_a_group_can_leave_a_category_out_and_print_a_table_per_remaining_one(db, world, requirements):
    tree = doc({
        "type": "group", "source": {"record_type": REQ, "where": [leaf("category", "not_in", ["General", "Legacy"])]}, "by": "category", "as": "cat",
        "children": [
            {"type": "heading", "text": "{{cat.value}}"},
            {"type": "table", "source": {"group": "cat", "sort": [{"field": "title"}]}, "columns": [{"field": "title"}]},
        ],
    })

    result = run(db, world, requirements, tree)

    assert lines(result.document) == [
        "H1 Safety", "T Title :: Brake rule / Zed two",
        "H1 Security", "T Title :: Lock rule",
    ]


def test_an_if_with_logic_chooses_a_branch_per_record(db, world, requirements):
    tree = doc({
        "type": "each", "source": {"record_type": REQ, "sort": [{"field": "title"}]}, "as": "req",
        "children": [{
            "type": "if",
            "when": {"all": [
                {"ref": "req.category", "op": "in", "value": ["Safety", "Security"]},
                {"not": {"ref": "req.title", "op": "contains", "value": "Zed"}},
            ]},
            "children": [{"type": "text", "text": "keep {{req.title}}"}],
            "else_children": [{"type": "text", "text": "skip {{req.title}}"}],
        }],
    })

    result = run(db, world, requirements, tree)

    assert lines(result.document) == ["P keep Brake rule", "P keep Lock rule", "P skip Old rule", "P skip Zed one", "P skip Zed two"]


# ---- sorting a widget -----------------------------------------------------------------------------------------


def test_cells_sort_the_way_a_person_reads_them():
    assert cell_sort_key("") is None and cell_sort_key("  ") is None
    assert not cell_sort_key("10") < cell_sort_key("9.5")  # numbers compare as numbers, not as text
    assert cell_sort_key("9.5") < cell_sort_key("10")
    assert cell_sort_key("1,200") == (0, 1200.0) and cell_sort_key("-3") == (0, -3.0) and cell_sort_key("45%") == (0, 45.0)
    assert cell_sort_key("2026-10-01") == (1, "2026-10-01")
    assert cell_sort_key("Banana") == (2, "banana") and cell_sort_key("REQ-001") == (2, "req-001")
    assert cell_sort_key("5") < cell_sort_key("2026-10-01") < cell_sort_key("apple")


def order(columns: list[str], rows: list[list[str]], *sort: dict[str, Any]) -> tuple[list[int], list[str]]:
    said: list[str] = []
    return sorted_order(columns, rows, list(sort), said.append), said


ROWS = [["b", "10", "2026-02-01"], ["A", "9", ""], ["c", "", "2026-01-01"], ["B", "100", "2026-03-01"]]
COLS = ["Name", "Count", "Date"]


def test_sorting_by_text_ignores_case_and_by_number_is_numeric():
    assert order(COLS, ROWS, {"column": "Name"})[0] == [1, 0, 3, 2]  # A, b, B (stable), c
    assert order(COLS, ROWS, {"column": "count"})[0] == [1, 0, 3, 2]  # 9, 10, 100, then the empty one last
    assert order(COLS, ROWS, {"column": "Count", "descending": True})[0] == [3, 0, 1, 2]  # empty stays last descending


def test_dates_sort_as_dates_and_empty_cells_are_last_either_way():
    assert order(COLS, ROWS, {"column": "Date"})[0] == [2, 0, 3, 1]
    assert order(COLS, ROWS, {"column": "Date", "descending": True})[0] == [3, 0, 2, 1]


def test_a_second_key_breaks_ties_and_the_first_is_most_significant():
    rows = [["x", "2"], ["y", "1"], ["x", "1"], ["y", "2"]]

    assert order(["K", "N"], rows, {"column": "K"}, {"column": "N", "descending": True})[0] == [0, 2, 3, 1]
    assert order(["K", "N"], rows, {"column": "N"}, {"column": "K"})[0] == [2, 1, 0, 3]


def test_a_heading_the_table_does_not_have_is_a_warning_and_that_key_is_skipped():
    got, said = order(COLS, ROWS, {"column": "Nope"}, {"column": "Name"})

    assert got == [1, 0, 3, 2]
    assert said == ['The table has no column "Nope" to sort by, so that sort was ignored.']


def result_with(section: ReportSection, **kwargs: Any) -> ReportResult:
    from datetime import UTC, datetime

    return ReportResult("k", "T", "S", datetime.now(UTC), kwargs.pop("notes", []), [section], **kwargs)


def test_sorting_moves_the_cell_colours_with_their_rows():
    section = ReportSection("s", "S", ["Name", "N"], [["b", "2"], ["a", "1"]], tones=[["danger", None], [None, "info"]])
    part = WidgetPart("s", "S", "", "section")

    (table,) = part_blocks(result_with(section), part, [{"column": "Name"}])

    assert table.rows == [["a", "1"], ["b", "2"]] and table.tones == [[None, "info"], ["danger", None]]
    assert section.rows == [["b", "2"], ["a", "1"]]  # the report's own rows are untouched


def test_the_figures_can_be_sorted_and_the_notes_cannot():
    from app.services.report_framework import ReportMetric

    said: list[str] = []
    figures = WidgetPart("figures", "F", "", "figures")
    notes = WidgetPart("notes", "N", "", "notes")
    result = result_with(ReportSection("s", "S", ["X"], [["1"]]), metrics=[ReportMetric("B", 2), ReportMetric("A", 9)], notes=["n"])

    (table,) = part_blocks(result, figures, [{"column": "Measure"}], said.append)
    blocks = part_blocks(result, notes, [{"column": "Measure"}], said.append)

    assert table.rows == [["A", "9"], ["B", "2"]]
    assert blocks == [Note("n")] and said == ["The notes are not a table, so the sort was ignored."]


def test_a_widget_block_sorts_its_table_in_a_layout_run(db, world, monkeypatch):
    project = world.project("Alpha")
    section = ReportSection("matrix", "Matrix", ["Type", "Open"], [["beta", "3"], ["Alpha", "12"], ["gamma", "2"]])
    monkeypatch.setattr(report_layout_eval, "collect_widget", lambda db_, widget_, ctx: result_with(section))
    node = {"type": "widget", "key": MATRIX, "sort": [{"column": "Open", "descending": True}]}

    result = run(db, world, project, doc(node))

    (table,) = (b for b in result.document.blocks if isinstance(b, Table))
    assert [r[0] for r in table.rows] == ["Alpha", "beta", "gamma"]
    node["sort"] = [{"column": "Missing"}]
    again = run(db, world, project, doc(node))
    assert any('no column "Missing"' in w for w in again.warnings)


def test_widget_sort_is_validated_and_written_as_text():
    def widget(sort: Any) -> dict[str, Any]:
        return doc({"type": "widget", "key": MATRIX, "sort": sort})

    assert validate_tree(widget([{"column": "Open", "descending": True}, {"column": "Type"}])).ok
    assert paths(widget([]))["nodes[0].sort"].startswith("Must be a list of 1 to 3 sort keys")
    assert paths(widget([{"column": "A"}] * 4))["nodes[0].sort"].startswith("Must be a list of 1 to 3 sort keys")
    assert paths(widget([{"column": ""}]))["nodes[0].sort[0].column"] == "Must not be empty."
    assert paths(widget([{"column": "A", "descending": "yes"}]))["nodes[0].sort[0].descending"] == "Must be true or false."
    assert paths(widget([{"colum": "A"}]))["nodes[0].sort[0].colum"] == "Unknown key."
    assert paths(widget("Open"))["nodes[0].sort"].startswith("Must be a list")

    tree = doc({
        "type": "widget", "key": MATRIX, "params": {},
    })
    del tree["nodes"][0]["params"]
    tree["nodes"][0].update(
        sort=[{"column": "Next review", "descending": False}, {"column": "asc"}, {"column": "Open", "descending": True}],
        empty_text="None.",
    )
    text = format_tree(tree)

    assert '[[widget.context_strategy.pain-point-coverage.matrix sort "Next review" asc sort asc sort Open desc empty "None."]]' in text
    assert parse_text(text).tree == tree


@pytest.mark.parametrize(
    ("clause", "message"),
    [("sort", "Sort needs a column heading"), ('sort "Open', "never closed"), ('sort "\\q"', "Not valid quoted text")],
)
def test_a_malformed_widget_sort_is_a_syntax_error(clause, message):
    result = parse_text(f"@layout document\n\n[[widget.{MATRIX} {clause}]]\n")

    assert result.tree is None and message in result.errors[0].message


def test_param_collision_free_sort_and_empty_clauses():
    """`sort` and `empty` are clauses, not parameters: a parameter is always `name=value`."""
    text = '@layout document\n\n[[widget.decisions.decision-register.register sort=1 sort Title empty "x"]]\n'

    result = parse_text(text)

    assert result.tree is not None
    node = result.tree["nodes"][0]
    assert node["params"] == {"sort": 1} and node["sort"] == [{"column": "Title"}] and node["empty_text"] == "x"
    assert any("no parameter 'sort'" in e.message for e in result.errors)  # the report has no such parameter: the validator says so


def test_all_the_combinations_of_two_tests_round_trip():
    for outer, inner in itertools.product(("all", "any"), repeat=2):
        cond = {outer: [A, {inner: [B, C]}]}
        tree = where(cond)
        assert parse_text(format_tree(tree)).tree == tree
        tree = where({"not": cond})
        assert parse_text(format_tree(tree)).tree == tree
        # reading it back never re-associates: the nested node stays nested
        assert parse_text(format_tree(tree)).tree["nodes"][0]["source"]["where"][0]["not"][outer][1] == {inner: [B, C]}


