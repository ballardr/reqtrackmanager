"""Tests for a layout's run-time variables that need no database (`services.report_variables`, the tree validator's
variable checks and the text view's `@var` / `$name` forms): declarations, references, value checking, binding,
and the round trip. The run, preview and queue behaviour is in `test_report_variables_run.py`.

Run with `pytest --noconftest` for speed; nothing here touches the database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import app.main  # noqa: F401  (registers the modules before the validator is used)
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import validate_tree
from app.services.report_variables import (
    VariableValueError,
    bind_variables,
    is_reference,
    resolve_values,
    variable_text,
)

REQ = "requirement"
TODAY = date(2026, 10, 27)


def tree(variables: list[dict[str, Any]] | None, *nodes: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": 1, "family": "document", "nodes": list(nodes)}
    if variables is not None:
        out["variables"] = variables
    return out


def table(*where: dict[str, Any]) -> dict[str, Any]:
    return {"type": "table", "source": {"record_type": REQ, "where": list(where)}, "columns": [{"field": "title"}]}


def messages(t: dict[str, Any]) -> list[str]:
    return [f"{e.path}: {e.message}" for e in validate_tree(t).errors]


CATEGORIES = {"name": "categories", "type": "enum", "multiple": True, "label": "Categories", "source": {"record_type": REQ, "field": "category"}}
SINCE = {"name": "since", "type": "date", "default": "today"}
LEVEL = {"name": "level", "type": "enum", "options": ["Must", "Should"], "default": "Must"}


# ---- declarations -----------------------------------------------------------------------------------------------


def test_a_layout_with_variables_used_everywhere_is_valid():
    t = tree(
        [CATEGORIES, SINCE, LEVEL],
        {"type": "heading", "text": "{{var.categories}} since {{var.since}}"},
        table(
            {"field": "category", "op": "in", "value": {"var": "categories"}},
            {"field": "review_date", "op": "gte", "value": {"var": "since"}},
            {"field": "level", "op": "eq", "value": {"var": "level"}},
        ),
    )
    assert messages(t) == []


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ({"name": "Bad Name", "type": "text"}, "lower-case letters"),
        ({"name": "x", "type": "colour"}, "Must be one of: text, number, date, bool, enum"),
        ({"name": "x", "type": "enum"}, "needs \"options\" or a \"source\""),
        ({"name": "x", "type": "text", "options": ["a"]}, 'Only an "enum" variable has options'),
        ({"name": "x", "type": "enum", "options": ["a"], "source": {"record_type": REQ, "field": "level"}}, "not both"),
        ({"name": "x", "type": "enum", "options": ["a", "a"]}, "1 to 100 different texts"),
        ({"name": "x", "type": "bool", "multiple": True}, "holds one value"),
        ({"name": "x", "type": "number", "default": "ten"}, "Must be a number"),
        ({"name": "x", "type": "date", "default": "27/10/2026"}, "YYYY-MM-DD"),
        ({"name": "x", "type": "enum", "options": ["a"], "default": "b"}, "one of the options"),
        ({"name": "x", "type": "text", "multiple": True, "default": "a"}, "list of 1 to"),
        ({"name": "x", "type": "number", "source": {"record_type": REQ, "field": "category"}}, "cannot take its values from"),
        ({"name": "x", "type": "enum", "source": {"record_type": REQ, "field": "nope"}}, "is not a field of requirement"),
        ({"name": "x", "type": "enum", "source": {"record_type": "nothing", "field": "x"}}, "reportable record type"),
        ({"name": "x", "type": "text", "colour": "red"}, "Unknown key"),
    ],
)
def test_a_bad_declaration_is_reported_where_it_is(declaration, expected):
    found = messages(tree([declaration]))
    assert any(expected in m and m.startswith("variables[0]") for m in found), found


def test_names_must_be_unique_and_the_list_not_empty_or_huge():
    assert any("already called" in m for m in messages(tree([{"name": "a", "type": "text"}, {"name": "a", "type": "text"}])))
    assert any("1 to 20 variables" in m for m in messages(tree([])))
    assert any("1 to 20 variables" in m for m in messages(tree([{"name": f"v{i}", "type": "text"} for i in range(21)])))


def test_a_date_default_may_be_today_and_a_list_default_a_list():
    ok = tree([SINCE, {"name": "l", "type": "text", "multiple": True, "default": ["a", "b"]}])
    assert messages(ok) == []


def test_var_is_not_available_as_a_block_name():
    t = tree(None, {"type": "each", "as": "var", "source": {"record_type": REQ}, "children": [{"type": "text", "text": "x"}]})
    assert any("reserved for variables" in m for m in messages(t))


# ---- references ---------------------------------------------------------------------------------------------------


def test_a_reference_must_name_a_declared_variable_that_fits_the_field():
    cases = {
        "undeclared": (table({"field": "category", "op": "eq", "value": {"var": "nope"}}), "not a variable of this layout"),
        "wrong type": (table({"field": "review_date", "op": "eq", "value": {"var": "level"}}), "is of type enum; this field is a date"),
        "list under eq": (table({"field": "category", "op": "eq", "value": {"var": "categories"}}), "only \"in\" and \"not_in\""),
        "single under in": (table({"field": "level", "op": "in", "value": {"var": "level"}}), "need a list variable"),
        "malformed": (table({"field": "category", "op": "eq", "value": {"var": "level", "extra": 1}}), 'written {"var"'),
    }
    for name, (node, expected) in cases.items():
        found = messages(tree([CATEGORIES, SINCE, LEVEL], node))
        assert any(expected in m for m in found), (name, found)


def test_text_placeholders_must_name_a_declared_variable():
    t = tree([LEVEL], {"type": "text", "text": "{{var.level}} {{var.missing}}"})
    found = messages(t)
    assert len(found) == 1 and found[0].startswith('nodes[0].text: "missing" is not a variable')


def test_an_if_can_use_a_variable_in_text_but_not_as_a_ref():
    t = tree([LEVEL], {"type": "if", "when": {"ref": "var.level", "op": "eq", "value": "Must"}, "children": [{"type": "text", "text": "x"}]})
    assert messages(t)  # `var` is not an enclosing block


def test_widget_parameters_can_be_bound_to_a_variable_of_the_right_type():
    ok = tree(
        [{"name": "since", "type": "date", "default": "today"}, {"name": "days", "type": "number", "default": 30}],
        {"type": "widget", "key": "stakeholders.engagement-yield.yield", "params": {"since": {"var": "since"}}},
        {"type": "widget", "key": "risk_management.review-schedule.overdue", "params": {"due_within_days": {"var": "days"}}},
    )
    assert messages(ok) == []
    wrong = tree(
        [{"name": "since", "type": "date", "default": "today"}],
        {"type": "widget", "key": "risk_management.review-schedule.overdue", "params": {"due_within_days": {"var": "since"}}},
    )
    assert any("is of type date; this parameter is a integer" in m for m in messages(wrong))
    listed = tree(
        [{"name": "d", "type": "number", "multiple": True, "default": [1]}],
        {"type": "widget", "key": "risk_management.review-schedule.overdue", "params": {"due_within_days": {"var": "d"}}},
    )
    assert any("holds a list" in m for m in messages(listed))


def test_a_variable_reference_is_recognised_only_in_its_exact_shape():
    assert is_reference({"var": "a"})
    assert not is_reference({"var": "a", "x": 1}) and not is_reference({"var": 1}) and not is_reference("a")


# ---- values ---------------------------------------------------------------------------------------------------------


def test_defaults_apply_and_today_is_the_callers_day():
    values = resolve_values([SINCE, LEVEL, CATEGORIES | {"default": ["A"]}], None, today=TODAY)
    assert values == {"since": "2026-10-27", "level": "Must", "categories": ["A"]}


def test_supplied_values_override_defaults_and_lists_lose_duplicates():
    values = resolve_values([CATEGORIES, SINCE], {"categories": ["A", "B", "A"], "since": "2026-01-02"}, today=TODAY)
    assert values == {"categories": ["A", "B"], "since": "2026-01-02"}


def test_a_whole_valued_number_becomes_an_int_so_it_can_feed_a_whole_number_parameter():
    assert resolve_values([{"name": "n", "type": "number"}], {"n": 30.0}, today=TODAY) == {"n": 30}
    assert resolve_values([{"name": "n", "type": "number"}], {"n": 2.5}, today=TODAY) == {"n": 2.5}


@pytest.mark.parametrize(
    ("declaration", "supplied", "expected"),
    [
        (CATEGORIES, {}, "Needs a value"),
        (CATEGORIES, {"categories": "A"}, "Choose 1 to 20 values"),
        (CATEGORIES, {"categories": []}, "Choose 1 to 20 values"),
        (CATEGORIES, {"categories": ["A"] * 0 + [str(i) for i in range(21)]}, "Choose 1 to 20 values"),
        (LEVEL, {"level": ["Must"]}, "one value, not a list"),
        (LEVEL, {"level": "Could"}, "Must be one of: Must, Should"),
        (SINCE, {"since": "yesterday"}, "YYYY-MM-DD"),
        ({"name": "n", "type": "number"}, {"n": True}, "Must be a number"),
        ({"name": "n", "type": "number"}, {"n": float("inf")}, "Must be a number"),
        ({"name": "b", "type": "bool"}, {"b": "yes"}, "true or false"),
        ({"name": "t", "type": "text"}, {"t": " "}, "1 to 200 characters"),
        ({"name": "t", "type": "text"}, {"t": "x" * 201}, "1 to 200 characters"),
    ],
)
def test_unacceptable_values_are_refused_with_the_variable_named(declaration, supplied, expected):
    with pytest.raises(VariableValueError) as caught:
        resolve_values([declaration], supplied, today=TODAY)
    assert any(name == declaration["name"] and expected in message for name, message in caught.value.problems)


def test_an_undeclared_value_is_refused_and_every_problem_is_listed():
    with pytest.raises(VariableValueError) as caught:
        resolve_values([CATEGORIES, LEVEL], {"ghost": 1, "level": "Could"}, today=TODAY)
    names = [name for name, _ in caught.value.problems]
    assert sorted(names) == ["categories", "ghost", "level"]


def test_a_layout_with_no_variables_refuses_supplied_values():
    with pytest.raises(VariableValueError):
        resolve_values(None, {"x": 1}, today=TODAY)
    assert resolve_values(None, None, today=TODAY) == {}


# ---- binding and text ---------------------------------------------------------------------------------------------


def test_binding_replaces_references_with_literals_in_a_copy():
    t = tree(
        [CATEGORIES, LEVEL],
        table({"field": "category", "op": "in", "value": {"var": "categories"}}, {"field": "level", "op": "eq", "value": {"var": "level"}}),
        {"type": "widget", "key": "risk_management.review-schedule.overdue", "params": {"due_within_days": {"var": "n"}}},
    )
    bound = bind_variables(t, {"categories": ["A", "B"], "level": "Must", "n": 7})
    where = bound["nodes"][0]["source"]["where"]
    assert where == [{"field": "category", "op": "in", "value": ["A", "B"]}, {"field": "level", "op": "eq", "value": "Must"}]
    assert bound["nodes"][1]["params"] == {"due_within_days": 7}
    assert t["nodes"][0]["source"]["where"][0]["value"] == {"var": "categories"}  # the original is untouched
    assert bound["variables"] == t["variables"]
    bound["nodes"][0]["source"]["where"][0]["value"].append("C")
    assert bind_variables(t, {"categories": ["A"], "level": "x", "n": 1})["nodes"][0]["source"]["where"][0]["value"] == ["A"]


def test_text_for_a_placeholder_joins_lists_and_prints_flags_and_dates_plainly():
    declared = [CATEGORIES, {"name": "flag", "type": "bool"}, SINCE]
    text = variable_text(declared, {"categories": ["A", "B"], "flag": True, "since": "2026-10-27"})
    assert text == {"categories": "A, B", "flag": "Yes", "since": "2026-10-27"}


# ---- text view ------------------------------------------------------------------------------------------------------

TEXT = """@layout document
@var categories enum list label "Categories" from requirement.category
@var since date default today
@var level enum default Must options "Must", "Should"
@var tags text list default "a b", c, 3
@var cap number default 2.5
@var on bool default true

@heading {{var.level}} for {{var.categories}}

@table requirement where category in $categories and review_date gte $since and level eq $level
  @column title
@end

[[widget.risk_management.review-schedule.overdue due_within_days=$cap]]
"""


def test_the_text_view_round_trips_variables_and_references():
    parsed = parse_text(TEXT)
    assert parsed.errors == [] or all("tags" not in e.message and "due_within_days" not in e.message for e in parsed.errors)
    assert parsed.tree is not None
    # Only the declarations and the references are of interest; the widget parameter type is checked by the validator.
    variables = parsed.tree["variables"]
    assert [v["name"] for v in variables] == ["categories", "since", "level", "tags", "cap", "on"]
    assert variables[3]["default"] == ["a b", "c", 3]
    where = parsed.tree["nodes"][1]["source"]["where"][0]
    assert where == {"all": [
        {"field": "category", "op": "in", "value": {"var": "categories"}},
        {"field": "review_date", "op": "gte", "value": {"var": "since"}},
        {"field": "level", "op": "eq", "value": {"var": "level"}},
    ]}
    assert parsed.tree["nodes"][2]["params"] == {"due_within_days": {"var": "cap"}}


def test_a_valid_layout_with_variables_formats_and_parses_back_exactly():
    t = tree(
        [CATEGORIES, SINCE, LEVEL, {"name": "n", "type": "number", "default": 30}],
        {"type": "heading", "text": "{{var.level}}"},
        table({"field": "category", "op": "in", "value": {"var": "categories"}}, {"field": "title", "op": "eq", "value": "$notavar"}),
        {"type": "widget", "key": "risk_management.review-schedule.overdue", "params": {"due_within_days": {"var": "n"}}},
    )
    assert messages(t) == []
    text = format_tree(t)
    assert '"$notavar"' in text  # a literal that looks like a reference is quoted
    assert parse_text(text).tree == t


def test_the_text_view_reports_variable_mistakes_at_their_line():
    result = parse_text('@layout document\n@var a text\n@var a text\n@heading {{var.zz}}\n')
    assert {e.line for e in result.errors} == {3, 4}
    assert parse_text("@layout document\n@heading x\n@var a text\n").errors[0].line == 3
    bad = parse_text("@layout document\n@var a colour\n").errors
    assert bad and bad[0].line == 2
    assert parse_text("@layout document\n@var a text bogus\n").errors[0].message.startswith("Unexpected")
    assert "given twice" in parse_text('@layout document\n@var a text label "x" label "y"\n').errors[0].message
    assert "record type" in parse_text("@layout document\n@var a enum from category\n").errors[0].message


def test_a_variable_cannot_share_a_list_with_other_values_in_the_text_view():
    src = "@layout document\n@var c enum list options \"A\"\n@table requirement where category in $c, B\n  @column title\n@end\n"
    assert "whole list" in parse_text(src).errors[0].message
    assert "$name" in parse_text("@layout document\n@table requirement where title eq $Bad\n  @column title\n@end\n").errors[0].message
