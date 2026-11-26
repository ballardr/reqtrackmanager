"""
Module: modules.traceability.rule_evaluation

Evaluates one traceability rule for the records of one project: which records are in scope and, for each, how many links
each requirement leaf finds and whether the rule holds.

Responsibilities:
- Read the project's records of the rule's source type, narrow them by the rule's sub-type and `applies_when` tree, and count
  for each record the distinct records at the other end of the links each `requires` leaf names (`evaluate_rule`).
- Name each leaf for a status view (`leaf_label`) so a result can show a checkmark per requirement.

Design decisions:
- The statement count grows with the rule's leaves and the record types it names, never with the records: each leaf reads the
  links of every in-scope record in one query, and the records at the other ends are read once per record type and project.
- A leaf counts distinct records at the other end, so two links of different types to one record count once.
- A record at the other end that the project cannot see, or that is archived, is not counted (`get_artefact_summaries_in_project`),
  so a link to a removed record never satisfies a rule.
- Links that cross into an ancestor or descendant project are counted only when `include_cross_project` is set; the default is
  the project's own links, so a rule's result never depends on records the viewer may not open.
- Evaluation only computes. It never changes a record, never blocks a transition and reports what it cannot evaluate (a record
  type or field that is no longer registered) as `problems` instead of guessing.

Dependencies: `modules.registry`, `services.record_summaries`, `services.relationships`, `modules.traceability.rule_tree`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.modules import registry
from app.modules.traceability import rule_tree
from app.modules.traceability.rule_tree import LinkLeaf, Node
from app.services import record_summaries, relationships


@dataclass(frozen=True)
class LeafResult:
    """How one requirement leaf fared for one record.

    Attributes:
        path: The leaf's position in the `requires` tree (`rule_tree.leaves`).
        label: The leaf's name in a status view.
        count: Distinct records found at the other end.
        met: Whether `count` is within the leaf's minimum and maximum.
    """

    path: str
    label: str
    count: int
    met: bool


@dataclass(frozen=True)
class RecordResult:
    """A record in a rule's scope and whether the rule holds for it.

    Attributes:
        record_id: The record.
        satisfied: Whether the `requires` tree is satisfied.
        leaves: One result per link leaf, in tree order.
    """

    record_id: uuid.UUID
    satisfied: bool
    leaves: tuple[LeafResult, ...]


@dataclass(frozen=True)
class RuleEvaluation:
    """The outcome of evaluating a rule in a project.

    Attributes:
        source_total: The project's records of the source type (after the sub-type narrowing) before `applies_when`.
        in_scope: A result for each record the rule applies to, ordered by record id.
        problems: Why the rule could not be evaluated (a type or field that is not registered); `in_scope` is empty then.
    """

    source_total: int
    in_scope: tuple[RecordResult, ...] = ()
    problems: tuple[str, ...] = field(default=())

    @property
    def satisfied_count(self) -> int:
        """In-scope records the rule holds for."""
        return sum(1 for r in self.in_scope if r.satisfied)

    @property
    def unsatisfied_count(self) -> int:
        """In-scope records the rule does not hold for."""
        return len(self.in_scope) - self.satisfied_count


def leaf_label(leaf: LinkLeaf) -> str:
    """The leaf's own label, or a generated one: `Links to Requirement (Stakeholder Requirement)`."""
    if leaf.label:
        return leaf.label
    named = []
    for target in leaf.targets:
        label = registry.get_artefact_type_label(target.artefact_type)
        named.append(f"{label} ({target.subtype})" if target.subtype else label)
    verb = "Links to" if leaf.direction == "outgoing" else "Linked from"
    return f"{verb} {' or '.join(named)}"


class _OtherEnds:
    """The summaries and sub-types of records at the far end of links, read once per record type and project."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._summaries: dict[tuple[str, uuid.UUID], dict[uuid.UUID, str | None]] = {}
        self._asked: dict[tuple[str, uuid.UUID], set[uuid.UUID]] = defaultdict(set)

    def load(self, artefact_type: str, project_id: uuid.UUID, ids: set[uuid.UUID], *, want_subtype: bool) -> None:
        """Reads the records `ids` of one type in one project that have not been read yet."""
        key = (artefact_type, project_id)
        fresh = ids - self._asked[key]
        if not fresh:
            return
        self._asked[key] |= fresh
        found = record_summaries.read_summaries(self._db, project_id, artefact_type, sorted(fresh))
        visible = [i for i, s in found.items() if not s.is_archived]
        subtypes = registry.resolve_record_subtypes(self._db, project_id, artefact_type, visible) if visible and want_subtype else {}
        self._summaries.setdefault(key, {}).update({i: subtypes.get(i) for i in visible})

    def subtype_of(self, artefact_type: str, project_id: uuid.UUID, record_id: uuid.UUID) -> tuple[bool, str | None]:
        """`(counted, sub-type)`: whether the record is visible and not archived, and its sub-type if it has one."""
        known = self._summaries.get((artefact_type, project_id), {})
        return (record_id in known, known.get(record_id))


def _leaf_counts(
    db: Session, project_id: uuid.UUID, source_type: str, source_ids: Sequence[uuid.UUID], leaf: LinkLeaf, ends: _OtherEnds,
    *, include_cross_project: bool,
) -> dict[uuid.UUID, int]:
    """Distinct matching records at the other end of the links of each source record, for one leaf."""
    if leaf.direction == "outgoing":
        rows = relationships.get_links_from_many(db, source_type, source_ids, include_cross_project=include_cross_project)
    else:
        rows = relationships.get_links_to_many(db, source_type, source_ids, include_cross_project=include_cross_project)
    wanted_types = {t.artefact_type for t in leaf.targets}
    candidates: list[tuple[uuid.UUID, str, uuid.UUID, uuid.UUID]] = []
    for link in rows:
        if leaf.link_types.mode == "untyped" and link.link_type_id is not None:
            continue
        if leaf.link_types.mode == "types" and link.link_type_id not in leaf.link_types.ids:
            continue
        if leaf.direction == "outgoing":
            own, other_type, other_id, other_project = link.source_id, link.target_type, link.target_id, link.target_project_id
        else:
            own, other_type, other_id, other_project = link.target_id, link.source_type, link.source_id, link.source_project_id
        if other_type in wanted_types:
            candidates.append((own, other_type, other_id, other_project or project_id))
    grouped: dict[tuple[str, uuid.UUID], set[uuid.UUID]] = defaultdict(set)
    for _own, other_type, other_id, other_project in candidates:
        grouped[(other_type, other_project)].add(other_id)
    needs_subtype = any(t.subtype for t in leaf.targets)
    for (other_type, other_project), ids in grouped.items():
        ends.load(other_type, other_project, ids, want_subtype=needs_subtype)
    matched: dict[uuid.UUID, set[tuple[str, uuid.UUID]]] = defaultdict(set)
    for own, other_type, other_id, other_project in candidates:
        counted, subtype = ends.subtype_of(other_type, other_project, other_id)
        if not counted:
            continue
        for target in leaf.targets:
            if target.artefact_type != other_type:
                continue
            if target.subtype is None or (subtype is not None and subtype.casefold() == target.subtype.casefold()):
                matched[own].add((other_type, other_id))
                break
    return {own: len(found) for own, found in matched.items()}


def _problems(
    source_type: str, applies_when: Node | None, requires: Node, fields: Mapping[str, registry.RuleConditionField],
) -> list[str]:
    """What stops the rule being evaluated: a record type or condition field that is not registered."""
    problems: list[str] = []
    registered = registry.get_all_registered_artefact_types()
    if source_type not in registered:
        problems.append(f"The record type {source_type!r} is not available.")
    for _path, leaf in rule_tree.leaves(requires):
        for target in leaf.targets:
            if target.artefact_type not in registered:
                problems.append(f"The record type {target.artefact_type!r} is not available.")
    for condition in rule_tree.conditions(applies_when):
        if condition.field not in fields:
            problems.append(f"The condition field {condition.field!r} is not available.")
    return sorted(set(problems))


def evaluate_rule(
    db: Session, project_id: uuid.UUID, *, source_type: str, source_subtype: str | None, applies_when: Node | None, requires: Node,
    include_cross_project: bool = False,
) -> RuleEvaluation:
    """Evaluates a rule for the records of a project.

    Args:
        db: Active session (read only).
        project_id: The project whose records are evaluated.
        source_type: The record type the rule applies to.
        source_subtype: A sub-type to limit the rule to, or `None`.
        applies_when: The scope tree, or `None` for every record.
        requires: The requirement tree.
        include_cross_project: Count links that cross into an ancestor or descendant project.

    Returns:
        The evaluation: every in-scope record with a result per leaf, or `problems` when the rule names something that is not
        registered.
    """
    fields = {key: f for key, (_module, f) in registry.get_rule_condition_fields().items()}
    problems = _problems(source_type, applies_when, requires, fields)
    if problems:
        return RuleEvaluation(source_total=0, problems=tuple(problems))
    summaries = [s for s in record_summaries.list_summaries(db, project_id, source_type) if not s.is_archived]
    ids = sorted(s.id for s in summaries)
    if source_subtype is not None and ids:
        names = registry.resolve_record_subtypes(db, project_id, source_type, ids)
        ids = [i for i in ids if (names.get(i) or "").casefold() == source_subtype.casefold()]
    total = len(ids)
    held: dict[str, Mapping[uuid.UUID, Sequence[str | int]]] = {}
    for condition in rule_tree.conditions(applies_when):
        if condition.field not in held:
            held[condition.field] = fields[condition.field].values(db, project_id, source_type, ids) if ids else {}
    def in_scope_of(record_id: uuid.UUID) -> bool:
        return rule_tree.holds(applies_when, lambda key: held.get(key, {}).get(record_id, ()))

    in_scope = [i for i in ids if in_scope_of(i)]
    if not in_scope:
        return RuleEvaluation(source_total=total)
    ends = _OtherEnds(db)
    leaves = rule_tree.leaves(requires)
    per_leaf = {
        path: _leaf_counts(db, project_id, source_type, in_scope, leaf, ends, include_cross_project=include_cross_project)
        for path, leaf in leaves
    }
    results = []
    for record_id in in_scope:
        counts = {path: found.get(record_id, 0) for path, found in per_leaf.items()}
        results.append(RecordResult(
            record_id=record_id, satisfied=rule_tree.satisfied(requires, counts),
            leaves=tuple(LeafResult(path, leaf_label(leaf), counts[path], rule_tree.leaf_met(leaf, counts[path])) for path, leaf in leaves),
        ))
    return RuleEvaluation(source_total=total, in_scope=tuple(results))
