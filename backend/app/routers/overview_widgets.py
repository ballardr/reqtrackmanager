"""
Module: routers.overview_widgets

The project overview's widgets, for a project and for the organisation's default:
- `GET/PUT/DELETE /projects/{id}/overview-layout`
- `GET /projects/{id}/overview-catalogue`
- `POST /projects/{id}/overview-metrics`
- `GET/PUT/DELETE /orgs/{id}/overview-layout`, `GET /orgs/{id}/overview-catalogue`

Authorisation: any project member reads the layout and asks for figures (the figures apply the caller's own record
visibility and module gates); changing the layout and reading the editor's catalogue need project settings
authority; the organisation's default is read and changed by an organisation administrator. `POST` is used to
fetch figures because the request carries a list of references, not because it changes anything.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import memoize_module_state
from app.schemas.overview_widgets import (
    BreakdownRowOut,
    MetricOut,
    MetricResultOut,
    OverviewCatalogueOut,
    OverviewLayoutOut,
    OverviewLayoutSet,
    OverviewMetricsOut,
    OverviewMetricsRequest,
    RecordTypeOptionOut,
    WidgetTypeOut,
)
from app.services import overview_metrics, overview_widgets
from app.services.rbac import can_manage_project_settings, require_org_role, require_project_manage, require_project_view

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["overview-widgets"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["overview-widgets"])

_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, or a 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or a 404."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return organization


def _project_layout_out(db: Session, project: Project, user: User) -> OverviewLayoutOut:
    """The project's layout in force, with where it would come from without its own and whether `user` may change it."""
    resolved = overview_widgets.resolve_layout(db, project)
    inherited = overview_widgets.inherited_layout(db, project).source if resolved.source == "own" else None
    return OverviewLayoutOut.model_validate({
        **resolved.layout, "source": resolved.source, "inherited_source": inherited,
        "can_customise": can_manage_project_settings(db, user, project),
    })


def _org_layout_out(db: Session, organization: Organization) -> OverviewLayoutOut:
    """The organisation's default layout (the built-in one when it has none)."""
    if organization.overview_widgets is None:
        built_in = overview_widgets.default_layout(overview_widgets.widget_types_for_organization(db, organization.id))
        return OverviewLayoutOut.model_validate({**built_in, "source": "default"})
    return OverviewLayoutOut.model_validate({**overview_widgets.stored_layout(organization.overview_widgets), "source": "own"})


def _catalogue_out(
    widget_types: list[overview_widgets.WidgetTypeInfo], metrics: dict[str, tuple[str | None, Any]],
    record_types: list[overview_metrics.RecordTypeOption],
) -> OverviewCatalogueOut:
    """The editor's catalogue from its parts."""
    return OverviewCatalogueOut(
        widget_types=[
            WidgetTypeOut(key=t.key, label=t.label, description=t.description, module_key=t.module_key, width=t.width, height=t.height)
            for t in widget_types
        ],
        metrics=[
            MetricOut(
                key=key, label=m.label, unit=m.unit, scalar=m.scalar, breakdown=m.breakdown, params=sorted(m.params), module_key=module_key,
            )
            for key, (module_key, m) in metrics.items()
        ],
        record_types=[RecordTypeOptionOut(type=o.type, label=o.label, filter_params=o.filter_params) for o in record_types],
    )


@router.get("/overview-layout", response_model=OverviewLayoutOut)
def get_project_overview_layout(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """The widgets the project's overview shows, in order, and which layout applies."""
    return _project_layout_out(db, _project_or_404(db, project_id), current_user)


@router.put("/overview-layout", response_model=OverviewLayoutOut)
def set_project_overview_layout(
    body: OverviewLayoutSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """Replaces the project's own layout."""
    overview_widgets.set_project_layout(db, project, body.model_dump(), current_user.id)
    db.commit()
    return _project_layout_out(db, project, current_user)


@router.delete("/overview-layout", response_model=OverviewLayoutOut)
def restore_project_overview_layout(
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """Removes the project's own layout, so the ancestor's, the organisation's or the built-in layout applies."""
    overview_widgets.set_project_layout(db, project, None, current_user.id)
    db.commit()
    return _project_layout_out(db, project, current_user)


@router.get("/overview-catalogue", response_model=OverviewCatalogueOut)
def get_project_overview_catalogue(
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OverviewCatalogueOut:
    """The widget types, metrics and record types the project's editor offers (module state and the caller's rights applied)."""
    with memoize_module_state():
        return _catalogue_out(
            overview_widgets.widget_types_for_project(db, project), overview_metrics.metrics_for_project(db, project),
            overview_metrics.record_type_options(db, current_user, project),
        )


@router.post("/overview-metrics", response_model=OverviewMetricsOut)
def get_overview_metrics(
    project_id: UUID, body: OverviewMetricsRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> OverviewMetricsOut:
    """The figures the visible widgets need, evaluated once each for the caller, each in its own project scope.

    A figure the caller may not read is `unavailable`, never zero; one that is slow or fails does not blank the others.
    """
    project = _project_or_404(db, project_id)
    specs = []
    for item in body.metrics:
        metric_key, params = overview_metrics.validate_reference(item.metric, item.params)
        specs.append(overview_metrics.MetricSpec(id=item.id, metric=metric_key, params=params, scope=item.scope))
    with memoize_module_state():
        results = overview_metrics.evaluate_batch(db, current_user, project, specs)
    return OverviewMetricsOut(
        results={
            spec_id: MetricResultOut(
                state=r.state, unit=r.unit, label=r.label, projects=r.projects, value=r.value,
                breakdown=None if r.breakdown is None else [
                    BreakdownRowOut(key=k, label=label, value=v, detail=r.detail.get(k)) for k, label, v in r.breakdown
                ],
            )
            for spec_id, r in results.items()
        },
    )


@org_router.get("/overview-layout", response_model=OverviewLayoutOut)
def get_org_overview_layout(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """The organisation's default overview layout (the built-in one when it has set none)."""
    return _org_layout_out(db, _org_or_404(db, organization_id))


@org_router.put("/overview-layout", response_model=OverviewLayoutOut)
def set_org_overview_layout(
    organization_id: UUID, body: OverviewLayoutSet, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """Replaces the organisation's default overview layout."""
    organization = _org_or_404(db, organization_id)
    overview_widgets.set_organization_layout(db, organization, body.model_dump(), current_user.id)
    db.commit()
    return _org_layout_out(db, organization)


@org_router.delete("/overview-layout", response_model=OverviewLayoutOut)
def restore_org_overview_layout(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OverviewLayoutOut:
    """Removes the organisation's default layout, so projects without their own show the built-in layout."""
    organization = _org_or_404(db, organization_id)
    overview_widgets.set_organization_layout(db, organization, None, current_user.id)
    db.commit()
    return _org_layout_out(db, organization)


@org_router.get("/overview-catalogue", response_model=OverviewCatalogueOut)
def get_org_overview_catalogue(
    organization_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> OverviewCatalogueOut:
    """The widget types, metrics and record types an organisation default may use (modules the organisation has enabled)."""
    return _catalogue_out(
        overview_widgets.widget_types_for_organization(db, organization_id), overview_metrics.organization_metrics(db, organization_id),
        overview_metrics.organization_record_type_options(db, organization_id),
    )
