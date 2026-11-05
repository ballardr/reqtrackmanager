"""
Module: modules.product_feedback.vocabulary_routes

Registers the endpoints of one of the module's two classified lists (`vocabularies.py`: external systems, request
channels) on the organisation and project routers, so the two lists cannot drift apart.

- Organisation tier (`register_org_vocabulary`): list, create, reorder, rename / deactivate, delete. Changes need
  the `feedback_list_admin` module role (composing with organisation admin); reading needs only the module.
- Project tier (`register_project_vocabulary`): the effective list (any member, so a picker can be filled; a project
  with no configuration of its own shows its ancestor's, and its first change copies that into it), create a
  project-local entry, override an organisation entry, delete / hide, list hidden, restore. Changes need the tier's
  triager gate (`_shared.require_request_manage`). Hiding and restoring use the shared bodies in
  `services.type_vocabulary_routes`.

Both read the module's gates from `_shared`; neither commits anywhere but its own endpoint bodies.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.service import PRODUCT_FEEDBACK_MODULE_KEY, RecordOwner
from app.schemas.project import MoveDirection
from app.schemas.type_vocabulary import (
    EffectiveTypeOut,
    HiddenTypeOut,
    OrgTypeCreate,
    OrgTypeOut,
    OrgTypeUpdate,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
    RestoreTypesOut,
    RestoreTypesRequest,
)
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.rbac import user_satisfies_module_role
from app.services.type_vocabulary import TypeVocabulary
from app.services.type_vocabulary_routes import list_hidden_types, remove_project_type, restore_hidden_types

LIST_ADMIN_ROLE_KEY = "feedback_list_admin"


def _require_list_admin(db: Session, current_user: User, organization_id: UUID) -> None:
    """Gate for changing an organisation's lists.

    Raises:
        HTTPException: 403 unless the caller is a Feedback List Admin (or organisation / server admin).
    """
    if not user_satisfies_module_role(
        db, current_user, PRODUCT_FEEDBACK_MODULE_KEY, LIST_ADMIN_ROLE_KEY, organization_id=organization_id, project_id=None,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Feedback List Admin (or org admin) may do this.")


def register_org_vocabulary(
    router: APIRouter, *, path: str, vocabulary: TypeVocabulary, entity_type: str, view_dependency,
) -> None:
    """Adds the organisation-tier endpoints of `vocabulary` under `path` (e.g. `/external-systems`) to `router`."""
    org_model = vocabulary.org_model
    label = vocabulary.label

    def _get(db: Session, organization_id: UUID, type_id: UUID):
        row = db.get(org_model, type_id)
        if row is None or row.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
        return row

    @router.get(path, response_model=list[OrgTypeOut], name=f"list_{entity_type}")
    def list_entries(organization_id: UUID, current_user: User = Depends(view_dependency), db: Session = Depends(get_db)):
        """The organisation's entries in order, inactive ones included (an administrator re-activates them)."""
        return db.scalars(
            select(org_model).where(org_model.organization_id == organization_id).order_by(org_model.sort_order)
        ).all()

    @router.post(path, response_model=OrgTypeOut, status_code=status.HTTP_201_CREATED, name=f"create_{entity_type}")
    def create_entry(
        organization_id: UUID, payload: OrgTypeCreate, current_user: User = Depends(view_dependency),
        db: Session = Depends(get_db),
    ):
        """Adds an entry at the end of the order. Needs the list admin role; 400 on a duplicate name."""
        _require_list_admin(db, current_user, organization_id)
        try:
            row = vocabulary.create_org_type(db, organization_id, payload.name)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=row.id, action="created", actor_id=current_user.id,
                  organization_id=organization_id, detail={"name": row.name})
        db.commit()
        db.refresh(row)
        return row

    @router.post(path + "/{type_id}/move", response_model=OrgTypeOut, name=f"move_{entity_type}")
    def move_entry(
        organization_id: UUID, type_id: UUID, payload: MoveDirection, current_user: User = Depends(view_dependency),
        db: Session = Depends(get_db),
    ):
        """Moves an entry up or down one place. Needs the list admin role."""
        _require_list_admin(db, current_user, organization_id)
        _get(db, organization_id, type_id)
        result = move_ordered(db, org_model, [org_model.organization_id == organization_id], type_id, payload.direction)
        log_event(db, entity_type=entity_type, entity_id=type_id, action="reordered", actor_id=current_user.id,
                  organization_id=organization_id, detail={"direction": payload.direction})
        db.commit()
        return result

    @router.patch(path + "/{type_id}", response_model=OrgTypeOut, name=f"update_{entity_type}")
    def update_entry(
        organization_id: UUID, type_id: UUID, payload: OrgTypeUpdate, current_user: User = Depends(view_dependency),
        db: Session = Depends(get_db),
    ):
        """Renames and/or activates / deactivates an entry (records reference it by id, so a rename reaches them all)."""
        _require_list_admin(db, current_user, organization_id)
        row = _get(db, organization_id, type_id)
        if payload.name is not None:
            clash = db.scalar(select(org_model.id).where(
                org_model.organization_id == organization_id, org_model.name == payload.name, org_model.id != type_id,
            ))
            if clash is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A {label.lower()} with this name already exists.")
            row.name = payload.name
        if payload.is_active is not None:
            row.is_active = payload.is_active
        log_event(db, entity_type=entity_type, entity_id=row.id, action="updated", actor_id=current_user.id,
                  organization_id=organization_id)
        db.commit()
        db.refresh(row)
        return row

    @router.delete(path + "/{type_id}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_{entity_type}")
    def delete_entry(
        organization_id: UUID, type_id: UUID, current_user: User = Depends(view_dependency), db: Session = Depends(get_db),
    ):
        """Deletes an entry; 409 while any record or project still uses it (deactivate it instead)."""
        _require_list_admin(db, current_user, organization_id)
        row = _get(db, organization_id, type_id)
        sh.apply_value_error_as_conflict(vocabulary.delete_org_type, db, row)
        log_event(db, entity_type=entity_type, entity_id=type_id, action="deleted", actor_id=current_user.id,
                  organization_id=organization_id)
        db.commit()


def register_project_vocabulary(
    router: APIRouter, *, path: str, vocabulary: TypeVocabulary, entity_type: str, view_dependency,
) -> None:
    """Adds the project-tier endpoints of `vocabulary` under `path` to `router` (prefix: a project in the URL)."""

    def _project(db: Session, project_id: UUID) -> Project:
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
        return project

    def _manage(db: Session, current_user: User, project: Project) -> None:
        sh.require_request_manage(db, current_user, RecordOwner.of_project(project))

    def _own(db: Session, project: Project, type_ref_id: UUID | None = None) -> UUID | None:
        """Gives the project its own copy of an inherited list before it is changed (the caller commits), and
        translates an id taken from the inherited list to the copy's."""
        mapping = vocabulary.materialize_inherited(db, project.id)
        return mapping.get(type_ref_id, type_ref_id) if type_ref_id is not None else None

    @router.get(path, response_model=list[EffectiveTypeOut], name=f"list_project_{entity_type}")
    def list_effective(project_id: UUID, current_user: User = Depends(view_dependency), db: Session = Depends(get_db)):
        """The project's effective list: organisation entries with overrides applied (hidden ones left out) plus
        the project's own. Open to any member so a picker can be filled."""
        project = _project(db, project_id)
        return vocabulary.resolve_effective(db, project_id, project.organization_id)

    @router.post(path, response_model=ProjectTypeOut, status_code=status.HTTP_201_CREATED, name=f"create_project_{entity_type}")
    def create_local(
        project_id: UUID, payload: ProjectTypeCreate, current_user: User = Depends(view_dependency),
        db: Session = Depends(get_db),
    ):
        """Adds an entry of this project's own. Needs the triager role; 400 on a duplicate name."""
        project = _project(db, project_id)
        _manage(db, current_user, project)
        _own(db, project)
        try:
            row = vocabulary.create_project_local(db, project_id, payload.name, display_order=payload.display_order)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=f"project_{entity_type}", entity_id=row.id, action="created", actor_id=current_user.id,
                  project_id=project_id, detail={"name": payload.name})
        db.commit()
        db.refresh(row)
        return row

    @router.put(path + "/{type_ref_id}", response_model=ProjectTypeOut, name=f"override_project_{entity_type}")
    def override(
        project_id: UUID, type_ref_id: UUID, payload: ProjectTypeOverrideUpdate,
        current_user: User = Depends(view_dependency), db: Session = Depends(get_db),
    ):
        """Renames, reorders and/or enables / disables an entry here; an organisation entry gets its override row on
        first use. `type_ref_id` is an id from the effective list."""
        project = _project(db, project_id)
        _manage(db, current_user, project)
        type_ref_id = _own(db, project, type_ref_id) or type_ref_id
        try:
            row = vocabulary.get_or_create_project_type(db, project_id, project.organization_id, type_ref_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        vocabulary.set_override(
            db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled,
        )
        log_event(db, entity_type=f"project_{entity_type}", entity_id=row.id, action="updated", actor_id=current_user.id,
                  project_id=project_id)
        db.commit()
        db.refresh(row)
        return row

    @router.delete(path + "/{type_ref_id}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_project_{entity_type}")
    def delete_or_hide(
        project_id: UUID, type_ref_id: UUID, current_user: User = Depends(view_dependency), db: Session = Depends(get_db),
    ):
        """Deletes the project's own entry, or hides an organisation entry here (restore it with `POST .../restore`);
        existing records keep what they hold. 409 while a project's own entry is in use."""
        project = _project(db, project_id)
        _manage(db, current_user, project)
        type_ref_id = _own(db, project, type_ref_id) or type_ref_id
        remove_project_type(db, vocabulary, project, type_ref_id, current_user, f"project_{entity_type}")

    @router.get(path + "/hidden", response_model=list[HiddenTypeOut], name=f"list_hidden_project_{entity_type}")
    def hidden(project_id: UUID, current_user: User = Depends(view_dependency), db: Session = Depends(get_db)):
        """The organisation entries this project has hidden. Needs the triager role."""
        project = _project(db, project_id)
        _manage(db, current_user, project)
        return list_hidden_types(db, vocabulary, project)

    @router.post(path + "/restore", response_model=RestoreTypesOut, name=f"restore_project_{entity_type}")
    def restore(
        project_id: UUID, payload: RestoreTypesRequest, current_user: User = Depends(view_dependency),
        db: Session = Depends(get_db),
    ):
        """Shows hidden organisation entries here again: all, or only `org_type_ids`. Needs the triager role."""
        project = _project(db, project_id)
        _manage(db, current_user, project)
        _own(db, project)
        return restore_hidden_types(db, vocabulary, project, payload, current_user, f"project_{entity_type}")
