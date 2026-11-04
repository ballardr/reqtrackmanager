"""
Module: modules.product_feedback.project_router

Project-scoped Product Feedback API, mounted at `/api/v1/projects/{project_id}/modules/product_feedback`:
request CRUD, archive, versions, lifecycle transitions, comments, files and the project's submission
policy.

RBAC: sub-component enablement and project membership to view; any project member may submit a request
unless the project's administrator restricted submission to triagers; `_shared.require_request_manage`
(project Feedback Triager role or FGAC grant) to edit, transition, archive or attach evidence; the
settings need project-settings management. A request's files resolve through
`service.resolve_request_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.enums import EnhancementRequestStatus
from app.modules.product_feedback.models import EnhancementRequest
from app.modules.product_feedback.schemas import (
    FeedbackSettingsOut,
    FeedbackSettingsUpdate,
    RequestCommentCreate,
    RequestCommentOut,
    RequestCommentUpdate,
    RequestCreate,
    RequestOut,
    RequestTransitionRequest,
    RequestUpdate,
    RequestVersionOut,
)
from app.modules.product_feedback.service import (
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
    RecordOwner,
    filter_requests,
    get_submission_policy,
    list_project_requests,
    set_submission_policy,
)
from app.schemas.file import FileAssetOut
from app.services import module_attachments as att
from app.services.audit import log_event
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_manage, require_project_subcomponent_enabled
from app.services.tags import TagFilter

router = APIRouter(
    prefix=f"/api/v1/projects/{{project_id}}/modules/{PRODUCT_FEEDBACK_MODULE_KEY}", tags=["product-feedback-project"],
)

_require_view = require_project_subcomponent_enabled(PRODUCT_FEEDBACK_MODULE_KEY, REQUEST_SUBCOMPONENT_KEY)


def _project(db: Session, project_id: UUID) -> Project:
    """Loads the project in the URL, 404ing if it does not exist."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _holder(db: Session, project_id: UUID) -> RecordOwner:
    """The owner of this project's requests."""
    return RecordOwner.of_project(_project(db, project_id))


def _get(db: Session, holder: RecordOwner, request_id: UUID) -> EnhancementRequest:
    """A request of this project (404 for anything else)."""
    return sh.get_request_in_scope(db, holder, request_id)


# --- Settings ----------------------------------------------------------------


@router.get("/settings", response_model=FeedbackSettingsOut)
def get_feedback_settings(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The project's Product Feedback settings (any member can read them, so the UI knows whether to offer Submit)."""
    _project(db, project_id)
    return FeedbackSettingsOut(submission_policy=get_submission_policy(db, project_id))


@router.put("/settings", response_model=FeedbackSettingsOut)
def update_feedback_settings(
    project_id: UUID, payload: FeedbackSettingsUpdate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Sets who may submit requests in this project. Needs project-settings management."""
    previous = get_submission_policy(db, project.id)
    set_submission_policy(db, project.id, payload.submission_policy)
    log_event(db, entity_type="project_feedback_settings", entity_id=project.id, action="updated",
              actor_id=current_user.id, project_id=project.id,
              detail={"submission_policy": {"from": previous.value, "to": payload.submission_policy.value}})
    db.commit()
    return FeedbackSettingsOut(submission_policy=payload.submission_policy)


# --- Request CRUD ------------------------------------------------------------


@router.post("/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    project_id: UUID, payload: RequestCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Submits a request in `NEW`. Any project member may, unless the project restricted submission to triagers."""
    holder = _holder(db, project_id)
    sh.require_request_submit(db, current_user, holder)
    return sh.create_from_payload(db, holder, payload, current_user)


@router.get("/requests", response_model=list[RequestOut])
def list_requests(
    project_id: UUID, include_archived: bool = False, status: EnhancementRequestStatus | None = None,
    open_only: bool = False, search: str | None = None, tag_filter: TagFilter = Depends(),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    project_scope: ProjectScope = Depends(),
):
    """The project's requests; archived ones only with `include_archived`, narrowed by `status`, `open_only`
    (new, under review or accepted) and a case-insensitive `search` of code, title and description."""

    def rows_for(pid: UUID) -> list:
        """This endpoint's rows for one project of the scope."""
        requests = tag_filter.keep(
            db, pid, REQUEST_ARTEFACT_TYPE, list_project_requests(db, pid, include_archived=include_archived),
        )
        return sh.requests_to_out(
            db, filter_requests(db, requests, status=status, open_only=open_only, search=search),
        )

    return project_scope.collect(
        db, _project(db, project_id), current_user.id, REQUEST_ARTEFACT_TYPE, rows_for,
        gate=(PRODUCT_FEEDBACK_MODULE_KEY, REQUEST_SUBCOMPONENT_KEY),
    )


@router.get("/requests/{request_id}", response_model=RequestOut)
def get_request(project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """One request with its current version."""
    return sh.current_request_out(db, _get(db, _holder(db, project_id), request_id))


@router.put("/requests/{request_id}", response_model=RequestOut)
def update_request(
    project_id: UUID, request_id: UUID, payload: RequestUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Applies a partial update as a new version (fields absent from the body are kept). Needs the triager role."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.update_from_payload(db, holder, request, payload, current_user)


@router.get("/requests/{request_id}/versions", response_model=list[RequestVersionOut])
def list_request_versions(
    project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """A request's full version history, oldest first."""
    return sh.request_versions_out(db, _get(db, _holder(db, project_id), request_id).versions)


@router.post("/requests/{request_id}/transition", response_model=RequestOut)
def transition(
    project_id: UUID, request_id: UUID, payload: RequestTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Moves a request along its lifecycle (`RequestOut.allowed_next_statuses` lists the legal targets). Needs
    the triager role. 409 for an illegal move, an archived request, or declining without a reason in `comment`."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.transition_from_payload(db, holder, request, payload.status, payload.comment, current_user)


@router.post("/requests/{request_id}/archive", response_model=RequestOut)
def archive(project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Soft-archives a request. Needs the triager role."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.set_archived(db, holder, request, current_user, archived=True)


@router.post("/requests/{request_id}/unarchive", response_model=RequestOut)
def unarchive(project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Restores an archived request. Needs the triager role."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.set_archived(db, holder, request, current_user, archived=False)


# --- Comments ----------------------------------------------------------------


@router.post("/requests/{request_id}/comments", response_model=RequestCommentOut, status_code=status.HTTP_201_CREATED)
def add_request_comment(
    project_id: UUID, request_id: UUID, payload: RequestCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a discussion comment. Any project member may comment."""
    request = _get(db, _holder(db, project_id), request_id)
    return att.add_comment(db, sh.REQUEST_ATTACHMENTS, request, current_user, payload.body, project_id=project_id)


@router.get("/requests/{request_id}/comments", response_model=list[RequestCommentOut])
def list_request_comments(
    project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """A request's comments, oldest first, with attachments."""
    return att.list_comments(db, sh.REQUEST_ATTACHMENTS, _get(db, _holder(db, project_id), request_id))


@router.patch("/requests/{request_id}/comments/{comment_id}", response_model=RequestCommentOut)
def edit_request_comment(
    project_id: UUID, request_id: UUID, comment_id: UUID, payload: RequestCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Edits a comment. Author only."""
    request = _get(db, _holder(db, project_id), request_id)
    return att.edit_comment(db, sh.REQUEST_ATTACHMENTS, request, comment_id, current_user, payload.body, project_id=project_id)


@router.post(
    "/requests/{request_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED,
)
async def upload_request_comment_attachment(
    project_id: UUID, request_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Attaches a file to a comment. Comment author only."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    return await att.attach_to_comment(
        db, sh.REQUEST_ATTACHMENTS, request, comment_id, current_user, file,
        organization_id=holder.organization_id, project_id=project_id,
    )


@router.delete("/requests/{request_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_request_comment_attachment(
    project_id: UUID, request_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a comment's attachment. Comment author only."""
    request = _get(db, _holder(db, project_id), request_id)
    att.remove_comment_attachment(
        db, sh.REQUEST_ATTACHMENTS, request, comment_id, file_id, current_user, project_id=project_id,
    )


# --- Direct files (evidence) -------------------------------------------------


@router.post("/requests/{request_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_request_file(
    project_id: UUID, request_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Uploads evidence directly to a request. Needs the triager role."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return await att.attach_file(
        db, sh.REQUEST_ATTACHMENTS, request, current_user, file,
        organization_id=holder.organization_id, project_id=project_id,
    )


@router.get("/requests/{request_id}/files", response_model=list[FileAssetOut])
def list_request_files(
    project_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Files attached directly to a request."""
    return att.list_files(db, sh.REQUEST_ATTACHMENTS, _get(db, _holder(db, project_id), request_id))


@router.delete("/requests/{request_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_request_file(
    project_id: UUID, request_id: UUID, file_id: UUID, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Removes (and deletes) a directly attached file. Needs the triager role."""
    holder = _holder(db, project_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    att.unlink_file(db, sh.REQUEST_ATTACHMENTS, request, file_id, current_user, project_id=project_id)
