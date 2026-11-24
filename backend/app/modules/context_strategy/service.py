"""
Module: modules.context_strategy.service

Business logic for the five artefact types.
- Strategy, Future State, Guiding Principle: identity row plus temporal
  versions; each transition makes a version and an audit event.
- Pain Point, Open Question: no version table; branching state machines.
- Links use `services.relationships` (same-organisation boundary); Decision
  targets are not created here (module boundary).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType
from app.models.project import Project
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
from app.modules.registry import LinkTypeSeed
from app.schemas.principal import PrincipalRef
from app.services import approval_separation, definition_suppression
from app.services.audit import log_event
from app.services.lifecycles import check_move
from app.services.link_types import ensure_org_link_type
from app.services.rbac import lock_row_for_update
from app.services.relationships import create_link, get_link_between
from app.services.sequences import code_owner, generate_unique_code

# This module's artefact-type string, registered on
# `ModuleDefinition.artefact_types` (module.py).
STRATEGY_ARTEFACT_TYPE = "strategy"
STRATEGY_CODE_PREFIX = "STR"


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


def get_current_version_for_update(db: Session, strategy_id: uuid.UUID) -> StrategyVersion:
    """`get_current_version` after locking the Strategy row, for every path that
    writes a next version: a second concurrent edit waits for the first, then
    reads the version the first created instead of dying on the
    `(strategy_id, version_number)` unique constraint (see `lock_row_for_update`).
    The lock must precede the read, which is why the two are one call.

    Raises:
        ValueError: as `get_current_version`.
    """
    lock_row_for_update(db, Strategy, strategy_id)
    return get_current_version(db, strategy_id)


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
    """Creates a Strategy and its initial (version 1) content snapshot in
    `DRAFT` status (identity row plus version row; the caller commits).

    Args:
        organization_id: Always required; selects the identity column when
            `scope` is `ORGANIZATION`.
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
    """
    code_scope = code_owner(
        db, is_org_scope=scope == StrategyScope.ORGANIZATION, organization_id=organization_id, project_id=project_id
    )
    strategy = Strategy(
        scope=scope,
        organization_id=organization_id if scope == StrategyScope.ORGANIZATION else None,
        project_id=project_id if scope == StrategyScope.PROJECT else None,
        unique_code=generate_unique_code(db, code_scope, STRATEGY_ARTEFACT_TYPE, STRATEGY_CODE_PREFIX),
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
    strategy.updated_at = now  # a new version is a change to the record: its Modified time moves

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

# Legal `StrategyStatus` transitions: forward through the in-flight and active
# states; `PROPOSED`/`UNDER_REVIEW` can return to `DRAFT`, and
# `APPROVED`/`ACTIVE` can reach `RETIRED` directly.
_ALLOWED_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.DRAFT: frozenset({StrategyStatus.PROPOSED}),
    StrategyStatus.PROPOSED: frozenset({StrategyStatus.UNDER_REVIEW, StrategyStatus.DRAFT}),
    StrategyStatus.UNDER_REVIEW: frozenset({StrategyStatus.APPROVED, StrategyStatus.DRAFT}),
    StrategyStatus.APPROVED: frozenset({StrategyStatus.ACTIVE, StrategyStatus.RETIRED}),
    StrategyStatus.ACTIVE: frozenset({StrategyStatus.SUPERSEDED, StrategyStatus.RETIRED}),
    StrategyStatus.SUPERSEDED: frozenset(),
    StrategyStatus.RETIRED: frozenset(),
}

# Content is locked once past `UNDER_REVIEW`: only a lifecycle transition may
# create a new version afterwards.
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
    row (the full version-history model) rather than only mutating
    an identity-row column.

    Raises:
        ValueError: if `new_status` isn't reachable from `current_version.
            status` per `_ALLOWED_TRANSITIONS`.
    """
    check_move(
        db, strategy.project_id, STRATEGY_ARTEFACT_TYPE, current_version.status.value, new_status.value,
        record_id=strategy.id,
    )
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
    """`UNDER_REVIEW` -> `APPROVED`; applies the approval separation rule first (`services.approval_separation`)."""
    approval_separation.enforce_record_approval(
        db, user=actor, artefact_type=STRATEGY_ARTEFACT_TYPE, record=strategy, comment=comment,
    )
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
    unlike Decision Management's `create_supersession` — this function does
    not create a typed `ArtefactLink` recording *which* Strategy supersedes
    this one; `create_strategy_supersession` layers that on top of this same
    status transition without changing this function's own contract."""
    return _transition(db, strategy, current_version, StrategyStatus.SUPERSEDED, actor, action="superseded", comment=comment)


def retire_strategy(
    db: Session, strategy: Strategy, current_version: StrategyVersion, actor: User, *, comment: str | None = None
) -> StrategyVersion:
    """`APPROVED`/`ACTIVE` -> `RETIRED`."""
    return _transition(db, strategy, current_version, StrategyStatus.RETIRED, actor, action="retired", comment=comment)


# --- File-ownership resolution hook ----------------------------------------


def resolve_strategy_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project of the **project-scoped**
    Strategy it is attached to, directly (`StrategyFile`) or through a
    `StrategyComment` (`StrategyCommentFile`): this module's
    `ModuleDefinition.resolve_file_owner_project_id` hook. Organisation-scoped
    files are `is_org_resource` uploads authorised by membership, never
    resolved here.

    Returns:
        The owning project's id, or `None`.
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


# --- Future State -------------------------------------------------

# The second artefact-type string, registered on `ModuleDefinition.artefact_types`.
FUTURE_STATE_ARTEFACT_TYPE = "future_state"
FUTURE_STATE_CODE_PREFIX = "FUT"


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


def get_current_future_state_version_for_update(db: Session, future_state_id: uuid.UUID) -> FutureStateVersion:
    """Locking variant of `get_current_future_state_version`; see
    `get_current_version_for_update`.

    Raises:
        ValueError: as `get_current_future_state_version`.
    """
    lock_row_for_update(db, FutureState, future_state_id)
    return get_current_future_state_version(db, future_state_id)


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
    Future State field set (§7: no `objective`/`rationale`/
    `priority`/`time_horizon`, adds `target_date`/`outcomes`/
    `success_measures`/`assumptions`).

    Args:
        organization_id: Always required, same convention as
            `create_strategy` — only used to decide which identity column
            to populate when `scope` is `ORGANIZATION`.
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
    """
    code_scope = code_owner(
        db, is_org_scope=scope == FutureStateScope.ORGANIZATION, organization_id=organization_id, project_id=project_id
    )
    future_state = FutureState(
        scope=scope,
        organization_id=organization_id if scope == FutureStateScope.ORGANIZATION else None,
        project_id=project_id if scope == FutureStateScope.PROJECT else None,
        unique_code=generate_unique_code(db, code_scope, FUTURE_STATE_ARTEFACT_TYPE, FUTURE_STATE_CODE_PREFIX),
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
    future_state.updated_at = now  # a new version is a change to the record: its Modified time moves

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
    check_move(
        db, future_state.project_id, FUTURE_STATE_ARTEFACT_TYPE, current_version.status.value, new_status.value,
        record_id=future_state.id,
    )
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
    """`UNDER_REVIEW` -> `APPROVED`; applies the approval separation rule first (`services.approval_separation`)."""
    approval_separation.enforce_record_approval(
        db, user=actor, artefact_type=FUTURE_STATE_ARTEFACT_TYPE, record=future_state, comment=comment,
    )
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


# --- Pain Points ---------------------------------------------------

# The third artefact-type string, registered on `ModuleDefinition.artefact_types`;
# Pain Point is project-scoped only.
PAIN_POINT_ARTEFACT_TYPE = "pain_point"
PAIN_POINT_CODE_PREFIX = "PP"

# §6.2 default types, seeded once per organisation
# (`seed_default_pain_point_types`); a module-owned vocabulary, kept here.
DEFAULT_PAIN_POINT_TYPES: tuple[str, ...] = ("Market", "User", "Operator")


def seed_default_pain_point_types(db: Session, organization_id: uuid.UUID) -> None:
    """Adds the 3 default `PainPointTypeDefinition` rows (Market/User/
    Operator) for a newly created organisation. Not committed/flushed here
    — caller owns the transaction, mirroring `services.definitions.
    seed_link_types`'s identical convention."""
    for i, name in enumerate(DEFAULT_PAIN_POINT_TYPES):
        db.add(PainPointTypeDefinition(organization_id=organization_id, name=name, sort_order=i, is_active=True))


# --- Org-scoped Pain Point type vocabulary -----------------------------------


def clean_type_definition(definition: str | None) -> str | None:
    """Normalises a Pain Point type definition: surrounding whitespace is dropped and a blank value
    becomes `None` (no definition)."""
    if definition is None:
        return None
    return definition.strip() or None


def create_org_pain_point_type(
    db: Session, organization_id: uuid.UUID, name: str, definition: str | None = None
) -> PainPointTypeDefinition:
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
    pain_point_type = PainPointTypeDefinition(
        organization_id=organization_id, name=name, sort_order=count, definition=clean_type_definition(definition)
    )
    db.add(pain_point_type)
    db.flush()
    return pain_point_type


def delete_org_pain_point_type(db: Session, pain_point_type: PainPointTypeDefinition) -> None:
    """Deletes an organisation-scoped Pain Point type (§6.2). No reassignment
    is offered: projects across the organisation may reference it, so there
    is no single target. It is blocked while any project references it.

    Raises:
        ValueError: if any `ProjectPainPointType` row references this type.
    """
    in_use = db.scalar(
        select(ProjectPainPointType.id).where(ProjectPainPointType.org_type_id == pain_point_type.id).limit(1)
    )
    if in_use is not None:
        raise ValueError(
            "This Pain Point type is still referenced by at least one project and cannot be removed. "
            "Disable it instead, or ask each referencing project to stop using it first."
        )
    definition_suppression.forget_definition(db, PAIN_POINT_TYPE_KIND, pain_point_type.id)
    db.delete(pain_point_type)
    db.flush()


# --- Project-scoped Pain Point type resolution -------------------------------


@dataclass(frozen=True)
class EffectivePainPointType:
    """One row of a project's effective Pain Point type list, built by
    `resolve_effective_pain_point_types` (never stored).

    Attributes:
        id: A `PainPointTypeDefinition.id` (`source == "org"`) or a
            `ProjectPainPointType.id` (`"project_override"`/`"project_local"`);
            passed back as `pain_point_type_id` and resolved by
            `get_or_create_project_pain_point_type`.
        name: Effective display name.
        display_order: Effective picker order.
        is_enabled: Effective state; a disabled type is listed but rejected
            when selected.
        source: `"org"`, `"project_override"` or `"project_local"`.
        definition: The project's own text, else the organisation's, else `None`.
    """

    id: uuid.UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str
    definition: str | None = None


PAIN_POINT_TYPE_KIND = "pain_point_type"
definition_suppression.register_definition_kind(PAIN_POINT_TYPE_KIND)


def resolve_effective_pain_point_types(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID) -> list[EffectivePainPointType]:
    """Resolves a project's effective Pain Point type list:
    every active org type (using its project override's name/order/enabled
    state if one exists) plus every project-local type. Sorted by effective
    `display_order`.

    No `resolve_effective_action_types`-style parent/child project walk —
    per the nested-projects decision, an empty
    `ProjectPainPointType` table already means "use org defaults as-is,"
    which is a correct, self-contained empty-state reading requiring no
    further inheritance from a parent project.
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

    hidden = definition_suppression.get_suppressed_ids(db, project_id, PAIN_POINT_TYPE_KIND)

    effective: list[EffectivePainPointType] = []
    for org_type in org_types:
        if org_type.id in hidden:
            continue
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
                    definition=(
                        override.definition_override if override.definition_override is not None else org_type.definition
                    ),
                )
            )
        else:
            effective.append(
                EffectivePainPointType(
                    id=org_type.id, name=org_type.name, display_order=org_type.sort_order,
                    is_enabled=True, source="org", definition=org_type.definition,
                )
            )
    for row in local_rows:
        effective.append(
            EffectivePainPointType(
                id=row.id, name=row.name_override or "", display_order=row.display_order_override or 0,
                is_enabled=row.is_enabled, source="project_local", definition=row.definition_override,
            )
        )

    effective.sort(key=lambda e: e.display_order)
    return effective


def get_or_create_project_pain_point_type(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID
) -> ProjectPainPointType:
    """Resolves a type reference (an `EffectivePainPointType.id`) to a
    `ProjectPainPointType` row, lazily creating a passthrough row the first
    time an organisation type with no override is selected.

    Raises:
        ValueError: if `type_ref_id` is neither a `ProjectPainPointType` of
            this project nor an active type of this project's organisation.
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
    if org_type.id in definition_suppression.get_suppressed_ids(db, project_id, PAIN_POINT_TYPE_KIND):
        raise ValueError("This Pain Point type is hidden in this project.")

    passthrough = ProjectPainPointType(project_id=project_id, org_type_id=org_type.id, is_enabled=True)
    db.add(passthrough)
    db.flush()
    return passthrough


def hide_org_pain_point_type(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID
) -> PainPointTypeDefinition:
    """Hides an organisation Pain Point type in a project (see
    `TypeVocabulary.hide_org_type`, which this mirrors). `type_ref_id` is the
    org type id or the project's override row id for it; the override row is
    kept so Pain Points that use it are unaffected.

    Raises:
        ValueError: if the id is not an org-backed type of this project.
    """
    row = db.get(ProjectPainPointType, type_ref_id)
    org_type_id = row.org_type_id if row is not None and row.project_id == project_id else type_ref_id
    org_type = db.get(PainPointTypeDefinition, org_type_id) if org_type_id is not None else None
    if org_type is None or org_type.organization_id != organization_id:
        raise ValueError("This is not an organisation Pain Point type that can be hidden here.")
    definition_suppression.hide_definition(db, project_id, PAIN_POINT_TYPE_KIND, org_type.id)
    return org_type


def remove_pain_point_type(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID
) -> tuple[str, uuid.UUID]:
    """What "delete" means for a Pain Point type in a project: a project-local
    type is deleted (`delete_project_pain_point_type`); an organisation default
    (by org id or override row id) is hidden here (`hide_org_pain_point_type`).

    Returns:
        `("deleted", row id)` or `("hidden", org type id)`.

    Raises:
        LookupError: if the id is no type of this project.
        ValueError: if a local type is still in use.
    """
    row = db.get(ProjectPainPointType, type_ref_id)
    if row is not None and row.project_id == project_id and row.org_type_id is None:
        delete_project_pain_point_type(db, row)
        return "deleted", row.id
    try:
        return "hidden", hide_org_pain_point_type(db, project_id, organization_id, type_ref_id).id
    except ValueError as exc:
        raise LookupError(str(exc)) from exc


def list_hidden_pain_point_types(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[PainPointTypeDefinition]:
    """The organisation Pain Point types hidden in the project, in the organisation's order."""
    hidden = definition_suppression.get_suppressed_ids(db, project_id, PAIN_POINT_TYPE_KIND)
    if not hidden:
        return []
    return list(db.scalars(
        select(PainPointTypeDefinition)
        .where(PainPointTypeDefinition.organization_id == organization_id, PainPointTypeDefinition.id.in_(hidden))
        .order_by(PainPointTypeDefinition.sort_order)
    ).all())


def restore_hidden_pain_point_types(
    db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, org_type_ids: set[uuid.UUID] | None = None,
) -> list[PainPointTypeDefinition]:
    """Shows hidden organisation Pain Point types in the project again: all of
    them, or only `org_type_ids`. Returns the restored org types."""
    hidden = list_hidden_pain_point_types(db, project_id, organization_id)
    wanted = {t.id for t in hidden}
    if org_type_ids is not None:
        wanted &= org_type_ids
    restored = definition_suppression.restore_definitions(db, project_id, PAIN_POINT_TYPE_KIND, wanted)
    return [t for t in hidden if t.id in restored]


class _PainPointTypeHiding:
    """Adapts the Pain Point type functions to `services.type_vocabulary_routes.HideableVocabulary`."""

    label = "Pain Point type"

    @staticmethod
    def remove_type(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, type_ref_id: uuid.UUID):
        return remove_pain_point_type(db, project_id, organization_id, type_ref_id)

    @staticmethod
    def list_hidden(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID):
        return list_hidden_pain_point_types(db, project_id, organization_id)

    @staticmethod
    def restore_hidden(db: Session, project_id: uuid.UUID, organization_id: uuid.UUID, org_type_ids=None):
        return restore_hidden_pain_point_types(db, project_id, organization_id, org_type_ids)


PAIN_POINT_TYPE_HIDING = _PainPointTypeHiding()


def create_project_local_pain_point_type(
    db: Session, project_id: uuid.UUID, name: str, *, display_order: int | None = None, definition: str | None = None
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
        is_enabled=True, definition_override=clean_type_definition(definition),
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
    definition: str | None = None,
) -> ProjectPainPointType:
    """Applies a partial update to a `ProjectPainPointType` row — for an
    org-backed row (`org_type_id` set), this is a local override of the
    org type's name/order/enabled state/definition (§6.2 "Rename types"/"Reorder
    types"/"Disable types"); for a project-local row, these fields are its
    own primary name/order/enabled state/definition. Only the fields explicitly
    passed (non-`None`) are changed; a blank `definition` clears the project's
    text (an organisation type's own then shows again)."""
    if name is not None:
        project_pain_point_type.name_override = name
    if display_order is not None:
        project_pain_point_type.display_order_override = display_order
    if is_enabled is not None:
        project_pain_point_type.is_enabled = is_enabled
    if definition is not None:
        project_pain_point_type.definition_override = clean_type_definition(definition)
    db.flush()
    return project_pain_point_type


def delete_project_pain_point_type(db: Session, project_pain_point_type: ProjectPainPointType) -> None:
    """Deletes a project-scoped `ProjectPainPointType` row. A project-local
    row removes the type; an org-backed override row reverts the project to
    the organisation default. No reassignment is offered: a Pain Point's
    `pain_point_type_id` is NOT NULL, so removal is blocked while any Pain
    Point references the row (both cases alike).

    Raises:
        ValueError: if any `PainPoint.pain_point_type_id` references this row.
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
    project: Project,
    pain_point_type: ProjectPainPointType,
    creator: User,
    title: str,
    description: str = "",
    source: str = "",
    impact: str = "",
    evidence: str = "",
    priority: PainPointPriority = PainPointPriority.MEDIUM,
    date_identified: date | None = None,
    is_intentional: bool = False,
) -> PainPoint:
    """Creates a Pain Point in `SUBMITTED` status (any project member may
    create) with the project's next `PP-nnn` code.

    Args:
        project: The owning project (its sequence counter is advanced).
        pain_point_type: Already resolved via `get_or_create_project_pain_point_type`,
            so callers can validate `is_enabled` first.
        date_identified: Defaults to today if not supplied.
    """
    pain_point = PainPoint(
        project_id=project.id, pain_point_type_id=pain_point_type.id, creator_id=creator.id,
        unique_code=generate_unique_code(db, project, PAIN_POINT_ARTEFACT_TYPE, PAIN_POINT_CODE_PREFIX),
        title=title, description=description, source=source, impact=impact, evidence=evidence,
        priority=priority, status=PainPointStatus.SUBMITTED, is_intentional=is_intentional,
        date_identified=date_identified if date_identified is not None else date.today(),
    )
    db.add(pain_point)
    db.flush()
    return pain_point


def _owner_columns(owner: PrincipalRef | None) -> tuple[str | None, uuid.UUID | None]:
    """An owner principal as its `(owner_type, owner_id)` column values (both None when unowned)."""
    return (owner.type.value, owner.id) if owner else (None, None)


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
    owner: PrincipalRef | None = None,
    owner_explicitly_set: bool = False,
    date_identified: date | None = None,
    is_intentional: bool | None = None,
) -> PainPoint:
    """Mutates `pain_point`'s content fields directly (no version snapshot
    — see module docstring). Any field left `None` (and not explicitly
    flagged otherwise) is left unchanged.

    `owner` (a principal — the caller has validated it) follows the
    `target_date_explicitly_set` convention `apply_future_state_new_version`
    already uses for a nullable field — assigning `NULL` (unassigning an
    owner) must be distinguishable from "not mentioned in this call."
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
    if owner_explicitly_set:
        pain_point.owner_type, pain_point.owner_id = _owner_columns(owner)
    if date_identified is not None:
        pain_point.date_identified = date_identified
    if is_intentional is not None:
        pain_point.is_intentional = is_intentional
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

# Legal `PainPointStatus` transitions: `Submitted -> Triaged -> {Rejected |
# Duplicate | Accepted -> Addressed -> Closed}`; only `TRIAGED` branches.
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

# Content is locked at a terminal outcome (`REJECTED`/`DUPLICATE`/`CLOSED`);
# `ACCEPTED`/`ADDRESSED` stay editable so a manager can reassign the owner or
# adjust priority while work is in progress.
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
    check_move(
        db, pain_point.project_id, PAIN_POINT_ARTEFACT_TYPE, pain_point.status.value, new_status.value,
        record_id=pain_point.id,
    )
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
    """`TRIAGED` -> `DUPLICATE`. A comment is required — this function is deliberately just the status
    transition (§6.5's "Merge duplicates"); the mandatory comment is
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


# --- Guiding Principles --------------------------------------------

# This module's fourth artefact-type string, registered on `ModuleDefinition.
# artefact_types` (module.py) for the same reason `STRATEGY_ARTEFACT_TYPE` is.
GUIDING_PRINCIPLE_ARTEFACT_TYPE = "guiding_principle"
GUIDING_PRINCIPLE_CODE_PREFIX = "GP"


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


def get_current_guiding_principle_version_for_update(
    db: Session, guiding_principle_id: uuid.UUID
) -> GuidingPrincipleVersion:
    """Locking variant of `get_current_guiding_principle_version`; see
    `get_current_version_for_update`.

    Raises:
        ValueError: as `get_current_guiding_principle_version`.
    """
    lock_row_for_update(db, GuidingPrinciple, guiding_principle_id)
    return get_current_guiding_principle_version(db, guiding_principle_id)


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
    owner: PrincipalRef | None = None,
) -> GuidingPrinciple:
    """Creates a Guiding Principle and its initial (version 1) content
    snapshot, in `DRAFT` status (the `create_strategy` shape).

    Args:
        organization_id: Always required; selects the identity column when
            `scope` is `ORGANIZATION`.
        project_id: Required when `scope` is `PROJECT`, ignored otherwise.
        owner: The principal responsible (already validated), or None.
    """
    code_scope = code_owner(
        db, is_org_scope=scope == GuidingPrincipleScope.ORGANIZATION, organization_id=organization_id, project_id=project_id
    )
    guiding_principle = GuidingPrinciple(
        scope=scope,
        organization_id=organization_id if scope == GuidingPrincipleScope.ORGANIZATION else None,
        project_id=project_id if scope == GuidingPrincipleScope.PROJECT else None,
        unique_code=generate_unique_code(db, code_scope, GUIDING_PRINCIPLE_ARTEFACT_TYPE, GUIDING_PRINCIPLE_CODE_PREFIX),
        creator_id=creator.id,
    )
    db.add(guiding_principle)
    db.flush()

    now = datetime.now(UTC)
    version = GuidingPrincipleVersion(
        guiding_principle_id=guiding_principle.id, version_number=1, valid_from=now, valid_to=None,
        name=name, principle_statement=principle_statement, rationale=rationale, priority=priority,
        status=GuidingPrincipleStatus.DRAFT, owner_type=owner.type.value if owner else None,
        owner_id=owner.id if owner else None, change_note="Initial creation.",
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
    owner: PrincipalRef | None = None,
    owner_explicitly_set: bool = False,
    status_value: GuidingPrincipleStatus | None = None,
    change_note: str = "",
) -> GuidingPrincipleVersion:
    """Closes `current_version` and inserts a new one, carrying forward any
    field left unspecified — exact mirror of `apply_new_version`/`apply_
    future_state_new_version`.

    `owner` (a principal — the caller has validated it) is nullable (a
    Guiding Principle may have no assigned owner), so — mirroring
    `apply_future_state_new_version`'s `target_date`/`target_date_explicitly_set`
    pair — it gets its own `owner_explicitly_set` flag to disambiguate
    "unassign the owner" (`owner=None`, flag `True`) from "leave it
    unchanged" (flag stays `False`).
    """
    now = datetime.now(UTC)
    current_version.valid_to = now
    guiding_principle.updated_at = now  # a new version is a change to the record: its Modified time moves
    owner_type, owner_id = (
        _owner_columns(owner) if owner_explicitly_set else (current_version.owner_type, current_version.owner_id)
    )

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
        owner_type=owner_type,
        owner_id=owner_id,
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


# Legal `GuidingPrincipleStatus` transitions: a linear chain with no
# `UNDER_REVIEW` step; `PROPOSED` goes to `APPROVED` or back to `DRAFT`,
# `APPROVED`/`ACTIVE` can reach `RETIRED`, `ACTIVE` can reach `SUPERSEDED`.
_GP_ALLOWED_TRANSITIONS: dict[GuidingPrincipleStatus, frozenset[GuidingPrincipleStatus]] = {
    GuidingPrincipleStatus.DRAFT: frozenset({GuidingPrincipleStatus.PROPOSED}),
    GuidingPrincipleStatus.PROPOSED: frozenset({GuidingPrincipleStatus.APPROVED, GuidingPrincipleStatus.DRAFT}),
    GuidingPrincipleStatus.APPROVED: frozenset({GuidingPrincipleStatus.ACTIVE, GuidingPrincipleStatus.RETIRED}),
    GuidingPrincipleStatus.ACTIVE: frozenset({GuidingPrincipleStatus.SUPERSEDED, GuidingPrincipleStatus.RETIRED}),
    GuidingPrincipleStatus.SUPERSEDED: frozenset(),
    GuidingPrincipleStatus.RETIRED: frozenset(),
}

# Content is locked once past `PROPOSED` (`APPROVED` and beyond); the lifecycle
# has no `UNDER_REVIEW` state.
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
    check_move(
        db, guiding_principle.project_id, GUIDING_PRINCIPLE_ARTEFACT_TYPE, current_version.status.value,
        new_status.value, record_id=guiding_principle.id,
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
    """`PROPOSED` -> `APPROVED`; applies the approval separation rule first (`services.approval_separation`)."""
    approval_separation.enforce_record_approval(
        db, user=actor, artefact_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, record=guiding_principle, comment=comment,
    )
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
    supersedes this one (a typed `ArtefactLink`) is
    `create_guiding_principle_supersession`'s job."""
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


# --- Open Questions -------------------------------------------------

# The fifth artefact-type string, registered on `ModuleDefinition.artefact_types`;
# Open Question is project-scoped only.
OPEN_QUESTION_ARTEFACT_TYPE = "open_question"
OPEN_QUESTION_CODE_PREFIX = "OQ"


def create_open_question(
    db: Session,
    *,
    project: Project,
    creator: User,
    question: str,
    context: str = "",
    evidence: str = "",
    priority: OpenQuestionPriority = OpenQuestionPriority.MEDIUM,
    due_date: date | None = None,
) -> OpenQuestion:
    """Creates an Open Question in `OPEN` status (§9.4's broad-creation
    model — any project member, not just an `open_question_owner`), with the
    project's next `OQ-nnn` code."""
    open_question = OpenQuestion(
        project_id=project.id, creator_id=creator.id,
        unique_code=generate_unique_code(db, project, OPEN_QUESTION_ARTEFACT_TYPE, OPEN_QUESTION_CODE_PREFIX),
        question=question, context=context, evidence=evidence, priority=priority, status=OpenQuestionStatus.OPEN, due_date=due_date,
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
    owner: PrincipalRef | None = None,
    owner_explicitly_set: bool = False,
    due_date: date | None = None,
    due_date_explicitly_set: bool = False,
) -> OpenQuestion:
    """Mutates `open_question`'s content fields directly (no version
    snapshot — see module docstring). Any field left `None` (and not
    explicitly flagged otherwise) is left unchanged.

    `owner`/`due_date` are both nullable, so — mirroring `update_pain_
    point`'s `owner`/`owner_explicitly_set` pair and `apply_future_
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
    if owner_explicitly_set:
        open_question.owner_type, open_question.owner_id = _owner_columns(owner)
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

# Legal `OpenQuestionStatus` transitions: `Open -> Investigating ->
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

# Content is locked at a terminal outcome (`RESOLVED`/`WITHDRAWN`);
# `INVESTIGATING`/`READY_FOR_DECISION` stay editable so an owner can reassign
# or adjust priority and due date while work continues.
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
    check_move(
        db, open_question.project_id, OPEN_QUESTION_ARTEFACT_TYPE, open_question.status.value, new_status.value,
        record_id=open_question.id,
    )
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


# --- cross-artefact relationships ----------------------------------
# A typed relationship name is created lazily as an org-shared
# `RequirementLinkTypeDefinition`; an untyped one has `link_type_id=None`.


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
    """Resolves a relationship target's owning organisation (core
    `Requirement` or one of this module's five types) so
    `create_context_strategy_link` can check it exists and shares the source's
    organisation. Decision ids are not resolved here (module boundary).

    Raises:
        ValueError: if `target_id` doesn't resolve to a row of `target_type`,
            or `target_type` is not resolvable.
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
    """This organisation's link type identified by `forward_name`, created on
    first use from the registered seed (`services.link_types.ensure_org_link_type`;
    `reverse_name` is the fallback phrase for an unseeded name)."""
    return ensure_org_link_type(db, organization_id, forward_name, reverse_name)


def create_context_strategy_link(
    db: Session, *, source_type: str, source_id: uuid.UUID, source_organization_id: uuid.UUID,
    target_type: str, target_id: uuid.UUID, forward_name: str | None, reverse_name: str | None,
    actor_id: uuid.UUID, project_id: uuid.UUID | None = None,
) -> ArtefactLink:
    """The single relationship-creation dispatcher every `create_<source>_link`
    wrapper calls.

    Args:
        source_type / source_id: The link's source, already resolved and
            authorised by the caller.
        source_organization_id: The source's owning organisation, compared
            with the target's.
        target_type / target_id: The link's target artefact.
        forward_name / reverse_name: The `RequirementLinkTypeDefinition` name
            pair for a typed relationship, or both `None` for an untyped
            "related to" association.
        actor_id: The user recording the relationship.
        project_id: The source's project (`None` for an organisation-scoped
            source), so project and ancestor artefact-type link rules apply.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if source and target are the same artefact, the target
            is missing or in another organisation, or the relationship exists.
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
        link_type_id=link_type_id, created_by=actor_id, project_id=project_id,
    )


# --- Strategy relationships (§5.6) --------------------------


class StrategyLinkKind(str, enum.Enum):
    """Which Strategy-sourced relationship `create_strategy_link` creates.
    `DRIVES_REQUIREMENT` reuses the `"Drives"` link-type name of
    `PainPointLinkKind.DRIVES_STRATEGY`: both express the same causal concept
    one level apart. `INFORMS_DECISION` is reserved (Decision targets are not
    created here); "guided by Guiding Principle" is built from the Guiding
    Principle side (`GuidingPrincipleLinkKind.SUPPORTS_STRATEGY`)."""

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
        project_id=strategy.project_id,
    )


def create_strategy_supersession(
    db: Session, *, new_strategy: Strategy, old_strategy: Strategy, actor: User, comment: str | None = None,
) -> tuple[ArtefactLink, StrategyVersion]:
    """Records that `new_strategy` supersedes `old_strategy`: creates the typed
    `"Supersedes"` `ArtefactLink`, then transitions `old_strategy` to
    `SUPERSEDED` via `supersede_strategy` (which requires it to be `ACTIVE`).

    Raises:
        ValueError: if the strategies are the same row or in different
            organisations, the link already exists, or `old_strategy` isn't
            currently `ACTIVE`.
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
        link_type_id=link_type.id, created_by=actor.id, enforce_rules=False,  # fixed-semantic lifecycle step
    )
    old_current_version = get_current_version_for_update(db, old_strategy.id)
    new_version = supersede_strategy(db, old_strategy, old_current_version, actor, comment=comment)
    return link, new_version


# --- Pain Point relationships (§6.6) -------------------------


class PainPointLinkKind(str, enum.Enum):
    """Which of §6.6's Pain-Point-sourced relationship types `create_pain_
    point_link` should create. `ADDRESSES` (Decision -> addresses -> Pain
    Point) is the reserved Decision-target relationship (module docstring)
    and is not present here.

    `DUPLICATE_OF` is not one of §6.6's own named relationships — it records
    the canonical Pain Point as a real `ArtefactLink`, which
    `mark_pain_point_duplicate`'s mandatory comment otherwise names only in
    free text."""

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
        project_id=pain_point.project_id,
    )


# --- Guiding Principle relationships (§8.5) ------------------


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
        project_id=guiding_principle.project_id,
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
        link_type_id=link_type.id, created_by=actor.id, enforce_rules=False,  # fixed-semantic lifecycle step
    )
    old_current_version = get_current_guiding_principle_version_for_update(db, old_guiding_principle.id)
    new_version = supersede_guiding_principle(db, old_guiding_principle, old_current_version, actor, comment=comment)
    return link, new_version


# --- Future State relationships (§7) -------------------------


class FutureStateLinkKind(str, enum.Enum):
    """Which of §7's Future-State-sourced relationships `create_future_
    state_link` should create — all untyped "linkable to" associations
    (§7's own wording is generic, unlike Strategy/Pain Point/Guiding
    Principle's specific causal verbs), per the typed/untyped split this
    module's docstring explains. `RELATED_TO_DECISION` (§7's "linkable to
    ... Decisions") is the reserved Decision-target relationship (module
    docstring) and is not present here. `RELATED_TO_STRATEGY` isn't present
    either — that relationship is `StrategyLinkKind.DEFINES_FUTURE_STATE`,
    built once from Strategy's own side (§5.6's "Defines ->
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
        project_id=future_state.project_id,
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
        link_type_id=link_type.id, created_by=actor.id, enforce_rules=False,  # fixed-semantic lifecycle step
    )
    old_current_version = get_current_future_state_version_for_update(db, old_future_state.id)
    new_version = supersede_future_state(db, old_future_state, old_current_version, actor, comment=comment)
    return link, new_version


# --- Open Question relationships (§9.2) ----------------------


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
        project_id=open_question.project_id,
    )


def _build_link_type_seeds() -> tuple[LinkTypeSeed, ...]:
    """The link types the typed relationship kinds above use, as registry seeds
    (`ModuleDefinition.link_type_seeds`), derived from the kind tables so the
    vocabulary has one definition. Each kind's source and target type become
    the seed's restriction; the registry unions seeds sharing a forward name
    ("Drives" runs Pain Point -> Strategy and Strategy -> Requirement). The
    "Supersedes" type is dedicated: its links flip a status through the
    supersession endpoints, not the generic link ones."""
    seeds: list[LinkTypeSeed] = []
    by_source = (
        (STRATEGY_ARTEFACT_TYPE, _STRATEGY_LINK_SPECS),
        (PAIN_POINT_ARTEFACT_TYPE, _PAIN_POINT_LINK_SPECS),
        (GUIDING_PRINCIPLE_ARTEFACT_TYPE, _GUIDING_PRINCIPLE_LINK_SPECS),
        (FUTURE_STATE_ARTEFACT_TYPE, _FUTURE_STATE_LINK_SPECS),
        (OPEN_QUESTION_ARTEFACT_TYPE, _OPEN_QUESTION_LINK_SPECS),
    )
    for source_type, specs in by_source:
        for target_type, forward, reverse in specs.values():
            if forward is None:  # untyped association: no link type
                continue
            seeds.append(
                LinkTypeSeed(
                    forward_name=forward, reverse_name=reverse or forward,
                    allowed_source_types=(source_type,), allowed_target_types=(target_type,),
                )
            )
    for artefact_type in (STRATEGY_ARTEFACT_TYPE, FUTURE_STATE_ARTEFACT_TYPE, GUIDING_PRINCIPLE_ARTEFACT_TYPE):
        seeds.append(
            LinkTypeSeed(
                forward_name="Supersedes", reverse_name="Is superseded by",
                allowed_source_types=(artefact_type,), allowed_target_types=(artefact_type,), dedicated_endpoint=True,
            )
        )
    return tuple(seeds)


LINK_TYPE_SEEDS: tuple[LinkTypeSeed, ...] = _build_link_type_seeds()
