"""
Module: modules.traceability.status

A record's traceability status: every rule that applies to it, whether it meets each requirement of each rule, and where
an unmet Required rule refuses something. The records' standing is computed from the rules and links each time; nothing is
stored.

Responsibilities:
- Evaluate a project's active rules for the records of one type (`record_statuses`).
- Say where a rule is enforced in a project, or why it is not (`Enforcement`, `enforcement_for`).

Design decisions:
- Traceability computes and never blocks. A Required rule refuses a baseline or an approval only through the baseline
  policy that enables the module's check (`baseline_checks`), and anywhere it does not, it says so with the reason rather
  than reading as enforced.
- A record is `incomplete` when any applying rule is unmet, else `inherited` when any is met only through carried-over
  links, else `complete`; with no applying rule it is `not_applicable`. The highest level among the rules that are not met
  lets a view highlight a warning or required rule apart from an informational one.
- A rule that cannot be evaluated is reported by name and counts neither way.
- The statements grow with the rules and their leaves, never with the records (`rule_evaluation`).

Dependencies: `rules`, `rule_evaluation`, `services.baseline` (which checks run), `services.approval_separation` (which
types have an approval), `services.record_summaries`.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules import registry
from app.modules.traceability import rule_evaluation, rules
from app.modules.traceability._shared import BASELINE_POLICIES, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import (
    EnforcementPoint,
    NotEnforcedReason,
    RecordTraceabilityStatus,
    RuleLevel,
    TraceabilityState,
)
from app.services import approval_separation, record_summaries
from app.services import baseline as core_baseline

RULES_CHECK_KEY = "traceability_rules"
#: The check's key as a baseline policy stores it.
RULES_CHECK = f"{TRACEABILITY_MODULE_KEY}:{RULES_CHECK_KEY}"

_LEVEL_ORDER = (RuleLevel.INFORMATIONAL, RuleLevel.WARNING, RuleLevel.REQUIRED)


@dataclass(frozen=True)
class Enforcement:
    """Where an unmet Required rule refuses something in a project.

    Attributes:
        points: The baselines and approvals that run the traceability check and can hold the rule's record type.
        reason: Why it refuses nothing, `None` when `points` is not empty.
    """

    points: tuple[EnforcementPoint, ...] = ()
    reason: NotEnforcedReason | None = None


@dataclass(frozen=True)
class RuleStatus:
    """One rule that applies to a record.

    Attributes:
        entry: The rule in effect, with its source.
        state: Whether the record meets it.
        leaves: One result per requirement of the rule, in tree order.
    """

    entry: rules.EffectiveRule
    state: TraceabilityState
    leaves: tuple[rule_evaluation.LeafResult, ...]

    @property
    def level(self) -> RuleLevel:
        """The rule's enforcement level."""
        return RuleLevel(self.entry.rule.level)


@dataclass(frozen=True)
class RecordStatus:
    """One record's standing against every rule that applies to it.

    Attributes:
        record_id: The record.
        rules: The rules that apply, in the order the project holds them.
    """

    record_id: uuid.UUID
    rules: tuple[RuleStatus, ...] = ()

    @property
    def status(self) -> RecordTraceabilityStatus:
        """The record's overall standing."""
        if not self.rules:
            return RecordTraceabilityStatus.NOT_APPLICABLE
        states = {r.state for r in self.rules}
        if TraceabilityState.UNMET in states:
            return RecordTraceabilityStatus.INCOMPLETE
        if TraceabilityState.INHERITED in states:
            return RecordTraceabilityStatus.INHERITED
        return RecordTraceabilityStatus.COMPLETE

    @property
    def highest_level(self) -> RuleLevel | None:
        """The highest level among the rules the record does not meet, `None` when it meets every one."""
        levels = [r.level for r in self.rules if r.state != TraceabilityState.MET]
        return max(levels, key=_LEVEL_ORDER.index) if levels else None


@dataclass(frozen=True)
class TypeStatus:
    """The statuses of the records of one type.

    Attributes:
        records: `{record id: status}` for each live record asked about that the project holds.
        unevaluated: The names of rules for the type that could not be evaluated.
    """

    records: dict[uuid.UUID, RecordStatus]
    unevaluated: tuple[str, ...] = ()


def record_statuses(
    db: Session, project: Project, artefact_type: str, record_ids: Collection[uuid.UUID] | None = None, *,
    levels: Collection[RuleLevel] | None = None,
) -> TypeStatus:
    """The traceability status of a project's records of one type.

    Args:
        db: Active session (read only).
        project: The project.
        artefact_type: The record type.
        record_ids: The records to report, `None` for every live record of the type. An id the project does not hold, or
            an archived record, is absent from the result.
        levels: Evaluate only rules of these levels; `None` for all.

    Returns:
        A status per record, and the names of the type's rules that could not be evaluated.

    The caller applies the type's `view` permission before showing the result.
    """
    summaries = (
        record_summaries.list_summaries(db, project.id, artefact_type) if record_ids is None
        else list(record_summaries.read_summaries(db, project.id, artefact_type, sorted(record_ids)).values())
    )
    ids = sorted(s.id for s in summaries if not s.is_archived)
    found: dict[uuid.UUID, list[RuleStatus]] = {i: [] for i in ids}
    unevaluated: list[str] = []
    if ids:
        for entry in rules.effective_rules(db, project):
            rule = entry.rule
            if not entry.active or rule.source_type != artefact_type:
                continue
            if levels is not None and RuleLevel(rule.level) not in levels:
                continue
            result = rules.evaluate(db, project, rule, record_ids=ids)
            if result.problems:
                unevaluated.append(rule.name)
                continue
            for record in result.in_scope:
                found[record.record_id].append(RuleStatus(entry, record.state, record.leaves))
    return TypeStatus({i: RecordStatus(i, tuple(v)) for i, v in found.items()}, tuple(unevaluated))


@dataclass(frozen=True)
class EnforcementContext:
    """What decides enforcement for every rule of one project, read once.

    Attributes:
        baseline_policies_on: The baseline policies part is in effect.
        running: The baselines and approvals whose enabled checks include the traceability check.
        baseline_types: The record types a baseline of the project holds.
        approval_types: The record types with an approval.
    """

    baseline_policies_on: bool
    running: frozenset[EnforcementPoint]
    baseline_types: frozenset[str]
    approval_types: frozenset[str]

    def for_rule(self, entry: rules.EffectiveRule) -> Enforcement | None:
        """Where the rule is enforced; `None` for a rule below the Required level, which refuses nothing anywhere."""
        if RuleLevel(entry.rule.level) != RuleLevel.REQUIRED:
            return None
        if not entry.active:
            return Enforcement(reason=NotEnforcedReason.RULE_NOT_ACTIVE)
        if not self.baseline_policies_on:
            return Enforcement(reason=NotEnforcedReason.BASELINE_POLICIES_OFF)
        if not self.running:
            return Enforcement(reason=NotEnforcedReason.CHECK_NOT_ENABLED)
        source = entry.rule.source_type
        points = tuple(
            point for point in EnforcementPoint
            if point in self.running
            and source in (self.approval_types if point == EnforcementPoint.MANUAL_APPROVAL else self.baseline_types)
        )
        return Enforcement(points) if points else Enforcement(reason=NotEnforcedReason.TYPE_NOT_COVERED)


def enforcement_for(db: Session, project: Project) -> EnforcementContext:
    """Reads what decides where the project's Required rules are enforced.

    Args:
        db: Active session (read only).
        project: The project.
    """
    runs: tuple[tuple[EnforcementPoint, core_baseline.BaselineKindName, bool], ...] = (
        (EnforcementPoint.STAGE_BASELINE, "stage", False),
        (EnforcementPoint.MANUAL_BASELINE, "manual", False),
        (EnforcementPoint.MANUAL_APPROVAL, "approval", False),
        (EnforcementPoint.AUTOMATED_APPROVAL, "stage", True),
    )
    running = frozenset(
        point for point, kind, automated in runs
        if any(key == RULES_CHECK for key, _ in core_baseline.active_checks(db, project, kind, automated=automated))
    )
    return EnforcementContext(
        baseline_policies_on=registry.is_module_subcomponent_enabled(db, project.id, TRACEABILITY_MODULE_KEY, BASELINE_POLICIES),
        running=running,
        baseline_types=frozenset({core_baseline.REQUIREMENT_ITEM_TYPE, *core_baseline.enabled_snapshot_providers(db, project)}),
        approval_types=frozenset(approval_separation.approval_gates()),
    )
