"""
Module: services.report_layout_eval

Evaluates a validated layout tree for one caller and returns the neutral report model: a
`ReportDocument` (document family) or a list of `Sheet`s (table family).

Responsibilities:
- Walk the tree, reading records through the traversal layer (`services.report_traversal`) and the
  field registry (`services.report_fields`), and emit `Heading`/`Paragraph`/`Table`/... blocks.
- Substitute `{{alias.field}}` and the global `{{project_name}}`-style placeholders into the parsed
  text of headings, text blocks, table cells and empty-state lines.
- Apply `where`, `sort` and `group` in memory over typed values, and `if` on one field.
- Bound the work: iteration, output-row and wall-clock caps raise `LayoutLimitError`; a traversal
  that hit its record cap adds a warning and a visible note instead of failing.
- Count what the caller could not see (never name it) and report it as a note.

Design decisions:
- **Authorisation is the traversal layer's, nothing here.** Every record this module reads came out of
  `root_records`/`linked_records`, which pass each through the caller's `ArtefactResolver`; the
  evaluator adds no visibility rule, so a layout never shows a record the caller's link graph would
  not. A record that fails is counted per parent and not traversed through.
- **A value never becomes markup.** Markdown is parsed first, from the author's text alone; record
  values are substituted into the parsed blocks afterwards, in a single pass that does not rescan
  the substituted text, so a title containing `# heading` or `{{record.title}}` stays literal text.
- The tree is revalidated before every run (`assert_valid`): a stored tree can predate a registry
  change (a module field removed), and the field references the analysis returns decide which
  columns are loaded.
- Linked records are fetched in batches. The first time a nested block needs the records linked to
  one parent it fetches for every record of that type read so far (`_Run.pool`), so the number of
  link queries follows the number of nested blocks, not the number of records.
- Group order is by the group field's typed value (so dates and numbers sort as such), the empty
  group last as `(none)`; a record with no value for a sort key sorts last in both directions.
- Past instants stay UTC and dates are plain dates (`format_value`); no server-local time or
  timezone conversion happens here.

Dependencies: `services.report_layout_tree` (validation), `services.report_fields`,
`services.report_traversal`, `services.report_framework.ReportContext` (record codes),
`services.link_type_scope` (link type names), `services.report_model` (output blocks).
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.report_layout import FAMILY_DOCUMENT
from app.services.link_graph import ArtefactResolver
from app.services.link_type_scope import resolve_link_type_scope
from app.services.report_fields import RESERVED_FIELD_KEYS, FieldInfo, ReportRecord, field_catalogue, format_value, load_records
from app.services.report_framework import ReportContext
from app.services.report_layout_tree import (
    DEFAULT_GROUP_ALIAS,
    DEFAULT_RECORD_ALIAS,
    PLACEHOLDER_RE,
    assert_valid,
)
from app.services.report_model import (
    Block,
    BulletList,
    Heading,
    Note,
    PageBreak,
    Paragraph,
    ReportDocument,
    Sheet,
    Table,
    markdown_to_blocks,
)
from app.services.report_traversal import MAX_LINKED, MAX_ROOTS, LinkDirection, linked_records, root_records

#: Most record visits (loop iterations over records, in all nested blocks) one run may make.
MAX_WORK = 200_000
#: Most output blocks plus table rows one run may produce.
MAX_OUTPUT = 100_000
DEFAULT_TIMEOUT_SECONDS = 60.0
EMPTY_GROUP_LABEL = "(none)"

Key = tuple[str, uuid.UUID]
Scope = dict[str, "Bound"]


class LayoutLimitError(RuntimeError):
    """A run exceeded its work, output or time limit; the caller offers an async run or a narrower layout."""


class LayoutTimeoutError(LayoutLimitError):
    """A run exceeded its wall-clock limit."""


@dataclass
class EvalStats:
    """What a run read and produced (for provenance and the sync/async decision).

    Attributes:
        records_read: Records loaded, by artefact type.
        blocks: Blocks emitted (document family).
        rows: Table and sheet rows emitted.
        hidden: Records the caller could not see (counted, never named).
        unavailable: Records of a type no installed module can display, or over a dormant link.
    """

    records_read: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    blocks: int = 0
    rows: int = 0
    hidden: int = 0
    unavailable: int = 0


@dataclass
class EvaluatedLayout:
    """The result of a run.

    Attributes:
        family: `document` or `table`.
        document: The neutral document (document family), else `None`.
        sheets: The sheets (table family), else empty.
        warnings: Things the reader should know (a cap truncated a read, a link type name matched nothing).
        stats: Counters.
        source_digest: SHA-256 hex over every record read (type, id, last-change time), so two runs can be
            compared for "did the source data change" without storing the records.
    """

    family: str
    document: ReportDocument | None
    sheets: list[Sheet]
    warnings: list[str]
    stats: EvalStats
    source_digest: str = ""


@dataclass
class Bound:
    """What an alias stands for at run time: one record, or one group of records.

    Attributes:
        kind: `record` or `group`.
        record_type: The artefact type (of the record, or of the group's members).
        record: The record (`record` kind).
        label: The group's printed value (`group` kind).
        members: The group's records (`group` kind).
    """

    kind: str
    record_type: str
    record: ReportRecord | None = None
    label: str = ""
    members: list[ReportRecord] = field(default_factory=list)


@dataclass
class _Source:
    """Records a block iterates plus the counts of those the caller cannot see."""

    records: list[ReportRecord]
    hidden: int = 0
    unavailable: int = 0


@dataclass
class _Linked:
    """Linked records fetched so far for one consuming block."""

    covered: set[Key] = field(default_factory=set)
    by_parent: dict[Key, list[ReportRecord]] = field(default_factory=dict)
    hidden: dict[Key, int] = field(default_factory=dict)
    unavailable: dict[Key, int] = field(default_factory=dict)


Evaluator = Callable[["_Run", dict[str, Any], Scope], None]
_EVALUATORS: dict[str, Evaluator] = {}


def register_evaluator(key: str, evaluator: Evaluator) -> None:
    """Adds the evaluation of a block type (the counterpart of `report_layout_tree.register_block_spec`)."""
    if key in _EVALUATORS:
        raise ValueError(f"block type {key!r} already has an evaluator")
    _EVALUATORS[key] = evaluator


def evaluate_layout(
    db: Session,
    resolver: ArtefactResolver,
    ctx: ReportContext,
    tree: dict[str, Any],
    *,
    title: str,
    placeholders: Mapping[str, str] | None = None,
    project_ids: list[uuid.UUID] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> EvaluatedLayout:
    """Runs a layout for the caller behind `resolver`.

    Args:
        db: Active session (read only).
        resolver: The caller's resolver for the report's project: the one authorisation point.
        ctx: The run context; supplies the organisation, the projects in scope and record-code
            formatting. Its `root_project` must be set (an organisation-wide run is a later extension).
        tree: The layout tree.
        title: The report title (the `{{report_title}}` placeholder and the document title).
        placeholders: Overrides for the global placeholders (`project_name`, `report_title`,
            `generated_on`, `organisation`).
        project_ids: Projects whose records a root source reads; defaults to `ctx.projects`.
        timeout_seconds: Wall-clock limit.

    Returns:
        The evaluated layout.

    Raises:
        InvalidLayoutError: The tree is not valid.
        LayoutLimitError: A work, output or time limit was exceeded (`LayoutTimeoutError` for time).
        ValueError: `ctx` has no root project.
    """
    if ctx.root_project is None:
        raise ValueError("A layout runs for one project; ctx.root_project is required.")
    analysis = assert_valid(tree)
    run = _Run(db, resolver, ctx, ctx.root_project, analysis.refs, title, placeholders, project_ids, timeout_seconds)
    for node in tree["nodes"]:
        run.evaluate(node, {})
    document = None
    if tree["family"] == FAMILY_DOCUMENT:
        document = ReportDocument(title=title, blocks=run.blocks, landscape=tree.get("orientation") == "landscape")
    return EvaluatedLayout(tree["family"], document, run.sheets, run.warnings, run.stats, run.source_digest())


class _Run:
    """The state of one evaluation: caches, counters, output and the helpers blocks use."""

    def __init__(
        self,
        db: Session,
        resolver: ArtefactResolver,
        ctx: ReportContext,
        project: Project,
        refs: dict[int, frozenset[tuple[str, str]]],
        title: str,
        placeholders: Mapping[str, str] | None,
        project_ids: list[uuid.UUID] | None,
        timeout_seconds: float,
    ) -> None:
        self.db, self.resolver, self.ctx, self.project, self.refs = db, resolver, ctx, project, refs
        self.project_ids = project_ids or [p.id for p in ctx.projects] or [project.id]
        self.placeholders: dict[str, str] = {
            "project_name": ctx.scope_label, "report_title": title,
            "generated_on": ctx.today.isoformat(), "organisation": ctx.organization.name,
            **(placeholders or {}),
        }
        self.deadline = time.monotonic() + timeout_seconds
        self.blocks: list[Block] = []
        self.sheets: list[Sheet] = []
        self.warnings: list[str] = []
        self.stats = EvalStats()
        self._work = 0
        self._output = 0
        self._catalogues: dict[str, dict[str, FieldInfo]] = {}
        self._markdown: dict[str, list[Block]] = {}
        self._roots: dict[tuple[Any, ...], _Source] = {}
        self._link_ids: dict[tuple[str, ...], set[uuid.UUID]] = {}
        self._linked: dict[int, _Linked] = {}
        #: Every record read so far, by type: the batch a nested linked source fetches for.
        self._pool: dict[str, dict[uuid.UUID, ReportRecord]] = defaultdict(dict)

    def source_digest(self) -> str:
        """SHA-256 hex over the records read: `type:id:last-change` per record, sorted.

        A versioned record's last-change time is its current version's, so a new version changes the digest.
        """
        lines = sorted(
            f"{artefact_type}:{record.id}:{record.updated_at.isoformat() if record.updated_at else ''}"
            for artefact_type, records in self._pool.items() for record in records.values()
        )
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()

    # --- dispatch and limits ---------------------------------------------------------------

    def evaluate(self, node: dict[str, Any], scope: Scope) -> None:
        """Evaluates one block."""
        self.tick()
        _EVALUATORS[node["type"]](self, node, scope)

    def children(self, nodes: list[dict[str, Any]], scope: Scope) -> None:
        """Evaluates a list of child blocks."""
        for child in nodes:
            self.evaluate(child, scope)

    def tick(self) -> None:
        """Counts one unit of work and enforces the time and work limits.

        Raises:
            LayoutTimeoutError: Past the deadline.
            LayoutLimitError: Past `MAX_WORK`.
        """
        self._work += 1
        if self._work > MAX_WORK:
            raise LayoutLimitError("The layout visits too many records. Narrow it with a filter, or run it asynchronously.")
        if time.monotonic() > self.deadline:
            raise LayoutTimeoutError("The layout took too long to run. Narrow it with a filter, or run it asynchronously.")

    def emit(self, *blocks: Block) -> None:
        """Appends blocks to the document, enforcing the output limit."""
        for block in blocks:
            self.stats.blocks += 1
            rows = len(block.rows) if isinstance(block, Table) else 0
            self.stats.rows += rows
            self._count_output(1 + rows)
            self.blocks.append(block)

    def _count_output(self, amount: int) -> None:
        self._output += amount
        if self._output > MAX_OUTPUT:
            raise LayoutLimitError("The report is too large. Narrow the layout with a filter, or run it asynchronously.")

    def warn(self, message: str) -> None:
        """Records a warning once."""
        if message not in self.warnings:
            self.warnings.append(message)

    # --- fields and text -------------------------------------------------------------------

    def catalogue(self, record_type: str) -> dict[str, FieldInfo]:
        """`{key: FieldInfo}` of a type."""
        if record_type not in self._catalogues:
            self._catalogues[record_type] = {f.key: f for f in field_catalogue(record_type)}
        return self._catalogues[record_type]

    def code(self, record: ReportRecord) -> str:
        """The record's code as this report shows it."""
        if not record.unique_code:
            return ""
        if record.project_id is not None:
            return self.ctx.code(record.unique_code, record.project_id)
        return self.ctx.org_code(record.unique_code)

    def raw(self, record: ReportRecord, key: str) -> Any:
        """A field's typed value (reserved keys as the text the report prints)."""
        if key == "code":
            return self.code(record)
        if key == "title":
            return record.title
        if key == "status":
            return record.status
        if key == "tags":
            return record.tags
        return record.values.get(key)

    def text_of(self, record: ReportRecord, key: str) -> str:
        """A field as printed text."""
        value = self.raw(record, key)
        if key in RESERVED_FIELD_KEYS:
            return value or ""
        return format_value(self.catalogue(record.artefact_type)[key].kind, value)

    def fill(self, text: str, scope: Scope) -> str:
        """Substitutes `{{...}}` placeholders in already-parsed text, in one pass over `text` only."""

        def replace(match: re.Match[str]) -> str:
            name, member = match.group(1), match.group(2)
            if member is None:
                return self.placeholders.get(name, match.group(0))
            bound = scope.get(name)
            if bound is None:
                return match.group(0)
            if bound.kind == "group":
                return bound.label if member == "value" else str(len(bound.members))
            assert bound.record is not None
            return self.text_of(bound.record, member)

        return PLACEHOLDER_RE.sub(replace, text) if "{{" in text else text

    def text_blocks(self, source: str, scope: Scope) -> list[Block]:
        """Markdown `source` as blocks with placeholders filled (parsed once, filled each time)."""
        if source not in self._markdown:
            self._markdown[source] = markdown_to_blocks(source)
        out: list[Block] = []
        for block in self._markdown[source]:
            if isinstance(block, Heading):
                out.append(Heading(self.fill(block.text, scope), block.level))
            elif isinstance(block, Paragraph):
                out.append(Paragraph(self.fill(block.text, scope)))
            elif isinstance(block, BulletList):
                out.append(BulletList([self.fill(item, scope) for item in block.items]))
            else:
                out.append(block)
        return out

    # --- conditions, sort, group -----------------------------------------------------------

    def passes(self, record: ReportRecord, conds: list[dict[str, Any]]) -> bool:
        """Whether `record` satisfies every `where` condition."""
        info = self.catalogue(record.artefact_type)
        return all(
            matches_value(self.raw(record, c["field"]), info[c["field"]].kind, c["op"], c.get("value")) for c in conds
        )

    def sort_key(self, record: ReportRecord, key: str) -> Any:
        """A comparable form of a field value (text case-insensitively), `None` when empty."""
        value = self.raw(record, key)
        if value is None or value == "":
            return None
        return str(value).casefold() if isinstance(value, str) else value

    def ordered_by(self, records: list[ReportRecord], keys: list[dict[str, Any]]) -> list[ReportRecord]:
        """`records` ordered by the `sort` keys; records lacking a value come last either way."""
        ordered = list(records)
        for item in reversed(keys):
            present = [r for r in ordered if self.sort_key(r, item["field"]) is not None]
            absent = [r for r in ordered if self.sort_key(r, item["field"]) is None]
            present.sort(key=lambda r: self.sort_key(r, item["field"]), reverse=bool(item.get("descending")))
            ordered = present + absent
        return ordered

    # --- sources ---------------------------------------------------------------------------

    def fields_for(self, node: dict[str, Any], record_type: str) -> tuple[list[str], bool]:
        """The provider fields (and whether tags) the subtree of `node` needs of `record_type`."""
        keys = {k for t, k in self.refs.get(id(node), frozenset()) if t == record_type}
        return sorted(keys - set(RESERVED_FIELD_KEYS)), "tags" in keys

    def source(self, node: dict[str, Any], scope: Scope) -> _Source:
        """The records `node["source"]` selects, filtered and sorted, with the unseen counts."""
        src = node["source"]
        if "group" in src:
            found = _Source(list(scope[src["group"]].members))
        elif "linked_from" in src:
            found = self._linked_source(node, src, scope)
        else:
            found = self._root_source(node, src)
        records = [r for r in found.records if self.passes(r, src.get("where", []))]
        for record in records:
            self._pool[record.artefact_type][record.id] = record
        return _Source(self.ordered_by(records, src.get("sort", [])), found.hidden, found.unavailable)

    def _root_source(self, node: dict[str, Any], src: dict[str, Any]) -> _Source:
        record_type = src["record_type"]
        fields, with_tags = self.fields_for(node, record_type)
        include_archived = bool(src.get("include_archived"))
        cache_key = (record_type, include_archived, tuple(fields), with_tags)
        if cache_key not in self._roots:
            roots = root_records(
                self.db, self.resolver, self.project, record_type, self.project_ids, include_archived=include_archived,
            )
            if roots.truncated:
                self.warn(f"Only the first {MAX_ROOTS} {record_type.replace('_', ' ')} records were read.")
            loaded = load_records(self.db, record_type, [s.id for s in roots.summaries], fields, with_tags=with_tags)
            self.stats.records_read[record_type] += len(loaded)
            self.stats.hidden += roots.hidden
            self.stats.unavailable += roots.unavailable
            self._roots[cache_key] = _Source(
                [loaded[s.id] for s in roots.summaries if s.id in loaded], roots.hidden, roots.unavailable,
            )
        return self._roots[cache_key]

    def _linked_source(self, node: dict[str, Any], src: dict[str, Any], scope: Scope) -> _Source:
        parent = scope[src["linked_from"]].record
        assert parent is not None
        parent_key = (parent.artefact_type, parent.id)
        data = self._linked.setdefault(id(node), _Linked())
        if parent_key not in data.covered:
            self._fetch_linked(node, src, data, parent)
        return _Source(
            data.by_parent.get(parent_key, []), data.hidden.get(parent_key, 0), data.unavailable.get(parent_key, 0),
        )

    def _fetch_linked(self, node: dict[str, Any], src: dict[str, Any], data: _Linked, parent: ReportRecord) -> None:
        """Fetches linked records for `parent` and every other record of its type read so far."""
        pending = {parent.id: parent} | self._pool[parent.artefact_type]
        parents = [(parent.artefact_type, rid) for rid in pending if (parent.artefact_type, rid) not in data.covered]
        target_type = src["record_type"]
        fields, with_tags = self.fields_for(node, target_type)
        found = linked_records(
            self.db, self.resolver, parents, target_type,
            link_type_ids=self._link_type_ids(src.get("link_types")),
            direction=LinkDirection(src.get("direction", "both")),
        )
        if found.truncated:
            self.warn(f"Only the first {MAX_LINKED} linked {target_type.replace('_', ' ')} records were read.")
        loaded = load_records(
            self.db, target_type, {s.id for shown in found.by_parent.values() for s in shown}, fields, with_tags=with_tags,
        )
        self.stats.records_read[target_type] += len(loaded)
        include_archived = bool(src.get("include_archived"))
        for key in parents:
            data.covered.add(key)
            data.by_parent[key] = [
                loaded[s.id] for s in found.by_parent.get(key, [])
                if s.id in loaded and (include_archived or not loaded[s.id].is_archived)
            ]
            if key in found.hidden:
                data.hidden[key] = found.hidden[key]
                self.stats.hidden += found.hidden[key]
            if key in found.unavailable:
                data.unavailable[key] = found.unavailable[key]
                self.stats.unavailable += found.unavailable[key]

    def _link_type_ids(self, names: list[str] | None) -> set[uuid.UUID] | None:
        """Ids of the project's link types named (forward or reverse) in `names`; `None` for any."""
        if not names:
            return None
        wanted = tuple(sorted({n.casefold() for n in names}))
        if wanted not in self._link_ids:
            matched: set[uuid.UUID] = set()
            seen: set[str] = set()
            for scoped in resolve_link_type_scope(self.db, self.project):
                link_type = scoped.link_type
                spelled = {link_type.forward_name.casefold(), link_type.reverse_name.casefold()}
                if scoped.shadowed_by is None and spelled & set(wanted):
                    matched.add(link_type.id)
                    seen |= spelled
            for name in names:
                if name.casefold() not in seen:
                    self.warn(f'No link type is named "{name}" in this project, so it matches nothing.')
            self._link_ids[wanted] = matched
        return self._link_ids[wanted]

    def unseen_note(self, found: _Source, what: str, *, filtered: bool = False) -> None:
        """Emits the count of records the caller cannot see, if any (never their names).

        Args:
            found: The block's source result.
            what: The noun, singular.
            filtered: Whether the block has a `where`; the unseen records were counted before it, so
                the figure is an upper bound.
        """
        count = found.hidden + found.unavailable
        if count:
            lead = "Up to " if filtered else ""
            plural = "" if count == 1 and not filtered else "s"
            self.emit(Note(f"{lead}{count} {what}{plural} not shown (not accessible to you, or not available)."))


def matches_value(actual: Any, kind: str, op: str, expected: Any) -> bool:
    """Whether a typed value satisfies `op expected` (see `OPERATORS_BY_KIND`)."""
    if op == "empty":
        return actual is None or actual == ""
    if op == "not_empty":
        return not (actual is None or actual == "")
    if actual is None or actual == "":
        return op == "ne"
    if kind in ("text", "principal", "enum"):
        have = str(actual).casefold()
        if op == "in":
            return have in {str(e).casefold() for e in expected}
        want = str(expected).casefold()
        return {"eq": have == want, "ne": have != want, "contains": want in have}[op]
    if kind == "bool":
        return (bool(actual) == expected) if op == "eq" else (bool(actual) != expected)
    if kind == "date":
        expected = date.fromisoformat(expected)
    elif kind == "instant":
        expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    return {
        "eq": actual == expected, "ne": actual != expected, "gt": actual > expected,
        "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected,
    }[op]


# --- block evaluators ----------------------------------------------------------------------------


def _eval_heading(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    run.emit(Heading(run.fill(node["text"], scope), node.get("level", 1)))


def _eval_text(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    run.emit(*run.text_blocks(node["text"], scope))


def _eval_page_break(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    run.emit(PageBreak())


def _source_type(node: dict[str, Any], scope: Scope) -> str:
    """The record type a block's source yields (a group's members take the group's type)."""
    src = node["source"]
    return scope[src["group"]].record_type if "group" in src else src["record_type"]


def _table_cells(run: _Run, node: dict[str, Any], scope: Scope, records: list[ReportRecord]) -> tuple[list[str], list[list[str]]]:
    """Header labels (a column's own, else the field's) and body cells for `columns` over `records`."""
    columns = node["columns"]
    info = run.catalogue(_source_type(node, scope))
    labels = [c.get("label") or info[c["field"]].label for c in columns]
    rows = []
    for record in records:
        run.tick()
        rows.append([run.text_of(record, c["field"]) for c in columns])
    return labels, rows


def _eval_table(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    found = run.source(node, scope)
    if found.records:
        labels, rows = _table_cells(run, node, scope, found.records)
        run.emit(Table(labels, rows, compact=True))
    elif node.get("empty_text"):
        run.emit(Note(run.fill(node["empty_text"], scope)))
    run.unseen_note(found, "record", filtered=bool(node["source"].get("where")))


def _eval_each(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    alias = node.get("as", DEFAULT_RECORD_ALIAS)
    found = run.source(node, scope)
    if not found.records and node.get("empty_text"):
        run.emit(Note(run.fill(node["empty_text"], scope)))
    for record in found.records:
        run.tick()
        run.children(node["children"], {**scope, alias: Bound("record", record.artefact_type, record=record)})
    run.unseen_note(found, "record", filtered=bool(node["source"].get("where")))


def _eval_group(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    alias = node.get("as", DEFAULT_GROUP_ALIAS)
    found = run.source(node, scope)
    key = node["by"]
    groups: dict[str, list[ReportRecord]] = {}
    for record in found.records:
        run.tick()
        groups.setdefault(run.text_of(record, key) or EMPTY_GROUP_LABEL, []).append(record)

    def order(label: str) -> tuple[bool, Any]:
        typed = run.sort_key(groups[label][0], key)
        return label == EMPTY_GROUP_LABEL, (label.casefold() if typed is None else typed)

    for label in sorted(groups, key=order):
        members = groups[label]
        run.children(node["children"], {**scope, alias: Bound("group", members[0].artefact_type, label=label, members=members)})
    run.unseen_note(found, "record", filtered=bool(node["source"].get("where")))


def _eval_if(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    when = node["when"]
    alias, member = when["ref"].split(".")
    bound = scope[alias]
    if bound.kind == "group":
        actual: Any = bound.label if member == "value" else len(bound.members)
        kind = "text" if member == "value" else "number"
    else:
        assert bound.record is not None
        actual = run.raw(bound.record, member)
        kind = run.catalogue(bound.record_type)[member].kind
    chosen = node["children"] if matches_value(actual, kind, when["op"], when.get("value")) else node.get("else_children", [])
    run.children(chosen, scope)


def _eval_sheet(run: _Run, node: dict[str, Any], scope: Scope) -> None:
    """One sheet: a row per root record, widened by each left join to a row per linked record.

    A root or joined record with nothing linked still yields its row, with blank cells for the join;
    a join that follows a blank one stays blank. Rows are in root order, then each join's sort.
    """
    root = run.source(node, scope)
    root_alias = node.get("as", DEFAULT_RECORD_ALIAS)
    types = {root_alias: node["source"]["record_type"]}
    rows_of: list[dict[str, ReportRecord | None]] = [{root_alias: r} for r in root.records]
    unseen = 0
    counted: set[tuple[str, uuid.UUID]] = set()
    for join in node.get("joins", []):
        alias, parent_alias = join["as"], join["source"]["linked_from"]
        types[alias] = join["source"]["record_type"]
        widened: list[dict[str, ReportRecord | None]] = []
        for combo in rows_of:
            run.tick()
            parent = combo.get(parent_alias)
            if parent is None:
                widened.append({**combo, alias: None})
                continue
            found = run.source(join, {name: Bound("record", rec.artefact_type, record=rec) for name, rec in combo.items() if rec is not None})
            if (alias, parent.id) not in counted:  # a parent that appears in many rows is counted once
                counted.add((alias, parent.id))
                unseen += found.hidden + found.unavailable
            if found.records:
                widened.extend({**combo, alias: child} for child in found.records)
            else:
                widened.append({**combo, alias: None})
            if len(widened) > MAX_OUTPUT:
                raise LayoutLimitError("The report is too large. Narrow the layout with a filter, or run it asynchronously.")
        rows_of = widened

    columns = node["columns"]
    labels = [c.get("label") or run.catalogue(types[c.get("from", root_alias)])[c["field"]].label for c in columns]
    rows = []
    for combo in rows_of:
        run.tick()
        rows.append([
            run.text_of(record, c["field"]) if (record := combo[c.get("from", root_alias)]) is not None else "" for c in columns
        ])
    run.stats.rows += len(rows)
    run._count_output(1 + len(rows))
    run.sheets.append(Sheet(node["name"], labels, rows))
    count = root.hidden + root.unavailable + unseen
    if count:
        run.warn(f'Sheet "{node["name"]}": {count} record(s) not shown (not accessible to you, or not available).')


for _key, _fn in (
    ("heading", _eval_heading), ("text", _eval_text), ("page_break", _eval_page_break), ("table", _eval_table),
    ("each", _eval_each), ("group", _eval_group), ("if", _eval_if), ("sheet", _eval_sheet),
):
    register_evaluator(_key, _fn)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS", "EMPTY_GROUP_LABEL", "MAX_OUTPUT", "MAX_WORK", "EvalStats", "EvaluatedLayout",
    "LayoutLimitError", "LayoutTimeoutError", "evaluate_layout", "matches_value", "register_evaluator",
]
