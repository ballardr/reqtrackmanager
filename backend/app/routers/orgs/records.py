"""
Module: routers.orgs.records

Looks a record up by its qualified code (`ACME-REQ-001`) across an organisation's projects.

Responsibilities:
- One read endpoint that turns a qualified code into the record's type, id and project, so a
  code pasted into a conversation or report can be followed.

Design decisions:
- A record the caller cannot see (not in the project, no `view` permission, module off) is
  indistinguishable from one that does not exist: both are a 404.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.user import User
from app.schemas.org import CodedRecordOut
from app.services.codes import find_record_by_qualified_code
from app.services.rbac import check_pat_scope, require_org_role

router = APIRouter(tags=["organizations-records"])


@router.get("/{organization_id}/records/by-code/{qualified_code}", response_model=CodedRecordOut)
def get_record_by_code(
    organization_id: UUID, qualified_code: str, request: Request,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Finds the record a qualified code (`ACME-REQ-001`) names.

    Raises:
        HTTPException: 404 if the code is malformed or names no record the caller can see.
    """
    check_pat_scope(request, organization_id)
    found = find_record_by_qualified_code(db, current_user.id, organization_id, qualified_code)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No visible record has that code.")
    return CodedRecordOut(
        artefact_type=found.artefact_type, id=found.id, project_id=found.project_id,
        qualified_code=found.qualified_code, label=found.label,
    )
