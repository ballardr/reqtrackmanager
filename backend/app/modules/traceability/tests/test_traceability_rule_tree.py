"""Tests for the rule expression (`modules.traceability.rule_tree`): parsing and its limits, the canonical JSON, evaluating a
scope tree against a record's values and a requirement tree against link counts. The tree touches no database, so none of
these tests needs one."""

from __future__ import annotations

import uuid

import pytest

from app.modules.traceability import rule_presets, rule_tree
from app.modules.traceability.rule_tree import RuleTreeError, Vocabulary

LINK_TYPE = uuid.uuid4()


def _leaf(target="requirement", subtype=None, **extra) -> dict:
    return {"op": "link", "targets": [{"artefact_type": target, "subtype": subtype}], **extra}


def _group(op, *children) -> dict:
    return {"op": op, "children": list(children)}


def _nest(depth: int) -> dict:
    """A requirement tree whose groups are nested `depth` levels deep, with one leaf at the bottom."""
    node: dict = _leaf()
    for _ in range(depth):
        node = _group("all", node)
    return node


def _vocab(source="requirement") -> Vocabulary:
    return Vocabulary(
        artefact_types={"requirement", "requirement_action", "decision"},
        fields={"subtype": ("text", ()), "requirement_type_rank": ("number", ("requirement",))},
        link_type_ids={LINK_TYPE}, source_type=source,
    )


# --- parsing -------------------------------------------------------------------------------------


def test_a_lone_leaf_is_a_valid_requirement_with_defaults():
    node = rule_tree.parse_requires(_leaf())
    assert isinstance(node, rule_tree.LinkLeaf)
    assert (node.minimum, node.maximum, node.direction, node.link_types.mode) == (1, None, "outgoing", "any")


def test_a_tree_round_trips_through_its_canonical_json():
    raw = _group("any", _leaf(subtype="Business Requirement", min=2, max=5, label="Parent"), _leaf("decision", direction="incoming"))
    once = rule_tree.to_json(rule_tree.parse_requires(raw))
    assert rule_tree.to_json(rule_tree.parse_requires(once)) == once
    assert once["children"][0]["min"] == 2 and once["children"][0]["label"] == "Parent"


def test_depth_is_limited_to_four_nested_groups():
    rule_tree.parse_requires(_nest(rule_tree.MAX_DEPTH))
    with pytest.raises(RuleTreeError, match="nested at most 4 levels"):
        rule_tree.parse_requires(_nest(rule_tree.MAX_DEPTH + 1))


def test_a_rule_is_limited_to_twenty_five_parts():
    leaves = [_leaf() for _ in range(rule_tree.MAX_NODES - 1)]
    assert rule_tree.node_count(rule_tree.parse_requires(_group("all", *leaves))) == rule_tree.MAX_NODES
    with pytest.raises(RuleTreeError, match="at most 25 parts"):
        rule_tree.parse_requires(_group("all", *leaves, _leaf()))


def test_the_limit_counts_parts_across_nested_groups():
    wide = _group("all", *[_group("any", _leaf(), _leaf()) for _ in range(9)])
    with pytest.raises(RuleTreeError, match="at most 25 parts"):
        rule_tree.parse_requires(wide)


@pytest.mark.parametrize("raw, message", [
    (None, "must say what it requires"),
    ("not an object", "must be an object"),
    ({"op": "condition", "field": "x", "operator": "equals", "value": "y"}, "group or a link"),
    ({"op": "not", "child": _leaf()}, "cannot be negated"),
    ({"op": "all", "children": []}, "at least one part"),
    ({"op": "all"}, "at least one part"),
    (_leaf(direction="sideways"), "outgoing or incoming"),
    (_leaf(min=-1), "from 0 to 1000"),
    (_leaf(min=2, max=1), "maximum cannot be below"),
    (_leaf(min=0), "needs a maximum"),
    (_leaf(min=True), "from 0 to 1000"),
    ({"op": "link", "targets": []}, "Choose 1 to 10 target"),
    ({"op": "link"}, "Choose 1 to 10 target"),
    ({"op": "link", "targets": [{"artefact_type": "requirement"}], "link_types": {"mode": "types"}}, "Choose 1 to 25 link types"),
    ({"op": "link", "targets": [{"artefact_type": "requirement"}], "link_types": {"mode": "bogus"}}, "any, untyped or a list"),
    ({"op": "link", "targets": [{"artefact_type": "requirement"}], "link_types": {"mode": "types", "ids": ["nope"]}}, "named by its id"),
])
def test_malformed_requirements_are_rejected_with_a_reason(raw, message):
    with pytest.raises(RuleTreeError, match=message):
        rule_tree.parse_requires(raw)


def test_a_minimum_of_zero_with_a_maximum_is_the_way_to_forbid_links():
    leaf = rule_tree.parse_requires(_leaf(min=0, max=0))
    assert isinstance(leaf, rule_tree.LinkLeaf)
    assert rule_tree.leaf_met(leaf, 0) and not rule_tree.leaf_met(leaf, 1)


def test_the_error_names_the_part_that_is_wrong():
    with pytest.raises(RuleTreeError) as caught:
        rule_tree.parse_requires(_group("all", _leaf(), _group("any", _leaf(), _leaf(min=5, max=1))))
    assert caught.value.path == "1.1"


def test_a_vocabulary_rejects_unknown_types_and_link_types():
    with pytest.raises(RuleTreeError, match="is not a record type"):
        rule_tree.parse_requires(_leaf("nonsense"), _vocab())
    with pytest.raises(RuleTreeError, match="not available to this rule"):
        rule_tree.parse_requires(_leaf(link_types={"mode": "types", "ids": [str(uuid.uuid4())]}), _vocab())
    rule_tree.parse_requires(_leaf(link_types={"mode": "types", "ids": [str(LINK_TYPE)]}), _vocab())


def test_duplicate_targets_and_link_types_are_kept_once():
    leaf = rule_tree.parse_requires({
        "op": "link", "targets": [{"artefact_type": "requirement"}, {"artefact_type": "requirement", "subtype": ""}],
        "link_types": {"mode": "types", "ids": [str(LINK_TYPE), str(LINK_TYPE)]},
    })
    assert isinstance(leaf, rule_tree.LinkLeaf)
    assert len(leaf.targets) == 1 and leaf.link_types.ids == (LINK_TYPE,)


# --- conditions ----------------------------------------------------------------------------------


def _cond(field="subtype", operator="equals", value="Project Requirement") -> dict:
    return {"op": "condition", "field": field, "operator": operator, "value": value}


def test_no_scope_means_every_record_is_in_scope():
    assert rule_tree.parse_applies_when(None) is None
    assert rule_tree.holds(None, lambda _k: ())


def test_a_scope_may_negate_and_nest_and_or_groups():
    scope = rule_tree.parse_applies_when(_group(
        "all", _cond(), {"op": "not", "child": _cond("tag", "equals", "legacy")},
    ))
    assert rule_tree.holds(scope, lambda k: {"subtype": ["Project Requirement"], "tag": ["new"]}.get(k, ()))
    assert not rule_tree.holds(scope, lambda k: {"subtype": ["Project Requirement"], "tag": ["legacy"]}.get(k, ()))
    either = rule_tree.parse_applies_when(_group("any", _cond(value="A"), _cond(value="B")))
    assert rule_tree.holds(either, lambda k: ["B"]) and not rule_tree.holds(either, lambda k: ["C"])


def test_text_conditions_compare_ignoring_case_and_numbers_compare_by_size():
    scope = rule_tree.parse_applies_when(_cond(value="project requirement"))
    assert rule_tree.holds(scope, lambda _k: ["Project Requirement"])
    higher = rule_tree.parse_applies_when(_cond("requirement_type_rank", "greater_than", 1), _vocab())
    assert rule_tree.holds(higher, lambda _k: [3]) and not rule_tree.holds(higher, lambda _k: [1])
    assert not rule_tree.holds(higher, lambda _k: [])


def test_a_record_with_several_values_matches_when_any_value_does():
    scope = rule_tree.parse_applies_when(_cond("tag", "equals", "safety"))
    assert rule_tree.holds(scope, lambda _k: ["ui", "safety"])
    in_list = rule_tree.parse_applies_when(_cond("tag", "in", ["safety", "security"]))
    assert rule_tree.holds(in_list, lambda _k: ["security"]) and not rule_tree.holds(in_list, lambda _k: ["ui"])


def test_not_equals_holds_for_a_record_with_no_value():
    scope = rule_tree.parse_applies_when(_cond("tag", "not_equals", "legacy"))
    assert rule_tree.holds(scope, lambda _k: [])
    assert not rule_tree.holds(scope, lambda _k: ["legacy"])


def test_is_set_and_is_not_set_take_no_value():
    assert rule_tree.parse_applies_when(_cond("tag", "is_set", None)) == rule_tree.Condition("tag", "is_set", None)
    unranked = rule_tree.parse_applies_when(_cond("requirement_type_rank", "is_not_set", None), _vocab())
    assert rule_tree.holds(unranked, lambda _k: []) and not rule_tree.holds(unranked, lambda _k: [2])


@pytest.mark.parametrize("raw, message", [
    (_cond(operator="starts_with"), "not available for the field"),
    (_cond(operator="less_than", value="x"), "whole number"),
    (_cond(operator="in", value=[]), "1 to 25 entries"),
    (_cond(operator="in", value="x"), "1 to 25 entries"),
    (_cond(value=""), "must be text"),
    (_cond(value="x" * 201), "at most 200 characters"),
    ({"op": "condition", "field": "", "operator": "equals", "value": "x"}, "must be text"),
    ({"op": "link", "targets": [{"artefact_type": "requirement"}]}, "group, a negation or a condition"),
])
def test_malformed_conditions_are_rejected(raw, message):
    with pytest.raises(RuleTreeError, match=message):
        rule_tree.parse_applies_when(raw)


def test_a_size_comparison_is_refused_on_a_text_field():
    with pytest.raises(RuleTreeError, match="not available for the field"):
        rule_tree.parse_applies_when(_cond("subtype", "less_than", "x"), _vocab())


def test_a_condition_is_checked_against_the_registered_fields():
    with pytest.raises(RuleTreeError, match="not a field a rule can test"):
        rule_tree.parse_applies_when(_cond("mystery"), _vocab())
    with pytest.raises(RuleTreeError, match="does not apply to this record type"):
        rule_tree.parse_applies_when(_cond("requirement_type_rank", "equals", 1), _vocab("decision"))
    with pytest.raises(RuleTreeError, match="whole number"):
        rule_tree.parse_applies_when(_cond("requirement_type_rank", "equals", "one"), _vocab())


# --- satisfaction --------------------------------------------------------------------------------


def test_all_needs_every_leaf_and_any_needs_one():
    both = rule_tree.parse_requires(_group("all", _leaf(), _leaf("decision")))
    one_of = rule_tree.parse_requires(_group("any", _leaf(), _leaf("decision")))
    assert [p for p, _ in rule_tree.leaves(both)] == ["0", "1"]
    assert rule_tree.satisfied(both, {"0": 1, "1": 1}) and not rule_tree.satisfied(both, {"0": 1})
    assert rule_tree.satisfied(one_of, {"1": 2}) and not rule_tree.satisfied(one_of, {})


def test_nested_groups_combine_and_a_lone_leaf_has_the_empty_path():
    nested = rule_tree.parse_requires(_group("all", _leaf(), _group("any", _leaf("decision"), _leaf("requirement_action"))))
    assert [p for p, _ in rule_tree.leaves(nested)] == ["0", "1.0", "1.1"]
    assert rule_tree.satisfied(nested, {"0": 1, "1.1": 1}) and not rule_tree.satisfied(nested, {"1.0": 1})
    lone = rule_tree.parse_requires(_leaf())
    assert [p for p, _ in rule_tree.leaves(lone)] == [""]
    assert rule_tree.satisfied(lone, {"": 1})


def test_a_leaf_is_met_within_its_minimum_and_maximum():
    leaf = rule_tree.parse_requires(_leaf(min=2, max=3))
    assert isinstance(leaf, rule_tree.LinkLeaf)
    assert [rule_tree.leaf_met(leaf, n) for n in range(5)] == [False, False, True, True, False]


# --- presets -------------------------------------------------------------------------------------


def test_the_three_presets_build_trees_the_parser_accepts():
    assert rule_presets.build_preset(
        "none", target_type=None, target_subtype=None, alternative_type=None, alternative_subtype=None, link_type_ids=[], minimum=1,
    ) is None
    single = rule_presets.build_preset(
        "type", target_type="requirement", target_subtype="Business Requirement", alternative_type=None,
        alternative_subtype=None, link_type_ids=[LINK_TYPE], minimum=2,
    )
    leaf = rule_tree.parse_requires(single, _vocab())
    assert isinstance(leaf, rule_tree.LinkLeaf) and leaf.minimum == 2 and leaf.link_types.ids == (LINK_TYPE,)
    either = rule_presets.build_preset(
        "type_or_alternative", target_type="requirement", target_subtype=None, alternative_type="decision",
        alternative_subtype=None, link_type_ids=[], minimum=1,
    )
    group = rule_tree.parse_requires(either, _vocab())
    assert isinstance(group, rule_tree.Group) and group.op == "any" and len(group.children) == 2


def _preset(key, target_type=None, alternative_type=None):
    return rule_presets.build_preset(
        key, target_type=target_type, target_subtype=None, alternative_type=alternative_type, alternative_subtype=None,
        link_type_ids=[], minimum=1,
    )


def test_a_preset_without_what_it_needs_is_refused():
    with pytest.raises(ValueError, match="target record type"):
        _preset("type")
    with pytest.raises(ValueError, match="alternative record type"):
        _preset("type_or_alternative", target_type="requirement")
    with pytest.raises(ValueError, match="not a preset"):
        _preset("nope", target_type="requirement")


def test_a_condition_parsed_without_a_vocabulary_reads_its_kind_from_the_value():
    size = rule_tree.parse_applies_when(_cond("anything", "greater_than", 2))
    assert size == rule_tree.Condition("anything", "greater_than", 2)
    equal = rule_tree.parse_applies_when(_cond("anything", "equals", 3))
    assert equal == rule_tree.Condition("anything", "equals", 3)
    several = rule_tree.parse_applies_when(_cond("anything", "in", [1, 2]))
    assert several == rule_tree.Condition("anything", "in", (1, 2))
    assert rule_tree.parse_applies_when(_cond("anything", "equals", "x")) == rule_tree.Condition("anything", "equals", "x")
