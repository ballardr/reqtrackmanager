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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.modules.context_strategy.enums import (
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    Strategy,
    StrategyComment,
    StrategyCommentFile,
    StrategyFile,
    StrategyVersion,
)
from app.services.audit import log_event

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
