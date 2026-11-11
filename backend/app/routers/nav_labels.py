"""
Module: routers.nav_labels

Navigation names, for a project and for the organisation's defaults:
- `GET/PUT /projects/{id}/nav-labels`
- `GET/PUT /orgs/{id}/nav-labels`

Authorisation: any project member reads the project's names (the navigation needs them on every page);
changing them needs project settings authority; the organisation's defaults are read and changed by an
organisation administrator. The catalogue lists only what the project or organisation can currently reach.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.nav_labels import NavLabelItemOut, NavLabelsOut, NavLabelsSet
from app.services import nav_labels
from app.services.rbac import require_org_role, require_project_manage, require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}/nav-labels", tags=["nav-labels"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/nav-labels", tags=["nav-labels"])

_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _project_out(db: Session, project: Project) -> NavLabelsOut:
    """The project's catalogue with own, inherited and effective names, resolved in a fixed number of queries."""
    inherited = nav_labels.inherited_names(db, project)
    own = project.nav_label_overrides or {}
    items: list[NavLabelItemOut] = []
    for item in nav_labels.catalogue_for_project(db, project):
        parent = inherited.get(item.key)
        own_name = own.get(item.key)
        items.append(NavLabelItemOut(
            key=item.key, label=item.label, path=item.path.replace("{project_id}", str(project.id)), module_key=item.module_key,
            own=own_name, inherited=parent.value if parent else None, inherited_from=parent.source if parent else None,
            effective=own_name or (parent.value if parent else None),
        ))
    return NavLabelsOut(items=items)


def _org_out(db: Session, organization: Organization) -> NavLabelsOut:
    """The organisation's catalogue with its default names."""
    names = organization.nav_label_overrides or {}
    return NavLabelsOut(items=[
        NavLabelItemOut(key=item.key, label=item.label, module_key=item.module_key, own=names.get(item.key), effective=names.get(item.key))
        for item in nav_labels.catalogue_for_organization(db, organization.id)
    ])


@router.get("", response_model=NavLabelsOut)
def get_project_nav_labels(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> NavLabelsOut:
    """The navigation entries of the project with the names that apply to them."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _project_out(db, project)


@router.put("", response_model=NavLabelsOut)
def set_project_nav_labels(
    body: NavLabelsSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> NavLabelsOut:
    """Replaces the project's own navigation names; an entry left out follows the ancestor or organisation name."""
    nav_labels.set_project_names(db, project, body.names, current_user.id)
    db.commit()
    return _project_out(db, project)


@org_router.get("", response_model=NavLabelsOut)
def get_org_nav_labels(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> NavLabelsOut:
    """The entries the organisation can name, with its default names."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return _org_out(db, org)


@org_router.put("", response_model=NavLabelsOut)
def set_org_nav_labels(
    organization_id: UUID, body: NavLabelsSet, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> NavLabelsOut:
    """Replaces the organisation's default navigation names."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    nav_labels.set_organization_names(db, org, body.names, current_user.id)
    db.commit()
    return _org_out(db, org)
