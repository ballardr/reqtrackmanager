"""
Module: modules.context_strategy.enums

Context & Strategy-owned vocabulary. Kept in this package rather than
`app.models.enums`, mirroring `app.modules.decisions.enums`'s own
reasoning — these are domain concepts this module owns, not core
ReqTrackManager concepts.

Future State has its own `FutureStateScope`/`FutureStateStatus` rather than
reusing `StrategyScope`/`StrategyStatus`, **Decided by: Agent**, by direct
analogy to how this module already keeps `DecisionStatus` and
`StrategyStatus` separate despite both being lifecycle enums with an
identical shape (see `StrategyStatus`'s own docstring, which cites the
decision that Future State's lifecycle "mirrors Strategy's in full"). Two
independent artefact types owning two textually-identical vocabularies
avoids one artefact's future divergence (e.g. Strategy someday gaining a
scope Future State never needs) silently reaching into the other's column
values.

Pain Point has `PainPointStatus` (a genuinely different, **branching**
lifecycle shape — not a mirror of `StrategyStatus`'s linear chain) and
`PainPointPriority`, kept as its own enum rather than a reuse of
`StrategyPriority` (**Decided by: Agent**, by the same "two independent
artefact types, two owned vocabularies" reasoning — a future divergence in
either artefact's own priority vocabulary should not require touching the
other's).

Guiding Principle has `GuidingPrincipleScope` (same org/project discriminator
shape as `StrategyScope`/`FutureStateScope`, its own enum for the same
reason), `GuidingPrinciplePriority` (its own three-value enum, same reasoning
as `PainPointPriority`), and `GuidingPrincipleStatus` — a **shorter**
lifecycle than Strategy/Future State's seven-member one ("propose ->
approve/activate -> retire, no 'Under Review'/'Superseded' split called out
explicitly in §8"). See `GuidingPrincipleStatus`'s own docstring for the full
reconciliation of that source text against the enum's actual six members
(**Decided by: Agent**).

Open Question has `OpenQuestionPriority` (its own three-value enum, same
reasoning as `PainPointPriority`/`GuidingPrinciplePriority`) and
`OpenQuestionStatus` — a **branching** lifecycle (§9.3:
`Open -> Investigating -> Ready for Decision -> Resolved/Withdrawn`), built
from the same `_PP_ALLOWED_TRANSITIONS`-style dict-of-frozensets mechanism
Pain Point uses, not Strategy/Future State/Guiding Principle's
linear-chain-plus-terminal-branch shape. Unlike Pain Point, Open Question has
**no `type` field and no version-history table** (Decided by: Agent — see
`models.OpenQuestion`'s own docstring) and is **project-scoped only**
(Decided by: Agent — see that same docstring for the scope reasoning,
grounded in Decision's own project-only scope since an Open Question
ultimately resolves into a Decision per §9.5). See
`OpenQuestionStatus`'s own docstring for the full lifecycle reasoning.
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
    """Lifecycle states for a `Strategy`: `Draft
    -> Proposed -> Under Review -> Approved -> Active -> Superseded/
    Retired`.

    **Reconciling "six-state lifecycle" with seven enum members below**
    (Decided by: Agent, flagged for awareness — not a genuine fork, just an
    ambiguity in the requirement's phrasing worth recording): the
    arrow chain has six *positions*, the last of which
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
    — the requirement lists only the six positions above,
    with no rejection-branch state named. A Strategy sent back for rework
    from `PROPOSED`/`UNDER_REVIEW` instead returns to `DRAFT` (see
    `service._ALLOWED_TRANSITIONS`) rather than landing in a new terminal
    state nobody asked for.

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
    """A Pain Point's relative priority/significance (§6.3
    "Priority / significance") — its own enum, not a reuse of
    `StrategyPriority` (see this module's own docstring for why). Same
    three-value shape as `StrategyPriority` since nothing in either
    artefact's own scope asks for a different granularity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PainPointStatus(str, enum.Enum):
    """Lifecycle states for a `PainPoint` (§6.4) —
    deliberately a **branching**, not linear, lifecycle: `Submitted ->
    Triaged -> {Rejected | Duplicate | Accepted -> Addressed -> Closed}`.
    `TRIAGED` has three legal next states, not one (`service.
    _PP_ALLOWED_TRANSITIONS`) — the only lifecycle in this module (so far)
    where a single status column's legal-next-set has more than two
    members, unlike `StrategyStatus`/`FutureStateStatus`'s linear-chain-
    plus-terminal-branch shape (each state there has at most two legal
    next states).

    No version-history table backs this status ("No version-history table is
    required for Pain Point") — a
    `PainPoint` row is mutated in place, with every transition recorded via
    `services.audit.log_event` (a plain audit trail), not a `PainPointVersion`
    snapshot table. **Decided by: Agent** — the requirement
    says no version-history table is required but doesn't explicitly
    rule one in either; a full temporal version table exists in this module
    only where one was explicitly asked for (Strategy, Future State,
    and Guiding Principle), and Pain Point was
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
    """Lifecycle states for a `FutureState` — mirrors `StrategyStatus` in
    full ("Future State's lifecycle and
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
    """Lifecycle states for a `GuidingPrinciple` (§8) —
    **shorter** than `StrategyStatus`/`FutureStateStatus`'s seven-member
    chain, per the scope text: "propose -> approve/activate ->
    retire, no 'Under Review'/'Superseded' split called out explicitly in
    §8."

    **Reconciling that scope text with six actual enum members below**
    (Decided by: Agent, the same kind of phrasing-vs-implementation
    reconciliation `StrategyStatus`'s own docstring already made explicit
    for its "six-state lifecycle" text):

    - No `UNDER_REVIEW`. §8's own text names only "propose -> approve" —
      it never describes a Strategy/Future-State-style formal review step
      distinct from the act of approving, so this lifecycle has no
      standalone review state to mirror. A Guiding Principle moves directly
      `PROPOSED -> APPROVED` (`service._GP_ALLOWED_TRANSITIONS`).
    - `SUPERSEDED` **is** kept, despite the scope text's own "no ...
      'Superseded' split called out explicitly" phrasing — re-examined
      against §8.4's own reasoning ("revision control here
      protects historical Decision rationale"): a Decision that cites a
      Guiding Principle as its rationale needs that Principle's history to
      remain resolvable even after a newer Principle replaces it in
      practice, the same "a principle can be superseded by a newer one and
      still needs its own terminal state, not silently overwritten" logic
      `StrategyStatus`'s own docstring uses for Strategy. Dropping
      `SUPERSEDED` here would leave "this Principle was replaced by a
      newer one" inexpressible except by retiring it outright — a different
      and less precise historical claim. This is the one point in this
      enum's design where a weighed judgment call was
      explicitly asked for rather than the literal scope-text reading;
      the weighed reading (keep `SUPERSEDED`) mirrors Strategy's *reasoning*
      per the brief's own instruction, without mirroring Strategy's literal
      seven-member conclusion.
    - `PROPOSED` can still send a Guiding Principle back to `DRAFT`
      (`service.send_guiding_principle_back_to_draft`) — this module's
      established "reject"-equivalent (see `StrategyStatus`'s own docstring)
      — even though the scope text's arrow chain doesn't spell out a
      rework path either; every other lifecycle in this module has one, and
      nothing in §8 suggests a Guiding Principle is uniquely exempt from
      needing rework before approval.

    Transition enforcement (`service._GP_ALLOWED_TRANSITIONS`) is this
    enum's sibling, not this docstring's — declared here for completeness
    of the "what values exist" question only.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class OpenQuestionPriority(str, enum.Enum):
    """An Open Question's relative priority (§9.2) — its own
    enum, not a reuse of `StrategyPriority`/`PainPointPriority`/
    `GuidingPrinciplePriority` (see this module's own docstring for why).
    Same three-value shape as its siblings since nothing in this artefact's
    own scope asks for a different granularity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OpenQuestionStatus(str, enum.Enum):
    """Lifecycle states for an `OpenQuestion` (§9.3) —
    deliberately a **branching**, not linear, lifecycle, the same mechanism
    shape `PainPointStatus` already established in this module,
    not Strategy/Future State/Guiding Principle's linear-chain-plus-
    terminal-branch shape.

    Source overview §9.3's own arrow chain reads as a single, unbranched
    line: `Open -> Investigating -> Ready for Decision -> Resolved /
    Withdrawn`. As with `StrategyStatus`'s "six-state lifecycle" text (see
    that enum's own docstring), the final slot reads as one position that
    resolves to either of two distinct terminal values — `RESOLVED` and
    `WITHDRAWN` are two real, separate enum members, not one combined value
    (five members total, not four).

    **Where this lifecycle genuinely branches mid-chain, not just at the
    end (Decided by: Agent, the specific judgment call flagged)**: `WITHDRAWN` is reachable directly from `INVESTIGATING`
    as well as from `READY_FOR_DECISION` — an Open Question can turn out to
    be moot, already answered elsewhere, or no longer relevant while still
    under active investigation, not only once it has reached the "ready for
    a decision" point. `OPEN` itself does **not** branch directly to
    `WITHDRAWN` — it only advances to `INVESTIGATING` — mirroring
    `PainPointStatus`'s own precedent that only a lifecycle's *middle*
    state(s) branch, not its very first one (`SUBMITTED` -> `TRIAGED` only,
    never straight to a terminal state).

    **No rework/"send back" transition** (unlike Strategy/Future State/
    Guiding Principle's `PROPOSED`/`UNDER_REVIEW` -> `DRAFT` path) — this
    lifecycle is investigatory, not a formal review-and-approval gate; there
    is no "content under review that might be rejected back to draft"
    concept here, the same reasoning `PainPointStatus` already applies (Pain
    Point has no rework path either).

    Transition enforcement (`service._OQ_ALLOWED_TRANSITIONS`) is this
    enum's sibling, not this docstring's — declared here for completeness
    of the "what values exist" question only.
    """

    OPEN = "open"
    INVESTIGATING = "investigating"
    READY_FOR_DECISION = "ready_for_decision"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"
