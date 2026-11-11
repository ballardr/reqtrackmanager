"""
Module: routers.org_dashboards

The organisation overview's dashboard pages:
- `GET/POST /orgs/{id}/dashboards`, `PUT /orgs/{id}/dashboards/order`
- `GET/PUT/DELETE /orgs/{id}/dashboards/{dashboard_id}`, `PUT/DELETE /orgs/{id}/dashboards/{dashboard_id}/layout`
- `POST /orgs/{id}/dashboards/{dashboard_id}/metrics`, `GET /orgs/{id}/dashboard-catalogue`

Authorisation: any member of the organisation lists the pages they may see and reads a page or its figures; creating,
renaming, restricting, laying out, ordering and deleting need the organisation administrator role, and so does reading the
editor's catalogue. A page the caller may not see is a 404 on every route, the metrics request included.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.org_dashboard import (
    DashboardCopy,
    DashboardCreate,
    DashboardLayoutOut,
    DashboardOrder,
    DashboardOut,
    DashboardUpdate,
)
from app.schemas.overview_widgets import (
    BreakdownRowOut,
    MetricOut,
    MetricResultOut,
    OverviewCatalogueOut,
    OverviewLayoutSet,
    OverviewMetricsOut,
    OverviewMetricsRequest,
    RecordTypeOptionOut,
    WidgetTypeOut,
)
from app.services import org_dashboard_metrics, org_dashboards
from app.services.org_dashboards import DashboardView
from app.services.overview_metrics import MetricSpec
from app.services.principals import principal_out
from app.services.rbac import require_org_role

router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["org-dashboards"])

_member = require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)
_admin = require_org_role(OrgRole.ORG_ADMIN)


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or a 404."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return organization


def _out(db: Session, user: User, organization_id: UUID, page: DashboardView) -> DashboardOut:
    """A page for the response; the viewer list is shown to a manager only (it names who else may see the page)."""
    manager = org_dashboards.is_manager(db, user, organization_id)
    return DashboardOut(
        id=page.id, name=page.name, is_default=page.is_default, restricted=bool(page.viewers),
        viewers=[p for v in page.viewers if (p := principal_out(db, v.type.value, v.id)) is not None] if manager else [],
        can_manage=manager,
    )


def _layout_out(db: Session, user: User, organization_id: UUID, page: DashboardView) -> DashboardLayoutOut:
    """A page with its layout in force."""
    layout = org_dashboards.layout_of(db, organization_id, page)
    built_in = page.row is None or not page.row.layout
    return DashboardLayoutOut.model_validate({
        "dashboard": _out(db, user, organization_id, page), "scope": layout["scope"], "widgets": layout["widgets"], "built_in": built_in,
    })


def _reload(db: Session, user: User, organization_id: UUID, dashboard_id: str) -> DashboardLayoutOut:
    """The page after a change."""
    return _layout_out(db, user, organization_id, org_dashboards.get_page(db, user, organization_id, dashboard_id))


@router.get("/dashboards", response_model=list[DashboardOut])
def list_dashboards(
    organization_id: UUID, current_user: User = Depends(_member), db: Session = Depends(get_db),
) -> list[DashboardOut]:
    """The dashboard pages the caller may see, in order (the built-in Overview first)."""
    return [_out(db, current_user, organization_id, page) for page in org_dashboards.visible_pages(db, current_user, organization_id)]


@router.post("/dashboards", response_model=DashboardLayoutOut, status_code=status.HTTP_201_CREATED)
def create_dashboard(
    organization_id: UUID, body: DashboardCreate, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """Adds an empty dashboard page."""
    row = org_dashboards.create_page(db, organization_id, body.name, body.viewers, current_user.id)
    db.commit()
    return _reload(db, current_user, organization_id, str(row.id))


@router.post("/dashboards/{dashboard_id}/copy", response_model=DashboardLayoutOut, status_code=status.HTTP_201_CREATED)
def copy_dashboard(
    organization_id: UUID, dashboard_id: str, body: DashboardCopy, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """Adds a page that starts as a copy of this one (its layout and its viewers)."""
    row = org_dashboards.copy_page(db, organization_id, dashboard_id, body.name, current_user.id)
    db.commit()
    return _reload(db, current_user, organization_id, str(row.id))


@router.put("/dashboards/order", status_code=status.HTTP_204_NO_CONTENT)
def reorder_dashboards(
    organization_id: UUID, body: DashboardOrder, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> Response:
    """Orders the pages after the built-in one."""
    org_dashboards.reorder_pages(db, organization_id, body.ids, current_user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dashboards/{dashboard_id}", response_model=DashboardLayoutOut)
def get_dashboard(
    organization_id: UUID, dashboard_id: str, current_user: User = Depends(_member), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """A page and its layout; 404 when the caller may not see it."""
    return _reload(db, current_user, organization_id, dashboard_id)


@router.put("/dashboards/{dashboard_id}", response_model=DashboardLayoutOut)
def update_dashboard(
    organization_id: UUID, dashboard_id: str, body: DashboardUpdate, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """Renames a page and/or replaces who it is limited to."""
    org_dashboards.update_page(db, organization_id, dashboard_id, body.name, body.viewers, current_user.id)
    db.commit()
    return _reload(db, current_user, organization_id, dashboard_id)


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard(
    organization_id: UUID, dashboard_id: str, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> Response:
    """Deletes a page (not the built-in one)."""
    org_dashboards.delete_page(db, organization_id, dashboard_id, current_user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/dashboards/{dashboard_id}/layout", response_model=DashboardLayoutOut)
def set_dashboard_layout(
    organization_id: UUID, dashboard_id: str, body: OverviewLayoutSet, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """Replaces a page's layout."""
    org_dashboards.set_layout(db, organization_id, dashboard_id, body.model_dump(), current_user.id)
    db.commit()
    return _reload(db, current_user, organization_id, dashboard_id)


@router.delete("/dashboards/{dashboard_id}/layout", response_model=DashboardLayoutOut)
def restore_dashboard_layout(
    organization_id: UUID, dashboard_id: str, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> DashboardLayoutOut:
    """Restores a page's layout: the built-in one for the Overview page, an empty one for any other."""
    org_dashboards.set_layout(db, organization_id, dashboard_id, None, current_user.id)
    db.commit()
    return _reload(db, current_user, organization_id, dashboard_id)


@router.post("/dashboards/{dashboard_id}/metrics", response_model=OverviewMetricsOut)
def get_dashboard_metrics(
    organization_id: UUID, dashboard_id: str, body: OverviewMetricsRequest,
    current_user: User = Depends(_member), db: Session = Depends(get_db),
) -> OverviewMetricsOut:
    """The figures the page's visible widgets need, for the caller. A page the caller may not see is a 404, so its figures
    cannot be requested by id; a figure the caller may not read is `unavailable`, never zero."""
    org_dashboards.get_page(db, current_user, organization_id, dashboard_id)
    organization = _org_or_404(db, organization_id)
    specs = []
    for item in body.metrics:
        metric_key, params = org_dashboard_metrics.validate_reference(db, organization_id, item.metric, item.params)
        specs.append(MetricSpec(id=item.id, metric=metric_key, params=params))
    results = org_dashboard_metrics.evaluate_batch(db, current_user, organization, specs)
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


@router.get("/dashboard-catalogue", response_model=OverviewCatalogueOut)
def get_dashboard_catalogue(
    organization_id: UUID, current_user: User = Depends(_admin), db: Session = Depends(get_db),
) -> OverviewCatalogueOut:
    """The widget types, metrics and record types the dashboard editor offers (modules the organisation has enabled)."""
    metrics = org_dashboard_metrics.catalogue_for(db, organization_id)
    return OverviewCatalogueOut(
        widget_types=[
            WidgetTypeOut(key=t.key, label=t.label, description=t.description, module_key=t.module_key, width=t.width, height=t.height)
            for t in org_dashboards.widget_types(db, organization_id)
        ],
        metrics=[
            MetricOut(
                key=key, label=m.label, unit=m.unit, scalar=m.scalar, breakdown=m.breakdown, params=sorted(m.params),
                module_key=module_key,
            )
            for key, (module_key, m) in metrics.items()
        ],
        record_types=[
            RecordTypeOptionOut(type=t, label=label, filter_params=filter_params)
            for t, label, filter_params in org_dashboard_metrics.record_type_options(db, organization_id)
        ],
    )
