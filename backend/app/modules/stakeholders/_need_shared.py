"""
Module: modules.stakeholders._need_shared

Helpers behind the project-scoped Stakeholder Need router
(`need_project_router.py`), mirroring `_stakeholder_shared.py`: the bodies the
router's routes would otherwise inline — the manage gate, the API shape,
create/update/lifecycle, and the "has need" / "gives rise to" link operations.
Comments and files go through the shared `_attachments` kit.

RBAC (Phase 0 resolution 6): viewing is gated by sub-component enablement
alone; create/edit/archive/retire/link need the project `stakeholder_need_owner`
role or a Fine-Grained Access Control `(stakeholder_need, manage)` grant. A Need
has no organisation scope, so there is no org-level role.

Tenancy: a need only links to a Stakeholder/Persona its own project can see (its
own or its organisation's) and to a Requirement of the same project; anything
else 404s so another tenant's ids look absent.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.stakeholders import _attachments as att
from app.modules.stakeholders._shared import (
    apply_value_error_as_conflict,
    get_visible_holder,
    holder_name,
    validate_people,
)
from app.modules.stakeholders.enums import NeedStatus
from app.modules.stakeholders.models import (
    Persona,
    Stakeholder,
    StakeholderNeed,
    StakeholderNeedComment,
    StakeholderNeedCommentFile,
    StakeholderNeedFile,
    StakeholderNeedVersion,
)
from app.modules.stakeholders.schemas import (
    HeldNeedOut,
    NeedCommentOut,
    NeedCreate,
    NeedHolderOut,
    NeedOut,
    NeedRequirementOut,
    NeedUpdate,
)
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    STAKEHOLDERS_MODULE_KEY,
    add_gives_rise_to_link,
    add_has_need_link,
    apply_need_new_version,
    create_need,
    get_current_need_version,
    list_need_holders,
    list_need_requirement_links,
    transition_need,
)
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role
from app.services.relationships import delete_link
from app.services.requirements import get_current_version as get_current_requirement_version

NEED_MANAGE_PERMISSION = encode_permission(NEED_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

_TEXT_FIELDS = ("description", "rationale")

NEED_ATTACHMENTS = att.AttachmentKit(
    artefact_type=NEED_ARTEFACT_TYPE, label="Stakeholder Need", comment_model=StakeholderNeedComment,
    comment_file_model=StakeholderNeedCommentFile, file_model=StakeholderNeedFile, fk="need_id",
    comment_out=NeedCommentOut,
)


def need_to_out(need: StakeholderNeed, version: StakeholderNeedVersion) -> NeedOut:
    """Merges a need with its current version."""
    return NeedOut(
        id=need.id, project_id=need.project_id, creator_id=need.creator_id, is_archived=need.is_archived,
        archived_at=need.archived_at, archived_by=need.archived_by, name=version.name,
        description=version.description, rationale=version.rationale, status=version.status,
        owner_id=version.owner_id, version_number=version.version_number, created_at=need.created_at,
        updated_at=need.updated_at,
    )


def get_need_in_project(db: Session, project_id: uuid.UUID, need_id: uuid.UUID) -> StakeholderNeed:
    """Loads a need, 404ing unless it belongs to `project_id` (so another
    project's ids look absent)."""
    need = db.get(StakeholderNeed, need_id)
    if need is None or need.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder Need not found.")
    return need


def require_need_manage(db: Session, current_user: User, project: Project) -> None:
    """Gate for create/edit/archive/retire/link/attachment actions: the project
    `stakeholder_need_owner` role (composing with server admin, org admin and
    project manager) or an FGAC `(stakeholder_need, manage)` grant.

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, "stakeholder_need_owner",
        organization_id=project.organization_id, project_id=project.id,
    ):
        return
    held = get_effective_permissions(
        db, current_user.id, organization_id=project.organization_id, project_id=project.id
    )
    if permission_satisfied(held, NEED_MANAGE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Stakeholder Need Owner (or admin/manager) may do this.")


def create_need_from_payload(db: Session, payload: NeedCreate, creator: User, project: Project) -> NeedOut:
    """Validates a create payload, creates the need, audit-logs, commits and
    returns the API shape."""
    validate_people(db, project.organization_id, payload.owner_id)
    need = create_need(db, project_id=project.id, creator=creator, **payload.model_dump())
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="created", actor_id=creator.id,
              project_id=project.id, detail={"name": payload.name})
    db.commit()
    db.refresh(need)
    return need_to_out(need, get_current_need_version(db, need.id))


def update_need_from_payload(
    db: Session, need: StakeholderNeed, payload: NeedUpdate, actor: User, project: Project
) -> NeedOut:
    """Applies a partial update as a new version (only fields present in the
    request body change), audit-logs, commits and returns the API shape."""
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note"})
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A Stakeholder Need name cannot be null.")
    for text_field in _TEXT_FIELDS:
        if text_field in sent and sent[text_field] is None:
            sent[text_field] = ""
    validate_people(db, project.organization_id, sent.get("owner_id"))
    current = get_current_need_version(db, need.id)
    apply_need_new_version(db, need, current, actor, changes=sent, change_note=payload.change_note)
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="updated", actor_id=actor.id,
              project_id=need.project_id)
    db.commit()
    return need_to_out(need, get_current_need_version(db, need.id))


def transition_need_endpoint(
    db: Session, need: StakeholderNeed, new_status: NeedStatus, actor: User, *, action: str, comment: str | None
) -> NeedOut:
    """Runs a lifecycle transition (409 if illegal), commits and returns the API shape."""
    current = get_current_need_version(db, need.id)
    apply_value_error_as_conflict(transition_need, db, need, current, new_status, actor, action=action, comment=comment)
    db.commit()
    return need_to_out(need, get_current_need_version(db, need.id))


# --- Links -------------------------------------------------------------------


def holder_to_out(db: Session, link, kind: str, record: Stakeholder | Persona) -> NeedHolderOut:
    """API shape of a "has need" link seen from the need."""
    return NeedHolderOut(link_id=link.id, kind=kind, id=record.id, name=holder_name(db, kind, record), scope=record.scope.value)


def held_need_to_out(db: Session, link, need: StakeholderNeed) -> HeldNeedOut:
    """API shape of a "has need" link seen from a Stakeholder/Persona."""
    version = get_current_need_version(db, need.id)
    return HeldNeedOut(link_id=link.id, id=need.id, name=version.name, status=version.status)


def requirement_to_out(db: Session, link, requirement: Requirement) -> NeedRequirementOut:
    """API shape of a "gives rise to" link."""
    return NeedRequirementOut(
        link_id=link.id, id=requirement.id, unique_code=requirement.unique_code,
        title=get_current_requirement_version(db, requirement.id).name,
    )


def list_holders(db: Session, need: StakeholderNeed, project: Project) -> list[NeedHolderOut]:
    """The Stakeholders/Personas that have `need`, restricted to those the need's
    project can see."""
    out = []
    for link, kind, record in list_need_holders(db, need, project.organization_id):
        try:
            get_visible_holder(db, project, kind, record.id)
        except HTTPException:
            continue
        out.append(holder_to_out(db, link, kind, record))
    return out


def add_holder(
    db: Session, need: StakeholderNeed, kind: str, holder_id: uuid.UUID, actor: User, project: Project
) -> NeedHolderOut:
    """Links a visible Stakeholder/Persona to `need` ("has need"), audit-logs and
    commits (409 on a duplicate)."""
    record = get_visible_holder(db, project, kind, holder_id)
    link = apply_value_error_as_conflict(
        add_has_need_link, db, kind, record.id, need, actor, organization_id=project.organization_id,
        project_id=project.id,
    )
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="holder_added", actor_id=actor.id,
              project_id=need.project_id, detail={"kind": kind, "id": str(record.id)})
    db.commit()
    return holder_to_out(db, link, kind, record)


def remove_holder(
    db: Session, need: StakeholderNeed, kind: str, holder_id: uuid.UUID, actor: User, project: Project
) -> None:
    """Removes a "has need" link (404 if there is none), audit-logs and commits."""
    for link, link_kind, record in list_need_holders(db, need, project.organization_id):
        if link_kind == kind and record.id == holder_id:
            delete_link(db, link)
            log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="holder_removed",
                      actor_id=actor.id, project_id=need.project_id, detail={"kind": kind, "id": str(holder_id)})
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "That record does not have this need.")


def get_project_requirement(db: Session, project: Project, requirement_id: uuid.UUID) -> Requirement:
    """A Requirement of `project` (404 for another project's)."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    return requirement


def list_requirements(db: Session, need: StakeholderNeed, project: Project) -> list[NeedRequirementOut]:
    """The Requirements `need` gave rise to."""
    out = []
    for link in list_need_requirement_links(db, need, project.organization_id):
        requirement = db.get(Requirement, link.target_id)
        if requirement is not None and requirement.project_id == project.id:
            out.append(requirement_to_out(db, link, requirement))
    return out


def add_requirement(
    db: Session, need: StakeholderNeed, requirement_id: uuid.UUID, actor: User, project: Project
) -> NeedRequirementOut:
    """Links `need` to a Requirement of the same project ("gives rise to"),
    audit-logs and commits (409 on a duplicate)."""
    requirement = get_project_requirement(db, project, requirement_id)
    link = apply_value_error_as_conflict(
        add_gives_rise_to_link, db, need, requirement.id, actor, organization_id=project.organization_id,
        project_id=project.id,
    )
    log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="requirement_linked",
              actor_id=actor.id, project_id=need.project_id, detail={"requirement_id": str(requirement.id)})
    db.commit()
    return requirement_to_out(db, link, requirement)


def remove_requirement(
    db: Session, need: StakeholderNeed, requirement_id: uuid.UUID, actor: User, project: Project
) -> None:
    """Removes a "gives rise to" link (404 if there is none), audit-logs and commits."""
    for link in list_need_requirement_links(db, need, project.organization_id):
        if link.target_id == requirement_id:
            delete_link(db, link)
            log_event(db, entity_type=NEED_ARTEFACT_TYPE, entity_id=need.id, action="requirement_unlinked",
                      actor_id=actor.id, project_id=need.project_id, detail={"requirement_id": str(requirement_id)})
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "This need did not give rise to that Requirement.")


# --- Comments and files ------------------------------------------------------


def add_comment(db: Session, need: StakeholderNeed, user: User, body: str, **scope_ids) -> NeedCommentOut:
    """Adds and audit-logs a comment."""
    return att.add_comment(db, NEED_ATTACHMENTS, need, user, body, **scope_ids)


def list_comments(db: Session, need: StakeholderNeed) -> list[NeedCommentOut]:
    """Comments on a need, oldest first."""
    return att.list_comments(db, NEED_ATTACHMENTS, need)


def edit_comment(
    db: Session, need: StakeholderNeed, comment_id: uuid.UUID, user: User, body: str, **scope_ids
) -> NeedCommentOut:
    """Author-only edit; audit-logged."""
    return att.edit_comment(db, NEED_ATTACHMENTS, need, comment_id, user, body, **scope_ids)


async def attach_to_comment(
    db: Session, need: StakeholderNeed, comment_id: uuid.UUID, user: User, file: UploadFile, *,
    organization_id: uuid.UUID, **scope_ids,
) -> FileAsset:
    """Author-only comment attachment."""
    return await att.attach_to_comment(
        db, NEED_ATTACHMENTS, need, comment_id, user, file, organization_id=organization_id, **scope_ids
    )


def remove_comment_attachment(
    db: Session, need: StakeholderNeed, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids
) -> None:
    """Author-only removal of a comment attachment; audit-logged."""
    att.remove_comment_attachment(db, NEED_ATTACHMENTS, need, comment_id, file_id, user, **scope_ids)


async def attach_file(
    db: Session, need: StakeholderNeed, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids
) -> FileAsset:
    """Uploads and links a file to a need (caller has checked manage)."""
    return await att.attach_file(db, NEED_ATTACHMENTS, need, user, file, organization_id=organization_id, **scope_ids)


def list_files(db: Session, need: StakeholderNeed) -> list[FileAsset]:
    """Files directly attached to a need."""
    return att.list_files(db, NEED_ATTACHMENTS, need)


def unlink_file(db: Session, need: StakeholderNeed, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    att.unlink_file(db, NEED_ATTACHMENTS, need, file_id, user, **scope_ids)
