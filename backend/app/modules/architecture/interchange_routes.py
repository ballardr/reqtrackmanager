"""
Module: modules.architecture.interchange_routes

The interchange endpoints, added to the module's project router by `add_interchange_routes`: the JSON file (download,
import preview, import) and the Structurizr DSL export.

RBAC: reading needs project membership and the Elements sub-component (what a caller may not read is not written, see
`interchange`). The import and its preview change data and create type rows, so they need the Architect role for
elements, connections and diagrams and the Architecture Admin role. An import is one audit event with counts, never
names or cell values.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture import interchange, structurizr
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY
from app.modules.architecture.visibility import Viewer
from app.services.audit import log_event
from app.services.lookups import project_or_404
from app.services.rbac import require_project_subcomponent_enabled

_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
AUDIT_ENTITY = "architecture_interchange"


class ImportReportOut(BaseModel):
    """What an import did, or would do (a preview)."""

    created: dict[str, int]
    warnings: list[str]


def _require_importer(db: Session, user: User, project_id: uuid.UUID):
    """The project, after checking the caller may import (Architect for every record type, and Architecture Admin)."""
    project = project_or_404(db, project_id)
    for permission in (sh.ELEMENT_MANAGE_PERMISSION, sh.CONNECTION_MANAGE_PERMISSION, sh.DIAGRAM_MANAGE_PERMISSION):
        sh.require_architect(db, user, project, permission)
    sh.require_architecture_admin(db, user, project)
    return project


async def _read_body(request: Request) -> bytes:
    """The request body, refused as too large before it is read when its declared length is over the limit."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > interchange.MAX_BYTES:
        raise HTTPException(413, f"The file is larger than {interchange.MAX_BYTES // (1024 * 1024)} MB.")
    return await request.body()


def add_interchange_routes(router: APIRouter) -> None:
    """Adds the interchange routes to `router` (the project router)."""
    view = require_project_subcomponent_enabled(ARCHITECTURE_MODULE_KEY, ELEMENT_SUBCOMPONENT_KEY)

    @router.get("/interchange/json")
    def download_json(project_id: uuid.UUID, current_user: User = Depends(view), db: Session = Depends(get_db)):
        """The project's architecture as a versioned JSON file."""
        project = project_or_404(db, project_id)
        document = interchange.export_document(db, project, current_user)
        return Response(
            content=json.dumps(document, indent=2, ensure_ascii=False), media_type="application/json",
            headers={**_HEADERS, "Content-Disposition": f'attachment; filename="{project.code.lower()}-architecture.json"'},
        )

    def run(db: Session, user: User, project_id: uuid.UUID, raw: bytes, *, apply: bool) -> ImportReportOut:
        project = _require_importer(db, user, project_id)
        try:
            document = interchange.parse_document(raw)
            found = (interchange.apply_import if apply else interchange.preview_import)(db, project, document, user)
        except interchange.InterchangeError as exc:
            db.rollback()
            raise HTTPException(exc.status_code, str(exc)) from exc
        if apply:
            log_event(
                db, entity_type=AUDIT_ENTITY, entity_id=project.id, action="import", actor_id=user.id,
                organization_id=project.organization_id, project_id=project.id,
                detail={"created": found.created, "warnings": len(found.warnings)},
            )
            db.commit()
        else:
            db.rollback()
        return ImportReportOut(created=found.created, warnings=found.warnings)

    @router.post("/interchange/json/preview", response_model=ImportReportOut)
    async def preview_json(
        project_id: uuid.UUID, request: Request, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """What importing the file (the request body) would create, and what it could not resolve; nothing is stored."""
        raw = await _read_body(request)
        return await run_in_threadpool(run, db, current_user, project_id, raw, apply=False)

    @router.post("/interchange/json", response_model=ImportReportOut)
    async def import_json(
        project_id: uuid.UUID, request: Request, current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """Imports the file (the request body) into the project, numbering its records afresh."""
        raw = await _read_body(request)
        return await run_in_threadpool(run, db, current_user, project_id, raw, apply=True)

    @router.get("/interchange/structurizr")
    def download_structurizr(
        project_id: uuid.UUID, diagram_id: uuid.UUID | None = None, toggle_on: list[uuid.UUID] = Query(default=[]),
        toggle_off: list[uuid.UUID] = Query(default=[]), current_user: User = Depends(view), db: Session = Depends(get_db),
    ):
        """The project as a Structurizr DSL workspace (export only). `diagram_id` limits the views to one diagram;
        `toggle_on` / `toggle_off` override the saved state of a toggle, as for the diagram's own exports."""
        project = project_or_404(db, project_id)
        text = structurizr.render_workspace(
            db, project, Viewer.of_user(current_user, project), diagram_id=diagram_id,
            toggle_on=frozenset(toggle_on), toggle_off=frozenset(toggle_off),
        )
        return Response(
            content=text, media_type="text/plain; charset=utf-8",
            headers={**_HEADERS, "Content-Disposition": f'attachment; filename="{project.code.lower()}-architecture.dsl"'},
        )
