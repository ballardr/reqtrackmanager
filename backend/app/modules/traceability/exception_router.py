"""
Module: modules.traceability.exception_router

Project-scoped API of traceability exceptions, mounted under `/api/v1/projects/{project_id}/modules/traceability`:
list, create, read, change, the approval actions, reviews, archive, comments and evidence files.

Design decisions:
- Every route needs the `traceability_exceptions` part to be in effect. Who may do what is decided by the service
  (`exceptions`), not by the route.
- An exception whose record type the caller may not read is absent from the list and a 404 elsewhere.
- Approve, reject and revoke are marked as human decisions (`APPROVAL_ACTION_ROUTE_EXTRA`), so no module MCP tool can
  resolve to them, and a call arriving through the MCP server also needs AI approvals to be enabled.
- Evidence may be added to an exception in any state; it cannot be removed from an approved one.

Dependencies: `exceptions` (writes and rights), `exception_views` (response shapes), `services.module_attachments`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.registry import APPROVAL_ACTION_ROUTE_EXTRA
from app.modules.traceability import exception_views, exceptions
from app.modules.traceability._shared import EXCEPTION_ARTEFACT_TYPE, TRACEABILITY_EXCEPTIONS, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import ExceptionStatus
from app.modules.traceability.exception_schemas import (
    ExceptionCommentCreate,
    ExceptionCommentOut,
    ExceptionCreate,
    ExceptionDecision,
    ExceptionDetailOut,
    ExceptionOut,
    ExceptionReviewCreate,
    ExceptionUpdate,
)
from app.modules.traceability.models import TraceabilityException
from app.schemas.file import FileAssetOut
from app.services import module_attachments as att
from app.services.lookups import project_or_404
from app.services.project_scope import ProjectScope
from app.services.rbac import (
    get_effective_permissions,
    require_ai_approvals_enabled,
    require_project_subcomponent_enabled,
)
from app.services.tags import TagFilter

project_routes = APIRouter()

_view = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, TRACEABILITY_EXCEPTIONS)
_PATH = "/exceptions"
_ONE = "/exceptions/{exception_id}"


def _held(db: Session, user: User, project_id: UUID) -> set[str]:
    return get_effective_permissions(db, user.id, project_id=project_id)


def _load(db: Session, project_id: UUID, exception_id: UUID, user: User) -> tuple[Project, TraceabilityException]:
    """The project and its exception, 404 when the caller may not see it."""
    project = project_or_404(db, project_id)
    return project, exceptions.get_in_project(db, project.id, exception_id, _held(db, user, project.id))


def _detail(db: Session, project: Project, exception: TraceabilityException, user: User) -> ExceptionDetailOut:
    db.refresh(exception)
    return exception_views.detail_out(db, project, exception, user)


@project_routes.get(_PATH, response_model=list[ExceptionOut])
def list_exceptions(
    project_id: UUID, include_archived: bool = False, status_filter: ExceptionStatus | None = Query(None, alias="status"),
    artefact_type: str | None = None, record_id: UUID | None = None, rule_id: UUID | None = None, open_only: bool = False,
    tag_filter: TagFilter = Depends(), project_scope: ProjectScope = Depends(), current_user: User = Depends(_view),
    db: Session = Depends(get_db),
) -> list[ExceptionOut]:
    """The project's exceptions, newest code last; `open_only` keeps those awaiting a decision or in force."""

    def rows_for(pid: UUID) -> list[ExceptionOut]:
        """This endpoint's rows for one project of the scope."""
        project = project_or_404(db, pid)
        query = select(TraceabilityException).where(TraceabilityException.project_id == pid)
        if not include_archived:
            query = query.where(TraceabilityException.is_archived.is_(False))
        if status_filter is not None:
            query = query.where(TraceabilityException.status == status_filter)
        if artefact_type is not None:
            query = query.where(TraceabilityException.artefact_type == artefact_type)
        if record_id is not None:
            query = query.where(TraceabilityException.artefact_id == record_id)
        if rule_id is not None:
            query = query.where(TraceabilityException.rule_id == rule_id)
        rows = list(db.scalars(query.order_by(TraceabilityException.unique_code)))
        rows = tag_filter.keep(db, pid, EXCEPTION_ARTEFACT_TYPE, exceptions.readable(_held(db, current_user, pid), rows))
        out = exception_views.rows_out(db, project, rows)
        return [o for o in out if exception_views.is_open(o)] if open_only else out

    return project_scope.collect(
        db, project_or_404(db, project_id), current_user.id, EXCEPTION_ARTEFACT_TYPE, rows_for,
        gate=(TRACEABILITY_MODULE_KEY, TRACEABILITY_EXCEPTIONS),
    )


@project_routes.post(_PATH, response_model=ExceptionDetailOut, status_code=status.HTTP_201_CREATED)
def create_exception(
    project_id: UUID, payload: ExceptionCreate, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """Requests an exception for one record against one rule in effect."""
    project = project_or_404(db, project_id)
    exception = exceptions.create_exception(db, project=project, actor=current_user, **dict(payload))
    db.commit()
    return _detail(db, project, exception, current_user)


@project_routes.get(_ONE, response_model=ExceptionDetailOut)
def get_exception(
    project_id: UUID, exception_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """One exception, with what the caller may do to it."""
    project, exception = _load(db, project_id, exception_id, current_user)
    return exception_views.detail_out(db, project, exception, current_user)


@project_routes.patch(_ONE, response_model=ExceptionDetailOut)
def update_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionUpdate,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """Changes the fields sent."""
    project, exception = _load(db, project_id, exception_id, current_user)
    changes = {key: getattr(payload, key) for key in payload.model_fields_set}
    exceptions.update_exception(db, project=project, exception=exception, actor=current_user, changes=changes)
    db.commit()
    return _detail(db, project, exception, current_user)


def _move(
    db: Session, project_id: UUID, exception_id: UUID, user: User, target: ExceptionStatus, comment: str, channel: str,
) -> ExceptionDetailOut:
    project, exception = _load(db, project_id, exception_id, user)
    via_mcp = channel == "mcp"
    if via_mcp and target in (ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.REVOKED):
        require_ai_approvals_enabled(db, project)
    exceptions.transition(
        db, project=project, exception=exception, target=target, actor=user, comment=comment, via_mcp=via_mcp,
    )
    db.commit()
    return _detail(db, project, exception, user)


@project_routes.post(f"{_ONE}/approve", response_model=ExceptionDetailOut, openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA)
def approve_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionDecision, current_user: User = Depends(_view),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
) -> ExceptionDetailOut:
    """Approves a requested exception, which then covers its rule for its record."""
    return _move(db, project_id, exception_id, current_user, ExceptionStatus.APPROVED, payload.comment, channel)


@project_routes.post(f"{_ONE}/reject", response_model=ExceptionDetailOut, openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA)
def reject_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionDecision, current_user: User = Depends(_view),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
) -> ExceptionDetailOut:
    """Rejects a requested exception; a comment is required."""
    return _move(db, project_id, exception_id, current_user, ExceptionStatus.REJECTED, payload.comment, channel)


@project_routes.post(f"{_ONE}/revoke", response_model=ExceptionDetailOut, openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA)
def revoke_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionDecision, current_user: User = Depends(_view),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
) -> ExceptionDetailOut:
    """Ends the cover of an approved exception; a comment is required."""
    return _move(db, project_id, exception_id, current_user, ExceptionStatus.REVOKED, payload.comment, channel)


@project_routes.post(f"{_ONE}/withdraw", response_model=ExceptionDetailOut)
def withdraw_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionDecision, current_user: User = Depends(_view),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
) -> ExceptionDetailOut:
    """Withdraws a request."""
    return _move(db, project_id, exception_id, current_user, ExceptionStatus.WITHDRAWN, payload.comment, channel)


@project_routes.post(f"{_ONE}/resubmit", response_model=ExceptionDetailOut)
def resubmit_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionDecision, current_user: User = Depends(_view),
    db: Session = Depends(get_db), channel: str = Depends(get_request_channel),
) -> ExceptionDetailOut:
    """Requests a rejected, withdrawn or revoked exception again."""
    return _move(db, project_id, exception_id, current_user, ExceptionStatus.REQUESTED, payload.comment, channel)


@project_routes.post(f"{_ONE}/reviews", response_model=ExceptionDetailOut)
def review_traceability_exception(
    project_id: UUID, exception_id: UUID, payload: ExceptionReviewCreate,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """Records a review and the date of the next one."""
    project, exception = _load(db, project_id, exception_id, current_user)
    exceptions.record_exception_review(
        db, project=project, exception=exception, actor=current_user, next_review_date=payload.next_review_date,
        notes=payload.notes,
    )
    db.commit()
    return _detail(db, project, exception, current_user)


def _set_archived(db: Session, project_id: UUID, exception_id: UUID, user: User, archived: bool) -> ExceptionDetailOut:
    project, exception = _load(db, project_id, exception_id, user)
    exceptions.set_archived(db, project=project, exception=exception, actor=user, archived=archived)
    db.commit()
    return _detail(db, project, exception, user)


@project_routes.post(f"{_ONE}/archive", response_model=ExceptionDetailOut)
def archive_exception(
    project_id: UUID, exception_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """Archives an exception that is not in force."""
    return _set_archived(db, project_id, exception_id, current_user, True)


@project_routes.post(f"{_ONE}/unarchive", response_model=ExceptionDetailOut)
def unarchive_exception(
    project_id: UUID, exception_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ExceptionDetailOut:
    """Restores an archived exception."""
    return _set_archived(db, project_id, exception_id, current_user, False)


# --- comments and evidence --------------------------------------------------------------------------


@project_routes.post(f"{_ONE}/comments", response_model=ExceptionCommentOut, status_code=status.HTTP_201_CREATED)
def add_exception_comment(
    project_id: UUID, exception_id: UUID, payload: ExceptionCommentCreate,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
):
    """Adds a comment."""
    project, exception = _load(db, project_id, exception_id, current_user)
    return att.add_comment(db, exception_views.ATTACHMENTS, exception, current_user, payload.body, project_id=project.id)


@project_routes.get(f"{_ONE}/comments", response_model=list[ExceptionCommentOut])
def list_exception_comments(
    project_id: UUID, exception_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
):
    """The comments, oldest first, with their attachments."""
    _project, exception = _load(db, project_id, exception_id, current_user)
    return att.list_comments(db, exception_views.ATTACHMENTS, exception)


@project_routes.patch(f"{_ONE}/comments/{{comment_id}}", response_model=ExceptionCommentOut)
def edit_exception_comment(
    project_id: UUID, exception_id: UUID, comment_id: UUID, payload: ExceptionCommentCreate,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
):
    """Edits a comment. Author only."""
    project, exception = _load(db, project_id, exception_id, current_user)
    return att.edit_comment(
        db, exception_views.ATTACHMENTS, exception, comment_id, current_user, payload.body, project_id=project.id,
    )


@project_routes.post(
    f"{_ONE}/comments/{{comment_id}}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED,
)
async def upload_exception_comment_file(
    project_id: UUID, exception_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> FileAsset:
    """Attaches a file to a comment. Comment author only."""
    project, exception = _load(db, project_id, exception_id, current_user)
    return await att.attach_to_comment(
        db, exception_views.ATTACHMENTS, exception, comment_id, current_user, file,
        organization_id=project.organization_id, project_id=project.id,
    )


@project_routes.delete(f"{_ONE}/comments/{{comment_id}}/files/{{file_id}}", status_code=status.HTTP_204_NO_CONTENT)
def remove_exception_comment_file(
    project_id: UUID, exception_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> None:
    """Removes a comment's attachment. Comment author only."""
    project, exception = _load(db, project_id, exception_id, current_user)
    att.remove_comment_attachment(
        db, exception_views.ATTACHMENTS, exception, comment_id, file_id, current_user, project_id=project.id,
    )


def _require_evidence_right(db: Session, exception: TraceabilityException, user: User) -> None:
    if exceptions.is_requester(db, exception, user.id) or exceptions.may_manage(_held(db, user, exception.project_id)):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the requester or a Traceability Manager may change the evidence.")


@project_routes.post(f"{_ONE}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_exception_file(
    project_id: UUID, exception_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> FileAsset:
    """Attaches evidence."""
    project, exception = _load(db, project_id, exception_id, current_user)
    _require_evidence_right(db, exception, current_user)
    return await att.attach_file(
        db, exception_views.ATTACHMENTS, exception, current_user, file,
        organization_id=project.organization_id, project_id=project.id,
    )


@project_routes.get(f"{_ONE}/files", response_model=list[FileAssetOut])
def list_exception_files(
    project_id: UUID, exception_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> list[FileAsset]:
    """The evidence files."""
    _project, exception = _load(db, project_id, exception_id, current_user)
    return att.list_files(db, exception_views.ATTACHMENTS, exception)


@project_routes.delete(f"{_ONE}/files/{{file_id}}", status_code=status.HTTP_204_NO_CONTENT)
def remove_exception_file(
    project_id: UUID, exception_id: UUID, file_id: UUID,
    current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> None:
    """Removes evidence from an exception that is not approved."""
    project, exception = _load(db, project_id, exception_id, current_user)
    _require_evidence_right(db, exception, current_user)
    if exception.status == ExceptionStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "The evidence of an approved exception cannot be removed.")
    att.unlink_file(db, exception_views.ATTACHMENTS, exception, file_id, current_user, project_id=project.id)
