"""
Module: services.report_layout_text

The text view of a layout: a readable, line-based form of the layout tree that a person can type, plus
the parser and serialiser that keep it and the JSON tree the same thing.

```
@layout document landscape

@heading {{report_title}} for {{project_name}}

@group requirement by component as comp
  @heading {{comp.value}} ({{comp.count}})
  @each in comp sort title as req empty "None."
    @heading level=3 {{req.code}} {{req.title}}
    Plain lines are text (restricted Markdown).
    @table stakeholder from req where role eq analyst
      @column title "Stakeholder"
    @end
  @end
@end
```

Responsibilities:
- `parse_text`: text to tree, with line/column positioned errors for the text's own mistakes and the
  tree validator's errors mapped back to the line of the block they concern.
- `format_tree`: tree to text. `parse_text(format_tree(t))` returns exactly `t` for every valid tree
  (including keys that are present but empty, such as `"where": []`), so opening a layout in the text
  editor and saving it unchanged creates no new version.
- Let other block types add their text form (`register_text_form`), as they add a validator and an evaluator.

Grammar (one statement per line; indentation is cosmetic):
- `@layout document [portrait|landscape] [A3|A4|A5|Letter|Legal]` or `@layout table` is the first line.
- A block opens with `@name ...`; `each`, `group`, `if` (with `@else`), `table`, `sheet` and an explicit
  `@text` end with `@end`. `heading`, `page_break` and the quoted `@text "..."` are one line.
- A source is a record type, or `in <group name>`, followed by clauses in any order: `from <name>`,
  `via "<link type>", ...`, `direction <d>`, `archived true|false`, `where <condition>`,
  `sort <field> [asc|desc]`; a block adds `as <name>`, `by <field>` or `empty "<text>"` where its
  validator takes them. `none` after `via`, `where` or `sort` writes an empty list.
- A condition is a test of one field, `<field> <op> [value, ...]` (`eq ne contains gt gte lt lte empty not_empty`, and
  `in` / `not_in` with a comma-separated list), or tests combined with `and`, `or`, `not` and brackets: `not` binds
  tightest, then `and`, then `or`. Several `where` clauses must all hold. A bare `and`, `or` or `not` is never a value
  (write it in quotes), and a bracket is never part of a bare word.
- An `@if` also takes `module <key>` (for example `@if module risk_management`): true where that module is
  available in the project being run, so a layout that spans modules can leave out the parts of one that is off.
- An equation block is `@equation <TeX>` on one line (`@equation \\frac{a}{b} = c`). Equations inside a text line
  are written `\\( x \\)` (inline) or `$$ x $$` (display), which are ordinary text to this grammar.
- A widget is one component of a report (a table, its headline figures or its notes) on a line of its own,
  `[[widget.<module>.<report>.<part> name=value ... sort <column> [asc|desc] ... empty "<text>"]]`: a bare word,
  number, `true` or `false` is read as such, anything else is quoted (`since="2026-10-01"`); `sort` orders the table by
  a column heading (up to three, most significant first); `empty` is the text shown when the component has
  nothing in it. A line starting `[[widget` is always a widget (and an error if malformed), so prose that needs
  one writes it inside `@text`.
- Run-time variables are declared before the first block, one per line:
  `@var <name> <text|number|date|bool|enum> [list] [label "<text>"] [default <value>[, ...]] [options "<a>", ...]
  [from <record type>.<field>]`. A condition value or widget parameter written `$name` is a reference to one
  (`where category in $categories`, `[[widget.… since=$since]]`; a quoted `"$name"` is the text), and `{{var.name}}`
  in text prints its value.
- Any line that is not a directive is text; consecutive such lines are one text block. A line whose first
  character is `@` is written `@@` in text. Text that cannot be written as plain lines (carriage
  returns, edge blank lines, directly after another text block) uses `@text ... @end` or `@text "..."`.

Design decisions:
- **No new semantics.** The parser builds the same dict the JSON API accepts and then runs `validate_tree`
  on it, so the text view cannot allow what the tree forbids.
- **Syntax first, then meaning.** A syntax error stops validation (indexes in the tree would be wrong); a
  clean parse reports every validator error at its block's line.
- **Bounded.** Input size, nesting depth and block count are capped before any tree is built, so hostile text
  cannot make the parser recurse or allocate without limit. The text is customer content and is never logged.

Dependencies: `services.report_layout_tree` (vocabulary, validator, caps).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.models.report_layout import FAMILY_DOCUMENT, FAMILY_TABLE
from app.services.report_layout_tree import (
    LIST_OPERATORS,
    MAX_CONDITION_DEPTH,
    MAX_DEPTH,
    MAX_ERRORS,
    MAX_NODES,
    TREE_SCHEMA_VERSION,
    assert_valid,
    validate_tree,
)
from app.services.report_variables import NAME_RE, VARIABLE_TYPES, is_reference

MAX_TEXT_VIEW_CHARS = 1_000_000
#: Words that join conditions; a bare one is never a value.
LOGIC_WORDS = ("and", "or", "not")
#: Brackets that may be open at once in a condition.
MAX_BRACKET_DEPTH = 8
INDENT = "  "
ORIENTATION_WORDS = ("portrait", "landscape")
PAGE_SIZE_WORDS = ("A3", "A4", "A5", "Letter", "Legal")
SOURCE_CLAUSES = ("from", "via", "direction", "archived", "where", "sort")
EXTRA_CLAUSES = ("as", "by", "empty")

_STRING_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"')
_WORD_TOKEN = re.compile(r'[^\s,"()]+')
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
_LEVEL_ATTR = re.compile(r"level=(\S*)(?:\s+|$)")
_ATTR_LOOKALIKE = re.compile(r"[a-z_]+=")
#: The clauses of an `@var` line after its name and type.
VARIABLE_CLAUSES = ("label", "default", "options", "from")


@dataclass(frozen=True)
class TextError:
    """One problem found in the text.

    Attributes:
        line: 1-based line.
        column: 1-based column for a syntax error; `None` for a validator error, which concerns a whole block.
        message: What is wrong, written for the author.
    """

    line: int
    column: int | None
    message: str


@dataclass
class ParseResult:
    """The outcome of `parse_text`.

    Attributes:
        tree: The layout tree, `None` when the text has syntax errors. Present (but possibly invalid) when
            only validator errors were found.
        errors: Every problem found, in line order.
    """

    tree: dict[str, Any] | None = None
    errors: list[TextError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the text is a valid layout."""
        return self.tree is not None and not self.errors


class _Syntax(Exception):
    """A mistake in one line; carries the column it was noticed at."""

    def __init__(self, message: str, column: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.column = column


class _Halt(Exception):
    """Parsing cannot usefully continue (too many errors or blocks)."""


# --- tokens ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    kind: str  # "str" (quoted), "word", "comma" or "paren"
    value: str
    column: int

    def shown(self) -> str:
        """The token as the author wrote it, for messages."""
        return json.dumps(self.value, ensure_ascii=False) if self.kind == "str" else self.value


def _tokenize(rest: str, offset: int) -> list[_Token]:
    """Splits the arguments of a directive. `offset` is the 0-based column of `rest` in its line."""
    tokens: list[_Token] = []
    pos, n = 0, len(rest)
    while True:
        while pos < n and rest[pos] in " \t":
            pos += 1
        if pos >= n:
            return tokens
        column = offset + pos + 1
        if rest[pos] == '"':
            match = _STRING_TOKEN.match(rest, pos)
            if match is None:
                raise _Syntax("This quoted text is never closed.", column)
            try:
                value = json.loads(match.group())
            except ValueError:
                raise _Syntax('Not valid quoted text (write \\" for a quote and \\\\ for a backslash).', column) from None
            tokens.append(_Token("str", value, column))
            pos = match.end()
        elif rest[pos] == ",":
            tokens.append(_Token("comma", ",", column))
            pos += 1
        elif rest[pos] in "()":
            tokens.append(_Token("paren", rest[pos], column))
            pos += 1
        else:
            match = _WORD_TOKEN.match(rest, pos)
            assert match is not None  # not whitespace, comma or quote, so at least one character
            tokens.append(_Token("word", match.group(), column))
            pos = match.end()


class _Cursor:
    """Reads the tokens of one directive line, in order."""

    def __init__(self, tokens: list[_Token], end_column: int) -> None:
        self._tokens = tokens
        self._i = 0
        self._end = end_column

    def peek(self) -> _Token | None:
        """The next token, or `None` at the end of the line."""
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def take(self, what: str) -> _Token:
        """The next token.

        Raises:
            _Syntax: The line ends here.
        """
        token = self.peek()
        if token is None:
            raise _Syntax(f"Expected {what}.", self._end)
        self._i += 1
        return token

    def word(self, what: str) -> str:
        """The next token, which must be an unquoted word."""
        token = self.take(what)
        if token.kind != "word":
            raise _Syntax(f"Expected {what}, found {token.shown()}.", token.column)
        return token.value

    def text(self, what: str) -> str:
        """The next token as text: quoted, or an unquoted word taken as written."""
        token = self.take(what)
        if token.kind == "comma":
            raise _Syntax(f"Expected {what}, found a comma.", token.column)
        if token.kind == "paren":
            raise _Syntax(f"Expected {what}, found {token.value}. Put text with brackets in quotes.", token.column)
        return token.value

    def value(self, what: str) -> Any:
        """The next token as a literal: quoted text, `true`/`false`, a number, or an unquoted word as text."""
        token = self.take(what)
        if token.kind == "str":
            return token.value
        if token.kind == "comma":
            raise _Syntax(f"Expected {what}, found a comma.", token.column)
        if token.kind == "paren":
            raise _Syntax(f"Expected {what}, found {token.value}. Put text with brackets in quotes.", token.column)
        if token.value in LOGIC_WORDS:
            raise _Syntax(f'A bare "{token.value}" is logic, not a value: write "{token.value}" in quotes to use it as one.', token.column)
        if token.value.startswith("$"):
            return _variable_reference(token.value, token.column)
        if token.value in ("true", "false"):
            return token.value == "true"
        if _NUMBER.fullmatch(token.value):
            return json.loads(token.value)
        return token.value

    def list_or_reference(self, what: str) -> Any:
        """`value (, value)*`, or one `$name` reference standing for the whole list (`in $categories`)."""
        items = self.comma_list(lambda: self.value(what))
        if any(is_reference(item) for item in items) and len(items) > 1:
            raise _Syntax("A variable stands for the whole list: write `in $name`, not a list that includes one.", self._tokens[0].column)
        return items[0] if is_reference(items[0]) else items

    def accept(self, *names: str) -> str | None:
        """Consumes the next token when it is one of the unquoted words `names`."""
        token = self.peek()
        if token is not None and token.kind == "word" and token.value in names:
            self._i += 1
            return token.value
        return None

    def condition(self, leaf: Callable[[_Cursor], dict[str, Any]], depth: int = 0) -> dict[str, Any]:
        """A condition: `leaf` tests joined by `and` / `or` / `not` and brackets (`not` > `and` > `or`).

        Brackets are kept as structure, so `a and (b and c)` reads back as the same tree it was written from.

        Args:
            leaf: Reads one test from the cursor.
            depth: How many brackets are open.

        Returns:
            The condition as the tree stores it: a test, `{"all": [...]}`, `{"any": [...]}` or `{"not": ...}`.
        """
        items = [self._conjunction(leaf, depth)]
        while self.accept("or"):
            items.append(self._conjunction(leaf, depth))
        return items[0] if len(items) == 1 else {"any": items}

    def _conjunction(self, leaf: Callable[[_Cursor], dict[str, Any]], depth: int) -> dict[str, Any]:
        items = [self._negation(leaf, depth)]
        while self.accept("and"):
            items.append(self._negation(leaf, depth))
        return items[0] if len(items) == 1 else {"all": items}

    def _negation(self, leaf: Callable[[_Cursor], dict[str, Any]], depth: int) -> dict[str, Any]:
        nots = 0
        while (token := self.peek()) is not None and token.kind == "word" and token.value == "not":
            self._i += 1
            nots += 1
            if nots > MAX_CONDITION_DEPTH:
                raise _Syntax(f"Too many nots in a row (the limit is {MAX_CONDITION_DEPTH}).", token.column)
        token = self.peek()
        if token is not None and token.kind == "paren" and token.value == "(":
            if depth >= MAX_BRACKET_DEPTH:
                raise _Syntax(f"Brackets are nested too deeply (the limit is {MAX_BRACKET_DEPTH}).", token.column)
            self._i += 1
            node = self.condition(leaf, depth + 1)
            closing = self.peek()
            if closing is None or closing.kind != "paren" or closing.value != ")":
                raise _Syntax("This bracket is never closed.", token.column)
            self._i += 1
        else:
            node = leaf(self)
        for _ in range(nots):
            node = {"not": node}
        return node

    def comma_list(self, item: Callable[[], Any]) -> list[Any]:
        """`item (, item)*`."""
        items = [item()]
        while (token := self.peek()) is not None and token.kind == "comma":
            self._i += 1
            items.append(item())
        return items

    def expect_end(self) -> None:
        """Raises when anything is left on the line."""
        token = self.peek()
        if token is not None:
            raise _Syntax(f"Unexpected {token.shown()}.", token.column)


def _variable_reference(word: str, column: int) -> dict[str, str]:
    """`$name` as the tree's `{"var": name}`.

    Raises:
        _Syntax: The name is not a valid variable name.
    """
    if not NAME_RE.fullmatch(word[1:]):
        raise _Syntax("A variable is written $name (lower-case letters, digits and underscores). Quote the text to use it as one.", column)
    return {"var": word[1:]}


def _cursor(rest: str, offset: int, line_length: int) -> _Cursor:
    return _Cursor(_tokenize(rest, offset), line_length + 1)


# --- shared clause grammar -------------------------------------------------------------------------


def _condition_tail(cur: _Cursor, cond: dict[str, Any]) -> None:
    """Reads `<op> [value, ...]` into `cond` (`op` and, unless the operator takes none, `value`)."""
    cond["op"] = cur.word("an operator (eq, ne, gt, gte, lt, lte, contains, in, not_in, empty, not_empty)")
    if cond["op"] in ("empty", "not_empty"):
        return
    if cond["op"] in LIST_OPERATORS:
        cond["value"] = cur.list_or_reference("a value")
        return
    cond["value"] = cur.value("a value")
    following = cur.peek()
    if following is not None and following.kind == "comma":
        raise _Syntax('Only "in" and "not_in" take several values.', following.column)


def _test_subject(cur: _Cursor, what: str) -> str:
    """The field (or `name.field`) a test is about; a word of logic here means a test is missing."""
    token = cur.peek()
    if token is not None and token.kind == "word" and token.value in LOGIC_WORDS:
        raise _Syntax(f'Expected {what}, found "{token.value}": a test is missing before or after it.', token.column)
    return cur.word(what)


def _where_leaf(cur: _Cursor) -> dict[str, Any]:
    """One `<field> <op> [value, ...]` test of a `where`."""
    cond: dict[str, Any] = {"field": _test_subject(cur, "a field name")}
    _condition_tail(cur, cond)
    return cond


def _if_leaf(cur: _Cursor) -> dict[str, Any]:
    """One `<name.field> <op> [value, ...]` test of an `@if`, or `module <key>` (the module is available in the project)."""
    token = cur.peek()
    if token is not None and token.kind == "word" and token.value == "module":
        cur.take("module")
        return {"module": cur.word("a module key, for example risk_management")}
    cond: dict[str, Any] = {"ref": _test_subject(cur, "name.field, for example record.status")}
    _condition_tail(cur, cond)
    return cond


def _source(cur: _Cursor, extras: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, str]]:
    """Reads a source and the block's own clauses.

    Args:
        cur: The directive's remaining tokens.
        extras: Which of `as`, `by`, `empty` this block takes.

    Returns:
        `(source, extra)`: the tree's `source` object, and the values of the extra clauses given.
    """
    first = cur.take("a record type (for example requirement) or in <group name>")
    if first.kind != "word":
        raise _Syntax(f"Expected a record type, found {first.shown()}.", first.column)
    source: dict[str, Any] = {}
    if first.value == "in":
        source["group"] = cur.word("the name of an enclosing group")
    else:
        source["record_type"] = first.value
    given: dict[str, str] = {}
    allowed = (*SOURCE_CLAUSES, *extras)
    where: list[dict[str, Any]] | None = None
    sort: list[dict[str, Any]] | None = None
    while (token := cur.peek()) is not None:
        if token.kind != "word" or token.value not in (*SOURCE_CLAUSES, *EXTRA_CLAUSES):
            hint = " If it is part of a value, put the value in quotes." if token.kind == "paren" else ""
            raise _Syntax(f"Unexpected {token.shown()}. Expected one of: {', '.join(allowed)}.{hint}", token.column)
        keyword = cur.take("a clause").value
        if keyword not in allowed:
            raise _Syntax(f'"{keyword}" is not used here. This block takes: {", ".join(allowed)}.', token.column)
        if keyword in ("where", "sort"):
            items = where if keyword == "where" else sort
            if cur.accept("none"):
                if items is not None:
                    raise _Syntax(f'"{keyword} none" cannot be combined with other {keyword} clauses.', token.column)
                items = []
            else:
                if items is not None and not items:
                    raise _Syntax(f'"{keyword} none" cannot be combined with other {keyword} clauses.', token.column)
                items = [*(items or [])]
                if keyword == "where":
                    items.append(cur.condition(_where_leaf))
                else:
                    key: dict[str, Any] = {"field": cur.word("a field name")}
                    direction = cur.accept("asc", "desc")
                    if direction:
                        key["descending"] = direction == "desc"
                    items.append(key)
            if keyword == "where":
                where = items
            else:
                sort = items
            continue
        if keyword in given:
            raise _Syntax(f'"{keyword}" is given twice.', token.column)
        if keyword == "via":
            given[keyword] = "-"
            source["link_types"] = [] if cur.accept("none") else cur.comma_list(lambda: cur.text("a link type name"))
        elif keyword == "archived":
            given[keyword] = "-"
            flag = cur.value("true or false")
            source["include_archived"] = flag
        elif keyword == "from":
            given[keyword] = "-"
            source["linked_from"] = cur.word("the name of an enclosing block")
        elif keyword == "direction":
            given[keyword] = "-"
            source["direction"] = cur.word("both, outgoing or incoming")
        elif keyword == "empty":
            given[keyword] = cur.text("the text to show when there are no records")
        else:  # as, by
            given[keyword] = cur.word("a name" if keyword == "as" else "a field name")
    if where is not None:
        source["where"] = where
    if sort is not None:
        source["sort"] = sort
    return source, given


def _bare_or_quoted(value: str) -> str:
    """`value` unquoted when it reads back as the same text, else as quoted text."""
    return value if _BARE.fullmatch(value) and value not in ("true", "false", *LOGIC_WORDS) else _quote(value)


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _literal(value: Any) -> str:
    """A condition value as text."""
    if is_reference(value):
        return "$" + value["var"]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("A number must be finite.")
        return json.dumps(value)
    return _bare_or_quoted(value)


def _condition_text(cond: dict[str, Any]) -> str:
    out = cond["op"]
    if "value" in cond:
        value = cond["value"]
        out += " " + (", ".join(_literal(v) for v in value) if isinstance(value, list) else _literal(value))
    return out


def _where_leaf_text(cond: dict[str, Any]) -> str:
    return f"{cond['field']} {_condition_text(cond)}"


def _if_leaf_text(cond: dict[str, Any]) -> str:
    if "module" in cond:
        return f"module {cond['module']}"
    return f"{cond['ref']} {_condition_text(cond)}"


def _logic_text(node: dict[str, Any], leaf: Callable[[dict[str, Any]], str], parent: str | None = None) -> str:
    """A condition as text, with only the brackets that keep it reading back as the same tree.

    A nested `all` / `any` is bracketed under any other boolean node (so `a and (b and c)` stays distinct from
    `a and b and c`), except an `all` directly under an `any`, where `and` already binds tighter. `not` needs
    none: it binds tightest.

    Args:
        node: The condition.
        leaf: Writes one test.
        parent: The kind of boolean node it sits in (`all`, `any`, `not`), `None` at the top.
    """
    if "not" in node:
        return "not " + _logic_text(node["not"], leaf, "not")
    for kind, word in (("all", " and "), ("any", " or ")):
        if kind in node:
            text = word.join(_logic_text(child, leaf, kind) for child in node[kind])
            bracket = parent is not None and not (kind == "all" and parent == "any")
            return f"({text})" if bracket else text
    return leaf(node)


def _source_text(source: dict[str, Any]) -> str:
    parts = ["in " + source["group"] if "group" in source else source["record_type"]]
    if "linked_from" in source:
        parts.append(f"from {source['linked_from']}")
    if "link_types" in source:
        names = source["link_types"]
        parts.append("via " + (", ".join(_quote(n) for n in names) if names else "none"))
    if "direction" in source:
        parts.append(f"direction {source['direction']}")
    if "include_archived" in source:
        parts.append(f"archived {_literal(source['include_archived'])}")
    for key, clause in (("where", "where"), ("sort", "sort")):
        if key not in source:
            continue
        if not source[key]:
            parts.append(f"{clause} none")
        for item in source[key]:
            if key == "where":
                parts.append(f"where {_logic_text(item, _where_leaf_text)}")
            else:
                parts.append(f"sort {item['field']}" + ("" if "descending" not in item else " desc" if item["descending"] else " asc"))
    return " ".join(parts)


# --- parser ----------------------------------------------------------------------------------------


@dataclass
class _Frame:
    """An open block: where its children go and how to close it."""

    kind: str  # root | container | table | sheet | text
    node: dict[str, Any]
    path: str
    line: int
    list_name: str = "children"
    body: list[str] = field(default_factory=list)  # lines of an explicit @text
    joins_none: bool = False  # a sheet written with @joins none

    def child_prefix(self) -> str:
        """The tree path of this frame's current child list."""
        return "nodes" if self.kind == "root" else f"{self.path}.{self.list_name}"


@dataclass(frozen=True)
class TextForm:
    """How one block type reads and writes in the text view.

    Attributes:
        key: The block's `type` and the directive name (`@key`).
        parse: `(parser, directive)` — reads the rest of the line and adds the block to the parser.
        write: `(writer, node, depth)` — emits the block's lines.
        bracketed: Whether the block is a line of its own, `[[key.…]]`, rather than an `@key` directive. The
            directive's `rest` is then what follows `[[key.` up to the closing `]]`.
    """

    key: str
    parse: Callable[[_Parser, _Directive], None]
    write: Callable[[_Writer, dict[str, Any], int], None]
    bracketed: bool = False


TEXT_FORMS: dict[str, TextForm] = {}


def register_text_form(form: TextForm) -> None:
    """Adds a block type's text form (for widgets, equations and the like).

    Raises:
        ValueError: The key is already registered.
    """
    if form.key in TEXT_FORMS:
        raise ValueError(f"block type {form.key!r} already has a text form")
    TEXT_FORMS[form.key] = form


@dataclass
class _Directive:
    """One `@name rest` line."""

    name: str
    rest: str
    offset: int  # 0-based column where `rest` starts
    line_no: int
    line_length: int

    def cursor(self) -> _Cursor:
        """The tokens of `rest`."""
        return _cursor(self.rest, self.offset, self.line_length)


def _is_directive(stripped: str) -> bool:
    return stripped.startswith("@") and not stripped.startswith("@@")


_BRACKET_START = re.compile(r"\[\[([a-z_]+)(?![a-z_0-9])")


def _bracketed_form(stripped: str) -> TextForm | None:
    """The `[[name.…]]` form a (left-stripped) line opens, or `None` when it is ordinary text."""
    match = _BRACKET_START.match(stripped)
    form = TEXT_FORMS.get(match.group(1)) if match else None
    return form if form is not None and form.bracketed else None


def _escape(line: str) -> str:
    """Writes a text line so a leading `@` is not taken for a directive."""
    stripped = line.lstrip(" \t")
    return line if not stripped.startswith("@") else line[: len(line) - len(stripped)] + "@" + stripped


def _unescape(line: str) -> str:
    stripped = line.lstrip(" \t")
    if stripped.startswith("@@"):
        return line[: len(line) - len(stripped)] + stripped[1:]
    return line


class _Parser:
    """Turns text into a tree, one line at a time, with a stack of open blocks."""

    def __init__(self, text: str) -> None:
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.errors: list[TextError] = []
        self.line_of: dict[str, int] = {}
        self.node_count = 0
        self.root: dict[str, Any] = {"nodes": []}
        self.frames: list[_Frame] = [_Frame("root", self.root, "", 1)]
        self.run: list[str] = []
        self.run_line = 0
        self.header_line = 1
        self.tree: dict[str, Any] = {"schema_version": TREE_SCHEMA_VERSION, "family": FAMILY_DOCUMENT}

    # --- driver

    def parse(self) -> ParseResult:
        """Parses the whole text."""
        try:
            self._parse_lines()
        except _Halt:
            pass
        if self.errors:
            return ParseResult(None, self._ordered())
        tree = {**self.tree, "nodes": self.root["nodes"]}
        problems = []
        for e in validate_tree(tree).errors:
            line, block = self._line_for(e.path)
            where = e.path[len(block):].lstrip(".")
            problems.append(TextError(line, None, f"{where}: {e.message}" if where else e.message))
        return ParseResult(tree, sorted(problems, key=lambda e: e.line))

    def _ordered(self) -> list[TextError]:
        return sorted(self.errors, key=lambda e: (e.line, e.column or 0))

    def _parse_lines(self) -> None:
        seen_header = False
        for index, raw in enumerate(self.lines):
            line_no = index + 1
            stripped = raw.lstrip(" \t")
            if self.frames[-1].kind == "text":
                self._explicit_text_line(raw, stripped, line_no)
                continue
            if not stripped.strip():
                if self.run:
                    self.run.append(self._unindent(raw))
                continue
            if not seen_header:
                seen_header = True
                self.header_line = line_no
                if stripped.startswith("@layout") and stripped[7:8] in ("", " ", "\t"):
                    self._guarded(self._layout_header, raw, stripped, line_no)
                    continue
                self.error(line_no, 1 + len(raw) - len(stripped), "A layout starts with @layout document or @layout table.")
            if _is_directive(stripped):
                self._flush_run()
                self._guarded(self._directive, raw, stripped, line_no)
            elif _bracketed_form(stripped) is not None:
                self._flush_run()
                self._guarded(self._bracketed, raw, stripped, line_no)
            else:
                self._prose(raw, line_no)
        self._flush_run()
        for frame in reversed(self.frames[1:]):
            what = "@text" if frame.kind == "text" else "block"
            self.error(frame.line, None, f"This {what} is never closed with @end.")
        if not seen_header:
            self.error(1, None, "A layout starts with @layout document or @layout table.")

    def error(self, line: int, column: int | None, message: str) -> None:
        """Records a problem; stops parsing after `MAX_ERRORS`."""
        self.errors.append(TextError(line, column, message))
        if len(self.errors) >= MAX_ERRORS:
            raise _Halt

    def _guarded(self, handler: Callable[..., None], raw: str, stripped: str, line_no: int) -> None:
        try:
            handler(raw, stripped, line_no)
        except _Syntax as exc:
            self.error(line_no, exc.column, exc.message)

    # --- header and directives

    def _layout_header(self, raw: str, stripped: str, line_no: int) -> None:
        offset = len(raw) - len(stripped) + 7
        cur = _cursor(stripped[7:], offset, len(raw))
        family = cur.word("document or table")
        if family not in (FAMILY_DOCUMENT, FAMILY_TABLE):
            raise _Syntax(f"The layout must be a {FAMILY_DOCUMENT} or a {FAMILY_TABLE}, not {family!r}.", offset + 2)
        self.tree["family"] = family
        # The orientation and the page size may come in either order, each at most once.
        for _ in range(2):
            word = cur.accept(*ORIENTATION_WORDS, *PAGE_SIZE_WORDS)
            if not word:
                break
            key = "orientation" if word in ORIENTATION_WORDS else "page_size"
            if key in self.tree:
                raise _Syntax(f"The {key.replace('_', ' ')} is written once.", offset)
            self.tree[key] = word
        cur.expect_end()

    def _directive(self, raw: str, stripped: str, line_no: int) -> None:
        indent = len(raw) - len(stripped)
        match = re.fullmatch(r"@(\S*)(.*)", stripped)
        assert match is not None  # `stripped` starts with "@"
        name, rest = match.group(1), match.group(2)
        directive = _Directive(name, rest, indent + 1 + len(name), line_no, len(raw))
        top = self.frames[-1]
        if name == "layout":
            raise _Syntax("@layout can only be the first line.", indent + 1)
        if name == "var":
            self._variable(directive, indent, line_no)
            return
        if name in ("end", "else"):
            if rest.strip():
                raise _Syntax(f"@{name} takes nothing after it.", directive.offset + 1)
            if name == "end":
                if len(self.frames) == 1:
                    raise _Syntax("@end has nothing to close.", indent + 1)
                self.frames.pop()
            elif top.kind != "container" or top.node.get("type") != "if" or top.list_name == "else_children":
                raise _Syntax("@else belongs inside an @if, once.", indent + 1)
            else:
                top.list_name = "else_children"
                top.node["else_children"] = []
            return
        if top.kind in ("table", "sheet"):
            self._sub_directive(top, directive, indent)
            return
        form = TEXT_FORMS.get(name)
        if form is not None and form.bracketed:
            raise _Syntax(f"Write a {name} on a line of its own as [[{name}.…]], not as @{name}.", indent + 1)
        if form is None:
            directives = {key for key, f in TEXT_FORMS.items() if not f.bracketed}
            known = ", ".join(sorted({*directives, "end"} | ({"else"} if top.node.get("type") == "if" else set())))
            raise _Syntax(f"Unknown directive @{name}. Use one of: {known}.", indent + 1)
        before = len(self.frames)
        try:
            form.parse(self, directive)
        except _Syntax:
            if name in ("each", "group", "if", "table", "sheet") and len(self.frames) == before:
                # Keep the @end of a block whose first line was wrong matched to it.
                scratch: dict[str, Any] = {"type": name, "children": [], "columns": []}
                self._push(_Frame("container" if name in ("each", "group", "if") else name, scratch, "", line_no))
            raise

    def _variable(self, directive: _Directive, indent: int, line_no: int) -> None:
        """Reads an `@var` line into the root's `variables` (it belongs before the first block)."""
        if len(self.frames) > 1 or self.root["nodes"]:
            raise _Syntax("@var declares a variable for the whole layout: put it before the first block.", indent + 1)
        cur = directive.cursor()
        declaration: dict[str, Any] = {
            "name": cur.word("a variable name"), "type": cur.word(f"a type ({', '.join(VARIABLE_TYPES)})"),
        }
        if cur.accept("list"):
            declaration["multiple"] = True
        while (token := cur.peek()) is not None:
            clause = cur.word(f"one of: {', '.join(VARIABLE_CLAUSES)}")
            if clause not in VARIABLE_CLAUSES:
                raise _Syntax(f"Unexpected {clause!r}. Expected one of: {', '.join(VARIABLE_CLAUSES)}.", token.column)
            key = {"label": "label", "default": "default", "options": "options", "from": "source"}[clause]
            if key in declaration:
                raise _Syntax(f'"{clause}" is given twice.', token.column)
            if clause == "label":
                declaration[key] = cur.text("the label")
            elif clause == "default":
                declaration[key] = cur.comma_list(lambda: cur.value("a value")) if declaration.get("multiple") else cur.value("a value")
            elif clause == "options":
                declaration[key] = cur.comma_list(lambda: cur.text("an option"))
            else:
                record_type, dot, field_key = cur.word("<record type>.<field>").partition(".")
                if not dot:
                    raise _Syntax("Write the source as <record type>.<field>, for example requirement.category.", token.column)
                declaration[key] = {"record_type": record_type, "field": field_key}
        variables = self.tree.setdefault("variables", [])
        self.line_of[f"variables[{len(variables)}]"] = line_no
        variables.append(declaration)

    def _bracketed(self, raw: str, stripped: str, line_no: int) -> None:
        """A `[[name.…]]` line (a widget): checks its frame and closing brackets, then hands the inside to its form."""
        indent = len(raw) - len(stripped)
        form = _bracketed_form(stripped)
        assert form is not None  # the caller matched it
        if self.frames[-1].kind in ("table", "sheet"):
            raise _Syntax(f"Inside @{self.frames[-1].node['type']} use @column or @end, not a {form.key}.", indent + 1)
        body = stripped.rstrip()
        if not body.endswith("]]"):
            raise _Syntax(f"A [[{form.key}.…]] line must end with ]] and have nothing after it.", indent + len(body) + 1)
        opening = f"[[{form.key}"
        inner = body[len(opening):-2]
        if not inner.startswith("."):
            raise _Syntax(f"Write [[{form.key}.<name> …]], with a dot after {form.key}.", indent + len(opening) + 1)
        directive = _Directive(form.key, inner[1:], indent + len(opening) + 1, line_no, len(raw))
        form.parse(self, directive)

    def _sub_directive(self, frame: _Frame, directive: _Directive, indent: int) -> None:
        name = directive.name
        node = frame.node
        column_path = f"{frame.path}.columns"
        if name == "column":
            cur = directive.cursor()
            word = cur.word("a field name, or name.field")
            column: dict[str, Any] = {}
            owner, dot, field_key = word.partition(".")
            if dot:
                if frame.kind != "sheet":
                    raise _Syntax("Only a sheet reads columns from a joined name.", directive.offset + 1)
                column["field"], column["from"] = field_key, owner
            else:
                column["field"] = word
            if cur.peek() is not None:
                column["label"] = cur.text("the column heading")
            cur.expect_end()
            self.line_of[f"{column_path}[{len(node['columns'])}]"] = directive.line_no
            node["columns"].append(column)
        elif name in ("join", "joins") and frame.kind == "sheet":
            cur = directive.cursor()
            if name == "joins":
                if cur.word("none") != "none":
                    raise _Syntax("Write @joins none for an empty list, or one @join per join.", directive.offset + 1)
                cur.expect_end()
                if node.get("joins") or frame.joins_none:
                    raise _Syntax("@joins none cannot follow a @join or another @joins none.", indent + 1)
                frame.joins_none = True
                node["joins"] = []
                return
            source, extra = _source(cur, ("as",))
            if frame.joins_none:
                raise _Syntax("@join cannot follow @joins none.", indent + 1)
            join: dict[str, Any] = {"source": source}
            if "as" in extra:
                join["as"] = extra["as"]
            joins = node.setdefault("joins", [])
            self.line_of[f"{frame.path}.joins[{len(joins)}]"] = directive.line_no
            joins.append(join)
        else:
            allowed = "@column, @end" if frame.kind == "table" else "@column, @join, @joins none, @end"
            raise _Syntax(f"Inside @{node['type']} use {allowed}.", indent + 1)

    # --- building blocks (used by the forms)

    @property
    def depth(self) -> int:
        """How many blocks are open; the indentation of the statements inside the innermost one."""
        return len(self.frames) - 1 - (self.frames[-1].kind == "text")

    def _count(self, line_no: int) -> None:
        self.node_count += 1
        if self.node_count > MAX_NODES:
            self.error(line_no, None, f"The layout has too many blocks (the limit is {MAX_NODES}).")
            raise _Halt

    def add(self, node: dict[str, Any], line_no: int) -> str:
        """Appends a finished block to the innermost open one and returns its tree path."""
        self._count(line_no)
        frame = self.frames[-1]
        siblings = frame.node.setdefault(frame.list_name if frame.kind != "root" else "nodes", [])
        path = f"{frame.child_prefix()}[{len(siblings)}]"
        siblings.append(node)
        self.line_of[path] = line_no
        return path

    def open(self, node: dict[str, Any], line_no: int, kind: str = "container") -> None:
        """Appends a block and makes it the innermost open one, until its `@end`."""
        if len(self.frames) > MAX_DEPTH:
            self.error(line_no, None, f"Blocks are nested too deeply (the limit is {MAX_DEPTH} levels).")
            raise _Halt
        path = self.add(node, line_no)
        self._push(_Frame(kind, node, path, line_no))

    def _push(self, frame: _Frame) -> None:
        self.frames.append(frame)

    def start_text(self, line_no: int) -> None:
        """Begins an explicit `@text` block, whose lines are read verbatim until `@end`."""
        self._push(_Frame("text", {}, "", line_no))

    # --- text

    def _unindent(self, raw: str) -> str:
        """Removes the block's indentation (as many of its leading spaces as the line has)."""
        want = self.depth * len(INDENT)
        have = len(raw) - len(raw.lstrip(" "))
        return raw[min(have, want):]

    def _prose(self, raw: str, line_no: int) -> None:
        if self.frames[-1].kind in ("table", "sheet"):
            self.error(line_no, None, f"Inside @{self.frames[-1].node['type']} use @column or @end, not text.")
            return
        if not self.run:
            self.run_line = line_no
        self.run.append(_unescape(self._unindent(raw)))

    def _flush_run(self) -> None:
        if not self.run:
            return
        lines = self.run
        self.run = []
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines:
            self.add({"type": "text", "text": "\n".join(lines)}, self.run_line)

    def _explicit_text_line(self, raw: str, stripped: str, line_no: int) -> None:
        frame = self.frames[-1]
        if _is_directive(stripped):
            if stripped.rstrip() == "@end":
                self.frames.pop()
                self.add({"type": "text", "text": "\n".join(frame.body)}, frame.line)
            else:
                self.error(
                    line_no, 1 + len(raw) - len(stripped),
                    "A line starting with @ inside @text must be written @@; close the text with @end.",
                )
            return
        frame.body.append(_unescape(self._unindent(raw)))

    # --- error positions

    def _line_for(self, path: str) -> tuple[int, str]:
        """The line of the nearest block at or above a tree `path`, and that block's path."""
        while path:
            if path in self.line_of:
                return self.line_of[path], path
            path = re.sub(r"(\.[A-Za-z_]+|\[\d+\]|^[A-Za-z_]+)$", "", path)
        return self.header_line, ""


def parse_text(text: str) -> ParseResult:
    """Reads a layout from its text view.

    Args:
        text: The text view.

    Returns:
        The tree and any problems. A syntax error gives no tree; otherwise the tree is returned with the
        validator's errors (each at the line of the block concerned), and `ok` says whether it may be saved.
    """
    if len(text) > MAX_TEXT_VIEW_CHARS:
        return ParseResult(None, [TextError(1, None, f"The text is too long ({len(text)} characters; the limit is {MAX_TEXT_VIEW_CHARS}).")])
    return _Parser(text).parse()


# --- writer ----------------------------------------------------------------------------------------


class _Writer:
    """Collects the lines of a tree's text view."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.prev_implicit_text = False

    def line(self, depth: int, text: str) -> None:
        """Adds a statement at `depth`."""
        self.lines.append(INDENT * depth + text)

    def blank(self) -> None:
        """Adds an empty line."""
        self.lines.append("")

    def blocks(self, nodes: list[dict[str, Any]], depth: int) -> None:
        """Writes sibling blocks, separated by blank lines."""
        self.prev_implicit_text = False
        for i, node in enumerate(nodes):
            if i:
                self.blank()
            TEXT_FORMS[node["type"]].write(self, node, depth)
            if node["type"] != "text":
                self.prev_implicit_text = False


def _variable_text(declaration: dict[str, Any]) -> str:
    """An `@var` line (see the module docstring for the grammar)."""
    parts = ["@var", declaration["name"], declaration["type"]]
    if declaration.get("multiple"):
        parts.append("list")
    if "label" in declaration:
        parts.append(f"label {_quote(declaration['label'])}")
    if "default" in declaration:
        default = declaration["default"]
        parts.append("default " + (", ".join(_literal(v) for v in default) if isinstance(default, list) else _literal(default)))
    if "options" in declaration:
        parts.append("options " + ", ".join(_quote(o) for o in declaration["options"]))
    if "source" in declaration:
        parts.append(f"from {declaration['source']['record_type']}.{declaration['source']['field']}")
    return " ".join(parts)


def format_tree(tree: dict[str, Any]) -> str:
    """Writes a layout tree as its text view.

    Args:
        tree: A valid layout tree.

    Returns:
        The text, ending in a newline. `parse_text` of it returns `tree` exactly.

    Raises:
        InvalidLayoutError: The tree is not valid (only a valid tree has a text view).
    """
    assert_valid(tree)
    writer = _Writer()
    header = f"@layout {tree['family']}"
    if "orientation" in tree:
        header += f" {tree['orientation']}"
    if "page_size" in tree:
        header += f" {tree['page_size']}"
    writer.line(0, header)
    for declaration in tree.get("variables", []):
        writer.line(0, _variable_text(declaration))
    if tree["nodes"]:
        writer.blank()
    writer.blocks(tree["nodes"], 0)
    return "\n".join(writer.lines) + "\n"


# --- block types -----------------------------------------------------------------------------------


def _parse_heading(p: _Parser, d: _Directive) -> None:
    node: dict[str, Any] = {"type": "heading"}
    rest = d.rest.strip()
    match = _LEVEL_ATTR.match(rest)
    if match:
        raw_level = match.group(1)
        if not re.fullmatch(r"-?\d+", raw_level):
            raise _Syntax("The level must be a number from 1 to 4.", d.offset + 1)
        node["level"] = int(raw_level)
        rest = rest[match.end():]
    if rest.startswith('"'):
        try:
            node["text"] = json.loads(rest)
        except ValueError:
            raise _Syntax("Not valid quoted text (write \\\" for a quote and \\\\ for a backslash).", d.offset + 1) from None
        if not isinstance(node["text"], str):
            raise _Syntax("Not valid quoted text.", d.offset + 1)
    elif rest:
        node["text"] = rest
    p.add(node, d.line_no)


def _write_heading(w: _Writer, node: dict[str, Any], depth: int) -> None:
    text = node["text"]
    plain = (
        text == text.strip() and not text.startswith('"') and not _ATTR_LOOKALIKE.match(text)
        and all(ord(c) >= 32 and ord(c) != 127 for c in text)
    )
    level = f" level={node['level']}" if "level" in node else ""
    w.line(depth, f"@heading{level} {text if plain else _quote(text)}")


def _parse_text(p: _Parser, d: _Directive) -> None:
    rest = d.rest.strip()
    if not rest:
        p.start_text(d.line_no)
        return
    if not rest.startswith('"'):
        raise _Syntax('Write @text on its own line, then the text, then @end; or @text "quoted text".', d.offset + 1)
    try:
        value = json.loads(rest)
    except ValueError:
        raise _Syntax('Not valid quoted text (write \\" for a quote and \\\\ for a backslash).', d.offset + 1) from None
    if not isinstance(value, str):
        raise _Syntax("Not valid quoted text.", d.offset + 1)
    p.add({"type": "text", "text": value}, d.line_no)


def _write_text(w: _Writer, node: dict[str, Any], depth: int) -> None:
    text = node["text"]
    if "\r" in text:
        w.line(depth, f"@text {_quote(text)}")
        w.prev_implicit_text = False
        return
    lines = text.split("\n")
    reads_as_block = any(_bracketed_form(line.lstrip(" \t")) is not None for line in lines)
    if not w.prev_implicit_text and lines[0].strip() and lines[-1].strip() and not reads_as_block:
        for line in lines:
            w.lines.append(INDENT * depth + _escape(line) if line else "")
        w.prev_implicit_text = True
        return
    w.line(depth, "@text")
    for line in lines:
        w.lines.append(INDENT * depth + _escape(line) if line else "")
    w.line(depth, "@end")
    w.prev_implicit_text = False


def _parse_page_break(p: _Parser, d: _Directive) -> None:
    if d.rest.strip():
        raise _Syntax("@page_break takes nothing after it.", d.offset + 1)
    p.add({"type": "page_break"}, d.line_no)


def _write_page_break(w: _Writer, node: dict[str, Any], depth: int) -> None:
    w.line(depth, "@page_break")


def _parse_equation(p: _Parser, d: _Directive) -> None:
    tex = d.rest.strip()
    if not tex:
        raise _Syntax("Write the TeX after @equation, on the same line.", d.offset + 1)
    p.add({"type": "equation", "tex": tex}, d.line_no)


def _write_equation(w: _Writer, node: dict[str, Any], depth: int) -> None:
    w.line(depth, f"@equation {node['tex']}")


def _parse_table(p: _Parser, d: _Directive) -> None:
    source, extra = _source(d.cursor(), ("empty",))
    node: dict[str, Any] = {"type": "table", "source": source, "columns": []}
    if "empty" in extra:
        node["empty_text"] = extra["empty"]
    p.open(node, d.line_no, "table")


def _write_columns(w: _Writer, columns: list[dict[str, Any]], depth: int) -> None:
    for column in columns:
        name = f"{column['from']}.{column['field']}" if "from" in column else column["field"]
        w.line(depth, f"@column {name}" + (f" {_quote(column['label'])}" if "label" in column else ""))


def _write_table(w: _Writer, node: dict[str, Any], depth: int) -> None:
    empty = f" empty {_quote(node['empty_text'])}" if "empty_text" in node else ""
    w.line(depth, f"@table {_source_text(node['source'])}{empty}")
    _write_columns(w, node["columns"], depth + 1)
    w.line(depth, "@end")


def _parse_each(p: _Parser, d: _Directive) -> None:
    source, extra = _source(d.cursor(), ("as", "empty"))
    node: dict[str, Any] = {"type": "each", "source": source, "children": []}
    if "as" in extra:
        node["as"] = extra["as"]
    if "empty" in extra:
        node["empty_text"] = extra["empty"]
    p.open(node, d.line_no)


def _write_each(w: _Writer, node: dict[str, Any], depth: int) -> None:
    alias = f" as {node['as']}" if "as" in node else ""
    empty = f" empty {_quote(node['empty_text'])}" if "empty_text" in node else ""
    w.line(depth, f"@each {_source_text(node['source'])}{alias}{empty}")
    w.blocks(node["children"], depth + 1)
    w.line(depth, "@end")


def _parse_group(p: _Parser, d: _Directive) -> None:
    source, extra = _source(d.cursor(), ("as", "by"))
    node: dict[str, Any] = {"type": "group", "source": source, "children": []}
    if "by" in extra:
        node["by"] = extra["by"]
    if "as" in extra:
        node["as"] = extra["as"]
    p.open(node, d.line_no)


def _write_group(w: _Writer, node: dict[str, Any], depth: int) -> None:
    alias = f" as {node['as']}" if "as" in node else ""
    w.line(depth, f"@group {_source_text(node['source'])} by {node['by']}{alias}")
    w.blocks(node["children"], depth + 1)
    w.line(depth, "@end")


def _parse_if(p: _Parser, d: _Directive) -> None:
    cur = d.cursor()
    when = cur.condition(_if_leaf)
    cur.expect_end()
    p.open({"type": "if", "when": when, "children": []}, d.line_no)


def _write_if(w: _Writer, node: dict[str, Any], depth: int) -> None:
    w.line(depth, f"@if {_logic_text(node['when'], _if_leaf_text)}")
    w.blocks(node["children"], depth + 1)
    if "else_children" in node:
        w.line(depth, "@else")
        w.blocks(node["else_children"], depth + 1)
    w.line(depth, "@end")


def _parse_sheet(p: _Parser, d: _Directive) -> None:
    cur = d.cursor()
    node: dict[str, Any] = {"type": "sheet", "name": cur.text("the sheet's name in quotes")}
    source, extra = _source(cur, ("as",))
    node["source"] = source
    node["columns"] = []
    if "as" in extra:
        node["as"] = extra["as"]
    p.open(node, d.line_no, "sheet")


def _write_sheet(w: _Writer, node: dict[str, Any], depth: int) -> None:
    alias = f" as {node['as']}" if "as" in node else ""
    w.line(depth, f"@sheet {_quote(node['name'])} {_source_text(node['source'])}{alias}")
    if "joins" in node and not node["joins"]:
        w.line(depth + 1, "@joins none")
    for join in node.get("joins", []):
        w.line(depth + 1, f"@join {_source_text(join['source'])} as {join['as']}")
    _write_columns(w, node["columns"], depth + 1)
    w.line(depth, "@end")


_PARAM_NAME = re.compile(r"([a-z][a-z0-9_]*)=")
_EMPTY_CLAUSE = re.compile(r'empty\s+(?=")')
_SORT_CLAUSE = re.compile(r"sort(?:\s+|$)")
_DIRECTION = re.compile(r"\s+(asc|desc)(?=\s|$)")
_BARE_VALUE = re.compile(r'[^\s"]+')
_WIDGET_BARE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-.:]*")


def _parse_widget(p: _Parser, d: _Directive) -> None:
    rest = d.rest
    key = re.match(r"\S+", rest)
    if key is None:
        raise _Syntax("Name the component: [[widget.<module>.<report>.<part>]].", d.offset + 1)
    node: dict[str, Any] = {"type": "widget", "key": key.group()}
    params: dict[str, Any] = {}
    pos, n = key.end(), len(rest)
    while True:
        while pos < n and rest[pos] in " \t":
            pos += 1
        if pos >= n:
            break
        column = d.offset + pos + 1
        empty = _EMPTY_CLAUSE.match(rest, pos)
        if empty is not None:
            if "empty_text" in node:
                raise _Syntax('"empty" is given twice.', column)
            quoted = _STRING_TOKEN.match(rest, empty.end())
            if quoted is None:
                raise _Syntax("This quoted text is never closed.", d.offset + empty.end() + 1)
            try:
                node["empty_text"] = json.loads(quoted.group())
            except ValueError:
                raise _Syntax('Not valid quoted text (write \\" for a quote and \\\\ for a backslash).', d.offset + empty.end() + 1) from None
            pos = quoted.end()
            continue
        sorting = _SORT_CLAUSE.match(rest, pos)
        if sorting is not None:
            pos = _parse_widget_sort(node, rest, sorting.end(), d.offset)
            continue
        name = _PARAM_NAME.match(rest, pos)
        if name is None:
            raise _Syntax(f"Expected name=value, found {rest[pos:].split()[0]!r}.", column)
        if name.group(1) in params:
            raise _Syntax(f'"{name.group(1)}" is given twice.', column)
        pos = name.end()
        if pos >= n or rest[pos] in " \t":
            raise _Syntax(f'"{name.group(1)}=" needs a value.', d.offset + pos + 1)
        if rest[pos] == '"':
            quoted = _STRING_TOKEN.match(rest, pos)
            if quoted is None:
                raise _Syntax("This quoted text is never closed.", d.offset + pos + 1)
            try:
                value: Any = json.loads(quoted.group())
            except ValueError:
                raise _Syntax('Not valid quoted text (write \\" for a quote and \\\\ for a backslash).', d.offset + pos + 1) from None
            pos = quoted.end()
        else:
            word = _BARE_VALUE.match(rest, pos)
            assert word is not None  # not whitespace or a quote, so at least one character
            text = word.group()
            if text.startswith("$"):
                value = _variable_reference(text, d.offset + pos + 1)
            else:
                value = text == "true" if text in ("true", "false") else json.loads(text) if _NUMBER.fullmatch(text) else text
            pos = word.end()
        params[name.group(1)] = value
    if params:
        node["params"] = params
    p.add(node, d.line_no)


def _parse_widget_sort(node: dict[str, Any], rest: str, pos: int, offset: int) -> int:
    """Reads `<column> [asc|desc]` after a widget's `sort`, adds the key to `node["sort"]` and returns the new position."""
    if pos >= len(rest):
        raise _Syntax("Sort needs a column heading, for example sort Name or sort \"Next review\" desc.", offset + pos + 1)
    if rest[pos] == '"':
        quoted = _STRING_TOKEN.match(rest, pos)
        if quoted is None:
            raise _Syntax("This quoted text is never closed.", offset + pos + 1)
        try:
            column = json.loads(quoted.group())
        except ValueError:
            raise _Syntax('Not valid quoted text (write \\" for a quote and \\\\ for a backslash).', offset + pos + 1) from None
        pos = quoted.end()
    else:
        word = _BARE_VALUE.match(rest, pos)
        assert word is not None  # not whitespace or a quote
        column, pos = word.group(), word.end()
    key: dict[str, Any] = {"column": column}
    direction = _DIRECTION.match(rest, pos)
    if direction is not None:
        key["descending"] = direction.group(1) == "desc"
        pos = direction.end()
    node.setdefault("sort", []).append(key)
    return pos


def _widget_literal(value: Any) -> str:
    """A parameter value as text: bare when it reads back as the same value, else quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float) or is_reference(value):
        return _literal(value)
    bare = _WIDGET_BARE.fullmatch(value) and value not in ("true", "false") and not _NUMBER.fullmatch(value)
    return value if bare else _quote(value)


def _write_widget(w: _Writer, node: dict[str, Any], depth: int) -> None:
    settings = "".join(f" {name}={_widget_literal(value)}" for name, value in node.get("params", {}).items())
    sorting = "".join(
        f" sort {_bare_or_quoted(k['column'])}" + ("" if "descending" not in k else " desc" if k["descending"] else " asc")
        for k in node.get("sort", [])
    )
    empty = f" empty {_quote(node['empty_text'])}" if "empty_text" in node else ""
    w.line(depth, f"[[widget.{node['key']}{settings}{sorting}{empty}]]")


for _form in (
    TextForm("heading", _parse_heading, _write_heading),
    TextForm("text", _parse_text, _write_text),
    TextForm("page_break", _parse_page_break, _write_page_break),
    TextForm("equation", _parse_equation, _write_equation),
    TextForm("table", _parse_table, _write_table),
    TextForm("each", _parse_each, _write_each),
    TextForm("group", _parse_group, _write_group),
    TextForm("if", _parse_if, _write_if),
    TextForm("sheet", _parse_sheet, _write_sheet),
    TextForm("widget", _parse_widget, _write_widget, bracketed=True),
):
    register_text_form(_form)

__all__ = [
    "MAX_TEXT_VIEW_CHARS", "TEXT_FORMS", "ParseResult", "TextError", "TextForm", "format_tree", "parse_text",
    "register_text_form",
]
