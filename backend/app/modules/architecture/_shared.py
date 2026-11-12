"""
Module: modules.architecture._shared

The gates behind the Architecture routers.

RBAC: any project member can read the vocabularies, elements and connections once
the matching sub-component is enabled. Creating and changing elements, ports and
connections needs the project `architect` role or a Fine-Grained Access Control
`(architecture_element, manage)` / `(architecture_connection, manage)` / `(architecture_diagram, manage)` grant;
changing a project's vocabulary or symbol library needs the project `architecture_admin` role and
changing the organisation's defaults the organisation `architecture_org_admin` role.
All compose with server admin, organisation admin and (for a project) project manager.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.project import Project
from app.models.user import User
from app.modules.architecture.service import (
    ARCHITECTURE_MODULE_KEY,
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
)
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role

ARCHITECTURE_ADMIN_ROLE = "architecture_admin"
ARCHITECTURE_ORG_ADMIN_ROLE = "architecture_org_admin"
ARCHITECT_ROLE = "architect"

#: The Fine-Grained Access Control atoms the `architect` role carries.
ELEMENT_MANAGE_PERMISSION = encode_permission(ELEMENT_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)
CONNECTION_MANAGE_PERMISSION = encode_permission(CONNECTION_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)
DIAGRAM_MANAGE_PERMISSION = encode_permission(DIAGRAM_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)


def require_architect(db: Session, current_user: User, project: Project, permission: str) -> None:
    """Gate for creating and changing elements, ports, connections and diagrams: the project `architect` role
    (composing with server admin, organisation admin and project manager) or the given Fine-Grained Access Control
    atom (`ELEMENT_MANAGE_PERMISSION`, `CONNECTION_MANAGE_PERMISSION` or `DIAGRAM_MANAGE_PERMISSION`).

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, ARCHITECTURE_MODULE_KEY, ARCHITECT_ROLE,
        organization_id=project.organization_id, project_id=project.id,
    ):
        return
    held = get_effective_permissions(db, current_user.id, organization_id=project.organization_id, project_id=project.id)
    if permission_satisfied(held, permission):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Architect (or admin/manager) may do this.")


def require_architecture_admin(db: Session, current_user: User, project: Project) -> None:
    """Gate for changing a project's vocabularies.

    Raises:
        HTTPException: 403 if the caller lacks `architecture_admin` (or an overriding admin role).
    """
    if not user_satisfies_module_role(
        db, current_user, ARCHITECTURE_MODULE_KEY, ARCHITECTURE_ADMIN_ROLE,
        organization_id=project.organization_id, project_id=project.id,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Architecture Admin (or admin/manager) may do this.")


def require_architecture_org_admin(db: Session, current_user: User, *, organization_id: uuid.UUID) -> None:
    """Gate for changing the organisation's default vocabularies.

    Raises:
        HTTPException: 403 if the caller lacks `architecture_org_admin` (or organisation admin).
    """
    if not user_satisfies_module_role(
        db, current_user, ARCHITECTURE_MODULE_KEY, ARCHITECTURE_ORG_ADMIN_ROLE,
        organization_id=organization_id, project_id=None,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Architecture Org Admin (or org admin) may do this.")


def get_project(db: Session, project_id: uuid.UUID) -> Project:
    """Loads the project in the URL.

    Raises:
        HTTPException: 404 if it does not exist.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project
