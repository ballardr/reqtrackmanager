"""
Module: modules.context_strategy.project_router

Context & Strategy's Phase 1 project-scoped API (docs/plans/module-01-
context-and-strategy-plan.md Phase 1) — CRUD, lifecycle transitions,
comments, and file attachments for **project-scoped** Strategy records.
Mounted at `/api/v1/projects/{project_id}/modules/context_strategy`.

Phase 2 adds the same surface for **project-scoped** Future State records,
at `/future-states`, gated by `require_project_subcomponent_enabled
("context_strategy", "future_state")` and `_shared.require_future_state_
manage_role`/`require_future_state_approve_permission` — exact structural
mirror of the Strategy surface below, under distinct function names. A
project-scoped Future State's file attachments resolve through this
module's own `resolve_file_owner_project_id` hook (`module.py` ->
`service.resolve_future_state_file_project_id`), the same as Strategy's.

Phase 3 adds Pain Points, at `/pain-points`, plus their own two-tier type
vocabulary's project-scoped half at `/pain-point-types` (Phase 0 Q3 —
the org-scoped half, `PainPointTypeDefinition` CRUD, lives in `router.py`
instead, since Pain Point's *type vocabulary* has an org-level component
even though the Pain Point *artefact* does not). Gated by `require_
project_subcomponent_enabled("context_strategy", "pain_point")`
(`_require_pain_point_view`) for reads/creation — deliberately **broader**
than Strategy/Future State's own gate for one specific action: source
overview §6.5 explicitly grants "Add evidence" to any project member, so
(unlike `upload_project_strategy_file`, owner-gated) `upload_project_pain_
point_file` uses `_require_pain_point_view` alone, no `pain_point_manager`
role required — see that endpoint's own docstring. Direct content edits
(`PUT`), archive, type-vocabulary CRUD, and the "decide"-tier lifecycle
transitions (triage/reject/mark-duplicate/accept/address/close) are gated
by `_shared.require_pain_point_manage_role`/`require_pain_point_decide_
permission` — see those functions' own docstrings for the manage-vs-decide
split (Pain Point has only one elevated role, unlike Strategy/Future
State's owner+approver pair). A project-scoped Pain Point's file
attachments resolve through this module's own `resolve_file_owner_
project_id` hook (`module.py` -> `service.resolve_pain_point_file_
project_id`) — there is no org-scoped Pain Point file branch to contrast
with, since Pain Point itself has no org scope at all.

RBAC: reads/creation are gated by `require_project_subcomponent_enabled
("context_strategy", "strategy")` (`_require_view`) — any project member
with the module *and* this sub-component enabled may browse and propose a
Strategy (Phase 1's "project members (View + Propose)"). Module 0
(Platform Foundations) Phase 4 added the sub-component tier on top of the
whole-module check this router originally used (see `docs/decisions.md`'s
"Module 1 (Context & Strategy) Phase 1" entry's "Coordination note" for
why Phase 1 shipped whole-module-gated first) — `require_project_
subcomponent_enabled` still checks whole-module enablement first
internally, so this is a strict narrowing, not a parallel/replacement
check. Direct edits/archival require the
`strategy_owner` module role (`_shared.require_manage_role`); approve/
activate/supersede/retire require `strategy_approver` or an equivalent
Fine-Grained Access Control permission grant (`_shared.
require_approve_permission`). See `_shared.py` for the full composition
rules (server admin / `ProjectRole.PROJECT_MANAGER` / direct grant /
custom-role grant).

A project-scoped Strategy's file attachments are ordinary project-
authorized uploads, resolved via this module's own `resolve_file_owner_
project_id` hook (`module.py` -> `service.resolve_strategy_file_project_id`)
so the core `GET /api/v1/files/{id}` download endpoint can authorize them
without importing this module directly — mirrors `modules.decisions.
project_router.files`'s identical shape. See `router.py`'s own module
docstring for the org-scoped sibling of this router (whose files instead
use `is_org_resource=True`), and `_shared.py` for the helpers both share.

Phase 4 adds the same surface for **project-scoped** Guiding Principle
records, at `/guiding-principles`, gated by `require_project_subcomponent_
enabled("context_strategy", "guiding_principle")` and `_shared.require_
guiding_principle_manage_role`/`require_guiding_principle_approve_
permission` — exact structural mirror of the Strategy/Future State
surfaces above, minus the `submit-for-review` endpoint (`enums.
GuidingPrincipleStatus` has no `UNDER_REVIEW` state). A project-scoped
Guiding Principle's file attachments resolve through this module's own
`resolve_file_owner_project_id` hook (`module.py` -> `service.resolve_
guiding_principle_file_project_id`), the same as Strategy's/Future State's.

Phase 5 adds Open Questions, at `/open-questions` — project-scoped only,
like Pain Point (no org-scoped counterpart in `router.py` at all this
time, unlike Pain Point's own org-scoped type-vocabulary half, since Open
Question has no type vocabulary of its own). Gated by `require_project_
subcomponent_enabled("context_strategy", "open_question")`
(`_require_open_question_view`) for reads/creation — §9.4's broad-creation
model (any project member may create/comment/add evidence/suggest
resolution), the same posture as Pain Point's §6.5. Direct content edits
(`PUT`), archive, and the "change status"-tier lifecycle transitions
(`investigate`/`mark-ready-for-decision`/`withdraw`) are gated by `_shared.
require_open_question_manage_role` (`open_question_owner`); the `resolve`
transition alone is gated by a *separate* `_shared.require_open_question_
resolve_permission` (`open_question_resolver` — §9.4's own "Decision Maker"
tier, distinct from "Question Owner / Project Manager"; see `module.py`'s
own docstring for why this is two roles, not Pain Point's one). `resolve`
is deliberately a plain status transition, not the actual "Create Decision
from Open Question" workflow (§9.5, Module 4's own Phase 7) — see `service.
resolve_open_question`'s own docstring. A project-scoped Open Question's
file attachments resolve through this module's own `resolve_file_owner_
project_id` hook (`module.py` -> `service.resolve_open_question_file_
project_id`) — no org-scoped file branch, same as Pain Point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy._shared import (
    apply_value_error_as_conflict,
    context_strategy_link_to_out,
    future_state_to_out,
    get_future_state_in_scope,
    get_guiding_principle_in_scope,
    get_open_question_in_scope,
    get_pain_point_in_scope,
    get_strategy_in_scope,
    guiding_principle_to_out,
    open_question_to_out,
    pain_point_to_out,
    require_approve_permission,
    require_future_state_approve_permission,
    require_future_state_manage_role,
    require_guiding_principle_approve_permission,
    require_guiding_principle_manage_role,
    require_manage_role,
    require_open_question_manage_role,
    require_open_question_resolve_permission,
    require_pain_point_decide_permission,
    require_pain_point_manage_role,
    strategy_to_out,
)
from app.modules.context_strategy.enums import FutureStateScope, GuidingPrincipleScope, StrategyScope
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateComment,
    FutureStateCommentFile,
    FutureStateFile,
    GuidingPrinciple,
    GuidingPrincipleComment,
    GuidingPrincipleCommentFile,
    GuidingPrincipleFile,
    OpenQuestion,
    OpenQuestionComment,
    OpenQuestionCommentFile,
    OpenQuestionFile,
    PainPoint,
    PainPointComment,
    PainPointCommentFile,
    PainPointFile,
    ProjectPainPointType,
    Strategy,
    StrategyComment,
    StrategyCommentFile,
    StrategyFile,
)
from app.modules.context_strategy.pain_point_scores import (
    PainPointScoringSummary,
    RollupMethod,
    ScoreEntryInput,
    build_pain_point_scoring,
    load_scoring_context,
    resolve_model,
    set_pain_point_scores,
)
from app.modules.context_strategy.reports import REPORT_ROUTERS
from app.modules.context_strategy.schemas import (
    ContextStrategyLinkOut,
    EffectivePainPointTypeOut,
    FutureStateCommentCreate,
    FutureStateCommentOut,
    FutureStateCommentUpdate,
    FutureStateCreate,
    FutureStateLinkCreate,
    FutureStateOut,
    FutureStateSupersessionCreate,
    FutureStateTransitionRequest,
    FutureStateUpdate,
    FutureStateVersionOut,
    GuidingPrincipleCommentCreate,
    GuidingPrincipleCommentOut,
    GuidingPrincipleCommentUpdate,
    GuidingPrincipleCreate,
    GuidingPrincipleLinkCreate,
    GuidingPrincipleOut,
    GuidingPrincipleSupersessionCreate,
    GuidingPrincipleTransitionRequest,
    GuidingPrincipleUpdate,
    GuidingPrincipleVersionOut,
    OpenQuestionCommentCreate,
    OpenQuestionCommentOut,
    OpenQuestionCommentUpdate,
    OpenQuestionCreate,
    OpenQuestionLinkCreate,
    OpenQuestionOut,
    OpenQuestionTransitionRequest,
    OpenQuestionUpdate,
    PainPointCommentCreate,
    PainPointCommentOut,
    PainPointCommentUpdate,
    PainPointCreate,
    PainPointLinkCreate,
    PainPointOut,
    PainPointScoreEntryOut,
    PainPointScoresOut,
    PainPointScoresUpdate,
    PainPointScoringListOut,
    PainPointScoringSummaryOut,
    PainPointTransitionRequest,
    PainPointUpdate,
    ProjectPainPointTypeCreate,
    ProjectPainPointTypeOut,
    ProjectPainPointTypeOverrideUpdate,
    ScoreOut,
    ScoringTargetOut,
    StrategyCommentCreate,
    StrategyCommentOut,
    StrategyCommentUpdate,
    StrategyCreate,
    StrategyLinkCreate,
    StrategyOut,
    StrategySupersessionCreate,
    StrategyTransitionRequest,
    StrategyUpdate,
    StrategyVersionOut,
)
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    OPEN_QUESTION_ARTEFACT_TYPE,
    PAIN_POINT_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
    accept_pain_point,
    activate_future_state,
    activate_guiding_principle,
    activate_strategy,
    address_pain_point,
    apply_future_state_new_version,
    apply_guiding_principle_new_version,
    apply_new_version,
    approve_future_state,
    approve_guiding_principle,
    approve_strategy,
    archive_future_state,
    archive_guiding_principle,
    archive_open_question,
    archive_pain_point,
    archive_strategy,
    close_pain_point,
    create_future_state,
    create_future_state_link,
    create_future_state_supersession,
    create_guiding_principle,
    create_guiding_principle_link,
    create_guiding_principle_supersession,
    create_open_question,
    create_open_question_link,
    create_pain_point,
    create_pain_point_link,
    create_project_local_pain_point_type,
    create_strategy,
    create_strategy_link,
    create_strategy_supersession,
    delete_project_pain_point_type,
    get_current_future_state_version,
    get_current_guiding_principle_version,
    get_current_version,
    get_or_create_project_pain_point_type,
    investigate_open_question,
    is_future_state_locked,
    is_guiding_principle_locked,
    is_locked,
    is_open_question_locked,
    is_pain_point_locked,
    mark_open_question_ready_for_decision,
    mark_pain_point_duplicate,
    propose_future_state,
    propose_guiding_principle,
    propose_strategy,
    reject_pain_point,
    resolve_effective_pain_point_types,
    resolve_open_question,
    retire_future_state,
    retire_guiding_principle,
    retire_strategy,
    send_future_state_back_to_draft,
    send_guiding_principle_back_to_draft,
    send_strategy_back_to_draft,
    set_project_pain_point_type_override,
    submit_future_state_for_review,
    submit_strategy_for_review,
    supersede_future_state,
    supersede_guiding_principle,
    supersede_strategy,
    triage_pain_point,
    unarchive_future_state,
    unarchive_guiding_principle,
    unarchive_open_question,
    unarchive_pain_point,
    unarchive_strategy,
    update_open_question,
    update_pain_point,
    withdraw_open_question,
)
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.rbac import require_ai_approvals_enabled, require_project_subcomponent_enabled
from app.services.relationships import get_all_links

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/context_strategy", tags=["context-strategy-project"])

_SCOPE = StrategyScope.PROJECT
_require_view = require_project_subcomponent_enabled("context_strategy", "strategy")

_FS_SCOPE = FutureStateScope.PROJECT
_require_future_state_view = require_project_subcomponent_enabled("context_strategy", "future_state")

_require_pain_point_view = require_project_subcomponent_enabled("context_strategy", "pain_point")

_GP_SCOPE = GuidingPrincipleScope.PROJECT
_require_guiding_principle_view = require_project_subcomponent_enabled("context_strategy", "guiding_principle")

_require_open_question_view = require_project_subcomponent_enabled("context_strategy", "open_question")


def _get_strategy(db: Session, project_id: UUID, strategy_id: UUID) -> Strategy:
    return get_strategy_in_scope(db, _SCOPE, project_id=project_id, strategy_id=strategy_id)


def _require_creator_or_manage(db: Session, current_user: User, project: Project, strategy: Strategy) -> None:
    if current_user.id == strategy.creator_id:
        return
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project.id)


# --- Strategy CRUD -----------------------------------------------------------


@router.post("/strategies", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def create_project_strategy(
    project_id: UUID, payload: StrategyCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped Strategy in `DRAFT` status. Any project
    member with the module enabled may create one — no `strategy_owner`
    grant required (Phase 1's "project members (View + Propose)")."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    strategy = create_strategy(
        db, scope=_SCOPE, organization_id=project.organization_id, project_id=project_id, creator=current_user,
        title=payload.title, objective=payload.objective, current_state=payload.current_state,
        desired_future_state=payload.desired_future_state, rationale=payload.rationale,
        expected_outcomes=payload.expected_outcomes, constraints=payload.constraints,
        measures_of_success=payload.measures_of_success, priority=payload.priority, time_horizon=payload.time_horizon,
    )
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"title": payload.title})
    db.commit()
    db.refresh(strategy)
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.get("/strategies", response_model=list[StrategyOut])
def list_project_strategies(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    query = select(Strategy).where(Strategy.project_id == project_id, Strategy.scope == _SCOPE)
    if not include_archived:
        query = query.where(Strategy.is_archived.is_(False))
    strategies = db.scalars(query.order_by(Strategy.created_at)).all()
    return [strategy_to_out(s, get_current_version(db, s.id)) for s in strategies]


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
def get_project_strategy(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
def update_project_strategy(
    project_id: UUID, strategy_id: UUID, payload: StrategyUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Direct edit of a Strategy's content (a new `StrategyVersion`, same
    status). 409s once the current version is locked (past `UNDER_REVIEW`
    — see `service.LOCKED_STATUSES`)."""
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    if is_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Strategy is past review; its content can no longer be edited in place.",
        )
    apply_new_version(
        db, strategy, current_version, current_user,
        title=payload.title, objective=payload.objective, current_state=payload.current_state,
        desired_future_state=payload.desired_future_state, rationale=payload.rationale,
        expected_outcomes=payload.expected_outcomes, constraints=payload.constraints,
        measures_of_success=payload.measures_of_success, priority=payload.priority, time_horizon=payload.time_horizon,
        change_note=payload.change_note,
    )
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.get("/strategies/{strategy_id}/versions", response_model=list[StrategyVersionOut])
def list_project_strategy_versions(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    return list(strategy.versions)


@router.post("/strategies/{strategy_id}/archive", response_model=StrategyOut)
def archive_project_strategy(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    if strategy.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Strategy is already archived.")
    archive_strategy(db, strategy, current_user)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/unarchive", response_model=StrategyOut)
def unarchive_project_strategy(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    if not strategy.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Strategy is not archived.")
    unarchive_strategy(db, strategy)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


# --- Lifecycle transitions ---------------------------------------------------


@router.post("/strategies/{strategy_id}/propose", response_model=StrategyOut)
def propose_project_strategy(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    _require_creator_or_manage(db, current_user, project, strategy)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(propose_strategy, db, strategy, current_version, current_user)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/submit-for-review", response_model=StrategyOut)
def submit_project_strategy_for_review(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    _require_creator_or_manage(db, current_user, project, strategy)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(submit_strategy_for_review, db, strategy, current_version, current_user)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/send-back", response_model=StrategyOut)
def send_project_strategy_back(
    project_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED`/`UNDER_REVIEW` Strategy back to `DRAFT` for
    rework — this module's "reject"-equivalent (see `enums.StrategyStatus`'s
    own docstring). A comment is required."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to send a Strategy back to draft.")
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        send_strategy_back_to_draft, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/approve", response_model=StrategyOut)
def approve_project_strategy(
    project_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves a Strategy (`UNDER_REVIEW` -> `APPROVED`). MCP-
    reachable (Phase 6, `module.py`'s `mcp_tools`) — per the 2026-09-22
    write-enabled-MCP decision (`docs/decisions.md`), reached through the
    MCP server this additionally requires this project and its organisation
    to both have explicitly enabled AI approval (`require_ai_approvals_
    enabled`), mirroring `modules.decisions.project_router.workflow.
    approve_decision_endpoint`'s own docstring/pattern exactly; a plain
    UI/API call is unaffected by that flag either way."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        approve_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/activate", response_model=StrategyOut)
def activate_project_strategy(
    project_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        activate_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/supersede", response_model=StrategyOut)
def supersede_project_strategy(
    project_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        supersede_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/retire", response_model=StrategyOut)
def retire_project_strategy(
    project_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        retire_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


# --- Comments -----------------------------------------------------------


def _comment_to_out(db: Session, comment: StrategyComment) -> StrategyCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(StrategyCommentFile, StrategyCommentFile.file_id == FileAsset.id)
        .where(StrategyCommentFile.comment_id == comment.id)
    ).all()
    return StrategyCommentOut(
        id=comment.id, strategy_id=comment.strategy_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post("/strategies/{strategy_id}/comments", response_model=StrategyCommentOut, status_code=status.HTTP_201_CREATED)
def add_project_strategy_comment(
    project_id: UUID, strategy_id: UUID, payload: StrategyCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    comment = StrategyComment(strategy_id=strategy.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.get("/strategies/{strategy_id}/comments", response_model=list[StrategyCommentOut])
def list_project_strategy_comments(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    comments = db.scalars(
        select(StrategyComment).where(StrategyComment.strategy_id == strategy.id).order_by(StrategyComment.created_at)
    ).all()
    return [_comment_to_out(db, c) for c in comments]


@router.patch("/strategies/{strategy_id}/comments/{comment_id}", response_model=StrategyCommentOut)
def edit_project_strategy_comment(
    project_id: UUID, strategy_id: UUID, comment_id: UUID, payload: StrategyCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Strategy Owner may edit someone else's words."""
    _get_strategy(db, project_id, strategy_id)
    comment = db.get(StrategyComment, comment_id)
    if comment is None or comment.strategy_id != strategy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.post(
    "/strategies/{strategy_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_strategy_comment_attachment(
    project_id: UUID, strategy_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors `modules.decisions.project_router.comments.
    upload_decision_comment_attachment`'s pattern exactly."""
    project = db.get(Project, project_id)
    _get_strategy(db, project_id, strategy_id)
    comment = db.get(StrategyComment, comment_id)
    if comment is None or comment.strategy_id != strategy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(StrategyCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/strategies/{strategy_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_strategy_comment_attachment(
    project_id: UUID, strategy_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _get_strategy(db, project_id, strategy_id)
    comment = db.get(StrategyComment, comment_id)
    if comment is None or comment.strategy_id != strategy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(StrategyCommentFile).where(
            StrategyCommentFile.comment_id == comment.id, StrategyCommentFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    db.commit()


# --- Direct file attachments -------------------------------------------------


@router.post("/strategies/{strategy_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_strategy_file(
    project_id: UUID, strategy_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Ordinary project-authorized upload, resolved via this module's own
    `resolve_file_owner_project_id` hook — see this module's own docstring
    for why (contrast `router.py`'s org-scoped, `is_org_resource=True`
    sibling)."""
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    current_version = get_current_version(db, strategy.id)
    if is_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Strategy is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(StrategyFile(strategy_id=strategy.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/strategies/{strategy_id}/files", response_model=list[FileAssetOut])
def list_project_strategy_files(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    return db.scalars(
        select(FileAsset).join(StrategyFile, StrategyFile.file_id == FileAsset.id).where(
            StrategyFile.strategy_id == strategy.id
        )
    ).all()


@router.delete("/strategies/{strategy_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_strategy_file(
    project_id: UUID, strategy_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    strategy = _get_strategy(db, project_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    link = db.scalar(select(StrategyFile).where(StrategyFile.strategy_id == strategy.id, StrategyFile.file_id == file_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Strategy.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Future State (Phase 2) -------------------------------------------------
# =============================================================================


def _get_future_state(db: Session, project_id: UUID, future_state_id: UUID) -> FutureState:
    return get_future_state_in_scope(db, _FS_SCOPE, project_id=project_id, future_state_id=future_state_id)


def _require_fs_creator_or_manage(db: Session, current_user: User, project: Project, future_state: FutureState) -> None:
    if current_user.id == future_state.creator_id:
        return
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project.id,
    )


# --- Future State CRUD -------------------------------------------------------


@router.post("/future-states", response_model=FutureStateOut, status_code=status.HTTP_201_CREATED)
def create_project_future_state(
    project_id: UUID, payload: FutureStateCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped Future State in `DRAFT` status. Any project
    member with the module enabled may create one — no `future_state_owner`
    grant required, same posture as Strategy creation."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    future_state = create_future_state(
        db, scope=_FS_SCOPE, organization_id=project.organization_id, project_id=project_id, creator=current_user,
        title=payload.title, current_state=payload.current_state, desired_state=payload.desired_state,
        target_date=payload.target_date, outcomes=payload.outcomes, success_measures=payload.success_measures,
        constraints=payload.constraints, assumptions=payload.assumptions,
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"title": payload.title})
    db.commit()
    db.refresh(future_state)
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.get("/future-states", response_model=list[FutureStateOut])
def list_project_future_states(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    query = select(FutureState).where(FutureState.project_id == project_id, FutureState.scope == _FS_SCOPE)
    if not include_archived:
        query = query.where(FutureState.is_archived.is_(False))
    future_states = db.scalars(query.order_by(FutureState.created_at)).all()
    return [future_state_to_out(fs, get_current_future_state_version(db, fs.id)) for fs in future_states]


@router.get("/future-states/{future_state_id}", response_model=FutureStateOut)
def get_project_future_state(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.put("/future-states/{future_state_id}", response_model=FutureStateOut)
def update_project_future_state(
    project_id: UUID, future_state_id: UUID, payload: FutureStateUpdate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Direct edit of a Future State's content (a new `FutureStateVersion`,
    same status). 409s once the current version is locked."""
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    if is_future_state_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Future State is past review; its content can no longer be edited in place.",
        )
    apply_future_state_new_version(
        db, future_state, current_version, current_user,
        title=payload.title, current_state=payload.current_state, desired_state=payload.desired_state,
        target_date=payload.target_date, target_date_explicitly_set=True, outcomes=payload.outcomes,
        success_measures=payload.success_measures, constraints=payload.constraints, assumptions=payload.assumptions,
        change_note=payload.change_note,
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.get("/future-states/{future_state_id}/versions", response_model=list[FutureStateVersionOut])
def list_project_future_state_versions(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    return list(future_state.versions)


@router.post("/future-states/{future_state_id}/archive", response_model=FutureStateOut)
def archive_project_future_state(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    if future_state.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Future State is already archived.")
    archive_future_state(db, future_state, current_user)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/unarchive", response_model=FutureStateOut)
def unarchive_project_future_state(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    if not future_state.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Future State is not archived.")
    unarchive_future_state(db, future_state)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


# --- Future State lifecycle transitions --------------------------------------


@router.post("/future-states/{future_state_id}/propose", response_model=FutureStateOut)
def propose_project_future_state(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    _require_fs_creator_or_manage(db, current_user, project, future_state)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(propose_future_state, db, future_state, current_version, current_user)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/submit-for-review", response_model=FutureStateOut)
def submit_project_future_state_for_review(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    _require_fs_creator_or_manage(db, current_user, project, future_state)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(submit_future_state_for_review, db, future_state, current_version, current_user)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/send-back", response_model=FutureStateOut)
def send_project_future_state_back(
    project_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED`/`UNDER_REVIEW` Future State back to `DRAFT` for
    rework. A comment is required."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to send a Future State back to draft.")
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        send_future_state_back_to_draft, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/approve", response_model=FutureStateOut)
def approve_project_future_state(
    project_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Formally approves a Future State (`UNDER_REVIEW` -> `APPROVED`).
    MCP-reachable (Phase 6) — same `require_ai_approvals_enabled` gate as
    `approve_project_strategy`, see that endpoint's own docstring."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        approve_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/activate", response_model=FutureStateOut)
def activate_project_future_state(
    project_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        activate_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/supersede", response_model=FutureStateOut)
def supersede_project_future_state(
    project_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        supersede_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/retire", response_model=FutureStateOut)
def retire_project_future_state(
    project_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        retire_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


# --- Future State comments ----------------------------------------------------


def _fs_comment_to_out(db: Session, comment: FutureStateComment) -> FutureStateCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(FutureStateCommentFile, FutureStateCommentFile.file_id == FileAsset.id)
        .where(FutureStateCommentFile.comment_id == comment.id)
    ).all()
    return FutureStateCommentOut(
        id=comment.id, future_state_id=comment.future_state_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post(
    "/future-states/{future_state_id}/comments", response_model=FutureStateCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_project_future_state_comment(
    project_id: UUID, future_state_id: UUID, payload: FutureStateCommentCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    comment = FutureStateComment(future_state_id=future_state.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _fs_comment_to_out(db, comment)


@router.get("/future-states/{future_state_id}/comments", response_model=list[FutureStateCommentOut])
def list_project_future_state_comments(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    comments = db.scalars(
        select(FutureStateComment).where(FutureStateComment.future_state_id == future_state.id)
        .order_by(FutureStateComment.created_at)
    ).all()
    return [_fs_comment_to_out(db, c) for c in comments]


@router.patch("/future-states/{future_state_id}/comments/{comment_id}", response_model=FutureStateCommentOut)
def edit_project_future_state_comment(
    project_id: UUID, future_state_id: UUID, comment_id: UUID, payload: FutureStateCommentUpdate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Future State Owner may edit someone else's words."""
    _get_future_state(db, project_id, future_state_id)
    comment = db.get(FutureStateComment, comment_id)
    if comment is None or comment.future_state_id != future_state_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _fs_comment_to_out(db, comment)


@router.post(
    "/future-states/{future_state_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_future_state_comment_attachment(
    project_id: UUID, future_state_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's identical comment-attachment pattern."""
    project = db.get(Project, project_id)
    _get_future_state(db, project_id, future_state_id)
    comment = db.get(FutureStateComment, comment_id)
    if comment is None or comment.future_state_id != future_state_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(FutureStateCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/future-states/{future_state_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_future_state_comment_attachment(
    project_id: UUID, future_state_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    _get_future_state(db, project_id, future_state_id)
    comment = db.get(FutureStateComment, comment_id)
    if comment is None or comment.future_state_id != future_state_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(FutureStateCommentFile).where(
            FutureStateCommentFile.comment_id == comment.id, FutureStateCommentFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    db.commit()


# --- Future State direct file attachments ------------------------------------


@router.post("/future-states/{future_state_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_future_state_file(
    project_id: UUID, future_state_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Ordinary project-authorized upload, resolved via this module's own
    `resolve_file_owner_project_id` hook — see this module's own docstring
    for why (contrast `router.py`'s org-scoped, `is_org_resource=True`
    sibling)."""
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_future_state_version(db, future_state.id)
    if is_future_state_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Future State is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(
        FutureStateFile(
            future_state_id=future_state.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at,
        )
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/future-states/{future_state_id}/files", response_model=list[FileAssetOut])
def list_project_future_state_files(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    return db.scalars(
        select(FileAsset).join(FutureStateFile, FutureStateFile.file_id == FileAsset.id).where(
            FutureStateFile.future_state_id == future_state.id
        )
    ).all()


@router.delete("/future-states/{future_state_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_future_state_file(
    project_id: UUID, future_state_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    future_state = _get_future_state(db, project_id, future_state_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    link = db.scalar(
        select(FutureStateFile).where(
            FutureStateFile.future_state_id == future_state.id, FutureStateFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Future State.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Pain Points (Phase 3) ---------------------------------------------------
# =============================================================================


def _get_pain_point(db: Session, project_id: UUID, pain_point_id: UUID) -> PainPoint:
    return get_pain_point_in_scope(db, project_id=project_id, pain_point_id=pain_point_id)


def _get_project_pain_point_type(db: Session, project_id: UUID, project_pain_point_type_id: UUID) -> ProjectPainPointType:
    row = db.get(ProjectPainPointType, project_pain_point_type_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pain Point type not found.")
    return row


# --- Pain Point type vocabulary (project-scoped half, Phase 0 Q3) -----------


@router.get("/pain-point-types", response_model=list[EffectivePainPointTypeOut])
def list_project_pain_point_types(
    project_id: UUID, current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Lists this project's *effective* Pain Point type list — every active
    org type (its own project override's name/order/enabled state, if any)
    plus every project-local type (`service.resolve_effective_pain_point_types`).
    Open to any project member with the module+sub-component enabled — a
    plain member submitting a Pain Point needs this to populate a type
    picker, same reasoning as `list_action_types`' own "not manage-only"
    read."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return resolve_effective_pain_point_types(db, project_id, project.organization_id)


@router.post("/pain-point-types", response_model=ProjectPainPointTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_local_pain_point_type_endpoint(
    project_id: UUID, payload: ProjectPainPointTypeCreate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Creates a fully project-local Pain Point type (§6.2 "Add types") —
    manager-gated, matching "project administrators should be able to
    add/rename/reorder/disable/remove types."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    try:
        local_type = create_project_local_pain_point_type(
            db, project_id, payload.name, display_order=payload.display_order,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="project_pain_point_type", entity_id=local_type.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(local_type)
    return local_type


@router.put("/pain-point-types/{type_ref_id}", response_model=ProjectPainPointTypeOut)
def override_project_pain_point_type(
    project_id: UUID, type_ref_id: UUID, payload: ProjectPainPointTypeOverrideUpdate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Applies a partial override to a Pain Point type in this project —
    `type_ref_id` is an `EffectivePainPointTypeOut.id` (see that schema's
    own docstring): an org type with no override yet gets one created the
    first time this is called (`get_or_create_project_pain_point_type`);
    an existing override row or project-local row is updated in place.
    Manager-gated — §6.2 "Rename types"/"Reorder types"/"Disable types"."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    try:
        row = get_or_create_project_pain_point_type(db, project_id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    set_project_pain_point_type_override(
        db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled,
    )
    log_event(db, entity_type="project_pain_point_type", entity_id=row.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/pain-point-types/{project_pain_point_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_pain_point_type_endpoint(
    project_id: UUID, project_pain_point_type_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Deletes a `ProjectPainPointType` row (§6.2 "Remove types where no
    longer used") — for an org-backed override, this simply reverts to the
    plain org default; for a project-local type, this genuinely removes it.
    409s if any Pain Point still references it (`service.delete_project_
    pain_point_type`'s own docstring)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    row = _get_project_pain_point_type(db, project_id, project_pain_point_type_id)
    apply_value_error_as_conflict(delete_project_pain_point_type, db, row)
    log_event(db, entity_type="project_pain_point_type", entity_id=project_pain_point_type_id, action="deleted",
              actor_id=current_user.id, project_id=project_id)
    db.commit()


# --- Pain Point CRUD -----------------------------------------------------------


@router.post("/pain-points", response_model=PainPointOut, status_code=status.HTTP_201_CREATED)
def create_project_pain_point(
    project_id: UUID, payload: PainPointCreate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Creates a Pain Point in `SUBMITTED` status. Any project member with
    the module enabled may create one — no `pain_point_manager` grant
    required (§6.5's broad-creation model: "restricting creation to
    administrators would prevent the system from capturing problems
    discovered by ordinary users and operators")."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    try:
        pain_point_type = get_or_create_project_pain_point_type(
            db, project_id, project.organization_id, payload.pain_point_type_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not pain_point_type.is_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This Pain Point type is disabled for this project.")
    pain_point = create_pain_point(
        db, project_id=project_id, pain_point_type=pain_point_type, creator=current_user, title=payload.title,
        description=payload.description, source=payload.source, impact=payload.impact, evidence=payload.evidence,
        priority=payload.priority, date_identified=payload.date_identified,
        is_intentional=payload.is_intentional,
    )
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"title": payload.title})
    db.commit()
    db.refresh(pain_point)
    return pain_point_to_out(db, pain_point)


@router.get("/pain-points", response_model=list[PainPointOut])
def list_project_pain_points(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    query = select(PainPoint).where(PainPoint.project_id == project_id)
    if not include_archived:
        query = query.where(PainPoint.is_archived.is_(False))
    pain_points = db.scalars(query.order_by(PainPoint.created_at)).all()
    return [pain_point_to_out(db, p) for p in pain_points]


@router.get("/pain-points/{pain_point_id}", response_model=PainPointOut)
def get_project_pain_point(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    return pain_point_to_out(db, pain_point)


@router.put("/pain-points/{pain_point_id}", response_model=PainPointOut)
def update_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointUpdate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Direct edit of a Pain Point's content, including classification/
    priority/owner (§6.5's manager-tier "Change classification"/"Set
    priority"/"Assign owner"). Manager-only (`_shared.require_pain_point_
    manage_role`) — see this module's own docstring for why Pain Point's
    broad-creation model does not extend to a standing creator edit right.
    409s once the Pain Point has reached a terminal outcome (`service.
    PAIN_POINT_LOCKED_STATUSES`)."""
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if is_pain_point_locked(pain_point):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Pain Point has reached a terminal outcome; its content can no longer be edited.",
        )
    try:
        pain_point_type = get_or_create_project_pain_point_type(
            db, project_id, project.organization_id, payload.pain_point_type_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    update_pain_point(
        db, pain_point, pain_point_type=pain_point_type, title=payload.title, description=payload.description,
        source=payload.source, impact=payload.impact, evidence=payload.evidence, priority=payload.priority,
        owner_id=payload.owner_id, owner_id_explicitly_set=True, date_identified=payload.date_identified,
        is_intentional=payload.is_intentional,
    )
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/archive", response_model=PainPointOut)
def archive_project_pain_point(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if pain_point.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Pain Point is already archived.")
    archive_pain_point(db, pain_point, current_user)
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/unarchive", response_model=PainPointOut)
def unarchive_project_pain_point(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if not pain_point.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Pain Point is not archived.")
    unarchive_pain_point(db, pain_point)
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return pain_point_to_out(db, pain_point)


# --- Pain Point scoring (Phase 11) ---------------------------------------------


def _score_out(score) -> ScoreOut | None:
    """Maps a `services.scoring.ScoreResult` (or `None`) to its API shape."""
    if score is None:
        return None
    return ScoreOut(
        raw=float(score.raw), normalised=score.normalised,
        band_label=score.band.label if score.band else None, band_tone=score.band.tone if score.band else None,
    )


def _scoring_summary_out(summary: PainPointScoringSummary) -> PainPointScoringSummaryOut:
    """Maps a roll-up to its API shape."""
    return PainPointScoringSummaryOut(
        pain_point_id=summary.pain_point_id, scope=summary.scope, score=_score_out(summary.score),
        counted=summary.counted, is_blocker=summary.is_blocker, blocker_labels=summary.blocker_labels,
        personas_degraded=summary.personas_degraded,
        entries=[
            PainPointScoreEntryOut(
                target_id=e.row.target_id, target_type=e.row.target_type, label=e.label, weight=e.weight,
                status=e.target_status.value, severity_level_id=e.row.severity_level_id,
                frequency_level_id=e.row.frequency_level_id, confidence_level_id=e.row.confidence_level_id,
                score=_score_out(e.score), is_blocker=e.is_blocker,
            )
            for e in summary.entries
        ],
    )


def _parse_rollup(value: str) -> RollupMethod:
    """Parses the `rollup` query parameter, 400 on an unknown method."""
    try:
        return RollupMethod(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown roll-up method '{value}'.") from exc


@router.get("/pain-point-scores", response_model=PainPointScoringListOut)
def list_project_pain_point_scores(
    project_id: UUID, model_key: str | None = None, rollup: str = RollupMethod.WEIGHTED_AVERAGE.value,
    include_archived: bool = False,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Every Pain Point's roll-up under one scoring model and persona
    roll-up method (both chosen when viewing; the model defaults to the
    project's resolved default). Read-only, so open to any project member
    who can see Pain Points."""
    project = db.get(Project, project_id)
    method = _parse_rollup(rollup)
    ctx = load_scoring_context(db, project)
    model = resolve_model(ctx, model_key)
    query = select(PainPoint).where(PainPoint.project_id == project_id)
    if not include_archived:
        query = query.where(PainPoint.is_archived.is_(False))
    pain_points = list(db.scalars(query.order_by(PainPoint.created_at)).all())
    summaries = build_pain_point_scoring(db, ctx, pain_points, model, method)
    return PainPointScoringListOut(
        model_key=model.key, model_source=ctx.default_model_source if model.key == ctx.default_model_key else "chosen",
        rollup=method.value, items=[_scoring_summary_out(s) for s in summaries],
    )


@router.get("/pain-points/{pain_point_id}/scores", response_model=PainPointScoresOut)
def get_project_pain_point_scores(
    project_id: UUID, pain_point_id: UUID, model_key: str | None = None,
    rollup: str = RollupMethod.WEIGHTED_AVERAGE.value,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """A Pain Point's per-persona scores and roll-up, plus the personas it
    can be scored against."""
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    return _scores_out(db, pain_point, model_key, _parse_rollup(rollup))


def _scores_out(db: Session, pain_point: PainPoint, model_key: str | None, method: RollupMethod) -> PainPointScoresOut:
    """Builds the single-Pain-Point scoring response."""
    project = db.get(Project, pain_point.project_id)
    ctx = load_scoring_context(db, project)
    model = resolve_model(ctx, model_key)
    summary = build_pain_point_scoring(db, ctx, [pain_point], model, method)[0]
    return PainPointScoresOut(
        **_scoring_summary_out(summary).model_dump(),
        model_key=model.key, model_source=ctx.default_model_source if model.key == ctx.default_model_key else "chosen",
        rollup=method.value,
        available_targets=[
            ScoringTargetOut(id=t.id, label=t.label, weight=t.weight, is_active=t.is_active)
            for t in ctx.targets.values()
        ],
    )


@router.put("/pain-points/{pain_point_id}/scores", response_model=PainPointScoresOut)
def set_project_pain_point_scores(
    project_id: UUID, pain_point_id: UUID, payload: PainPointScoresUpdate,
    model_key: str | None = None, rollup: str = RollupMethod.WEIGHTED_AVERAGE.value,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Replaces a Pain Point's score set. Manager-only (prioritisation is
    a triage-tier action, unlike broad Pain Point creation); 409 once the
    Pain Point has reached a terminal outcome. Returns the new roll-up under
    the requested model and method."""
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if is_pain_point_locked(pain_point):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Pain Point has reached a terminal outcome; its scores can no longer be edited.",
        )
    method = _parse_rollup(rollup)
    ctx = load_scoring_context(db, project)
    resolve_model(ctx, model_key)  # validate before writing
    set_pain_point_scores(
        db, ctx, pain_point,
        [ScoreEntryInput(e.target_id, e.severity_level_id, e.frequency_level_id, e.confidence_level_id)
         for e in payload.scores],
        current_user,
    )
    db.commit()
    return _scores_out(db, pain_point, model_key, method)


# --- Pain Point lifecycle (branching) -----------------------------------------


@router.post("/pain-points/{pain_point_id}/triage", response_model=PainPointOut)
def triage_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(triage_pain_point, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/reject", response_model=PainPointOut)
def reject_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """`TRIAGED` -> `REJECTED`. A comment is required."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to reject a Pain Point.")
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(reject_pain_point, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/mark-duplicate", response_model=PainPointOut)
def mark_project_pain_point_duplicate(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """`TRIAGED` -> `DUPLICATE`. A comment is required (`service.mark_
    pain_point_duplicate`'s own docstring — this is also where the
    canonical Pain Point is noted, pending Phase 6's real link)."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to mark a Pain Point as a duplicate.")
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(mark_pain_point_duplicate, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/accept", response_model=PainPointOut)
def accept_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(accept_pain_point, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/address", response_model=PainPointOut)
def address_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(address_pain_point, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


@router.post("/pain-points/{pain_point_id}/close", response_model=PainPointOut)
def close_project_pain_point(
    project_id: UUID, pain_point_id: UUID, payload: PainPointTransitionRequest,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_decide_permission(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(close_pain_point, db, pain_point, current_user, comment=payload.comment)
    db.commit()
    return pain_point_to_out(db, pain_point)


# --- Pain Point comments -------------------------------------------------------


def _pp_comment_to_out(db: Session, comment: PainPointComment) -> PainPointCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(PainPointCommentFile, PainPointCommentFile.file_id == FileAsset.id)
        .where(PainPointCommentFile.comment_id == comment.id)
    ).all()
    return PainPointCommentOut(
        id=comment.id, pain_point_id=comment.pain_point_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post(
    "/pain-points/{pain_point_id}/comments", response_model=PainPointCommentOut, status_code=status.HTTP_201_CREATED,
)
def add_project_pain_point_comment(
    project_id: UUID, pain_point_id: UUID, payload: PainPointCommentCreate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Any project member with the module enabled may comment (§6.5)."""
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    comment = PainPointComment(pain_point_id=pain_point.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _pp_comment_to_out(db, comment)


@router.get("/pain-points/{pain_point_id}/comments", response_model=list[PainPointCommentOut])
def list_project_pain_point_comments(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    comments = db.scalars(
        select(PainPointComment).where(PainPointComment.pain_point_id == pain_point.id)
        .order_by(PainPointComment.created_at)
    ).all()
    return [_pp_comment_to_out(db, c) for c in comments]


@router.patch("/pain-points/{pain_point_id}/comments/{comment_id}", response_model=PainPointCommentOut)
def edit_project_pain_point_comment(
    project_id: UUID, pain_point_id: UUID, comment_id: UUID, payload: PainPointCommentUpdate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Pain Point Manager may edit someone else's words."""
    _get_pain_point(db, project_id, pain_point_id)
    comment = db.get(PainPointComment, comment_id)
    if comment is None or comment.pain_point_id != pain_point_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _pp_comment_to_out(db, comment)


@router.post(
    "/pain-points/{pain_point_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_pain_point_comment_attachment(
    project_id: UUID, pain_point_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's identical comment-attachment pattern."""
    project = db.get(Project, project_id)
    _get_pain_point(db, project_id, pain_point_id)
    comment = db.get(PainPointComment, comment_id)
    if comment is None or comment.pain_point_id != pain_point_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(PainPointCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/pain-points/{pain_point_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_pain_point_comment_attachment(
    project_id: UUID, pain_point_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    _get_pain_point(db, project_id, pain_point_id)
    comment = db.get(PainPointComment, comment_id)
    if comment is None or comment.pain_point_id != pain_point_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(PainPointCommentFile).where(
            PainPointCommentFile.comment_id == comment.id, PainPointCommentFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    db.commit()


# --- Pain Point direct file attachments ("evidence") --------------------------


@router.post("/pain-points/{pain_point_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_pain_point_file(
    project_id: UUID, pain_point_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """**Deliberately open to any project member**, not manager-gated —
    unlike `upload_project_strategy_file`/`upload_project_future_state_
    file` (both owner-gated), source overview §6.5 explicitly lists "Add
    evidence" among the broad-creation-model capabilities every project
    member gets for a Pain Point. Still 409s once the Pain Point has
    reached a terminal outcome."""
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    if is_pain_point_locked(pain_point):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Pain Point has reached a terminal outcome; new evidence can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(
        PainPointFile(pain_point_id=pain_point.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at)
    )
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/pain-points/{pain_point_id}/files", response_model=list[FileAssetOut])
def list_project_pain_point_files(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    return db.scalars(
        select(FileAsset).join(PainPointFile, PainPointFile.file_id == FileAsset.id).where(
            PainPointFile.pain_point_id == pain_point.id
        )
    ).all()


@router.delete("/pain-points/{pain_point_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_pain_point_file(
    project_id: UUID, pain_point_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    """Manager-gated to remove — asymmetric with the open-to-all upload
    above (§6.5 grants broad *adding* of evidence, not broad removal of
    evidence someone else added)."""
    project = db.get(Project, project_id)
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    link = db.scalar(
        select(PainPointFile).where(PainPointFile.pain_point_id == pain_point.id, PainPointFile.file_id == file_id)
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Pain Point.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=PAIN_POINT_ARTEFACT_TYPE, entity_id=pain_point.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Guiding Principles (Phase 4) --------------------------------------------
# =============================================================================


def _get_guiding_principle(db: Session, project_id: UUID, guiding_principle_id: UUID) -> GuidingPrinciple:
    return get_guiding_principle_in_scope(db, _GP_SCOPE, project_id=project_id, guiding_principle_id=guiding_principle_id)


def _require_gp_creator_or_manage(
    db: Session, current_user: User, project: Project, guiding_principle: GuidingPrinciple
) -> None:
    if current_user.id == guiding_principle.creator_id:
        return
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project.id,
    )


# --- Guiding Principle CRUD ---------------------------------------------------


@router.post("/guiding-principles", response_model=GuidingPrincipleOut, status_code=status.HTTP_201_CREATED)
def create_project_guiding_principle(
    project_id: UUID, payload: GuidingPrincipleCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Creates a project-scoped Guiding Principle in `DRAFT` status. Any
    project member with the module enabled may create one — no `guiding_
    principle_owner` grant required, same posture as Strategy/Future State
    creation."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    guiding_principle = create_guiding_principle(
        db, scope=_GP_SCOPE, organization_id=project.organization_id, project_id=project_id, creator=current_user,
        name=payload.name, principle_statement=payload.principle_statement, rationale=payload.rationale,
        priority=payload.priority, owner_id=payload.owner_id,
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(guiding_principle)
    return guiding_principle_to_out(guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id))


@router.get("/guiding-principles", response_model=list[GuidingPrincipleOut])
def list_project_guiding_principles(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    query = select(GuidingPrinciple).where(
        GuidingPrinciple.project_id == project_id, GuidingPrinciple.scope == _GP_SCOPE,
    )
    if not include_archived:
        query = query.where(GuidingPrinciple.is_archived.is_(False))
    guiding_principles = db.scalars(query.order_by(GuidingPrinciple.created_at)).all()
    return [
        guiding_principle_to_out(gp, get_current_guiding_principle_version(db, gp.id)) for gp in guiding_principles
    ]


@router.get("/guiding-principles/{guiding_principle_id}", response_model=GuidingPrincipleOut)
def get_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.put("/guiding-principles/{guiding_principle_id}", response_model=GuidingPrincipleOut)
def update_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleUpdate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Direct edit of a Guiding Principle's content (a new `GuidingPrinciple
    Version`, same status). 409s once the current version is locked (past
    `PROPOSED` — see `service.GUIDING_PRINCIPLE_LOCKED_STATUSES`)."""
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    if is_guiding_principle_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Guiding Principle is past review; its content can no longer be edited in place.",
        )
    apply_guiding_principle_new_version(
        db, guiding_principle, current_version, current_user,
        name=payload.name, principle_statement=payload.principle_statement, rationale=payload.rationale,
        priority=payload.priority, owner_id=payload.owner_id, owner_id_explicitly_set=True,
        change_note=payload.change_note,
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.get("/guiding-principles/{guiding_principle_id}/versions", response_model=list[GuidingPrincipleVersionOut])
def list_project_guiding_principle_versions(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    return list(guiding_principle.versions)


@router.post("/guiding-principles/{guiding_principle_id}/archive", response_model=GuidingPrincipleOut)
def archive_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    if guiding_principle.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Guiding Principle is already archived.")
    archive_guiding_principle(db, guiding_principle, current_user)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/unarchive", response_model=GuidingPrincipleOut)
def unarchive_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    if not guiding_principle.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Guiding Principle is not archived.")
    unarchive_guiding_principle(db, guiding_principle)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


# --- Guiding Principle lifecycle transitions ----------------------------------


@router.post("/guiding-principles/{guiding_principle_id}/propose", response_model=GuidingPrincipleOut)
def propose_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    _require_gp_creator_or_manage(db, current_user, project, guiding_principle)
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(propose_guiding_principle, db, guiding_principle, current_version, current_user)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/send-back", response_model=GuidingPrincipleOut)
def send_project_guiding_principle_back(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED` Guiding Principle back to `DRAFT` for rework —
    this module's "reject"-equivalent. A comment is required."""
    if not (payload.comment or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A comment is required to send a Guiding Principle back to draft.",
        )
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(
        send_guiding_principle_back_to_draft, db, guiding_principle, current_version, current_user,
        comment=payload.comment,
    )
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/approve", response_model=GuidingPrincipleOut)
def approve_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(
        approve_guiding_principle, db, guiding_principle, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/activate", response_model=GuidingPrincipleOut)
def activate_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Activates an approved Guiding Principle. MCP-reachable (Phase 6) —
    per the plan's own 2026-09-22 update, Guiding Principle's own
    `require_ai_approvals_enabled`-gated actions are `activate`/`retire`,
    not `approve` (see `service.py`'s own Phase 6 docstring for the
    reasoning) — same gate pattern as `approve_project_strategy`."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(
        activate_guiding_principle, db, guiding_principle, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/supersede", response_model=GuidingPrincipleOut)
def supersede_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(
        supersede_guiding_principle, db, guiding_principle, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/retire", response_model=GuidingPrincipleOut)
def retire_project_guiding_principle(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Retires a Guiding Principle. MCP-reachable (Phase 6) — same
    `require_ai_approvals_enabled` gate as `activate_project_guiding_
    principle`, see that endpoint's own docstring."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(
        retire_guiding_principle, db, guiding_principle, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


# --- Guiding Principle comments -----------------------------------------------


def _gp_comment_to_out(db: Session, comment: GuidingPrincipleComment) -> GuidingPrincipleCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(GuidingPrincipleCommentFile, GuidingPrincipleCommentFile.file_id == FileAsset.id)
        .where(GuidingPrincipleCommentFile.comment_id == comment.id)
    ).all()
    return GuidingPrincipleCommentOut(
        id=comment.id, guiding_principle_id=comment.guiding_principle_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post(
    "/guiding-principles/{guiding_principle_id}/comments", response_model=GuidingPrincipleCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_project_guiding_principle_comment(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleCommentCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    comment = GuidingPrincipleComment(
        guiding_principle_id=guiding_principle.id, author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.flush()
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _gp_comment_to_out(db, comment)


@router.get("/guiding-principles/{guiding_principle_id}/comments", response_model=list[GuidingPrincipleCommentOut])
def list_project_guiding_principle_comments(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    comments = db.scalars(
        select(GuidingPrincipleComment).where(GuidingPrincipleComment.guiding_principle_id == guiding_principle.id)
        .order_by(GuidingPrincipleComment.created_at)
    ).all()
    return [_gp_comment_to_out(db, c) for c in comments]


@router.patch(
    "/guiding-principles/{guiding_principle_id}/comments/{comment_id}", response_model=GuidingPrincipleCommentOut,
)
def edit_project_guiding_principle_comment(
    project_id: UUID, guiding_principle_id: UUID, comment_id: UUID, payload: GuidingPrincipleCommentUpdate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Guiding Principle Owner may edit someone
    else's words."""
    _get_guiding_principle(db, project_id, guiding_principle_id)
    comment = db.get(GuidingPrincipleComment, comment_id)
    if comment is None or comment.guiding_principle_id != guiding_principle_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _gp_comment_to_out(db, comment)


@router.post(
    "/guiding-principles/{guiding_principle_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_guiding_principle_comment_attachment(
    project_id: UUID, guiding_principle_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's identical comment-attachment pattern."""
    project = db.get(Project, project_id)
    _get_guiding_principle(db, project_id, guiding_principle_id)
    comment = db.get(GuidingPrincipleComment, comment_id)
    if comment is None or comment.guiding_principle_id != guiding_principle_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(GuidingPrincipleCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle_id,
              action="comment_file_attached", actor_id=current_user.id, project_id=project_id,
              detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/guiding-principles/{guiding_principle_id}/comments/{comment_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_guiding_principle_comment_attachment(
    project_id: UUID, guiding_principle_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    _get_guiding_principle(db, project_id, guiding_principle_id)
    comment = db.get(GuidingPrincipleComment, comment_id)
    if comment is None or comment.guiding_principle_id != guiding_principle_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(GuidingPrincipleCommentFile).where(
            GuidingPrincipleCommentFile.comment_id == comment.id, GuidingPrincipleCommentFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    db.commit()


# --- Guiding Principle direct file attachments --------------------------------


@router.post(
    "/guiding-principles/{guiding_principle_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_guiding_principle_file(
    project_id: UUID, guiding_principle_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Ordinary project-authorized upload, resolved via this module's own
    `resolve_file_owner_project_id` hook — see this module's own docstring
    for why (contrast `router.py`'s org-scoped, `is_org_resource=True`
    sibling)."""
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    if is_guiding_principle_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Guiding Principle is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(
        GuidingPrincipleFile(
            guiding_principle_id=guiding_principle.id, file_id=asset.id, linked_by=current_user.id,
            created_at=asset.created_at,
        )
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/guiding-principles/{guiding_principle_id}/files", response_model=list[FileAssetOut])
def list_project_guiding_principle_files(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    return db.scalars(
        select(FileAsset).join(GuidingPrincipleFile, GuidingPrincipleFile.file_id == FileAsset.id).where(
            GuidingPrincipleFile.guiding_principle_id == guiding_principle.id
        )
    ).all()


@router.delete("/guiding-principles/{guiding_principle_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_guiding_principle_file(
    project_id: UUID, guiding_principle_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    link = db.scalar(
        select(GuidingPrincipleFile).where(
            GuidingPrincipleFile.guiding_principle_id == guiding_principle.id, GuidingPrincipleFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Guiding Principle.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Open Questions (Phase 5) -------------------------------------------------
# =============================================================================


def _get_open_question(db: Session, project_id: UUID, open_question_id: UUID) -> OpenQuestion:
    return get_open_question_in_scope(db, project_id=project_id, open_question_id=open_question_id)


# --- Open Question CRUD -------------------------------------------------------


@router.post("/open-questions", response_model=OpenQuestionOut, status_code=status.HTTP_201_CREATED)
def create_project_open_question(
    project_id: UUID, payload: OpenQuestionCreate,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Creates an Open Question in `OPEN` status. Any project member with
    the module enabled may create one — no `open_question_owner` grant
    required (§9.4's broad-creation model)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    open_question = create_open_question(
        db, project_id=project_id, creator=current_user, question=payload.question, context=payload.context,
        evidence=payload.evidence, priority=payload.priority, due_date=payload.due_date,
    )
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"question": payload.question})
    db.commit()
    db.refresh(open_question)
    return open_question_to_out(open_question)


@router.get("/open-questions", response_model=list[OpenQuestionOut])
def list_project_open_questions(
    project_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    query = select(OpenQuestion).where(OpenQuestion.project_id == project_id)
    if not include_archived:
        query = query.where(OpenQuestion.is_archived.is_(False))
    open_questions = db.scalars(query.order_by(OpenQuestion.created_at)).all()
    return [open_question_to_out(oq) for oq in open_questions]


@router.get("/open-questions/{open_question_id}", response_model=OpenQuestionOut)
def get_project_open_question(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    open_question = _get_open_question(db, project_id, open_question_id)
    return open_question_to_out(open_question)


@router.put("/open-questions/{open_question_id}", response_model=OpenQuestionOut)
def update_project_open_question(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionUpdate,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Direct edit of an Open Question's content, including priority/owner/
    due date (§9.4's manager-tier "Assign"/"Prioritise"). Manager-only
    (`_shared.require_open_question_manage_role`) — see this module's own
    docstring for why the broad-creation model does not extend to a
    standing creator edit right. 409s once the Open Question has reached a
    terminal outcome (`service.OPEN_QUESTION_LOCKED_STATUSES`)."""
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if is_open_question_locked(open_question):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Open Question has reached a terminal outcome; its content can no longer be edited.",
        )
    update_open_question(
        db, open_question, question=payload.question, context=payload.context, evidence=payload.evidence,
        priority=payload.priority, owner_id=payload.owner_id, owner_id_explicitly_set=True,
        due_date=payload.due_date, due_date_explicitly_set=True,
    )
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return open_question_to_out(open_question)


@router.post("/open-questions/{open_question_id}/archive", response_model=OpenQuestionOut)
def archive_project_open_question(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if open_question.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Open Question is already archived.")
    archive_open_question(db, open_question, current_user)
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return open_question_to_out(open_question)


@router.post("/open-questions/{open_question_id}/unarchive", response_model=OpenQuestionOut)
def unarchive_project_open_question(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    if not open_question.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Open Question is not archived.")
    unarchive_open_question(db, open_question)
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    return open_question_to_out(open_question)


# --- Open Question lifecycle (branching) --------------------------------------


@router.post("/open-questions/{open_question_id}/investigate", response_model=OpenQuestionOut)
def investigate_project_open_question(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionTransitionRequest,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """`OPEN` -> `INVESTIGATING`. §9.4's "change status" tier — `open_
    question_owner`-gated."""
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(investigate_open_question, db, open_question, current_user, comment=payload.comment)
    db.commit()
    return open_question_to_out(open_question)


@router.post("/open-questions/{open_question_id}/mark-ready-for-decision", response_model=OpenQuestionOut)
def mark_project_open_question_ready_for_decision(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionTransitionRequest,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """`INVESTIGATING` -> `READY_FOR_DECISION`."""
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(
        mark_open_question_ready_for_decision, db, open_question, current_user, comment=payload.comment,
    )
    db.commit()
    return open_question_to_out(open_question)


@router.post("/open-questions/{open_question_id}/withdraw", response_model=OpenQuestionOut)
def withdraw_project_open_question(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionTransitionRequest,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """`INVESTIGATING`/`READY_FOR_DECISION` -> `WITHDRAWN`. A comment is
    required — §9.4's "Close" capability, `open_question_owner`-gated."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to withdraw an Open Question.")
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    apply_value_error_as_conflict(withdraw_open_question, db, open_question, current_user, comment=payload.comment)
    db.commit()
    return open_question_to_out(open_question)


@router.post("/open-questions/{open_question_id}/resolve", response_model=OpenQuestionOut)
def resolve_project_open_question(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionTransitionRequest,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """`READY_FOR_DECISION` -> `RESOLVED`. §9.4's "Decision Maker: Resolve
    through a Decision" tier — gated separately from `open_question_owner`
    (`_shared.require_open_question_resolve_permission`). A plain status
    transition here, not the actual "Create Decision from Open Question"
    workflow (§9.5, Module 4's own Phase 7) — see `service.resolve_open_
    question`'s own docstring. MCP-reachable (Phase 6) — same `require_ai_
    approvals_enabled` gate as `approve_project_strategy`, see that
    endpoint's own docstring."""
    project = db.get(Project, project_id)
    if channel == "mcp":
        require_ai_approvals_enabled(db, project)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_resolve_permission(
        db, current_user, organization_id=project.organization_id, project_id=project_id,
    )
    apply_value_error_as_conflict(resolve_open_question, db, open_question, current_user, comment=payload.comment)
    db.commit()
    return open_question_to_out(open_question)


# --- Open Question comments ----------------------------------------------------


def _oq_comment_to_out(db: Session, comment: OpenQuestionComment) -> OpenQuestionCommentOut:
    author = db.get(User, comment.author_id)
    attachments = db.scalars(
        select(FileAsset)
        .join(OpenQuestionCommentFile, OpenQuestionCommentFile.file_id == FileAsset.id)
        .where(OpenQuestionCommentFile.comment_id == comment.id)
    ).all()
    return OpenQuestionCommentOut(
        id=comment.id, open_question_id=comment.open_question_id, author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body, created_at=comment.created_at, edited_at=comment.edited_at,
        attachments=[FileAssetOut.model_validate(a) for a in attachments],
    )


@router.post(
    "/open-questions/{open_question_id}/comments", response_model=OpenQuestionCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_project_open_question_comment(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionCommentCreate,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Any project member with the module enabled may comment (§9.4) — this
    is also this artefact's mechanism for "Suggest resolution"."""
    open_question = _get_open_question(db, project_id, open_question_id)
    comment = OpenQuestionComment(open_question_id=open_question.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="comment_added",
              actor_id=current_user.id, project_id=project_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _oq_comment_to_out(db, comment)


@router.get("/open-questions/{open_question_id}/comments", response_model=list[OpenQuestionCommentOut])
def list_project_open_question_comments(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    open_question = _get_open_question(db, project_id, open_question_id)
    comments = db.scalars(
        select(OpenQuestionComment).where(OpenQuestionComment.open_question_id == open_question.id)
        .order_by(OpenQuestionComment.created_at)
    ).all()
    return [_oq_comment_to_out(db, c) for c in comments]


@router.patch("/open-questions/{open_question_id}/comments/{comment_id}", response_model=OpenQuestionCommentOut)
def edit_project_open_question_comment(
    project_id: UUID, open_question_id: UUID, comment_id: UUID, payload: OpenQuestionCommentUpdate,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Author-only — not even an Open Question Owner may edit someone
    else's words."""
    _get_open_question(db, project_id, open_question_id)
    comment = db.get(OpenQuestionComment, comment_id)
    if comment is None or comment.open_question_id != open_question_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may edit it.")
    comment.body = payload.body
    comment.edited_at = datetime.now(UTC)
    db.commit()
    db.refresh(comment)
    return _oq_comment_to_out(db, comment)


@router.post(
    "/open-questions/{open_question_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_open_question_comment_attachment(
    project_id: UUID, open_question_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's/Pain Point's identical comment-
    attachment pattern."""
    project = db.get(Project, project_id)
    _get_open_question(db, project_id, open_question_id)
    comment = db.get(OpenQuestionComment, comment_id)
    if comment is None or comment.open_question_id != open_question_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(OpenQuestionCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question_id, action="comment_file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/open-questions/{open_question_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_open_question_comment_attachment(
    project_id: UUID, open_question_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    _get_open_question(db, project_id, open_question_id)
    comment = db.get(OpenQuestionComment, comment_id)
    if comment is None or comment.open_question_id != open_question_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may remove its attachments.")
    link = db.scalar(
        select(OpenQuestionCommentFile).where(
            OpenQuestionCommentFile.comment_id == comment.id, OpenQuestionCommentFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this comment.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    db.commit()


# --- Open Question direct file attachments ("evidence") -----------------------


@router.post("/open-questions/{open_question_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_project_open_question_file(
    project_id: UUID, open_question_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """**Deliberately open to any project member**, not manager-gated —
    same asymmetric shape as `upload_project_pain_point_file` (§9.4
    explicitly lists "Add evidence" among the broad-creation-model
    capabilities every project member gets for an Open Question). Still
    409s once the Open Question has reached a terminal outcome."""
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    if is_open_question_locked(open_question):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This Open Question has reached a terminal outcome; new evidence can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(
        OpenQuestionFile(
            open_question_id=open_question.id, file_id=asset.id, linked_by=current_user.id,
            created_at=asset.created_at,
        )
    )
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/open-questions/{open_question_id}/files", response_model=list[FileAssetOut])
def list_project_open_question_files(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    open_question = _get_open_question(db, project_id, open_question_id)
    return db.scalars(
        select(FileAsset).join(OpenQuestionFile, OpenQuestionFile.file_id == FileAsset.id).where(
            OpenQuestionFile.open_question_id == open_question.id
        )
    ).all()


@router.delete("/open-questions/{open_question_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_project_open_question_file(
    project_id: UUID, open_question_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    """Manager-gated to remove — asymmetric with the open-to-all upload
    above, same as `unlink_project_pain_point_file`."""
    project = db.get(Project, project_id)
    open_question = _get_open_question(db, project_id, open_question_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    link = db.scalar(
        select(OpenQuestionFile).where(
            OpenQuestionFile.open_question_id == open_question.id, OpenQuestionFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Open Question.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=OPEN_QUESTION_ARTEFACT_TYPE, entity_id=open_question.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()


# --- Phase 6: cross-artefact relationships -----------------------------------
#
# List + create relationship endpoints for all five project-scoped source
# artefact types, plus supersession endpoints for the three that support
# one (Strategy/Future State/Guiding Principle — Pain Point/Open Question
# have no "supersedes" concept in their own lifecycles). See `service.py`'s
# own Phase 6 docstring section for the overall design and why Decision is
# not a valid `target_id` for any of these yet.


@router.get("/strategies/{strategy_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_project_strategy_relationships(
    project_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, project_id, strategy_id)
    links = get_all_links(db, STRATEGY_ARTEFACT_TYPE, strategy.id)
    return [context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=strategy.id) for link in links]


@router.post(
    "/strategies/{strategy_id}/relationships", response_model=ContextStrategyLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_project_strategy_relationship(
    project_id: UUID, strategy_id: UUID, payload: StrategyLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Gated by `require_manage_role` (the `strategy_owner`-tier role) —
    mirrors `routers.requirements.links.create_link`'s own precedent of
    requiring an edit-capable role to create a traceability relationship,
    not just view access."""
    strategy = _get_strategy(db, project_id, strategy_id)
    project = db.get(Project, project_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    link = apply_value_error_as_conflict(
        create_strategy_link, db, strategy=strategy, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": payload.kind.value, "strategy_id": str(strategy.id), "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=strategy.id)


@router.post(
    "/strategies/{strategy_id}/supersessions", response_model=ContextStrategyLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_project_strategy_supersession(
    project_id: UUID, strategy_id: UUID, payload: StrategySupersessionCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """`strategy_id` (the new Strategy) supersedes `payload.old_strategy_id`.
    Gated the same as the existing `/supersede` endpoint (`require_approve_
    permission`) — this endpoint performs the identical `ACTIVE ->
    SUPERSEDED` transition on the old Strategy, just also recording which
    Strategy superseded it."""
    new_strategy = _get_strategy(db, project_id, strategy_id)
    project = db.get(Project, project_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=project.organization_id, project_id=project_id)
    old_strategy = db.get(Strategy, payload.old_strategy_id)
    if old_strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_strategy_supersession, db, new_strategy=new_strategy, old_strategy=old_strategy,
        actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": "supersession", "new_strategy_id": str(new_strategy.id), "old_strategy_id": str(old_strategy.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=new_strategy.id)


@router.get("/future-states/{future_state_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_project_future_state_relationships(
    project_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    links = get_all_links(db, FUTURE_STATE_ARTEFACT_TYPE, future_state.id)
    return [
        context_strategy_link_to_out(db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=future_state.id)
        for link in links
    ]


@router.post(
    "/future-states/{future_state_id}/relationships", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_future_state_relationship(
    project_id: UUID, future_state_id: UUID, payload: FutureStateLinkCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, project_id, future_state_id)
    project = db.get(Project, project_id)
    require_future_state_manage_role(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    link = apply_value_error_as_conflict(
        create_future_state_link, db, future_state=future_state, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": payload.kind.value, "future_state_id": str(future_state.id), "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=future_state.id)


@router.post(
    "/future-states/{future_state_id}/supersessions", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_future_state_supersession(
    project_id: UUID, future_state_id: UUID, payload: FutureStateSupersessionCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    new_future_state = _get_future_state(db, project_id, future_state_id)
    project = db.get(Project, project_id)
    require_future_state_approve_permission(
        db, current_user, _FS_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    old_future_state = db.get(FutureState, payload.old_future_state_id)
    if old_future_state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Future State not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_future_state_supersession, db, new_future_state=new_future_state, old_future_state=old_future_state,
        actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": "supersession", "new_future_state_id": str(new_future_state.id),
                      "old_future_state_id": str(old_future_state.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=new_future_state.id,
    )


@router.get("/pain-points/{pain_point_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_project_pain_point_relationships(
    project_id: UUID, pain_point_id: UUID,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    links = get_all_links(db, PAIN_POINT_ARTEFACT_TYPE, pain_point.id)
    return [
        context_strategy_link_to_out(db, link, viewpoint_type=PAIN_POINT_ARTEFACT_TYPE, viewpoint_id=pain_point.id)
        for link in links
    ]


@router.post(
    "/pain-points/{pain_point_id}/relationships", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_pain_point_relationship(
    project_id: UUID, pain_point_id: UUID, payload: PainPointLinkCreate,
    current_user: User = Depends(_require_pain_point_view), db: Session = Depends(get_db),
):
    pain_point = _get_pain_point(db, project_id, pain_point_id)
    project = db.get(Project, project_id)
    require_pain_point_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    link = apply_value_error_as_conflict(
        create_pain_point_link, db, pain_point=pain_point, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": payload.kind.value, "pain_point_id": str(pain_point.id), "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=PAIN_POINT_ARTEFACT_TYPE, viewpoint_id=pain_point.id)


@router.get("/guiding-principles/{guiding_principle_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_project_guiding_principle_relationships(
    project_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    links = get_all_links(db, GUIDING_PRINCIPLE_ARTEFACT_TYPE, guiding_principle.id)
    return [
        context_strategy_link_to_out(
            db, link, viewpoint_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, viewpoint_id=guiding_principle.id,
        )
        for link in links
    ]


@router.post(
    "/guiding-principles/{guiding_principle_id}/relationships", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_guiding_principle_relationship(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleLinkCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    project = db.get(Project, project_id)
    require_guiding_principle_manage_role(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    link = apply_value_error_as_conflict(
        create_guiding_principle_link, db, guiding_principle=guiding_principle, kind=payload.kind,
        target_id=payload.target_id, actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": payload.kind.value, "guiding_principle_id": str(guiding_principle.id),
                      "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, viewpoint_id=guiding_principle.id,
    )


@router.post(
    "/guiding-principles/{guiding_principle_id}/supersessions", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_guiding_principle_supersession(
    project_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleSupersessionCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    new_guiding_principle = _get_guiding_principle(db, project_id, guiding_principle_id)
    project = db.get(Project, project_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=project.organization_id, project_id=project_id,
    )
    old_guiding_principle = db.get(GuidingPrinciple, payload.old_guiding_principle_id)
    if old_guiding_principle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guiding Principle not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_guiding_principle_supersession, db, new_guiding_principle=new_guiding_principle,
        old_guiding_principle=old_guiding_principle, actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": "supersession", "new_guiding_principle_id": str(new_guiding_principle.id),
                      "old_guiding_principle_id": str(old_guiding_principle.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, viewpoint_id=new_guiding_principle.id,
    )


@router.get("/open-questions/{open_question_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_project_open_question_relationships(
    project_id: UUID, open_question_id: UUID,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    open_question = _get_open_question(db, project_id, open_question_id)
    links = get_all_links(db, OPEN_QUESTION_ARTEFACT_TYPE, open_question.id)
    return [
        context_strategy_link_to_out(db, link, viewpoint_type=OPEN_QUESTION_ARTEFACT_TYPE, viewpoint_id=open_question.id)
        for link in links
    ]


@router.post(
    "/open-questions/{open_question_id}/relationships", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_open_question_relationship(
    project_id: UUID, open_question_id: UUID, payload: OpenQuestionLinkCreate,
    current_user: User = Depends(_require_open_question_view), db: Session = Depends(get_db),
):
    open_question = _get_open_question(db, project_id, open_question_id)
    project = db.get(Project, project_id)
    require_open_question_manage_role(db, current_user, organization_id=project.organization_id, project_id=project_id)
    link = apply_value_error_as_conflict(
        create_open_question_link, db, open_question=open_question, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"kind": payload.kind.value, "open_question_id": str(open_question.id),
                      "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=OPEN_QUESTION_ARTEFACT_TYPE, viewpoint_id=open_question.id,
    )


# Phases 12/12b: reports (core `services.report_framework`, declared in `reports.py`).
router.include_router(REPORT_ROUTERS.project)
