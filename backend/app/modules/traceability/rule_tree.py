"""
Module: modules.traceability.rule_tree

The Boolean expression a traceability rule is made of, and its parsing, validation, serialisation and in-memory
evaluation. It touches no database.

A rule holds two trees:
- `applies_when`: when a source record is in scope. Nodes are `all` (AND), `any` (OR), `not` and the leaf `condition`
  (a registered record property, an operator and a value).
- `requires`: what an in-scope record must have. Nodes are `all` and `any` and the leaf `link` (a set of link types, a
  direction, a set of target record types counted together, and a minimum and maximum count).

Responsibilities:
- Parse a stored or submitted JSON document into frozen node dataclasses, rejecting a malformed one with the path of the
  fault (`RuleTreeError`), and serialise nodes back to the canonical JSON (`to_json`).
- Enforce the shape limits (`MAX_DEPTH`, `MAX_NODES`, `MAX_TARGETS`, `MAX_IN_VALUES`) and, when a `Vocabulary` is given,
  that every named type, field, operator and link type exists.
- Evaluate an `applies_when` tree against a record's property values (`holds`) and a `requires` tree against the number of
  matching links per leaf (`satisfied`), and number the leaves (`leaves`) so a result can name each one.

Design decisions:
- The flat rule of the first design (one link type, one target, a minimum) is a `requires` tree of one leaf, so one
  structure serves every case; the three preset rules are ready-made trees (`rule_presets`).
- The limits (depth 4, 25 nodes) keep an evaluation's statement count bounded by the leaves, which is what the scaling
  probe measures, and keep a rule readable in the editor. Depth counts nested `all`, `any` and `not` levels.
- `not` appears only in `applies_when`: negating a requirement would turn "must have a link" into "must not have one",
  which is a maximum of zero and is written as such (`max`).
- A condition on a text field compares ignoring case; a number field compares whole numbers.
- Link types and target types are stored by id and key, never by name, so a rename of a link type does not change a rule;
  bundles translate them to names (`rules`).
- Parsing without a `Vocabulary` is structural only: a stored rule whose type or field has since been unregistered still
  loads and is reported as a problem rather than failing the page. Without the field's registered kind, a condition's kind is
  read from its operator and value.

Dependencies: none beyond the standard library.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA_VERSION = 1
MAX_DEPTH = 4
MAX_NODES = 25
MAX_TARGETS = 10
MAX_LINK_TYPES = 25
MAX_IN_VALUES = 25
MAX_COUNT = 1000
MAX_TEXT_VALUE = 200
MAX_LABEL = 120

GROUP_OPS = ("all", "any")
TEXT_OPERATORS = ("equals", "not_equals", "in", "is_set", "is_not_set")
NUMBER_OPERATORS = (
    "equals", "not_equals", "in", "less_than", "less_or_equal", "greater_than", "greater_or_equal", "is_set", "is_not_set",
)
VALUELESS_OPERATORS = ("is_set", "is_not_set")
DIRECTIONS = ("outgoing", "incoming")
LINK_TYPE_MODES = ("any", "untyped", "types")

Value = str | int | tuple[str, ...] | tuple[int, ...] | None


class RuleTreeError(ValueError):
    """A rule tree that is malformed or breaks a limit.

    Attributes:
        path: Where in the tree the fault is, as dotted child positions (`"1.0"`); empty for the root.
    """

    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class Condition:
    """A test of one record property: `field` (a `RuleConditionField` key), `operator` and `value`."""

    field: str
    operator: str
    value: Value = None


@dataclass(frozen=True)
class Target:
    """A record type, and optionally one of its sub-types, whose records a link leaf counts."""

    artefact_type: str
    subtype: str | None = None


@dataclass(frozen=True)
class LinkTypes:
    """Which links a leaf counts: any link, only untyped links, or the listed link types."""

    mode: Literal["any", "untyped", "types"]
    ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class LinkLeaf:
    """A required number of links of the in-scope record.

    Attributes:
        link_types: The links counted.
        direction: `outgoing` counts links the record is the source of, `incoming` links it is the target of.
        targets: The record types (and sub-types) at the other end, counted together.
        minimum: The fewest distinct records at the other end that satisfy the leaf.
        maximum: The most that satisfy it, or `None` for no upper bound.
        label: A name for the leaf in a status view; empty to use a generated one.
    """

    link_types: LinkTypes
    direction: Literal["outgoing", "incoming"]
    targets: tuple[Target, ...]
    minimum: int = 1
    maximum: int | None = None
    label: str = ""


@dataclass(frozen=True)
class Group:
    """An AND (`all`) or OR (`any`) of child nodes."""

    op: Literal["all", "any"]
    children: tuple[Node, ...]


@dataclass(frozen=True)
class Negation:
    """The opposite of a child node (an `applies_when` tree only)."""

    child: Node


Node = Group | Negation | Condition | LinkLeaf


@dataclass(frozen=True)
class Vocabulary:
    """What a rule may name, for validation.

    Attributes:
        artefact_types: Every registered record type.
        fields: `{field key: (value kind, record types the field applies to or empty for all)}`.
        link_type_ids: The link types the rule's owner may use.
        source_type: The rule's source record type, which a condition field must apply to.
    """

    artefact_types: Collection[str]
    fields: Mapping[str, tuple[Literal["text", "number"], Collection[str]]]
    link_type_ids: Collection[uuid.UUID]
    source_type: str


@dataclass(frozen=True)
class _Budget:
    """The nodes still available to a tree being parsed."""

    left: int = MAX_NODES

    def take(self, path: str) -> _Budget:
        if self.left <= 0:
            raise RuleTreeError(f"A rule may have at most {MAX_NODES} parts.", path)
        return _Budget(self.left - 1)


def _path(parent: str, position: int) -> str:
    return f"{parent}.{position}" if parent else str(position)


def _as_mapping(raw: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuleTreeError("A rule part must be an object.", path)
    return raw


def _whole(value: Any, path: str, what: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise RuleTreeError(f"{what} must be a whole number from {low} to {high}.", path)
    return value


def _text(value: Any, path: str, what: str, *, high: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleTreeError(f"{what} must be text.", path)
    cleaned = value.strip()
    if len(cleaned) > high:
        raise RuleTreeError(f"{what} must be at most {high} characters.", path)
    return cleaned


def _inferred_kind(operator: Any, value: Any) -> str:
    """The value kind of a condition parsed without a vocabulary: a size comparison or a whole-number value is a number."""
    if operator in ("less_than", "less_or_equal", "greater_than", "greater_or_equal"):
        return "number"
    first = value[0] if isinstance(value, list | tuple) and value else value
    return "number" if isinstance(first, int) and not isinstance(first, bool) else "text"


def _parse_condition(raw: Mapping[str, Any], path: str, vocab: Vocabulary | None) -> Condition:
    field_key = _text(raw.get("field"), path, "A condition's field", high=100)
    operator = raw.get("operator")
    kind: str = _inferred_kind(operator, raw.get("value")) if vocab is None else "text"
    if vocab is not None:
        known = vocab.fields.get(field_key)
        if known is None:
            raise RuleTreeError(f"{field_key!r} is not a field a rule can test.", path)
        kind, applies_to = known
        if applies_to and vocab.source_type not in applies_to:
            raise RuleTreeError(f"The field {field_key!r} does not apply to this record type.", path)
    operators = NUMBER_OPERATORS if kind == "number" else TEXT_OPERATORS
    if operator not in operators:
        raise RuleTreeError(f"The operator {operator!r} is not available for the field {field_key!r}.", path)
    assert isinstance(operator, str)
    value = raw.get("value")
    if operator in VALUELESS_OPERATORS:
        return Condition(field_key, operator, None)
    if operator == "in":
        if not isinstance(value, list | tuple) or not 1 <= len(value) <= MAX_IN_VALUES:
            raise RuleTreeError(f"A list of values needs 1 to {MAX_IN_VALUES} entries.", path)
        if kind == "number":
            numbers = tuple(_whole(v, path, "A value", low=0, high=100000) for v in value)
            return Condition(field_key, operator, numbers)
        return Condition(field_key, operator, tuple(_text(v, path, "A value", high=MAX_TEXT_VALUE) for v in value))
    if kind == "number":
        return Condition(field_key, operator, _whole(value, path, "A value", low=0, high=100000))
    return Condition(field_key, operator, _text(value, path, "A value", high=MAX_TEXT_VALUE))


def _parse_link_types(raw: Any, path: str, vocab: Vocabulary | None) -> LinkTypes:
    entry = _as_mapping(raw if raw is not None else {"mode": "any"}, path)
    mode = entry.get("mode")
    if mode not in LINK_TYPE_MODES:
        raise RuleTreeError("The link types must be any, untyped or a list of types.", path)
    if mode != "types":
        return LinkTypes(mode)
    named = entry.get("ids")
    if not isinstance(named, list | tuple) or not 1 <= len(named) <= MAX_LINK_TYPES:
        raise RuleTreeError(f"Choose 1 to {MAX_LINK_TYPES} link types.", path)
    ids: list[uuid.UUID] = []
    for item in named:
        try:
            link_type_id = item if isinstance(item, uuid.UUID) else uuid.UUID(str(item))
        except ValueError:
            raise RuleTreeError("A link type must be named by its id.", path) from None
        if vocab is not None and link_type_id not in vocab.link_type_ids:
            raise RuleTreeError("A link type is not available to this rule.", path)
        if link_type_id not in ids:
            ids.append(link_type_id)
    return LinkTypes("types", tuple(ids))


def _parse_targets(raw: Any, path: str, vocab: Vocabulary | None) -> tuple[Target, ...]:
    if not isinstance(raw, list | tuple) or not 1 <= len(raw) <= MAX_TARGETS:
        raise RuleTreeError(f"Choose 1 to {MAX_TARGETS} target record types.", path)
    targets: list[Target] = []
    for item in raw:
        entry = _as_mapping(item, path)
        artefact_type = _text(entry.get("artefact_type"), path, "A target type", high=64)
        if vocab is not None and artefact_type not in vocab.artefact_types:
            raise RuleTreeError(f"{artefact_type!r} is not a record type.", path)
        subtype_raw = entry.get("subtype")
        subtype = None if subtype_raw in (None, "") else _text(subtype_raw, path, "A target sub-type", high=MAX_TEXT_VALUE)
        target = Target(artefact_type, subtype)
        if target not in targets:
            targets.append(target)
    return tuple(targets)


def _parse_link(raw: Mapping[str, Any], path: str, vocab: Vocabulary | None) -> LinkLeaf:
    direction = raw.get("direction", "outgoing")
    if direction not in DIRECTIONS:
        raise RuleTreeError("The direction must be outgoing or incoming.", path)
    minimum = _whole(raw.get("min", 1), path, "The minimum", low=0, high=MAX_COUNT)
    maximum_raw = raw.get("max")
    maximum = None if maximum_raw is None else _whole(maximum_raw, path, "The maximum", low=0, high=MAX_COUNT)
    if maximum is not None and maximum < minimum:
        raise RuleTreeError("The maximum cannot be below the minimum.", path)
    if minimum == 0 and maximum is None:
        raise RuleTreeError("A minimum of 0 needs a maximum, otherwise the part requires nothing.", path)
    label_raw = raw.get("label")
    label = "" if label_raw in (None, "") else _text(label_raw, path, "A label", high=MAX_LABEL)
    return LinkLeaf(
        link_types=_parse_link_types(raw.get("link_types"), path, vocab), direction=direction,
        targets=_parse_targets(raw.get("targets"), path, vocab), minimum=minimum, maximum=maximum, label=label,
    )


def _parse_node(
    raw: Any, path: str, depth: int, budget: list[_Budget], *, requires: bool, vocab: Vocabulary | None,
) -> Node:
    """Parses one node; `budget` is a one-element list so a child's use of the node allowance is seen by its siblings."""
    entry = _as_mapping(raw, path)
    budget[0] = budget[0].take(path)
    op = entry.get("op")
    if op in GROUP_OPS or op == "not":
        if depth >= MAX_DEPTH:
            raise RuleTreeError(f"Groups may be nested at most {MAX_DEPTH} levels deep.", path)
        if op == "not":
            if requires:
                raise RuleTreeError("A requirement cannot be negated; use a maximum of 0 on the link instead.", path)
            return Negation(_parse_node(entry.get("child"), _path(path, 0), depth + 1, budget, requires=requires, vocab=vocab))
        children = entry.get("children")
        if not isinstance(children, list | tuple) or not children:
            raise RuleTreeError("A group needs at least one part.", path)
        assert isinstance(op, str)
        return Group(
            "all" if op == "all" else "any",
            tuple(
                _parse_node(child, _path(path, i), depth + 1, budget, requires=requires, vocab=vocab)
                for i, child in enumerate(children)
            ),
        )
    if requires:
        if op != "link":
            raise RuleTreeError("A requirement is a group or a link.", path)
        return _parse_link(entry, path, vocab)
    if op != "condition":
        raise RuleTreeError("A scope is a group, a negation or a condition.", path)
    return _parse_condition(entry, path, vocab)


def parse_applies_when(raw: Any, vocab: Vocabulary | None = None) -> Node | None:
    """Parses an `applies_when` document; `None` (no condition) means every record of the source type is in scope.

    Raises:
        RuleTreeError: If the document is malformed, too large or too deep, or (with a `vocab`) names something unknown.
    """
    if raw is None:
        return None
    return _parse_node(raw, "", 0, [_Budget()], requires=False, vocab=vocab)


def parse_requires(raw: Any, vocab: Vocabulary | None = None) -> Node:
    """Parses a `requires` document.

    Raises:
        RuleTreeError: As `parse_applies_when`; also when the document is missing.
    """
    if raw is None:
        raise RuleTreeError("A rule must say what it requires.")
    return _parse_node(raw, "", 0, [_Budget()], requires=True, vocab=vocab)


def to_json(node: Node) -> dict[str, Any]:
    """The canonical JSON of a node, as stored and returned by the API."""
    if isinstance(node, Group):
        return {"op": node.op, "children": [to_json(c) for c in node.children]}
    if isinstance(node, Negation):
        return {"op": "not", "child": to_json(node.child)}
    if isinstance(node, Condition):
        value: Any = list(node.value) if isinstance(node.value, tuple) else node.value
        return {"op": "condition", "field": node.field, "operator": node.operator, "value": value}
    link_types: dict[str, Any] = {"mode": node.link_types.mode}
    if node.link_types.mode == "types":
        link_types["ids"] = [str(i) for i in node.link_types.ids]
    return {
        "op": "link", "link_types": link_types, "direction": node.direction,
        "targets": [{"artefact_type": t.artefact_type, "subtype": t.subtype} for t in node.targets],
        "min": node.minimum, "max": node.maximum, "label": node.label,
    }


def node_count(node: Node | None) -> int:
    """How many parts (groups, negations and leaves) the tree has."""
    if node is None:
        return 0
    if isinstance(node, Group):
        return 1 + sum(node_count(c) for c in node.children)
    if isinstance(node, Negation):
        return 1 + node_count(node.child)
    return 1


def walk(node: Node | None) -> Iterator[Node]:
    """Every part of the tree, parents before children."""
    if node is None:
        return
    yield node
    if isinstance(node, Group):
        for child in node.children:
            yield from walk(child)
    elif isinstance(node, Negation):
        yield from walk(node.child)


def leaves(node: Node, path: str = "") -> list[tuple[str, LinkLeaf]]:
    """The link leaves of a `requires` tree with their paths (dotted child positions, `""` for a lone leaf), in order."""
    if isinstance(node, LinkLeaf):
        return [(path, node)]
    if isinstance(node, Group):
        found: list[tuple[str, LinkLeaf]] = []
        for i, child in enumerate(node.children):
            found.extend(leaves(child, _path(path, i)))
        return found
    return []


def conditions(node: Node | None) -> list[Condition]:
    """The condition leaves of an `applies_when` tree."""
    return [n for n in walk(node) if isinstance(n, Condition)]


def _test(condition: Condition, held: Sequence[str | int]) -> bool:
    """Whether a record holding `held` values satisfies one condition (any held value may satisfy it)."""
    operator = condition.operator
    if operator == "is_set":
        return bool(held)
    if operator == "is_not_set":
        return not held
    if operator == "not_equals":
        return not any(_same(v, condition.value) for v in held)
    if not held:
        return False
    if operator == "equals":
        return any(_same(v, condition.value) for v in held)
    if operator == "in":
        wanted = condition.value if isinstance(condition.value, tuple) else ()
        return any(_same(v, w) for v in held for w in wanted)
    compare = _COMPARISONS[operator]
    return any(isinstance(v, int) and isinstance(condition.value, int) and compare(v, condition.value) for v in held)


_COMPARISONS: dict[str, Callable[[int, int], bool]] = {
    "less_than": lambda a, b: a < b, "less_or_equal": lambda a, b: a <= b,
    "greater_than": lambda a, b: a > b, "greater_or_equal": lambda a, b: a >= b,
}


def _same(held: str | int, wanted: Any) -> bool:
    if isinstance(held, str) and isinstance(wanted, str):
        return held.casefold() == wanted.casefold()
    return held == wanted


def holds(node: Node | None, values: Callable[[str], Sequence[str | int]]) -> bool:
    """Whether a record is in scope.

    Args:
        node: The `applies_when` tree, or `None` for every record.
        values: `field key -> the values the record holds for it`.

    Returns:
        `True` when the tree holds for the record.
    """
    if node is None:
        return True
    if isinstance(node, Group):
        results = (holds(c, values) for c in node.children)
        return all(results) if node.op == "all" else any(results)
    if isinstance(node, Negation):
        return not holds(node.child, values)
    if isinstance(node, Condition):
        return _test(node, values(node.field))
    return False


def leaf_met(leaf: LinkLeaf, count: int) -> bool:
    """Whether `count` matching records satisfy one link leaf."""
    return count >= leaf.minimum and (leaf.maximum is None or count <= leaf.maximum)


def satisfied(node: Node, counts: Mapping[str, int], path: str = "") -> bool:
    """Whether a `requires` tree is satisfied.

    Args:
        node: The tree.
        counts: `leaf path -> matching records` as `leaves` numbers them; a leaf missing from it counts zero.
        path: The path of `node` itself (for recursion).

    Returns:
        `True` when every `all` group has every child satisfied and every `any` group at least one.
    """
    if isinstance(node, LinkLeaf):
        return leaf_met(node, counts.get(path, 0))
    if isinstance(node, Group):
        results = (satisfied(c, counts, _path(path, i)) for i, c in enumerate(node.children))
        return all(results) if node.op == "all" else any(results)
    return False
