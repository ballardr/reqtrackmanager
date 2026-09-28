"""
Module: modules.context_strategy.enums

Context & Strategy-owned vocabulary (docs/plans/module-01-context-and-
strategy-plan.md Phase 1). Kept in this package rather than
`app.models.enums`, mirroring `app.modules.decisions.enums`'s own
reasoning — these are domain concepts this module owns, not core
ReqTrackManager concepts.
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
