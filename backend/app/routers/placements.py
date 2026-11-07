"""
Module: routers.placements

The placement API: `GET/PUT /projects/{project_id}/artefacts/{type}/{id}/placements`, where one record of any
registered artefact type sits in the project's component/category tree.

Authorisation: reading follows the record; changing needs the authority `services.placements.can_place` gives
(the authority to tag the type). A record the caller cannot open is a 404, never a 403, as for the Links panel.
A requirement keeps its own component and category (shown read-only here) and a record owned by the
organisation has no project tree, so neither can be changed through this API.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types, get_not_placeable_types
from app.schemas.placements import PagePlacementsOut, PlacementOut, RecordPlacementsOut, RecordPlacementsSet
from app.services import placements as placement_service
from app.services.link_authoring import DRAFT_ARTEFACT_ID
from app.services.link_graph import ArtefactResolver
from app.services.lookups import project_or_404
from app.services.placements import PlacementPair
from app.services.rbac import require_project_view
from app.services.tags import require_visible_record

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["placements"])


def _out(
    db: Session, resolver: ArtefactResolver, artefact_type: str, artefact_id: UUID, owner_project_id: UUID | None,
) -> RecordPlacementsOut:
    """The record's placements with names, and whether the caller may change them."""
    pairs = placement_service.pairs_for_records(db, artefact_type, [artefact_id]).get(artefact_id, [])
    names = _names(db, pairs)
    return RecordPlacementsOut(
        placements=[
            PlacementOut(
                component_id=p.component_id, category_id=p.category_id, component_name=names[p.component_id],
                category_name=names.get(p.category_id) if p.category_id else None,
            )
            for p in pairs
        ],
        can_edit=owner_project_id is not None and placement_service.can_place(resolver, artefact_type),
        managed_on_record=artefact_type in placement_service.COLUMN_PLACED_TYPES,
    )


def _names(db: Session, pairs: list[PlacementPair]) -> dict[UUID, str]:
    """`{component or category id: name}` for the pairs."""
    names: dict[UUID, str] = {}
    component_ids = {p.component_id for p in pairs}
    category_ids = {p.category_id for p in pairs if p.category_id is not None}
    if component_ids:
        for row_id, name in db.execute(
            select(ProjectComponent.id, ProjectComponent.name).where(ProjectComponent.id.in_(component_ids))
        ).tuples():
            names[row_id] = name
    if category_ids:
        for row_id, name in db.execute(
            select(ProjectCategory.id, ProjectCategory.name).where(ProjectCategory.id.in_(category_ids))
        ).tuples():
            names[row_id] = name
    return names


def _context(
    db: Session, project_id: UUID, user: User, artefact_type: str, artefact_id: UUID,
) -> tuple[Project, ArtefactResolver, UUID | None]:
    """The project, resolver and owning project id of a record the caller can open (else 404)."""
    project = project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, user.id)
    return project, resolver, require_visible_record(resolver, project, artefact_type, artefact_id)


#: Most records one page read may ask about (a list's page is far smaller).
MAX_PAGE_RECORDS = 500


@router.get("/placements/{artefact_type}", response_model=PagePlacementsOut)
def get_page_placements(
    project_id: UUID, artefact_type: str, id: list[UUID] = Query(default=[]),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> PagePlacementsOut:
    """The places of the listed records of one type, in a few statements, for a list's Components column.

    Records the caller cannot open from this project (or in another project) are left out, never reported as
    absent from the tree, so the answer discloses nothing a list would not already show."""
    project = project_or_404(db, project_id)
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    ids = list(dict.fromkeys(id))[:MAX_PAGE_RECORDS]
    if not ids or artefact_type in get_not_placeable_types():
        return PagePlacementsOut(placements={})
    resolver = ArtefactResolver(db, project, current_user.id)
    resolver.resolve({artefact_type: set(ids)})
    visible = [
        i for i in ids
        if (summary := resolver.visible((artefact_type, i))) is not None and summary.project_id == project.id
    ]
    pairs = placement_service.pairs_for_records(db, artefact_type, visible)
    all_pairs = [p for row in pairs.values() for p in row]
    names = _names(db, all_pairs)
    return PagePlacementsOut(
        placements={
            record_id: [
                PlacementOut(
                    component_id=p.component_id, category_id=p.category_id, component_name=names[p.component_id],
                    category_name=names.get(p.category_id) if p.category_id else None,
                )
                for p in row
            ]
            for record_id, row in pairs.items()
        }
    )


@router.get("/artefacts/{artefact_type}/{artefact_id}/placements", response_model=RecordPlacementsOut)
def get_record_placements(
    project_id: UUID, artefact_type: str, artefact_id: UUID, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> RecordPlacementsOut:
    """The record's placements and whether the caller may change them.

    `DRAFT_ARTEFACT_ID` stands for a record being created: no placements, but the same `can_edit` the create
    form's field needs (a write never accepts it)."""
    if artefact_id == DRAFT_ARTEFACT_ID:
        project = project_or_404(db, project_id)
        if artefact_type not in get_all_registered_artefact_types():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
        resolver = ArtefactResolver(db, project, current_user.id)
        return RecordPlacementsOut(
            placements=[], can_edit=placement_service.can_place(resolver, artefact_type),
            managed_on_record=artefact_type in placement_service.COLUMN_PLACED_TYPES,
        )
    _, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    return _out(db, resolver, artefact_type, artefact_id, owner)


@router.put("/artefacts/{artefact_type}/{artefact_id}/placements", response_model=RecordPlacementsOut)
def set_record_placements(
    project_id: UUID, artefact_type: str, artefact_id: UUID, body: RecordPlacementsSet,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordPlacementsOut:
    """Makes the record sit in exactly these places."""
    project, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    if artefact_type in placement_service.COLUMN_PLACED_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This record's component and category are set on the record itself."
        )
    if artefact_type in get_not_placeable_types():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, get_not_placeable_types()[artefact_type])
    if owner is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A record owned by the organisation is not placed in a project's components."
        )
    placement_service.require_place_authority(resolver, artefact_type)
    placement_service.set_record_placements(
        db, project=project, actor_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        pairs=[PlacementPair(p.component_id, p.category_id) for p in body.placements],
    )
    db.commit()
    return _out(db, resolver, artefact_type, artefact_id, owner)
