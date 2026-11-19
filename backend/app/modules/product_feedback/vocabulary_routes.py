"""
Module: modules.product_feedback.vocabulary_routes

Registers the endpoints of the module's classified list (`vocabularies.py`: request channels) on the organisation and
project routers through the shared registrars in `services.vocabulary_endpoints`, with the module's own gates:

- Organisation tier: changes need the `feedback_list_admin` module role (composing with organisation admin); reading
  needs only the module.
- Project tier: changes need the tier's triager gate (`_shared.require_request_manage`).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.service import PRODUCT_FEEDBACK_MODULE_KEY, RecordOwner
from app.services import vocabulary_endpoints
from app.services.rbac import user_satisfies_module_role
from app.services.type_vocabulary import TypeVocabulary

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


def _require_project_triager(db: Session, current_user: User, project: Project) -> None:
    """Gate for changing a project's lists (the triager gate)."""
    sh.require_request_manage(db, current_user, RecordOwner.of_project(project))


def register_org_vocabulary(
    router: APIRouter, *, path: str, vocabulary: TypeVocabulary, entity_type: str, view_dependency,
) -> None:
    """Adds the organisation-tier endpoints of `vocabulary` under `path` to `router`, gated by the list admin role."""
    vocabulary_endpoints.register_org_vocabulary(
        router, path=path, vocabulary=vocabulary, entity_type=entity_type, view_dependency=view_dependency,
        require_admin=_require_list_admin,
    )


def register_project_vocabulary(
    router: APIRouter, *, path: str, vocabulary: TypeVocabulary, entity_type: str, view_dependency,
) -> None:
    """Adds the project-tier endpoints of `vocabulary` under `path` to `router`, gated by the triager role."""
    vocabulary_endpoints.register_project_vocabulary(
        router, path=path, vocabulary=vocabulary, entity_type=entity_type, view_dependency=view_dependency,
        require_manage=_require_project_triager,
    )
