"""
Module: modules.stakeholders._stakeholder_shared

Helpers shared by the org-scoped (`stakeholder_router.py`) and project-scoped
(`stakeholder_project_router.py`) Stakeholder routers, mirroring `_shared.py`
for Personas: the routers declare their own routes and these hold the bodies
the two would otherwise duplicate. Comments and files go through the shared
`_attachments` kit.

RBAC (Phase 0 resolution 6): viewing is gated by sub-component enablement
alone; create/edit/archive/retire/erase need the scope's owner role
(`org_stakeholder_owner`/`stakeholder_owner`) or a Fine-Grained Access Control
`(stakeholder, manage)` grant. Stakeholder-type admin (and scoring
configuration) is the separate org-scoped `stakeholder_type_admin` role.

Personal data (Phase 0 resolution 15): a stakeholder is a record about an
identifiable person, so audit events here never carry the name, contact info
or filenames, and `erase_stakeholder_endpoint` hard-deletes the record.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.file import FileAsset
from app.models.user import User
from app.modules.stakeholders import _attachments as att
from app.modules.stakeholders._shared import apply_value_error_as_conflict, validate_people, visibility_fields
from app.modules.stakeholders.enums import StakeholderScope, StakeholderStatus
from app.modules.stakeholders.models import (
    Persona,
    Stakeholder,
    StakeholderComment,
    StakeholderCommentFile,
    StakeholderFile,
    StakeholderVersion,
)
from app.modules.stakeholders.schemas import (
    RepresentedPersonaOut,
    StakeholderCommentOut,
    StakeholderCreate,
    StakeholderFromUserCreate,
    StakeholderOut,
    StakeholderUpdate,
)
from app.modules.stakeholders.service import (
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    STAKEHOLDERS_MODULE_KEY,
    add_represents_link,
    apply_stakeholder_new_version,
    create_stakeholder,
    erase_stakeholder,
    find_stakeholder_for_user,
    get_current_persona_version,
    get_current_stakeholder_version,
    resolve_stakeholder_type_refs,
    resolve_stakeholder_visibility,
    transition_stakeholder,
    validate_scoring_levels,
)
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role

STAKEHOLDER_MANAGE_PERMISSION = encode_permission(STAKEHOLDER_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

_OWNER_ROLE_KEY = {StakeholderScope.ORGANIZATION: "org_stakeholder_owner", StakeholderScope.PROJECT: "stakeholder_owner"}

_TEXT_FIELDS = (
    "description", "role", "organisation_group", "interests", "responsibilities", "goals_needs", "priorities",
    "constraints", "workflows_scenarios", "contact_info", "availability_constraints",
)

STAKEHOLDER_ATTACHMENTS = att.AttachmentKit(
    artefact_type=STAKEHOLDER_ARTEFACT_TYPE, label="Stakeholder", comment_model=StakeholderComment,
    comment_file_model=StakeholderCommentFile, file_model=StakeholderFile, fk="stakeholder_id",
    comment_out=StakeholderCommentOut, log_filenames=False,
)


def stakeholder_to_out(
    db: Session, stakeholder: Stakeholder, version: StakeholderVersion, *, project_id: uuid.UUID | None = None
) -> StakeholderOut:
    """Merges a stakeholder with its current version. When `project_id` is given
    (project router) and the stakeholder is an org one, also resolves its
    visibility to that project (`project_hidden`, `hidden_override`,
    `hidden_source`)."""
    hidden: dict[str, bool | str | None] = {}
    if project_id is not None and stakeholder.scope == StakeholderScope.ORGANIZATION:
        hidden = visibility_fields(resolve_stakeholder_visibility(db, project_id), stakeholder.id)
    return StakeholderOut(
        id=stakeholder.id, scope=stakeholder.scope, organization_id=stakeholder.organization_id,
        project_id=stakeholder.project_id, creator_id=stakeholder.creator_id, is_archived=stakeholder.is_archived,
        archived_at=stakeholder.archived_at, archived_by=stakeholder.archived_by, name=version.name,
        description=version.description, stakeholder_type_id=version.project_type_id or version.org_type_id,
        stakeholder_type_name=STAKEHOLDER_TYPES.display_name(
            db, org_type_id=version.org_type_id, project_type_id=version.project_type_id
        ),
        role=version.role, organisation_group=version.organisation_group, interests=version.interests,
        responsibilities=version.responsibilities, goals_needs=version.goals_needs, priorities=version.priorities,
        constraints=version.constraints, workflows_scenarios=version.workflows_scenarios,
        contact_info=version.contact_info, target_cadence=version.target_cadence,
        availability_constraints=version.availability_constraints, influence_level_id=version.influence_level_id,
        interest_level_id=version.interest_level_id, status=version.status, owner_id=version.owner_id,
        user_id=version.user_id, version_number=version.version_number, created_at=stakeholder.created_at,
        updated_at=stakeholder.updated_at, **hidden,
    )


def get_stakeholder_in_scope(
    db: Session, scope: StakeholderScope, *, organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None, stakeholder_id: uuid.UUID,
) -> Stakeholder:
    """Loads a stakeholder, 404ing unless it exists, matches `scope` and
    belongs to the given organisation/project (so cross-tenant ids look absent)."""
    stakeholder = db.get(Stakeholder, stakeholder_id)
    if stakeholder is None or stakeholder.scope != scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder not found.")
    if scope == StakeholderScope.ORGANIZATION and stakeholder.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder not found.")
    if scope == StakeholderScope.PROJECT and stakeholder.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder not found.")
    return stakeholder


def require_stakeholder_manage(
    db: Session, current_user: User, scope: StakeholderScope, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for create/edit/archive/retire/erase/attachment actions: the
    scope's owner role (which composes with server admin, org admin and, for
    project scope, project manager) or an FGAC `(stakeholder, manage)` grant.

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, _OWNER_ROLE_KEY[scope],
        organization_id=organization_id, project_id=project_id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=organization_id, project_id=project_id)
    if permission_satisfied(held, STAKEHOLDER_MANAGE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Stakeholder Owner (or admin/manager) may do this.")


def require_stakeholder_type_admin(db: Session, current_user: User, *, organization_id: uuid.UUID) -> None:
    """Gate for org-level Stakeholder type CRUD (`stakeholder_type_admin`,
    composing with server admin and org admin)."""
    if not user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, "stakeholder_type_admin", organization_id=organization_id,
        project_id=None,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Stakeholder Type Admin (or org admin) may do this.")


def _validate_refs(db: Session, organization_id: uuid.UUID, content: dict) -> None:
    """Owner/user tenancy and scoring-level checks for a payload's fields.

    Raises:
        HTTPException: 400 on the first violation.
    """
    validate_people(db, organization_id, content.get("owner_id"), content.get("user_id"))
    try:
        validate_scoring_levels(
            db, organization_id, influence_level_id=content.get("influence_level_id"),
            interest_level_id=content.get("interest_level_id"),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def create_stakeholder_from_payload(
    db: Session, scope: StakeholderScope, payload: StakeholderCreate, creator: User, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> StakeholderOut:
    """Validates a create payload, creates the stakeholder, audit-logs (no
    personal data), commits and returns the API shape."""
    content = payload.model_dump(exclude={"stakeholder_type_id"})
    _validate_refs(db, organization_id, content)
    try:
        org_type_id, project_type_id = resolve_stakeholder_type_refs(
            db, scope, organization_id=organization_id, project_id=project_id, type_id=payload.stakeholder_type_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    stakeholder = create_stakeholder(
        db, scope=scope, organization_id=organization_id, project_id=project_id, creator=creator,
        org_type_id=org_type_id, project_type_id=project_type_id, **content,
    )
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="created",
              actor_id=creator.id, organization_id=stakeholder.organization_id, project_id=stakeholder.project_id)
    db.commit()
    db.refresh(stakeholder)
    return stakeholder_to_out(db, stakeholder, get_current_stakeholder_version(db, stakeholder.id))


def create_stakeholder_from_user(
    db: Session, scope: StakeholderScope, payload: StakeholderFromUserCreate, creator: User, *,
    organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> StakeholderOut:
    """"Create stakeholder from org user" (resolution 13): prefills the name
    and contact info from the user's account.

    Raises:
        HTTPException: 400 if the user is not an org member; 409 if a live
            stakeholder in this scope already represents them.
    """
    validate_people(db, organization_id, payload.user_id)
    if find_stakeholder_for_user(
        db, scope, organization_id=organization_id, project_id=project_id, user_id=payload.user_id
    ) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A Stakeholder already represents this user.")
    user = db.get(User, payload.user_id)
    assert user is not None  # validate_people proved membership
    return create_stakeholder_from_payload(
        db, scope,
        StakeholderCreate(
            name=user.display_name, contact_info=user.email, user_id=user.id,
            stakeholder_type_id=payload.stakeholder_type_id, role=payload.role,
            organisation_group=payload.organisation_group, target_cadence=payload.target_cadence,
        ),
        creator, organization_id=organization_id, project_id=project_id,
    )


def update_stakeholder_from_payload(
    db: Session, stakeholder: Stakeholder, payload: StakeholderUpdate, actor: User, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> StakeholderOut:
    """Applies a partial update as a new version (only fields present in the
    request body change), audit-logs, commits and returns the API shape."""
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note"})
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A Stakeholder name cannot be null.")
    for text_field in _TEXT_FIELDS:
        if text_field in sent and sent[text_field] is None:
            sent[text_field] = ""
    _validate_refs(db, organization_id, sent)
    if "stakeholder_type_id" in sent:
        try:
            sent["org_type_id"], sent["project_type_id"] = resolve_stakeholder_type_refs(
                db, stakeholder.scope, organization_id=organization_id, project_id=project_id,
                type_id=sent.pop("stakeholder_type_id"),
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    current = get_current_stakeholder_version(db, stakeholder.id)
    apply_stakeholder_new_version(db, stakeholder, current, actor, changes=sent, change_note=payload.change_note)
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="updated",
              actor_id=actor.id, organization_id=stakeholder.organization_id, project_id=stakeholder.project_id)
    db.commit()
    return stakeholder_to_out(db, stakeholder, get_current_stakeholder_version(db, stakeholder.id))


def transition_stakeholder_endpoint(
    db: Session, stakeholder: Stakeholder, new_status: StakeholderStatus, actor: User, *, action: str,
    comment: str | None,
) -> StakeholderOut:
    """Runs a lifecycle transition (409 if illegal), commits and returns the API shape."""
    current = get_current_stakeholder_version(db, stakeholder.id)
    apply_value_error_as_conflict(
        transition_stakeholder, db, stakeholder, current, new_status, actor, action=action, comment=comment
    )
    db.commit()
    return stakeholder_to_out(db, stakeholder, get_current_stakeholder_version(db, stakeholder.id))


def erase_stakeholder_endpoint(db: Session, stakeholder: Stakeholder, actor: User) -> None:
    """Hard-deletes a stakeholder and all data held about them, then commits."""
    erase_stakeholder(db, stakeholder, actor)
    db.commit()


# --- Represents Persona ------------------------------------------------------


def represents_to_out(db: Session, link, persona: Persona) -> RepresentedPersonaOut:
    """API shape of a link seen from the stakeholder side."""
    return RepresentedPersonaOut(
        link_id=link.id, id=persona.id, name=get_current_persona_version(db, persona.id).name,
        scope=persona.scope.value,
    )


def stakeholder_link_to_out(db: Session, link, stakeholder: Stakeholder) -> RepresentedPersonaOut:
    """API shape of a link seen from the persona side (the other end is a stakeholder)."""
    return RepresentedPersonaOut(
        link_id=link.id, id=stakeholder.id, name=get_current_stakeholder_version(db, stakeholder.id).name,
        scope=stakeholder.scope.value,
    )


def add_represents(
    db: Session, stakeholder: Stakeholder, persona: Persona, actor: User, *, organization_id: uuid.UUID
) -> RepresentedPersonaOut:
    """Links `stakeholder` to `persona`, audit-logs and commits (409 on a
    duplicate or an incompatible pair)."""
    link = apply_value_error_as_conflict(
        add_represents_link, db, stakeholder, persona, actor, organization_id=organization_id,
        project_id=stakeholder.project_id,
    )
    log_event(db, entity_type=STAKEHOLDER_ARTEFACT_TYPE, entity_id=stakeholder.id, action="represents_added",
              actor_id=actor.id, organization_id=stakeholder.organization_id, project_id=stakeholder.project_id,
              detail={"persona_id": str(persona.id)})
    db.commit()
    return represents_to_out(db, link, persona)


# --- Comments and files ------------------------------------------------------


def add_comment(db: Session, stakeholder: Stakeholder, user: User, body: str, **scope_ids) -> StakeholderCommentOut:
    """Adds and audit-logs a comment."""
    return att.add_comment(db, STAKEHOLDER_ATTACHMENTS, stakeholder, user, body, **scope_ids)


def list_comments(db: Session, stakeholder: Stakeholder) -> list[StakeholderCommentOut]:
    """Comments on a stakeholder, oldest first."""
    return att.list_comments(db, STAKEHOLDER_ATTACHMENTS, stakeholder)


def edit_comment(
    db: Session, stakeholder: Stakeholder, comment_id: uuid.UUID, user: User, body: str, **scope_ids
) -> StakeholderCommentOut:
    """Author-only edit; audit-logged."""
    return att.edit_comment(db, STAKEHOLDER_ATTACHMENTS, stakeholder, comment_id, user, body, **scope_ids)


async def attach_to_comment(
    db: Session, stakeholder: Stakeholder, comment_id: uuid.UUID, user: User, file: UploadFile, *,
    organization_id: uuid.UUID, **scope_ids,
) -> FileAsset:
    """Author-only comment attachment."""
    return await att.attach_to_comment(
        db, STAKEHOLDER_ATTACHMENTS, stakeholder, comment_id, user, file, organization_id=organization_id, **scope_ids
    )


def remove_comment_attachment(
    db: Session, stakeholder: Stakeholder, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids
) -> None:
    """Author-only removal of a comment attachment; audit-logged."""
    att.remove_comment_attachment(db, STAKEHOLDER_ATTACHMENTS, stakeholder, comment_id, file_id, user, **scope_ids)


async def attach_file(
    db: Session, stakeholder: Stakeholder, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids
) -> FileAsset:
    """Uploads and links a file to a stakeholder (caller has checked manage)."""
    return await att.attach_file(
        db, STAKEHOLDER_ATTACHMENTS, stakeholder, user, file, organization_id=organization_id, **scope_ids
    )


def list_files(db: Session, stakeholder: Stakeholder) -> list[FileAsset]:
    """Files directly attached to a stakeholder."""
    return att.list_files(db, STAKEHOLDER_ATTACHMENTS, stakeholder)


def unlink_file(db: Session, stakeholder: Stakeholder, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    att.unlink_file(db, STAKEHOLDER_ATTACHMENTS, stakeholder, file_id, user, **scope_ids)

