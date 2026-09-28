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
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy._shared import (
    apply_value_error_as_conflict,
    future_state_to_out,
    get_future_state_in_scope,
    get_strategy_in_scope,
    require_approve_permission,
    require_future_state_approve_permission,
    require_future_state_manage_role,
    require_manage_role,
    strategy_to_out,
)
from app.modules.context_strategy.enums import FutureStateScope, StrategyScope
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateComment,
    FutureStateCommentFile,
    FutureStateFile,
    Strategy,
    StrategyComment,
    StrategyCommentFile,
    StrategyFile,
)
from app.modules.context_strategy.schemas import (
    FutureStateCommentCreate,
    FutureStateCommentOut,
    FutureStateCommentUpdate,
    FutureStateCreate,
    FutureStateOut,
    FutureStateTransitionRequest,
    FutureStateUpdate,
    FutureStateVersionOut,
    StrategyCommentCreate,
    StrategyCommentOut,
    StrategyCommentUpdate,
    StrategyCreate,
    StrategyOut,
    StrategyTransitionRequest,
    StrategyUpdate,
    StrategyVersionOut,
)
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    STRATEGY_ARTEFACT_TYPE,
    activate_future_state,
    activate_strategy,
    apply_future_state_new_version,
    apply_new_version,
    approve_future_state,
    approve_strategy,
    archive_future_state,
    archive_strategy,
    create_future_state,
    create_strategy,
    get_current_future_state_version,
    get_current_version,
    is_future_state_locked,
    is_locked,
    propose_future_state,
    propose_strategy,
    retire_future_state,
    retire_strategy,
    send_future_state_back_to_draft,
    send_strategy_back_to_draft,
    submit_future_state_for_review,
    submit_strategy_for_review,
    supersede_future_state,
    supersede_strategy,
    unarchive_future_state,
    unarchive_strategy,
)
from app.schemas.file import FileAssetOut
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.rbac import require_project_subcomponent_enabled

router = APIRouter(prefix="/api/v1/projects/{project_id}/modules/context_strategy", tags=["context-strategy-project"])

_SCOPE = StrategyScope.PROJECT
_require_view = require_project_subcomponent_enabled("context_strategy", "strategy")

_FS_SCOPE = FutureStateScope.PROJECT
_require_future_state_view = require_project_subcomponent_enabled("context_strategy", "future_state")


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
):
    project = db.get(Project, project_id)
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
):
    project = db.get(Project, project_id)
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
