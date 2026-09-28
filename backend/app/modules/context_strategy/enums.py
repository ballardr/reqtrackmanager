"""
Module: modules.context_strategy.enums

Context & Strategy-owned vocabulary (docs/plans/module-01-context-and-
strategy-plan.md Phases 1–2). Kept in this package rather than
`app.models.enums`, mirroring `app.modules.decisions.enums`'s own
reasoning — these are domain concepts this module owns, not core
ReqTrackManager concepts.

Phase 2 (Future State) adds `FutureStateScope`/`FutureStateStatus` as
their own enums rather than reusing `StrategyScope`/`StrategyStatus`,
**Decided by: Agent**, by direct analogy to how this module already keeps
`DecisionStatus` and `StrategyStatus` separate despite both being
lifecycle enums with an identical shape (see `StrategyStatus`'s own
docstring, which the plan's Phase 0 Q1 follow-on explicitly cites when
requiring Future State's lifecycle to "mirror Strategy's in full"). Two
independent artefact types owning two textually-identical vocabularies
avoids one artefact's future divergence (e.g. Strategy someday gaining a
scope Future State never needs) silently reaching into the other's
column values.

Phase 3 (Pain Points) adds `PainPointStatus` (a genuinely different,
**branching** lifecycle shape — not a mirror of `StrategyStatus`'s linear
chain, so there was no "reuse or not" question to answer the way Phase 2
had for Future State) and `PainPointPriority`, kept as its own enum rather
than a reuse of `StrategyPriority` (**Decided by: Agent**, by the same
"two independent artefact types, two owned vocabularies" reasoning already
applied to `FutureStateScope`/`FutureStateStatus` above — a future
divergence in either artefact's own priority vocabulary should not require
touching the other's).
"""

from __future__ import annotations

import enum


class StrategyScope(str, enum.Enum):
    """Which level a `Strategy` row belongs to (Phase 0 Q2) — exactly one of
    `Strategy.organization_id`/`project_id` is set, matching this value.
    A single table with this discriminator, rather than two separate
    tables, so a future Portfolio/Programme scope (overview §5.2's own
    explicit ask) can be added without a fundamental redesign.
    """

    ORGANIZATION = "organization"
    PROJECT = "project"


class StrategyPriority(str, enum.Enum):
    """A Strategy's relative priority — a small, fixed vocabulary (unlike
    Pain Point's project-configurable `type`, Phase 0 Q3), since nothing in
    this module's scope asks for priority itself to vary per
    organisation/project. No precedent for a "priority" field exists
    elsewhere in this codebase yet (checked before adding this enum), so
    this is Context & Strategy's own first use of the concept, kept
    module-local rather than promoted to `app.models.enums` on day one —
    a later module needing the identical concept can either reuse this
    or, if genuinely core, be the point at which promoting it is
    reconsidered. **Decided by: Agent.**
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StrategyTimeHorizon(str, enum.Enum):
    """How far out a Strategy's desired future state is targeted — a small,
    fixed vocabulary rather than a free-text field, for the same
    consistency-of-display reasoning `StrategyPriority` uses.
    **Decided by: Agent.**
    """

    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class StrategyStatus(str, enum.Enum):
    """Lifecycle states for a `Strategy` (Phase 0 Q1's follow-on/Q4): `Draft
    -> Proposed -> Under Review -> Approved -> Active -> Superseded/
    Retired` (module-01 plan's Phase 1 scope text and its own "six-state
    lifecycle" description).

    **Reconciling "six-state lifecycle" with seven enum members below**
    (Decided by: Agent, flagged for awareness — not a genuine fork the plan
    left open, just an ambiguity in its own phrasing worth recording): the
    plan's arrow chain has six *positions*, the last of which
    ("Superseded/Retired") reads as one slot that resolves to either of two
    distinct terminal values — a `status` column can only ever hold one
    concrete value at a time, so `SUPERSEDED` and `RETIRED` must be two
    real, separate enum members, not one combined value. This mirrors
    `DecisionStatus`'s own shape exactly (a linear chain of "in-flight"
    states plus separate terminal branches, `REJECTED` there / `SUPERSEDED`
    and `RETIRED` here), just with `ACTIVE` inserted between `APPROVED` and
    the terminal branches, which Decision has no equivalent of (a Decision
    has no separate "in force" state beyond being approved).

    `REJECTED` intentionally does not exist here (unlike `DecisionStatus`)
    — this module's Phase 1 scope text lists only the six positions above,
    with no rejection-branch state named. A Strategy sent back for rework
    from `PROPOSED`/`UNDER_REVIEW` instead returns to `DRAFT` (see
    `service._ALLOWED_TRANSITIONS`) rather than landing in a new terminal
    state the plan never asked for.

    Transition enforcement (`service._ALLOWED_TRANSITIONS`) is this
    enum's sibling, not this docstring's — declared here for completeness
    of the "what values exist" question only.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class PainPointPriority(str, enum.Enum):
    """A Pain Point's relative priority/significance (source overview §6.3
    "Priority / significance") — its own enum, not a reuse of
    `StrategyPriority` (see this module's own docstring for why). Same
    three-value shape as `StrategyPriority` since nothing in either
    artefact's own scope asks for a different granularity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PainPointStatus(str, enum.Enum):
    """Lifecycle states for a `PainPoint` (source overview §6.4) —
    deliberately a **branching**, not linear, lifecycle: `Submitted ->
    Triaged -> {Rejected | Duplicate | Accepted -> Addressed -> Closed}`.
    `TRIAGED` has three legal next states, not one (`service.
    _PP_ALLOWED_TRANSITIONS`) — the only lifecycle in this module (so far)
    where a single status column's legal-next-set has more than two
    members, unlike `StrategyStatus`/`FutureStateStatus`'s linear-chain-
    plus-terminal-branch shape (each state there has at most two legal
    next states).

    No version-history table backs this status (Phase 3's own scope, per
    `docs/plans/module-01-context-and-strategy-plan.md`'s Phase 0 sign-off
    text: "No version-history table is required for Pain Point") — a
    `PainPoint` row is mutated in place, with every transition recorded via
    `services.audit.log_event` (a plain audit trail), not a `PainPointVersion`
    snapshot table. **Decided by: Agent** — the plan's own Phase 3 scope
    text says no version-history table is required but doesn't explicitly
    rule one in either; a full temporal version table exists in this module
    only where Phase 0 Q4 explicitly asked for one (Strategy, Future State,
    and — per that same resolution — Guiding Principle), and Pain Point was
    not named there, so this follows the absence of that instruction rather
    than adding an unrequested version table by analogy to its siblings.
    """

    SUBMITTED = "submitted"
    TRIAGED = "triaged"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    ACCEPTED = "accepted"
    ADDRESSED = "addressed"
    CLOSED = "closed"


class FutureStateScope(str, enum.Enum):
    """Which level a `FutureState` row belongs to (Phase 0 Q1's follow-on,
    Decided by: Agent) — exactly one of `FutureState.organization_id`/
    `project_id` is set, matching this value. Identical shape and
    reasoning to `StrategyScope` (single table with a discriminator, so a
    future Portfolio/Programme scope can be added without a redesign), but
    its own enum rather than a reuse of `StrategyScope` — see this
    module's own docstring above for why.
    """

    ORGANIZATION = "organization"
    PROJECT = "project"


class FutureStateStatus(str, enum.Enum):
    """Lifecycle states for a `FutureState` — mirrors `StrategyStatus` in
    full, per Phase 0 Q1's follow-on ("Future State's lifecycle and
    permissions mirror Strategy's in full"): `Draft -> Proposed -> Under
    Review -> Approved -> Active -> Superseded/Retired`, seven enum members
    for the same reason `StrategyStatus` has seven (`SUPERSEDED` and
    `RETIRED` are two distinct terminal values, not one combined slot), and
    no `REJECTED` state — a Future State sent back for rework from
    `PROPOSED`/`UNDER_REVIEW` returns to `DRAFT` instead (see
    `service._FS_ALLOWED_TRANSITIONS`). See `StrategyStatus`'s own
    docstring for the full reasoning this repeats; kept as its own enum
    rather than a reuse of `StrategyStatus`, by direct analogy to
    `DecisionStatus`/`StrategyStatus` already being separate despite
    identical shape (Decided by: Agent — see this module's own docstring
    above).
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
