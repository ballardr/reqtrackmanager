"""
Module: routers.requirement_types

The requirement type list, for the organisation and for each project:
- `/orgs/{id}/requirement-types`: the organisation's list (list, create, reorder, rename / deactivate, delete).
- `/projects/{id}/requirement-types`: a project's effective list, its own additions and overrides, hiding an
  organisation entry and restoring it.

Authorisation: reading is open to every organisation member / project member (a picker needs it); changing needs the
organisation administrator, or project settings authority (`can_manage_project_settings`, as for tags and components).
The endpoints are the shared registrars in `services.vocabulary_endpoints`, so a hidden default, a rename and a delete
behave exactly as for every other typed list. A type's `rank` is its priority.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.project import Project
from app.models.user import User
from app.schemas.requirement_type import (
    RequirementTypeEffectiveOut,
    RequirementTypeOrgCreate,
    RequirementTypeOrgOut,
    RequirementTypeOrgUpdate,
    RequirementTypeProjectCreate,
    RequirementTypeProjectOut,
    RequirementTypeProjectOverride,
)
from app.services.rbac import can_manage_project_settings, is_org_admin, require_org_role, require_project_view
from app.services.requirement_types import REQUIREMENT_TYPES
from app.services.vocabulary_endpoints import VocabularySchemas, register_org_vocabulary, register_project_vocabulary

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["requirement-types"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["requirement-types"])


_SCHEMAS = VocabularySchemas(
    org_create=RequirementTypeOrgCreate, org_update=RequirementTypeOrgUpdate, org_out=RequirementTypeOrgOut,
    effective_out=RequirementTypeEffectiveOut, project_create=RequirementTypeProjectCreate,
    project_override=RequirementTypeProjectOverride, project_out=RequirementTypeProjectOut,
)


def _require_org_admin(db: Session, current_user: User, organization_id: UUID) -> None:
    """Gate for changing the organisation's requirement types.

    Raises:
        HTTPException: 403 unless the caller is an organisation administrator.
    """
    if not is_org_admin(db, current_user.id, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation administrator may change the requirement types.")


def _require_project_settings(db: Session, current_user: User, project: Project) -> None:
    """Gate for changing a project's requirement types.

    Raises:
        HTTPException: 403 unless the caller has project settings authority.
    """
    if not can_manage_project_settings(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")


register_org_vocabulary(
    org_router, path="/requirement-types", vocabulary=REQUIREMENT_TYPES, entity_type="requirement_type_definition",
    view_dependency=require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER),
    require_admin=_require_org_admin, schemas=_SCHEMAS,
)
register_project_vocabulary(
    project_router, path="/requirement-types", vocabulary=REQUIREMENT_TYPES, entity_type="requirement_type",
    view_dependency=require_project_view, require_manage=_require_project_settings, schemas=_SCHEMAS,
)
