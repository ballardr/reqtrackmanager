"""
Module: modules.product_feedback.router

Organisation-scoped Product Feedback API (the organisation's inbox), mounted at
`/api/v1/orgs/{organization_id}/modules/product_feedback`: request CRUD, archive, versions, lifecycle
transitions, comments and files for requests the organisation itself owns, and the triage of a request into a project
(`move-to-project`), plus merging a duplicate into another inbox request (`merge`, `unmerge`, `merges`).

RBAC: every endpoint needs the `organization_requests` sub-component enabled for the organisation (an
organisation administrator can switch the inbox off; the endpoints then answer 404) and organisation
membership. Any member may submit; `_shared.require_request_manage` (organisation Feedback Triager role
or FGAC grant) is needed to edit, transition, archive or attach evidence. An organisation request's files
are organisation shared resources (`is_org_resource=True`), so the file-owner hook is never consulted for
them.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.enums import EnhancementRequestStatus
from app.modules.product_feedback.models import EnhancementRequest
from app.modules.product_feedback.ratings import parse_model_keys
from app.modules.product_feedback.schemas import (
    RequestCommentCreate,
    RequestCommentOut,
    RequestCommentUpdate,
    RequestCreate,
    RequestMergeOut,
    RequestMergeRequest,
    RequestMoveRequest,
    RequestOut,
    RequestTransitionRequest,
    RequestUpdate,
    RequestVersionOut,
)
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME_KEY
from app.modules.product_feedback.scoring_filter import ScoredFilter
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    RecordOwner,
    filter_requests,
    list_organization_requests,
)
from app.schemas.file import FileAssetOut
from app.schemas.scoring import ScoringSchemeOut
from app.services import module_attachments as att
from app.services import scoring
from app.services.rbac import require_org_subcomponent_enabled

router = APIRouter(
    prefix=f"/api/v1/orgs/{{organization_id}}/modules/{PRODUCT_FEEDBACK_MODULE_KEY}", tags=["product-feedback-org"],
)

_require_view = require_org_subcomponent_enabled(PRODUCT_FEEDBACK_MODULE_KEY, ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY)


def _holder(db: Session, organization_id: UUID) -> RecordOwner:
    """The owner of the organisation's inbox, 404ing for an unknown organisation."""
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return RecordOwner(organization_id)


def _get(db: Session, holder: RecordOwner, request_id: UUID) -> EnhancementRequest:
    """A request of this organisation's inbox (404 for anything else)."""
    return sh.get_request_in_scope(db, holder, request_id)


@router.post("/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_org_request(
    organization_id: UUID, payload: RequestCreate, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Submits a request to the organisation's inbox in `NEW`. Any organisation member may."""
    holder = _holder(db, organization_id)
    sh.require_request_submit(db, current_user, holder)
    return sh.create_from_payload(db, holder, payload, current_user)


@router.get("/requests", response_model=list[RequestOut])
def list_org_requests(
    organization_id: UUID, include_archived: bool = False, status: EnhancementRequestStatus | None = None,
    open_only: bool = False, search: str | None = None, scoring_model: list[str] | None = Query(None),
    scored: ScoredFilter | None = None, missing_axis: str | None = None,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The organisation's inbox; archived requests only with `include_archived`, narrowed by `status`,
    `open_only` and a case-insensitive `search` of code, title and description.
    `scoring_model` (repeat it, or comma-separate; `ice`, `rice`, `rice_demand`) picks the models scored, the first
    being the primary (default: the project's enabled models). `scored=unscored|scored` keeps requests with no
    level (or all levels) on the first model's manual axes; `missing_axis=<axis key>` keeps those lacking one axis."""
    holder = _holder(db, organization_id)
    requests = list_organization_requests(db, organization_id, include_archived=include_archived)
    return sh.requests_to_out(
        db, filter_requests(
            db, holder, requests, status=status, open_only=open_only, search=search, scored=scored,
            missing_axis=missing_axis, scoring_model=parse_model_keys(scoring_model),
        ), scoring_model,
    )


@router.get("/requests/{request_id}", response_model=RequestOut)
def get_org_request(
    organization_id: UUID, request_id: UUID, scoring_model: list[str] | None = Query(None),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """One inbox request with its current version.
    `scoring_model` (repeat it, or comma-separate; `ice`, `rice`, `rice_demand`) picks the models scored, the first
    being the primary (default: the project's enabled models). `scored=unscored|scored` keeps requests with no
    level (or all levels) on the first model's manual axes; `missing_axis=<axis key>` keeps those lacking one axis."""
    return sh.current_request_out(db, _get(db, _holder(db, organization_id), request_id), scoring_model)


@router.get("/scoring-scheme", response_model=ScoringSchemeOut)
def get_org_scoring_scheme(
    organization_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The `enhancement_request` scoring scheme as it applies to the organisation: each axis's level ids and
    weights (what a request's `levels` map takes), the default model and its rating bands. A read-only
    mirror of the core scoring endpoint under this module's prefix, so a client confined to the module (the MCP
    server) can discover the level ids."""
    _holder(db, organization_id)
    return scoring.build_scheme_config(db, organization_id, scoring.get_registered_scheme(REQUEST_SCORING_SCHEME_KEY))


@router.put("/requests/{request_id}", response_model=RequestOut)
def update_org_request(
    organization_id: UUID, request_id: UUID, payload: RequestUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Applies a partial update as a new version. Needs the organisation triager role."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.update_from_payload(db, holder, request, payload, current_user)


@router.get("/requests/{request_id}/versions", response_model=list[RequestVersionOut])
def list_org_request_versions(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """A request's full version history, oldest first."""
    return sh.request_versions_out(db, _get(db, _holder(db, organization_id), request_id).versions)


@router.post("/requests/{request_id}/transition", response_model=RequestOut)
def transition_org_request(
    organization_id: UUID, request_id: UUID, payload: RequestTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Moves an inbox request along its lifecycle. Needs the organisation triager role; 409 for an illegal move,
    an archived request, or declining without a reason in `comment`."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.transition_from_payload(db, holder, request, payload.status, payload.comment, current_user)


@router.post("/requests/{request_id}/archive", response_model=RequestOut)
def archive_org_request(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Soft-archives an inbox request. Needs the organisation triager role."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.set_archived(db, holder, request, current_user, archived=True)


@router.post("/requests/{request_id}/unarchive", response_model=RequestOut)
def unarchive_org_request(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Restores an archived inbox request. Needs the organisation triager role."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.set_archived(db, holder, request, current_user, archived=False)


@router.post("/requests/{request_id}/merge", response_model=RequestOut)
def merge_org_request(
    organization_id: UUID, request_id: UUID, payload: RequestMergeRequest, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Marks the inbox request a duplicate of `canonical_id` (another inbox request). Needs the organisation
    triager role; 409 for an illegal merge. Reversible with `unmerge`."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.merge_from_payload(db, holder, request, payload.canonical_id, payload.note, current_user)


@router.post("/requests/{request_id}/unmerge", response_model=RequestOut)
def unmerge_org_request(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Reverses the merge of a duplicate inbox request: it returns to the status it had. Needs the organisation
    triager role; 409 if it is not merged."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.unmerge_from_payload(db, holder, request, current_user)


@router.get("/requests/{request_id}/merges", response_model=list[RequestMergeOut])
def list_org_request_merges(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The merges an inbox request took part in, active and ended, newest first."""
    return sh.merges_out(db, _get(db, _holder(db, organization_id), request_id))


@router.post("/requests/{request_id}/move-to-project", response_model=RequestOut)
def move_org_request_to_project(
    organization_id: UUID, request_id: UUID, payload: RequestMoveRequest, http_request: Request,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Triages an inbox request into a project of the organisation: it keeps its id, status, comments and history,
    takes the project's next `ENH` code, and its tags and files become the project's. Needs the organisation
    triager role and the right to submit in the target project; 409 if the request has links."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return sh.move_to_project_from_payload(db, http_request, holder, request, payload.project_id, current_user)


@router.post("/requests/{request_id}/comments", response_model=RequestCommentOut, status_code=status.HTTP_201_CREATED)
def add_org_request_comment(
    organization_id: UUID, request_id: UUID, payload: RequestCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a discussion comment. Any organisation member may comment."""
    request = _get(db, _holder(db, organization_id), request_id)
    return att.add_comment(
        db, sh.REQUEST_ATTACHMENTS, request, current_user, payload.body, organization_id=organization_id,
    )


@router.get("/requests/{request_id}/comments", response_model=list[RequestCommentOut])
def list_org_request_comments(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """A request's comments, oldest first, with attachments."""
    return att.list_comments(db, sh.REQUEST_ATTACHMENTS, _get(db, _holder(db, organization_id), request_id))


@router.patch("/requests/{request_id}/comments/{comment_id}", response_model=RequestCommentOut)
def edit_org_request_comment(
    organization_id: UUID, request_id: UUID, comment_id: UUID, payload: RequestCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Edits a comment. Author only."""
    request = _get(db, _holder(db, organization_id), request_id)
    return att.edit_comment(
        db, sh.REQUEST_ATTACHMENTS, request, comment_id, current_user, payload.body, organization_id=organization_id,
    )


@router.post(
    "/requests/{request_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED,
)
async def upload_org_request_comment_attachment(
    organization_id: UUID, request_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Attaches a file to a comment. Comment author only."""
    request = _get(db, _holder(db, organization_id), request_id)
    return await att.attach_to_comment(
        db, sh.REQUEST_ATTACHMENTS, request, comment_id, current_user, file,
        organization_id=organization_id,
    )


@router.delete("/requests/{request_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_request_comment_attachment(
    organization_id: UUID, request_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a comment's attachment. Comment author only."""
    request = _get(db, _holder(db, organization_id), request_id)
    att.remove_comment_attachment(
        db, sh.REQUEST_ATTACHMENTS, request, comment_id, file_id, current_user, organization_id=organization_id,
    )


@router.post("/requests/{request_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_request_file(
    organization_id: UUID, request_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Uploads evidence directly to an inbox request. Needs the organisation triager role."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    return await att.attach_file(db, sh.REQUEST_ATTACHMENTS, request, current_user, file, organization_id=organization_id)


@router.get("/requests/{request_id}/files", response_model=list[FileAssetOut])
def list_org_request_files(
    organization_id: UUID, request_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Files attached directly to an inbox request."""
    return att.list_files(db, sh.REQUEST_ATTACHMENTS, _get(db, _holder(db, organization_id), request_id))


@router.delete("/requests/{request_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_org_request_file(
    organization_id: UUID, request_id: UUID, file_id: UUID, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Removes (and deletes) a directly attached file. Needs the organisation triager role."""
    holder = _holder(db, organization_id)
    request = _get(db, holder, request_id)
    sh.require_request_manage(db, current_user, holder)
    att.unlink_file(db, sh.REQUEST_ATTACHMENTS, request, file_id, current_user, organization_id=organization_id)
