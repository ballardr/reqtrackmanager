"""
Module: modules.context_strategy.edits

The list queries and create / edit paths of Context & Strategy's five record types, shared by the HTTP
endpoints (`project_router`, and `router` for the organisation's own records) and the record-table export and
import (`record_tables`) so a filter or rule added here reaches both.

Responsibilities:
- Select a project's Strategies, Future States, Guiding Principles, Pain Points or Open Questions the way the
  list endpoint does (own project, project scope, archived only when asked, oldest first), and the
  organisation's own Strategies, Future States and Guiding Principles the same way.
- Create a Strategy, Future State, Guiding Principle (a project's or the organisation's, named by a
  `RecordOwner`) or a Pain Point or Open Question (a project's) with its principal validation, and record the
  `created` audit event.
- Edit one in place with the checks the edit endpoint makes (the content lock past review, the closed
  lifecycle of a Pain Point and an Open Question, the principal check, the version lock row), and record the
  `updated` audit event.

Design decisions:
- Strategy, Future State and Guiding Principle live at two tiers, so their paths take a `RecordOwner` (the
  `*_project_*` names are the project wrappers the project endpoints and the import use); the rules about the
  record's own state are the same at both.
- Nothing here commits and nothing here checks who may do it: the caller owns the transaction and the role
  gate (the endpoint's `require_*_manage_role`, the import's `can_update`), because the gates differ by caller
  context while the rules about the record's own state do not.
- A refusal is an `HTTPException` (409 for a locked record, 400 for an unusable Pain Point type), the shape the
  endpoints already answered with and the import turns into that row's error.
- Edits mirror the underlying `service` functions' "left `None` means unchanged" convention; a nullable field
  (an owner, a target date, a due date) is changed only when its `*_explicitly_set` flag is true.

Dependencies: `modules.context_strategy.service` (the create / version / update functions),
`services.principals`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy.enums import (
    FutureStateScope,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    OpenQuestionPriority,
    PainPointPriority,
    StrategyPriority,
    StrategyScope,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    FutureState,
    GuidingPrinciple,
    OpenQuestion,
    PainPoint,
    ProjectPainPointType,
    Strategy,
)
from app.modules.context_strategy.pain_point_scores import (
    ScoreEntryInput,
    ScoringContext,
    list_pain_point_scores,
    set_pain_point_scores,
)
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    OPEN_QUESTION_ARTEFACT_TYPE,
    PAIN_POINT_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
    apply_future_state_new_version,
    apply_guiding_principle_new_version,
    apply_new_version,
    create_future_state,
    create_guiding_principle,
    create_open_question,
    create_pain_point,
    create_strategy,
    get_current_future_state_version_for_update,
    get_current_guiding_principle_version_for_update,
    get_current_version_for_update,
    get_or_create_project_pain_point_type,
    is_future_state_locked,
    is_guiding_principle_locked,
    is_locked,
    is_open_question_locked,
    is_pain_point_locked,
    update_open_question,
    update_pain_point,
)
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.principals import validate_principal

STRATEGY_LOCKED = "This Strategy is past review; its content can no longer be edited in place."
FUTURE_STATE_LOCKED = "This Future State is past review; its content can no longer be edited in place."
GUIDING_PRINCIPLE_LOCKED = "This Guiding Principle is past review; its content can no longer be edited in place."
PAIN_POINT_LOCKED = "This Pain Point has reached a terminal outcome; its content can no longer be edited."
PAIN_POINT_SCORES_LOCKED = "This Pain Point has reached a terminal outcome; its scores can no longer be edited."
PAIN_POINT_SCORED_PER_PERSONA = "This Pain Point is scored per persona; edit its scores on the Pain Point page."
OPEN_QUESTION_LOCKED = "This Open Question has reached a terminal outcome; its content can no longer be edited."


@dataclass(frozen=True)
class RecordOwner:
    """Who owns a record being created or edited: a project, or (without `project_id`) the organisation itself.

    Attributes:
        organization_id: The owning organisation (also the project's organisation).
        project_id: The owning project, or `None` for an organisation-owned record.
    """

    organization_id: uuid.UUID
    project_id: uuid.UUID | None = None

    @classmethod
    def of_project(cls, project: Project) -> RecordOwner:
        """The owner of a project's own record."""
        return cls(project.organization_id, project.id)

    @property
    def is_project(self) -> bool:
        return self.project_id is not None

    @property
    def audit(self) -> dict[str, uuid.UUID]:
        """The audit-event field that places the record: its project, or its organisation."""
        return {"project_id": self.project_id} if self.project_id is not None else {"organization_id": self.organization_id}


def _locked(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _project_rows(db: Session, model: Any, project_id: uuid.UUID, include_archived: bool, scoped: Any = None) -> list[Any]:
    """`model`'s rows of one project, oldest first, archived ones only when asked (`scoped`: an extra criterion)."""
    query = select(model).where(model.project_id == project_id)
    if scoped is not None:
        query = query.where(scoped)
    if not include_archived:
        query = query.where(model.is_archived.is_(False))
    return list(db.scalars(query.order_by(model.created_at)).all())


def _organization_rows(db: Session, model: Any, organization_id: uuid.UUID, include_archived: bool, scoped: Any) -> list[Any]:
    """`model`'s rows the organisation itself owns (`scoped`: the scope criterion), oldest first, archived ones only when asked."""
    query = select(model).where(model.organization_id == organization_id, scoped)
    if not include_archived:
        query = query.where(model.is_archived.is_(False))
    return list(db.scalars(query.order_by(model.created_at)).all())


def organization_strategies(db: Session, organization_id: uuid.UUID, include_archived: bool = False) -> list[Strategy]:
    """The organisation's own Strategies, as the organisation list endpoint selects them."""
    return _organization_rows(db, Strategy, organization_id, include_archived, Strategy.scope == StrategyScope.ORGANIZATION)


def organization_future_states(db: Session, organization_id: uuid.UUID, include_archived: bool = False) -> list[FutureState]:
    """The organisation's own Future States, as the organisation list endpoint selects them."""
    return _organization_rows(db, FutureState, organization_id, include_archived, FutureState.scope == FutureStateScope.ORGANIZATION)


def organization_guiding_principles(db: Session, organization_id: uuid.UUID, include_archived: bool = False) -> list[GuidingPrinciple]:
    """The organisation's own Guiding Principles, as the organisation list endpoint selects them."""
    return _organization_rows(
        db, GuidingPrinciple, organization_id, include_archived, GuidingPrinciple.scope == GuidingPrincipleScope.ORGANIZATION
    )


def project_strategies(db: Session, project_id: uuid.UUID, include_archived: bool = False) -> list[Strategy]:
    """The project's own (not organisation) Strategies, as the list endpoint selects them."""
    return _project_rows(db, Strategy, project_id, include_archived, Strategy.scope == StrategyScope.PROJECT)


def project_future_states(db: Session, project_id: uuid.UUID, include_archived: bool = False) -> list[FutureState]:
    """The project's own Future States, as the list endpoint selects them."""
    return _project_rows(db, FutureState, project_id, include_archived, FutureState.scope == FutureStateScope.PROJECT)


def project_guiding_principles(db: Session, project_id: uuid.UUID, include_archived: bool = False) -> list[GuidingPrinciple]:
    """The project's own Guiding Principles, as the list endpoint selects them."""
    return _project_rows(
        db, GuidingPrinciple, project_id, include_archived, GuidingPrinciple.scope == GuidingPrincipleScope.PROJECT
    )


def project_pain_points(db: Session, project_id: uuid.UUID, include_archived: bool = False) -> list[PainPoint]:
    """The project's Pain Points, as the list endpoint selects them."""
    return _project_rows(db, PainPoint, project_id, include_archived)


def project_open_questions(db: Session, project_id: uuid.UUID, include_archived: bool = False) -> list[OpenQuestion]:
    """The project's Open Questions, as the list endpoint selects them."""
    return _project_rows(db, OpenQuestion, project_id, include_archived)


# --- Strategy ----------------------------------------------------------------------------------------------------


def create_strategy_record(
    db: Session, holder: RecordOwner, creator: User, *, title: str, objective: str, current_state: str = "",
    desired_future_state: str = "", rationale: str = "", expected_outcomes: str = "", constraints: str = "",
    measures_of_success: str = "", priority: StrategyPriority = StrategyPriority.MEDIUM,
    time_horizon: StrategyTimeHorizon = StrategyTimeHorizon.MEDIUM_TERM,
) -> Strategy:
    """Creates a Strategy in `DRAFT` status and records the `created` event.

    Args:
        db: Active session; the caller commits.
        holder: The owning project, or the organisation itself.
        creator: The actor.
        title: Strategy title.
        objective: Strategy objective.
        current_state / desired_future_state / rationale / expected_outcomes / constraints / measures_of_success:
            The remaining text fields.
        priority: Strategy priority.
        time_horizon: Strategy time horizon.

    Returns:
        The new Strategy (flushed, not committed).
    """
    strategy = create_strategy(
        db, scope=StrategyScope.PROJECT if holder.is_project else StrategyScope.ORGANIZATION,
        organization_id=holder.organization_id, project_id=holder.project_id, creator=creator,
        title=title, objective=objective, current_state=current_state, desired_future_state=desired_future_state,
        rationale=rationale, expected_outcomes=expected_outcomes, constraints=constraints,
        measures_of_success=measures_of_success, priority=priority, time_horizon=time_horizon,
    )
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="created",
              actor_id=creator.id, detail={"title": title}, **holder.audit)
    return strategy


def edit_strategy_record(db: Session, holder: RecordOwner, strategy: Strategy, actor: User, **fields: Any) -> None:
    """Writes a new Strategy version with `fields` (any of `apply_new_version`'s content fields and `change_note`).

    Raises:
        HTTPException: 409 once the current version is past review.
    """
    current_version = get_current_version_for_update(db, strategy.id)
    if is_locked(current_version):
        raise _locked(STRATEGY_LOCKED)
    apply_new_version(db, strategy, current_version, actor, **fields)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="updated",
              actor_id=actor.id, **holder.audit)


def create_project_strategy_record(db: Session, project: Project, creator: User, **fields: Any) -> Strategy:
    """`create_strategy_record` for a project's own Strategy."""
    return create_strategy_record(db, RecordOwner.of_project(project), creator, **fields)


def edit_project_strategy_record(db: Session, project: Project, strategy: Strategy, actor: User, **fields: Any) -> None:
    """`edit_strategy_record` for a project's own Strategy."""
    edit_strategy_record(db, RecordOwner.of_project(project), strategy, actor, **fields)


# --- Future State ------------------------------------------------------------------------------------------------


def create_future_state_record(
    db: Session, holder: RecordOwner, creator: User, *, title: str, current_state: str = "", desired_state: str = "",
    target_date: date | None = None, outcomes: str = "", success_measures: str = "", constraints: str = "",
    assumptions: str = "",
) -> FutureState:
    """Creates a Future State in `DRAFT` status (a project's or the organisation's) and records the `created` event."""
    future_state = create_future_state(
        db, scope=FutureStateScope.PROJECT if holder.is_project else FutureStateScope.ORGANIZATION,
        organization_id=holder.organization_id, project_id=holder.project_id,
        creator=creator, title=title, current_state=current_state, desired_state=desired_state,
        target_date=target_date, outcomes=outcomes, success_measures=success_measures, constraints=constraints,
        assumptions=assumptions,
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="created",
              actor_id=creator.id, detail={"title": title}, **holder.audit)
    return future_state


def edit_future_state_record(db: Session, holder: RecordOwner, future_state: FutureState, actor: User, **fields: Any) -> None:
    """Writes a new Future State version with `fields` (see `apply_future_state_new_version`).

    Raises:
        HTTPException: 409 once the current version is past review.
    """
    current_version = get_current_future_state_version_for_update(db, future_state.id)
    if is_future_state_locked(current_version):
        raise _locked(FUTURE_STATE_LOCKED)
    apply_future_state_new_version(db, future_state, current_version, actor, **fields)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="updated",
              actor_id=actor.id, **holder.audit)


def create_project_future_state_record(db: Session, project: Project, creator: User, **fields: Any) -> FutureState:
    """`create_future_state_record` for a project's own Future State."""
    return create_future_state_record(db, RecordOwner.of_project(project), creator, **fields)


def edit_project_future_state_record(db: Session, project: Project, future_state: FutureState, actor: User, **fields: Any) -> None:
    """`edit_future_state_record` for a project's own Future State."""
    edit_future_state_record(db, RecordOwner.of_project(project), future_state, actor, **fields)


# --- Guiding Principle -------------------------------------------------------------------------------------------


def create_guiding_principle_record(
    db: Session, holder: RecordOwner, creator: User, *, name: str, principle_statement: str, rationale: str = "",
    priority: GuidingPrinciplePriority = GuidingPrinciplePriority.MEDIUM, owner: PrincipalRef | None = None,
) -> GuidingPrinciple:
    """Creates a Guiding Principle in `DRAFT` status (a project's or the organisation's) and records the `created` event.

    `owner` is the principle's accountable owner (a user or group); `holder` places the record.

    Raises:
        HTTPException: 4xx when `owner` is not a principal the owner's tier may use.
    """
    validate_principal(db, owner, organization_id=holder.organization_id, project_id=holder.project_id, field="owner")
    guiding_principle = create_guiding_principle(
        db, scope=GuidingPrincipleScope.PROJECT if holder.is_project else GuidingPrincipleScope.ORGANIZATION,
        organization_id=holder.organization_id, project_id=holder.project_id,
        creator=creator, name=name, principle_statement=principle_statement, rationale=rationale, priority=priority,
        owner=owner,
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="created",
              actor_id=creator.id, detail={"name": name}, **holder.audit)
    return guiding_principle


def edit_guiding_principle_record(
    db: Session, holder: RecordOwner, guiding_principle: GuidingPrinciple, actor: User, **fields: Any
) -> None:
    """Writes a new Guiding Principle version with `fields` (see `apply_guiding_principle_new_version`).

    Raises:
        HTTPException: 409 once the current version is past review; 4xx for an unusable owner.
    """
    current_version = get_current_guiding_principle_version_for_update(db, guiding_principle.id)
    if is_guiding_principle_locked(current_version):
        raise _locked(GUIDING_PRINCIPLE_LOCKED)
    if fields.get("owner_explicitly_set"):
        validate_principal(
            db, fields.get("owner"), organization_id=holder.organization_id, project_id=holder.project_id, field="owner",
        )
    apply_guiding_principle_new_version(db, guiding_principle, current_version, actor, **fields)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="updated",
              actor_id=actor.id, **holder.audit)


def create_project_guiding_principle_record(db: Session, project: Project, creator: User, **fields: Any) -> GuidingPrinciple:
    """`create_guiding_principle_record` for a project's own Guiding Principle."""
    return create_guiding_principle_record(db, RecordOwner.of_project(project), creator, **fields)


def edit_project_guiding_principle_record(
    db: Session, project: Project, guiding_principle: GuidingPrinciple, actor: User, **fields: Any
) -> None:
    """`edit_guiding_principle_record` for a project's own Guiding Principle."""
    edit_guiding_principle_record(db, RecordOwner.of_project(project), guiding_principle, actor, **fields)


# --- Pain Point --------------------------------------------------------------------------------------------------


def resolve_usable_pain_point_type(db: Session, project: Project, type_ref_id: uuid.UUID) -> ProjectPainPointType:
    """The project's Pain Point type for an effective-type id, which must be enabled.

    Raises:
        HTTPException: 400 when the id is not a type this project can use or the type is disabled.
    """
    try:
        pain_point_type = get_or_create_project_pain_point_type(db, project.id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not pain_point_type.is_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Pain Point type is disabled for this project.")
    return pain_point_type


def create_project_pain_point_record(
    db: Session, project: Project, creator: User, pain_point_type: ProjectPainPointType, *, title: str,
    description: str = "", source: str = "", impact: str = "", evidence: str = "",
    priority: PainPointPriority = PainPointPriority.MEDIUM, date_identified: date | None = None,
    is_intentional: bool = False,
) -> PainPoint:
    """Creates a Pain Point in `SUBMITTED` status (`pain_point_type` from `resolve_usable_pain_point_type`)
    and records the `created` event."""
    pain_point = create_pain_point(
        db, project=project, pain_point_type=pain_point_type, creator=creator, title=title, description=description,
        source=source, impact=impact, evidence=evidence, priority=priority, date_identified=date_identified,
        is_intentional=is_intentional,
    )
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="created",
              actor_id=creator.id, project_id=project.id, detail={"title": title})
    return pain_point


def edit_project_pain_point_record(
    db: Session, project: Project, pain_point: PainPoint, actor: User, *, type_ref_id: uuid.UUID | None = None,
    **fields: Any,
) -> None:
    """Edits a Pain Point in place (`fields`: see `update_pain_point`), moving it to `type_ref_id` when given.

    Raises:
        HTTPException: 409 once the Pain Point reached a terminal outcome; 400 for an unusable type; 4xx for an
            unusable owner.
    """
    if is_pain_point_locked(pain_point):
        raise _locked(PAIN_POINT_LOCKED)
    pain_point_type = None
    if type_ref_id is not None:
        try:
            pain_point_type = get_or_create_project_pain_point_type(db, project.id, project.organization_id, type_ref_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if fields.get("owner_explicitly_set"):
        validate_principal(db, fields.get("owner"), organization_id=project.organization_id, project_id=project.id, field="owner")
    update_pain_point(db, pain_point, pain_point_type=pain_point_type, **fields)
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="updated",
              actor_id=actor.id, project_id=project.id)


def edit_project_pain_point_scores(
    db: Session, scoring: ScoringContext, pain_point: PainPoint, actor: User, levels: Mapping[str, uuid.UUID | None],
) -> None:
    """Changes the "all personas" Severity / Frequency / Confidence of a Pain Point (the scores endpoint's rules).

    Only the axes named in `levels` change (`None` clears one); the others keep their level. The caller has
    checked the manager role, as the scores endpoint does.

    Args:
        db: Active session (nothing is committed).
        scoring: The project's scoring context (`load_scoring_context`).
        pain_point: The Pain Point.
        actor: The person scoring.
        levels: `{"severity" | "frequency" | "confidence": level id or None}`.

    Raises:
        HTTPException: 409 at a terminal outcome, or when the Pain Point is scored per persona (a single level
            cannot stand for several); 400 for a level that is not this organisation's for the axis.
    """
    if is_pain_point_locked(pain_point):
        raise _locked(PAIN_POINT_SCORES_LOCKED)
    rows = list_pain_point_scores(db, pain_point.id)
    if any(row.target_id is not None for row in rows):
        raise _locked(PAIN_POINT_SCORED_PER_PERSONA)
    current = rows[0] if rows else None
    merged = {axis: getattr(current, f"{axis}_level_id", None) for axis in ("severity", "frequency", "confidence")}
    merged.update(levels)
    set_pain_point_scores(
        db, scoring, pain_point,
        [ScoreEntryInput(None, merged["severity"], merged["frequency"], merged["confidence"])], actor,
    )


# --- Open Question -----------------------------------------------------------------------------------------------


def create_project_open_question_record(
    db: Session, project: Project, creator: User, *, question: str, context: str = "", evidence: str = "",
    priority: OpenQuestionPriority = OpenQuestionPriority.MEDIUM, due_date: date | None = None,
) -> OpenQuestion:
    """Creates an Open Question in `OPEN` status and records the `created` event."""
    open_question = create_open_question(
        db, project=project, creator=creator, question=question, context=context, evidence=evidence,
        priority=priority, due_date=due_date,
    )
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="created",
              actor_id=creator.id, project_id=project.id, detail={"question": question})
    return open_question


def edit_project_open_question_record(
    db: Session, project: Project, open_question: OpenQuestion, actor: User, **fields: Any
) -> None:
    """Edits an Open Question in place (`fields`: see `update_open_question`).

    Raises:
        HTTPException: 409 once the Open Question reached a terminal outcome; 4xx for an unusable owner.
    """
    if is_open_question_locked(open_question):
        raise _locked(OPEN_QUESTION_LOCKED)
    if fields.get("owner_explicitly_set"):
        validate_principal(db, fields.get("owner"), organization_id=project.organization_id, project_id=project.id, field="owner")
    update_open_question(db, open_question, **fields)
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="updated",
              actor_id=actor.id, project_id=project.id)
