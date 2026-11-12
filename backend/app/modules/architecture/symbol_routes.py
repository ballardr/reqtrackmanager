"""
Module: modules.architecture.symbol_routes

The symbol library's endpoints that the shared vocabulary builders (`vocabulary_routes`) do not provide: uploading a
symbol (multipart, so a file is checked and stored before its row is created) and reading its SVG.

Upload is organisation level for the organisation's library and project level for a project's own, each audited with
the symbol's name and size only. The SVG is served sanitised with a restrictive content-security policy, only to a
viewer `symbols.visible_symbol_ids` admits; any other symbol is answered 404, as if it did not exist.

This file deliberately has no postponed annotations: FastAPI resolves the annotations of the functions defined inside
the builders.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture.models import ArchitectureSymbol
from app.modules.architecture.schemas import SymbolOut
from app.modules.architecture.service import SYMBOLS
from app.modules.architecture.symbols import MAX_NAME, default_name, prepare_symbol_upload, symbol_svg, visible_symbol_ids
from app.modules.architecture.visibility import Viewer
from app.services import report_images
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.report_raster import ImageRejectedError

SYMBOL_ENTITY_TYPE = "architecture_symbol"

#: Sent with a symbol's SVG: it is only ever drawn as an image, and must never run anything if opened on its own. The
#: security-headers middleware keeps a policy a route sets, so this one also forbids framing.
_SVG_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=60",
}


async def _store(
    db: Session, user: User, *, project_id: UUID | None, organization_id: UUID, file: UploadFile, name: str | None,
) -> ArchitectureSymbol:
    """Checks an upload, stores its sanitised copy and creates the symbol row (flushed, not committed).

    Raises:
        HTTPException: 422 for a file that is not an acceptable SVG, 400 for a name the owner already lists, 403 or 413
            from the upload rules (uploads disabled, storage limit, size).
    """
    limit = report_images.max_image_bytes()
    data = await file.read(limit + 1)
    try:
        if len(data) > limit:
            raise ImageRejectedError(f"The file is too large (limit {limit // (1024 * 1024)} MB).")
        # An EPS or PDF is converted to SVG here, in a worker thread, so the conversion does not block the event loop.
        filename, svg = await run_in_threadpool(prepare_symbol_upload, file.filename or "symbol.svg", data, user.id)
    except ImageRejectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    wanted = (name or default_name(filename)).strip()[:MAX_NAME]
    try:
        SYMBOLS.check_new_name(db, project_id=project_id, organization_id=organization_id, name=wanted)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=user.id, filename=filename, content_type=report_images.SVG_TYPE, data=svg,
    )
    db.flush()
    try:
        return SYMBOLS.create(db, project_id=project_id, organization_id=organization_id, name=wanted, file_asset_id=asset.id)
    except ValueError as exc:
        delete_file(db, asset)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _svg_response(db: Session, symbol: ArchitectureSymbol) -> Response:
    """The symbol's sanitised SVG with the restrictive headers; 404 when its file is gone."""
    try:
        svg = symbol_svg(db, symbol)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.") from exc
    return Response(content=svg, media_type=report_images.SVG_TYPE, headers=_SVG_HEADERS)


def _readable(db: Session, viewer: Viewer, symbol_id: UUID) -> ArchitectureSymbol:
    """The symbol, if the viewer may read it.

    Raises:
        HTTPException: 404 for a missing symbol or one the viewer may not read (indistinguishable).
    """
    symbol = db.get(ArchitectureSymbol, symbol_id)
    if symbol is None or symbol_id not in visible_symbol_ids(db, viewer, [symbol_id]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.")
    return symbol


def add_org_symbol_routes(router: APIRouter, *, require_view) -> None:
    """Adds the organisation's symbol upload and the SVG read to `router` under `/symbols`."""

    @router.post("/symbols", response_model=SymbolOut, status_code=status.HTTP_201_CREATED)
    async def upload_org_symbol(
        organization_id: UUID, file: UploadFile = File(...), name: str | None = Form(default=None, max_length=MAX_NAME),
        current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Adds a symbol to the organisation's library from an SVG (or an EPS or PDF, when the converter is available).
        The stored copy is the sanitised one. 422 for a file that is not acceptable, 400 on a clashing name."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        row = await _store(db, current_user, project_id=None, organization_id=organization_id, file=file, name=name)
        log_event(db, entity_type=SYMBOL_ENTITY_TYPE, entity_id=row.id, action="created", actor_id=current_user.id,
                  organization_id=organization_id, detail={"name": row.name})
        db.commit()
        db.refresh(row)
        return row

    @router.get("/symbols/{symbol_id}/content")
    def org_symbol_content(
        organization_id: UUID, symbol_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The symbol's sanitised SVG."""
        return _svg_response(db, _readable(db, Viewer.of_organization(current_user, organization_id), symbol_id))


def add_project_symbol_routes(router: APIRouter, *, require_view) -> None:
    """Adds a project's symbol upload and the SVG read to `router` under `/symbols`."""

    @router.post("/symbols", response_model=SymbolOut, status_code=status.HTTP_201_CREATED)
    async def upload_project_symbol(
        project_id: UUID, file: UploadFile = File(...), name: str | None = Form(default=None, max_length=MAX_NAME),
        current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Adds a symbol to this project's own library (see the organisation upload for the checks)."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        SYMBOLS.materialize_inherited(db, project_id)
        row = await _store(
            db, current_user, project_id=project_id, organization_id=project.organization_id, file=file, name=name,
        )
        log_event(db, entity_type=SYMBOL_ENTITY_TYPE, entity_id=row.id, action="created", actor_id=current_user.id,
                  project_id=project_id, detail={"name": row.name})
        db.commit()
        db.refresh(row)
        return row

    @router.get("/symbols/{symbol_id}/content")
    def project_symbol_content(
        project_id: UUID, symbol_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The symbol's sanitised SVG: one the project's library offers, or one drawn on an element the project can read."""
        project = sh.get_project(db, project_id)
        return _svg_response(db, _readable(db, Viewer.of_user(current_user, project), symbol_id))
