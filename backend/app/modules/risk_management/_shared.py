"""
Module: modules.risk_management._shared

Helpers behind the Risk routers (`project_router.py`, `router.py`): the manage
and type-admin gates, the API shape (a risk merged with its current version and
derived ratings), the create/update bodies, and the comment/file wrappers over
the shared `services.module_attachments` kit.

RBAC (plan Phase 0 resolution 10): viewing needs the sub-component enabled and
project membership; any project member may *propose* (create) a risk, which
starts `IDENTIFIED`; edit, archive, attachment and project-type changes need the
project `risk_manager` role or a Fine-Grained Access Control `(risk, manage)`
grant; the org Risk type vocabulary needs `risk_type_admin`.

Tenancy: every lookup is scoped to the project in the URL, so another tenant's
ids look absent (404), and a level or owner must belong to the project's
organisation.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.risk_management.models import (
    Risk,
    RiskComment,
    RiskCommentFile,
    RiskFile,
    RiskTypeDefinition,
    RiskVersion,
)
from app.modules.risk_management.ratings import RatingContext, RiskRating, load_rating_context, rate_version
from app.modules.risk_management.schemas import RiskCommentOut, RiskCreate, RiskOut, RiskRatingOut, RiskUpdate
from app.modules.risk_management.scoring import LEVEL_COLUMN_AXES
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_TYPES,
    apply_new_version,
    create_risk,
    get_current_risk_version,
    resolve_risk_type,
    validate_levels,
)
from app.services import module_attachments as att
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.rbac import (
    get_effective_org_roles,
    get_effective_permissions,
    lock_row_for_update,
    permission_satisfied,
    user_satisfies_module_role,
)

RISK_MANAGE_PERMISSION = encode_permission(RISK_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

_TEXT_FIELDS = ("statement", "cause", "risk_event", "consequence", "acceptance_criteria")


def _rating_out(rating: RiskRating | None) -> RiskRatingOut | None:
    """Converts a `RiskRating` dataclass to its API schema (`None` stays `None`)."""
    return RiskRatingOut(**rating.__dict__) if rating is not None else None


def risk_to_out(db: Session, risk: Risk, version: RiskVersion, ctx: RatingContext) -> RiskOut:
    """Merges a risk with its current version and derived ratings. `ctx` is
    loaded once per request (`load_rating_context`)."""
    inherent, residual = rate_version(ctx, version)
    return RiskOut(
        id=risk.id, project_id=risk.project_id, unique_code=risk.unique_code, creator_id=risk.creator_id,
        is_archived=risk.is_archived, archived_at=risk.archived_at, archived_by=risk.archived_by,
        title=version.title, statement=version.statement, cause=version.cause, risk_event=version.risk_event,
        consequence=version.consequence, risk_type_id=version.project_type_id,
        risk_type_name=RISK_TYPES.display_name(db, org_type_id=None, project_type_id=version.project_type_id),
        treatment_strategy=version.treatment_strategy, acceptance_criteria=version.acceptance_criteria,
        **{column: getattr(version, column) for column in LEVEL_COLUMN_AXES},
        inherent_rating=_rating_out(inherent), residual_rating=_rating_out(residual), status=version.status,
        owner_id=version.owner_id, review_date=version.review_date, version_number=version.version_number,
        created_at=risk.created_at, updated_at=risk.updated_at,
    )


def current_risk_out(db: Session, risk: Risk, project: Project) -> RiskOut:
    """The API shape of one risk, loading its version and rating context."""
    return risk_to_out(db, risk, get_current_risk_version(db, risk.id), load_rating_context(db, project))


def get_risk_in_project(db: Session, project_id: uuid.UUID, risk_id: uuid.UUID) -> Risk:
    """Loads a risk, 404ing unless it belongs to `project_id` (so another
    project's ids look absent)."""
    risk = db.get(Risk, risk_id)
    if risk is None or risk.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk not found.")
    return risk


def require_risk_manage(db: Session, current_user: User, project: Project) -> None:
    """Gate for edit/archive/attachment/project-type actions: the project
    `risk_manager` role (composing with server admin, org admin and project
    manager) or an FGAC `(risk, manage)` grant.

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, RISK_MODULE_KEY, "risk_manager", organization_id=project.organization_id, project_id=project.id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=project.organization_id, project_id=project.id)
    if permission_satisfied(held, RISK_MANAGE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Risk Manager (or admin/manager) may do this.")


def require_risk_type_admin(db: Session, current_user: User, *, organization_id: uuid.UUID) -> None:
    """Gate for org-level Risk type CRUD (`risk_type_admin`, composing with
    server admin and org admin).

    Raises:
        HTTPException: 403 if the caller lacks it.
    """
    if not user_satisfies_module_role(
        db, current_user, RISK_MODULE_KEY, "risk_type_admin", organization_id=organization_id, project_id=None,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Risk Type Admin (or org admin) may do this.")


def get_org_type(db: Session, organization_id: uuid.UUID, type_id: uuid.UUID) -> RiskTypeDefinition:
    """Loads an org Risk type, 404ing across organisations."""
    row = db.get(RiskTypeDefinition, type_id)
    if row is None or row.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk type not found.")
    return row


def apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls `fn`, translating `ValueError` (in-use type) into HTTP 409."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def validate_owner(db: Session, organization_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
    """Rejects an owner who is not a member of the organisation, so a risk can't
    point at a user from another tenant.

    Raises:
        HTTPException: 400 if `owner_id` is not in the organisation.
    """
    if owner_id is not None and not get_effective_org_roles(db, owner_id, organization_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner must be a member of this organisation.")


def _resolve_references(db: Session, project: Project, sent: dict) -> None:
    """Validates and rewrites the payload's references in place: the owner, the
    scoring levels, and `risk_type_id` -> `project_type_id`.

    Raises:
        HTTPException: 400 for an invalid owner, level or type.
    """
    validate_owner(db, project.organization_id, sent.get("owner_id"))
    try:
        validate_levels(db, project.organization_id, {c: sent[c] for c in LEVEL_COLUMN_AXES if c in sent})
        if "risk_type_id" in sent:
            sent["project_type_id"] = resolve_risk_type(db, project, sent.pop("risk_type_id"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def create_risk_from_payload(db: Session, payload: RiskCreate, creator: User, project: Project) -> RiskOut:
    """Validates a create payload, creates the risk, audit-logs, commits and
    returns the API shape."""
    content = payload.model_dump()
    _resolve_references(db, project, content)
    risk = create_risk(db, project=project, creator=creator, **content)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="created", actor_id=creator.id,
              project_id=project.id, detail={"title": payload.title, "unique_code": risk.unique_code})
    db.commit()
    db.refresh(risk)
    return current_risk_out(db, risk, project)


def update_risk_from_payload(db: Session, risk: Risk, payload: RiskUpdate, actor: User, project: Project) -> RiskOut:
    """Applies a partial update as a new version (only fields present in the
    request body change), audit-logs, commits and returns the API shape."""
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note"})
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A Risk title cannot be null.")
    for text_field in _TEXT_FIELDS:
        if text_field in sent and sent[text_field] is None:
            sent[text_field] = ""
    _resolve_references(db, project, sent)
    lock_row_for_update(db, Risk, risk.id)
    current = get_current_risk_version(db, risk.id)
    apply_new_version(db, risk, current, actor, changes=sent, change_note=payload.change_note)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="updated", actor_id=actor.id,
              project_id=risk.project_id)
    db.commit()
    return current_risk_out(db, risk, project)


# --- Comments and files (shared kit, see `services.module_attachments`) ------

RISK_ATTACHMENTS = att.AttachmentKit(
    artefact_type=RISK_ARTEFACT_TYPE, label="Risk", comment_model=RiskComment, comment_file_model=RiskCommentFile,
    file_model=RiskFile, fk="risk_id", comment_out=RiskCommentOut,
)


def add_comment(db: Session, risk: Risk, user: User, body: str, **scope_ids) -> RiskCommentOut:
    """Adds and audit-logs a comment."""
    return att.add_comment(db, RISK_ATTACHMENTS, risk, user, body, **scope_ids)


def list_comments(db: Session, risk: Risk) -> list[RiskCommentOut]:
    """Comments on a risk, oldest first."""
    return att.list_comments(db, RISK_ATTACHMENTS, risk)


def edit_comment(db: Session, risk: Risk, comment_id: uuid.UUID, user: User, body: str, **scope_ids) -> RiskCommentOut:
    """Author-only edit; audit-logged."""
    return att.edit_comment(db, RISK_ATTACHMENTS, risk, comment_id, user, body, **scope_ids)


async def attach_to_comment(
    db: Session, risk: Risk, comment_id: uuid.UUID, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids,
) -> FileAsset:
    """Author-only comment attachment."""
    return await att.attach_to_comment(db, RISK_ATTACHMENTS, risk, comment_id, user, file, organization_id=organization_id, **scope_ids)


def remove_comment_attachment(db: Session, risk: Risk, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Author-only removal of a comment attachment; audit-logged."""
    att.remove_comment_attachment(db, RISK_ATTACHMENTS, risk, comment_id, file_id, user, **scope_ids)


async def attach_file(db: Session, risk: Risk, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids) -> FileAsset:
    """Uploads and links a file to a risk (caller has checked manage)."""
    return await att.attach_file(db, RISK_ATTACHMENTS, risk, user, file, organization_id=organization_id, **scope_ids)


def list_files(db: Session, risk: Risk) -> list[FileAsset]:
    """Files directly attached to a risk."""
    return att.list_files(db, RISK_ATTACHMENTS, risk)


def unlink_file(db: Session, risk: Risk, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    att.unlink_file(db, RISK_ATTACHMENTS, risk, file_id, user, **scope_ids)
