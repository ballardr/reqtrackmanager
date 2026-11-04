"""
Module: modules.product_feedback._shared

Helpers behind the two routers (`project_router.py`, `router.py`) and the record-table import: the
gates, the API shape (a request merged with its current version), the create / update / transition
bodies, and the comment and file wrappers over the shared `services.module_attachments` kit.

RBAC: viewing needs the sub-component enabled and membership. Submitting needs only that, unless a
project administrator restricted submission to triagers (`SubmissionPolicy.TRIAGERS`). Editing,
transitions, archiving and attachments need the triager role of the tier (`feedback_triager` in a
project, `org_feedback_triager` in the organisation) or a Fine-Grained Access Control
`(enhancement_request, manage)` grant.

Tenancy: every lookup is scoped to the project or organisation in the URL, so another tenant's ids
look absent (404), and an owner must belong to the organisation.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.user import User
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestCommentFile,
    EnhancementRequestFile,
    EnhancementRequestVersion,
)
from app.modules.product_feedback.schemas import (
    RequestCommentOut,
    RequestCreate,
    RequestOut,
    RequestUpdate,
    RequestVersionOut,
)
from app.modules.product_feedback.service import (
    ALLOWED_TRANSITIONS,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    RecordOwner,
    apply_new_version,
    archive_request,
    create_request,
    get_current_version,
    get_submission_policy,
    transition_request,
    unarchive_request,
)
from app.schemas.principal import PrincipalOut
from app.services import module_attachments as att
from app.services.audit import log_event
from app.services.current_versions import current_versions
from app.services.permissions import encode_permission
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.rbac import get_effective_permissions, lock_row_for_update, permission_satisfied, user_satisfies_module_role

REQUEST_MANAGE_PERMISSION = encode_permission(REQUEST_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

#: The triager module role of each tier.
TRIAGER_ROLE_KEY: dict[EnhancementRequestScope, str] = {
    EnhancementRequestScope.PROJECT: "feedback_triager",
    EnhancementRequestScope.ORGANIZATION: "org_feedback_triager",
}

# Resolved display data for owners, keyed by `(owner_type, owner_id)` (`services.principals.principal_labels`).
OwnerLabels = dict[tuple[str, uuid.UUID], PrincipalOut]


def owner_labels(db: Session, versions: Sequence[EnhancementRequestVersion]) -> OwnerLabels:
    """Display data for the owner of every version in `versions`, in one batch."""
    return principal_labels(db, [principal_ref(v.owner_type, v.owner_id) for v in versions])


def _owner_of(labels: OwnerLabels, version: EnhancementRequestVersion) -> PrincipalOut | None:
    """The resolved owner of `version`, or None when it has none."""
    if version.owner_type is None or version.owner_id is None:
        return None
    return labels[(version.owner_type, version.owner_id)]


def request_to_out(
    db: Session, request: EnhancementRequest, version: EnhancementRequestVersion, labels: OwnerLabels | None = None,
) -> RequestOut:
    """Merges a request with its current version. `labels` is pre-resolved owner data when building many,
    resolved here when omitted."""
    labels = labels if labels is not None else owner_labels(db, [version])
    return RequestOut(
        id=request.id, scope=request.scope, organization_id=request.organization_id, project_id=request.project_id,
        unique_code=request.unique_code, creator_id=request.creator_id, is_archived=request.is_archived,
        archived_at=request.archived_at, archived_by=request.archived_by, title=version.title,
        description=version.description, status=version.status,
        allowed_next_statuses=sorted(
            ALLOWED_TRANSITIONS[version.status] - {EnhancementRequestStatus.DUPLICATE},
            key=list(EnhancementRequestStatus).index,
        ),
        owner=_owner_of(labels, version), external_ref_url=version.external_ref_url,
        external_ref_key=version.external_ref_key, decline_reason=version.decline_reason,
        version_number=version.version_number, created_at=request.created_at, updated_at=request.updated_at,
    )


def requests_to_out(db: Session, requests: Sequence[EnhancementRequest]) -> list[RequestOut]:
    """The list response: each current version loaded and every owner resolved in a fixed number of statements."""
    by_id = current_versions(db, EnhancementRequestVersion, "request_id", [r.id for r in requests])
    versions = [by_id[r.id] for r in requests]
    labels = owner_labels(db, versions)
    return [request_to_out(db, r, v, labels) for r, v in zip(requests, versions, strict=True)]


def current_request_out(db: Session, request: EnhancementRequest) -> RequestOut:
    """The API shape of one request, loading its current version."""
    return request_to_out(db, request, get_current_version(db, request.id))


def request_versions_out(db: Session, versions: Sequence[EnhancementRequestVersion]) -> list[RequestVersionOut]:
    """The API shape of a request's version history, resolving every owner in one batch."""
    labels = owner_labels(db, versions)
    return [
        RequestVersionOut(
            id=v.id, request_id=v.request_id, version_number=v.version_number, valid_from=v.valid_from,
            valid_to=v.valid_to, title=v.title, description=v.description, status=v.status, owner=_owner_of(labels, v),
            external_ref_url=v.external_ref_url, external_ref_key=v.external_ref_key,
            decline_reason=v.decline_reason, change_note=v.change_note, created_by=v.created_by,
            created_at=v.created_at,
        )
        for v in versions
    ]


def get_request_in_scope(db: Session, holder: RecordOwner, request_id: uuid.UUID) -> EnhancementRequest:
    """Loads a request, 404ing unless it belongs to the project (or organisation inbox) of `holder`, so another
    tenant's ids look absent."""
    request = db.get(EnhancementRequest, request_id)
    if request is None or request.scope != holder.scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    if holder.is_project and request.project_id != holder.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    if not holder.is_project and request.organization_id != holder.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    return request


def can_manage(db: Session, current_user: User, holder: RecordOwner) -> bool:
    """Whether `current_user` holds the tier's triager role (composing with server admin, org admin and project
    manager) or an FGAC `(enhancement_request, manage)` grant."""
    if user_satisfies_module_role(
        db, current_user, PRODUCT_FEEDBACK_MODULE_KEY, TRIAGER_ROLE_KEY[holder.scope],
        organization_id=holder.organization_id, project_id=holder.project_id,
    ):
        return True
    held = get_effective_permissions(
        db, current_user.id, organization_id=holder.organization_id, project_id=holder.project_id,
    )
    return permission_satisfied(held, REQUEST_MANAGE_PERMISSION)


def require_request_manage(db: Session, current_user: User, holder: RecordOwner) -> None:
    """Gate for edit, transition, archive and attachment actions.

    Raises:
        HTTPException: 403 unless `can_manage`.
    """
    if not can_manage(db, current_user, holder):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Feedback Triager (or admin/manager) may do this.")


def require_request_submit(db: Session, current_user: User, holder: RecordOwner) -> None:
    """Gate for creating a request: any member who can see the list, unless the project's administrator
    restricted submission to triagers (organisation requests are always open to members).

    Raises:
        HTTPException: 403 when the project's policy is `TRIAGERS` and the caller is not a triager.
    """
    project_id = holder.project_id
    if project_id is not None and get_submission_policy(db, project_id) == SubmissionPolicy.TRIAGERS:
        if not can_manage(db, current_user, holder):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Feedback Triager may submit requests in this project.")


def apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls `fn`, translating `ValueError` (an illegal move) into HTTP 409."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def audit_request(
    db: Session, holder: RecordOwner, request: EnhancementRequest, action: str, actor: User, detail: dict | None = None,
) -> None:
    """Records an audit event about `request`, placed under its project or (for an inbox request) its organisation."""
    log_event(
        db, entity_type=REQUEST_ARTEFACT_TYPE, entity_id=request.id, action=action, actor_id=actor.id, detail=detail,
        organization_id=holder.audit_organization_id, project_id=holder.project_id,
    )


def _owner_columns(db: Session, holder: RecordOwner, payload: RequestCreate | RequestUpdate) -> dict:
    """The `owner_type` / `owner_id` column values for the payload's owner, validated; empty when an update does
    not mention the owner (so it is carried forward).

    Raises:
        HTTPException: 400 when the owner is not a member of the organisation, or is a group of another
            organisation or project.
    """
    if "owner" not in payload.model_fields_set:
        return {}
    validate_principal(db, payload.owner, organization_id=holder.organization_id, project_id=holder.project_id, field="owner")
    return principal_columns("owner", payload.owner)


def stage_request(db: Session, holder: RecordOwner, payload: RequestCreate, creator: User) -> EnhancementRequest:
    """Validates a create payload, creates the request (`NEW`) and audit-logs it. Does not commit: the endpoint and
    the record-table import each own their transaction. The caller has checked `require_request_submit`.

    Raises:
        HTTPException: 400 for an unusable owner.
    """
    content = payload.model_dump(exclude={"owner"})
    content.update(_owner_columns(db, holder, payload))
    request = create_request(db, holder, creator, **content)
    audit_request(db, holder, request, "created", creator, {"title": payload.title, "unique_code": request.unique_code})
    return request


def create_from_payload(db: Session, holder: RecordOwner, payload: RequestCreate, creator: User) -> RequestOut:
    """`stage_request`, then commits and returns the API shape."""
    request = stage_request(db, holder, payload, creator)
    db.commit()
    db.refresh(request)
    return current_request_out(db, request)


def stage_request_update(
    db: Session, holder: RecordOwner, request: EnhancementRequest, payload: RequestUpdate, actor: User,
) -> None:
    """Applies a partial update as a new version (only fields present in the request body change) and audit-logs
    it. Does not commit. The caller has checked `require_request_manage`.

    Raises:
        HTTPException: 422 for a null title, 400 for an unusable owner.
    """
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note", "owner"})
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An enhancement request title cannot be null.")
    if "description" in sent and sent["description"] is None:
        sent["description"] = ""
    sent.update(_owner_columns(db, holder, payload))
    lock_row_for_update(db, EnhancementRequest, request.id)
    current = get_current_version(db, request.id)
    apply_new_version(db, request, current, actor, changes=sent, change_note=payload.change_note)
    audit_request(db, holder, request, "updated", actor)


def update_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, payload: RequestUpdate, actor: User,
) -> RequestOut:
    """`stage_request_update`, then commits and returns the API shape."""
    stage_request_update(db, holder, request, payload, actor)
    db.commit()
    return current_request_out(db, request)


def transition_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, target: EnhancementRequestStatus, comment: str,
    actor: User,
) -> RequestOut:
    """Moves a request to `target` (the caller has checked the actor may), audit-logs, commits and returns the API
    shape. Locks the request row first so two concurrent moves cannot both pass the transition check.

    Raises:
        HTTPException: 409 for an illegal move, an archived request or a decline without a reason.
    """
    lock_row_for_update(db, EnhancementRequest, request.id)
    db.refresh(request)
    current = get_current_version(db, request.id)
    previous = current.status
    apply_value_error_as_conflict(transition_request, db, request, current, target, actor, comment=comment)
    detail: dict = {"from": previous.value, "to": target.value}
    if comment.strip():
        detail["comment"] = comment.strip()
    audit_request(db, holder, request, "status_changed", actor, detail)
    db.commit()
    return current_request_out(db, request)


def set_archived(
    db: Session, holder: RecordOwner, request: EnhancementRequest, actor: User, *, archived: bool,
) -> RequestOut:
    """Archives or unarchives a request (the caller has checked the actor may), audit-logs and commits."""
    if archived:
        archive_request(request, actor)
    else:
        unarchive_request(request)
    audit_request(db, holder, request, "archived" if archived else "unarchived", actor)
    db.commit()
    return current_request_out(db, request)


# --- Comments and files (shared kit, see `services.module_attachments`) ------

REQUEST_ATTACHMENTS = att.AttachmentKit(
    artefact_type=REQUEST_ARTEFACT_TYPE, label="Enhancement request", comment_model=EnhancementRequestComment,
    comment_file_model=EnhancementRequestCommentFile, file_model=EnhancementRequestFile, fk="request_id",
    comment_out=RequestCommentOut,
)
