"""Tests for the diagram resolver (`diagram_resolver.resolve`), the one rule behind the view, the SVG and later the
reports and exports: direct lines, roll-up to placed ancestors, connections inside one placed element, toggles
(bridging across hidden elements, chains, dead ends, directions, hidden subtrees) and the merge of parallel lines.
The resolver is pure, so these tests need no database."""

from __future__ import annotations

import uuid

from app.modules.architecture.diagram_resolver import ModelConnection, resolve


def _ids(*names: str) -> dict[str, uuid.UUID]:
    return {name: uuid.uuid5(uuid.NAMESPACE_DNS, name) for name in names}


def _conn(ids, name, source, target, *, directional=True) -> ModelConnection:
    return ModelConnection(uuid.uuid5(uuid.NAMESPACE_DNS, f"conn-{name}"), ids[source], ids[target], directional)


def _cid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"conn-{name}")


def _flat(ids):
    """A tree with no parents: every element is a root."""
    return {i: None for i in ids.values()}


def test_a_connection_between_two_placed_elements_is_one_solid_line():
    ids = _ids("a", "b")
    result = resolve(
        placed=[ids["a"], ids["b"]], parents=_flat(ids), connections=[_conn(ids, "ab", "a", "b")], merge_parallel=False,
    )
    (line,) = result.lines
    assert (line.source_id, line.target_id) == (ids["a"], ids["b"])
    assert line.connection_ids == (_cid("ab"),)
    assert (line.rolled_up, line.bridged, line.indirect, line.two_way) == (False, False, False, False)
    assert result.internal == {} and result.hidden_placed == frozenset()


def test_a_two_way_connection_is_a_two_way_line():
    ids = _ids("a", "b")
    result = resolve(
        placed=ids.values(), parents=_flat(ids), connections=[_conn(ids, "ab", "a", "b", directional=False)],
        merge_parallel=False,
    )
    assert result.lines[0].two_way is True


def test_an_end_rolls_up_to_its_nearest_placed_ancestor_and_the_line_is_indirect():
    ids = _ids("parent", "child", "other")
    parents = {ids["parent"]: None, ids["child"]: ids["parent"], ids["other"]: None}
    result = resolve(
        placed=[ids["parent"], ids["other"]], parents=parents, connections=[_conn(ids, "x", "child", "other")],
        merge_parallel=False,
    )
    (line,) = result.lines
    assert (line.source_id, line.target_id) == (ids["parent"], ids["other"])
    assert (line.rolled_up, line.indirect, line.bridged) == (True, True, False)


def test_a_connection_with_an_end_under_no_placed_element_is_not_drawn():
    ids = _ids("a", "b", "c")
    result = resolve(
        placed=[ids["a"]], parents=_flat(ids), connections=[_conn(ids, "ab", "a", "b"), _conn(ids, "bc", "b", "c")],
        merge_parallel=False,
    )
    assert result.lines == () and result.internal == {}


def test_a_connection_inside_one_placed_element_is_on_no_line_but_is_counted_for_it():
    ids = _ids("parent", "c1", "c2")
    parents = {ids["parent"]: None, ids["c1"]: ids["parent"], ids["c2"]: ids["parent"]}
    result = resolve(
        placed=[ids["parent"]], parents=parents, connections=[_conn(ids, "in", "c1", "c2")], merge_parallel=False,
    )
    assert result.lines == ()
    assert result.internal == {ids["parent"]: (_cid("in"),)}


def test_several_connections_collapsing_into_one_rolled_up_line_are_listed_together():
    ids = _ids("p", "c1", "c2", "x")
    parents = {ids["p"]: None, ids["c1"]: ids["p"], ids["c2"]: ids["p"], ids["x"]: None}
    result = resolve(
        placed=[ids["p"], ids["x"]], parents=parents,
        connections=[_conn(ids, "one", "c1", "x"), _conn(ids, "two", "c2", "x")], merge_parallel=False,
    )
    (line,) = result.lines
    assert line.connection_ids == (_cid("one"), _cid("two")) and line.indirect is True


def test_parallel_direct_lines_stay_apart_with_detail_and_merge_without_it():
    ids = _ids("a", "b")
    connections = [_conn(ids, "one", "a", "b"), _conn(ids, "two", "b", "a")]
    detailed = resolve(placed=ids.values(), parents=_flat(ids), connections=connections, merge_parallel=False)
    plain = resolve(placed=ids.values(), parents=_flat(ids), connections=connections, merge_parallel=True)
    assert len(detailed.lines) == 2
    (merged,) = plain.lines
    assert set(merged.connection_ids) == {_cid("one"), _cid("two")}
    assert merged.two_way is True  # one runs each way


def test_a_merged_line_with_a_direct_member_stays_solid():
    ids = _ids("p", "c", "x")
    parents = {ids["p"]: None, ids["c"]: ids["p"], ids["x"]: None}
    result = resolve(
        placed=[ids["p"], ids["x"]], parents=parents,
        connections=[_conn(ids, "direct", "p", "x"), _conn(ids, "rolled", "c", "x")], merge_parallel=True,
    )
    (line,) = result.lines
    assert line.rolled_up is True and line.indirect is False


def test_a_hidden_transit_element_is_bridged_and_the_line_lists_its_hop():
    ids = _ids("sensor", "firewall", "cloud")
    result = resolve(
        placed=[ids["sensor"], ids["firewall"], ids["cloud"]], parents=_flat(ids),
        connections=[_conn(ids, "in", "sensor", "firewall"), _conn(ids, "out", "firewall", "cloud")],
        hidden_elements=[ids["firewall"]], merge_parallel=False,
    )
    (line,) = result.lines
    assert (line.source_id, line.target_id) == (ids["sensor"], ids["cloud"])
    assert (line.bridged, line.indirect, line.two_way) == (True, True, False)
    assert line.hops == (ids["firewall"],)
    assert set(line.connection_ids) == {_cid("in"), _cid("out")}
    assert result.hidden_placed == frozenset({ids["firewall"]})


def test_switching_the_transit_element_on_draws_the_real_connections():
    ids = _ids("sensor", "firewall", "cloud")
    result = resolve(
        placed=ids.values(), parents=_flat(ids),
        connections=[_conn(ids, "in", "sensor", "firewall"), _conn(ids, "out", "firewall", "cloud")], merge_parallel=False,
    )
    assert {(ln.source_id, ln.target_id) for ln in result.lines} == {(ids["sensor"], ids["firewall"]), (ids["firewall"], ids["cloud"])}
    assert not any(ln.bridged for ln in result.lines)


def test_a_chain_of_hidden_elements_is_followed_and_every_hop_listed_in_order():
    ids = _ids("a", "h1", "h2", "h3", "b")
    result = resolve(
        placed=[ids["a"], ids["b"]], parents=_flat(ids),
        connections=[
            _conn(ids, "1", "a", "h1"), _conn(ids, "2", "h1", "h2"), _conn(ids, "3", "h2", "h3"), _conn(ids, "4", "h3", "b"),
        ],
        hidden_elements=[ids["h1"], ids["h2"], ids["h3"]], merge_parallel=False,
    )
    (line,) = result.lines
    assert (line.source_id, line.target_id) == (ids["a"], ids["b"])
    assert line.hops == (ids["h1"], ids["h2"], ids["h3"])


def test_a_hidden_dead_end_just_disappears():
    ids = _ids("a", "h")
    result = resolve(
        placed=[ids["a"]], parents=_flat(ids), connections=[_conn(ids, "ah", "a", "h")], hidden_elements=[ids["h"]],
        merge_parallel=False,
    )
    assert result.lines == ()


def test_bridging_follows_the_direction_of_the_connections():
    ids = _ids("a", "h", "b")
    connections = [_conn(ids, "ah", "a", "h"), _conn(ids, "bh", "b", "h")]  # both point into the hidden element
    result = resolve(
        placed=[ids["a"], ids["b"]], parents=_flat(ids), connections=connections, hidden_elements=[ids["h"]],
        merge_parallel=False,
    )
    assert result.lines == ()


def test_two_way_connections_bridge_once_as_a_two_way_line():
    ids = _ids("a", "h", "b")
    connections = [_conn(ids, "ah", "a", "h", directional=False), _conn(ids, "hb", "h", "b", directional=False)]
    result = resolve(
        placed=[ids["a"], ids["b"]], parents=_flat(ids), connections=connections, hidden_elements=[ids["h"]],
        merge_parallel=False,
    )
    (line,) = result.lines
    assert line.two_way is True and line.bridged is True


def test_a_hidden_element_hides_its_subtree_and_a_hidden_placed_element_is_reported():
    ids = _ids("group", "member", "x")
    parents = {ids["group"]: None, ids["member"]: ids["group"], ids["x"]: None}
    result = resolve(
        placed=[ids["group"], ids["x"]], parents=parents, connections=[_conn(ids, "mx", "member", "x")],
        hidden_elements=[ids["group"]], merge_parallel=False,
    )
    assert result.lines == ()
    assert result.hidden_placed == frozenset({ids["group"]})


def test_a_hidden_connection_is_left_out_and_does_not_bridge():
    ids = _ids("a", "b")
    result = resolve(
        placed=ids.values(), parents=_flat(ids), connections=[_conn(ids, "ab", "a", "b")],
        hidden_connections=[_cid("ab")], merge_parallel=False,
    )
    assert result.lines == ()


def test_a_bridged_line_that_lands_inside_one_placed_element_is_internal():
    ids = _ids("p", "a", "h", "b")
    parents = {ids["p"]: None, ids["a"]: ids["p"], ids["b"]: ids["p"], ids["h"]: ids["p"]}
    result = resolve(
        placed=[ids["p"]], parents=parents, connections=[_conn(ids, "ah", "a", "h"), _conn(ids, "hb", "h", "b")],
        hidden_elements=[ids["h"]], merge_parallel=False,
    )
    assert result.lines == () and set(result.internal[ids["p"]]) == {_cid("ah"), _cid("hb")}


def test_the_result_does_not_depend_on_the_order_connections_are_given_in():
    ids = _ids("a", "b", "c")
    connections = [_conn(ids, "ab", "a", "b"), _conn(ids, "bc", "b", "c"), _conn(ids, "ca", "c", "a")]
    forward = resolve(placed=ids.values(), parents=_flat(ids), connections=connections, merge_parallel=False)
    backward = resolve(placed=ids.values(), parents=_flat(ids), connections=connections[::-1], merge_parallel=False)
    assert forward.lines == backward.lines


def test_a_corrupt_parent_cycle_ends_the_walk_instead_of_hanging():
    ids = _ids("a", "b", "x")
    parents = {ids["a"]: ids["b"], ids["b"]: ids["a"], ids["x"]: None}
    result = resolve(
        placed=[ids["x"]], parents=parents, connections=[_conn(ids, "ax", "a", "x")], merge_parallel=False,
    )
    assert result.lines == ()
