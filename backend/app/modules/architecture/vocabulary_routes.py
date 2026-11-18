"""
Module: modules.architecture.vocabulary_routes

Builds the endpoints of one vocabulary on the organisation and project routers,
so the element type and connection type APIs are the same code with different
paths and schemas. The hide-and-restore bodies are the shared ones in
`services.type_vocabulary_routes`.

Organisation endpoints change the organisation's defaults. Project endpoints
read the project's effective list and change its own rows; deleting an
organisation default there hides it, and restoring shows it again.

This file deliberately has no postponed annotations: FastAPI resolves the
schema classes handed to the builders from the annotations of the functions
defined inside them.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture.service import ArchitectureVocabulary
from app.schemas.project import MoveDirection
from app.schemas.type_vocabulary import HiddenTypeOut, RestoreTypesOut, RestoreTypesRequest
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.type_vocabulary_routes import list_hidden_types, remove_project_type, restore_hidden_types


def _field_values(payload) -> dict:
    """The set fields of a create or update body, with enum members as their string values."""
    return {
        key: getattr(value, "value", value) for key, value in payload.model_dump(exclude_unset=True).items()
    }


def add_org_routes(
    router: APIRouter, *, path: str, vocabulary: ArchitectureVocabulary, create_schema, update_schema, out_schema,
    entity_type: str, require_view, create_route: bool = True,
) -> None:
    """Adds list, create, update, move and delete of the organisation's rows to `router` under `/{path}`.

    `create_route=False` leaves out the JSON create endpoint, for a vocabulary whose rows are created another way (a
    symbol is uploaded as a file: `symbol_routes`)."""

    def org_row(db: Session, organization_id: UUID, type_id: UUID):
        row = db.get(vocabulary.model, type_id)
        if row is None or row.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{vocabulary.label} not found.")
        return row

    @router.get(f"/{path}", response_model=list[out_schema])
    def list_org_rows(
        organization_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The organisation's default rows in picker order."""
        return vocabulary.org_rows(db, organization_id)

    def create_org_row(
        organization_id: UUID, payload: create_schema, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Creates an organisation default at the end of the order. 400 on a clashing name."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        try:
            row = vocabulary.create(db, project_id=None, organization_id=organization_id, **_field_values(payload))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=row.id, action="created", actor_id=current_user.id,
                  organization_id=organization_id, detail={"name": row.name})
        db.commit()
        db.refresh(row)
        return row

    if create_route:
        router.add_api_route(f"/{path}", create_org_row, methods=["POST"], response_model=out_schema, status_code=status.HTTP_201_CREATED)

    @router.patch(f"/{path}/{{type_id}}", response_model=out_schema)
    def update_org_row(
        organization_id: UUID, type_id: UUID, payload: update_schema, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Changes an organisation default. References are by id, so a rename never affects a record."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        row = org_row(db, organization_id, type_id)
        try:
            vocabulary.update(db, row, organization_id, **_field_values(payload))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=row.id, action="updated", actor_id=current_user.id,
                  organization_id=organization_id)
        db.commit()
        db.refresh(row)
        return row

    @router.post(f"/{path}/{{type_id}}/move", response_model=out_schema)
    def move_org_row(
        organization_id: UUID, type_id: UUID, payload: MoveDirection, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Moves a default up or down one place."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        org_row(db, organization_id, type_id)
        result = move_ordered(
            db, vocabulary.model, [vocabulary.model.organization_id == organization_id], type_id, payload.direction,
        )
        log_event(db, entity_type=entity_type, entity_id=type_id, action="reordered", actor_id=current_user.id,
                  organization_id=organization_id, detail={"direction": payload.direction})
        db.commit()
        return result

    @router.delete(f"/{path}/{{type_id}}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_org_row(
        organization_id: UUID, type_id: UUID, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Deletes a default. 409 while a record uses it."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        row = org_row(db, organization_id, type_id)
        try:
            vocabulary.delete_org_row(db, row)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=type_id, action="deleted", actor_id=current_user.id,
                  organization_id=organization_id)
        db.commit()


def add_project_routes(
    router: APIRouter, *, path: str, vocabulary: ArchitectureVocabulary, create_schema, update_schema, out_schema,
    entity_type: str, require_view, create_route: bool = True,
) -> None:
    """Adds the project's effective list, its own rows' create, update, move and delete (which hides an
    organisation default) and the hidden-default list and restore to `router` under `/{path}`. `create_route=False`
    leaves out the JSON create endpoint (see `add_org_routes`)."""

    @router.get(f"/{path}", response_model=list[out_schema])
    def list_project_rows(
        project_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The project's effective list: the organisation's defaults it has not hidden, then its own rows.
        Open to any project member so a picker can be filled."""
        project = sh.get_project(db, project_id)
        return vocabulary.resolve_effective(db, project_id, project.organization_id).rows

    @router.get(f"/{path}/hidden", response_model=list[HiddenTypeOut])
    def list_hidden_rows(
        project_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The organisation defaults this project has hidden."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        return list_hidden_types(db, vocabulary, project)

    @router.post(f"/{path}/restore", response_model=RestoreTypesOut)
    def restore_rows(
        project_id: UUID, payload: RestoreTypesRequest, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Shows hidden organisation defaults again: every one, or only `org_type_ids`."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        return restore_hidden_types(db, vocabulary, project, payload, current_user, entity_type)

    def create_project_row(
        project_id: UUID, payload: create_schema, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Creates a row owned by the project. 400 on a name the project already lists."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        vocabulary.materialize_inherited(db, project_id)
        try:
            row = vocabulary.create(
                db, project_id=project_id, organization_id=project.organization_id, **_field_values(payload),
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=row.id, action="created", actor_id=current_user.id,
                  project_id=project_id, detail={"name": row.name})
        db.commit()
        db.refresh(row)
        return row

    if create_route:
        router.add_api_route(f"/{path}", create_project_row, methods=["POST"], response_model=out_schema, status_code=status.HTTP_201_CREATED)

    @router.patch(f"/{path}/{{type_id}}", response_model=out_schema)
    def update_project_row(
        project_id: UUID, type_id: UUID, payload: update_schema, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Changes one of the project's own rows. An organisation default is changed by hiding it and adding a
        row of the project's own."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        try:
            row = vocabulary.own_row(db, project_id, project.organization_id, type_id)
            vocabulary.update(db, row, project.organization_id, **_field_values(payload))
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        log_event(db, entity_type=entity_type, entity_id=row.id, action="updated", actor_id=current_user.id,
                  project_id=project_id)
        db.commit()
        db.refresh(row)
        return row

    @router.post(f"/{path}/{{type_id}}/move", response_model=out_schema)
    def move_project_row(
        project_id: UUID, type_id: UUID, payload: MoveDirection, current_user: User = Depends(require_view),
        db: Session = Depends(get_db),
    ):
        """Moves one of the project's own rows up or down one place among its own rows."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        try:
            row = vocabulary.own_row(db, project_id, project.organization_id, type_id)
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        result = move_ordered(
            db, vocabulary.model, [vocabulary.model.project_id == project_id], row.id, payload.direction,
        )
        log_event(db, entity_type=entity_type, entity_id=row.id, action="reordered", actor_id=current_user.id,
                  project_id=project_id, detail={"direction": payload.direction})
        db.commit()
        return result

    @router.delete(f"/{path}/{{type_id}}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_project_row(
        project_id: UUID, type_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Deletes one of the project's own rows (409 while a record uses it), or hides an organisation default
        here (restore it with `POST /{path}/restore`). Hiding stops new use only."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        remove_project_type(db, vocabulary, project, type_id, current_user, entity_type)
