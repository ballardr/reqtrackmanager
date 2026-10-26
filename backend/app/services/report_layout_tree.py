"""
Module: services.report_layout_tree

The layout tree: the versioned JSON a person authors for a custom report, and the validator that
decides whether a tree may be saved or run.

Responsibilities:
- Define the tree vocabulary (`TREE_SCHEMA_VERSION`): document blocks `heading`, `text`, `table`,
  `each`, `group`, `if`, `page_break`, `widget` (one component of a module report, by key), and the table-family
  block `sheet` (a root source plus optional left `joins` along links, one row per combination).
- Validate a tree with positioned errors (`validate_tree`): shape, unknown keys, depth/node/size
  caps, record types and field names against the report field registry, operators and values per
  field kind, conditions combined with `all` / `any` / `not`, aliases in scope and `{{alias.field}}`
  placeholders.
- Report, per container block, which `(record type, field)` pairs its subtree needs, so the
  evaluator loads exactly those columns (`TreeAnalysis.refs`).
- Hash a tree (`tree_hash`) for versioning and provenance.
- Check a `widget` block names a component in the widget catalogue (`services.report_widgets`)
  and sets only parameters that report declares, with values of the declared type.
- Let other features add block types (`register_block_spec`: equations).

Design decisions:
- **No expressions.** A value is a `{{alias.field}}` reference or a literal; a condition is one
  field, one operator, one literal. There is no template language (no Jinja), no raw HTML block and
  no way to name a table or column the registry does not declare, so a layout cannot reach data the
  registry omits (Restricted and consent-sensitive columns) or inject markup.
- Strict shape: an unknown key is an error, so a typo is found when saved rather than ignored when run.
- Everything an author can make unbounded is capped (`MAX_DEPTH`, `MAX_NODES`, `MAX_COLUMNS`,
  `MAX_TEXT_CHARS`, `MAX_WIDGET_REPORTS`, `MAX_TREE_BYTES`); the evaluator caps what the data can make unbounded.
- Link types in a source are stored by **name** (forward or reverse), never id, so a layout moves
  between projects and organisations; the evaluator resolves them for the project it runs in.
- The registry check is by key only. Whether the *runner* may see a type is decided at run time by
  the link graph's resolver, never at save time (an author may write a layout for a type they
  cannot read).

Dependencies: `services.report_fields` (field catalogue), `services.report_widgets` (widget catalogue),
`modules.registry` (reportable types), `services.report_model` (the allow-listed global placeholder names).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.models.report_layout import FAMILY_DOCUMENT, FAMILY_TABLE, LAYOUT_FAMILIES
from app.modules.registry import get_report_field_providers
from app.services.report_fields import FieldInfo, UnknownReportFieldError, field_catalogue
from app.services.report_model import PLACEHOLDER_NAMES
from app.services.report_widgets import find_widget, list_widgets, param_problems

TREE_SCHEMA_VERSION = 1

MAX_DEPTH = 8
MAX_NODES = 500
MAX_COLUMNS = 30
#: Most distinct reports (a report with one set of parameters) the widgets of one layout may run; the widgets of
#: one report share a single run, so only this count, not the number of widget blocks, bounds the work they cause.
MAX_WIDGET_REPORTS = 20
MAX_CONDITIONS = 10
#: Deepest nesting of `all` / `any` / `not` inside one condition.
MAX_CONDITION_DEPTH = 4
MAX_IN_VALUES = 20
MAX_SORT = 3
MAX_TEXT_CHARS = 20_000
MAX_TREE_BYTES = 512_000
MAX_ERRORS = 50

ORIENTATIONS = ("portrait", "landscape")
DIRECTIONS = ("both", "outgoing", "incoming")
DEFAULT_RECORD_ALIAS = "record"
DEFAULT_GROUP_ALIAS = "group"
DEFAULT_JOIN_ALIAS = "joined"
MAX_JOINS = 5

#: Operators a field of each kind accepts. `empty`/`not_empty` take no value; `in` takes a list.
OPERATORS_BY_KIND: dict[str, tuple[str, ...]] = {
    "text": ("eq", "ne", "contains", "in", "not_in", "empty", "not_empty"),
    "principal": ("eq", "ne", "contains", "in", "not_in", "empty", "not_empty"),
    "enum": ("eq", "ne", "in", "not_in", "empty", "not_empty"),
    "number": ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "empty", "not_empty"),
    "date": ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "empty", "not_empty"),
    "instant": ("gt", "gte", "lt", "lte", "empty", "not_empty"),
    "bool": ("eq", "ne"),
}
VALUELESS_OPERATORS = ("empty", "not_empty")
#: Operators that take a list of values: the field matches when it equals any (`in`) or none (`not_in`) of them.
LIST_OPERATORS = ("in", "not_in")
#: The boolean keys of a condition node: `all` / `any` hold two or more conditions, `not` holds one.
BOOLEAN_KEYS = ("all", "any", "not")

#: What a group exposes to `{{alias.value}}`, `{{alias.count}}` and conditions.
GROUP_FIELDS: dict[str, str] = {"value": "text", "count": "number"}

_ALIAS = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
#: `{{name}}` (a global placeholder) or `{{alias.field}}`.
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)(?:\.([a-z][a-z0-9_]*))?\s*\}\}")
_SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")

Ref = tuple[str, str]
#: Stands for an absent key when passed to `TreeValidator.text`.
MISSING: Any = object()


@dataclass(frozen=True)
class TreeError:
    """One problem found in a tree.

    Attributes:
        path: Where, e.g. `nodes[2].children[0].columns[1].field`.
        message: What is wrong, written for the author.
    """

    path: str
    message: str


@dataclass
class TreeAnalysis:
    """The outcome of validating a tree.

    Attributes:
        errors: Problems found (empty when valid), at most `MAX_ERRORS`.
        refs: For each container/source block (keyed by `id(node)` of the validated tree), the
            `(record type, field key)` pairs used anywhere in its subtree.
        node_count: Blocks in the tree.
    """

    errors: list[TreeError] = field(default_factory=list)
    refs: dict[int, frozenset[Ref]] = field(default_factory=dict)
    node_count: int = 0

    @property
    def ok(self) -> bool:
        """Whether the tree is valid."""
        return not self.errors


class InvalidLayoutError(ValueError):
    """A tree failed validation; `errors` lists every problem found."""

    def __init__(self, errors: list[TreeError]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{e.path}: {e.message}" for e in errors[:5]) or "invalid layout")


@dataclass(frozen=True)
class Binding:
    """What an alias stands for while validating: one record, or one group of records.

    Attributes:
        kind: `record` or `group`.
        record_type: The artefact type of the record (or of the group's members).
    """

    kind: str
    record_type: str


@dataclass(frozen=True)
class BlockSpec:
    """How one block type is validated (and, in `report_layout_eval`, evaluated).

    Attributes:
        key: The `type` value in a node.
        families: The layout families that may contain it.
        validate: `(validator, node, path)` — checks the node's own keys and recurses into children.
    """

    key: str
    families: tuple[str, ...]
    validate: Callable[[TreeValidator, dict[str, Any], str], None]


BLOCK_SPECS: dict[str, BlockSpec] = {}


def register_block_spec(spec: BlockSpec) -> None:
    """Adds a block type (for widgets, equations and the like).

    Raises:
        ValueError: The key is already registered.
    """
    if spec.key in BLOCK_SPECS:
        raise ValueError(f"block type {spec.key!r} is already registered")
    BLOCK_SPECS[spec.key] = spec


def tree_hash(tree: dict[str, Any]) -> str:
    """SHA-256 hex of the tree's canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(tree, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def empty_tree(family: str) -> dict[str, Any]:
    """A valid tree with no blocks."""
    tree: dict[str, Any] = {"schema_version": TREE_SCHEMA_VERSION, "family": family, "nodes": []}
    if family == FAMILY_DOCUMENT:
        tree["orientation"] = "portrait"
    return tree


def validate_tree(tree: Any, *, family: str | None = None) -> TreeAnalysis:
    """Validates a layout tree.

    Args:
        tree: The parsed JSON.
        family: The layout's family; when given, the tree must declare the same one.

    Returns:
        The analysis; `errors` is empty when the tree may be saved and run.
    """
    return TreeValidator().run(tree, family)


def assert_valid(tree: Any, *, family: str | None = None) -> TreeAnalysis:
    """`validate_tree`, raising when invalid.

    Raises:
        InvalidLayoutError: With every problem found.
    """
    analysis = validate_tree(tree, family=family)
    if analysis.errors:
        raise InvalidLayoutError(analysis.errors)
    return analysis


class TreeValidator:
    """Walks a tree once, collecting errors, field references and scope (aliases) as it goes.

    Block validators (`BlockSpec.validate`) call the helper methods below; they never raise, they
    record errors and carry on so the author sees every problem in one pass.
    """

    def __init__(self) -> None:
        self.analysis = TreeAnalysis()
        self.family = FAMILY_DOCUMENT
        self.scope: dict[str, Binding] = {}
        self._collectors: list[set[Ref]] = []
        self._catalogues: dict[str, dict[str, FieldInfo] | None] = {}
        self._sheet_names: set[str] = set()
        self.widget_reports: set[str] = set()

    # --- driver ----------------------------------------------------------------------------

    def run(self, tree: Any, family: str | None) -> TreeAnalysis:
        """Validates `tree` (see `validate_tree`)."""
        if not isinstance(tree, dict):
            self.error("", "The layout must be an object.")
            return self.analysis
        try:
            size = len(json.dumps(tree, ensure_ascii=False))
        except (TypeError, ValueError):
            self.error("", "The layout must be plain JSON.")
            return self.analysis
        if size > MAX_TREE_BYTES:
            self.error("", f"The layout is too large ({size} bytes; the limit is {MAX_TREE_BYTES}).")
            return self.analysis

        self.check_keys(tree, "", required=("schema_version", "family", "nodes"), optional=("orientation",))
        if tree.get("schema_version") != TREE_SCHEMA_VERSION:
            self.error("schema_version", f"Must be {TREE_SCHEMA_VERSION}.")
        declared = tree.get("family")
        if declared not in LAYOUT_FAMILIES:
            self.error("family", f"Must be one of: {', '.join(LAYOUT_FAMILIES)}.")
            return self.analysis
        if family is not None and declared != family:
            self.error("family", f"This layout is a {family} layout; the tree says {declared}.")
        self.family = declared
        if "orientation" in tree:
            if declared != FAMILY_DOCUMENT:
                self.error("orientation", "Only a document layout has a page orientation.")
            elif tree["orientation"] not in ORIENTATIONS:
                self.error("orientation", f"Must be one of: {', '.join(ORIENTATIONS)}.")
        nodes = tree.get("nodes")
        if isinstance(nodes, list):
            self.nodes(nodes, "nodes", 1)
        elif "nodes" in tree:
            self.error("nodes", "Must be a list of blocks.")
        return self.analysis

    def error(self, path: str, message: str) -> None:
        """Records a problem (silently dropped past `MAX_ERRORS`)."""
        if len(self.analysis.errors) < MAX_ERRORS:
            self.analysis.errors.append(TreeError(path, message))

    def nodes(self, nodes: Any, path: str, depth: int) -> None:
        """Validates a list of blocks at nesting `depth` (1 = top level)."""
        if not isinstance(nodes, list):
            self.error(path, "Must be a list of blocks.")
            return
        if depth > MAX_DEPTH:
            self.error(path, f"Blocks are nested too deeply (the limit is {MAX_DEPTH} levels).")
            return
        for i, node in enumerate(nodes):
            self.node(node, f"{path}[{i}]", depth)

    def node(self, node: Any, path: str, depth: int) -> None:
        """Validates one block."""
        self.analysis.node_count += 1
        if self.analysis.node_count == MAX_NODES + 1:
            self.error(path, f"The layout has too many blocks (the limit is {MAX_NODES}).")
        if self.analysis.node_count > MAX_NODES:
            return
        if not isinstance(node, dict):
            self.error(path, "A block must be an object.")
            return
        key = node.get("type")
        spec = BLOCK_SPECS.get(key) if isinstance(key, str) else None
        if spec is None:
            known = ", ".join(sorted(k for k, s in BLOCK_SPECS.items() if self.family in s.families))
            self.error(f"{path}.type", f"Unknown block type {key!r}. Use one of: {known}.")
            return
        if self.family not in spec.families:
            self.error(f"{path}.type", f"A {key} block cannot be used in a {self.family} layout.")
            return
        spec.validate(self, node, path)

    def children(self, node: dict[str, Any], path: str, key: str = "children") -> None:
        """Validates `node[key]` as the child blocks of a container (one level deeper)."""
        if key not in node:
            return
        self.nodes(node[key], f"{path}.{key}", self._depth_of(path) + 1)

    def _depth_of(self, path: str) -> int:
        """The nesting depth of the block at `path` (`nodes[0].children[1]` is 2)."""
        return path.count(".children[") + path.count(".else_children[") + 1

    # --- shape helpers ---------------------------------------------------------------------

    def check_keys(
        self, node: dict[str, Any], path: str, *, required: tuple[str, ...] = (), optional: tuple[str, ...] = (),
    ) -> None:
        """Errors for a missing required key and for any key not listed."""
        for key in required:
            if key not in node:
                self.error(f"{path}.{key}" if path else key, "Required.")
        allowed = {*required, *optional}
        for key in node:
            if key not in allowed:
                self.error(f"{path}.{key}" if path else key, "Unknown key.")

    def text(self, value: Any, path: str, *, limit: int = MAX_TEXT_CHARS, allow_empty: bool = False) -> str | None:
        """A string within `limit` characters; `None` (and an error) otherwise.

        A key that is absent has already been reported as missing by `check_keys`, so `value` is
        then the `MISSING` marker and adds no second error.
        """
        if value is MISSING:
            return None
        if not isinstance(value, str):
            self.error(path, "Must be text.")
            return None
        if not value.strip() and not allow_empty:
            self.error(path, "Must not be empty.")
            return None
        if len(value) > limit:
            self.error(path, f"Too long ({len(value)} characters; the limit is {limit}).")
            return None
        return value

    def alias(self, value: Any, path: str, default: str) -> str:
        """The alias a block binds: `value` if valid and unused, else `default` (with an error)."""
        if value is None:
            chosen = default
        elif isinstance(value, str) and _ALIAS.match(value):
            chosen = value
        else:
            self.error(path, "Must be lower-case letters, digits and underscores, starting with a letter (max 32).")
            return default
        if chosen in self.scope:
            self.error(
                path if value is not None else path.rsplit(".", 1)[0],
                f'The name "{chosen}" is already used by an enclosing block; give this block its own with "as".',
            )
        return chosen

    # --- registry helpers ------------------------------------------------------------------

    def fields_of(self, record_type: str) -> dict[str, FieldInfo] | None:
        """The fields a layout may use for `record_type`, or `None` when it is not reportable."""
        if record_type not in self._catalogues:
            try:
                self._catalogues[record_type] = {f.key: f for f in field_catalogue(record_type)}
            except UnknownReportFieldError:
                self._catalogues[record_type] = None
        return self._catalogues[record_type]

    def record_field(self, record_type: str, key: Any, path: str) -> FieldInfo | None:
        """Checks `key` is a field of `record_type`, notes the reference and returns the field."""
        fields = self.fields_of(record_type)
        if not isinstance(key, str) or fields is None or key not in fields:
            known = ", ".join(sorted(fields)) if fields else ""
            self.error(path, f'"{key}" is not a field of {record_type}. Fields: {known}.')
            return None
        self.add_ref(record_type, key)
        return fields[key]

    def add_ref(self, record_type: str, key: str) -> None:
        """Notes that the active blocks need `key` of `record_type`."""
        for collector in self._collectors:
            collector.add((record_type, key))

    @contextmanager
    def collecting(self, node: dict[str, Any]) -> Iterator[None]:
        """Collects every field reference made inside the `with` body onto `node`'s analysis entry."""
        refs: set[Ref] = set()
        self._collectors.append(refs)
        try:
            yield
        finally:
            self._collectors.pop()
            self.analysis.refs[id(node)] = frozenset(refs)

    @contextmanager
    def binding(self, alias: str, binding: Binding) -> Iterator[None]:
        """Makes `alias` available to the blocks inside the `with` body."""
        previous = self.scope.get(alias)
        self.scope[alias] = binding
        try:
            yield
        finally:
            if previous is None:
                del self.scope[alias]
            else:  # a duplicate name was already reported; keep the enclosing block's meaning
                self.scope[alias] = previous

    # --- composite checks used by several blocks -------------------------------------------

    def source(self, src: Any, path: str) -> str | None:
        """Validates a source (where a block's records come from) and returns its record type.

        A source is exactly one of: a root (`record_type`), a linked set (`record_type` +
        `linked_from`), or a group's members (`group`); each may add `where` and `sort`.
        """
        if not isinstance(src, dict):
            self.error(path, "Must be an object.")
            return None
        self.check_keys(
            src, path,
            optional=("record_type", "linked_from", "link_types", "direction", "group", "where", "sort", "include_archived"),
        )
        record_type: str | None = None
        if "group" in src:
            for bad in ("record_type", "linked_from", "link_types", "direction", "include_archived"):
                if bad in src:
                    self.error(f"{path}.{bad}", 'Not allowed with "group": the records are the group\'s members.')
            binding = self._bound(src["group"], f"{path}.group", "group")
            record_type = binding.record_type if binding else None
        else:
            rtype = src.get("record_type")
            if not isinstance(rtype, str) or self.fields_of(rtype) is None:
                reportable = ", ".join(sorted(get_report_field_providers()))
                self.error(f"{path}.record_type", f"Must be a reportable record type: {reportable}.")
            else:
                record_type = rtype
            if "linked_from" in src:
                self._bound(src["linked_from"], f"{path}.linked_from", "record")
            else:
                for bad in ("link_types", "direction"):
                    if bad in src:
                        self.error(f"{path}.{bad}", 'Only used with "linked_from".')
            if "link_types" in src:
                names = src["link_types"]
                if not isinstance(names, list) or len(names) > 20 or not all(
                    isinstance(n, str) and 0 < len(n) <= 200 for n in names
                ):
                    self.error(f"{path}.link_types", "Must be a list of up to 20 link type names.")
            if "direction" in src and src["direction"] not in DIRECTIONS:
                self.error(f"{path}.direction", f"Must be one of: {', '.join(DIRECTIONS)}.")
            if "include_archived" in src and not isinstance(src["include_archived"], bool):
                self.error(f"{path}.include_archived", "Must be true or false.")
        if record_type is not None:
            self.conditions(src.get("where", []), f"{path}.where", record_type)
            self.sort(src.get("sort", []), f"{path}.sort", record_type)
        return record_type

    def _bound(self, alias: Any, path: str, kind: str) -> Binding | None:
        """The binding `alias` names, requiring it to be a `kind` (record or group)."""
        binding = self.scope.get(alias) if isinstance(alias, str) else None
        if binding is None:
            self.error(path, f'"{alias}" is not the name of an enclosing block. In scope: {", ".join(self.scope) or "nothing"}.')
            return None
        if binding.kind != kind:
            self.error(path, f'"{alias}" is a {binding.kind}, not a {kind}.')
            return None
        return binding

    def conditions(self, conds: Any, path: str, record_type: str) -> None:
        """Validates a `where` list over `record_type`: every entry must hold (an implicit `all`).

        An entry is a condition `{field, op, value}` or a boolean node (see `condition_node`).
        """
        if not isinstance(conds, list):
            self.error(path, f"Must be a list of at most {MAX_CONDITIONS} conditions.")
            return
        leaves = [0]
        for i, cond in enumerate(conds):
            self.condition_node(cond, f"{path}[{i}]", leaf=lambda c, here: self._record_leaf(c, here, record_type), leaves=leaves)
        if leaves[0] > MAX_CONDITIONS:
            self.error(path, f"Too many conditions ({leaves[0]}; the limit is {MAX_CONDITIONS}).")

    def _record_leaf(self, cond: dict[str, Any], path: str, record_type: str) -> None:
        """A `{field, op, value}` condition over a record's fields."""
        self.check_keys(cond, path, required=("field", "op"), optional=("value",))
        info = self.record_field(record_type, cond.get("field"), f"{path}.field")
        if info is not None:
            self.operator_and_value(cond, path, info.kind)

    def condition_node(
        self, node: Any, path: str, *, leaf: Callable[[dict[str, Any], str], None], leaves: list[int], depth: int = 1,
    ) -> None:
        """Validates a condition: a leaf, or `{"all": [...]}` / `{"any": [...]}` (two or more) / `{"not": cond}`.

        Args:
            node: The condition.
            path: Where it is.
            leaf: Validates a leaf condition's own keys (it differs between a source's `where` and an `if`).
            leaves: A one-item counter of leaves seen, so a `where` can be capped as a whole.
            depth: Nesting depth of boolean nodes so far (1 = outermost).
        """
        if not isinstance(node, dict):
            self.error(path, "Must be an object.")
            return
        boolean = [k for k in BOOLEAN_KEYS if k in node]
        if not boolean:
            leaves[0] += 1
            if leaves[0] <= MAX_CONDITIONS:
                leaf(node, path)
            return
        if len(node) != 1:
            self.error(path, f'A "{boolean[0]}" condition has no other keys.')
            return
        if depth > MAX_CONDITION_DEPTH:
            self.error(path, f"Conditions are nested too deeply (the limit is {MAX_CONDITION_DEPTH} levels).")
            return
        key = boolean[0]
        body = node[key]
        if key == "not":
            self.condition_node(body, f"{path}.not", leaf=leaf, leaves=leaves, depth=depth + 1)
            return
        if not isinstance(body, list) or len(body) < 2:
            self.error(f"{path}.{key}", f'"{key}" needs a list of two or more conditions (use the condition itself for one).')
            return
        for i, child in enumerate(body):
            self.condition_node(child, f"{path}.{key}[{i}]", leaf=leaf, leaves=leaves, depth=depth + 1)

    def operator_and_value(self, cond: dict[str, Any], path: str, kind: str) -> None:
        """Checks `cond["op"]` suits the field `kind` and `cond["value"]` is a literal (or, for `in`, a list) of that kind."""
        allowed = OPERATORS_BY_KIND.get(kind, ())
        op = cond.get("op")
        if op not in allowed:
            self.error(f"{path}.op", f"A {kind} field accepts: {', '.join(allowed)}.")
            return
        if op in VALUELESS_OPERATORS:
            if "value" in cond:
                self.error(f"{path}.value", f'Not used with "{op}".')
            return
        if "value" not in cond:
            self.error(f"{path}.value", "Required.")
            return
        value = cond["value"]
        if op in LIST_OPERATORS:
            if not isinstance(value, list) or not 0 < len(value) <= MAX_IN_VALUES:
                self.error(f"{path}.value", f"Must be a list of 1 to {MAX_IN_VALUES} values.")
                return
            for i, item in enumerate(value):
                problem = literal_problem(kind, item)
                if problem:
                    self.error(f"{path}.value[{i}]", problem)
            return
        problem = literal_problem(kind, value)
        if problem:
            self.error(f"{path}.value", problem)

    def sort(self, items: Any, path: str, record_type: str) -> None:
        """Validates a `sort` list of `{field, descending?}` over `record_type`."""
        if not isinstance(items, list) or len(items) > MAX_SORT:
            self.error(path, f"Must be a list of at most {MAX_SORT} sort keys.")
            return
        for i, item in enumerate(items):
            here = f"{path}[{i}]"
            if not isinstance(item, dict):
                self.error(here, "Must be an object.")
                continue
            self.check_keys(item, here, required=("field",), optional=("descending",))
            self.record_field(record_type, item.get("field"), f"{here}.field")
            if "descending" in item and not isinstance(item["descending"], bool):
                self.error(f"{here}.descending", "Must be true or false.")

    def columns(self, cols: Any, path: str, record_type: str, *, aliases: dict[str, str] | None = None) -> None:
        """Validates a table's `columns` list of `{field, label?}` over `record_type`.

        Args:
            cols: The columns.
            path: Where they are.
            record_type: The type a column's field belongs to unless it says otherwise.
            aliases: For a sheet with joins, `{alias: record type}`; a column may then name the record
                it reads with `from` (default: the sheet's own records).
        """
        if not isinstance(cols, list) or not 0 < len(cols) <= MAX_COLUMNS:
            self.error(path, f"Must be a list of 1 to {MAX_COLUMNS} columns.")
            return
        for i, col in enumerate(cols):
            here = f"{path}[{i}]"
            if not isinstance(col, dict):
                self.error(here, "Must be an object.")
                continue
            self.check_keys(col, here, required=("field",), optional=("label", "from") if aliases else ("label",))
            owner = record_type
            if aliases and "from" in col:
                if col["from"] not in aliases:
                    self.error(f"{here}.from", f'"{col["from"]}" is not a name in this sheet. Use one of: {", ".join(aliases)}.')
                    continue
                owner = aliases[col["from"]]
            self.record_field(owner, col.get("field"), f"{here}.field")
            if "label" in col:
                self.text(col["label"], f"{here}.label", limit=200)

    def placeholders(self, text: str | None, path: str) -> None:
        """Checks every `{{...}}` reference in `text` names a global placeholder or a field in scope."""
        if not text:
            return
        for match in PLACEHOLDER_RE.finditer(text):
            name, member = match.group(1), match.group(2)
            if member is None:
                if name not in PLACEHOLDER_NAMES:
                    self.error(path, f'Unknown placeholder "{{{{{name}}}}}". Global ones: {", ".join(PLACEHOLDER_NAMES)}.')
                continue
            self.reference(name, member, path)

    def reference(self, alias: str, member: str, path: str) -> str | None:
        """Checks `alias.member` is valid in scope, notes the reference and returns the value's kind."""
        binding = self.scope.get(alias)
        if binding is None:
            self.error(path, f'"{alias}" is not the name of an enclosing block. In scope: {", ".join(self.scope) or "nothing"}.')
            return None
        if binding.kind == "group":
            if member not in GROUP_FIELDS:
                self.error(path, f'A group has "value" and "count", not "{member}".')
                return None
            return GROUP_FIELDS[member]
        info = self.record_field(binding.record_type, member, path)
        return info.kind if info else None


def literal_problem(kind: str, value: Any) -> str | None:
    """Why `value` is not a literal of a field `kind` (`None` when it is)."""
    if kind in ("text", "principal", "enum"):
        return None if isinstance(value, str) and len(value) <= 200 else "Must be text of at most 200 characters."
    if kind == "number":
        return None if isinstance(value, int | float) and not isinstance(value, bool) else "Must be a number."
    if kind == "bool":
        return None if isinstance(value, bool) else "Must be true or false."
    if kind == "date":
        try:
            ok = isinstance(value, str) and len(value) == 10 and date.fromisoformat(value) is not None
        except ValueError:
            ok = False
        return None if ok else "Must be a date as YYYY-MM-DD."
    if kind == "instant":
        try:
            ok = isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        except ValueError:
            ok = False
        return None if ok else "Must be a UTC date and time such as 2026-10-26T09:00:00Z."
    return "Unsupported field kind."


# --- block types -------------------------------------------------------------------------------


def _validate_heading(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "text"), optional=("level",))
    v.placeholders(v.text(node.get("text", MISSING), f"{path}.text", limit=500), f"{path}.text")
    if "level" in node and (not isinstance(node["level"], int) or isinstance(node["level"], bool) or not 1 <= node["level"] <= 4):
        v.error(f"{path}.level", "Must be 1 to 4.")


def _validate_text(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "text"))
    v.placeholders(v.text(node.get("text", MISSING), f"{path}.text"), f"{path}.text")


def _validate_page_break(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type",))


def _validate_table(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "source", "columns"), optional=("empty_text",))
    with v.collecting(node):
        record_type = v.source(node.get("source"), f"{path}.source")
        if record_type is not None:
            v.columns(node.get("columns"), f"{path}.columns", record_type)
    if "empty_text" in node:
        v.placeholders(v.text(node["empty_text"], f"{path}.empty_text", limit=500), f"{path}.empty_text")


def _validate_each(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "source", "children"), optional=("as", "empty_text"))
    with v.collecting(node):
        record_type = v.source(node.get("source"), f"{path}.source")
        alias = v.alias(node.get("as"), f"{path}.as", DEFAULT_RECORD_ALIAS)
        if record_type is not None:
            with v.binding(alias, Binding("record", record_type)):
                v.children(node, path)
    if "empty_text" in node:
        v.placeholders(v.text(node["empty_text"], f"{path}.empty_text", limit=500), f"{path}.empty_text")


def _validate_group(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "source", "by", "children"), optional=("as",))
    with v.collecting(node):
        record_type = v.source(node.get("source"), f"{path}.source")
        alias = v.alias(node.get("as"), f"{path}.as", DEFAULT_GROUP_ALIAS)
        if record_type is not None:
            v.record_field(record_type, node.get("by"), f"{path}.by")
            with v.binding(alias, Binding("group", record_type)):
                v.children(node, path)


def _validate_if(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "when", "children"), optional=("else_children",))
    if "when" in node:
        v.condition_node(node["when"], f"{path}.when", leaf=_validate_if_leaf(v), leaves=[0])
    v.children(node, path)
    v.children(node, path, "else_children")


def _validate_if_leaf(v: TreeValidator) -> Callable[[dict[str, Any], str], None]:
    """Validates one `{ref, op, value}` test of an `if` (`ref` is `name.field` of an enclosing block)."""

    def leaf(when: dict[str, Any], path: str) -> None:
        v.check_keys(when, path, required=("ref", "op"), optional=("value",))
        ref = when.get("ref")
        parts = ref.split(".") if isinstance(ref, str) else []
        if len(parts) != 2:
            v.error(f"{path}.ref", 'Must be "name.field", for example "record.status".')
            return
        kind = v.reference(parts[0], parts[1], f"{path}.ref")
        if kind is not None:
            v.operator_and_value(when, path, kind)

    return leaf


def _validate_widget_sort(v: TreeValidator, items: Any, path: str) -> None:
    """A widget's `sort`: one to `MAX_SORT` `{column, descending?}` keys, by the heading of a column of its table.

    The columns of a report's table are only known when the report runs, so a name that matches none is reported
    then (a warning), not here.
    """
    if not isinstance(items, list) or not 0 < len(items) <= MAX_SORT:
        v.error(path, f"Must be a list of 1 to {MAX_SORT} sort keys (leave sort out for the report's own order).")
        return
    for i, item in enumerate(items):
        here = f"{path}[{i}]"
        if not isinstance(item, dict):
            v.error(here, "Must be an object.")
            continue
        v.check_keys(item, here, required=("column",), optional=("descending",))
        v.text(item.get("column", MISSING), f"{here}.column", limit=200)
        if "descending" in item and not isinstance(item["descending"], bool):
            v.error(f"{here}.descending", "Must be true or false.")


def _validate_widget(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "key"), optional=("params", "empty_text", "sort"))
    key = v.text(node.get("key", MISSING), f"{path}.key", limit=100)
    if "sort" in node:
        _validate_widget_sort(v, node["sort"], f"{path}.sort")
    if "empty_text" in node:
        v.placeholders(v.text(node["empty_text"], f"{path}.empty_text", limit=500), f"{path}.empty_text")
    if key is None:
        return
    widget = find_widget(key)
    if widget is None:
        v.error(f"{path}.key", f'Unknown widget "{key}". Widgets: {", ".join(w.key for w in list_widgets())}.')
        return
    if "params" in node:
        problems = param_problems(widget, node["params"])
        for name, message in problems:
            v.error(f"{path}.params.{name}" if name else f"{path}.params", message)
        if problems:
            return
    run = f"{widget.report_key}|{json.dumps(node.get('params', {}), sort_keys=True, separators=(',', ':'))}"
    if run not in v.widget_reports:
        v.widget_reports.add(run)
        if len(v.widget_reports) == MAX_WIDGET_REPORTS + 1:
            v.error(
                path,
                f"The widgets run too many different reports (the limit is {MAX_WIDGET_REPORTS}; widgets of one report "
                "with the same settings share a run).",
            )


def _validate_sheet(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "name", "source", "columns"), optional=("as", "joins"))
    name = v.text(node.get("name", MISSING), f"{path}.name", limit=31)
    if name is not None:
        if _SHEET_NAME_BAD.search(name) or name.startswith("'") or name.endswith("'"):
            v.error(f"{path}.name", "A sheet name cannot contain [ ] : * ? / \\ or start or end with an apostrophe.")
        elif name.casefold() in v._sheet_names:
            v.error(f"{path}.name", f'Another sheet is already called "{name}".')
        v._sheet_names.add(name.casefold())
    with v.collecting(node), ExitStack() as stack:
        record_type = v.source(node.get("source"), f"{path}.source")
        root_alias = v.alias(node.get("as"), f"{path}.as", DEFAULT_RECORD_ALIAS)
        if record_type is None:
            return
        aliases = {root_alias: record_type}
        stack.enter_context(v.binding(root_alias, Binding("record", record_type)))
        joins = node.get("joins", [])
        if not isinstance(joins, list) or len(joins) > MAX_JOINS:
            v.error(f"{path}.joins", f"Must be a list of at most {MAX_JOINS} joins.")
            joins = []
        for i, join in enumerate(joins):
            here = f"{path}.joins[{i}]"
            if not isinstance(join, dict):
                v.error(here, "Must be an object.")
                continue
            v.check_keys(join, here, required=("as", "source"))
            # Entered before the join's source so its own where/sort fields, and every column that reads
            # from it, are attributed to the join and loaded for it.
            stack.enter_context(v.collecting(join))
            source = join.get("source")
            if isinstance(source, dict) and "linked_from" not in source:
                v.error(f"{here}.source.linked_from", "A join follows links from an earlier name in the sheet.")
            join_type = v.source(source, f"{here}.source")
            alias = v.alias(join.get("as"), f"{here}.as", DEFAULT_JOIN_ALIAS)
            if join_type is not None:
                aliases[alias] = join_type
                stack.enter_context(v.binding(alias, Binding("record", join_type)))
        v.columns(node.get("columns"), f"{path}.columns", record_type, aliases=aliases)


for _spec in (
    BlockSpec("heading", (FAMILY_DOCUMENT,), _validate_heading),
    BlockSpec("text", (FAMILY_DOCUMENT,), _validate_text),
    BlockSpec("page_break", (FAMILY_DOCUMENT,), _validate_page_break),
    BlockSpec("table", (FAMILY_DOCUMENT,), _validate_table),
    BlockSpec("each", (FAMILY_DOCUMENT,), _validate_each),
    BlockSpec("group", (FAMILY_DOCUMENT,), _validate_group),
    BlockSpec("if", (FAMILY_DOCUMENT,), _validate_if),
    BlockSpec("widget", (FAMILY_DOCUMENT,), _validate_widget),
    BlockSpec("sheet", (FAMILY_TABLE,), _validate_sheet),
):
    register_block_spec(_spec)

__all__ = [
    "BLOCK_SPECS", "BOOLEAN_KEYS", "DEFAULT_GROUP_ALIAS", "DEFAULT_JOIN_ALIAS", "DEFAULT_RECORD_ALIAS", "GROUP_FIELDS",
    "LIST_OPERATORS", "MAX_COLUMNS", "MAX_CONDITION_DEPTH", "MAX_DEPTH", "MAX_JOINS", "MAX_NODES", "MAX_TREE_BYTES",
    "MAX_WIDGET_REPORTS", "OPERATORS_BY_KIND", "PLACEHOLDER_RE", "TREE_SCHEMA_VERSION", "Binding", "BlockSpec",
    "InvalidLayoutError", "Ref", "TreeAnalysis", "TreeError", "TreeValidator", "assert_valid", "empty_tree",
    "literal_problem", "register_block_spec", "tree_hash", "validate_tree",
]
