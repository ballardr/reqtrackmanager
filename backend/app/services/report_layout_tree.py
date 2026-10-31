"""
Module: services.report_layout_tree

The layout tree: the versioned JSON a person authors for a custom report, and the validator that
decides whether a tree may be saved or run.

Responsibilities:
- Define the tree vocabulary (`TREE_SCHEMA_VERSION`): document blocks `heading`, `text`, `table`,
  `each`, `group`, `if`, `page_break`, `section` (its contents in another page style), `equation` (display TeX),
  `image` (a picture from the layout tier's image library, with size, alignment, caption and alt text),
  `widget` (one component of a module report, by key), and the table-family block `sheet` (a root source plus
  optional left `joins` along links, one row per combination).
- Validate a tree with positioned errors (`validate_tree`): shape, unknown keys, depth/node/size
  caps, record types and field names against the report field registry, operators and values per
  field kind, conditions combined with `all` / `any` / `not`, aliases in scope and `{{alias.field}}`
  placeholders.
- Report, per container block, which `(record type, field)` pairs its subtree needs, so the
  evaluator loads exactly those columns (`TreeAnalysis.refs`).
- Hash a tree (`tree_hash`) for versioning and provenance.
- Let an `if` test whether a module is available in the project being run (`{"module": key}`), so a layout that
  spans modules leaves out the parts of one that is off instead of printing an empty section.
- Check a `widget` block names a component in the widget catalogue (`services.report_widgets`)
  and sets only parameters that report declares, with values of the declared type.
- Check a layout's run-time `variables` (typed values supplied when it runs: `services.report_variables`) and that
  every reference to one (`{"var": name}` as a condition value or widget parameter, `{{var.name}}` in text) names a
  declared variable of a type that fits.
- Check TeX at save time against the allow-list in `services.report_math` (an `equation` block's `tex`, and the
  `\\( \\)` / `$$ $$` equations written in a text block); the extension point `register_block_spec` stays open for
  other block types.

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

Dependencies: `services.report_math` (TeX allow-list), `services.report_variables` (variable vocabulary),
`services.report_fields` (field catalogue), `services.report_widgets` (widget catalogue), `modules.registry`
(reportable types), `services.report_model` (the allow-listed global placeholder names).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from app.models.report_layout import FAMILY_DOCUMENT, FAMILY_TABLE, LAYOUT_FAMILIES
from app.modules.registry import (
    get_module_registry,
    get_no_record_attachment_reasons,
    get_record_attachment_providers,
    get_report_field_providers,
)
from app.services.report_fields import FieldInfo, UnknownReportFieldError, field_catalogue
from app.services.report_file_names import template_problems
from app.services.report_layout_block_schema import BlockContainer, BlockField, BlockProvides, BlockSchema
from app.services.report_math import MAX_TEX_CHARS, split_math, tex_problem
from app.services.report_model import CELL_ARRANGEMENTS, CONTENTS_SHEET_NAME, PLACEHOLDER_NAMES, PLACEHOLDER_RE
from app.services.report_org_values import ORG_FAMILY, ORG_LOGO_FILE, ORG_VALUE_KEYS, org_value_kind
from app.services.report_page_styles import (
    ORIENTATIONS,
    PAGE_FIELD_NAMES,
    PAGE_SIZES,
    document_style_problems,
    resolve_page_styles,
    styles_problems,
)
from app.services.report_variables import (
    FIELD_KINDS,
    MAX_LIST_VALUES,
    MAX_OPTIONS,
    MAX_VARIABLES,
    NAME_RE,
    PARAM_TYPES,
    PLACEHOLDER_FAMILY,
    TODAY,
    VARIABLE_TYPES,
    is_reference,
    value_problem,
)
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
MAX_ALT_CHARS = 300
MAX_CAPTION_CHARS = 500
#: Bounds of an image block's size per unit: a width in cm, mm or as a percentage of the text width, and a height in cm or mm.
IMAGE_SIZE_BOUNDS: dict[str, tuple[float, float]] = {"cm": (0.5, 100.0), "mm": (5.0, 1000.0), "percent": (1.0, 100.0)}
IMAGE_UNITS = ("cm", "mm", "percent")
IMAGE_HEIGHT_UNITS = ("cm", "mm")
#: How a caption is numbered: `auto` (a captioned picture is, a bare one is not), `always` or `never`.
IMAGE_NUMBERING = ("auto", "always", "never")
IMAGE_ALIGNMENTS = ("left", "center", "right")
IMAGE_CAPTION_POSITIONS = ("above", "below")
IMAGE_PLACEMENTS = ("inline", "wrap", "behind", "front")
IMAGE_ANCHORS = ("paragraph", "margin", "page")
IMAGE_OFFSET_LIMIT_CM = 100.0
#: A record-images block (the pictures attached to a record): allowed file extensions, the limits on its name patterns and
#: count, the orderings, the caption sources and the placements it offers (a picture layered over the text has no meaning
#: for a picture per record).
RECORD_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp", "svg")
MAX_NAME_PATTERNS = 10
MAX_PATTERN_CHARS = 200
MAX_PATTERN_STARS = 4
MAX_PICTURES_PER_RECORD = 20
MAX_PICTURE_MEGABYTES = 50
RECORD_IMAGE_ORDERS = ("name", "uploaded")
RECORD_IMAGE_CAPTIONS = ("file_name", "text", "none")
RECORD_IMAGE_PLACEMENTS = ("inline", "wrap")
MAX_TREE_BYTES = 512_000
MAX_ERRORS = 50

DIRECTIONS = ("both", "outgoing", "incoming")
DEFAULT_RECORD_ALIAS = "record"
#: The name an image column's file name patterns use for the row's own record (`{{row.code}}`).
ROW_ALIAS = "row"
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
        schema: What the visual designer offers for it (`report_layout_block_schema`); a type without one is
            shown there as raw JSON, so every type should declare it (a test requires it).
    """

    key: str
    families: tuple[str, ...]
    validate: Callable[[TreeValidator, dict[str, Any], str], None]
    schema: BlockSchema | None = None


BLOCK_SPECS: dict[str, BlockSpec] = {}


def register_block_spec(spec: BlockSpec) -> None:
    """Adds a block type (for widgets, equations and the like).

    Raises:
        ValueError: The key is already registered.
    """
    if spec.key in BLOCK_SPECS:
        raise ValueError(f"block type {spec.key!r} is already registered")
    BLOCK_SPECS[spec.key] = spec


def record_types_of(tree: Any) -> list[str]:
    """The record types a tree reads, sorted: every source's `record_type` (a block's, a sheet's or a join's) and the
    types the report behind each `widget` block names (`ReportDefinition.record_types`).

    Used by the catalogue so a record list can offer the reports that use its type. The tree is only walked, not
    validated, so an unknown widget or a malformed node adds nothing.

    Args:
        tree: A layout tree (any JSON value is tolerated).

    Returns:
        The distinct type keys, alphabetically.
    """
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            source = value.get("source")
            if isinstance(source, dict) and isinstance(source.get("record_type"), str):
                found.add(source["record_type"])
            key = value.get("key")
            if value.get("type") == "widget" and isinstance(key, str):
                widget = find_widget(key)
                if widget is not None:
                    found.update(widget.definition.record_types)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(tree)
    return sorted(found)


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
        #: `{lower-case sheet name: (name, record type of its rows)}` and the sheet links found, checked once every sheet is known
        #: (a link may name a sheet written after it): `(path, record type of the linked cell, sheet name)`.
        self._sheet_roots: dict[str, tuple[str, str]] = {}
        self._sheet_links: list[tuple[str, str, str]] = []
        #: Whether the layout starts with a generated contents sheet (so no sheet of its own may take its name).
        self.contents_sheet = False
        self.widget_reports: set[str] = set()
        #: `{name: declaration}` of the layout's valid variables (a reference is checked against these).
        self.variables: dict[str, dict[str, Any]] = {}
        #: Names of the layout's page styles, and whether the block being checked is inside a section.
        self.page_style_names: set[str] = set()
        self.in_section = False

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

        self.check_keys(
            tree, "", required=("schema_version", "family", "nodes"),
            optional=(
                "orientation", "page_size", "margins", "mirror_margins", "page_styles", "header", "footer", "variables", "file_name",
                "repeat_table_header", "contents_sheet",
            ),
        )
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
        if "page_size" in tree:
            if declared != FAMILY_DOCUMENT:
                self.error("page_size", "Only a document layout has a page size.")
            elif tree["page_size"] not in PAGE_SIZES:
                self.error("page_size", f"Must be one of: {', '.join(PAGE_SIZES)}.")
        self.page_styles(tree, declared)
        if "repeat_table_header" in tree:
            if declared != FAMILY_DOCUMENT:
                self.error("repeat_table_header", "Only a document layout has pages for a header row to repeat on.")
            elif not isinstance(tree["repeat_table_header"], bool):
                self.error("repeat_table_header", "Must be true or false.")
        if "contents_sheet" in tree:
            if declared != FAMILY_TABLE:
                self.error("contents_sheet", "Only a table layout has sheets for a contents sheet to list.")
            elif not isinstance(tree["contents_sheet"], bool):
                self.error("contents_sheet", "Must be true or false.")
            elif tree["contents_sheet"]:
                self.contents_sheet = True
        if "variables" in tree:
            self.variable_declarations(tree["variables"], "variables")
        if "file_name" in tree:
            for problem in template_problems(tree["file_name"], variables=list(self.variables)):
                self.error("file_name", problem)
        if declared == FAMILY_DOCUMENT:
            self.running_text(tree, "")
            for i, style in enumerate(tree["page_styles"] if isinstance(tree.get("page_styles"), list) else []):
                if isinstance(style, dict):
                    self.running_text(style, f"page_styles[{i}].")
        nodes = tree.get("nodes")
        if isinstance(nodes, list):
            self.nodes(nodes, "nodes", 1)
        elif "nodes" in tree:
            self.error("nodes", "Must be a list of blocks.")
        self.sheet_links()
        return self.analysis

    def sheet_links(self) -> None:
        """Checks every column `link` against the sheets: the sheet exists and lists the linked record's type."""
        for path, owner, target in self._sheet_links:
            found = self._sheet_roots.get(target.casefold())
            if found is None:
                names = ", ".join(name for name, _ in self._sheet_roots.values()) or "none"
                self.error(path, f'No sheet is called "{target}". The sheets are: {names}.')
            elif found[1] != owner:
                self.error(path, f'Sheet "{found[0]}" lists {found[1]} records, not {owner} records, so this cell cannot open its row.')

    def page_styles(self, tree: dict[str, Any], family: str) -> None:
        """Checks the root's margins and page styles and notes the names a `section` block may use."""
        keys = [k for k in ("margins", "mirror_margins", "page_styles", "header", "footer") if k in tree]
        if family != FAMILY_DOCUMENT:
            for key in keys:
                self.error(key, "Only a document layout has pages.")
            return
        if "mirror_margins" in tree and not isinstance(tree["mirror_margins"], bool):
            self.error("mirror_margins", "Must be true or false.")
        for sub, message in document_style_problems(tree):
            self.error(sub, message)
        own_valid = not any(p.path.startswith(("margins", "page_size", "orientation", "header", "footer")) for p in self.analysis.errors)
        if "page_styles" not in tree:
            return
        document = resolve_page_styles({k: v for k, v in tree.items() if k != "page_styles"})[0] if own_valid else None
        if document is None:
            self.error("page_styles", "Fix the document's own page setup first.")
            return
        inherited = {band: tree[band] for band in ("header", "footer") if isinstance(tree.get(band), dict)}
        for sub, message in styles_problems(tree["page_styles"], document, mirror=tree.get("mirror_margins") is True, inherited=inherited):
            self.error(f"page_styles{sub}", message)

        self.page_style_names = {
            style["name"] for style in tree["page_styles"] if isinstance(style, dict) and isinstance(style.get("name"), str)
        }

    def running_text(self, holder: dict[str, Any], prefix: str) -> None:
        """Checks the `{{...}}` names in the cells of a root's or page style's header and footer.

        A header or footer reads the report-wide placeholders, `{{page}}`, `{{pages}}` and run-time variables, but no
        record field (it is printed on every page, outside any record).
        """
        for band in ("header", "footer"):
            cells = holder.get(band)
            if not isinstance(cells, dict):
                continue
            for slot in ("left", "centre", "right"):
                text = cells.get(slot)
                for match in PLACEHOLDER_RE.finditer(text) if isinstance(text, str) else ():
                    name, member = match.group(1), match.group(2)
                    here = f"{prefix}{band}.{slot}"
                    if member is None and name not in (*PLACEHOLDER_NAMES, *PAGE_FIELD_NAMES):
                        self.error(here, f'Unknown placeholder "{{{{{name}}}}}". Use: {", ".join((*PLACEHOLDER_NAMES, *PAGE_FIELD_NAMES))}.')
                    elif member is not None and name == ORG_FAMILY:
                        self.org_value(member, here)
                    elif member is not None and name != PLACEHOLDER_FAMILY:
                        self.error(here, f'"{{{{{name}.{member}}}}}" names a record field, which a header or footer cannot read.')
                    elif member is not None and member not in self.variables:
                        self.error(here, f'"{member}" is not a variable of this layout.')

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
        if chosen == PLACEHOLDER_FAMILY:
            self.error(path, f'The name "{PLACEHOLDER_FAMILY}" is reserved for variables ({{{{var.name}}}}); choose another.')
        if chosen == ORG_FAMILY:
            self.error(path, f'The name "{ORG_FAMILY}" is reserved for the organisation report settings ({{{{org.footer_text}}}}); choose another.')
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
        if isinstance(value, dict):
            self.variable_value(value, f"{path}.value", kind, many=op in LIST_OPERATORS)
            return
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
            if "images" in col:
                self.image_column(col, here, record_type, aliases)
                continue
            self.check_keys(col, here, required=("field",), optional=("label", "from", "link") if aliases else ("label",))
            owner = record_type
            if aliases and "from" in col:
                if col["from"] not in aliases:
                    self.error(f"{here}.from", f'"{col["from"]}" is not a name in this sheet. Use one of: {", ".join(aliases)}.')
                    continue
                owner = aliases[col["from"]]
            self.record_field(owner, col.get("field"), f"{here}.field")
            if "label" in col:
                self.text(col["label"], f"{here}.label", limit=200)
            if aliases and "link" in col:
                self.sheet_link(col["link"], f"{here}.link", owner)

    def sheet_link(self, link: Any, path: str, owner: str) -> None:
        """Validates a column's `link`, `{sheet: <name>}`: the cell opens the row of its record on that sheet.

        The sheet may be written later in the layout, so it is resolved by `sheet_links` once every sheet is known.
        """
        if not isinstance(link, dict):
            self.error(path, "Must be an object like {\"sheet\": \"Requirements\"}.")
            return
        self.check_keys(link, path, required=("sheet",))
        target = self.text(link.get("sheet", MISSING), f"{path}.sheet", limit=31)
        if target is not None:
            self._sheet_links.append((f"{path}.sheet", owner, target))

    def image_column(self, col: dict[str, Any], path: str, record_type: str, aliases: dict[str, str] | None) -> None:
        """Validates a column that shows the pictures attached to each row's record: `{images: {...rules}, label?, from?}`.

        The rules are the record-images block's (name patterns, types, most per record, order, largest file) plus a size
        (a width, default 90 % of the column, and an optional height) and an arrangement. A name pattern may read the row's
        own record as `{{row.field}}`.
        """
        self.check_keys(col, path, required=("images",), optional=("label", "from") if aliases else ("label",))
        owner = record_type
        if aliases and "from" in col:
            if col["from"] not in aliases:
                self.error(f"{path}.from", f'"{col["from"]}" is not a name in this sheet. Use one of: {", ".join(aliases)}.')
                return
            owner = aliases[col["from"]]
        if "label" in col:
            self.text(col["label"], f"{path}.label", limit=200)
        if owner not in get_record_attachment_providers():
            reason = get_no_record_attachment_reasons().get(owner, "Its attachments cannot be printed.")
            self.error(f"{path}.images", f'The pictures of a "{owner}" record cannot be printed. {reason}')
        spec = col["images"]
        here = f"{path}.images"
        if not isinstance(spec, dict):
            self.error(here, "Must be an object (it may be empty).")
            return
        self.check_keys(
            spec, here, required=(),
            optional=("names", "types", "max_count", "order", "max_size_mb", "width", "width_unit", "height", "height_unit", "arrange"),
        )
        with self.binding(ROW_ALIAS, Binding("record", owner)):
            _validate_picture_rules(self, spec, here)
        _image_size(self, spec, "width", "width_unit", IMAGE_UNITS, here, "width")
        _image_size(self, spec, "height", "height_unit", IMAGE_HEIGHT_UNITS, here, "height")
        if "arrange" in spec and spec["arrange"] not in CELL_ARRANGEMENTS:
            self.error(f"{here}.arrange", f"Must be one of: {', '.join(CELL_ARRANGEMENTS)}.")

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
            if name == PLACEHOLDER_FAMILY:
                if member not in self.variables:
                    self.error(path, f'"{member}" is not a variable of this layout. Variables: {", ".join(self.variables) or "none"}.')
                continue
            if name == ORG_FAMILY:
                self.org_value(member, path)
                continue
            self.reference(name, member, path)

    def org_value(self, member: str, path: str) -> str | None:
        """Checks `member` is one of the organisation's report settings a layout may read; returns its kind."""
        kind = org_value_kind(member)
        if kind is None:
            self.error(path, f'"{member}" is not an organisation report setting. Use: {", ".join(ORG_VALUE_KEYS)}.')
        return kind

    # --- run-time variables ----------------------------------------------------------------

    def variable_declarations(self, declarations: Any, path: str) -> None:
        """Validates the root `variables` list and records the valid ones for later references."""
        if not isinstance(declarations, list) or not 0 < len(declarations) <= MAX_VARIABLES:
            self.error(path, f"Must be a list of 1 to {MAX_VARIABLES} variables (leave it out when there are none).")
            return
        for i, declaration in enumerate(declarations):
            here = f"{path}[{i}]"
            if not isinstance(declaration, dict):
                self.error(here, "Must be an object.")
                continue
            self.check_keys(declaration, here, required=("name", "type"), optional=("label", "multiple", "default", "options", "source"))
            name, vtype = declaration.get("name"), declaration.get("type")
            if not isinstance(name, str) or not NAME_RE.match(name):
                self.error(f"{here}.name", "Must be lower-case letters, digits and underscores, starting with a letter (max 32).")
                continue
            if name in self.variables:
                self.error(f"{here}.name", f'Another variable is already called "{name}".')
                continue
            if vtype not in VARIABLE_TYPES:
                self.error(f"{here}.type", f"Must be one of: {', '.join(VARIABLE_TYPES)}.")
                continue
            self._variable_body(declaration, here, name, vtype)
            self.variables[name] = declaration

    def _variable_body(self, declaration: dict[str, Any], path: str, name: str, vtype: str) -> None:
        """Checks the optional keys of one declaration (label, list, options, source, default)."""
        if "label" in declaration:
            self.text(declaration["label"], f"{path}.label", limit=200)
        multiple = declaration.get("multiple", False)
        if not isinstance(multiple, bool):
            self.error(f"{path}.multiple", "Must be true or false.")
            multiple = False
        elif multiple and vtype == "bool":
            self.error(f"{path}.multiple", "A yes/no variable holds one value.")
        options = declaration.get("options")
        if "options" in declaration:
            if vtype != "enum":
                self.error(f"{path}.options", 'Only an "enum" variable has options.')
            elif "source" in declaration:
                self.error(f"{path}.options", 'Give "options" or "source", not both.')
            elif (
                not isinstance(options, list) or not 0 < len(options) <= MAX_OPTIONS
                or not all(value_problem("text", o) is None for o in options) or len(set(options)) != len(options)
            ):
                self.error(f"{path}.options", f"Must be a list of 1 to {MAX_OPTIONS} different texts.")
                options = None
        if "source" in declaration:
            self._variable_source(declaration["source"], f"{path}.source", vtype)
        elif vtype == "enum" and "options" not in declaration:
            self.error(path, 'An "enum" variable needs "options" or a "source" field to offer its values from.')
        if "default" in declaration:
            self._variable_default(declaration["default"], f"{path}.default", vtype, multiple, options)

    def _variable_source(self, source: Any, path: str, vtype: str) -> None:
        """Checks `source` is a field of a reportable type whose values fit the variable's type."""
        if not isinstance(source, dict):
            self.error(path, "Must be an object.")
            return
        self.check_keys(source, path, required=("record_type", "field"))
        record_type, key = source.get("record_type"), source.get("field")
        fields = self.fields_of(record_type) if isinstance(record_type, str) else None
        if fields is None:
            self.error(f"{path}.record_type", f"Must be a reportable record type: {', '.join(sorted(get_report_field_providers()))}.")
        elif not isinstance(key, str) or key not in fields:
            self.error(f"{path}.field", f'"{key}" is not a field of {record_type}. Fields: {", ".join(sorted(fields))}.')
        elif fields[key].kind not in FIELD_KINDS[vtype]:
            self.error(path, f'A {vtype} variable cannot take its values from {record_type}.{key}, which is a {fields[key].kind} field.')

    def _variable_default(self, default: Any, path: str, vtype: str, multiple: bool, options: list[str] | None) -> None:
        """Checks a default is a value (or, for a list, a list of values) of the variable's type."""
        items = default if multiple else [default]
        if multiple and (not isinstance(default, list) or not 0 < len(default) <= MAX_LIST_VALUES):
            self.error(path, f"Must be a list of 1 to {MAX_LIST_VALUES} values.")
            return
        for item in items:
            if vtype == "date" and item == TODAY:
                continue
            problem = value_problem(vtype, item)
            if problem:
                self.error(path, problem)
            elif options is not None and item not in options:
                self.error(path, f"Must be one of the options: {', '.join(options)}.")

    def variable_value(self, ref: Any, path: str, kind: str, *, many: bool) -> None:
        """Checks a condition's `value` reference: a declared variable that fits a field of `kind`.

        Args:
            ref: The `value` (anything but a `{"var": name}` is an error).
            path: Where it is.
            kind: The compared field's kind.
            many: Whether the operator takes a list (`in` / `not_in`), which needs a list variable.
        """
        declaration = self.variable_named(ref, path)
        if declaration is None:
            return
        if kind not in FIELD_KINDS[declaration["type"]]:
            self.error(path, f'The variable "{declaration["name"]}" is of type {declaration["type"]}; this field is a {kind} field.')
        elif many != bool(declaration.get("multiple")):
            self.error(
                path,
                f'"{declaration["name"]}" holds a list, which only "in" and "not_in" take.' if not many
                else f'"in" and "not_in" need a list variable; "{declaration["name"]}" holds one value (declare it with multiple).',
            )

    def variable_named(self, ref: Any, path: str) -> dict[str, Any] | None:
        """The declaration a `{"var": name}` reference names, or `None` (with an error) when it is malformed or undeclared."""
        if not is_reference(ref):
            self.error(path, 'A variable is written {"var": "<name>"}.')
            return None
        declaration = self.variables.get(ref["var"])
        if declaration is None:
            self.error(path, f'"{ref["var"]}" is not a variable of this layout. Variables: {", ".join(self.variables) or "none"}.')
        return declaration

    def reference(self, alias: str, member: str, path: str) -> str | None:
        """Checks `alias.member` is valid in scope, notes the reference and returns the value's kind."""
        if alias == ORG_FAMILY:
            return self.org_value(member, path)
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


def _check_authored_math(v: TreeValidator, text: str | None, path: str) -> None:
    """Errors for authored `\\( \\)` / `$$ $$` equations in `text` that fail the allow-list.

    An equation holding a `{{placeholder}}` is only known at run time, where a failure shows its source.
    """
    for segment in split_math(text or ""):
        if segment.kind != "text" and "{{" not in segment.value and (problem := tex_problem(segment.value)):
            v.error(path, f"An equation in the text: {problem}")


def _validate_heading(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "text"), optional=("level",))
    text = v.text(node.get("text", MISSING), f"{path}.text", limit=500)
    v.placeholders(text, f"{path}.text")
    _check_authored_math(v, text, f"{path}.text")
    if "level" in node and (not isinstance(node["level"], int) or isinstance(node["level"], bool) or not 1 <= node["level"] <= 4):
        v.error(f"{path}.level", "Must be 1 to 4.")


def _validate_text(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "text"))
    text = v.text(node.get("text", MISSING), f"{path}.text")
    v.placeholders(text, f"{path}.text")
    _check_authored_math(v, text, f"{path}.text")


def _validate_equation(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "tex"))
    tex = v.text(node.get("tex", MISSING), f"{path}.tex", limit=MAX_TEX_CHARS)
    if tex is None:
        return
    if tex != tex.strip() or any(c in tex for c in "\r\n\t"):
        v.error(f"{path}.tex", "Write the equation on one line, without spaces at either end.")
    elif problem := tex_problem(tex):
        v.error(f"{path}.tex", problem)


def _image_size(v: TreeValidator, node: dict[str, Any], key: str, unit_key: str, units: tuple[str, ...], path: str, what: str) -> None:
    """Checks an optional image size and its unit: a real number (not a boolean) within the unit's bounds."""
    unit = node.get(unit_key, "cm")
    if unit_key in node and unit not in units:
        v.error(f"{path}.{unit_key}", f"Must be one of: {', '.join(units)}.")
        unit = "cm"
    if unit_key in node and key not in node:
        v.error(f"{path}.{unit_key}", f"A unit needs a {what}.")
    if key not in node:
        return
    low, high = IMAGE_SIZE_BOUNDS[unit]
    value = node[key]
    if not isinstance(value, int | float) or isinstance(value, bool) or not low <= value <= high:
        v.error(f"{path}.{key}", f"The {what} must be a number from {low:g} to {high:g} {'%' if unit == 'percent' else unit}.")


def _validate_image(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(
        node, path, required=("type", "file"),
        optional=(
            "alt", "decorative", "width", "width_unit", "height", "height_unit", "align", "caption", "caption_position", "numbering",
            "placement", "anchor", "offset_x", "offset_y",
        ),
    )
    raw = node.get("file", MISSING)
    if raw is not MISSING and raw != ORG_LOGO_FILE:
        try:
            ok = isinstance(raw, str) and str(uuid.UUID(raw)) == raw
        except ValueError:
            ok = False
        if not ok:
            v.error(
                f"{path}.file",
                f'Must be the id of an image in the library (lower-case, with hyphens), or "{ORG_LOGO_FILE}" for the organisation\'s logo.',
            )
    decorative = node.get("decorative", False)
    if not isinstance(decorative, bool):
        v.error(f"{path}.decorative", "Must be true or false.")
        decorative = False
    alt = node.get("alt", "")
    if not isinstance(alt, str):
        v.error(f"{path}.alt", "Must be text.")
    elif len(alt) > MAX_ALT_CHARS:
        v.error(f"{path}.alt", f"Too long ({len(alt)} characters; the limit is {MAX_ALT_CHARS}).")
    elif not alt.strip() and not decorative:
        v.error(f"{path}.alt", "Describe the image for someone who cannot see it, or mark it decorative.")
    _image_size(v, node, "width", "width_unit", IMAGE_UNITS, path, "width")
    _image_size(v, node, "height", "height_unit", IMAGE_HEIGHT_UNITS, path, "height")
    if "align" in node and node["align"] not in IMAGE_ALIGNMENTS:
        v.error(f"{path}.align", f"Must be one of: {', '.join(IMAGE_ALIGNMENTS)}.")
    if "caption_position" in node and node["caption_position"] not in IMAGE_CAPTION_POSITIONS:
        v.error(f"{path}.caption_position", f"Must be one of: {', '.join(IMAGE_CAPTION_POSITIONS)}.")
    if "numbering" in node and node["numbering"] not in IMAGE_NUMBERING:
        v.error(f"{path}.numbering", f"Must be one of: {', '.join(IMAGE_NUMBERING)}.")
    if "caption" in node:
        caption = v.text(node["caption"], f"{path}.caption", limit=MAX_CAPTION_CHARS)
        v.placeholders(caption, f"{path}.caption")
    _validate_image_placement(v, node, path)


def _validate_image_placement(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    """How the picture sits on the page: a mode, and only the settings that mode uses.

    A setting the mode ignores is refused rather than silently dropped, so what the designer shows is what every format
    prints: text wraps only beside a picture aligned left or right, and a layered picture has no caption (a caption is a
    line of text that belongs to a picture on a line of its own).
    """
    placement = node.get("placement", "inline")
    if placement not in IMAGE_PLACEMENTS:
        v.error(f"{path}.placement", f"Must be one of: {', '.join(IMAGE_PLACEMENTS)}.")
        return
    if "anchor" in node and node["anchor"] not in IMAGE_ANCHORS:
        v.error(f"{path}.anchor", f"Must be one of: {', '.join(IMAGE_ANCHORS)}.")
    for key in ("offset_x", "offset_y"):
        if key not in node:
            continue
        value = node[key]
        if not isinstance(value, int | float) or isinstance(value, bool) or abs(value) > IMAGE_OFFSET_LIMIT_CM:
            v.error(f"{path}.{key}", f"Must be a number of centimetres from -{IMAGE_OFFSET_LIMIT_CM:g} to {IMAGE_OFFSET_LIMIT_CM:g}.")
    layered = placement in ("behind", "front")
    if not layered:
        for key in ("anchor", "offset_x", "offset_y"):
            if key in node:
                v.error(f"{path}.{key}", f"Only a picture placed behind or in front of the text has a position; this one is {placement}.")
    if placement == "wrap" and node.get("align", "center") not in ("left", "right"):
        v.error(f"{path}.align", "Text wraps beside a picture aligned left or right: choose which side the picture is on.")
    if layered and "align" in node:
        v.error(f"{path}.align", f"A picture {placement} the text is placed by its anchor and offsets, not an alignment.")
    if placement != "inline":
        for key in ("caption", "caption_position", "numbering"):
            if key in node:
                v.error(f"{path}.{key}", "A caption goes with a picture on a line of its own; use placement inline for it.")


def _enclosing_record(v: TreeValidator) -> Binding | None:
    """The record of the nearest enclosing block that brings one into scope, or `None`."""
    for binding in reversed(list(v.scope.values())):
        if binding.kind == "record":
            return binding
    return None


def _text_list(v: TreeValidator, node: dict[str, Any], key: str, path: str, *, limit: int, chars: int) -> list[tuple[int, str]]:
    """The `(index, text)` of each entry of a list of at most `limit` non-empty texts of at most `chars` characters.

    Errors are recorded and a bad entry dropped."""
    if key not in node:
        return []
    value = node[key]
    if not isinstance(value, list) or len(value) > limit:
        v.error(f"{path}.{key}", f"Must be a list of at most {limit} entries.")
        return []
    kept: list[tuple[int, str]] = []
    for i, item in enumerate(value):
        text = v.text(item, f"{path}.{key}[{i}]", limit=chars)
        if text is not None:
            kept.append((i, text))
    return kept


def _validate_picture_rules(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    """Checks the rules that choose which of a record's attached files print: name patterns, file types, most per record, order and
    largest file. One model for the record-images block and for an image column of a table, so a rule added later reaches both."""
    for i, pattern in _text_list(v, node, "names", path, limit=MAX_NAME_PATTERNS, chars=MAX_PATTERN_CHARS):
        v.placeholders(pattern, f"{path}.names[{i}]")
        if PLACEHOLDER_RE.sub("", pattern).count("*") > MAX_PATTERN_STARS:
            v.error(f"{path}.names[{i}]", f"At most {MAX_PATTERN_STARS} * wildcards in one name pattern.")
    for i, ext in _text_list(v, node, "types", path, limit=len(RECORD_IMAGE_EXTENSIONS), chars=10):
        if ext.casefold() not in RECORD_IMAGE_EXTENSIONS:
            v.error(f"{path}.types[{i}]", f'"{ext}" is not a picture type a report can print. Use: {", ".join(RECORD_IMAGE_EXTENSIONS)}.')
    if "max_count" in node:
        count = node["max_count"]
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_PICTURES_PER_RECORD:
            v.error(f"{path}.max_count", f"Must be a whole number from 1 to {MAX_PICTURES_PER_RECORD}.")
    if "order" in node and node["order"] not in RECORD_IMAGE_ORDERS:
        v.error(f"{path}.order", f"Must be one of: {', '.join(RECORD_IMAGE_ORDERS)}.")
    if "max_size_mb" in node:
        size = node["max_size_mb"]
        if not isinstance(size, int | float) or isinstance(size, bool) or not 0.1 <= size <= MAX_PICTURE_MEGABYTES:
            v.error(f"{path}.max_size_mb", f"Must be a number of megabytes from 0.1 to {MAX_PICTURE_MEGABYTES}.")


def _validate_record_images(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(
        node, path, required=("type",),
        optional=(
            "names", "types", "max_count", "order", "max_size_mb", "caption_source", "caption", "caption_position", "numbering",
            "width", "width_unit", "height", "height_unit", "align", "placement", "empty_text",
        ),
    )
    record = _enclosing_record(v)
    if record is None:
        v.error(path, "Put this block inside a For each record block: it prints the pictures attached to that block's record.")
    elif record.record_type not in get_record_attachment_providers():
        reason = get_no_record_attachment_reasons().get(record.record_type, "Its attachments cannot be printed.")
        v.error(path, f'The pictures of a "{record.record_type}" record cannot be printed. {reason}')
    _validate_picture_rules(v, node, path)
    source = node.get("caption_source", "file_name")
    if source not in RECORD_IMAGE_CAPTIONS:
        v.error(f"{path}.caption_source", f"Must be one of: {', '.join(RECORD_IMAGE_CAPTIONS)}.")
    if source == "text" and not str(node.get("caption", "")).strip():
        v.error(f"{path}.caption", "Write the caption text, or choose another caption source.")
    if source != "text" and "caption" in node:
        v.error(f"{path}.caption", 'Only used when the caption source is "text".')
    if "caption" in node:
        v.placeholders(v.text(node["caption"], f"{path}.caption", limit=MAX_CAPTION_CHARS), f"{path}.caption")
    if source == "none":
        for key in ("caption_position", "numbering"):
            if key in node:
                v.error(f"{path}.{key}", "There is no caption to place or number.")
    if "caption_position" in node and node["caption_position"] not in IMAGE_CAPTION_POSITIONS:
        v.error(f"{path}.caption_position", f"Must be one of: {', '.join(IMAGE_CAPTION_POSITIONS)}.")
    if "numbering" in node and node["numbering"] not in IMAGE_NUMBERING:
        v.error(f"{path}.numbering", f"Must be one of: {', '.join(IMAGE_NUMBERING)}.")
    _image_size(v, node, "width", "width_unit", IMAGE_UNITS, path, "width")
    _image_size(v, node, "height", "height_unit", IMAGE_HEIGHT_UNITS, path, "height")
    if "align" in node and node["align"] not in IMAGE_ALIGNMENTS:
        v.error(f"{path}.align", f"Must be one of: {', '.join(IMAGE_ALIGNMENTS)}.")
    if node.get("placement", "inline") not in RECORD_IMAGE_PLACEMENTS:
        v.error(f"{path}.placement", f"Must be one of: {', '.join(RECORD_IMAGE_PLACEMENTS)}.")
    else:
        _validate_image_placement(v, node, path)
        if node.get("placement") == "wrap" and source != "none":
            v.error(f"{path}.caption_source", "Text wraps beside a picture with no caption: set the caption to none, or place it in line.")
    if "empty_text" in node:
        v.placeholders(v.text(node["empty_text"], f"{path}.empty_text", limit=500), f"{path}.empty_text")


def _validate_page_break(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type",))


def _validate_section(v: TreeValidator, node: dict[str, Any], path: str) -> None:
    v.check_keys(node, path, required=("type", "page_style", "children"))
    style = v.text(node.get("page_style", MISSING), f"{path}.page_style", limit=100)
    if style is not None and style not in v.page_style_names:
        known = ", ".join(sorted(v.page_style_names)) or "none yet: add one under the layout's page styles"
        v.error(f"{path}.page_style", f'"{style}" is not a page style of this layout. Page styles: {known}.')
    if v.in_section:
        v.error(path, "A section cannot be inside another section.")
    previous, v.in_section = v.in_section, True
    try:
        v.children(node, path)
    finally:
        v.in_section = previous


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
        if "module" in when:  # "the module is available in the project being run"
            v.check_keys(when, path, required=("module",))
            if when.get("module") not in get_module_registry():
                v.error(f"{path}.module", f"Must be a module key: {', '.join(sorted(get_module_registry()))}.")
            return
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


def _widget_param_problems(v: TreeValidator, widget: Any, params: Any, path: str) -> list[tuple[str, str]]:
    """`param_problems` for a widget's `params`, where a value may be a `{"var": name}` reference.

    A reference must name a declared variable that holds one value of a type the parameter accepts; the value
    it takes at run time is checked as a literal then. Errors about a reference are recorded on `v` directly
    (they have their own path); the rest are returned.
    """
    if not isinstance(params, dict):
        return param_problems(widget, params)
    declared = {p.name: p for p in widget.params}
    literal: dict[str, Any] = {}
    bound = 0
    for name, value in params.items():
        if not is_reference(value):
            literal[name] = value
            continue
        bound += 1
        declaration = v.variable_named(value, f"{path}.{name}")
        param = declared.get(name)
        if param is None:
            literal[name] = value  # reported below as an unknown parameter
        elif declaration is not None and param.type not in PARAM_TYPES[declaration["type"]]:
            v.error(f"{path}.{name}", f'The variable "{declaration["name"]}" is of type {declaration["type"]}; this parameter is a {param.type}.')
        elif declaration is not None and declaration.get("multiple"):
            v.error(f"{path}.{name}", f'A report parameter takes one value; "{declaration["name"]}" holds a list.')
    if bound and not literal:
        return []
    return param_problems(widget, literal)


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
        problems = _widget_param_problems(v, widget, node["params"], f"{path}.params")
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
        elif v.contents_sheet and name.casefold() == CONTENTS_SHEET_NAME.casefold():
            v.error(f"{path}.name", f'"{CONTENTS_SHEET_NAME}" names the generated contents sheet. Choose another name, or switch it off.')
        elif name.casefold() in v._sheet_names:
            v.error(f"{path}.name", f'Another sheet is already called "{name}".')
        v._sheet_names.add(name.casefold())
    with v.collecting(node), ExitStack() as stack:
        record_type = v.source(node.get("source"), f"{path}.source")
        root_alias = v.alias(node.get("as"), f"{path}.as", DEFAULT_RECORD_ALIAS)
        if record_type is None:
            return
        aliases = {root_alias: record_type}
        if name is not None:
            v._sheet_roots.setdefault(name.casefold(), (name, record_type))
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


_PLACEHOLDER_HELP = "Use {{record.field}} for a value and {{project_name}} for the project."
_SOURCE_FIELD = BlockField(
    "source", "Records", "source", required=True,
    help="Where the records come from: all of a type, the records linked to an enclosing record, or a group's members; "
    "optionally filtered and sorted.",
)
_EMPTY_TEXT = BlockField("empty_text", "Text when there is nothing", "text", max_length=500, features=("placeholders",),
                         help="Shown instead of the block when it finds no records. Leave empty to show nothing.")
_CHILDREN = BlockContainer("children", "Contents")

#: The settings of an image column (a column of the pictures attached to each row's record), described once for the designer. The
#: rules that choose the files are the record-images block's; the size is a share of the column.
IMAGE_COLUMN_FIELDS: tuple[BlockField, ...] = (
    BlockField("names", "File names", "text_list", max_length=MAX_PATTERN_CHARS, features=("placeholders",),
               help="Show only files whose name matches one of these (case-insensitive). Use * for any run of characters and ? for "
               "one, for example site-*. A value like {{row.code}} (the row's own record) is matched as plain text. Leave empty to "
               "allow any name."),
    BlockField("types", "File types", "text_list", max_length=10,
               help=f"Allowed extensions: {', '.join(RECORD_IMAGE_EXTENSIONS)}. Leave empty to allow them all. Only real pictures "
               "show, whatever the extension says."),
    BlockField("max_count", "Most per row", "integer", minimum=1, maximum=MAX_PICTURES_PER_RECORD, default=5,
               help="The most pictures shown in one row's cell."),
    BlockField("order", "Order", "choice", choices=RECORD_IMAGE_ORDERS, default="name",
               help="By file name, or by when the file was attached (oldest first)."),
    BlockField("max_size_mb", "Largest file (MB)", "number", minimum=0.1, maximum=MAX_PICTURE_MEGABYTES,
               help="Skip files bigger than this. Leave empty for the report limit."),
    BlockField("width", "Width", "number", minimum=1, maximum=1000,
               help="How wide to show each picture. Leave empty for 90% of the column, which follows the page size and the column "
               "widths."),
    BlockField("width_unit", "Width unit", "choice", choices=IMAGE_UNITS, default="percent", depends_on="width",
               help="A percentage of the column's width, or centimetres or millimetres."),
    BlockField("height", "Height", "number", minimum=0.5, maximum=1000,
               help="Size by height instead. Leave empty to keep each picture's shape. Nothing else limits the size, except that a "
               "picture is shrunk if it could never fit on a page."),
    BlockField("height_unit", "Height unit", "choice", choices=IMAGE_HEIGHT_UNITS, default="cm", depends_on="height",
               help="Centimetres or millimetres."),
    BlockField("arrange", "Arrangement", "choice", choices=CELL_ARRANGEMENTS, default="stacked",
               help="Stacked puts one picture under another; side by side puts them in a line that wraps inside the cell."),
)

_CORE_SCHEMAS: dict[str, BlockSchema] = {
    "heading": BlockSchema(
        "Heading", "A heading in the document.",
        (
            BlockField("text", "Heading", "text", required=True, max_length=500, features=("placeholders", "math"),
                       help=f"The heading's words. {_PLACEHOLDER_HELP}"),
            BlockField("level", "Level", "integer", minimum=1, maximum=4, default=1,
                       help="1 is the largest. Levels 1 to 4 appear in the contents list."),
        ),
        template={"type": "heading", "text": "Heading", "level": 2},
    ),
    "text": BlockSchema(
        "Text", "A paragraph, list or other formatted text.",
        (BlockField("text", "Text", "longtext", required=True, max_length=MAX_TEXT_CHARS,
                    features=("placeholders", "math", "markdown"), help=f"Formatted text. {_PLACEHOLDER_HELP}"),),
        template={"type": "text", "text": "Some text."},
    ),
    "page_break": BlockSchema("Page break", "Starts a new page in PDF and Word output.", template={"type": "page_break"}),
    "section": BlockSchema(
        "Section", "Lays out its contents in another page style (paper, orientation, margins), on pages of their own.",
        (BlockField("page_style", "Page style", "page_style", required=True,
                    help="One of the layout's page styles. The section starts on a new page and the report returns to its own "
                    "page style on a new page after it."),),
        (_CHILDREN,),
        template={"type": "section", "page_style": "", "children": []},
    ),
    "image": BlockSchema(
        "Image", "A picture from the image library: in line with the text, with text wrapped beside it, or behind or in front of it.",
        (
            BlockField("file", "Image", "image", required=True,
                       help="A picture from the library: the project's own and the organisation's (an organisation layout "
                       "can use organisation images only). PNG, JPEG, GIF, WebP and plain SVG."),
            BlockField("alt", "Alternative text", "text", max_length=MAX_ALT_CHARS,
                       help="What the picture shows, for readers who cannot see it. Required unless the image is decorative."),
            BlockField("decorative", "Decorative", "boolean", default=False,
                       help="Tick for a picture that adds no information (a rule, a flourish): it needs no alternative text."),
            BlockField("width", "Width", "number", minimum=1, maximum=1000,
                       help="How wide to print it. Leave empty for its own size, never wider than the text. With no height "
                       "the shape is kept."),
            BlockField("width_unit", "Width unit", "choice", choices=IMAGE_UNITS, default="cm", depends_on="width",
                       help="Centimetres, millimetres, or a percentage of the width of the text."),
            BlockField("height", "Height", "number", minimum=0.5, maximum=1000,
                       help="Size by height instead, or set both to stretch the picture to an exact size. Leave empty to keep "
                       "its shape."),
            BlockField("height_unit", "Height unit", "choice", choices=IMAGE_HEIGHT_UNITS, default="cm", depends_on="height",
                       help="Centimetres or millimetres."),
            BlockField("align", "Alignment", "choice", choices=IMAGE_ALIGNMENTS, default="center",
                       help="Where it sits across the text width."),
            BlockField("placement", "Placement", "choice", choices=IMAGE_PLACEMENTS, default="inline",
                       help="In line: the picture has a line of its own. Wrap: the text that follows runs beside it (set Alignment "
                       "to the side the picture is on). Behind or In front: laid over the page under or over the text, at the "
                       "position set below; no caption."),
            BlockField("anchor", "Position from", "choice", choices=IMAGE_ANCHORS, default="paragraph", depends_on="placement",
                       help="Behind and In front only. Paragraph: measured from where this block sits in the text. Margin: from the "
                       "corner of the text area of the page. Page: from the corner of the sheet (a watermark). The browser preview "
                       "has no pages and measures Margin and Page from where the block sits."),
            BlockField("offset_x", "Across (cm)", "number", minimum=-IMAGE_OFFSET_LIMIT_CM, maximum=IMAGE_OFFSET_LIMIT_CM,
                       depends_on="placement",
                       help="Behind and In front only. Centimetres to the right of the corner it is measured from; negative goes left."),
            BlockField("offset_y", "Down (cm)", "number", minimum=-IMAGE_OFFSET_LIMIT_CM, maximum=IMAGE_OFFSET_LIMIT_CM,
                       depends_on="placement",
                       help="Behind and In front only. Centimetres below the corner it is measured from; negative goes up."),
            BlockField("caption", "Caption", "text", max_length=MAX_CAPTION_CHARS, features=("placeholders",),
                       help=f"A line printed with an in-line picture. {_PLACEHOLDER_HELP}"),
            BlockField("caption_position", "Caption position", "choice", choices=IMAGE_CAPTION_POSITIONS, default="below",
                       depends_on="caption", help="Above or below the picture."),
            BlockField("numbering", "Caption numbering", "choice", choices=IMAGE_NUMBERING, default="auto", depends_on="caption",
                       help="Prints \"Figure 1:\", \"Figure 2:\" ... in the order they appear. Automatic numbers a picture that has "
                       "a caption and leaves a bare one (a logo) alone; Always numbers it even with no caption; Never does not."),
        ),
        template={"type": "image", "file": ""},
    ),
    "record_images": BlockSchema(
        "Record images", "The pictures attached to the record of the enclosing For each block, chosen by rules.",
        (
            BlockField("names", "File names", "text_list", max_length=MAX_PATTERN_CHARS, features=("placeholders",),
                       help="Print only files whose name matches one of these (case-insensitive). Use * for any run of "
                       "characters and ? for one, for example site-photo-*. A value like {{rec.code}} is matched as plain "
                       "text. Leave empty to allow any name."),
            BlockField("types", "File types", "text_list", max_length=10,
                       help=f"Allowed extensions: {', '.join(RECORD_IMAGE_EXTENSIONS)}. Leave empty to allow them all. Only "
                       "real pictures print, whatever the extension says."),
            BlockField("max_count", "Most per record", "integer", minimum=1, maximum=MAX_PICTURES_PER_RECORD, default=5,
                       help="The most pictures printed for one record."),
            BlockField("order", "Order", "choice", choices=RECORD_IMAGE_ORDERS, default="name",
                       help="By file name, or by when the file was attached (oldest first)."),
            BlockField("max_size_mb", "Largest file (MB)", "number", minimum=0.1, maximum=MAX_PICTURE_MEGABYTES,
                       help="Skip files bigger than this. Leave empty for the report limit."),
            BlockField("caption_source", "Caption", "choice", choices=RECORD_IMAGE_CAPTIONS, default="file_name",
                       help="The file name, a fixed text you write below, or no caption."),
            BlockField("caption", "Caption text", "text", max_length=MAX_CAPTION_CHARS, features=("placeholders",),
                       depends_on="caption_source", help=f"Used when the caption is Text. {_PLACEHOLDER_HELP}"),
            BlockField("caption_position", "Caption position", "choice", choices=IMAGE_CAPTION_POSITIONS, default="below",
                       depends_on="caption_source", help="Above or below the picture."),
            BlockField("numbering", "Caption numbering", "choice", choices=IMAGE_NUMBERING, default="auto",
                       depends_on="caption_source", help="Prints \"Figure 1:\", \"Figure 2:\" ... in the order the pictures appear."),
            BlockField("width", "Width", "number", minimum=1, maximum=1000,
                       help="How wide to print each picture. Leave empty for its own size, never wider than the text."),
            BlockField("width_unit", "Width unit", "choice", choices=IMAGE_UNITS, default="cm", depends_on="width",
                       help="Centimetres, millimetres, or a percentage of the width of the text."),
            BlockField("height", "Height", "number", minimum=0.5, maximum=1000,
                       help="Size by height instead. Leave empty to keep each picture's shape."),
            BlockField("height_unit", "Height unit", "choice", choices=IMAGE_HEIGHT_UNITS, default="cm", depends_on="height",
                       help="Centimetres or millimetres."),
            BlockField("align", "Alignment", "choice", choices=IMAGE_ALIGNMENTS, default="center",
                       help="Where each picture sits across the text width."),
            BlockField("placement", "Placement", "choice", choices=RECORD_IMAGE_PLACEMENTS, default="inline",
                       help="In line: each picture has a line of its own. Wrap: the text that follows runs beside it (set "
                       "Alignment to left or right)."),
            _EMPTY_TEXT,
        ),
        template={"type": "record_images"},
    ),
    "equation": BlockSchema(
        "Equation", "A displayed equation written in TeX.",
        (BlockField("tex", "TeX", "tex", required=True, max_length=MAX_TEX_CHARS,
                    help="One line of TeX without spaces at either end, for example \\frac{a}{b} = c."),),
        template={"type": "equation", "tex": "a = b"},
    ),
    "table": BlockSchema(
        "Table", "A table with one row per record.",
        (
            _SOURCE_FIELD,
            BlockField("columns", "Columns", "columns", required=True, help="The fields to show, in order, with an optional heading each."),
            _EMPTY_TEXT,
        ),
        template={"type": "table", "source": {}, "columns": []},
    ),
    "each": BlockSchema(
        "For each record", "Repeats its contents once for every record found.",
        (
            _SOURCE_FIELD,
            BlockField("as", "Name", "alias", max_length=32, default=DEFAULT_RECORD_ALIAS,
                       help="What the contents call each record, for example req in {{req.title}}."),
            _EMPTY_TEXT,
        ),
        (_CHILDREN,), BlockProvides("as", "record", DEFAULT_RECORD_ALIAS),
        template={"type": "each", "source": {}, "children": []},
    ),
    "group": BlockSchema(
        "Group records", "Repeats its contents once for every distinct value of a field.",
        (
            _SOURCE_FIELD,
            BlockField("by", "Group by", "record_field", required=True, depends_on="source",
                       help="The field whose values form the groups."),
            BlockField("as", "Name", "alias", max_length=32, default=DEFAULT_GROUP_ALIAS,
                       help="What the contents call each group; {{grp.value}} and {{grp.count}} are its value and size."),
        ),
        (_CHILDREN,), BlockProvides("as", "group", DEFAULT_GROUP_ALIAS),
        template={"type": "group", "source": {}, "by": "", "children": []},
    ),
    "if": BlockSchema(
        "If", "Shows its contents only when a condition holds, and optionally other contents when it does not.",
        (BlockField("when", "Condition", "condition", required=True,
                    help="A test on a field of an enclosing record, or on whether a module is available."),),
        (_CHILDREN, BlockContainer("else_children", "Otherwise")),
        template={"type": "if", "when": {}, "children": []},
    ),
    "widget": BlockSchema(
        "Report component", "Embeds a table, the headline figures or the notes of an existing report.",
        (
            BlockField("key", "Component", "widget_key", required=True, max_length=100,
                       help="Which report component to embed."),
            BlockField("params", "Settings", "widget_params", depends_on="key",
                       help="The report's own settings. Leave out to use its defaults."),
            BlockField("sort", "Sort", "widget_sort", depends_on="key",
                       help="Sort the component's table by its column headings. Leave out for the report's own order."),
            _EMPTY_TEXT,
        ),
        template={"type": "widget", "key": ""},
    ),
    "sheet": BlockSchema(
        "Sheet", "One sheet of a spreadsheet or CSV, one row per record, with optional joined records.",
        (
            BlockField("name", "Sheet name", "text", required=True, max_length=31,
                       help="The tab's name. It cannot contain [ ] : * ? / \\ and must differ from the other sheets."),
            _SOURCE_FIELD,
            BlockField("as", "Name", "alias", max_length=32, default=DEFAULT_RECORD_ALIAS,
                       help="What the columns and joins call the sheet's own records."),
            BlockField(
                "joins", "Joins", "joins",
                help=f"Up to {MAX_JOINS} linked record types to add columns from; a row with nothing linked is kept, with blank cells.",
            ),
            BlockField("columns", "Columns", "columns", required=True, help="The fields to show, in order, with an optional heading each."),
        ),
        provides=BlockProvides("as", "record", DEFAULT_RECORD_ALIAS),
        template={"type": "sheet", "name": "Sheet", "source": {}, "columns": []},
    ),
}

for _spec in (
    BlockSpec("heading", (FAMILY_DOCUMENT,), _validate_heading),
    BlockSpec("text", (FAMILY_DOCUMENT,), _validate_text),
    BlockSpec("page_break", (FAMILY_DOCUMENT,), _validate_page_break),
    BlockSpec("section", (FAMILY_DOCUMENT,), _validate_section),
    BlockSpec("image", (FAMILY_DOCUMENT,), _validate_image),
    BlockSpec("record_images", (FAMILY_DOCUMENT,), _validate_record_images),
    BlockSpec("equation", (FAMILY_DOCUMENT,), _validate_equation),
    BlockSpec("table", (FAMILY_DOCUMENT,), _validate_table),
    BlockSpec("each", (FAMILY_DOCUMENT,), _validate_each),
    BlockSpec("group", (FAMILY_DOCUMENT,), _validate_group),
    BlockSpec("if", (FAMILY_DOCUMENT,), _validate_if),
    BlockSpec("widget", (FAMILY_DOCUMENT,), _validate_widget),
    BlockSpec("sheet", (FAMILY_TABLE,), _validate_sheet),
):
    register_block_spec(replace(_spec, schema=_CORE_SCHEMAS[_spec.key]))

__all__ = [
    "BLOCK_SPECS", "BOOLEAN_KEYS", "IMAGE_COLUMN_FIELDS", "DEFAULT_GROUP_ALIAS", "DEFAULT_JOIN_ALIAS", "DEFAULT_RECORD_ALIAS", "GROUP_FIELDS",
    "LIST_OPERATORS", "MAX_COLUMNS", "MAX_CONDITION_DEPTH", "MAX_DEPTH", "MAX_JOINS", "MAX_NODES", "MAX_TREE_BYTES",
    "MAX_WIDGET_REPORTS", "OPERATORS_BY_KIND", "PLACEHOLDER_RE", "TREE_SCHEMA_VERSION", "Binding", "BlockSpec",
    "InvalidLayoutError", "Ref", "TreeAnalysis", "TreeError", "TreeValidator", "assert_valid", "empty_tree",
    "literal_problem", "record_types_of", "register_block_spec", "tree_hash", "validate_tree",
]
