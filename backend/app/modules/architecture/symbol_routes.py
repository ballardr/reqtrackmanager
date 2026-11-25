"""
Module: modules.architecture.symbol_routes

The symbol library's endpoints that the shared vocabulary builders (`vocabulary_routes`) do not provide: uploading a
symbol (multipart, so a file is checked and stored before its row is created, into a folder when one is named), the
library page's filtered and paged listing (`symbol_library`), where one symbol is used, and reading its SVG.

Upload is organisation level for the organisation's library and project level for a project's own, each audited with
the symbol's name and size only. The listing and the usage answer are open to whoever may read the library (as the
picker's list is) and name only the projects the reader may open. The SVG is served sanitised with a restrictive content-security policy, only to a
viewer `symbols.visible_symbol_ids` admits; any other symbol is answered 404, as if it did not exist.

This file deliberately has no postponed annotations: FastAPI resolves the annotations of the functions defined inside
the builders.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.architecture import _shared as sh
from app.modules.architecture import folders as folder_rules
from app.modules.architecture.models import ArchitectureSymbol
from app.modules.architecture.records import ElementOwner, RuleError
from app.modules.architecture.schemas import SymbolLibraryPageOut, SymbolOut, SymbolUsageOut
from app.modules.architecture.service import SYMBOLS
from app.modules.architecture.symbol_library import FILE_TYPES, SORT_KEYS, LibraryQuery, LibraryScope, library_page, usage_for
from app.modules.architecture.symbols import MAX_NAME, default_name, prepare_symbol_upload, symbol_svg, visible_symbol_ids
from app.modules.architecture.visibility import Viewer
from app.services import report_images
from app.services.audit import log_event
from app.services.files import delete_file, upload_file
from app.services.report_raster import ImageRejectedError

SYMBOL_ENTITY_TYPE = "architecture_symbol"

#: Sent with a symbol's SVG: it is only ever drawn as an image, and must never run anything if opened on its own. The
#: security-headers middleware keeps a policy a route sets, so this one also forbids framing.
SVG_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=60",
}


async def _store(
    db: Session, user: User, *, project_id: UUID | None, organization_id: UUID, file: UploadFile, name: str | None,
    owner: ElementOwner, folder_id: UUID | None = None,
) -> ArchitectureSymbol:
    """Checks an upload, stores its sanitised copy and creates the symbol row (flushed, not committed).

    Args:
        db: The session.
        user: The uploader.
        project_id: The owning project, or `None` for the organisation's library.
        organization_id: The organisation.
        file: The uploaded file.
        name: The symbol's name, or `None` for the file's name without its extension.
        owner: The owner whose folder tree `folder_id` is checked against.
        folder_id: The folder of the owner's symbol tree to file it in, or `None` for the top level.

    Raises:
        HTTPException: 422 for a file that is not an acceptable SVG, 400 for a name the owner already lists or a folder
            that is not the owner's, 403 or 413 from the upload rules (uploads disabled, storage limit, size).
    """
    if folder_id is not None:
        try:
            folder_rules.usable_folder(db, owner, "symbol", folder_id)
        except RuleError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
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
        return SYMBOLS.create(
            db, project_id=project_id, organization_id=organization_id, name=wanted, file_asset_id=asset.id, folder_id=folder_id,
        )
    except ValueError as exc:
        delete_file(db, asset)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _svg_response(db: Session, symbol: ArchitectureSymbol) -> Response:
    """The symbol's sanitised SVG with the restrictive headers; 404 when its file is gone."""
    try:
        svg = symbol_svg(db, symbol)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.") from exc
    return Response(content=svg, media_type=report_images.SVG_TYPE, headers=SVG_HEADERS)


def _readable(db: Session, viewer: Viewer, symbol_id: UUID) -> ArchitectureSymbol:
    """The symbol, if the viewer may read it.

    Raises:
        HTTPException: 404 for a missing symbol or one the viewer may not read (indistinguishable).
    """
    symbol = db.get(ArchitectureSymbol, symbol_id)
    if symbol is None or symbol_id not in visible_symbol_ids(db, viewer, [symbol_id]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.")
    return symbol


def _library_query(
    search: str | None, source: str | None, file_type: str | None, used: str | None, folder: str | None,
    folder_scope: str | None, subfolders: bool, sort: str | None, order: str, offset: int, limit: int,
) -> LibraryQuery:
    """The listing's query, after checking each choice is one the page offers.

    Raises:
        HTTPException: 422 for a choice outside the allowed ones.
    """
    for value, allowed, label in (
        (source, ("builtin", "uploaded"), "source"), (file_type, FILE_TYPES, "file_type"), (used, ("used", "unused"), "used"),
        (folder_scope, ("own", "organization"), "folder_scope"), (sort, SORT_KEYS, "sort"), (order, ("asc", "desc"), "order"),
    ):
        if value is not None and value not in allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {label}: choose one of {', '.join(allowed)}.")
    return LibraryQuery(
        search=search, source=source, file_type=file_type, used=used, folder=folder, folder_scope=folder_scope,
        subfolders=subfolders, sort=sort, descending=order == "desc", offset=offset, limit=limit,
    )


def add_org_symbol_routes(router: APIRouter, *, require_view) -> None:
    """Adds the organisation's symbol upload and the SVG read to `router` under `/symbols`."""

    @router.post("/symbols", response_model=SymbolOut, status_code=status.HTTP_201_CREATED)
    async def upload_org_symbol(
        organization_id: UUID, file: UploadFile = File(...), name: str | None = Form(default=None, max_length=MAX_NAME),
        folder_id: UUID | None = Form(default=None), current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Adds a symbol to the organisation's library from an SVG (or an EPS or PDF, when the converter is available),
        into the organisation's symbol folder `folder_id` when given. The stored copy is the sanitised one. 422 for a
        file that is not acceptable, 400 on a clashing name or a folder that is not the organisation's."""
        sh.require_architecture_org_admin(db, current_user, organization_id=organization_id)
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
        row = await _store(
            db, current_user, project_id=None, organization_id=organization_id, file=file, name=name,
            owner=ElementOwner.of_organization(organization), folder_id=folder_id,
        )
        log_event(db, entity_type=SYMBOL_ENTITY_TYPE, entity_id=row.id, action="created", actor_id=current_user.id,
                  organization_id=organization_id, detail={"name": row.name, "in_folder": folder_id is not None})
        db.commit()
        db.refresh(row)
        return row

    @router.get("/symbols/library", response_model=SymbolLibraryPageOut)
    def org_symbol_library(
        organization_id: UUID, search: str | None = Query(default=None, max_length=200), source: str | None = None,
        file_type: str | None = None, used: str | None = None, folder: str | None = Query(default=None, max_length=1000),
        subfolders: bool = True, sort: str | None = None, order: str = "asc", offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500), current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The organisation's symbol library after the filters, the sort and the page, with each symbol's folder, file
        type and where it is used (the projects the reader may open, by name)."""
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
        query = _library_query(search, source, file_type, used, folder, None, subfolders, sort, order, offset, limit)
        return library_page(db, LibraryScope(organization), current_user, query)

    @router.get("/symbols/{symbol_id}/usage", response_model=SymbolUsageOut)
    def org_symbol_usage(
        organization_id: UUID, symbol_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Where the symbol is used: each owner with how many element types and elements use it. 404 for a symbol the
        library does not offer."""
        organization = db.get(Organization, organization_id)
        found = usage_for(db, LibraryScope(organization), current_user, symbol_id) if organization is not None else None
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.")
        return found

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
        folder_id: UUID | None = Form(default=None), current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Adds a symbol to this project's own library, into the project's symbol folder `folder_id` when given (see the
        organisation upload for the checks)."""
        project = sh.get_project(db, project_id)
        sh.require_architecture_admin(db, current_user, project)
        SYMBOLS.materialize_inherited(db, project_id)
        row = await _store(
            db, current_user, project_id=project_id, organization_id=project.organization_id, file=file, name=name,
            owner=ElementOwner.of_project(project), folder_id=folder_id,
        )
        log_event(db, entity_type=SYMBOL_ENTITY_TYPE, entity_id=row.id, action="created", actor_id=current_user.id,
                  project_id=project_id, detail={"name": row.name, "in_folder": folder_id is not None})
        db.commit()
        db.refresh(row)
        return row

    @router.get("/symbols/library", response_model=SymbolLibraryPageOut)
    def project_symbol_library(
        project_id: UUID, search: str | None = Query(default=None, max_length=200), source: str | None = None,
        file_type: str | None = None, used: str | None = None, folder: str | None = Query(default=None, max_length=1000),
        folder_scope: str | None = None, subfolders: bool = True, sort: str | None = None, order: str = "asc",
        offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
        current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The project's effective symbol library (the organisation's symbols it has not hidden, then its own) after the
        filters, the sort and the page. `folder_scope=organization` makes `folder` name an organisation folder."""
        project = sh.get_project(db, project_id)
        organization = db.get(Organization, project.organization_id)
        if organization is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
        query = _library_query(search, source, file_type, used, folder, folder_scope, subfolders, sort, order, offset, limit)
        return library_page(db, LibraryScope(organization, project), current_user, query)

    @router.get("/symbols/{symbol_id}/usage", response_model=SymbolUsageOut)
    def project_symbol_usage(
        project_id: UUID, symbol_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """Where the symbol is used in this project: its element types by name and how many elements. 404 for a symbol the
        project's library does not offer."""
        project = sh.get_project(db, project_id)
        organization = db.get(Organization, project.organization_id)
        found = usage_for(db, LibraryScope(organization, project), current_user, symbol_id) if organization is not None else None
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not found.")
        return found

    @router.get("/symbols/{symbol_id}/content")
    def project_symbol_content(
        project_id: UUID, symbol_id: UUID, current_user: User = Depends(require_view), db: Session = Depends(get_db),
    ):
        """The symbol's sanitised SVG: one the project's library offers, or one drawn on an element the project can read."""
        project = sh.get_project(db, project_id)
        return _svg_response(db, _readable(db, Viewer.of_user(current_user, project), symbol_id))
