"""
Module: services.type_vocabulary_routes

The shared bodies of the three project-side endpoints every typed vocabulary
(Pain Point, Persona, Stakeholder, Risk types) offers for organisation defaults:
"delete" a type (hides an organisation default, deletes a project-local type),
list the hidden defaults, and restore them. A module's router keeps its own
paths, permission dependency and audit entity name, and calls these for the body,
so the hide-and-restore behaviour cannot drift between vocabularies.

Takes any `vocabulary` with `remove_type`, `list_hidden` and `restore_hidden`
(`TypeVocabulary`, or the Pain Point adapter in `modules.context_strategy.service`).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.schemas.type_vocabulary import HiddenTypeOut, RestoreTypesOut, RestoreTypesRequest
from app.services.audit import log_event


class HideableVocabulary(Protocol):
    """What the endpoint bodies need from a vocabulary."""

    label: str

    def remove_type(self, db: Session, project_id: UUID, organization_id: UUID, type_ref_id: UUID) -> tuple[str, UUID]: ...
    def list_hidden(self, db: Session, project_id: UUID, organization_id: UUID) -> list: ...
    def restore_hidden(
        self, db: Session, project_id: UUID, organization_id: UUID, org_type_ids: set[UUID] | None = None,
    ) -> list: ...


def remove_project_type(
    db: Session, vocabulary: HideableVocabulary, project: Project, type_ref_id: UUID, actor: User, entity_type: str,
) -> None:
    """Deletes a project-local type or hides an organisation default, audits it and commits.

    Raises:
        HTTPException: 404 if the id is no type of this project; 409 if a local
            type is still in use.
    """
    try:
        action, entity_id = vocabulary.remove_type(db, project.id, project.organization_id, type_ref_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{vocabulary.label} not found.") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    log_event(db, entity_type=entity_type, entity_id=entity_id, action=action, actor_id=actor.id, project_id=project.id)
    db.commit()


def list_hidden_types(db: Session, vocabulary: HideableVocabulary, project: Project) -> list[HiddenTypeOut]:
    """The organisation defaults hidden in the project."""
    return [HiddenTypeOut.model_validate(t) for t in vocabulary.list_hidden(db, project.id, project.organization_id)]


def restore_hidden_types(
    db: Session, vocabulary: HideableVocabulary, project: Project, payload: RestoreTypesRequest, actor: User,
    entity_type: str,
) -> RestoreTypesOut:
    """Shows hidden organisation defaults again (all, or those in `payload`), audits each and commits."""
    wanted = None if payload.org_type_ids is None else set(payload.org_type_ids)
    restored = vocabulary.restore_hidden(db, project.id, project.organization_id, wanted)
    for org_type in restored:
        log_event(db, entity_type=entity_type, entity_id=org_type.id, action="restored", actor_id=actor.id,
                  project_id=project.id)
    db.commit()
    return RestoreTypesOut(restored=[HiddenTypeOut.model_validate(t) for t in restored])
