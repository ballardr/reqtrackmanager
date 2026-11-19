"""
Module: routers.external_systems

The outside systems (Jira, ServiceNow, ...) records can carry external references in, for the organisation and for
each project:
- `/orgs/{id}/external-systems`: the organisation's list (list, create, reorder, rename / deactivate, delete).
- `/projects/{id}/external-systems`: a project's effective list, its own additions and overrides, hiding an
  organisation entry and restoring it.

Authorisation: reading is open to every organisation member / project member (a picker needs it); changing needs the
organisation administrator, or project settings authority (`can_manage_project_settings`, as for tags and components).
The endpoints themselves are the shared registrars in `services.vocabulary_endpoints`, so a hidden default, a rename
and a delete behave exactly as for every other typed list. A new system link template is checked as http(s).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.project import Project
from app.models.user import User
from app.schemas.external_reference import (
    ExternalSystemEffectiveOut,
    ExternalSystemOrgCreate,
    ExternalSystemOrgOut,
    ExternalSystemOrgUpdate,
    ExternalSystemProjectCreate,
    ExternalSystemProjectOut,
    ExternalSystemProjectOverride,
)
from app.services.external_references import EXTERNAL_SYSTEMS
from app.services.rbac import can_manage_project_settings, is_org_admin, require_org_role, require_project_view
from app.services.vocabulary_endpoints import VocabularySchemas, register_org_vocabulary, register_project_vocabulary

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["external-systems"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["external-systems"])

_SCHEMAS = VocabularySchemas(
    org_create=ExternalSystemOrgCreate, org_update=ExternalSystemOrgUpdate, org_out=ExternalSystemOrgOut,
    effective_out=ExternalSystemEffectiveOut, project_create=ExternalSystemProjectCreate,
    project_override=ExternalSystemProjectOverride, project_out=ExternalSystemProjectOut,
)


def _require_org_admin(db: Session, current_user: User, organization_id: UUID) -> None:
    """Gate for changing the organisation's systems.

    Raises:
        HTTPException: 403 unless the caller is an organisation administrator.
    """
    if not is_org_admin(db, current_user.id, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation administrator may change the external systems.")


def _require_project_settings(db: Session, current_user: User, project: Project) -> None:
    """Gate for changing a project's systems.

    Raises:
        HTTPException: 403 unless the caller has project settings authority.
    """
    if not can_manage_project_settings(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")


register_org_vocabulary(
    org_router, path="/external-systems", vocabulary=EXTERNAL_SYSTEMS, entity_type="external_system_definition",
    view_dependency=require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER),
    require_admin=_require_org_admin, schemas=_SCHEMAS,
)
register_project_vocabulary(
    project_router, path="/external-systems", vocabulary=EXTERNAL_SYSTEMS, entity_type="external_system",
    view_dependency=require_project_view, require_manage=_require_project_settings, schemas=_SCHEMAS,
)
