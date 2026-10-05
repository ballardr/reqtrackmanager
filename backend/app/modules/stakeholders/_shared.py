"""
Module: modules.stakeholders._shared

Helpers shared by the org-scoped (`router.py`) and project-scoped
(`project_router.py`) routers, which expose the same Persona surface and
differ only in which of `organization_id`/`project_id` scopes the call and
which module role gates a mutation. Each router still declares its own
routes; the bodies that would otherwise be duplicated (comments, file
attachment, type updates) live here.

RBAC (Phase 0 resolution 6): viewing is gated by sub-component enablement
alone; create/edit/archive/retire need the scope's owner role
(`persona_owner`/`org_persona_owner`) or a Fine-Grained Access Control
`(persona, manage)` grant. There is no approve action. Persona-type admin is
the separate org-scoped `persona_type_admin` role.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _attachments as att
from app.modules.stakeholders.enums import PersonaScope, PersonaStatus, StakeholderScope
from app.modules.stakeholders.models import (
    Persona,
    PersonaComment,
    PersonaCommentFile,
    PersonaFile,
    PersonaTypeDefinition,
    PersonaVersion,
    Stakeholder,
)
from app.modules.stakeholders.schemas import PersonaCommentOut, PersonaCreate, PersonaOut, PersonaUpdate
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDERS_MODULE_KEY,
    apply_persona_new_version,
    create_persona,
    get_current_persona_version,
    get_current_stakeholder_version,
    resolve_persona_type_refs,
    resolve_persona_weight_with_source,
    transition_persona,
)
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_org_roles, get_effective_permissions, permission_satisfied, user_satisfies_module_role

PERSONA_MANAGE_PERMISSION = encode_permission(PERSONA_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

_OWNER_ROLE_KEY = {PersonaScope.ORGANIZATION: "org_persona_owner", PersonaScope.PROJECT: "persona_owner"}


def persona_to_out(db: Session, persona: Persona, version: PersonaVersion, *, project_id: uuid.UUID | None = None) -> PersonaOut:
    """Merges a persona with its current version. When `project_id` is given
    (project router), also resolves `effective_weight` and `weight_override`
    for that project."""
    from app.modules.stakeholders.models import ProjectPersonaWeight

    type_ref = version.project_type_id or version.org_type_id
    effective_weight = override = weight_source = None
    if project_id is not None:
        effective_weight, weight_source = resolve_persona_weight_with_source(db, project_id, persona.id, version.weight)
        override = db.scalar(
            select(ProjectPersonaWeight.weight).where(
                ProjectPersonaWeight.project_id == project_id, ProjectPersonaWeight.persona_id == persona.id
            )
        )
    return PersonaOut(
        id=persona.id, scope=persona.scope, organization_id=persona.organization_id, project_id=persona.project_id,
        creator_id=persona.creator_id, is_archived=persona.is_archived, archived_at=persona.archived_at,
        archived_by=persona.archived_by, name=version.name, description=version.description,
        persona_type_id=type_ref,
        persona_type_name=PERSONA_TYPES.display_name(
            db, org_type_id=version.org_type_id, project_type_id=version.project_type_id
        ),
        role_title=version.role_title, goals=version.goals, needs=version.needs, behaviours=version.behaviours,
        context_environment=version.context_environment, skills_proficiency=version.skills_proficiency,
        frequency_of_use=version.frequency_of_use, constraints=version.constraints, weight=version.weight,
        status=version.status, owner_id=version.owner_id, champion_id=version.champion_id,
        version_number=version.version_number, effective_weight=effective_weight, weight_override=override,
        weight_source=weight_source,
        created_at=persona.created_at, updated_at=persona.updated_at,
    )


def get_persona_in_scope(
    db: Session, scope: PersonaScope, *, organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None, persona_id: uuid.UUID,
) -> Persona:
    """Loads a persona, 404ing unless it exists, matches `scope` and belongs
    to the given organisation/project (so cross-tenant ids look absent)."""
    persona = db.get(Persona, persona_id)
    if persona is None or persona.scope != scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found.")
    if scope == PersonaScope.ORGANIZATION and persona.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found.")
    if scope == PersonaScope.PROJECT and persona.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found.")
    return persona


def require_persona_manage(
    db: Session, current_user: User, scope: PersonaScope, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Gate for create/edit/archive/retire/weight/attachment actions: the
    scope's owner role (which composes with server admin, org admin and, for
    project scope, project manager) or an FGAC `(persona, manage)` grant.

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, _OWNER_ROLE_KEY[scope],
        organization_id=organization_id, project_id=project_id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=organization_id, project_id=project_id)
    if permission_satisfied(held, PERSONA_MANAGE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Persona Owner (or admin/manager) may do this.")


def require_persona_type_admin(db: Session, current_user: User, *, organization_id: uuid.UUID) -> None:
    """Gate for org-level Persona type CRUD (`persona_type_admin`, composing
    with server admin and org admin)."""
    if not user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, "persona_type_admin", organization_id=organization_id, project_id=None,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Persona Type Admin (or org admin) may do this.")


def apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls `fn`, translating `ValueError` (illegal transition / in-use
    type) into HTTP 409."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def validate_people(db: Session, organization_id: uuid.UUID, *user_ids: uuid.UUID | None) -> None:
    """Rejects an owner/champion who is not an active member of the
    organisation, so a persona can't point at a user from another tenant.

    Raises:
        HTTPException: 400 on the first user not in the organisation.
    """
    for user_id in user_ids:
        if user_id is not None and not get_effective_org_roles(db, user_id, organization_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner/champion must be a member of this organisation.")


# --- Comments and files (shared kit, see `_attachments`) ---------------------

PERSONA_ATTACHMENTS = att.AttachmentKit(
    artefact_type=PERSONA_ARTEFACT_TYPE, label="Persona", comment_model=PersonaComment,
    comment_file_model=PersonaCommentFile, file_model=PersonaFile, fk="persona_id", comment_out=PersonaCommentOut,
)


def add_comment(db: Session, persona: Persona, user: User, body: str, **scope_ids) -> PersonaCommentOut:
    """Adds and audit-logs a comment."""
    return att.add_comment(db, PERSONA_ATTACHMENTS, persona, user, body, **scope_ids)


def list_comments(db: Session, persona: Persona) -> list[PersonaCommentOut]:
    """Comments on a persona, oldest first."""
    return att.list_comments(db, PERSONA_ATTACHMENTS, persona)


def edit_comment(db: Session, persona: Persona, comment_id: uuid.UUID, user: User, body: str, **scope_ids) -> PersonaCommentOut:
    """Author-only edit; audit-logged."""
    return att.edit_comment(db, PERSONA_ATTACHMENTS, persona, comment_id, user, body, **scope_ids)


async def attach_to_comment(
    db: Session, persona: Persona, comment_id: uuid.UUID, user: User, file: UploadFile, *, organization_id: uuid.UUID,
    **scope_ids,
) -> FileAsset:
    """Author-only comment attachment (see `_attachments.attach_to_comment`)."""
    return await att.attach_to_comment(
        db, PERSONA_ATTACHMENTS, persona, comment_id, user, file, organization_id=organization_id, **scope_ids
    )


def remove_comment_attachment(
    db: Session, persona: Persona, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids
) -> None:
    """Author-only removal of a comment attachment; audit-logged."""
    att.remove_comment_attachment(db, PERSONA_ATTACHMENTS, persona, comment_id, file_id, user, **scope_ids)


async def attach_file(
    db: Session, persona: Persona, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids
) -> FileAsset:
    """Uploads and links a file to a persona (caller has checked manage)."""
    return await att.attach_file(db, PERSONA_ATTACHMENTS, persona, user, file, organization_id=organization_id, **scope_ids)


def list_files(db: Session, persona: Persona) -> list[FileAsset]:
    """Files directly attached to a persona."""
    return att.list_files(db, PERSONA_ATTACHMENTS, persona)


def unlink_file(db: Session, persona: Persona, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    att.unlink_file(db, PERSONA_ATTACHMENTS, persona, file_id, user, **scope_ids)


def get_org_type(db: Session, organization_id: uuid.UUID, type_id: uuid.UUID) -> PersonaTypeDefinition:
    """Loads an org Persona type, 404ing across organisations."""
    row = db.get(PersonaTypeDefinition, type_id)
    if row is None or row.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona type not found.")
    return row


# --- Create / update bodies --------------------------------------------------


def create_persona_from_payload(
    db: Session, scope: PersonaScope, payload: PersonaCreate, creator: User, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> PersonaOut:
    """Validates a create payload (type reference, owner/champion tenancy),
    creates the persona, audit-logs, commits and returns the API shape."""
    validate_people(db, organization_id, payload.owner_id, payload.champion_id)
    try:
        org_type_id, project_type_id = resolve_persona_type_refs(
            db, scope, organization_id=organization_id, project_id=project_id, type_id=payload.persona_type_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    content = payload.model_dump(exclude={"persona_type_id"})
    persona = create_persona(
        db, scope=scope, organization_id=organization_id, project_id=project_id, creator=creator,
        org_type_id=org_type_id, project_type_id=project_type_id, **content,
    )
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="created", actor_id=creator.id,
              organization_id=persona.organization_id, project_id=persona.project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(persona)
    return persona_to_out(db, persona, get_current_persona_version(db, persona.id), project_id=project_id)


def update_persona_from_payload(
    db: Session, persona: Persona, payload: PersonaUpdate, actor: User, *, organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> PersonaOut:
    """Applies a partial update as a new version (only fields present in the
    request body change), audit-logs, commits and returns the API shape."""
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note"})
    # `name` is NOT NULL: an explicit null would otherwise be applied verbatim.
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A Persona name cannot be null.")
    for text_field in ("description", "role_title", "goals", "needs", "behaviours", "context_environment",
                       "skills_proficiency", "frequency_of_use", "constraints"):
        if text_field in sent and sent[text_field] is None:
            sent[text_field] = ""
    validate_people(db, organization_id, sent.get("owner_id"), sent.get("champion_id"))
    if "persona_type_id" in sent:
        try:
            sent["org_type_id"], sent["project_type_id"] = resolve_persona_type_refs(
                db, persona.scope, organization_id=organization_id, project_id=project_id,
                type_id=sent.pop("persona_type_id"),
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    current = get_current_persona_version(db, persona.id)
    apply_persona_new_version(db, persona, current, actor, changes=sent, change_note=payload.change_note)
    log_event(db, entity_type=PERSONA_ARTEFACT_TYPE, entity_id=persona.id, action="updated", actor_id=actor.id,
              organization_id=persona.organization_id, project_id=persona.project_id)
    db.commit()
    return persona_to_out(db, persona, get_current_persona_version(db, persona.id), project_id=project_id)


def transition_persona_endpoint(
    db: Session, persona: Persona, new_status: PersonaStatus, actor: User, *, action: str,
    comment: str | None, project_id: uuid.UUID | None,
) -> PersonaOut:
    """Runs a lifecycle transition (409 if illegal), commits and returns the
    API shape."""
    current = get_current_persona_version(db, persona.id)
    apply_value_error_as_conflict(transition_persona, db, persona, current, new_status, actor, action=action, comment=comment)
    db.commit()
    return persona_to_out(db, persona, get_current_persona_version(db, persona.id), project_id=project_id)


# --- Records a project can see -----------------------------------------------


def get_visible_stakeholder(db: Session, project: Project, stakeholder_id: uuid.UUID) -> Stakeholder:
    """A Stakeholder `project` can see (its own, or its organisation's), else 404."""
    stakeholder = db.get(Stakeholder, stakeholder_id)
    visible = stakeholder is not None and (
        (stakeholder.scope == StakeholderScope.PROJECT and stakeholder.project_id == project.id)
        or (stakeholder.scope == StakeholderScope.ORGANIZATION
            and stakeholder.organization_id == project.organization_id)
    )
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder not found.")
    return stakeholder


def get_visible_persona(db: Session, project: Project, persona_id: uuid.UUID) -> Persona:
    """A Persona `project` can see (its own, or its organisation's), else 404."""
    persona = db.get(Persona, persona_id)
    visible = persona is not None and (
        (persona.scope == PersonaScope.PROJECT and persona.project_id == project.id)
        or (persona.scope == PersonaScope.ORGANIZATION and persona.organization_id == project.organization_id)
    )
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found.")
    return persona


def get_visible_holder(db: Session, project: Project, kind: str, holder_id: uuid.UUID) -> Stakeholder | Persona:
    """A Stakeholder/Persona (`kind` is its artefact type) `project` can see, else 404."""
    if kind == STAKEHOLDER_ARTEFACT_TYPE:
        return get_visible_stakeholder(db, project, holder_id)
    return get_visible_persona(db, project, holder_id)


def holder_name(db: Session, kind: str, record: Stakeholder | Persona) -> str:
    """The current name of a Stakeholder/Persona."""
    if kind == STAKEHOLDER_ARTEFACT_TYPE:
        return get_current_stakeholder_version(db, record.id).name
    return get_current_persona_version(db, record.id).name
