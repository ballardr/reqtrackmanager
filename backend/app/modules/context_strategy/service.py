"""
Module: modules.context_strategy.service

Context & Strategy's Phase 1 business logic (docs/plans/module-01-context-
and-strategy-plan.md Phase 1 — Organisation & Project Strategy):

- `create_strategy` — creates a `Strategy` identity row plus its initial
  (version 1) content snapshot, mirroring `services.requirements.
  create_requirement`'s shape exactly.
- `apply_new_version` — closes the current `StrategyVersion` and inserts a
  new one, carrying forward any field left unspecified — the exact
  `services.requirements.apply_new_version` pattern, applied here because
  Phase 0 Q4 requires Strategy to have the same full temporal
  version-history model Requirement has, not Decision Management's lighter
  identity-row-status-plus-audit-log approach.
- `propose_strategy` / `submit_strategy_for_review` / `send_strategy_back_
  to_draft` / `approve_strategy` / `activate_strategy` / `supersede_
  strategy` / `retire_strategy` — the `StrategyStatus` transitions
  (`enums._ALLOWED_TRANSITIONS` below), each applied via `apply_new_
  version` (a transition is a content change like any other, per the model
  docstring) and recorded via `services.audit.log_event`.
- `resolve_strategy_file_project_id` — this module's `ModuleDefinition.
  resolve_file_owner_project_id` hook, for a **project-scoped** Strategy's
  direct/comment file attachments only. An **org-scoped** Strategy's files
  are uploaded as organisation shared resources instead
  (`FileAsset.is_org_resource=True`), authorized by org membership alone
  through `routers.files.download_file`'s existing `is_org_resource`
  branch — this hook only ever needs to resolve the project-owned case,
  mirroring `modules.decisions.service.resolve_decision_file_project_id`'s
  shape for the half of this module's files that *do* need it.

No relationship/MCP-tool logic lives here — cross-artefact relationship
wiring (Pain Point -> drives -> Strategy, Strategy -> defines -> Future
State, etc.) and MCP tools are both Phase 6's job, explicitly out of scope
for this phase (see the plan's own Phase 6 section).

Phase 2 (Future State) adds the same shape of functions for the
standalone Future State artefact — `create_future_state`,
`apply_future_state_new_version`, `archive_future_state`/
`unarchive_future_state`, the seven `FutureStateStatus` lifecycle
transitions, and `resolve_future_state_file_project_id`. Distinct
function/constant names throughout (not a reuse of the Strategy names
above) since both artefact types now share this one file — see each
function's own docstring for anything that isn't a pure rename of its
Strategy counterpart.

Phase 3 (Pain Points) adds a third, structurally different shape — no
version table (`enums.PainPointStatus`'s own docstring), so `create_
pain_point`/`update_pain_point` mutate one row directly rather than
opening/closing `...Version` snapshots — plus the Phase 0 Q3 two-tier type
vocabulary's own resolution logic (`resolve_effective_pain_point_types`,
`get_or_create_project_pain_point_type`) and org-/project-scoped type CRUD
(`create_org_pain_point_type`/`delete_org_pain_point_type`/`create_
project_local_pain_point_type`/`set_project_pain_point_type_override`/
`delete_project_pain_point_type`). The `_PP_ALLOWED_TRANSITIONS` state
machine expresses `PainPointStatus`'s **branching** shape (`TRIAGED` has
three legal next states), unlike `_ALLOWED_TRANSITIONS`/`_FS_ALLOWED_
TRANSITIONS`'s linear-chain-plus-terminal-branch shape above, but is built
from the same dict-of-frozensets pattern, not a new mechanism.

Phase 4 (Guiding Principles) adds `create_guiding_principle`,
`apply_guiding_principle_new_version`, `archive_guiding_principle`/
`unarchive_guiding_principle`, the six `GuidingPrincipleStatus` lifecycle
transitions (`_GP_ALLOWED_TRANSITIONS` — a linear chain with no
`UNDER_REVIEW` step, see that enum's own docstring), and `resolve_guiding_
principle_file_project_id` — a structural mirror of Phase 1/2's Strategy/
Future State shape (full version-history table, org/project scope), not
Phase 3's version-less Pain Point shape.

Phase 5 (Open Questions) adds `create_open_question`/`update_open_question`
(no version table — back to Phase 3's Pain Point shape, see `models.
OpenQuestion`'s own docstring), `archive_open_question`/`unarchive_open_
question`, and the branching `OpenQuestionStatus` lifecycle transitions
(`investigate_open_question`/`mark_open_question_ready_for_decision`/
`withdraw_open_question`/`resolve_open_question`, `_OQ_ALLOWED_TRANSITIONS`
— built from the same dict-of-frozensets mechanism as `_PP_ALLOWED_
TRANSITIONS`, with two branch points instead of one: both `INVESTIGATING`
and `READY_FOR_DECISION` can reach `WITHDRAWN`), plus `resolve_open_
question_file_project_id`. `resolve_open_question` is deliberately a plain
status transition here, not the actual "Create Decision from Open Question"
workflow (§9.5) or its `ArtefactLink` — that workflow lives in Module 4's
own Phase 7 (Phase 0 Q5), the same "ship the plain transition now, wire the
real relationship later" posture `supersede_strategy`/`supersede_future_
state`/`supersede_guiding_principle` already established for their own
deferred `ArtefactLink` side effects.

Phase 6 (Cross-artefact relationships) adds the actual `ArtefactLink`
wiring Phases 1-5 deferred, using Module 0's generic `services.
relationships` layer directly rather than a bespoke storage mechanism —
mirrors `modules.decisions.service`'s own Phase 3 "relationships" section
structurally (a lazy fetch-or-create `RequirementLinkTypeDefinition` for
each typed relationship name, `services.relationships.create_link`/
`get_link_between` underneath) but is organised around one kind-enum per
*source* artefact type (`StrategyLinkKind`/`PainPointLinkKind`/
`GuidingPrincipleLinkKind`/`FutureStateLinkKind`/`OpenQuestionLinkKind`)
rather than Decision's per-target-type kind enums, since this module has
five source types fanning out to a shared pool of targets (Requirement,
each other, and — reserved, see below — Decision) rather than Decision's
one source type fanning out to two.

- `resolve_link_target_organization_id` / `_resolve_scope_organization_id`
  — resolves any link *target* this module knows how to link to (core
  Requirement, or any of this module's own five artefact types) to its
  owning organisation, so `create_context_strategy_link` can enforce a
  same-organisation boundary before creating the link — the generalised
  form of `modules.decisions.service._project_organization_id`, needed here
  because a source artefact may itself be org- *or* project-scoped (unlike
  Decision, always project-scoped), so "same project" isn't always the
  right boundary; "same organisation" is, and subsumes "same project" (a
  project's own organisation is always the boundary a same-project check
  would have enforced too).
- `create_context_strategy_link` — the single generic dispatcher every
  `create_*_link` wrapper below calls: validates same-organisation,
  fetches-or-creates the named link type (or leaves `link_type_id` `None`
  for an untyped "related to" association — source overview §6.6's own
  instruction that "the relationship type should distinguish causation/
  rationale from generic association" is what the typed/untyped split
  below implements), pre-checks for a duplicate, then calls `services.
  relationships.create_link`.
- One `create_<source>_link(db, *, <source>, kind, target_id, actor_id)`
  wrapper per source artefact type, each resolving `target_id` against
  whichever artefact type `kind` implies (`_STRATEGY_LINK_SPECS`/
  `_PAIN_POINT_LINK_SPECS`/`_GUIDING_PRINCIPLE_LINK_SPECS`/`_FUTURE_STATE_
  LINK_SPECS`/`_OPEN_QUESTION_LINK_SPECS`) and calling the dispatcher.
- `create_strategy_supersession` / `create_future_state_supersession` /
  `create_guiding_principle_supersession` — the deferred `ArtefactLink`
  side effect `supersede_strategy`/`supersede_future_state`/`supersede_
  guiding_principle`'s own docstrings promised: each creates the typed
  `"Supersedes"` link, reusing this module's own plain status-transition
  function underneath (unchanged from Phases 1/2/4, exactly as those
  docstrings said a future Phase 6 pass could layer on top of them without
  changing their contract) rather than duplicating the transition logic.

**Decision-target relationships stay reserved, not built here (Decided by:
Agent — see `docs/decisions.md`'s dated Phase 6 entry for the full
reasoning).** Source overview §5.6/§8.5/§9.5 name three relationship types
whose target is a Decision Management `Decision` (Strategy -> informs ->
Decision, Guiding Principle -> guides -> Decision, Open Question ->
resolved by -> Decision) — this module's own earlier plan text called these
"reserved... only become populatable once Module 4's own Phase 7 lands."
Checked directly against `docs/plans/module-04-decision-management-plan.md`
before starting this phase: Module 4's Phase 7 is **not** complete (its own
Status table still reads "blocked until Module 1 and/or Module 6 exist"),
and that phase's own Goal text explicitly assigns "wire the four Module-1-
reserved relationship types" to Module 4 itself, once Module 1 ships — not
to Module 1. Building the Decision-target wiring here anyway would also hit
the same structural problem Module 4's own Phase 7 exists to solve: this
module cannot import `app.modules.decisions.models.Decision` to validate a
target Decision id (the Modular Feature System Boundary rule — Decision is
module-owned, not core, unlike `Requirement`), and Decision Management
would hit the identical problem in reverse trying to import this module's
own models. Module 4's Phase 7 remains the right place to resolve that
(most likely by adding `create_decision_strategy_link`/`create_decision_
guiding_principle_link`/`create_decision_open_question_link` to `modules.
decisions.service`, mirroring `create_decision_requirement_link` exactly,
now that Strategy/Guiding Principle/Open Question all exist as real,
registered artefact types for it to target) — this phase does not attempt
it. `Decision` (`DECISION_ARTEFACT_TYPE = "decision"`, `modules.decisions.
service`) is nonetheless a real, fully shipped, registered artefact type as
of this phase (Decision Management shipped through its own Phase 9) — so
the *target* itself is no longer hypothetical, only the wiring code is
still pending, on Module 4's side.

**MCP tools and the `require_ai_approvals_enabled` gate** (`module.py`'s
`mcp_tools`, 2026-09-22 write-enabled decision, `docs/decisions.md`):
ordinary CRUD and non-decisive lifecycle transitions (create/update,
propose/submit-for-review/send-back, plain `supersede`/`retire`/`activate`)
are declared as normal write tools, gated only by `MCP_WRITES_ENABLED` +
the calling account's own RBAC role — no special treatment. Five specific
actions additionally require `app.services.rbac.require_ai_approvals_
enabled` when reached through MCP (`get_request_channel(request) ==
"mcp"`), per the plan's own literal list: `approve_strategy`, `approve_
future_state`, `activate_guiding_principle`, `retire_guiding_principle`,
and `resolve_open_question` — project-scoped only (the gate itself needs a
`Project` to check both its own and its organisation's `allow_ai_approvals`
flags, so an org-scoped Strategy/Future State/Guiding Principle's own
approve/activate/retire endpoints are not declared as MCP tools at all,
rather than gated against a project that doesn't exist for them). Note
Guiding Principle's own gated pair is `activate`/`retire`, **not**
`approve` — asymmetric with Strategy/Future State's own gated `approve` —
this is the plan's own literal text (2026-09-22 update), not a rewording:
Guiding Principle's lifecycle has no `UNDER_REVIEW` step (`enums.
GuidingPrincipleStatus`'s own docstring), so `approve` there is closer to a
review-sign-off than the "this Principle governs Decisions now" /
"this Principle no longer applies" decisions `activate`/`retire` actually
make — the plan's own authors evidently drew the "is this a real decision"
line one step later for this artefact than for Strategy/Future State.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateComment,
    FutureStateCommentFile,
    FutureStateFile,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleComment,
    GuidingPrincipleCommentFile,
    GuidingPrincipleFile,
    GuidingPrincipleVersion,
    OpenQuestion,
    OpenQuestionComment,
    OpenQuestionCommentFile,
    OpenQuestionFile,
    PainPoint,
    PainPointComment,
    PainPointCommentFile,
    PainPointFile,
    PainPointTypeDefinition,
    ProjectPainPointType,
    Strategy,
    StrategyComment,
    StrategyCommentFile,
    StrategyFile,
    StrategyVersion,
)
from app.services.audit import log_event
from app.services.relationships import create_link, get_link_between

# This module's own artefact-type string, registered on `ModuleDefinition.
# artefact_types` (module.py) — Phase 6's cross-artefact relationship
# wiring (`ArtefactLink`) is out of scope for this phase, but registering
# the string now means Phase 6 doesn't also need a core-file edit later,
# following Decision Management's own precedent exactly (see module.py).
STRATEGY_ARTEFACT_TYPE = "strategy"


def get_current_version(db: Session, strategy_id: uuid.UUID) -> StrategyVersion:
    """Returns the current (`valid_to IS NULL`) version row for a Strategy.

    Raises:
        ValueError: if no current version exists — a data-integrity bug
            (every `Strategy` row is created with an initial version in
            the same transaction), not a normal runtime condition.
    """
    version = db.scalar(
        select(StrategyVersion).where(StrategyVersion.strategy_id == strategy_id, StrategyVersion.valid_to.is_(None))
    )
    if version is None:
        raise ValueError(f"Strategy {strategy_id} has no current version.")
    return version


def create_strategy(
    db: Session,
    *,
    scope: StrategyScope,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    creator: User,
    title: str,
    objective: str,
    current_state: str = "",
    desired_future_state: str = "",
    rationale: str = "",
    expected_outcomes: str = "",
    constraints: str = "",
    measures_of_success: str = "",
    priority: StrategyPriority = StrategyPriority.MEDIUM,
    time_horizon: StrategyTimeHorizon = StrategyTimeHorizon.MEDIUM_TERM,
) -> Strategy:
    """Creates a Strategy and its initial (version 1) content snapshot, in
    `DRAFT` status. Mirrors `services.requirements.create_requirement`'s
    shape exactly (identity row + version row, one transaction, not
    committed here — caller commits).

    Args:
        organization_id: Always required — even a project-scoped Strategy
            resolves to an owning organisation (`Strategy.organization_id`
            stays `None` for that case; this parameter is only used to
            decide which identity column to populate, not stored directly
            unless `scope` is `ORGANIZATION`).
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
    """
    strategy = Strategy(
        scope=scope,
        organization_id=organization_id if scope == StrategyScope.ORGANIZATION else None,
        project_id=project_id if scope == StrategyScope.PROJECT else None,
        creator_id=creator.id,
    )
    db.add(strategy)
    db.flush()

    now = datetime.now(UTC)
    version = StrategyVersion(
        strategy_id=strategy.id, version_number=1, valid_from=now, valid_to=None,
        title=title, objective=objective, current_state=current_state, desired_future_state=desired_future_state,
        rationale=rationale, expected_outcomes=expected_outcomes, constraints=constraints,
        measures_of_success=measures_of_success, priority=priority, time_horizon=time_horizon,
        status=StrategyStatus.DRAFT, change_note="Initial creation.", created_by=creator.id, created_at=now,
    )
    db.add(version)
    db.flush()
    return strategy


def apply_new_version(
    db: Session,
    strategy: Strategy,
    current_version: StrategyVersion,
    actor: User,
    *,
    title: str | None = None,
    objective: str | None = None,
    current_state: str | None = None,
    desired_future_state: str | None = None,
    rationale: str | None = None,
    expected_outcomes: str | None = None,
    constraints: str | None = None,
    measures_of_success: str | None = None,
    priority: StrategyPriority | None = None,
    time_horizon: StrategyTimeHorizon | None = None,
    status_value: StrategyStatus | None = None,
    change_note: str = "",
) -> StrategyVersion:
    """Closes `current_version` and inserts a new one, carrying forward any
    field left as `None` unchanged — exact mirror of `services.
    requirements.apply_new_version` (see this module's own docstring for
    why a lifecycle-status change also goes through this same function
    rather than a separate identity-row column)."""
    now = datetime.now(UTC)
    current_version.valid_to = now

    new_version = StrategyVersion(
        strategy_id=strategy.id,
        version_number=current_version.version_number + 1,
        valid_from=now,
        valid_to=None,
        title=title if title is not None else current_version.title,
        objective=objective if objective is not None else current_version.objective,
        current_state=current_state if current_state is not None else current_version.current_state,
        desired_future_state=(
            desired_future_state if desired_future_state is not None else current_version.desired_future_state
        ),
        rationale=rationale if rationale is not None else current_version.rationale,
        expected_outcomes=expected_outcomes if expected_outcomes is not None else current_version.expected_outcomes,
        constraints=constraints if constraints is not None else current_version.constraints,
        measures_of_success=(
            measures_of_success if measures_of_success is not None else current_version.measures_of_success
        ),
        priority=priority if priority is not None else current_version.priority,
        time_horizon=time_horizon if time_horizon is not None else current_version.time_horizon,
        status=status_value if status_value is not None else current_version.status,
        change_note=change_note,
        created_by=actor.id,
        created_at=now,
    )
    db.add(new_version)
    db.flush()
    return new_version


def archive_strategy(db: Session, strategy: Strategy, actor: User) -> None:
    """Soft-archives a Strategy, preserving its full version history —
    mirrors `services.requirements.archive_requirement`."""
    strategy.is_archived = True
    strategy.archived_at = datetime.now(UTC)
    strategy.archived_by = actor.id


def unarchive_strategy(db: Session, strategy: Strategy) -> None:
    """Reverses `archive_strategy` — mirrors `services.requirements.
    unarchive_requirement`'s unconditional, idempotent shape."""
    strategy.is_archived = False
    strategy.archived_at = None
    strategy.archived_by = None


# --- Lifecycle transitions --------------------------------------------------

# Legal `StrategyStatus` transitions (`enums.StrategyStatus`'s own
# docstring): forward through the five "in-flight"/active states, with
# `PROPOSED`/`UNDER_REVIEW` both able to send a Strategy back to `DRAFT`
# (this module's "reject"-equivalent, since the plan's own lifecycle text
# names no separate rejected state), and `APPROVED`/`ACTIVE` both able to
# reach `RETIRED` directly (a Strategy approved but never activated can
# still be retired without passing through `ACTIVE` first).
_ALLOWED_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.DRAFT: frozenset({StrategyStatus.PROPOSED}),
    StrategyStatus.PROPOSED: frozenset({StrategyStatus.UNDER_REVIEW, StrategyStatus.DRAFT}),
    StrategyStatus.UNDER_REVIEW: frozenset({StrategyStatus.APPROVED, StrategyStatus.DRAFT}),
    StrategyStatus.APPROVED: frozenset({StrategyStatus.ACTIVE, StrategyStatus.RETIRED}),
    StrategyStatus.ACTIVE: frozenset({StrategyStatus.SUPERSEDED, StrategyStatus.RETIRED}),
    StrategyStatus.SUPERSEDED: frozenset(),
    StrategyStatus.RETIRED: frozenset(),
}

# A Strategy's content fields are locked (no direct edit; only a further
# lifecycle transition may create a new version) once past `UNDER_REVIEW` —
# mirrors Decision Management's "approved decisions should not normally be
# edited in-place" rule, applied one state earlier here since Strategy has
# no single "APPROVED" terminal-ish state the way Decision does (Strategy
# keeps moving through ACTIVE/SUPERSEDED/RETIRED afterwards).
LOCKED_STATUSES = frozenset(
    {StrategyStatus.APPROVED, StrategyStatus.ACTIVE, StrategyStatus.SUPERSEDED, StrategyStatus.RETIRED}
)


def is_locked(version: StrategyVersion) -> bool:
    return version.status in LOCKED_STATUSES


def _transition(
    db: Session, strategy: Strategy, current_version: StrategyVersion, new_status: StrategyStatus, actor: User, *,
    action: str, comment: str | None = None,
) -> StrategyVersion:
    """Validates `new_status` against `_ALLOWED_TRANSITIONS`, applies it via
    `apply_new_version`, and records it via `services.audit.log_event` —
    mirrors `modules.decisions.service._transition_status`'s validate-then-
    apply-then-log shape, adapted to also create a new `StrategyVersion`
    row (Phase 0 Q4's full version-history model) rather than only mutating
    an identity-row column.

    Raises:
        ValueError: if `new_status` isn't reachable from `current_version.
            status` per `_ALLOWED_TRANSITIONS`.
    """
    if new_status not in _ALLOWED_TRANSITIONS[current_version.status]:
        raise ValueError(f"Cannot move a Strategy from '{current_version.status.value}' to '{new_status.value}'.")
    new_version = apply_new_version(
        db, strategy, current_version, actor, status_value=new_status, change_note=comment or "",
    )
    project_id = strategy.project_id
    log_event(
        db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action=action, actor_id=actor.id,
        organization_id=strategy.organization_id, project_id=project_id,
        detail={"comment": comment} if comment else None,
    )
    return new_version


def propose_strategy(db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User) -> StrategyVersion:
    """`DRAFT` -> `PROPOSED`: ready for others to review."""
    return _transition(db, strategy, current_version, StrategyStatus.PROPOSED, actor, action="proposed")


def submit_strategy_for_review(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User
) -> StrategyVersion:
    """`PROPOSED` -> `UNDER_REVIEW`: formal review has started."""
    return _transition(db, strategy, current_version, StrategyStatus.UNDER_REVIEW, actor, action="submitted_for_review")


def send_strategy_back_to_draft(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str
) -> StrategyVersion:
    """`PROPOSED`/`UNDER_REVIEW` -> `DRAFT`: this module's "reject"-
    equivalent (see `enums.StrategyStatus`'s own docstring for why there is
    no separate rejected state). A comment is required — the router
    enforces this before calling in, mirroring every other mandatory-
    comment-on-rejection rule in this codebase."""
    return _transition(db, strategy, current_version, StrategyStatus.DRAFT, actor, action="sent_back", comment=comment)


def approve_strategy(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str | None = None
) -> StrategyVersion:
    """`UNDER_REVIEW` -> `APPROVED`."""
    return _transition(db, strategy, current_version, StrategyStatus.APPROVED, actor, action="approved", comment=comment)


def activate_strategy(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str | None = None
) -> StrategyVersion:
    """`APPROVED` -> `ACTIVE`: the Strategy is now formally in effect."""
    return _transition(db, strategy, current_version, StrategyStatus.ACTIVE, actor, action="activated", comment=comment)


def supersede_strategy(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str | None = None
) -> StrategyVersion:
    """`ACTIVE` -> `SUPERSEDED`. Deliberately a plain status transition,
    unlike Decision Management's `create_supersession` — this phase does
    not create a typed `ArtefactLink` recording *which* Strategy supersedes
    this one; that relationship (and any other Strategy<->Strategy link)
    is Phase 6's job, per this module's plan. A future phase wiring that
    relationship can layer it on top of this same status transition
    without needing to change this function's own contract."""
    return _transition(db, strategy, current_version, StrategyStatus.SUPERSEDED, actor, action="superseded", comment=comment)


def retire_strategy(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str | None = None
) -> StrategyVersion:
    """`APPROVED`/`ACTIVE` -> `RETIRED`."""
    return _transition(db, strategy, current_version, StrategyStatus.RETIRED, actor, action="retired", comment=comment)


# --- File-ownership resolution hook ----------------------------------------


def resolve_strategy_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to a **project-scoped** Strategy directly (`StrategyFile`) or
    via a `StrategyComment` (`StrategyCommentFile`) — this module's own
    `ModuleDefinition.resolve_file_owner_project_id` hook, mirroring
    `modules.decisions.service.resolve_decision_file_project_id`'s exact
    shape. An org-scoped Strategy's files are never resolved here — they
    are uploaded with `FileAsset.is_org_resource=True` instead, authorized
    by `routers.files.download_file`'s own org-membership branch before
    this hook is ever consulted (see module docstring).

    Returns:
        The owning project's id, or `None` if `file_id` isn't attached to
        a project-scoped Strategy or its comment.
    """
    direct_link = db.scalar(select(StrategyFile).where(StrategyFile.file_id == file_id))
    if direct_link is not None:
        strategy = db.get(Strategy, direct_link.strategy_id)
        return strategy.project_id if strategy is not None else None

    comment_link = db.scalar(select(StrategyCommentFile).where(StrategyCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(StrategyComment, comment_link.comment_id)
        if comment is not None:
            strategy = db.get(Strategy, comment.strategy_id)
            return strategy.project_id if strategy is not None else None

    return None


# --- Future State (Phase 2) -------------------------------------------------

# This module's second artefact-type string (Phase 0 Q1: Future State is a
# standalone artefact, not fields on Strategy), registered on
# `ModuleDefinition.artefact_types` (module.py) for the same reason
# `STRATEGY_ARTEFACT_TYPE` is — Phase 6's relationship wiring doesn't also
# need a core-file edit later.
FUTURE_STATE_ARTEFACT_TYPE = "future_state"


def get_current_future_state_version(db: Session, future_state_id: uuid.UUID) -> FutureStateVersion:
    """Returns the current (`valid_to IS NULL`) version row for a Future
    State — exact mirror of `get_current_version`.

    Raises:
        ValueError: if no current version exists (data-integrity bug).
    """
    version = db.scalar(
        select(FutureStateVersion).where(
            FutureStateVersion.future_state_id == future_state_id, FutureStateVersion.valid_to.is_(None)
        )
    )
    if version is None:
        raise ValueError(f"Future State {future_state_id} has no current version.")
    return version


def create_future_state(
    db: Session,
    *,
    scope: FutureStateScope,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    creator: User,
    title: str,
    current_state: str = "",
    desired_state: str = "",
    target_date: date | None = None,
    outcomes: str = "",
    success_measures: str = "",
    constraints: str = "",
    assumptions: str = "",
) -> FutureState:
    """Creates a Future State and its initial (version 1) content snapshot,
    in `DRAFT` status — exact mirror of `create_strategy`'s shape, for the
    Phase 2 field set (source overview §7: no `objective`/`rationale`/
    `priority`/`time_horizon`, adds `target_date`/`outcomes`/
    `success_measures`/`assumptions`).

    Args:
        organization_id: Always required, same convention as
            `create_strategy` — only used to decide which identity column
            to populate when `scope` is `ORGANIZATION`.
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
    """
    future_state = FutureState(
        scope=scope,
        organization_id=organization_id if scope == FutureStateScope.ORGANIZATION else None,
        project_id=project_id if scope == FutureStateScope.PROJECT else None,
        creator_id=creator.id,
    )
    db.add(future_state)
    db.flush()

    now = datetime.now(UTC)
    version = FutureStateVersion(
        future_state_id=future_state.id, version_number=1, valid_from=now, valid_to=None,
        title=title, current_state=current_state, desired_state=desired_state, target_date=target_date,
        outcomes=outcomes, success_measures=success_measures, constraints=constraints, assumptions=assumptions,
        status=FutureStateStatus.DRAFT, change_note="Initial creation.", created_by=creator.id, created_at=now,
    )
    db.add(version)
    db.flush()
    return future_state


def apply_future_state_new_version(
    db: Session,
    future_state: FutureState,
    current_version: FutureStateVersion,
    actor: User,
    *,
    title: str | None = None,
    current_state: str | None = None,
    desired_state: str | None = None,
    target_date: date | None = None,
    target_date_explicitly_set: bool = False,
    outcomes: str | None = None,
    success_measures: str | None = None,
    constraints: str | None = None,
    assumptions: str | None = None,
    status_value: FutureStateStatus | None = None,
    change_note: str = "",
) -> FutureStateVersion:
    """Closes `current_version` and inserts a new one, carrying forward any
    field left unspecified — exact mirror of `apply_new_version`.

    `target_date` is nullable in the schema, so (mirroring `services.
    requirements.apply_new_version`'s identical `review_date`/
    `review_date_explicitly_set` pair) it gets its own `target_date_
    explicitly_set` flag to disambiguate "clear this field"
    (`target_date=None`, flag `True`) from "leave it unchanged" (flag
    stays `False`) — every other field here is non-nullable, so a plain
    `None`-means-"carry forward" check is unambiguous for them.
    """
    now = datetime.now(UTC)
    current_version.valid_to = now

    new_version = FutureStateVersion(
        future_state_id=future_state.id,
        version_number=current_version.version_number + 1,
        valid_from=now,
        valid_to=None,
        title=title if title is not None else current_version.title,
        current_state=current_state if current_state is not None else current_version.current_state,
        desired_state=desired_state if desired_state is not None else current_version.desired_state,
        target_date=target_date if target_date_explicitly_set else current_version.target_date,
        outcomes=outcomes if outcomes is not None else current_version.outcomes,
        success_measures=success_measures if success_measures is not None else current_version.success_measures,
        constraints=constraints if constraints is not None else current_version.constraints,
        assumptions=assumptions if assumptions is not None else current_version.assumptions,
        status=status_value if status_value is not None else current_version.status,
        change_note=change_note,
        created_by=actor.id,
        created_at=now,
    )
    db.add(new_version)
    db.flush()
    return new_version


def archive_future_state(db: Session, future_state: FutureState, actor: User) -> None:
    """Soft-archives a Future State — exact mirror of `archive_strategy`."""
    future_state.is_archived = True
    future_state.archived_at = datetime.now(UTC)
    future_state.archived_by = actor.id


def unarchive_future_state(db: Session, future_state: FutureState) -> None:
    """Reverses `archive_future_state` — exact mirror of `unarchive_strategy`."""
    future_state.is_archived = False
    future_state.archived_at = None
    future_state.archived_by = None


# Legal `FutureStateStatus` transitions — exact mirror of `_ALLOWED_TRANSITIONS`.
_FS_ALLOWED_TRANSITIONS: dict[FutureStateStatus, frozenset[FutureStateStatus]] = {
    FutureStateStatus.DRAFT: frozenset({FutureStateStatus.PROPOSED}),
    FutureStateStatus.PROPOSED: frozenset({FutureStateStatus.UNDER_REVIEW, FutureStateStatus.DRAFT}),
    FutureStateStatus.UNDER_REVIEW: frozenset({FutureStateStatus.APPROVED, FutureStateStatus.DRAFT}),
    FutureStateStatus.APPROVED: frozenset({FutureStateStatus.ACTIVE, FutureStateStatus.RETIRED}),
    FutureStateStatus.ACTIVE: frozenset({FutureStateStatus.SUPERSEDED, FutureStateStatus.RETIRED}),
    FutureStateStatus.SUPERSEDED: frozenset(),
    FutureStateStatus.RETIRED: frozenset(),
}

# Content lock past `UNDER_REVIEW` — exact mirror of Strategy's `LOCKED_STATUSES`.
FUTURE_STATE_LOCKED_STATUSES = frozenset(
    {FutureStateStatus.APPROVED, FutureStateStatus.ACTIVE, FutureStateStatus.SUPERSEDED, FutureStateStatus.RETIRED}
)


def is_future_state_locked(version: FutureStateVersion) -> bool:
    return version.status in FUTURE_STATE_LOCKED_STATUSES


def _future_state_transition(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, new_status: FutureStateStatus,
    actor: User, *, action: str, comment: str | None = None,
) -> FutureStateVersion:
    """Validates `new_status` against `_FS_ALLOWED_TRANSITIONS`, applies it
    via `apply_future_state_new_version`, and records it via `services.
    audit.log_event` — exact mirror of `_transition`.

    Raises:
        ValueError: if `new_status` isn't reachable from `current_version.
            status` per `_FS_ALLOWED_TRANSITIONS`.
    """
    if new_status not in _FS_ALLOWED_TRANSITIONS[current_version.status]:
        raise ValueError(f"Cannot move a Future State from '{current_version.status.value}' to '{new_status.value}'.")
    new_version = apply_future_state_new_version(
        db, future_state, current_version, actor, status_value=new_status, change_note=comment or "",
    )
    log_event(
        db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action=action, actor_id=actor.id,
        organization_id=future_state.organization_id, project_id=future_state.project_id,
        detail={"comment": comment} if comment else None,
    )
    return new_version


def propose_future_state(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User
) -> FutureStateVersion:
    """`DRAFT` -> `PROPOSED`."""
    return _future_state_transition(db, future_state, current_version, FutureStateStatus.PROPOSED, actor, action="proposed")


def submit_future_state_for_review(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User
) -> FutureStateVersion:
    """`PROPOSED` -> `UNDER_REVIEW`."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.UNDER_REVIEW, actor, action="submitted_for_review",
    )


def send_future_state_back_to_draft(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User, *, comment: str
) -> FutureStateVersion:
    """`PROPOSED`/`UNDER_REVIEW` -> `DRAFT`. A comment is required — the
    router enforces this before calling in, mirroring `send_strategy_back_
    to_draft`."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.DRAFT, actor, action="sent_back", comment=comment,
    )


def approve_future_state(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User,
    *, comment: str | None = None,
) -> FutureStateVersion:
    """`UNDER_REVIEW` -> `APPROVED`."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.APPROVED, actor, action="approved", comment=comment,
    )


def activate_future_state(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User,
    *, comment: str | None = None,
) -> FutureStateVersion:
    """`APPROVED` -> `ACTIVE`."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.ACTIVE, actor, action="activated", comment=comment,
    )


def supersede_future_state(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User,
    *, comment: str | None = None,
) -> FutureStateVersion:
    """`ACTIVE` -> `SUPERSEDED`. Deliberately a plain status transition, for
    the same reason `supersede_strategy` is — see that function's own
    docstring."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.SUPERSEDED, actor, action="superseded", comment=comment,
    )


def retire_future_state(
    db: Session, future_state: FutureState, current_version: FutureStateVersion, actor: User,
    *, comment: str | None = None,
) -> FutureStateVersion:
    """`APPROVED`/`ACTIVE` -> `RETIRED`."""
    return _future_state_transition(
        db, future_state, current_version, FutureStateStatus.RETIRED, actor, action="retired", comment=comment,
    )


# --- File-ownership resolution hook (Future State) --------------------------


def resolve_future_state_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to a **project-scoped** Future State directly
    (`FutureStateFile`) or via a `FutureStateComment`
    (`FutureStateCommentFile`) — exact mirror of `resolve_strategy_file_
    project_id`. An org-scoped Future State's files are never resolved
    here — see that function's own docstring for why.

    Returns:
        The owning project's id, or `None` if `file_id` isn't attached to
        a project-scoped Future State or its comment.
    """
    direct_link = db.scalar(select(FutureStateFile).where(FutureStateFile.file_id == file_id))
    if direct_link is not None:
        future_state = db.get(FutureState, direct_link.future_state_id)
        return future_state.project_id if future_state is not None else None

    comment_link = db.scalar(select(FutureStateCommentFile).where(FutureStateCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(FutureStateComment, comment_link.comment_id)
        if comment is not None:
            future_state = db.get(FutureState, comment.future_state_id)
            return future_state.project_id if future_state is not None else None

    return None


# --- Pain Points (Phase 3) ---------------------------------------------------

# This module's third artefact-type string (Pain Point is project-scoped
# only — source overview §6 — so it never needs a `scope` discriminator the
# way Strategy/Future State do), registered on `ModuleDefinition.
# artefact_types` for the same reason `STRATEGY_ARTEFACT_TYPE` is.
PAIN_POINT_ARTEFACT_TYPE = "pain_point"

# Source overview §6.2's own named defaults — seeded once per organisation
# (`seed_default_pain_point_types`), the same "organisation may optionally
# provide default types" convention `services.definitions.seed_link_types`
# already follows for `RequirementLinkTypeDefinition`. Kept module-local
# (not added to that core file's own default-content section) since these
# are a module-owned vocabulary, not a core one.
DEFAULT_PAIN_POINT_TYPES: tuple[str, ...] = ("Market", "User", "Operator")


def seed_default_pain_point_types(db: Session, organization_id: uuid.UUID) -> None:
    """Adds the 3 default `PainPointTypeDefinition` rows (Market/User/
    Operator) for a newly created organisation. Not committed/flushed here
    — caller owns the transaction, mirroring `services.definitions.
    seed_link_types`'s identical convention."""
    for i, name in enumerate(DEFAULT_PAIN_POINT_TYPES):
        db.add(PainPointTypeDefinition(organization_id=organization_id, name=name, sort_order=i, is_active=True))


# --- Org-scoped Pain Point type vocabulary -----------------------------------


def create_org_pain_point_type(db: Session, organization_id: uuid.UUID, name: str) -> PainPointTypeDefinition:
    """Creates a new organisation-scoped Pain Point type (§6.2 "Add
    types"). Placed at the end of the organisation's own display order.

    Raises:
        ValueError: if a type with this name already exists for this
            organisation (the table's own unique constraint would also
            reject it, but this gives the router a clean 400, matching
            `routers.orgs.taxonomies.create_link_type`'s identical
            pre-check convention).
    """
    existing = db.scalar(
        select(PainPointTypeDefinition.id).where(
            PainPointTypeDefinition.organization_id == organization_id, PainPointTypeDefinition.name == name
        )
    )
    if existing is not None:
        raise ValueError(f"A Pain Point type named {name!r} already exists for this organisation.")
    count = len(
        db.scalars(
            select(PainPointTypeDefinition.id).where(PainPointTypeDefinition.organization_id == organization_id)
        ).all()
    )
    pain_point_type = PainPointTypeDefinition(organization_id=organization_id, name=name, sort_order=count)
    db.add(pain_point_type)
    db.flush()
    return pain_point_type


def delete_org_pain_point_type(db: Session, pain_point_type: PainPointTypeDefinition) -> None:
    """Deletes an organisation-scoped Pain Point type (§6.2 "Remove types
    where no longer used").

    Unlike `services.definitions.delete_definition_with_reassignment`
    (used by `RequirementLinkTypeDefinition`/`ActionTypeDefinition`), this
    does **not** offer single-scope reassignment — an org type may be
    referenced (via `ProjectPainPointType.org_type_id`) by override rows
    across *many* projects at once, and a cross-project bulk reassignment
    has no single obviously-correct target the way a same-scope
    reassignment does. **Decided by: Agent.** Blocks outright (`ValueError`,
    translated to a 409 by the router) while any project still references
    this type; the org admin must ask each such project to stop using it
    first (no automated tooling for that within this phase — a reasonable
    scope boundary given how rarely an in-use org type should be removed
    outright rather than merely disabled via `is_active`).

    Raises:
        ValueError: if any `ProjectPainPointType` row still references
            this org type.
    """
    in_use = db.scalar(
        select(ProjectPainPointType.id).where(ProjectPainPointType.org_type_id == pain_point_type.id).limit(1)
    )
    if in_use is not None:
        raise ValueError(
            "This Pain Point type is still referenced by at least one project and cannot be removed. "
            "Disable it instead, or ask each referencing project to stop using it first."
        )
    db.delete(pain_point_type)
    db.flush()


# --- Project-scoped Pain Point type resolution -------------------------------


@dataclass(frozen=True)
class EffectivePainPointType:
    """One row of a project's *effective* Pain Point type list (Phase 0
    Q3) — the merged view `resolve_effective_pain_point_types` builds, never
    itself a stored/materialized table.

    Attributes:
        id: Either a `PainPointTypeDefinition.id` (an org type with no
            project override yet — `source == "org"`) or a
            `ProjectPainPointType.id` (an org type *with* a project
            override, `source == "project_override"`; or a fully
            project-local type, `source == "project_local"`). Passed back
            as `PainPointCreate.pain_point_type_id`/`PainPointUpdate.
            pain_point_type_id`, resolved by `get_or_create_project_
            pain_point_type` regardless of which of the three cases it is.
        name: Effective display name.
        display_order: Effective display/picker order.
        is_enabled: Effective enabled state — a disabled type is still
            listed (so a project admin can see and re-enable it) but
            rejected by `create_pain_point`/`update_pain_point` if selected.
        source: `"org"` / `"project_override"` / `"project_local"` — see
            `id`'s own docstring.
    """

    id: uuid.UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


def resolve_effective_pain_point_types(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> list[EffectivePainPointType]:
    """Resolves a project's effective Pain Point type list (Phase 0 Q3):
    every active org type (using its project override's name/order/enabled
    state if one exists) plus every project-local type. Sorted by effective
    `display_order`.

    No `resolve_effective_action_types`-style parent/child project walk —
    per the plan's own Phase 0 Q3 nested-projects note, an empty
    `ProjectPainPointType` table already means "use org defaults as-is,"
    which is a correct, self-contained empty-state reading requiring no
    further inheritance from a parent project (see `docs/plans/module-01-
    context-and-strategy-plan.md`'s Phase 0 Q3 for the full reasoning).
    """
    org_types = db.scalars(
        select(PainPointTypeDefinition)
        .where(PainPointTypeDefinition.organization_id == organization_id, PainPointTypeDefinition.is_active.is_(True))
    ).all()
    overrides = {
        row.org_type_id: row
        for row in db.scalars(
            select(ProjectPainPointType).where(
                ProjectPainPointType.project_id == project_id, ProjectPainPointType.org_type_id.is_not(None)
            )
        ).all()
    }
    local_rows = db.scalars(
        select(ProjectPainPointType).where(
            ProjectPainPointType.project_id == project_id, ProjectPainPointType.org_type_id.is_(None)
        )
    ).all()

    effective: list[EffectivePainPointType] = []
    for org_type in org_types:
        override = overrides.get(org_type.id)
        if override is not None:
            effective.append(
                EffectivePainPointType(
                    id=override.id,
                    name=override.name_override if override.name_override is not None else org_type.name,
                    display_order=(
                        override.display_order_override
                        if override.display_order_override is not None
                        else org_type.sort_order
                    ),
                    is_enabled=override.is_enabled,
                    source="project_override",
                )
            )
        else:
            effective.append(
                EffectivePainPointType(
                    id=org_type.id, name=org_type.name, display_order=org_type.sort_order,
                    is_enabled=True, source="org",
                )
            )
    for row in local_rows:
        effective.append(
            EffectivePainPointType(
                id=row.id, name=row.name_override or "", display_order=row.display_order_override or 0,
                is_enabled=row.is_enabled, source="project_local",
            )
        )

    effective.sort(key=lambda e: e.display_order)
    return effective


def get_or_create_project_pain_point_type(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID
) -> ProjectPainPointType:
    """Resolves a `PainPointCreate.pain_point_type_id`/`PainPointUpdate.
    pain_point_type_id` value (an `EffectivePainPointType.id`, per that
    dataclass's own docstring) to a concrete `ProjectPainPointType` row,
    creating a "no override yet" passthrough row the first time an org
    type (with no existing override in this project) is actually selected
    for a Pain Point — lazy materialization, not eager (`resolve_effective_
    pain_point_types` itself never writes).

    Raises:
        ValueError: if `type_ref_id` doesn't resolve to any type this
            project can use (not an existing `ProjectPainPointType` row for
            this project, and not an active `PainPointTypeDefinition`
            belonging to this project's own organisation).
    """
    existing = db.get(ProjectPainPointType, type_ref_id)
    if existing is not None and existing.project_id == project_id:
        return existing

    org_type = db.get(PainPointTypeDefinition, type_ref_id)
    if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
        raise ValueError("This is not a valid Pain Point type for this project.")

    passthrough = db.scalar(
        select(ProjectPainPointType).where(
            ProjectPainPointType.project_id == project_id, ProjectPainPointType.org_type_id == org_type.id
        )
    )
    if passthrough is not None:
        return passthrough

    passthrough = ProjectPainPointType(project_id=project_id, org_type_id=org_type.id, is_enabled=True)
    db.add(passthrough)
    db.flush()
    return passthrough


def create_project_local_pain_point_type(
    db: Session, project_id: uuid.UUID, name: str, *, display_order: int | None = None
) -> ProjectPainPointType:
    """Creates a fully project-local Pain Point type (§6.2 "Add types" —
    the genuinely project-only case, not backed by any org row).

    Raises:
        ValueError: if a project-local type with this name already exists
            for this project (checked against the effective list — a
            project-local name colliding with an *org* type's effective
            name is allowed, since they are distinguishable by `source`).
    """
    existing = db.scalar(
        select(ProjectPainPointType.id).where(
            ProjectPainPointType.project_id == project_id, ProjectPainPointType.org_type_id.is_(None),
            ProjectPainPointType.name_override == name,
        )
    )
    if existing is not None:
        raise ValueError(f"A project-local Pain Point type named {name!r} already exists for this project.")
    if display_order is None:
        display_order = len(
            db.scalars(select(ProjectPainPointType.id).where(ProjectPainPointType.project_id == project_id)).all()
        )
    local_type = ProjectPainPointType(
        project_id=project_id, org_type_id=None, name_override=name, display_order_override=display_order,
        is_enabled=True,
    )
    db.add(local_type)
    db.flush()
    return local_type


def set_project_pain_point_type_override(
    db: Session,
    project_pain_point_type: ProjectPainPointType,
    *,
    name: str | None = None,
    display_order: int | None = None,
    is_enabled: bool | None = None,
) -> ProjectPainPointType:
    """Applies a partial update to a `ProjectPainPointType` row — for an
    org-backed row (`org_type_id` set), this is a local override of the
    org type's name/order/enabled state (§6.2 "Rename types"/"Reorder
    types"/"Disable types"); for a project-local row, these fields are its
    own primary name/order/enabled state. Only the fields explicitly
    passed (non-`None`) are changed."""
    if name is not None:
        project_pain_point_type.name_override = name
    if display_order is not None:
        project_pain_point_type.display_order_override = display_order
    if is_enabled is not None:
        project_pain_point_type.is_enabled = is_enabled
    db.flush()
    return project_pain_point_type


def delete_project_pain_point_type(db: Session, project_pain_point_type: ProjectPainPointType) -> None:
    """Deletes a project-scoped `ProjectPainPointType` row (§6.2 "Remove
    types where no longer used").

    For a project-local row (`org_type_id` `NULL`), this genuinely removes
    the type. For an org-backed override row, this simply reverts the
    project to the plain org default (the org type itself is untouched) —
    safe to delete outright rather than needing reassignment, unlike the
    project-local case below.

    **Decided by: Agent** — no `reassign_to_id` support (unlike `services.
    definitions.delete_definition_with_reassignment`): a Pain Point's own
    `pain_point_type_id` is NOT NULL, so removing a project-local type
    still in use by a Pain Point would orphan it. This phase blocks that
    outright rather than adding reassignment machinery `RequirementLinkTypeDefinition`/
    `ActionTypeDefinition` already have elsewhere, disproportionate to a
    single phase's own scope (an org-backed override row is never "in use"
    on its own — a Pain Point can still reference it, so the same check
    applies to both cases uniformly, not only the project-local one).

    Raises:
        ValueError: if any `PainPoint.pain_point_type_id` still references
            this row.
    """
    in_use = db.scalar(select(PainPoint.id).where(PainPoint.pain_point_type_id == project_pain_point_type.id).limit(1))
    if in_use is not None:
        raise ValueError("This Pain Point type is still in use and cannot be removed.")
    db.delete(project_pain_point_type)
    db.flush()


# --- Pain Point CRUD ----------------------------------------------------------


def create_pain_point(
    db: Session,
    *,
    project_id: uuid.UUID,
    pain_point_type: ProjectPainPointType,
    creator: User,
    title: str,
    description: str = "",
    source: str = "",
    impact: str = "",
    evidence: str = "",
    priority: PainPointPriority = PainPointPriority.MEDIUM,
    date_identified: date | None = None,
) -> PainPoint:
    """Creates a Pain Point in `SUBMITTED` status (§6.5's broad-creation
    model — any project member, not just a `pain_point_manager`).

    Args:
        pain_point_type: Already resolved via `get_or_create_project_
            pain_point_type` — this function does not resolve it itself so
            callers can validate `is_enabled` against the effective list
            first (see `project_router.create_project_pain_point`).
        date_identified: Defaults to today if not supplied — lowers the
            friction of a quick problem report from an ordinary member
            (§6.5), the one field on this artefact this module defaults
            server-side rather than requiring explicitly.
    """
    pain_point = PainPoint(
        project_id=project_id, pain_point_type_id=pain_point_type.id, creator_id=creator.id,
        title=title, description=description, source=source, impact=impact, evidence=evidence,
        priority=priority, status=PainPointStatus.SUBMITTED,
        date_identified=date_identified if date_identified is not None else date.today(),
    )
    db.add(pain_point)
    db.flush()
    return pain_point


def update_pain_point(
    db: Session,
    pain_point: PainPoint,
    *,
    pain_point_type: ProjectPainPointType | None = None,
    title: str | None = None,
    description: str | None = None,
    source: str | None = None,
    impact: str | None = None,
    evidence: str | None = None,
    priority: PainPointPriority | None = None,
    owner_id: uuid.UUID | None = None,
    owner_id_explicitly_set: bool = False,
    date_identified: date | None = None,
) -> PainPoint:
    """Mutates `pain_point`'s content fields directly (no version snapshot
    — see module docstring). Any field left `None` (and not explicitly
    flagged otherwise) is left unchanged.

    `owner_id` follows the `target_date_explicitly_set` convention
    `apply_future_state_new_version` already uses for a nullable field —
    assigning `NULL` (unassigning an owner) must be distinguishable from
    "not mentioned in this call."
    """
    if pain_point_type is not None:
        pain_point.pain_point_type_id = pain_point_type.id
    if title is not None:
        pain_point.title = title
    if description is not None:
        pain_point.description = description
    if source is not None:
        pain_point.source = source
    if impact is not None:
        pain_point.impact = impact
    if evidence is not None:
        pain_point.evidence = evidence
    if priority is not None:
        pain_point.priority = priority
    if owner_id_explicitly_set:
        pain_point.owner_id = owner_id
    if date_identified is not None:
        pain_point.date_identified = date_identified
    db.flush()
    return pain_point


def archive_pain_point(db: Session, pain_point: PainPoint, actor: User) -> None:
    """Soft-archives a Pain Point — mirrors `archive_strategy`."""
    pain_point.is_archived = True
    pain_point.archived_at = datetime.now(UTC)
    pain_point.archived_by = actor.id


def unarchive_pain_point(db: Session, pain_point: PainPoint) -> None:
    """Reverses `archive_pain_point` — mirrors `unarchive_strategy`."""
    pain_point.is_archived = False
    pain_point.archived_at = None
    pain_point.archived_by = None


# --- Pain Point lifecycle (branching) ----------------------------------------

# Legal `PainPointStatus` transitions (`enums.PainPointStatus`'s own
# docstring) — the branching shape source overview §6.4 describes:
# `Submitted -> Triaged -> {Rejected | Duplicate | Accepted -> Addressed ->
# Closed}`. `TRIAGED` alone has three legal next states, unlike every other
# lifecycle in this module.
_PP_ALLOWED_TRANSITIONS: dict[PainPointStatus, frozenset[PainPointStatus]] = {
    PainPointStatus.SUBMITTED: frozenset({PainPointStatus.TRIAGED}),
    PainPointStatus.TRIAGED: frozenset(
        {PainPointStatus.REJECTED, PainPointStatus.DUPLICATE, PainPointStatus.ACCEPTED}
    ),
    PainPointStatus.REJECTED: frozenset(),
    PainPointStatus.DUPLICATE: frozenset(),
    PainPointStatus.ACCEPTED: frozenset({PainPointStatus.ADDRESSED}),
    PainPointStatus.ADDRESSED: frozenset({PainPointStatus.CLOSED}),
    PainPointStatus.CLOSED: frozenset(),
}

# Content is locked once a Pain Point reaches a terminal outcome —
# `REJECTED`/`DUPLICATE`/`CLOSED` are this lifecycle's true end states.
# `ACCEPTED`/`ADDRESSED` deliberately stay unlocked (unlike Strategy's
# `LOCKED_STATUSES`, which locks at `APPROVED` and everything after) —
# **Decided by: Agent** — a `pain_point_manager` may still need to
# reassign `owner_id`/adjust `priority` while work is genuinely in
# progress (`ACCEPTED`/`ADDRESSED`), not only before triage.
PAIN_POINT_LOCKED_STATUSES = frozenset({PainPointStatus.REJECTED, PainPointStatus.DUPLICATE, PainPointStatus.CLOSED})


def is_pain_point_locked(pain_point: PainPoint) -> bool:
    return pain_point.status in PAIN_POINT_LOCKED_STATUSES


def _pp_transition(
    db: Session, pain_point: PainPoint, new_status: PainPointStatus, actor: User, *,
    action: str, comment: str | None = None,
) -> PainPoint:
    """Validates `new_status` against `_PP_ALLOWED_TRANSITIONS`, mutates
    `pain_point.status` directly (no version snapshot — see module
    docstring), and records it via `services.audit.log_event`.

    Raises:
        ValueError: if `new_status` isn't reachable from `pain_point.
            status` per `_PP_ALLOWED_TRANSITIONS`.
    """
    if new_status not in _PP_ALLOWED_TRANSITIONS[pain_point.status]:
        raise ValueError(f"Cannot move a Pain Point from '{pain_point.status.value}' to '{new_status.value}'.")
    pain_point.status = new_status
    db.flush()
    log_event(
        db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action=action, actor_id=actor.id,
        project_id=pain_point.project_id, detail={"comment": comment} if comment else None,
    )
    return pain_point


def triage_pain_point(db: Session, pain_point: PainPoint, actor: User, *, comment: str | None = None) -> PainPoint:
    """`SUBMITTED` -> `TRIAGED`."""
    return _pp_transition(db, pain_point, PainPointStatus.TRIAGED, actor, action="triaged", comment=comment)


def reject_pain_point(db: Session, pain_point: PainPoint, actor: User, *, comment: str) -> PainPoint:
    """`TRIAGED` -> `REJECTED`. A comment is required, mirroring every
    other mandatory-comment-on-rejection rule in this codebase."""
    return _pp_transition(db, pain_point, PainPointStatus.REJECTED, actor, action="rejected", comment=comment)


def mark_pain_point_duplicate(db: Session, pain_point: PainPoint, actor: User, *, comment: str) -> PainPoint:
    """`TRIAGED` -> `DUPLICATE`. A comment is required — until Phase 6
    wires the real `ArtefactLink` to the canonical Pain Point (§6.5's
    "Merge duplicates" — this phase is deliberately just the status
    transition, per this module's own plan), the mandatory comment is
    where the canonical Pain Point is noted."""
    return _pp_transition(db, pain_point, PainPointStatus.DUPLICATE, actor, action="marked_duplicate", comment=comment)


def accept_pain_point(db: Session, pain_point: PainPoint, actor: User, *, comment: str | None = None) -> PainPoint:
    """`TRIAGED` -> `ACCEPTED`."""
    return _pp_transition(db, pain_point, PainPointStatus.ACCEPTED, actor, action="accepted", comment=comment)


def address_pain_point(db: Session, pain_point: PainPoint, actor: User, *, comment: str | None = None) -> PainPoint:
    """`ACCEPTED` -> `ADDRESSED`."""
    return _pp_transition(db, pain_point, PainPointStatus.ADDRESSED, actor, action="addressed", comment=comment)


def close_pain_point(db: Session, pain_point: PainPoint, actor: User, *, comment: str | None = None) -> PainPoint:
    """`ADDRESSED` -> `CLOSED`."""
    return _pp_transition(db, pain_point, PainPointStatus.CLOSED, actor, action="closed", comment=comment)


# --- File-ownership resolution hook (Pain Point) -----------------------------


def resolve_pain_point_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to a Pain Point directly (`PainPointFile`) or via a
    `PainPointComment` (`PainPointCommentFile`) — exact mirror of
    `resolve_strategy_file_project_id`, simpler than that function since
    Pain Point is project-scoped only (no org-resource branch to not
    resolve here).

    Returns:
        The owning project's id, or `None` if `file_id` isn't attached to
        a Pain Point or its comment.
    """
    direct_link = db.scalar(select(PainPointFile).where(PainPointFile.file_id == file_id))
    if direct_link is not None:
        pain_point = db.get(PainPoint, direct_link.pain_point_id)
        return pain_point.project_id if pain_point is not None else None

    comment_link = db.scalar(select(PainPointCommentFile).where(PainPointCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(PainPointComment, comment_link.comment_id)
        if comment is not None:
            pain_point = db.get(PainPoint, comment.pain_point_id)
            return pain_point.project_id if pain_point is not None else None

    return None


# --- Guiding Principles (Phase 4) --------------------------------------------

# This module's fourth artefact-type string, registered on `ModuleDefinition.
# artefact_types` (module.py) for the same reason `STRATEGY_ARTEFACT_TYPE` is.
GUIDING_PRINCIPLE_ARTEFACT_TYPE = "guiding_principle"


def get_current_guiding_principle_version(db: Session, guiding_principle_id: uuid.UUID) -> GuidingPrincipleVersion:
    """Returns the current (`valid_to IS NULL`) version row for a Guiding
    Principle — exact mirror of `get_current_version`/`get_current_future_
    state_version`.

    Raises:
        ValueError: if no current version exists (data-integrity bug).
    """
    version = db.scalar(
        select(GuidingPrincipleVersion).where(
            GuidingPrincipleVersion.guiding_principle_id == guiding_principle_id,
            GuidingPrincipleVersion.valid_to.is_(None),
        )
    )
    if version is None:
        raise ValueError(f"Guiding Principle {guiding_principle_id} has no current version.")
    return version


def create_guiding_principle(
    db: Session,
    *,
    scope: GuidingPrincipleScope,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    creator: User,
    name: str,
    principle_statement: str,
    rationale: str = "",
    priority: GuidingPrinciplePriority = GuidingPrinciplePriority.MEDIUM,
    owner_id: uuid.UUID | None = None,
) -> GuidingPrinciple:
    """Creates a Guiding Principle and its initial (version 1) content
    snapshot, in `DRAFT` status — exact mirror of `create_strategy`/`create_
    future_state`'s shape, for the Phase 4 field set (source overview §8.3:
    no `type` field, no `time_horizon`/`expected_outcomes`/`constraints`/
    `measures_of_success`).

    Args:
        organization_id: Always required, same convention as
            `create_strategy` — only used to decide which identity column
            to populate when `scope` is `ORGANIZATION`.
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
    """
    guiding_principle = GuidingPrinciple(
        scope=scope,
        organization_id=organization_id if scope == GuidingPrincipleScope.ORGANIZATION else None,
        project_id=project_id if scope == GuidingPrincipleScope.PROJECT else None,
        creator_id=creator.id,
    )
    db.add(guiding_principle)
    db.flush()

    now = datetime.now(UTC)
    version = GuidingPrincipleVersion(
        guiding_principle_id=guiding_principle.id, version_number=1, valid_from=now, valid_to=None,
        name=name, principle_statement=principle_statement, rationale=rationale, priority=priority,
        status=GuidingPrincipleStatus.DRAFT, owner_id=owner_id, change_note="Initial creation.",
        created_by=creator.id, created_at=now,
    )
    db.add(version)
    db.flush()
    return guiding_principle


def apply_guiding_principle_new_version(
    db: Session,
    guiding_principle: GuidingPrinciple,
    current_version: GuidingPrincipleVersion,
    actor: User,
    *,
    name: str | None = None,
    principle_statement: str | None = None,
    rationale: str | None = None,
    priority: GuidingPrinciplePriority | None = None,
    owner_id: uuid.UUID | None = None,
    owner_id_explicitly_set: bool = False,
    status_value: GuidingPrincipleStatus | None = None,
    change_note: str = "",
) -> GuidingPrincipleVersion:
    """Closes `current_version` and inserts a new one, carrying forward any
    field left unspecified — exact mirror of `apply_new_version`/`apply_
    future_state_new_version`.

    `owner_id` is nullable (a Guiding Principle may have no assigned owner),
    so — mirroring `apply_future_state_new_version`'s `target_date`/
    `target_date_explicitly_set` pair — it gets its own `owner_id_
    explicitly_set` flag to disambiguate "unassign the owner"
    (`owner_id=None`, flag `True`) from "leave it unchanged" (flag stays
    `False`).
    """
    now = datetime.now(UTC)
    current_version.valid_to = now

    new_version = GuidingPrincipleVersion(
        guiding_principle_id=guiding_principle.id,
        version_number=current_version.version_number + 1,
        valid_from=now,
        valid_to=None,
        name=name if name is not None else current_version.name,
        principle_statement=(
            principle_statement if principle_statement is not None else current_version.principle_statement
        ),
        rationale=rationale if rationale is not None else current_version.rationale,
        priority=priority if priority is not None else current_version.priority,
        status=status_value if status_value is not None else current_version.status,
        owner_id=owner_id if owner_id_explicitly_set else current_version.owner_id,
        change_note=change_note,
        created_by=actor.id,
        created_at=now,
    )
    db.add(new_version)
    db.flush()
    return new_version


def archive_guiding_principle(db: Session, guiding_principle: GuidingPrinciple, actor: User) -> None:
    """Soft-archives a Guiding Principle — exact mirror of `archive_strategy`."""
    guiding_principle.is_archived = True
    guiding_principle.archived_at = datetime.now(UTC)
    guiding_principle.archived_by = actor.id


def unarchive_guiding_principle(db: Session, guiding_principle: GuidingPrinciple) -> None:
    """Reverses `archive_guiding_principle` — exact mirror of `unarchive_strategy`."""
    guiding_principle.is_archived = False
    guiding_principle.archived_at = None
    guiding_principle.archived_by = None


# Legal `GuidingPrincipleStatus` transitions (`enums.GuidingPrincipleStatus`'s
# own docstring): a linear chain with no `UNDER_REVIEW` step — `PROPOSED`
# moves directly to `APPROVED` (or back to `DRAFT`, this module's "reject"-
# equivalent) — otherwise the same shape as `_ALLOWED_TRANSITIONS`/
# `_FS_ALLOWED_TRANSITIONS` (`APPROVED`/`ACTIVE` both able to reach
# `RETIRED` directly; `ACTIVE` can also reach `SUPERSEDED`).
_GP_ALLOWED_TRANSITIONS: dict[GuidingPrincipleStatus, frozenset[GuidingPrincipleStatus]] = {
    GuidingPrincipleStatus.DRAFT: frozenset({GuidingPrincipleStatus.PROPOSED}),
    GuidingPrincipleStatus.PROPOSED: frozenset({GuidingPrincipleStatus.APPROVED, GuidingPrincipleStatus.DRAFT}),
    GuidingPrincipleStatus.APPROVED: frozenset({GuidingPrincipleStatus.ACTIVE, GuidingPrincipleStatus.RETIRED}),
    GuidingPrincipleStatus.ACTIVE: frozenset({GuidingPrincipleStatus.SUPERSEDED, GuidingPrincipleStatus.RETIRED}),
    GuidingPrincipleStatus.SUPERSEDED: frozenset(),
    GuidingPrincipleStatus.RETIRED: frozenset(),
}

# Content is locked once past `PROPOSED` (i.e. `APPROVED` and beyond) — the
# same "lock at the first state past the last pre-approval state" rule
# `Strategy`/`FutureState` apply one state later (past `UNDER_REVIEW`, since
# they have that extra state and this lifecycle doesn't — see `enums.
# GuidingPrincipleStatus`'s own docstring for why there is no `UNDER_REVIEW`
# here).
GUIDING_PRINCIPLE_LOCKED_STATUSES = frozenset(
    {
        GuidingPrincipleStatus.APPROVED, GuidingPrincipleStatus.ACTIVE,
        GuidingPrincipleStatus.SUPERSEDED, GuidingPrincipleStatus.RETIRED,
    }
)


def is_guiding_principle_locked(version: GuidingPrincipleVersion) -> bool:
    return version.status in GUIDING_PRINCIPLE_LOCKED_STATUSES


def _guiding_principle_transition(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion,
    new_status: GuidingPrincipleStatus, actor: User, *, action: str, comment: str | None = None,
) -> GuidingPrincipleVersion:
    """Validates `new_status` against `_GP_ALLOWED_TRANSITIONS`, applies it
    via `apply_guiding_principle_new_version`, and records it via `services.
    audit.log_event` — exact mirror of `_transition`/`_future_state_transition`.

    Raises:
        ValueError: if `new_status` isn't reachable from `current_version.
            status` per `_GP_ALLOWED_TRANSITIONS`.
    """
    if new_status not in _GP_ALLOWED_TRANSITIONS[current_version.status]:
        raise ValueError(
            f"Cannot move a Guiding Principle from '{current_version.status.value}' to '{new_status.value}'."
        )
    new_version = apply_guiding_principle_new_version(
        db, guiding_principle, current_version, actor, status_value=new_status, change_note=comment or "",
    )
    log_event(
        db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action=action,
        actor_id=actor.id, organization_id=guiding_principle.organization_id, project_id=guiding_principle.project_id,
        detail={"comment": comment} if comment else None,
    )
    return new_version


def propose_guiding_principle(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User
) -> GuidingPrincipleVersion:
    """`DRAFT` -> `PROPOSED`: ready for others to review."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.PROPOSED, actor, action="proposed",
    )


def send_guiding_principle_back_to_draft(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User,
    *, comment: str,
) -> GuidingPrincipleVersion:
    """`PROPOSED` -> `DRAFT`: this module's "reject"-equivalent (see
    `enums.GuidingPrincipleStatus`'s own docstring). A comment is required
    — the router enforces this before calling in, mirroring every other
    mandatory-comment-on-rejection rule in this codebase."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.DRAFT, actor, action="sent_back",
        comment=comment,
    )


def approve_guiding_principle(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User,
    *, comment: str | None = None,
) -> GuidingPrincipleVersion:
    """`PROPOSED` -> `APPROVED`."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.APPROVED, actor, action="approved",
        comment=comment,
    )


def activate_guiding_principle(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User,
    *, comment: str | None = None,
) -> GuidingPrincipleVersion:
    """`APPROVED` -> `ACTIVE`: the Guiding Principle is now formally in effect."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.ACTIVE, actor, action="activated",
        comment=comment,
    )


def supersede_guiding_principle(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User,
    *, comment: str | None = None,
) -> GuidingPrincipleVersion:
    """`ACTIVE` -> `SUPERSEDED`. Deliberately a plain status transition, for
    the same reason `supersede_strategy`/`supersede_future_state` are — see
    those functions' own docstrings. Recording *which* Guiding Principle
    supersedes this one (a typed `ArtefactLink`) is Phase 6's job."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.SUPERSEDED, actor, action="superseded",
        comment=comment,
    )


def retire_guiding_principle(
    db: Session, guiding_principle: GuidingPrinciple, current_version: GuidingPrincipleVersion, actor: User,
    *, comment: str | None = None,
) -> GuidingPrincipleVersion:
    """`APPROVED`/`ACTIVE` -> `RETIRED`."""
    return _guiding_principle_transition(
        db, guiding_principle, current_version, GuidingPrincipleStatus.RETIRED, actor, action="retired",
        comment=comment,
    )


# --- File-ownership resolution hook (Guiding Principle) ----------------------


def resolve_guiding_principle_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to a **project-scoped** Guiding Principle directly
    (`GuidingPrincipleFile`) or via a `GuidingPrincipleComment`
    (`GuidingPrincipleCommentFile`) — exact mirror of `resolve_strategy_
    file_project_id`/`resolve_future_state_file_project_id`. An org-scoped
    Guiding Principle's files are never resolved here — see those
    functions' own docstrings for why.

    Returns:
        The owning project's id, or `None` if `file_id` isn't attached to
        a project-scoped Guiding Principle or its comment.
    """
    direct_link = db.scalar(select(GuidingPrincipleFile).where(GuidingPrincipleFile.file_id == file_id))
    if direct_link is not None:
        guiding_principle = db.get(GuidingPrinciple, direct_link.guiding_principle_id)
        return guiding_principle.project_id if guiding_principle is not None else None

    comment_link = db.scalar(select(GuidingPrincipleCommentFile).where(GuidingPrincipleCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(GuidingPrincipleComment, comment_link.comment_id)
        if comment is not None:
            guiding_principle = db.get(GuidingPrinciple, comment.guiding_principle_id)
            return guiding_principle.project_id if guiding_principle is not None else None

    return None


# --- Open Questions (Phase 5) -------------------------------------------------

# This module's fifth artefact-type string, registered on `ModuleDefinition.
# artefact_types` (module.py) for the same reason `STRATEGY_ARTEFACT_TYPE`
# is. Open Question is project-scoped only, like Pain Point (see `models.
# OpenQuestion`'s own docstring for the scope reasoning).
OPEN_QUESTION_ARTEFACT_TYPE = "open_question"


def create_open_question(
    db: Session,
    *,
    project_id: uuid.UUID,
    creator: User,
    question: str,
    context: str = "",
    evidence: str = "",
    priority: OpenQuestionPriority = OpenQuestionPriority.MEDIUM,
    due_date: date | None = None,
) -> OpenQuestion:
    """Creates an Open Question in `OPEN` status (§9.4's broad-creation
    model — any project member, not just an `open_question_owner`)."""
    open_question = OpenQuestion(
        project_id=project_id, creator_id=creator.id, question=question, context=context, evidence=evidence,
        priority=priority, status=OpenQuestionStatus.OPEN, due_date=due_date,
    )
    db.add(open_question)
    db.flush()
    return open_question


def update_open_question(
    db: Session,
    open_question: OpenQuestion,
    *,
    question: str | None = None,
    context: str | None = None,
    evidence: str | None = None,
    priority: OpenQuestionPriority | None = None,
    owner_id: uuid.UUID | None = None,
    owner_id_explicitly_set: bool = False,
    due_date: date | None = None,
    due_date_explicitly_set: bool = False,
) -> OpenQuestion:
    """Mutates `open_question`'s content fields directly (no version
    snapshot — see module docstring). Any field left `None` (and not
    explicitly flagged otherwise) is left unchanged.

    `owner_id`/`due_date` are both nullable, so — mirroring `update_pain_
    point`'s `owner_id`/`owner_id_explicitly_set` pair and `apply_future_
    state_new_version`'s `target_date`/`target_date_explicitly_set` pair —
    each gets its own `..._explicitly_set` flag to disambiguate "clear this
    field" from "leave it unchanged."
    """
    if question is not None:
        open_question.question = question
    if context is not None:
        open_question.context = context
    if evidence is not None:
        open_question.evidence = evidence
    if priority is not None:
        open_question.priority = priority
    if owner_id_explicitly_set:
        open_question.owner_id = owner_id
    if due_date_explicitly_set:
        open_question.due_date = due_date
    db.flush()
    return open_question


def archive_open_question(db: Session, open_question: OpenQuestion, actor: User) -> None:
    """Soft-archives an Open Question — mirrors `archive_pain_point`."""
    open_question.is_archived = True
    open_question.archived_at = datetime.now(UTC)
    open_question.archived_by = actor.id


def unarchive_open_question(db: Session, open_question: OpenQuestion) -> None:
    """Reverses `archive_open_question` — mirrors `unarchive_pain_point`."""
    open_question.is_archived = False
    open_question.archived_at = None
    open_question.archived_by = None


# --- Open Question lifecycle (branching) --------------------------------------

# Legal `OpenQuestionStatus` transitions (`enums.OpenQuestionStatus`'s own
# docstring) — the branching shape source overview §9.3 describes, with two
# branch points (unlike Pain Point's one): `Open -> Investigating ->
# {Withdrawn | Ready for Decision -> {Resolved | Withdrawn}}`.
_OQ_ALLOWED_TRANSITIONS: dict[OpenQuestionStatus, frozenset[OpenQuestionStatus]] = {
    OpenQuestionStatus.OPEN: frozenset({OpenQuestionStatus.INVESTIGATING}),
    OpenQuestionStatus.INVESTIGATING: frozenset(
        {OpenQuestionStatus.READY_FOR_DECISION, OpenQuestionStatus.WITHDRAWN}
    ),
    OpenQuestionStatus.READY_FOR_DECISION: frozenset(
        {OpenQuestionStatus.RESOLVED, OpenQuestionStatus.WITHDRAWN}
    ),
    OpenQuestionStatus.RESOLVED: frozenset(),
    OpenQuestionStatus.WITHDRAWN: frozenset(),
}

# Content is locked once an Open Question reaches a terminal outcome —
# `RESOLVED`/`WITHDRAWN` are this lifecycle's true end states. `INVESTIGATING`/
# `READY_FOR_DECISION` deliberately stay unlocked (same reasoning as Pain
# Point's `ACCEPTED`/`ADDRESSED` — an `open_question_owner` may still need to
# reassign `owner_id`/adjust `priority`/`due_date` while investigation is
# genuinely in progress).
OPEN_QUESTION_LOCKED_STATUSES = frozenset({OpenQuestionStatus.RESOLVED, OpenQuestionStatus.WITHDRAWN})


def is_open_question_locked(open_question: OpenQuestion) -> bool:
    return open_question.status in OPEN_QUESTION_LOCKED_STATUSES


def _oq_transition(
    db: Session, open_question: OpenQuestion, new_status: OpenQuestionStatus, actor: User, *,
    action: str, comment: str | None = None,
) -> OpenQuestion:
    """Validates `new_status` against `_OQ_ALLOWED_TRANSITIONS`, mutates
    `open_question.status` directly (no version snapshot — see module
    docstring), and records it via `services.audit.log_event` — exact
    mirror of `_pp_transition`.

    Raises:
        ValueError: if `new_status` isn't reachable from `open_question.
            status` per `_OQ_ALLOWED_TRANSITIONS`.
    """
    if new_status not in _OQ_ALLOWED_TRANSITIONS[open_question.status]:
        raise ValueError(f"Cannot move an Open Question from '{open_question.status.value}' to '{new_status.value}'.")
    open_question.status = new_status
    db.flush()
    log_event(
        db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action=action, actor_id=actor.id,
        project_id=open_question.project_id, detail={"comment": comment} if comment else None,
    )
    return open_question


def investigate_open_question(db: Session, open_question: OpenQuestion, actor: User, *, comment: str | None = None) -> OpenQuestion:
    """`OPEN` -> `INVESTIGATING`."""
    return _oq_transition(db, open_question, OpenQuestionStatus.INVESTIGATING, actor, action="investigating", comment=comment)


def mark_open_question_ready_for_decision(
    db: Session, open_question: OpenQuestion, actor: User, *, comment: str | None = None
) -> OpenQuestion:
    """`INVESTIGATING` -> `READY_FOR_DECISION`."""
    return _oq_transition(
        db, open_question, OpenQuestionStatus.READY_FOR_DECISION, actor, action="ready_for_decision", comment=comment,
    )


def withdraw_open_question(db: Session, open_question: OpenQuestion, actor: User, *, comment: str) -> OpenQuestion:
    """`INVESTIGATING`/`READY_FOR_DECISION` -> `WITHDRAWN`. A comment is
    required, mirroring every other mandatory-comment-on-a-negative-outcome
    rule in this codebase (`reject_pain_point`/`mark_pain_point_duplicate`).
    §9.4's "Close" capability — closing an Open Question without a Decision,
    as distinct from `resolve_open_question`'s "Resolve through a
    Decision"."""
    return _oq_transition(db, open_question, OpenQuestionStatus.WITHDRAWN, actor, action="withdrawn", comment=comment)


def resolve_open_question(db: Session, open_question: OpenQuestion, actor: User, *, comment: str | None = None) -> OpenQuestion:
    """`READY_FOR_DECISION` -> `RESOLVED`. Deliberately a plain status
    transition here, not the actual "Create Decision from Open Question"
    workflow (§9.5) or its `ArtefactLink` — see module docstring."""
    return _oq_transition(db, open_question, OpenQuestionStatus.RESOLVED, actor, action="resolved", comment=comment)


# --- File-ownership resolution hook (Open Question) --------------------------


def resolve_open_question_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to an Open Question directly (`OpenQuestionFile`) or via an
    `OpenQuestionComment` (`OpenQuestionCommentFile`) — exact mirror of
    `resolve_pain_point_file_project_id` (Open Question is project-scoped
    only, like Pain Point — no org-resource branch to not resolve here).

    Returns:
        The owning project's id, or `None` if `file_id` isn't attached to
        an Open Question or its comment.
    """
    direct_link = db.scalar(select(OpenQuestionFile).where(OpenQuestionFile.file_id == file_id))
    if direct_link is not None:
        open_question = db.get(OpenQuestion, direct_link.open_question_id)
        return open_question.project_id if open_question is not None else None

    comment_link = db.scalar(select(OpenQuestionCommentFile).where(OpenQuestionCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(OpenQuestionComment, comment_link.comment_id)
        if comment is not None:
            open_question = db.get(OpenQuestion, comment.open_question_id)
            return open_question.project_id if open_question is not None else None

    return None


# --- Phase 6: cross-artefact relationships ----------------------------------
#
# See module docstring's Phase 6 section for the overall design. Every
# *typed* relationship name below is created lazily, on first use, as an
# org-shared `RequirementLinkTypeDefinition` row (mirroring `modules.
# decisions.service._get_or_create_link_type` exactly) — no migration/
# seeding needed. An *untyped* relationship (`forward_name=None` below)
# creates a plain `ArtefactLink` with `link_type_id=None`, per source
# overview §6.6's own instruction to distinguish causation/rationale
# (typed) from generic association (untyped).


def _resolve_scope_organization_id(
    db: Session, *, organization_id: uuid.UUID | None, project_id: uuid.UUID | None
) -> uuid.UUID:
    """Resolves the owning organisation id for an artefact that carries
    either `organization_id` directly (an org-scoped Strategy/Future
    State/Guiding Principle row) or only a `project_id` (a project-scoped
    row of any of this module's five artefact types) — the common
    denominator every link-target resolver below needs before
    `create_context_strategy_link` can enforce its same-organisation rule.

    Raises:
        ValueError: if `project_id` doesn't resolve to a real `Project`
            (both `organization_id`/`project_id` being `None` is a caller
            bug, not a real "not found," but is treated the same way here).
    """
    if organization_id is not None:
        return organization_id
    from app.models.project import Project

    resolved = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    if resolved is None:
        raise ValueError("Project not found.")
    return resolved


def resolve_link_target_organization_id(db: Session, target_type: str, target_id: uuid.UUID) -> uuid.UUID:
    """Resolves a relationship target's owning organisation — core
    `Requirement`, or any of this module's own five artefact types (the
    only target types any `*LinkKind` below ever names) — so `create_
    context_strategy_link` can validate the target actually exists and
    belongs to the same organisation as the link's source, before creating
    the `ArtefactLink` row. Deliberately does not (and structurally cannot)
    resolve a Decision id — see module docstring's "Decision-target
    relationships stay reserved" section for why that's Module 4's own job,
    not a gap in this function.

    Raises:
        ValueError: if `target_id` doesn't resolve to a real row of
            `target_type`, or `target_type` isn't one this function knows
            how to resolve at all.
    """
    if target_type == ArtefactType.REQUIREMENT.value:
        from app.models.project import Project
        from app.models.requirement import Requirement

        requirement = db.get(Requirement, target_id)
        if requirement is None:
            raise ValueError("Requirement not found.")
        org_id = db.scalar(select(Project.organization_id).where(Project.id == requirement.project_id))
        if org_id is None:
            raise ValueError("Requirement's project not found.")
        return org_id
    if target_type == STRATEGY_ARTEFACT_TYPE:
        strategy = db.get(Strategy, target_id)
        if strategy is None:
            raise ValueError("Strategy not found.")
        return _resolve_scope_organization_id(db, organization_id=strategy.organization_id, project_id=strategy.project_id)
    if target_type == FUTURE_STATE_ARTEFACT_TYPE:
        future_state = db.get(FutureState, target_id)
        if future_state is None:
            raise ValueError("Future State not found.")
        return _resolve_scope_organization_id(
            db, organization_id=future_state.organization_id, project_id=future_state.project_id
        )
    if target_type == PAIN_POINT_ARTEFACT_TYPE:
        pain_point = db.get(PainPoint, target_id)
        if pain_point is None:
            raise ValueError("Pain Point not found.")
        return _resolve_scope_organization_id(db, organization_id=None, project_id=pain_point.project_id)
    if target_type == GUIDING_PRINCIPLE_ARTEFACT_TYPE:
        guiding_principle = db.get(GuidingPrinciple, target_id)
        if guiding_principle is None:
            raise ValueError("Guiding Principle not found.")
        return _resolve_scope_organization_id(
            db, organization_id=guiding_principle.organization_id, project_id=guiding_principle.project_id
        )
    if target_type == OPEN_QUESTION_ARTEFACT_TYPE:
        open_question = db.get(OpenQuestion, target_id)
        if open_question is None:
            raise ValueError("Open Question not found.")
        return _resolve_scope_organization_id(db, organization_id=None, project_id=open_question.project_id)
    raise ValueError(f"Unsupported relationship target type: {target_type!r}.")


def _get_or_create_cs_link_type(
    db: Session, organization_id: uuid.UUID, *, forward_name: str, reverse_name: str
) -> RequirementLinkTypeDefinition:
    """This module's own copy of `modules.decisions.service._get_or_create_
    link_type` — duplicated rather than imported (Decision Management's own
    version is a private, underscore-prefixed helper not meant for reuse,
    and importing it would be a cross-module import this codebase's Modular
    Feature System Boundary rule forbids regardless). Matches this module's
    own existing precedent of duplicating small per-module patterns rather
    than sharing private helpers across modules (Phase 1's `StrategyComment`/
    `StrategyCommentFile`/`StrategyFile` vs. Decision's `DecisionComment`/
    `DecisionCommentFile`/`DecisionFile` — see that phase's own notes)."""
    link_type = db.scalar(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == forward_name,
        )
    )
    if link_type is not None:
        return link_type
    from sqlalchemy import func

    next_sort_order = db.scalar(
        select(func.count())
        .select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=forward_name, reverse_name=reverse_name,
        sort_order=next_sort_order,
    )
    db.add(link_type)
    db.flush()
    return link_type


def create_context_strategy_link(
    db: Session, *, source_type: str, source_id: uuid.UUID, source_organization_id: uuid.UUID,
    target_type: str, target_id: uuid.UUID, forward_name: str | None, reverse_name: str | None,
    actor_id: uuid.UUID,
) -> ArtefactLink:
    """The single generic relationship-creation dispatcher every `create_
    <source>_link` wrapper below calls.

    Args:
        source_type / source_id: The link's source artefact — already
            resolved and authorized by the caller (router layer), mirroring
            `services.relationships.create_link`'s own contract.
        source_organization_id: The source's own owning organisation
            (already resolved by the caller via `_resolve_scope_
            organization_id`) — compared against the target's, below.
        target_type / target_id: The link's target artefact.
        forward_name / reverse_name: The `RequirementLinkTypeDefinition`
            name pair for a *typed* relationship, or both `None` for an
            *untyped* "related to" association (see module docstring).
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if source and target are the same artefact, the target
            doesn't exist or belongs to a different organisation, or this
            exact relationship already exists.
    """
    if source_type == target_type and source_id == target_id:
        raise ValueError("An artefact cannot link to itself.")
    target_organization_id = resolve_link_target_organization_id(db, target_type, target_id)
    if target_organization_id != source_organization_id:
        raise ValueError("Both artefacts must belong to the same organisation.")
    link_type_id = None
    if forward_name is not None:
        link_type = _get_or_create_cs_link_type(
            db, source_organization_id, forward_name=forward_name, reverse_name=reverse_name or forward_name,
        )
        link_type_id = link_type.id
    if (
        get_link_between(
            db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
            link_type_id=link_type_id,
        )
        is not None
    ):
        raise ValueError("This relationship already exists.")
    return create_link(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type_id=link_type_id, created_by=actor_id,
    )


# --- Strategy relationships (source overview §5.6) --------------------------


class StrategyLinkKind(str, enum.Enum):
    """Which of §5.6's Strategy-sourced relationship types `create_strategy_
    link` should create. `DRIVES_REQUIREMENT` deliberately reuses the same
    `"Drives"` link-type name `PainPointLinkKind.DRIVES_STRATEGY` uses (see
    `_get_or_create_cs_link_type` — keyed on `(organization_id,
    forward_name)` alone, no per-pair type constraint), since both express
    the same causal relationship concept one level apart in the Pain Point
    -> Strategy -> Requirement chain. `INFORMS_DECISION`/`GUIDED_BY_
    GUIDING_PRINCIPLE`/`REQUIRES_RESOLUTION_OF_OPEN_QUESTION` from §5.6's
    own list are **not** all present here — `INFORMS_DECISION` is the
    reserved Decision-target relationship (module docstring); `GUIDED_BY_
    GUIDING_PRINCIPLE` is instead built from Guiding Principle's own side
    (`GuidingPrincipleLinkKind.SUPPORTS_STRATEGY`, per §8.5's "Strategy ->
    supported by -> Guiding Principle" — one relationship, built once, not
    duplicated from both ends)."""

    DRIVES_REQUIREMENT = "drives_requirement"
    DEFINES_FUTURE_STATE = "defines_future_state"
    REQUIRES_RESOLUTION_OF_OPEN_QUESTION = "requires_resolution_of_open_question"
    CONTRIBUTES_TO_STRATEGY = "contributes_to_strategy"


_STRATEGY_LINK_SPECS: dict[StrategyLinkKind, tuple[str, str | None, str | None]] = {
    StrategyLinkKind.DRIVES_REQUIREMENT: (ArtefactType.REQUIREMENT.value, "Drives", "Is driven by"),
    StrategyLinkKind.DEFINES_FUTURE_STATE: (FUTURE_STATE_ARTEFACT_TYPE, "Defines", "Is defined by"),
    StrategyLinkKind.REQUIRES_RESOLUTION_OF_OPEN_QUESTION: (
        OPEN_QUESTION_ARTEFACT_TYPE, "Requires resolution of", "Resolution is required by",
    ),
    StrategyLinkKind.CONTRIBUTES_TO_STRATEGY: (STRATEGY_ARTEFACT_TYPE, "Contributes to", "Is contributed to by"),
}


def create_strategy_link(
    db: Session, *, strategy: Strategy, kind: StrategyLinkKind, target_id: uuid.UUID, actor_id: uuid.UUID,
) -> ArtefactLink:
    """Creates one of §5.6's Strategy-sourced relationships. `strategy` is
    the link's source; `target_id` is an id of whichever artefact type
    `kind` implies (`_STRATEGY_LINK_SPECS`)."""
    target_type, forward_name, reverse_name = _STRATEGY_LINK_SPECS[kind]
    source_organization_id = _resolve_scope_organization_id(
        db, organization_id=strategy.organization_id, project_id=strategy.project_id
    )
    return create_context_strategy_link(
        db, source_type=STRATEGY_ARTEFACT_TYPE, source_id=strategy.id, source_organization_id=source_organization_id,
        target_type=target_type, target_id=target_id, forward_name=forward_name, reverse_name=reverse_name,
        actor_id=actor_id,
    )


def create_strategy_supersession(
    db: Session, *, new_strategy: Strategy, old_strategy: Strategy, actor: User, comment: str | None = None,
) -> tuple[ArtefactLink, StrategyVersion]:
    """Records that `new_strategy` supersedes `old_strategy`: creates the
    typed `"Supersedes"` `ArtefactLink`, then transitions `old_strategy` to
    `SUPERSEDED` via the existing `supersede_strategy` (unchanged since
    Phase 1 — this is the deferred `ArtefactLink` side effect its own
    docstring promised a future Phase 6 pass would layer on top of it).
    Deliberately simpler than Decision Management's `create_supersession`:
    Strategy has no "flip only once the new one is already approved"
    condition to satisfy (`supersede_strategy`'s own `_ALLOWED_TRANSITIONS`
    check already requires `old_strategy` to currently be `ACTIVE`, which is
    sufficient validation on its own).

    Raises:
        ValueError: if `new_strategy`/`old_strategy` are the same row, are
            in different organisations, this exact supersession link
            already exists, or `old_strategy` isn't currently `ACTIVE`
            (raised by the underlying `supersede_strategy` call).
    """
    if new_strategy.id == old_strategy.id:
        raise ValueError("A Strategy cannot supersede itself.")
    new_org = _resolve_scope_organization_id(
        db, organization_id=new_strategy.organization_id, project_id=new_strategy.project_id
    )
    old_org = _resolve_scope_organization_id(
        db, organization_id=old_strategy.organization_id, project_id=old_strategy.project_id
    )
    if new_org != old_org:
        raise ValueError("A Strategy can only supersede another Strategy in the same organisation.")
    link_type = _get_or_create_cs_link_type(db, new_org, forward_name="Supersedes", reverse_name="Is superseded by")
    if (
        get_link_between(
            db, source_type=STRATEGY_ARTEFACT_TYPE, source_id=new_strategy.id,
            target_type=STRATEGY_ARTEFACT_TYPE, target_id=old_strategy.id, link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError("This Strategy already supersedes that one.")
    link = create_link(
        db, source_type=STRATEGY_ARTEFACT_TYPE, source_id=new_strategy.id,
        target_type=STRATEGY_ARTEFACT_TYPE, target_id=old_strategy.id,
        link_type_id=link_type.id, created_by=actor.id,
    )
    old_current_version = get_current_version(db, old_strategy.id)
    new_version = supersede_strategy(db, old_strategy, old_current_version, actor, comment=comment)
    return link, new_version


# --- Pain Point relationships (source overview §6.6) -------------------------


class PainPointLinkKind(str, enum.Enum):
    """Which of §6.6's Pain-Point-sourced relationship types `create_pain_
    point_link` should create. `ADDRESSES` (Decision -> addresses -> Pain
    Point) is the reserved Decision-target relationship (module docstring)
    and is not present here.

    `DUPLICATE_OF` is not one of §6.6's own named relationships — it closes
    a gap Phase 3's own notes explicitly flagged for this phase: `mark_
    pain_point_duplicate`'s mandatory comment names the canonical Pain
    Point in free text only ("standing in for the real `ArtefactLink`
    Phase 6 will add" — Phase 3 notes, `docs/plans/module-01-context-and-
    strategy-plan.md`), pending this phase's actual relationship
    infrastructure existing to record it for real."""

    DRIVES_STRATEGY = "drives_strategy"
    MOTIVATES_REQUIREMENT = "motivates_requirement"
    RAISES_OPEN_QUESTION = "raises_open_question"
    RELATED_TO_FUTURE_STATE = "related_to_future_state"
    DUPLICATE_OF = "duplicate_of"


_PAIN_POINT_LINK_SPECS: dict[PainPointLinkKind, tuple[str, str | None, str | None]] = {
    PainPointLinkKind.DRIVES_STRATEGY: (STRATEGY_ARTEFACT_TYPE, "Drives", "Is driven by"),
    PainPointLinkKind.MOTIVATES_REQUIREMENT: (ArtefactType.REQUIREMENT.value, "Motivates", "Is motivated by"),
    PainPointLinkKind.RAISES_OPEN_QUESTION: (OPEN_QUESTION_ARTEFACT_TYPE, "Raises", "Is raised by"),
    # `related to`: untyped — §6.6's own instruction to keep generic
    # association distinct from a causal/rationale-bearing typed link.
    PainPointLinkKind.RELATED_TO_FUTURE_STATE: (FUTURE_STATE_ARTEFACT_TYPE, None, None),
    PainPointLinkKind.DUPLICATE_OF: (PAIN_POINT_ARTEFACT_TYPE, "Duplicate of", "Is duplicated by"),
}


def create_pain_point_link(
    db: Session, *, pain_point: PainPoint, kind: PainPointLinkKind, target_id: uuid.UUID, actor_id: uuid.UUID,
) -> ArtefactLink:
    """Creates one of §6.6's Pain-Point-sourced relationships. `pain_point`
    is always project-scoped (its own only scope) and is the link's source;
    `target_id` is an id of whichever artefact type `kind` implies."""
    target_type, forward_name, reverse_name = _PAIN_POINT_LINK_SPECS[kind]
    source_organization_id = _resolve_scope_organization_id(db, organization_id=None, project_id=pain_point.project_id)
    return create_context_strategy_link(
        db, source_type=PAIN_POINT_ARTEFACT_TYPE, source_id=pain_point.id,
        source_organization_id=source_organization_id, target_type=target_type, target_id=target_id,
        forward_name=forward_name, reverse_name=reverse_name, actor_id=actor_id,
    )


# --- Guiding Principle relationships (source overview §8.5) ------------------


class GuidingPrincipleLinkKind(str, enum.Enum):
    """Which of §8.5's Guiding-Principle-sourced relationship types `create_
    guiding_principle_link` should create. `GUIDES_DECISION` (§8.5's
    "Decision -> guided by -> Guiding Principle") is the reserved
    Decision-target relationship (module docstring) and is not present
    here."""

    SUPPORTS_STRATEGY = "supports_strategy"
    INFORMS_REQUIREMENT = "informs_requirement"


_GUIDING_PRINCIPLE_LINK_SPECS: dict[GuidingPrincipleLinkKind, tuple[str, str | None, str | None]] = {
    GuidingPrincipleLinkKind.SUPPORTS_STRATEGY: (STRATEGY_ARTEFACT_TYPE, "Supports", "Is supported by"),
    GuidingPrincipleLinkKind.INFORMS_REQUIREMENT: (ArtefactType.REQUIREMENT.value, "Informs", "Is informed by"),
}


def create_guiding_principle_link(
    db: Session, *, guiding_principle: GuidingPrinciple, kind: GuidingPrincipleLinkKind, target_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> ArtefactLink:
    """Creates one of §8.5's Guiding-Principle-sourced relationships."""
    target_type, forward_name, reverse_name = _GUIDING_PRINCIPLE_LINK_SPECS[kind]
    source_organization_id = _resolve_scope_organization_id(
        db, organization_id=guiding_principle.organization_id, project_id=guiding_principle.project_id
    )
    return create_context_strategy_link(
        db, source_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, source_id=guiding_principle.id,
        source_organization_id=source_organization_id, target_type=target_type, target_id=target_id,
        forward_name=forward_name, reverse_name=reverse_name, actor_id=actor_id,
    )


def create_guiding_principle_supersession(
    db: Session, *, new_guiding_principle: GuidingPrinciple, old_guiding_principle: GuidingPrinciple, actor: User,
    comment: str | None = None,
) -> tuple[ArtefactLink, GuidingPrincipleVersion]:
    """Guiding Principle's own version of `create_strategy_supersession` —
    see that function's own docstring for the shared shape/reasoning.
    Reuses the same org-scoped `"Supersedes"` link-type row Strategy/Future
    State's own supersession functions use (keyed only on `(organization_id,
    forward_name)` — see `_get_or_create_cs_link_type`)."""
    if new_guiding_principle.id == old_guiding_principle.id:
        raise ValueError("A Guiding Principle cannot supersede itself.")
    new_org = _resolve_scope_organization_id(
        db, organization_id=new_guiding_principle.organization_id, project_id=new_guiding_principle.project_id
    )
    old_org = _resolve_scope_organization_id(
        db, organization_id=old_guiding_principle.organization_id, project_id=old_guiding_principle.project_id
    )
    if new_org != old_org:
        raise ValueError("A Guiding Principle can only supersede another Guiding Principle in the same organisation.")
    link_type = _get_or_create_cs_link_type(db, new_org, forward_name="Supersedes", reverse_name="Is superseded by")
    if (
        get_link_between(
            db, source_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, source_id=new_guiding_principle.id,
            target_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, target_id=old_guiding_principle.id,
            link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError("This Guiding Principle already supersedes that one.")
    link = create_link(
        db, source_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, source_id=new_guiding_principle.id,
        target_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, target_id=old_guiding_principle.id,
        link_type_id=link_type.id, created_by=actor.id,
    )
    old_current_version = get_current_guiding_principle_version(db, old_guiding_principle.id)
    new_version = supersede_guiding_principle(db, old_guiding_principle, old_current_version, actor, comment=comment)
    return link, new_version


# --- Future State relationships (source overview §7) -------------------------


class FutureStateLinkKind(str, enum.Enum):
    """Which of §7's Future-State-sourced relationships `create_future_
    state_link` should create — all untyped "linkable to" associations
    (§7's own wording is generic, unlike Strategy/Pain Point/Guiding
    Principle's specific causal verbs), per the typed/untyped split this
    module's docstring explains. `RELATED_TO_DECISION` (§7's "linkable to
    ... Decisions") is the reserved Decision-target relationship (module
    docstring) and is not present here. `RELATED_TO_STRATEGY` isn't present
    either — that relationship is `StrategyLinkKind.DEFINES_FUTURE_STATE`,
    built once from Strategy's own side (source overview §5.6's "Defines ->
    Future State"), not duplicated from both ends."""

    RELATED_TO_PAIN_POINT = "related_to_pain_point"
    RELATED_TO_REQUIREMENT = "related_to_requirement"
    RELATED_TO_GUIDING_PRINCIPLE = "related_to_guiding_principle"


_FUTURE_STATE_LINK_SPECS: dict[FutureStateLinkKind, tuple[str, str | None, str | None]] = {
    FutureStateLinkKind.RELATED_TO_PAIN_POINT: (PAIN_POINT_ARTEFACT_TYPE, None, None),
    FutureStateLinkKind.RELATED_TO_REQUIREMENT: (ArtefactType.REQUIREMENT.value, None, None),
    FutureStateLinkKind.RELATED_TO_GUIDING_PRINCIPLE: (GUIDING_PRINCIPLE_ARTEFACT_TYPE, None, None),
}


def create_future_state_link(
    db: Session, *, future_state: FutureState, kind: FutureStateLinkKind, target_id: uuid.UUID, actor_id: uuid.UUID,
) -> ArtefactLink:
    """Creates one of §7's Future-State-sourced relationships."""
    target_type, forward_name, reverse_name = _FUTURE_STATE_LINK_SPECS[kind]
    source_organization_id = _resolve_scope_organization_id(
        db, organization_id=future_state.organization_id, project_id=future_state.project_id
    )
    return create_context_strategy_link(
        db, source_type=FUTURE_STATE_ARTEFACT_TYPE, source_id=future_state.id,
        source_organization_id=source_organization_id, target_type=target_type, target_id=target_id,
        forward_name=forward_name, reverse_name=reverse_name, actor_id=actor_id,
    )


def create_future_state_supersession(
    db: Session, *, new_future_state: FutureState, old_future_state: FutureState, actor: User,
    comment: str | None = None,
) -> tuple[ArtefactLink, FutureStateVersion]:
    """Future State's own version of `create_strategy_supersession` — see
    that function's own docstring for the shared shape/reasoning."""
    if new_future_state.id == old_future_state.id:
        raise ValueError("A Future State cannot supersede itself.")
    new_org = _resolve_scope_organization_id(
        db, organization_id=new_future_state.organization_id, project_id=new_future_state.project_id
    )
    old_org = _resolve_scope_organization_id(
        db, organization_id=old_future_state.organization_id, project_id=old_future_state.project_id
    )
    if new_org != old_org:
        raise ValueError("A Future State can only supersede another Future State in the same organisation.")
    link_type = _get_or_create_cs_link_type(db, new_org, forward_name="Supersedes", reverse_name="Is superseded by")
    if (
        get_link_between(
            db, source_type=FUTURE_STATE_ARTEFACT_TYPE, source_id=new_future_state.id,
            target_type=FUTURE_STATE_ARTEFACT_TYPE, target_id=old_future_state.id, link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError("This Future State already supersedes that one.")
    link = create_link(
        db, source_type=FUTURE_STATE_ARTEFACT_TYPE, source_id=new_future_state.id,
        target_type=FUTURE_STATE_ARTEFACT_TYPE, target_id=old_future_state.id,
        link_type_id=link_type.id, created_by=actor.id,
    )
    old_current_version = get_current_future_state_version(db, old_future_state.id)
    new_version = supersede_future_state(db, old_future_state, old_current_version, actor, comment=comment)
    return link, new_version


# --- Open Question relationships (source overview §9.2) ----------------------


class OpenQuestionLinkKind(str, enum.Enum):
    """Which of §9.2's Open-Question-sourced "related" associations
    `create_open_question_link` should create — both untyped, matching
    §9.2's own plain "Related Strategy"/"Related Requirements" field
    naming (no causal verb, unlike Pain Point's own §6.6 relationships to
    this artefact). `RELATED_TO_PAIN_POINT` isn't present — that
    relationship is `PainPointLinkKind.RAISES_OPEN_QUESTION`, built once
    from Pain Point's own side (§6.6's "Raises -> Open Question"), not
    duplicated from both ends. `RESOLVED_BY_DECISION` (§9.5) is the
    reserved Decision-target relationship (module docstring) and is not
    present here."""

    RELATED_TO_STRATEGY = "related_to_strategy"
    RELATED_TO_REQUIREMENT = "related_to_requirement"


_OPEN_QUESTION_LINK_SPECS: dict[OpenQuestionLinkKind, tuple[str, str | None, str | None]] = {
    OpenQuestionLinkKind.RELATED_TO_STRATEGY: (STRATEGY_ARTEFACT_TYPE, None, None),
    OpenQuestionLinkKind.RELATED_TO_REQUIREMENT: (ArtefactType.REQUIREMENT.value, None, None),
}


def create_open_question_link(
    db: Session, *, open_question: OpenQuestion, kind: OpenQuestionLinkKind, target_id: uuid.UUID, actor_id: uuid.UUID,
) -> ArtefactLink:
    """Creates one of §9.2's Open-Question-sourced "related to"
    associations. `open_question` is always project-scoped (its own only
    scope) and is the link's source."""
    target_type, forward_name, reverse_name = _OPEN_QUESTION_LINK_SPECS[kind]
    source_organization_id = _resolve_scope_organization_id(
        db, organization_id=None, project_id=open_question.project_id
    )
    return create_context_strategy_link(
        db, source_type=OPEN_QUESTION_ARTEFACT_TYPE, source_id=open_question.id,
        source_organization_id=source_organization_id, target_type=target_type, target_id=target_id,
        forward_name=forward_name, reverse_name=reverse_name, actor_id=actor_id,
    )
