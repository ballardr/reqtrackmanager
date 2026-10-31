"""Tests for the layout tree vocabulary and validator (`services.report_layout_tree`).

Pure validation against the report field registry: shape, positioned errors, caps, record types and
fields, operators and values per field kind, aliases in scope, placeholders, the field references the
evaluator loads, and the tree hash. No database is touched.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.services import report_layout_tree as tree_module
from app.services.report_layout_tree import (
    MAX_DEPTH,
    MAX_NODES,
    InvalidLayoutError,
    assert_valid,
    empty_tree,
    tree_hash,
    validate_tree,
)

REQ = "requirement"
PAIN = "pain_point"


def doc(*nodes: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "family": "document", "nodes": list(nodes), **extra}


def sheets(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "family": "table", "nodes": list(nodes)}


def errors(tree: Any, **kwargs: Any) -> dict[str, str]:
    """`{path: message}` of the problems found."""
    return {e.path: e.message for e in validate_tree(tree, **kwargs).errors}


def example() -> dict[str, Any]:
    """Requirements by component and category, their linked Pain Points, and those Pain Points' Stakeholders."""
    return doc(
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
                                            "type": "table",
                                            "source": {"record_type": "stakeholder", "linked_from": "pain"},
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


# --- valid trees ------------------------------------------------------------------------------


def test_the_example_layout_is_valid_and_reports_the_fields_each_block_needs():
    tree = example()
    analysis = validate_tree(tree, family="document")

    assert analysis.errors == []
    group = tree["nodes"][1]
    assert {("requirement", "component"), ("requirement", "category"), ("requirement", "title"), ("requirement", "code")} <= analysis.refs[id(group)]
    assert ("stakeholder", "role") in analysis.refs[id(group)]
    pain_each = group["children"][1]["children"][1]["children"][1]
    assert ("pain_point", "title") in analysis.refs[id(pain_each)]
    # A requirement field is not asked of the Pain Point block's own subtree.
    assert ("requirement", "component") not in analysis.refs[id(pain_each)]


def test_an_empty_tree_is_valid_for_both_families():
    assert validate_tree(empty_tree("document")).ok and validate_tree(empty_tree("table")).ok


def test_the_table_family_takes_sheets():
    tree = sheets({"type": "sheet", "name": "Requirements", "source": {"record_type": REQ}, "columns": [{"field": "code"}, {"field": "title"}]})
    assert validate_tree(tree, family="table").ok


def test_every_literal_kind_validates():
    where = [
        {"field": "title", "op": "contains", "value": "slow"},
        {"field": "status", "op": "in", "value": ["Draft", "Approved"]},
        {"field": "review_date", "op": "lt", "value": "2026-10-26"},
        {"field": "is_completed", "op": "eq", "value": False},
        {"field": "completed_at", "op": "gte", "value": "2026-10-26T09:00:00Z"},
        {"field": "owner", "op": "not_empty"},
    ]
    tree = doc({"type": "table", "source": {"record_type": REQ, "where": where}, "columns": [{"field": "title"}]})
    assert errors(tree) == {}


# --- shape ------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, [], "text", 3])
def test_a_tree_must_be_an_object(bad):
    assert errors(bad) == {"": "The layout must be an object."}


def test_unserialisable_content_is_refused():
    assert "plain JSON" in errors({"schema_version": 1, "family": "document", "nodes": [object()]})[""]


def test_an_unknown_key_is_an_error_not_ignored():
    found = errors(doc({"type": "heading", "text": "x", "colour": "red"}))
    assert found == {"nodes[0].colour": "Unknown key."}


def test_missing_required_keys_are_named():
    found = errors({"family": "document"})
    assert found["nodes"] == "Required." and "schema_version" in found


def test_the_schema_version_must_be_current():
    tree = doc()
    tree["schema_version"] = 2
    assert errors(tree) == {"schema_version": "Must be 1."}


def test_an_unknown_block_type_lists_the_known_ones():
    found = errors(doc({"type": "script", "text": "x"}))
    assert "Unknown block type 'script'" in found["nodes[0].type"] and "heading" in found["nodes[0].type"]


def test_a_block_of_the_wrong_family_is_refused():
    assert "cannot be used in a table layout" in errors(sheets({"type": "heading", "text": "x"}))["nodes[0].type"]
    assert "cannot be used in a document layout" in errors(doc({"type": "sheet", "name": "S", "source": {}, "columns": []}))["nodes[0].type"]


def test_the_declared_family_must_match_the_layout():
    assert errors(doc(), family="table") == {"family": "This layout is a table layout; the tree says document."}


def test_orientation_is_for_documents_only_and_must_be_known():
    assert errors(doc(orientation="sideways")) == {"orientation": "Must be one of: portrait, landscape."}
    assert errors({**sheets(), "orientation": "landscape"}) == {"orientation": "Only a document layout has a page orientation."}
    assert validate_tree(doc(orientation="landscape")).ok


def test_a_raw_html_block_does_not_exist():
    assert "nodes[0].type" in errors(doc({"type": "html", "html": "<script>alert(1)</script>"}))


# --- caps -------------------------------------------------------------------------------------


def test_nesting_deeper_than_the_cap_is_refused():
    node: dict[str, Any] = {"type": "heading", "text": "deep"}
    for _ in range(MAX_DEPTH):
        node = {"type": "if", "when": {"ref": "x.y", "op": "empty"}, "children": [node]}
    found = errors(doc(node))
    assert any("nested too deeply" in message for message in found.values())


def test_the_block_count_is_capped():
    tree = doc(*({"type": "page_break"} for _ in range(MAX_NODES + 5)))
    found = errors(tree)
    assert sum("too many blocks" in m for m in found.values()) == 1


def test_a_huge_layout_is_refused_before_it_is_walked(monkeypatch):
    monkeypatch.setattr(tree_module, "MAX_TREE_BYTES", 100)
    assert "too large" in errors(doc({"type": "text", "text": "x" * 500}))[""]


def test_the_error_list_is_bounded():
    tree = doc(*({"type": "nope"} for _ in range(200)))
    assert len(validate_tree(tree).errors) == tree_module.MAX_ERRORS


def test_text_length_is_capped():
    assert "Too long" in errors(doc({"type": "heading", "text": "x" * 501}))["nodes[0].text"]
    assert "Must not be empty" in errors(doc({"type": "text", "text": "  "}))["nodes[0].text"]


# --- sources, fields and conditions -----------------------------------------------------------


def test_an_unknown_record_type_lists_the_reportable_ones():
    found = errors(doc({"type": "table", "source": {"record_type": "unicorn"}, "columns": [{"field": "title"}]}))
    assert "reportable record type" in found["nodes[0].source.record_type"] and "requirement" in found["nodes[0].source.record_type"]


def test_an_unknown_field_is_named_with_the_type_it_was_asked_of():
    found = errors(doc({"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "password_hash"}]}))
    assert '"password_hash" is not a field of requirement' in found["nodes[0].columns[0].field"]


def test_a_source_is_exactly_one_form():
    both = errors(doc({
        "type": "each", "source": {"record_type": REQ}, "as": "r",
        "children": [{"type": "table", "source": {"group": "r", "record_type": REQ}, "columns": [{"field": "title"}]}],
    }))
    assert "nodes[0].children[0].source.group" in both  # "r" is a record, not a group
    assert "nodes[0].children[0].source.record_type" in both  # not allowed with "group"


def test_link_options_need_linked_from():
    source = {"record_type": PAIN, "link_types": ["Raises"], "direction": "both"}
    found = errors(doc({"type": "table", "source": source, "columns": [{"field": "title"}]}))
    assert set(found) == {"nodes[0].source.link_types", "nodes[0].source.direction"}


def test_linked_from_must_name_an_enclosing_record():
    found = errors(doc({"type": "table", "source": {"record_type": PAIN, "linked_from": "req"}, "columns": [{"field": "title"}]}))
    assert "not the name of an enclosing block" in found["nodes[0].source.linked_from"]


def test_link_type_names_and_direction_are_checked():
    source = {"record_type": PAIN, "linked_from": "record", "link_types": [3], "direction": "up"}
    inner = {"type": "table", "source": source, "columns": [{"field": "title"}]}
    found = errors(doc({"type": "each", "source": {"record_type": REQ}, "children": [inner]}))
    assert set(found) == {"nodes[0].children[0].source.link_types", "nodes[0].children[0].source.direction"}


@pytest.mark.parametrize(("cond", "path"), [
    ({"field": "title", "op": "gt", "value": "a"}, "op"),                         # text has no ordering
    ({"field": "is_completed", "op": "contains", "value": True}, "op"),
    ({"field": "completed_at", "op": "eq", "value": "2026-10-26T00:00:00Z"}, "op"),  # instants only compare by order
    ({"field": "title", "op": "empty", "value": "x"}, "value"),                   # empty takes no value
    ({"field": "title", "op": "eq"}, "value"),                                    # eq needs one
    ({"field": "review_date", "op": "lt", "value": "26/10/2026"}, "value"),
    ({"field": "review_date", "op": "lt", "value": "2026-13-40"}, "value"),
    ({"field": "completed_at", "op": "lt", "value": "2026-10-26T09:00:00"}, "value"),  # no zone
    ({"field": "is_completed", "op": "eq", "value": "yes"}, "value"),
    ({"field": "status", "op": "in", "value": "Draft"}, "value"),
    ({"field": "title", "op": "eq", "value": "x" * 201}, "value"),
])
def test_a_condition_must_suit_its_field(cond, path):
    found = errors(doc({"type": "table", "source": {"record_type": REQ, "where": [cond]}, "columns": [{"field": "title"}]}))
    assert list(found) == [f"nodes[0].source.where[0].{path}"]


def test_where_and_sort_and_column_counts_are_capped():
    source = {"record_type": REQ, "where": [{"field": "title", "op": "empty"}] * 11, "sort": [{"field": "title"}] * 4}
    found = errors(doc({"type": "table", "source": source, "columns": [{"field": "title"}] * 31}))
    assert set(found) == {"nodes[0].source.where", "nodes[0].source.sort", "nodes[0].columns"}


def test_a_group_must_be_grouped_by_a_real_field():
    found = errors(doc({"type": "group", "source": {"record_type": REQ}, "by": "nope", "children": []}))
    assert list(found) == ["nodes[0].by"]


# --- aliases and placeholders -----------------------------------------------------------------


def test_a_nested_block_must_not_reuse_an_enclosing_name():
    inner = {"type": "each", "source": {"record_type": PAIN}, "children": []}
    found = errors(doc({"type": "each", "source": {"record_type": REQ}, "children": [inner]}))
    assert 'The name "record" is already used' in found["nodes[0].children[0]"]


def test_siblings_may_share_a_name():
    each = {"type": "each", "source": {"record_type": REQ}, "children": [{"type": "text", "text": "{{record.title}}"}]}
    assert errors(doc(each, copy.deepcopy(each))) == {}


@pytest.mark.parametrize("alias", ["Req", "1req", "re q", "a" * 33, ""])
def test_an_alias_must_be_a_plain_name(alias):
    found = errors(doc({"type": "each", "source": {"record_type": REQ}, "as": alias, "children": []}))
    assert list(found) == ["nodes[0].as"]


def test_a_placeholder_outside_its_block_is_refused():
    each = {"type": "each", "source": {"record_type": REQ}, "as": "req", "children": []}
    found = errors(doc(each, {"type": "text", "text": "{{req.title}}"}))
    assert "not the name of an enclosing block" in found["nodes[1].text"]


def test_placeholders_name_real_fields_and_known_globals():
    each = {"type": "each", "source": {"record_type": REQ}, "children": [
        {"type": "text", "text": "{{record.nope}} and {{record.title}}"},
        {"type": "text", "text": "{{mystery}}"},
    ]}
    found = errors(doc(each))
    assert '"nope" is not a field of requirement' in found["nodes[0].children[0].text"]
    assert 'Unknown placeholder "{{mystery}}"' in found["nodes[0].children[1].text"]


def test_text_that_only_looks_like_a_placeholder_stays_literal():
    # Not the `{{name}}` / `{{alias.field}}` shape, so it is plain text (maths, code samples).
    assert errors(doc({"type": "text", "text": "{{ 1 + 1 }} and {{a.b.c}} and {x}"})) == {}


def test_a_group_has_only_value_and_count():
    group = {"type": "group", "source": {"record_type": REQ}, "by": "title", "as": "g", "children": [
        {"type": "text", "text": "{{g.value}} {{g.count}} {{g.title}}"},
    ]}
    found = errors(doc(group))
    assert list(found) == ["nodes[0].children[0].text"] and 'has "value" and "count"' in found["nodes[0].children[0].text"]


def test_an_if_checks_its_reference_and_operator():
    each = {"type": "each", "source": {"record_type": REQ}, "children": [
        {"type": "if", "when": {"ref": "record.title", "op": "contains", "value": "x"}, "children": [], "else_children": []},
        {"type": "if", "when": {"ref": "record", "op": "empty"}, "children": []},
        {"type": "if", "when": {"ref": "record.is_completed", "op": "gt", "value": 1}, "children": []},
    ]}
    found = errors(doc(each))
    assert set(found) == {"nodes[0].children[1].when.ref", "nodes[0].children[2].when.op"}


def test_an_if_may_test_a_groups_count():
    group = {"type": "group", "source": {"record_type": REQ}, "by": "title", "as": "g", "children": [
        {"type": "if", "when": {"ref": "g.count", "op": "gt", "value": 1}, "children": []},
    ]}
    assert errors(doc(group)) == {}


# --- sheets -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a/b", "a[1]", "a:b", "'quoted", "x" * 32, " "])
def test_a_sheet_name_must_be_a_legal_tab_name(name):
    sheet = {"type": "sheet", "name": name, "source": {"record_type": REQ}, "columns": [{"field": "title"}]}
    assert list(errors(sheets(sheet))) == ["nodes[0].name"]


def test_sheet_names_are_unique_ignoring_case():
    sheet = {"type": "sheet", "name": "Reqs", "source": {"record_type": REQ}, "columns": [{"field": "title"}]}
    again = {**sheet, "name": "REQS"}
    assert list(errors(sheets(sheet, again))) == ["nodes[1].name"]


def test_a_sheet_source_cannot_be_linked_because_nothing_encloses_it():
    sheet = {"type": "sheet", "name": "S", "source": {"record_type": PAIN, "linked_from": "record"}, "columns": [{"field": "title"}]}
    assert list(errors(sheets(sheet))) == ["nodes[0].source.linked_from"]


def joined_sheet(**overrides: Any) -> dict[str, Any]:
    sheet = {
        "type": "sheet", "name": "Impact", "source": {"record_type": REQ}, "as": "req",
        "joins": [
            {"as": "pain", "source": {"record_type": PAIN, "linked_from": "req"}},
            {"as": "who", "source": {"record_type": "stakeholder", "linked_from": "pain", "sort": [{"field": "title"}]}},
        ],
        "columns": [{"field": "code"}, {"field": "title", "from": "pain", "label": "Pain point"}, {"field": "role", "from": "who"}],
    }
    return sheets({**sheet, **overrides})


def test_a_sheet_may_join_along_links_and_read_columns_from_each_record():
    tree = joined_sheet()
    analysis = validate_tree(tree, family="table")
    assert analysis.errors == []
    sheet = tree["nodes"][0]
    # The join's own fields and the columns reading from it are attributed to it.
    assert ("stakeholder", "role") in analysis.refs[id(sheet["joins"][1])]
    assert ("pain_point", "title") in analysis.refs[id(sheet["joins"][0])]


def test_a_join_must_follow_a_link_from_an_earlier_name():
    bad_source = joined_sheet(joins=[{"as": "pain", "source": {"record_type": PAIN}}])
    assert "nodes[0].joins[0].source.linked_from" in errors(bad_source)
    forward_reference = joined_sheet(joins=[
        {"as": "who", "source": {"record_type": "stakeholder", "linked_from": "pain"}},
        {"as": "pain", "source": {"record_type": PAIN, "linked_from": "req"}},
    ])
    assert "not the name of an enclosing block" in errors(forward_reference)["nodes[0].joins[0].source.linked_from"]


def test_join_names_are_unique_and_columns_must_name_a_known_join():
    clash = joined_sheet(joins=[{"as": "req", "source": {"record_type": PAIN, "linked_from": "req"}}])
    assert 'The name "req" is already used' in errors(clash)["nodes[0].joins[0].as"]
    unknown = joined_sheet(columns=[{"field": "title", "from": "nope"}])
    assert list(errors(unknown)) == ["nodes[0].columns[0].from"]
    wrong_field = joined_sheet(columns=[{"field": "component", "from": "pain"}])  # a requirement field on a Pain Point
    assert list(errors(wrong_field)) == ["nodes[0].columns[0].field"]


def test_joins_are_capped_and_a_column_can_only_read_from_a_name_in_its_sheet():
    many = joined_sheet(joins=[{"as": f"j{i}", "source": {"record_type": PAIN, "linked_from": "req"}} for i in range(6)])
    assert "nodes[0].joins" in errors(many)
    plain = sheets({"type": "sheet", "name": "S", "source": {"record_type": REQ}, "columns": [{"field": "title", "from": "x"}]})
    assert list(errors(plain)) == ["nodes[0].columns[0].from"]  # only the sheet's own name ("record") exists


# --- hash and helpers -------------------------------------------------------------------------


def test_the_hash_ignores_key_order_and_notices_content():
    a = doc({"type": "heading", "text": "x", "level": 1})
    b = {"nodes": [{"level": 1, "text": "x", "type": "heading"}], "family": "document", "schema_version": 1}
    assert tree_hash(a) == tree_hash(b)
    assert tree_hash(a) != tree_hash(doc({"type": "heading", "text": "y", "level": 1}))
    assert len(tree_hash(a)) == 64


def test_assert_valid_raises_with_every_problem():
    with pytest.raises(InvalidLayoutError) as caught:
        assert_valid(doc({"type": "nope"}, {"type": "heading"}))
    assert len(caught.value.errors) == 2


def test_another_feature_can_add_a_block_type_once_and_only_once():
    spec = tree_module.BlockSpec("probe", ("document",), lambda v, node, path: v.check_keys(node, path, required=("type",)))
    tree_module.register_block_spec(spec)
    try:
        assert validate_tree(doc({"type": "probe"})).ok
        with pytest.raises(ValueError):
            tree_module.register_block_spec(spec)
    finally:
        del tree_module.BLOCK_SPECS["probe"]


# ---- an `if` on a module ---------------------------------------------------------------------------------------


def test_an_if_may_test_that_a_module_is_available_and_a_made_up_module_is_refused():
    def tree(module: str) -> dict[str, Any]:
        return {
            **empty_tree("document"),
            "nodes": [{"type": "if", "when": {"module": module}, "children": [{"type": "text", "text": "x"}]}],
        }

    assert validate_tree(tree("risk_management")).errors == []
    errors = validate_tree(tree("no_such_module")).errors
    assert [e.path for e in errors] == ["nodes[0].when.module"]
    extra = {**empty_tree("document"), "nodes": [{"type": "if", "when": {"module": "risk_management", "op": "eq"}, "children": []}]}
    assert validate_tree(extra).errors, "an unknown key beside module is refused"


# --- sheet links and the contents sheet -------------------------------------------------------


def linking(link: Any = None, **overrides: Any) -> dict[str, Any]:
    """A table layout of a Requirements sheet and a Pain sheet whose Requirement column links to it."""
    requirements = {"type": "sheet", "name": "Requirements", "source": {"record_type": REQ}, "columns": [{"field": "code"}]}
    pain = {
        "type": "sheet", "name": "Pain", "source": {"record_type": PAIN}, "as": "pain",
        "joins": [{"as": "req", "source": {"record_type": REQ, "linked_from": "pain"}}],
        "columns": [{"field": "title"}, {"field": "code", "from": "req", "link": {"sheet": "Requirements"} if link is None else link}],
    }
    return {**sheets(requirements, pain), **overrides}


def test_a_column_can_link_to_a_sheet_that_lists_its_record_type():
    assert errors(linking()) == {}
    assert errors(linking({"sheet": "requirements"})) == {}  # names compare ignoring case


def test_a_link_may_name_a_sheet_written_after_it():
    tree = linking()
    tree["nodes"].reverse()
    assert errors(tree) == {}


def test_a_link_to_the_sheet_it_is_on_is_allowed():
    tree = sheets({
        "type": "sheet", "name": "Requirements", "source": {"record_type": REQ},
        "columns": [{"field": "code", "link": {"sheet": "Requirements"}}],
    })
    assert errors(tree) == {}


def test_a_link_to_a_missing_sheet_names_the_sheets():
    problems = errors(linking({"sheet": "Nope"}))
    assert list(problems) == ["nodes[1].columns[1].link.sheet"]
    message = problems["nodes[1].columns[1].link.sheet"]
    assert 'No sheet is called "Nope"' in message and "Requirements, Pain" in message


def test_a_link_to_a_sheet_of_another_record_type_is_refused_naming_both():
    problems = errors(linking({"sheet": "Pain"}))
    message = problems["nodes[1].columns[1].link.sheet"]
    assert 'Sheet "Pain" lists pain_point records, not requirement records' in message


@pytest.mark.parametrize("link", ["Requirements", {}, {"sheet": 5}, {"sheet": "Requirements", "row": 2}, {"sheet": ""}])
def test_a_link_must_be_an_object_with_one_sheet_name(link):
    assert any(path.startswith("nodes[1].columns[1].link") for path in errors(linking(link)))


def test_a_document_table_column_cannot_link():
    tree = doc({"type": "table", "source": {"record_type": REQ}, "columns": [{"field": "code", "link": {"sheet": "S"}}]})
    assert list(errors(tree)) == ["nodes[0].columns[0].link"]


def test_the_contents_sheet_is_for_table_layouts_and_a_flag():
    assert errors(linking(contents_sheet=True)) == {}
    assert errors(linking(contents_sheet=False)) == {}
    assert list(errors(linking(contents_sheet="yes"))) == ["contents_sheet"]
    assert list(errors(doc(contents_sheet=True))) == ["contents_sheet"]


def test_a_sheet_cannot_take_the_name_of_the_generated_contents_sheet():
    tree = linking(contents_sheet=True)
    tree["nodes"][1]["name"] = "contents"
    assert list(errors(tree)) == ["nodes[1].name"]
    tree["contents_sheet"] = False
    assert errors(tree) == {}
