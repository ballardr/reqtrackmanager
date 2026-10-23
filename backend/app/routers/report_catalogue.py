"""
Module: routers.report_catalogue

Lists the reports a caller can run (the platform's record list and the module-contributed ones), so the Reports UI
decides what to show without probing for 403/404. The
list is computed by `services.report_framework` from the registry's
`ReportDefinition`s: module enabled, declared sub-component enabled, and (for
organisation-wide reports) the declaring module's org role held. It is the
single source of "which reports exist"; no frontend list is kept.

Access: any project member for the project catalogue (403 otherwise, as for
the requirement report page); any organisation member for the organisation
catalogue, which then contains only the reports whose role the caller holds.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.project import Project
from app.models.user import User
from app.services.rbac import require_org_role, require_project_view
from app.services.record_list_report import catalogue_entry as record_list_catalogue_entry
from app.services.report_framework import ReportCatalogueEntryOut, organization_catalogue, project_catalogue

router = APIRouter(prefix="/api/v1", tags=["reports"])


@router.get("/projects/{project_id}/report-catalogue", response_model=list[ReportCatalogueEntryOut])
def get_project_report_catalogue(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> list[ReportCatalogueEntryOut]:
    """Reports runnable on this project, with their parameters and formats: the platform's
    record list (when the caller can list any record type), then each module report whose
    module and sub-component are enabled."""
    project = db.get(Project, project_id)
    record_list = record_list_catalogue_entry(db, current_user, project)
    return [*([record_list] if record_list else []), *project_catalogue(db, project)]


@router.get("/orgs/{organization_id}/report-catalogue", response_model=list[ReportCatalogueEntryOut])
def get_org_report_catalogue(
    organization_id: UUID, current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> list[ReportCatalogueEntryOut]:
    """Organisation-wide module reports the caller can run (module and
    sub-component enabled, required module role held)."""
    return organization_catalogue(db, current_user, organization_id)
