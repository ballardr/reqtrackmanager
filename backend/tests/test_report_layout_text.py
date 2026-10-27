"""Tests for the layout text view (`services.report_layout_text`).

Covers the pinned text of the worked example, the guarantee that every valid tree reads back exactly
(a hand-made corpus of awkward trees plus seeded random ones), how text that looks like syntax is
written, positioned syntax errors, validator errors mapped to the block's line, hostile input
(size, depth, block count) and that every block type has a text form. No database is touched.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from app.services import report_layout_text as text_module
from app.services.report_layout_text import MAX_TEXT_VIEW_CHARS, TEXT_FORMS, TextForm, format_tree, parse_text, register_text_form
from app.services.report_layout_tree import BLOCK_SPECS, MAX_DEPTH, MAX_NODES, InvalidLayoutError, tree_hash, validate_tree
from tests.test_report_layout_tree import PAIN, REQ, doc, example, sheets

STAKEHOLDER = "stakeholder"


def roundtrip(tree: dict[str, Any]) -> str:
    """Asserts `tree` reads back exactly from its text, and returns the text."""
    assert validate_tree(tree).ok, validate_tree(tree).errors
    text = format_tree(tree)
    result = parse_text(text)
    assert result.errors == [], (text, result.errors)
    assert result.tree == tree, text
    assert tree_hash(result.tree) == tree_hash(tree)
    # and the text is a fixed point too: writing what was read gives the same text
    assert format_tree(result.tree) == text
    return text


def text_block(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def errors_of(text: str) -> list[tuple[int, int | None, str]]:
    return [(e.line, e.column, e.message) for e in parse_text(text).errors]


# --- the worked example -----------------------------------------------------------------------


def test_the_worked_example_has_a_readable_text_view():
    text = roundtrip(example())

    assert text.splitlines()[:12] == [
        "@layout document",
        "",
        "@heading {{report_title}} for {{project_name}}",
        "",
        "@group requirement by component as comp",
        "  @heading {{comp.value}} ({{comp.count}})",
        "",
        "  @group in comp by category as cat",
        "    @heading level=2 {{cat.value}}",
        "",
        "    @each in cat sort title as req",
        "      @heading level=3 {{req.code}} {{req.title}}",
    ]
    assert '@table stakeholder from pain empty "No stakeholders affected."' in text
    assert '      @column title "Stakeholder"' in text


def test_a_hand_written_layout_with_text_parses_into_the_same_tree_as_json():
    source = """\
@layout document landscape

@heading level=2 Findings for {{project_name}}

Some **bold** words,
over two lines.

@each requirement where status in draft, "in review" where is_completed eq false sort title desc as req
  @if req.owner not_empty
    Owned by {{req.owner}}.
  @else
    Nobody owns {{req.code}}.
  @end
@end
"""
    result = parse_text(source)

    assert result.ok, result.errors
    assert result.tree == doc(
        {"type": "heading", "level": 2, "text": "Findings for {{project_name}}"},
        text_block("Some **bold** words,\nover two lines."),
        {
            "type": "each", "as": "req",
            "source": {
                "record_type": REQ,
                "where": [{"field": "status", "op": "in", "value": ["draft", "in review"]}, {"field": "is_completed", "op": "eq", "value": False}],
                "sort": [{"field": "title", "descending": True}],
            },
            "children": [{
                "type": "if", "when": {"ref": "req.owner", "op": "not_empty"},
                "children": [text_block("Owned by {{req.owner}}.")],
                "else_children": [text_block("Nobody owns {{req.code}}.")],
            }],
        },
        orientation="landscape",
    )


def test_a_table_layout_reads_sheets_joins_and_columns():
    tree = sheets({
        "type": "sheet", "name": "Impact", "as": "req",
        "source": {"record_type": REQ, "where": [{"field": "code", "op": "contains", "value": "REQ"}]},
        "joins": [
            {"as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "link_types": ["Relates to"], "direction": "incoming"}},
            {"as": "who", "source": {"record_type": STAKEHOLDER, "linked_from": "pain"}},
        ],
        "columns": [{"field": "code"}, {"field": "title", "from": "pain", "label": "Pain point"}, {"field": "role", "from": "who"}],
    })

    text = roundtrip(tree)

    assert '@sheet "Impact" requirement where code contains REQ as req' in text
    assert '  @join pain_point from req via "Relates to" direction incoming as pain' in text
    assert '  @column pain.title "Pain point"' in text


# --- every valid tree reads back exactly --------------------------------------------------------

NASTY_TEXTS = [
    "plain",
    "two\nlines",
    "ends with newline\n",
    "\nstarts with newline",
    "line\n\n\nwith gaps",
    "@end",
    "@@end",
    "@",
    "  @indented directive-lookalike",
    "\t@tab then at",
    "@layout document",
    "text\n@end\nmore",
    "carriage\rreturn",
    "windows\r\nnewlines",
    "trailing spaces   \nand more  ",
    "x\n   \n   ",
    "a\n   \nb",
    "    code block\n        deeper",
    "[[widget.gap-analysis]]",
    "# not a heading in text view\n- list\n- list",
    'quotes " and \\ backslashes',
    "unicode — ünïcödé ✓ 日本語",
    "{{report_title}} and {{project_name}}",
    "  line separator",
]
NASTY_HEADINGS = [
    "plain", '"starts with a quote"', "level=3 looks like an attribute", "  padded  ", "has\nnewline", "tab\tinside", "trailing:",
    "@looks like a directive",
    'a "quote" mid', "{{report_title}}", "x" * 500,
]


@pytest.mark.parametrize("value", NASTY_TEXTS)
def test_any_text_value_reads_back_exactly(value):
    roundtrip(doc(text_block(value)))
    roundtrip(doc(text_block(value), text_block(value)))
    roundtrip(doc({"type": "each", "source": {"record_type": REQ}, "children": [text_block(value), {"type": "page_break"}, text_block(value)]}))


@pytest.mark.parametrize("value", NASTY_HEADINGS)
def test_any_heading_reads_back_exactly(value):
    roundtrip(doc({"type": "heading", "text": value}, {"type": "heading", "level": 4, "text": value}))


def test_adjacent_text_blocks_stay_separate_blocks():
    text = roundtrip(doc(text_block("first"), text_block("second"), text_block("third")))

    assert "@text" in text  # only the first can be plain lines


def test_keys_that_are_present_but_empty_survive():
    tree = doc(
        {"type": "heading", "level": 1, "text": "h"},
        {
            "type": "each", "as": "req", "source": {"record_type": REQ, "where": [], "sort": [], "include_archived": False},
            "children": [
                {"type": "each", "as": "pain", "source": {"record_type": PAIN, "linked_from": "req", "link_types": []}, "children": []},
                {"type": "if", "when": {"ref": "req.owner", "op": "empty"}, "children": [], "else_children": []},
            ],
        },
    )

    text = roundtrip(tree)

    assert "@each requirement archived false where none sort none as req" in text
    assert "@each pain_point from req via none as pain" in text
    assert "@else" in text


def test_sort_direction_keeps_its_three_states():
    sort = [{"field": "title"}, {"field": "code", "descending": False}, {"field": "status", "descending": True}]
    tree = doc({"type": "table", "source": {"record_type": REQ, "sort": sort}, "columns": [{"field": "title"}]})

    assert "sort title sort code asc sort status desc" in roundtrip(tree)


def test_sheet_with_an_empty_join_list_survives():
    roundtrip(sheets({"type": "sheet", "name": "S", "source": {"record_type": REQ}, "joins": [], "columns": [{"field": "title"}]}))


def test_condition_values_of_every_kind_read_back_with_their_type():
    tree = doc({
        "type": "each", "as": "r",
        "source": {"record_type": REQ, "where": [
            {"field": "title", "op": "eq", "value": "true"},
            {"field": "title", "op": "ne", "value": "123"},
            {"field": "title", "op": "contains", "value": "has space, and comma"},
            {"field": "is_completed", "op": "eq", "value": True},
            {"field": "review_date", "op": "gte", "value": "2026-10-26"},
            {"field": "completed_at", "op": "lt", "value": "2026-10-26T09:00:00Z"},
            {"field": "status", "op": "in", "value": ["draft", "in review", "123", "true"]},
            {"field": "title", "op": "eq", "value": ""},
        ]},
        "children": [],
    })

    roundtrip(tree)


def test_numbers_read_back_as_int_or_float():
    # a number field is not in the requirement catalogue, so exercise the literal grammar directly
    cur = text_module._cursor("5, 5.0, -2, 1e+22, 007, true, \"5\"", 0, 40)
    values = cur.comma_list(lambda: cur.value("a value"))

    assert values == [5, 5.0, -2, 1e22, "007", True, "5"]
    assert [type(v) for v in values[:2]] == [int, float]


def _random_tree(rng: random.Random) -> dict[str, Any]:
    """A valid tree built from random parts."""
    def literal() -> str:
        return rng.choice(["draft", "in review", "x y", "", "has, comma", '"q"', "true", "42", "2026-01-01", "ünï", "a\nb"])

    def source(parent: str | None, aliases: dict[str, str]) -> dict[str, Any]:
        src: dict[str, Any] = {"record_type": rng.choice([REQ, PAIN, STAKEHOLDER])}
        if parent:
            src["linked_from"] = parent
            if rng.random() < 0.5:
                src["link_types"] = rng.choice([[], ["Relates to"], ["a", "b c"]])
            if rng.random() < 0.3:
                src["direction"] = rng.choice(["both", "incoming", "outgoing"])
        if rng.random() < 0.3:
            src["include_archived"] = rng.random() < 0.5
        if rng.random() < 0.6:
            src["where"] = [
                rng.choice([
                    {"field": "title", "op": rng.choice(["eq", "ne", "contains"]), "value": literal()},
                    {"field": "code", "op": rng.choice(["empty", "not_empty"])},
                    {"field": "status", "op": "in", "value": [literal() for _ in range(rng.randint(1, 3))]},
                ])
                for _ in range(rng.randint(0, 3))
            ]
        if rng.random() < 0.6:
            src["sort"] = [
                {"field": rng.choice(["code", "title"]), **({"descending": rng.random() < 0.5} if rng.random() < 0.7 else {})}
                for _ in range(rng.randint(0, 2))
            ]
        return src

    def block(depth: int, aliases: dict[str, str]) -> dict[str, Any]:
        choices = ["heading", "text", "text", "page_break", "table"] + (["each", "group", "if"] if depth < 4 and aliases is not None else [])
        kind = rng.choice(choices)
        if kind == "heading":
            node: dict[str, Any] = {"type": "heading", "text": rng.choice(NASTY_HEADINGS)}
            if rng.random() < 0.5:
                node["level"] = rng.randint(1, 4)
            return node
        if kind == "text":
            return text_block(rng.choice([t for t in NASTY_TEXTS if t.strip()]))
        if kind == "page_break":
            return {"type": "page_break"}
        records = [a for a, k in aliases.items() if k == "record"]
        parent = rng.choice(records) if records and rng.random() < 0.7 else None
        if kind == "table":
            column: dict[str, Any] = {"field": "title"}
            if rng.random() < 0.5:
                column["label"] = rng.choice(["T", "a b", '"q"'])
            node = {"type": "table", "source": source(parent, aliases), "columns": [column]}
            if rng.random() < 0.5:
                node["empty_text"] = rng.choice(["None.", "", "a \"b\" c"]) or "None."
            return node
        if kind == "if":
            if not records:
                return text_block("plain")
            name = rng.choice(records)
            node = {
                "type": "if", "when": {"ref": f"{name}.title", "op": "eq", "value": literal()},
                "children": [block(depth + 1, aliases) for _ in range(rng.randint(0, 2))],
            }
            if rng.random() < 0.5:
                node["else_children"] = [block(depth + 1, aliases) for _ in range(rng.randint(0, 2))]
            return node
        alias = f"a{depth}{rng.randint(0, 99)}"
        while alias in aliases:
            alias += "x"
        inner = {**aliases, alias: "group" if kind == "group" else "record"}
        src = source(parent, aliases)
        node = {"type": kind, "source": src, "children": [block(depth + 1, inner) for _ in range(rng.randint(0, 3))]}
        if kind == "group":
            node["by"] = rng.choice(["title", "code", "status"])
            src.pop("sort", None)
            src.pop("where", None) if rng.random() < 0.5 else None
        if rng.random() < 0.8:
            node["as"] = alias
        else:  # the default name must be free
            node["children"] = [c for c in node["children"] if c["type"] in ("heading", "text", "page_break")]
        if rng.random() < 0.3 and kind == "each":
            node["empty_text"] = "Nothing."
        return node

    tree = doc(*[block(1, {}) for _ in range(rng.randint(0, 6))])
    if rng.random() < 0.5:
        tree["orientation"] = rng.choice(["portrait", "landscape"])
    return tree


@pytest.mark.parametrize("seed", range(150))
def test_random_valid_trees_read_back_exactly(seed):
    tree = _random_tree(random.Random(seed))
    roundtrip(tree)


def test_the_random_generator_produces_enough_valid_trees_to_mean_something():
    valid = [_random_tree(random.Random(s)) for s in range(150)]

    assert any(n["type"] == "if" for t in valid for n in _walk(t["nodes"]))
    assert any(n["type"] == "group" for t in valid for n in _walk(t["nodes"]))


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        yield from _walk(node.get("children", []))
        yield from _walk(node.get("else_children", []))


def test_the_text_of_an_unchanged_layout_is_not_a_new_version():
    tree = example()

    assert tree_hash(parse_text(format_tree(tree)).tree) == tree_hash(tree)


def test_formatting_an_invalid_tree_is_refused():
    with pytest.raises(InvalidLayoutError):
        format_tree(doc({"type": "heading"}))


# --- how text is written ------------------------------------------------------------------------


def test_plain_lines_are_text_and_a_leading_at_sign_is_doubled():
    text = format_tree(doc(text_block("Hello\n@bob said\n@end")))

    assert text.splitlines() == ["@layout document", "", "Hello", "@@bob said", "@@end"]
    assert parse_text(text).tree["nodes"][0]["text"] == "Hello\n@bob said\n@end"


def test_text_inside_a_block_is_indented_with_it_and_extra_indentation_is_kept():
    tree = doc({"type": "each", "source": {"record_type": REQ}, "children": [text_block("a\n    indented\nb")]})

    text = format_tree(tree)

    assert text.splitlines()[3:6] == ["  a", "      indented", "  b"]
    assert parse_text(text).tree == tree


def test_a_text_block_that_cannot_be_plain_lines_uses_the_explicit_forms():
    assert format_tree(doc(text_block("\nx"))).splitlines()[2:5] == ["@text", "", "x"]
    assert format_tree(doc(text_block("a\rb"))).splitlines()[-1] == '@text "a\\rb"'


def test_a_hand_written_explicit_text_block_keeps_its_blank_edges():
    result = parse_text("@layout document\n@text\n\nbody\n\n@end\n")

    assert result.tree["nodes"] == [text_block("\nbody\n")]


def test_windows_line_endings_are_accepted():
    result = parse_text("@layout document\r\n\r\n@heading Hi\r\n\r\nTwo\r\nlines\r\n")

    assert result.ok and result.tree["nodes"] == [{"type": "heading", "text": "Hi"}, text_block("Two\nlines")]


# --- syntax errors are positioned ------------------------------------------------------------------


def test_the_layout_line_is_required_first():
    assert errors_of("@heading Hi\n")[0] == (1, 1, "A layout starts with @layout document or @layout table.")
    assert errors_of("")[0][0] == 1
    assert errors_of("@layout slides\n")[0][2].startswith("The layout must be a document or a table")


def test_an_unknown_directive_lists_the_known_ones():
    (line, column, message), *_ = errors_of("@layout document\n\n  @headin Hi\n")

    assert (line, column) == (3, 3)
    assert message.startswith("Unknown directive @headin. Use one of: ")
    assert "heading" in message and "sheet" in message


def test_each_syntax_mistake_points_at_its_column():
    cases = {
        '@each requirement where status eq\n@end': (2, "Expected a value."),
        '@each requirement where status eq "open\n@end': (2, "This quoted text is never closed."),
        "@each requirement wher title eq x\n@end": (2, "Unexpected wher. Expected one of: from, via, direction, archived, where, sort, as, empty."),
        "@each requirement empty \n@end": (2, "Expected the text to show when there are no records."),
        "@each requirement as a as b\n@end": (2, '"as" is given twice.'),
        "@each requirement by title\n@end": (2, '"by" is not used here. This block takes: from, via, direction, archived, where, sort, as, empty.'),
        "@each requirement where status eq a, b\n@end": (2, 'Only "in" and "not_in" take several values.'),
        "@each requirement where none where title eq x\n@end": (2, '"where none" cannot be combined with other where clauses.'),
        "@each\n@end": (2, "Expected a record type (for example requirement) or in <group name>."),
        "@page_break now": (2, "@page_break takes nothing after it."),
        "@heading level=x Hi": (2, "The level must be a number from 1 to 4."),
        '@text "never closed': (2, "Not valid quoted text (write \\\" for a quote and \\\\ for a backslash)."),
        "@text oops": (2, 'Write @text on its own line, then the text, then @end; or @text "quoted text".'),
        "@layout table": (2, "@layout can only be the first line."),
        "@else": (2, "@else belongs inside an @if, once."),
    }
    for body, (line, message) in cases.items():
        found = errors_of("@layout document\n" + body + "\n")
        assert found, body
        assert (found[0][0], found[0][2]) == (line, message), body
        assert found[0][1] is not None, body


def test_the_column_of_a_syntax_error_is_in_the_original_line():
    (line, column, _), *_ = errors_of("@layout document\n  @each requirement where status eq\n  @end\n")

    assert (line, column) == (2, 36)


def test_blocks_must_be_closed_and_closers_must_have_a_block():
    assert errors_of("@layout document\n@each requirement\n  Hi\n") == [(2, None, "This block is never closed with @end.")]
    assert errors_of("@layout document\n@text\nHi\n") == [(2, None, "This @text is never closed with @end.")]
    assert errors_of("@layout document\n@end\n") == [(2, 1, "@end has nothing to close.")]
    assert errors_of("@layout document\n@if r.title empty\n@else\n@else\n@end\n")[0][2] == "@else belongs inside an @if, once."


def test_an_error_in_a_block_line_does_not_unbalance_the_ends():
    found = errors_of("@layout document\n@each\n  Hi\n@end\n\n@heading ok\n")

    assert [(line, msg) for line, _, msg in found] == [(2, "Expected a record type (for example requirement) or in <group name>.")]


def test_several_syntax_errors_are_all_reported_in_line_order():
    found = errors_of("@layout document\n@bogus\n@page_break x\n@each\n@end\n")

    assert [line for line, _, _ in found] == [2, 3, 4]


def test_text_cannot_sit_inside_a_table_and_a_directive_cannot_sit_inside_text():
    in_table = errors_of("@layout document\n@table requirement\n  prose\n  @column title\n@end\n")
    in_text = errors_of("@layout document\n@text\n@heading x\n@end\n")

    assert in_table == [(3, None, "Inside @table use @column or @end, not text.")]
    assert in_text[0][0] == 3 and "must be written @@" in in_text[0][2]
    assert errors_of("@layout document\n@table requirement\n  @heading x\n@end\n")[0][2] == "Inside @table use @column, @end."


def test_a_join_is_only_for_sheets_and_none_cannot_be_mixed_with_joins():
    base = '@layout table\n@sheet "S" requirement\n'

    assert "Inside @table" in errors_of("@layout document\n@table requirement\n  @join pain_point from r as p\n@end\n")[0][2]
    assert "cannot follow" in errors_of(base + "  @joins none\n  @join pain_point from record as p\n@end\n")[0][2]
    assert "cannot follow" in errors_of(base + "  @join pain_point from record as p\n  @joins none\n@end\n")[0][2]
    assert errors_of(base + "  @column title\n@end\n") == []


# --- the validator's errors land on the block's line ------------------------------------------------------


def test_validator_errors_are_reported_at_the_line_of_the_block():
    source = """\
@layout document

@heading Fine

@each requirement as req
  @heading {{req.nope}}
  @table pain_point from req
    @column title
    @column bogus "Bad column"
  @end
@end
"""
    result = parse_text(source)

    assert result.tree is not None and not result.ok
    found = {(e.line, e.message.split(":")[0]) for e in result.errors}
    assert (6, "text") in found  # the heading, 6th line
    assert (9, "field") in found  # the second column's own line
    assert all(e.column is None for e in result.errors)
    assert any('"bogus" is not a field of pain_point' in e.message for e in result.errors)


def test_a_block_level_error_has_no_path_prefix_and_a_root_error_is_on_the_layout_line():
    unknown_type = parse_text("@layout document\n@each nonsense\n@end\n")
    table_in_doc = parse_text('@layout document\n@sheet "S" requirement\n  @column title\n@end\n')

    assert unknown_type.errors[0].line == 2 and unknown_type.errors[0].message.startswith("source.record_type: Must be a reportable record type")
    assert table_in_doc.errors[0].line == 2 and "cannot be used in a document layout" in table_in_doc.errors[0].message


def test_orientation_on_a_table_layout_is_a_validator_error_on_the_first_line():
    result = parse_text("@layout table landscape\n")

    assert [(e.line, e.message) for e in result.errors] == [(1, "orientation: Only a document layout has a page orientation.")]


# --- hostile input ------------------------------------------------------------------------------------


def test_text_over_the_size_limit_is_refused_before_parsing():
    result = parse_text("@layout document\n" + "x" * MAX_TEXT_VIEW_CHARS)

    assert result.tree is None and "too long" in result.errors[0].message


def test_nesting_is_capped_without_recursion():
    depth = MAX_DEPTH + 40
    source = "@layout document\n" + "".join("@if r.title empty\n" for _ in range(depth)) + "@end\n" * depth

    result = parse_text(source)

    assert result.tree is None
    assert "nested too deeply" in result.errors[0].message


def test_the_block_count_is_capped():
    source = "@layout document\n" + "@page_break\n" * (MAX_NODES + 50)

    result = parse_text(source)

    assert result.tree is None
    assert "too many blocks" in result.errors[-1].message


def test_a_flood_of_errors_stops_at_the_cap():
    result = parse_text("@layout document\n" + "@bogus\n" * 500)

    assert result.tree is None and len(result.errors) == 50


@pytest.mark.parametrize("hostile", ['"' * 5000, "\\" * 5000, "@" * 5000, "," * 5000, "a " * 20000, '"\\' * 3000])
def test_pathological_lines_finish_quickly_and_never_raise(hostile):
    for line in (f"@each requirement {hostile}", f"@heading {hostile}", f"@text {hostile}", f"@table requirement where title eq {hostile}", hostile):
        result = parse_text(f"@layout document\n{line}\n")
        assert result.tree is None or isinstance(result.tree, dict)


def test_parsing_does_not_modify_a_shared_tree_and_returns_fresh_objects():
    tree = example()
    snapshot = copy.deepcopy(tree)
    text = format_tree(tree)

    first, second = parse_text(text).tree, parse_text(text).tree

    assert tree == snapshot and first == second and first is not second


# --- extension ---------------------------------------------------------------------------------------


def test_every_block_type_has_a_text_form_and_every_text_form_a_block_type():
    assert set(TEXT_FORMS) == set(BLOCK_SPECS)


def test_a_text_form_cannot_be_registered_twice():
    with pytest.raises(ValueError, match="already has a text form"):
        register_text_form(TextForm("heading", lambda p, d: None, lambda w, n, depth: None))


def test_an_if_on_a_module_reads_and_writes_as_module_and_the_key():
    text = "@layout document\n\n@if module risk_management and not module decisions\n  @text \"x\"\n@else\n  @text \"y\"\n@end\n"

    parsed = parse_text(text)

    assert parsed.errors == []
    assert parsed.tree["nodes"][0]["when"] == {"all": [{"module": "risk_management"}, {"not": {"module": "decisions"}}]}
    assert parse_text(format_tree(parsed.tree)).tree == parsed.tree
