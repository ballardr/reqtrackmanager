"""
Module: routers.orgs.files

The organisation's Files page: the files of every project the caller may open, in one filterable list.

Responsibilities:
- `POST /orgs/{id}/files/search`: the list with its filters (file name, source, file type, uploader, upload window,
  project, archived projects), paged, with `X-Total-Count` and `X-Projects-Truncated` headers.
- `GET /orgs/{id}/files/uploaders` and `GET /orgs/{id}/files/projects`: the choices of the "Uploaded by" and
  "Project" filters.

Design decisions:
- Never a blanket organisation read: the projects covered come from `services.project_files.organization_file_projects`
  (a genuine role and a reachable credential, the project Files page's own test), and a project id the caller sends that is outside that
  set is ignored. Any organisation member may open the page; what it lists depends only on their projects.
- The file name typed in the search travels in the POST body, is used only as a bound pattern and is never logged,
  audited or traced; the endpoints are reads and write no audit event.
- One pass over the projects' joins (`file_rows`), so the number of statements does not grow with the project count.

Dependencies: `services.project_files`, `services.rbac` (the organisation membership gate), `schemas.file`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.user import User
from app.schemas.file import (
    OrganizationFileProjectOut,
    OrganizationFileSearchIn,
    ProjectFileOut,
    ProjectFileUploaderOut,
)
from app.services.project_files import (
    FileFilters,
    organization_file_projects,
    organization_file_rows,
)
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-files"])

_MEMBER = require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)


@router.post("/{organization_id}/files/search", response_model=list[ProjectFileOut])
def search_organization_files(
    organization_id: UUID,
    body: OrganizationFileSearchIn,
    response: Response,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(_MEMBER),
    db: Session = Depends(get_db),
):
    """The files of the projects the caller may open, newest first, each row labelled with its project.

    Pagination and `X-Total-Count` follow the project Files page; `X-Projects-Truncated: true` says the cap on the
    number of projects covered cut the list short.
    """
    filters = FileFilters(
        search=body.search, sources=frozenset(body.sources), kind=body.kind, uploaded_by=body.uploaded_by,
        uploaded_from=body.uploaded_from, uploaded_before=body.uploaded_before,
    )
    projects, truncated = organization_file_projects(
        db, current_user.id, organization_id, include_archived=body.include_archived
    )
    rows = organization_file_rows(db, projects, filters, only=body.project_ids)
    response.headers["X-Total-Count"] = str(len(rows))
    response.headers["X-Projects-Truncated"] = "true" if truncated else "false"
    return rows[offset:offset + limit] if limit is not None else rows


@router.get("/{organization_id}/files/uploaders", response_model=list[ProjectFileUploaderOut])
def list_organization_file_uploaders(
    organization_id: UUID,
    include_archived: bool = Query(False),
    current_user: User = Depends(_MEMBER),
    db: Session = Depends(get_db),
):
    """The people who uploaded a file in a project the caller may open: the "Uploaded by" choices, each once."""
    projects, _truncated = organization_file_projects(db, current_user.id, organization_id, include_archived=include_archived)
    rows = organization_file_rows(db, projects)
    people = {row.file.uploaded_by: row.uploaded_by_display_name for row in rows}
    return sorted(
        (ProjectFileUploaderOut(id=uid, display_name=name) for uid, name in people.items()),
        key=lambda person: person.display_name.lower(),
    )


@router.get("/{organization_id}/files/projects", response_model=list[OrganizationFileProjectOut])
def list_organization_file_projects(
    organization_id: UUID,
    include_archived: bool = Query(False),
    current_user: User = Depends(_MEMBER),
    db: Session = Depends(get_db),
):
    """The projects whose files the caller may list: the "Project" filter's choices, sorted by name."""
    projects, _truncated = organization_file_projects(db, current_user.id, organization_id, include_archived=include_archived)
    return [
        OrganizationFileProjectOut(id=p.id, name=p.name, code=p.code, is_archived=p.is_archived) for p in projects
    ]
