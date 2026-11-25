"""
Module: modules.context_strategy.enums

Context & Strategy-owned vocabulary, kept here rather than in `app.models.enums` (as `app.modules.decisions.enums`).

Design decisions (**Decided by: Agent**): each artefact type owns its vocabularies even where another's has the same
shape (`FutureStateScope` and `FutureStateStatus` beside `StrategyScope` and `StrategyStatus`, as `DecisionStatus` is
separate), so a later divergence in one never reaches the other's column values.
- Pain Point: `PainPointStatus` (a branching lifecycle, not Strategy's linear chain) and `PainPointPriority`.
- Guiding Principle: `GuidingPrincipleScope`, `GuidingPrinciplePriority` and `GuidingPrincipleStatus`, a shorter lifecycle
  than Strategy's seven members (§8: propose, approve and activate, retire; see `GuidingPrincipleStatus`).
- Open Question: `OpenQuestionPriority` and `OpenQuestionStatus`, a branching lifecycle (§9.3: `Open -> Investigating ->
  Ready for Decision -> Resolved/Withdrawn`) built like Pain Point's dict-of-frozensets transitions. It has no `type`
  field or version history and is project-scoped only because it resolves into a Decision (§9.5); see
  `models.OpenQuestion` and `OpenQuestionStatus`.
"""

from __future__ import annotations

import enum


class StrategyScope(str, enum.Enum):
    """Which level a `Strategy` row belongs to — exactly one of
    `Strategy.organization_id`/`project_id` is set, matching this value.
    A single table with this discriminator, rather than two separate
    tables, so a future Portfolio/Programme scope (overview §5.2's own
    explicit ask) can be added without a fundamental redesign.
    """

    ORGANIZATION = "organization"
    PROJECT = "project"


class StrategyPriority(str, enum.Enum):
    """A Strategy's relative priority — a small, fixed vocabulary (unlike
    Pain Point's project-configurable `type`), since nothing in
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
    """Lifecycle states for a `Strategy`: `Draft -> Proposed -> Under Review -> Approved -> Active -> Superseded/Retired`.

    The last position resolves to two terminal values, so `SUPERSEDED` and `RETIRED` are separate members (seven in
    total, **Decided by: Agent**), as `DecisionStatus` has a linear chain plus separate terminal branches (with `ACTIVE`
    inserted, which a Decision does not need). There is no `REJECTED`: a Strategy sent back from `PROPOSED` or
    `UNDER_REVIEW` returns to `DRAFT` (`service._ALLOWED_TRANSITIONS`). Transition enforcement is in
    `service._ALLOWED_TRANSITIONS`.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class PainPointPriority(str, enum.Enum):
    """A Pain Point's relative priority/significance (§6.3
    "Priority / significance") — its own enum, not a reuse of
    `StrategyPriority` (see this module's own docstring for why). Same
    three-value shape as `StrategyPriority` since nothing in either
    artefact's own scope asks for a different granularity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PainPointSubmissionPolicy(str, enum.Enum):
    """Who may submit a Pain Point in a project: only a Pain Point Manager (the platform default) or any project
    member (§6.5's broad-creation model, which a project or organisation opts in to). Ordinary requests are raised
    as Enhancement Requests where Product Feedback is enabled. Editing and triage stay manager-tier whichever is
    chosen."""

    MEMBERS = "members"
    MANAGERS = "managers"


class PainPointStatus(str, enum.Enum):
    """Lifecycle states for a `PainPoint` (§6.4): a branching lifecycle, `Submitted -> Triaged -> {Rejected | Duplicate |
    Accepted -> Addressed -> Closed}`. `TRIAGED` has three legal next states (`service._PP_ALLOWED_TRANSITIONS`), unlike
    the linear chain plus terminal branch of `StrategyStatus` and `FutureStateStatus`.

    No version-history table backs it: a `PainPoint` row is mutated in place and every transition is recorded with
    `services.audit.log_event` (**Decided by: Agent**); a full version table exists only for Strategy, Future State and
    Guiding Principle.
    """

    SUBMITTED = "submitted"
    TRIAGED = "triaged"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    ACCEPTED = "accepted"
    ADDRESSED = "addressed"
    CLOSED = "closed"


class FutureStateScope(str, enum.Enum):
    """Which level a `FutureState` row belongs to (Decided by: Agent) — exactly one of `FutureState.organization_id`/
    `project_id` is set, matching this value. Identical shape and
    reasoning to `StrategyScope` (single table with a discriminator, so a
    future Portfolio/Programme scope can be added without a redesign), but
    its own enum rather than a reuse of `StrategyScope` — see this
    module's own docstring above for why.
    """

    ORGANIZATION = "organization"
    PROJECT = "project"


class FutureStateStatus(str, enum.Enum):
    """Lifecycle states for a `FutureState`, mirroring `StrategyStatus` (`Draft -> Proposed -> Under Review -> Approved ->
    Active -> Superseded/Retired`, seven members, no `REJECTED`: rework returns to `DRAFT`,
    `service._FS_ALLOWED_TRANSITIONS`). It is its own enum so the two vocabularies can diverge independently
    (**Decided by: Agent**; see the module docstring).
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class GuidingPrincipleScope(str, enum.Enum):
    """Which level a `GuidingPrinciple` row belongs to — same org/project
    discriminator shape as `StrategyScope`/`FutureStateScope`, its own enum
    for the same "two independent artefact types, two owned vocabularies"
    reasoning (see this module's own docstring above)."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class GuidingPrinciplePriority(str, enum.Enum):
    """A Guiding Principle's relative priority — its own enum, not a reuse
    of `StrategyPriority`/`PainPointPriority` (see this module's own
    docstring for why). Same three-value shape as its siblings since
    nothing in this artefact's own scope (§8.3) asks for a
    different granularity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GuidingPrincipleStatus(str, enum.Enum):
    """Lifecycle states for a `GuidingPrinciple` (§8), shorter than the seven-member `StrategyStatus` chain (**Decided by:
    Agent**):
    - No `UNDER_REVIEW`: §8 names only "propose -> approve", so a Guiding Principle moves `PROPOSED -> APPROVED`
      (`service._GP_ALLOWED_TRANSITIONS`).
    - `SUPERSEDED` is kept: a Decision that cites a Principle as rationale needs that Principle's history to stay
      resolvable (§8.4), and "replaced by a newer one" is a more precise historical claim than `RETIRED`.
    - `PROPOSED` can send a Principle back to `DRAFT` (`service.send_guiding_principle_back_to_draft`), as every other
      lifecycle in this module allows rework before approval.

    Transition enforcement is in `service._GP_ALLOWED_TRANSITIONS`.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class OpenQuestionPriority(str, enum.Enum):
    """An Open Question's relative priority (§9.2): its own enum (see the module docstring) with the three-value shape of
    its siblings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OpenQuestionStatus(str, enum.Enum):
    """Lifecycle states for an `OpenQuestion` (§9.3): a branching lifecycle, as `PainPointStatus`, not the linear chain of
    Strategy, Future State and Guiding Principle.

    §9.3 reads `Open -> Investigating -> Ready for Decision -> Resolved / Withdrawn`; the final position is two
    separate members, `RESOLVED` and `WITHDRAWN` (five in total). `WITHDRAWN` is reachable from `INVESTIGATING` as well
    as `READY_FOR_DECISION`, because a question can become moot or answered elsewhere while under investigation
    (**Decided by: Agent**). `OPEN` advances only to `INVESTIGATING`, as `SUBMITTED` goes only to `TRIAGED`. There is no
    rework transition: the lifecycle is investigatory, not a review-and-approval gate. Transition enforcement is in
    `service._OQ_ALLOWED_TRANSITIONS`.
    """

    OPEN = "open"
    INVESTIGATING = "investigating"
    READY_FOR_DECISION = "ready_for_decision"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"
