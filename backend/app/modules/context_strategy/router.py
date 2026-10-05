"""
Module: modules.context_strategy.router

Context & Strategy's Phase 1 org-scoped API (docs/plans/module-01-context-
and-strategy-plan.md Phase 1) — CRUD, lifecycle transitions, comments, and
file attachments for **organisation-scoped** Strategy records. Mounted at
`/api/v1/orgs/{organization_id}/modules/context_strategy`.

Phase 2 adds the same surface for **organisation-scoped** Future State
records, at `/future-states` (this module's own established hyphenated
multi-word URL-segment convention — see e.g. `modules.compliance`'s
`/action-types`), gated by `require_org_subcomponent_enabled
("context_strategy", "future_state")` and `_shared.require_future_state_
manage_role`/`require_future_state_approve_permission` — exact structural
mirror of the Strategy surface below, under distinct function names.

Phase 4 adds the same surface for **organisation-scoped** Guiding
Principle records, at `/guiding-principles`, gated by `require_org_
subcomponent_enabled("context_strategy", "guiding_principle")` and
`_shared.require_guiding_principle_manage_role`/`require_guiding_principle_
approve_permission` — exact structural mirror of the Strategy/Future State
surfaces, minus the `submit-for-review` endpoint (`enums.
GuidingPrincipleStatus` has no `UNDER_REVIEW` state to submit into).

RBAC: reads/creation are gated by `require_org_subcomponent_enabled
("context_strategy", "strategy")` (`_require_view`) — any org member with
the module *and* this sub-component enabled may browse and propose a
Strategy ("project members (View + Propose)" from the plan's Phase 1,
applied at org scope by direct analogy). Module 0 (Platform Foundations)
Phase 4's own org-scoped-gating design question (see that plan's Phase 4
section and `docs/decisions.md`'s "Module 0 (Platform Foundations) Phase
4" entry): an org-scoped Strategy has no `project_id` for a project-level
override to key against at all, so `require_org_subcomponent_enabled`
resolves purely from the organisation's own default (`app.modules.
registry.is_org_module_subcomponent_enabled`) rather than reusing
`require_project_subcomponent_enabled`'s two-tier resolution — it still
checks whole-module enablement first internally, so this is a strict
narrowing of the whole-module check this router originally used, not a
parallel/replacement one. Direct edits/archival require the `org_strategy_owner` module role
(`_shared.require_manage_role`); approve/activate/supersede/retire require
`org_strategy_approver` or an equivalent Fine-Grained Access Control
permission grant (`_shared.require_approve_permission`). See `_shared.py`
for the full composition rules (server admin / `OrgRole.ORG_ADMIN` /
direct grant / custom-role grant).

An org-scoped Strategy's file attachments are uploaded as organisation
shared resources (`FileAsset.is_org_resource=True`), authorized purely by
org membership through `routers.files.download_file`'s existing
`is_org_resource` branch — unlike `project_router.py`'s project-scoped
Strategy files, this module's `resolve_file_owner_project_id` hook is
never consulted for these.

See `project_router.py`'s own module docstring for the project-scoped
sibling of this router, and `_shared.py` for the helpers both share.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.user import User
from app.modules.context_strategy._shared import (
    apply_value_error_as_conflict,
    context_strategy_link_to_out,
    future_state_to_out,
    get_future_state_in_scope,
    get_guiding_principle_in_scope,
    get_strategy_in_scope,
    guiding_principle_to_out,
    require_approve_permission,
    require_future_state_approve_permission,
    require_future_state_manage_role,
    require_guiding_principle_approve_permission,
    require_guiding_principle_manage_role,
    require_manage_role,
    require_pain_point_type_admin_role,
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
    PainPointTypeDefinition,
    Strategy,
    StrategyComment,
    StrategyCommentFile,
    StrategyFile,
)
from app.modules.context_strategy.report_router import org_reports_router
from app.modules.context_strategy.schemas import (
    ContextStrategyLinkOut,
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
    PainPointTypeCreate,
    PainPointTypeOut,
    PainPointTypeUpdate,
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
    STRATEGY_ARTEFACT_TYPE,
    activate_future_state,
    activate_guiding_principle,
    activate_strategy,
    apply_future_state_new_version,
    apply_guiding_principle_new_version,
    apply_new_version,
    approve_future_state,
    approve_guiding_principle,
    approve_strategy,
    archive_future_state,
    archive_guiding_principle,
    archive_strategy,
    create_future_state,
    create_future_state_link,
    create_future_state_supersession,
    create_guiding_principle,
    create_guiding_principle_link,
    create_guiding_principle_supersession,
    create_org_pain_point_type,
    create_strategy,
    create_strategy_link,
    create_strategy_supersession,
    delete_org_pain_point_type,
    get_current_future_state_version,
    get_current_guiding_principle_version,
    get_current_version,
    is_future_state_locked,
    is_guiding_principle_locked,
    is_locked,
    propose_future_state,
    propose_guiding_principle,
    propose_strategy,
    retire_future_state,
    retire_guiding_principle,
    retire_strategy,
    send_future_state_back_to_draft,
    send_guiding_principle_back_to_draft,
    send_strategy_back_to_draft,
    submit_future_state_for_review,
    submit_strategy_for_review,
    supersede_future_state,
    supersede_guiding_principle,
    supersede_strategy,
    unarchive_future_state,
    unarchive_guiding_principle,
    unarchive_strategy,
)
from app.schemas.file import FileAssetOut
from app.schemas.project import MoveDirection
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.ordering import move_ordered
from app.services.rbac import require_org_subcomponent_enabled
from app.services.relationships import get_all_links

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/modules/context_strategy", tags=["context-strategy-org"])

_SCOPE = StrategyScope.ORGANIZATION
_require_view = require_org_subcomponent_enabled("context_strategy", "strategy")

_FS_SCOPE = FutureStateScope.ORGANIZATION
_require_future_state_view = require_org_subcomponent_enabled("context_strategy", "future_state")

_GP_SCOPE = GuidingPrincipleScope.ORGANIZATION
_require_guiding_principle_view = require_org_subcomponent_enabled("context_strategy", "guiding_principle")


def _get_strategy(db: Session, organization_id: UUID, strategy_id: UUID) -> Strategy:
    return get_strategy_in_scope(db, _SCOPE, organization_id=organization_id, strategy_id=strategy_id)


def _require_creator_or_manage(db: Session, current_user: User, organization_id: UUID, strategy: Strategy) -> None:
    if current_user.id == strategy.creator_id:
        return
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)


# --- Strategy CRUD -----------------------------------------------------------


@router.post("/strategies", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def create_org_strategy(
    organization_id: UUID, payload: StrategyCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates an organisation-scoped Strategy in `DRAFT` status. Any org
    member with the module enabled may create one — no `org_strategy_owner`
    grant required (Phase 1's "project members (View + Propose)", applied
    at org scope)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    strategy = create_strategy(
        db, scope=_SCOPE, organization_id=organization_id, project_id=None, creator=current_user,
        title=payload.title, objective=payload.objective, current_state=payload.current_state,
        desired_future_state=payload.desired_future_state, rationale=payload.rationale,
        expected_outcomes=payload.expected_outcomes, constraints=payload.constraints,
        measures_of_success=payload.measures_of_success, priority=payload.priority, time_horizon=payload.time_horizon,
    )
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"title": payload.title})
    db.commit()
    db.refresh(strategy)
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.get("/strategies", response_model=list[StrategyOut])
def list_org_strategies(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    query = select(Strategy).where(Strategy.organization_id == organization_id, Strategy.scope == _SCOPE)
    if not include_archived:
        query = query.where(Strategy.is_archived.is_(False))
    strategies = db.scalars(query.order_by(Strategy.created_at)).all()
    return [strategy_to_out(s, get_current_version(db, s.id)) for s in strategies]


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
def get_org_strategy(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
def update_org_strategy(
    organization_id: UUID, strategy_id: UUID, payload: StrategyUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Direct edit of a Strategy's content (a new `StrategyVersion`, same
    status). 409s once the current version is locked (past `UNDER_REVIEW`
    — see `service.LOCKED_STATUSES`)."""
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
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
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.get("/strategies/{strategy_id}/versions", response_model=list[StrategyVersionOut])
def list_org_strategy_versions(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    return list(strategy.versions)


@router.post("/strategies/{strategy_id}/archive", response_model=StrategyOut)
def archive_org_strategy(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    if strategy.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Strategy is already archived.")
    archive_strategy(db, strategy, current_user)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/unarchive", response_model=StrategyOut)
def unarchive_org_strategy(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    if not strategy.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Strategy is not archived.")
    unarchive_strategy(db, strategy)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


# --- Lifecycle transitions ---------------------------------------------------


@router.post("/strategies/{strategy_id}/propose", response_model=StrategyOut)
def propose_org_strategy(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    _require_creator_or_manage(db, current_user, organization_id, strategy)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(propose_strategy, db, strategy, current_version, current_user)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/submit-for-review", response_model=StrategyOut)
def submit_org_strategy_for_review(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    _require_creator_or_manage(db, current_user, organization_id, strategy)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(submit_strategy_for_review, db, strategy, current_version, current_user)
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/send-back", response_model=StrategyOut)
def send_org_strategy_back(
    organization_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED`/`UNDER_REVIEW` Strategy back to `DRAFT` for
    rework — this module's "reject"-equivalent (see `enums.StrategyStatus`'s
    own docstring). A comment is required, mirroring every other mandatory-
    comment-on-rejection rule in this codebase."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to send a Strategy back to draft.")
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        send_strategy_back_to_draft, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/approve", response_model=StrategyOut)
def approve_org_strategy(
    organization_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        approve_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/activate", response_model=StrategyOut)
def activate_org_strategy(
    organization_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        activate_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/supersede", response_model=StrategyOut)
def supersede_org_strategy(
    organization_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_version(db, strategy.id)
    apply_value_error_as_conflict(
        supersede_strategy, db, strategy, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return strategy_to_out(strategy, get_current_version(db, strategy.id))


@router.post("/strategies/{strategy_id}/retire", response_model=StrategyOut)
def retire_org_strategy(
    organization_id: UUID, strategy_id: UUID, payload: StrategyTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
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
def add_org_strategy_comment(
    organization_id: UUID, strategy_id: UUID, payload: StrategyCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    comment = StrategyComment(strategy_id=strategy.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="comment_added",
              actor_id=current_user.id, organization_id=organization_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _comment_to_out(db, comment)


@router.get("/strategies/{strategy_id}/comments", response_model=list[StrategyCommentOut])
def list_org_strategy_comments(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    comments = db.scalars(
        select(StrategyComment).where(StrategyComment.strategy_id == strategy.id).order_by(StrategyComment.created_at)
    ).all()
    return [_comment_to_out(db, c) for c in comments]


@router.patch("/strategies/{strategy_id}/comments/{comment_id}", response_model=StrategyCommentOut)
def edit_org_strategy_comment(
    organization_id: UUID, strategy_id: UUID, comment_id: UUID, payload: StrategyCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Strategy Owner may edit someone else's words."""
    _get_strategy(db, organization_id, strategy_id)
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
async def upload_org_strategy_comment_attachment(
    organization_id: UUID, strategy_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors `modules.decisions.project_router.comments.
    upload_decision_comment_attachment`'s pattern exactly."""
    _get_strategy(db, organization_id, strategy_id)
    comment = db.get(StrategyComment, comment_id)
    if comment is None or comment.strategy_id != strategy_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(StrategyCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy_id, action="comment_file_attached",
              actor_id=current_user.id, organization_id=organization_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/strategies/{strategy_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_strategy_comment_attachment(
    organization_id: UUID, strategy_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _get_strategy(db, organization_id, strategy_id)
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
async def upload_org_strategy_file(
    organization_id: UUID, strategy_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Uploaded as an organisation shared resource (`is_org_resource=True`)
    — see this module's own docstring for why an org-scoped Strategy's
    files are authorized by org membership alone, not this module's
    `resolve_file_owner_project_id` hook."""
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_version(db, strategy.id)
    if is_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Strategy is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
        is_org_resource=True,
    )
    db.flush()
    db.add(StrategyFile(strategy_id=strategy.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at))
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="file_attached",
              actor_id=current_user.id, organization_id=organization_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/strategies/{strategy_id}/files", response_model=list[FileAssetOut])
def list_org_strategy_files(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    return db.scalars(
        select(FileAsset).join(StrategyFile, StrategyFile.file_id == FileAsset.id).where(
            StrategyFile.strategy_id == strategy.id
        )
    ).all()


@router.delete("/strategies/{strategy_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_strategy_file(
    organization_id: UUID, strategy_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    link = db.scalar(select(StrategyFile).where(StrategyFile.strategy_id == strategy.id, StrategyFile.file_id == file_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this Strategy.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None:
        delete_file(db, asset)
    log_event(db, entity_type=STRATEGY_ARTEFACT_TYPE, entity_id=strategy.id, action="file_unlinked",
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Future State (Phase 2) -------------------------------------------------
# =============================================================================


def _get_future_state(db: Session, organization_id: UUID, future_state_id: UUID) -> FutureState:
    return get_future_state_in_scope(db, _FS_SCOPE, organization_id=organization_id, future_state_id=future_state_id)


def _require_fs_creator_or_manage(db: Session, current_user: User, organization_id: UUID, future_state: FutureState) -> None:
    if current_user.id == future_state.creator_id:
        return
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)


# --- Future State CRUD -------------------------------------------------------


@router.post("/future-states", response_model=FutureStateOut, status_code=status.HTTP_201_CREATED)
def create_org_future_state(
    organization_id: UUID, payload: FutureStateCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Creates an organisation-scoped Future State in `DRAFT` status. Any
    org member with the module enabled may create one — no `org_future_
    state_owner` grant required, same posture as Strategy creation."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    future_state = create_future_state(
        db, scope=_FS_SCOPE, organization_id=organization_id, project_id=None, creator=current_user,
        title=payload.title, current_state=payload.current_state, desired_state=payload.desired_state,
        target_date=payload.target_date, outcomes=payload.outcomes, success_measures=payload.success_measures,
        constraints=payload.constraints, assumptions=payload.assumptions,
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"title": payload.title})
    db.commit()
    db.refresh(future_state)
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.get("/future-states", response_model=list[FutureStateOut])
def list_org_future_states(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    query = select(FutureState).where(FutureState.organization_id == organization_id, FutureState.scope == _FS_SCOPE)
    if not include_archived:
        query = query.where(FutureState.is_archived.is_(False))
    future_states = db.scalars(query.order_by(FutureState.created_at)).all()
    return [future_state_to_out(fs, get_current_future_state_version(db, fs.id)) for fs in future_states]


@router.get("/future-states/{future_state_id}", response_model=FutureStateOut)
def get_org_future_state(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.put("/future-states/{future_state_id}", response_model=FutureStateOut)
def update_org_future_state(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateUpdate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Direct edit of a Future State's content (a new `FutureStateVersion`,
    same status). 409s once the current version is locked."""
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
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
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.get("/future-states/{future_state_id}/versions", response_model=list[FutureStateVersionOut])
def list_org_future_state_versions(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    return list(future_state.versions)


@router.post("/future-states/{future_state_id}/archive", response_model=FutureStateOut)
def archive_org_future_state(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    if future_state.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Future State is already archived.")
    archive_future_state(db, future_state, current_user)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/unarchive", response_model=FutureStateOut)
def unarchive_org_future_state(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    if not future_state.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Future State is not archived.")
    unarchive_future_state(db, future_state)
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


# --- Future State lifecycle transitions --------------------------------------


@router.post("/future-states/{future_state_id}/propose", response_model=FutureStateOut)
def propose_org_future_state(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    _require_fs_creator_or_manage(db, current_user, organization_id, future_state)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(propose_future_state, db, future_state, current_version, current_user)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/submit-for-review", response_model=FutureStateOut)
def submit_org_future_state_for_review(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    _require_fs_creator_or_manage(db, current_user, organization_id, future_state)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(submit_future_state_for_review, db, future_state, current_version, current_user)
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/send-back", response_model=FutureStateOut)
def send_org_future_state_back(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED`/`UNDER_REVIEW` Future State back to `DRAFT` for
    rework. A comment is required, mirroring Strategy's identical rule."""
    if not (payload.comment or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required to send a Future State back to draft.")
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        send_future_state_back_to_draft, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/approve", response_model=FutureStateOut)
def approve_org_future_state(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        approve_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/activate", response_model=FutureStateOut)
def activate_org_future_state(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        activate_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/supersede", response_model=FutureStateOut)
def supersede_org_future_state(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_future_state_version(db, future_state.id)
    apply_value_error_as_conflict(
        supersede_future_state, db, future_state, current_version, current_user, comment=payload.comment,
    )
    db.commit()
    return future_state_to_out(future_state, get_current_future_state_version(db, future_state.id))


@router.post("/future-states/{future_state_id}/retire", response_model=FutureStateOut)
def retire_org_future_state(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateTransitionRequest,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
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
def add_org_future_state_comment(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateCommentCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    comment = FutureStateComment(future_state_id=future_state.id, author_id=current_user.id, body=payload.body)
    db.add(comment)
    db.flush()
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="comment_added",
              actor_id=current_user.id, organization_id=organization_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _fs_comment_to_out(db, comment)


@router.get("/future-states/{future_state_id}/comments", response_model=list[FutureStateCommentOut])
def list_org_future_state_comments(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    comments = db.scalars(
        select(FutureStateComment).where(FutureStateComment.future_state_id == future_state.id)
        .order_by(FutureStateComment.created_at)
    ).all()
    return [_fs_comment_to_out(db, c) for c in comments]


@router.patch("/future-states/{future_state_id}/comments/{comment_id}", response_model=FutureStateCommentOut)
def edit_org_future_state_comment(
    organization_id: UUID, future_state_id: UUID, comment_id: UUID, payload: FutureStateCommentUpdate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Future State Owner may edit someone else's words."""
    _get_future_state(db, organization_id, future_state_id)
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
async def upload_org_future_state_comment_attachment(
    organization_id: UUID, future_state_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's identical comment-attachment pattern."""
    _get_future_state(db, organization_id, future_state_id)
    comment = db.get(FutureStateComment, comment_id)
    if comment is None or comment.future_state_id != future_state_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(FutureStateCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state_id, action="comment_file_attached",
              actor_id=current_user.id, organization_id=organization_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/future-states/{future_state_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def remove_org_future_state_comment_attachment(
    organization_id: UUID, future_state_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    _get_future_state(db, organization_id, future_state_id)
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
async def upload_org_future_state_file(
    organization_id: UUID, future_state_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    """Uploaded as an organisation shared resource (`is_org_resource=True`)
    — same reasoning as Strategy's own org-scoped file uploads."""
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_future_state_version(db, future_state.id)
    if is_future_state_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Future State is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
        is_org_resource=True,
    )
    db.flush()
    db.add(
        FutureStateFile(
            future_state_id=future_state.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at,
        )
    )
    log_event(db, entity_type=FUTURE_STATE_ARTEFACT_TYPE, entity_id=future_state.id, action="file_attached",
              actor_id=current_user.id, organization_id=organization_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/future-states/{future_state_id}/files", response_model=list[FileAssetOut])
def list_org_future_state_files(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    return db.scalars(
        select(FileAsset).join(FutureStateFile, FutureStateFile.file_id == FileAsset.id).where(
            FutureStateFile.future_state_id == future_state.id
        )
    ).all()


@router.delete("/future-states/{future_state_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_future_state_file(
    organization_id: UUID, future_state_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
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
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(file_id)})
    db.commit()


# =============================================================================
# --- Pain Point types (Phase 3) ----------------------------------------------
# =============================================================================
#
# Organisation-scoped `PainPointTypeDefinition` CRUD only (Phase 0 Q3's
# shared base tier) — the Pain Point *artefact* itself is project-scoped
# only (source overview §6) and lives entirely in `project_router.py`,
# alongside the project-scoped `ProjectPainPointType` override/local-type
# endpoints. Reads are gated by `require_org_subcomponent_enabled
# ("context_strategy", "pain_point")` (any org member with the module and
# this sub-component enabled may browse); mutations additionally require
# the `pain_point_type_admin` module role (`_shared.require_pain_point_
# type_admin_role`) — mirrors `modules.compliance.router.action_types`'
# `_require_manage`/`_require_view` split, applied inline (per this
# module's own "Depends for view, inline call for elevated role"
# convention throughout `router.py`/`project_router.py`) rather than a
# second `Depends` dependency.

_require_pain_point_type_view = require_org_subcomponent_enabled("context_strategy", "pain_point")


@router.post("/pain-point-types", response_model=PainPointTypeOut, status_code=status.HTTP_201_CREATED)
def create_pain_point_type(
    organization_id: UUID, payload: PainPointTypeCreate,
    current_user: User = Depends(_require_pain_point_type_view), db: Session = Depends(get_db),
):
    """Creates a new organisation-scoped Pain Point type (§6.2 "Add types")."""
    require_pain_point_type_admin_role(db, current_user, organization_id=organization_id)
    try:
        pain_point_type = create_org_pain_point_type(db, organization_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="pain_point_type_definition", entity_id=pain_point_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": pain_point_type.name})
    db.commit()
    db.refresh(pain_point_type)
    return pain_point_type


@router.get("/pain-point-types", response_model=list[PainPointTypeOut])
def list_pain_point_types(
    organization_id: UUID, current_user: User = Depends(_require_pain_point_type_view), db: Session = Depends(get_db),
):
    """Lists this organisation's Pain Point types, including inactive ones
    (an org admin managing the vocabulary needs to see and re-activate a
    disabled type, not just the active subset a project's effective list
    resolves to)."""
    return db.scalars(
        select(PainPointTypeDefinition)
        .where(PainPointTypeDefinition.organization_id == organization_id)
        .order_by(PainPointTypeDefinition.sort_order)
    ).all()


@router.post("/pain-point-types/{pain_point_type_id}/move", response_model=PainPointTypeOut)
def move_pain_point_type(
    organization_id: UUID, pain_point_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(_require_pain_point_type_view), db: Session = Depends(get_db),
):
    """Moves a Pain Point type up/down in display order (§6.2 "Reorder types")."""
    require_pain_point_type_admin_role(db, current_user, organization_id=organization_id)
    result = move_ordered(
        db, PainPointTypeDefinition, [PainPointTypeDefinition.organization_id == organization_id],
        pain_point_type_id, payload.direction,
    )
    log_event(db, entity_type="pain_point_type_definition", entity_id=pain_point_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/pain-point-types/{pain_point_type_id}", response_model=PainPointTypeOut)
def update_pain_point_type(
    organization_id: UUID, pain_point_type_id: UUID, payload: PainPointTypeUpdate,
    current_user: User = Depends(_require_pain_point_type_view), db: Session = Depends(get_db),
):
    """Renames and/or activates/deactivates a Pain Point type (§6.2
    "Rename types"/"Disable types"). Every `ProjectPainPointType.
    org_type_id` reference points at this row's id, never its name, so
    renaming has zero effect on existing project overrides."""
    require_pain_point_type_admin_role(db, current_user, organization_id=organization_id)
    pain_point_type = db.get(PainPointTypeDefinition, pain_point_type_id)
    if pain_point_type is None or pain_point_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pain Point type not found.")
    if payload.name is not None:
        existing = db.scalar(
            select(PainPointTypeDefinition.id).where(
                PainPointTypeDefinition.organization_id == organization_id,
                PainPointTypeDefinition.name == payload.name, PainPointTypeDefinition.id != pain_point_type_id,
            )
        )
        if existing is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Pain Point type with this name already exists.")
        pain_point_type.name = payload.name
    if payload.is_active is not None:
        pain_point_type.is_active = payload.is_active
    log_event(db, entity_type="pain_point_type_definition", entity_id=pain_point_type.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(pain_point_type)
    return pain_point_type


@router.delete("/pain-point-types/{pain_point_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pain_point_type(
    organization_id: UUID, pain_point_type_id: UUID,
    current_user: User = Depends(_require_pain_point_type_view), db: Session = Depends(get_db),
):
    """Deletes an organisation-scoped Pain Point type (§6.2 "Remove types
    where no longer used") — 409s if any project still references it
    (`service.delete_org_pain_point_type`'s own docstring)."""
    require_pain_point_type_admin_role(db, current_user, organization_id=organization_id)
    pain_point_type = db.get(PainPointTypeDefinition, pain_point_type_id)
    if pain_point_type is None or pain_point_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pain Point type not found.")
    apply_value_error_as_conflict(delete_org_pain_point_type, db, pain_point_type)
    log_event(db, entity_type="pain_point_type_definition", entity_id=pain_point_type_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


# =============================================================================
# --- Guiding Principles (Phase 4) --------------------------------------------
# =============================================================================


def _get_guiding_principle(db: Session, organization_id: UUID, guiding_principle_id: UUID) -> GuidingPrinciple:
    return get_guiding_principle_in_scope(
        db, _GP_SCOPE, organization_id=organization_id, guiding_principle_id=guiding_principle_id,
    )


def _require_gp_creator_or_manage(
    db: Session, current_user: User, organization_id: UUID, guiding_principle: GuidingPrinciple
) -> None:
    if current_user.id == guiding_principle.creator_id:
        return
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)


# --- Guiding Principle CRUD ---------------------------------------------------


@router.post("/guiding-principles", response_model=GuidingPrincipleOut, status_code=status.HTTP_201_CREATED)
def create_org_guiding_principle(
    organization_id: UUID, payload: GuidingPrincipleCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Creates an organisation-scoped Guiding Principle in `DRAFT` status.
    Any org member with the module enabled may create one — no `org_
    guiding_principle_owner` grant required, same posture as Strategy/
    Future State creation."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    guiding_principle = create_guiding_principle(
        db, scope=_GP_SCOPE, organization_id=organization_id, project_id=None, creator=current_user,
        name=payload.name, principle_statement=payload.principle_statement, rationale=payload.rationale,
        priority=payload.priority, owner_id=payload.owner_id,
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": payload.name})
    db.commit()
    db.refresh(guiding_principle)
    return guiding_principle_to_out(guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id))


@router.get("/guiding-principles", response_model=list[GuidingPrincipleOut])
def list_org_guiding_principles(
    organization_id: UUID, include_archived: bool = False,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    query = select(GuidingPrinciple).where(
        GuidingPrinciple.organization_id == organization_id, GuidingPrinciple.scope == _GP_SCOPE,
    )
    if not include_archived:
        query = query.where(GuidingPrinciple.is_archived.is_(False))
    guiding_principles = db.scalars(query.order_by(GuidingPrinciple.created_at)).all()
    return [
        guiding_principle_to_out(gp, get_current_guiding_principle_version(db, gp.id)) for gp in guiding_principles
    ]


@router.get("/guiding-principles/{guiding_principle_id}", response_model=GuidingPrincipleOut)
def get_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.put("/guiding-principles/{guiding_principle_id}", response_model=GuidingPrincipleOut)
def update_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleUpdate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Direct edit of a Guiding Principle's content (a new `GuidingPrinciple
    Version`, same status). 409s once the current version is locked (past
    `PROPOSED` — see `service.GUIDING_PRINCIPLE_LOCKED_STATUSES`)."""
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
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
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.get("/guiding-principles/{guiding_principle_id}/versions", response_model=list[GuidingPrincipleVersionOut])
def list_org_guiding_principle_versions(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    return list(guiding_principle.versions)


@router.post("/guiding-principles/{guiding_principle_id}/archive", response_model=GuidingPrincipleOut)
def archive_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
    if guiding_principle.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Guiding Principle is already archived.")
    archive_guiding_principle(db, guiding_principle, current_user)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/unarchive", response_model=GuidingPrincipleOut)
def unarchive_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
    if not guiding_principle.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Guiding Principle is not archived.")
    unarchive_guiding_principle(db, guiding_principle)
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


# --- Guiding Principle lifecycle transitions ----------------------------------


@router.post("/guiding-principles/{guiding_principle_id}/propose", response_model=GuidingPrincipleOut)
def propose_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    _require_gp_creator_or_manage(db, current_user, organization_id, guiding_principle)
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    apply_value_error_as_conflict(propose_guiding_principle, db, guiding_principle, current_version, current_user)
    db.commit()
    return guiding_principle_to_out(
        guiding_principle, get_current_guiding_principle_version(db, guiding_principle.id)
    )


@router.post("/guiding-principles/{guiding_principle_id}/send-back", response_model=GuidingPrincipleOut)
def send_org_guiding_principle_back(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Sends a `PROPOSED` Guiding Principle back to `DRAFT` for rework —
    this module's "reject"-equivalent (see `enums.GuidingPrincipleStatus`'s
    own docstring). A comment is required, mirroring every other
    mandatory-comment-on-rejection rule in this codebase."""
    if not (payload.comment or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A comment is required to send a Guiding Principle back to draft.",
        )
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
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
def approve_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
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
def activate_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
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
def supersede_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
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
def retire_org_guiding_principle(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleTransitionRequest,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
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
def add_org_guiding_principle_comment(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleCommentCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    comment = GuidingPrincipleComment(
        guiding_principle_id=guiding_principle.id, author_id=current_user.id, body=payload.body,
    )
    db.add(comment)
    db.flush()
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="comment_added",
              actor_id=current_user.id, organization_id=organization_id, detail={"comment_id": str(comment.id)})
    db.commit()
    db.refresh(comment)
    return _gp_comment_to_out(db, comment)


@router.get("/guiding-principles/{guiding_principle_id}/comments", response_model=list[GuidingPrincipleCommentOut])
def list_org_guiding_principle_comments(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    comments = db.scalars(
        select(GuidingPrincipleComment).where(GuidingPrincipleComment.guiding_principle_id == guiding_principle.id)
        .order_by(GuidingPrincipleComment.created_at)
    ).all()
    return [_gp_comment_to_out(db, c) for c in comments]


@router.patch("/guiding-principles/{guiding_principle_id}/comments/{comment_id}", response_model=GuidingPrincipleCommentOut)
def edit_org_guiding_principle_comment(
    organization_id: UUID, guiding_principle_id: UUID, comment_id: UUID, payload: GuidingPrincipleCommentUpdate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Author-only — not even a Guiding Principle Owner may edit someone
    else's words."""
    _get_guiding_principle(db, organization_id, guiding_principle_id)
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
async def upload_org_guiding_principle_comment_attachment(
    organization_id: UUID, guiding_principle_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Author-only, mirrors Strategy's identical comment-attachment pattern."""
    _get_guiding_principle(db, organization_id, guiding_principle_id)
    comment = db.get(GuidingPrincipleComment, comment_id)
    if comment is None or comment.guiding_principle_id != guiding_principle_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    if comment.author_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the comment's author may attach a file to it.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(GuidingPrincipleCommentFile(comment_id=comment.id, file_id=asset.id, uploaded_by=current_user.id))
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle_id,
              action="comment_file_attached", actor_id=current_user.id, organization_id=organization_id,
              detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.delete(
    "/guiding-principles/{guiding_principle_id}/comments/{comment_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_org_guiding_principle_comment_attachment(
    organization_id: UUID, guiding_principle_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    _get_guiding_principle(db, organization_id, guiding_principle_id)
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
async def upload_org_guiding_principle_file(
    organization_id: UUID, guiding_principle_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    """Uploaded as an organisation shared resource (`is_org_resource=True`)
    — same reasoning as Strategy's/Future State's own org-scoped file
    uploads."""
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
    current_version = get_current_guiding_principle_version(db, guiding_principle.id)
    if is_guiding_principle_locked(current_version):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Guiding Principle is past review; new attachments can no longer be added.",
        )
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
        is_org_resource=True,
    )
    db.flush()
    db.add(
        GuidingPrincipleFile(
            guiding_principle_id=guiding_principle.id, file_id=asset.id, linked_by=current_user.id,
            created_at=asset.created_at,
        )
    )
    log_event(db, entity_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, entity_id=guiding_principle.id, action="file_attached",
              actor_id=current_user.id, organization_id=organization_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/guiding-principles/{guiding_principle_id}/files", response_model=list[FileAssetOut])
def list_org_guiding_principle_files(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    return db.scalars(
        select(FileAsset).join(GuidingPrincipleFile, GuidingPrincipleFile.file_id == FileAsset.id).where(
            GuidingPrincipleFile.guiding_principle_id == guiding_principle.id
        )
    ).all()


@router.delete("/guiding-principles/{guiding_principle_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_guiding_principle_file(
    organization_id: UUID, guiding_principle_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
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
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(file_id)})
    db.commit()


# --- Phase 6: cross-artefact relationships -----------------------------------
#
# Org-scoped list + create relationship endpoints for Strategy/Future State/
# Guiding Principle (the three artefact types with an org-scoped half — Pain
# Point has no artefact of its own at org scope, only its type vocabulary,
# already covered above, and Open Question has no org scope at all) — exact
# structural mirror of `project_router.py`'s own relationship section, under
# distinct function names, `organization_id` in place of `project_id`. See
# `service.py`'s own Phase 6 docstring section for the overall design.


@router.get("/strategies/{strategy_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_org_strategy_relationships(
    organization_id: UUID, strategy_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    links = get_all_links(db, STRATEGY_ARTEFACT_TYPE, strategy.id)
    return [context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=strategy.id) for link in links]


@router.post(
    "/strategies/{strategy_id}/relationships", response_model=ContextStrategyLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_org_strategy_relationship(
    organization_id: UUID, strategy_id: UUID, payload: StrategyLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    strategy = _get_strategy(db, organization_id, strategy_id)
    require_manage_role(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    link = apply_value_error_as_conflict(
        create_strategy_link, db, strategy=strategy, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"kind": payload.kind.value, "strategy_id": str(strategy.id), "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=strategy.id)


@router.post(
    "/strategies/{strategy_id}/supersessions", response_model=ContextStrategyLinkOut, status_code=status.HTTP_201_CREATED,
)
def create_org_strategy_supersession(
    organization_id: UUID, strategy_id: UUID, payload: StrategySupersessionCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    new_strategy = _get_strategy(db, organization_id, strategy_id)
    require_approve_permission(db, current_user, _SCOPE, organization_id=organization_id, project_id=None)
    old_strategy = db.get(Strategy, payload.old_strategy_id)
    if old_strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_strategy_supersession, db, new_strategy=new_strategy, old_strategy=old_strategy,
        actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"kind": "supersession", "new_strategy_id": str(new_strategy.id), "old_strategy_id": str(old_strategy.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=STRATEGY_ARTEFACT_TYPE, viewpoint_id=new_strategy.id)


@router.get("/future-states/{future_state_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_org_future_state_relationships(
    organization_id: UUID, future_state_id: UUID,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    links = get_all_links(db, FUTURE_STATE_ARTEFACT_TYPE, future_state.id)
    return [
        context_strategy_link_to_out(db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=future_state.id)
        for link in links
    ]


@router.post(
    "/future-states/{future_state_id}/relationships", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_org_future_state_relationship(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateLinkCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_manage_role(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    link = apply_value_error_as_conflict(
        create_future_state_link, db, future_state=future_state, kind=payload.kind, target_id=payload.target_id,
        actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"kind": payload.kind.value, "future_state_id": str(future_state.id), "target_id": str(payload.target_id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=future_state.id)


@router.post(
    "/future-states/{future_state_id}/supersessions", response_model=ContextStrategyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_org_future_state_supersession(
    organization_id: UUID, future_state_id: UUID, payload: FutureStateSupersessionCreate,
    current_user: User = Depends(_require_future_state_view), db: Session = Depends(get_db),
):
    new_future_state = _get_future_state(db, organization_id, future_state_id)
    require_future_state_approve_permission(db, current_user, _FS_SCOPE, organization_id=organization_id, project_id=None)
    old_future_state = db.get(FutureState, payload.old_future_state_id)
    if old_future_state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Future State not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_future_state_supersession, db, new_future_state=new_future_state, old_future_state=old_future_state,
        actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"kind": "supersession", "new_future_state_id": str(new_future_state.id),
                      "old_future_state_id": str(old_future_state.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=FUTURE_STATE_ARTEFACT_TYPE, viewpoint_id=new_future_state.id,
    )


@router.get("/guiding-principles/{guiding_principle_id}/relationships", response_model=list[ContextStrategyLinkOut])
def list_org_guiding_principle_relationships(
    organization_id: UUID, guiding_principle_id: UUID,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
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
def create_org_guiding_principle_relationship(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleLinkCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_manage_role(db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None)
    link = apply_value_error_as_conflict(
        create_guiding_principle_link, db, guiding_principle=guiding_principle, kind=payload.kind,
        target_id=payload.target_id, actor_id=current_user.id,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
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
def create_org_guiding_principle_supersession(
    organization_id: UUID, guiding_principle_id: UUID, payload: GuidingPrincipleSupersessionCreate,
    current_user: User = Depends(_require_guiding_principle_view), db: Session = Depends(get_db),
):
    new_guiding_principle = _get_guiding_principle(db, organization_id, guiding_principle_id)
    require_guiding_principle_approve_permission(
        db, current_user, _GP_SCOPE, organization_id=organization_id, project_id=None,
    )
    old_guiding_principle = db.get(GuidingPrinciple, payload.old_guiding_principle_id)
    if old_guiding_principle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guiding Principle not found.")
    link, _new_version = apply_value_error_as_conflict(
        create_guiding_principle_supersession, db, new_guiding_principle=new_guiding_principle,
        old_guiding_principle=old_guiding_principle, actor=current_user, comment=payload.comment,
    )
    log_event(db, entity_type="context_strategy_link", entity_id=link.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"kind": "supersession", "new_guiding_principle_id": str(new_guiding_principle.id),
                      "old_guiding_principle_id": str(old_guiding_principle.id)})
    db.commit()
    db.refresh(link)
    return context_strategy_link_to_out(
        db, link, viewpoint_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, viewpoint_id=new_guiding_principle.id,
    )


# Phase 12: reports (`report_router.py`).
router.include_router(org_reports_router)
