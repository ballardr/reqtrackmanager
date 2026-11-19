"""
Module: routers.external_references

The external references on one record of any registered artefact type:
`GET/POST/PATCH/DELETE /projects/{id}/artefacts/{type}/{id}/external-references`.

Authorisation: reading follows the record (one the caller cannot open is a 404, never a 403, as for tags and the
Links panel); adding, changing and removing need the authority for tagging (`services.tags.can_tag`), because a
reference is metadata rather than record content. An organisation-owned record seen from a project uses the
organisation's systems; a project record uses the project's. A module that declares the
`external_references` sub-component can switch the feature off, which answers 404 here.

Every change writes `reference_added`, `reference_updated` or `reference_removed` against the record
(`services.external_references.audit_reference`, no key or link in the detail).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types
from app.schemas.external_reference import (
    ExternalReferenceIn,
    ExternalReferenceUpdate,
    PageReferencesOut,
    RecordReferencesOut,
    ReferencedRecordOut,
    ReferencedRecordsOut,
    SystemChoiceOut,
)
from app.services import external_references as refs
from app.services.external_reference_surfaces import (
    MAX_FOUND_RECORDS,
    MAX_PAGE_RECORDS,
    find_records_by_reference,
    page_references,
)
from app.services.link_authoring import DRAFT_ARTEFACT_ID
from app.services.link_graph import ArtefactResolver
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_view
from app.services.tags import can_tag, require_tag_authority, require_visible_record
from app.services.type_vocabulary import EffectiveType

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/external-references", tags=["external-references"])
#: The reads that are about a project's records as a whole (a list's column, the look-up by key).
project_router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["external-references"])


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, else 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _systems_out(db: Session, project: Project, owner_project_id: UUID | None) -> list[SystemChoiceOut]:
    """The systems a record of this tier can be given a reference in: the project's effective list, or the
    organisation's active ones for an organisation-owned record. A disabled system is left out."""
    if owner_project_id is None:
        return [
            SystemChoiceOut(id=t.id, name=t.name, url_template=t.url_template)
            for t in refs.EXTERNAL_SYSTEMS.active_org_types(db, project.organization_id)
        ]
    entries: list[EffectiveType] = refs.EXTERNAL_SYSTEMS.resolve_effective(db, owner_project_id, project.organization_id)
    return [
        SystemChoiceOut(id=e.id, name=e.name, url_template=e.extras.get("url_template")) for e in entries if e.is_enabled
    ]


def _context(
    db: Session, project_id: UUID, user: User, artefact_type: str, artefact_id: UUID,
) -> tuple[Project, ArtefactResolver, UUID | None]:
    """The project, the resolver and the record's owning project id (`None`: organisation-owned) of a record the
    caller can open, else 404 (also while references are switched off for its type)."""
    project = _project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, user.id)
    owner = require_visible_record(resolver, project, artefact_type, artefact_id)
    _require_enabled(db, project, artefact_type, owner)
    return project, resolver, owner


def _require_enabled(db: Session, project: Project, artefact_type: str, owner_project_id: UUID | None) -> None:
    """Raises 404 while the record type's module has external references switched off."""
    if not refs.references_enabled(
        db, artefact_type, organization_id=project.organization_id, project_id=owner_project_id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "External references are switched off here.")


def _out(
    db: Session, project: Project, resolver: ArtefactResolver, artefact_type: str, artefact_id: UUID,
    owner_project_id: UUID | None,
) -> RecordReferencesOut:
    """A record's references with the picker data."""
    return RecordReferencesOut(
        references=refs.references_for_records(db, artefact_type, [artefact_id])[artefact_id],
        can_edit=can_tag(resolver, artefact_type), systems=_systems_out(db, project, owner_project_id),
    )


def _owner_project(db: Session, owner_project_id: UUID | None) -> Project | None:
    """The record's owning project (`None` for an organisation-owned record)."""
    return db.get(Project, owner_project_id) if owner_project_id is not None else None


@router.get("", response_model=RecordReferencesOut)
def get_record_references(
    project_id: UUID, artefact_type: str, artefact_id: UUID, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> RecordReferencesOut:
    """The record's references, whether the caller may change them, and the systems to choose from.

    `DRAFT_ARTEFACT_ID` stands for a record being created: no references, but the same `can_edit` and `systems` the
    create form's field needs (a write never accepts it)."""
    if artefact_id == DRAFT_ARTEFACT_ID:
        project = _project_or_404(db, project_id)
        if artefact_type not in get_all_registered_artefact_types():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
        _require_enabled(db, project, artefact_type, project.id)
        resolver = ArtefactResolver(db, project, current_user.id)
        return RecordReferencesOut(
            references=[], can_edit=can_tag(resolver, artefact_type), systems=_systems_out(db, project, project.id),
        )
    project, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    return _out(db, project, resolver, artefact_type, artefact_id, owner)


@router.post("", response_model=RecordReferencesOut, status_code=status.HTTP_201_CREATED)
def add_record_reference(
    project_id: UUID, artefact_type: str, artefact_id: UUID, body: ExternalReferenceIn,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordReferencesOut:
    """Adds a reference: a system from the record's tier's list, a key and/or an http(s) link, an optional note
    and role. 400 for a system the record cannot use or more than the maximum references."""
    project, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    require_tag_authority(resolver, artefact_type)
    try:
        row = refs.add_reference(
            db, artefact_type=artefact_type, artefact_id=artefact_id, organization_id=project.organization_id,
            project=_owner_project(db, owner), system_id=body.system_id, key=body.key, url=body.url, note=body.note,
            role=body.role, actor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    refs.audit_reference(db, row, "reference_added", current_user.id)
    db.commit()
    return _out(db, project, resolver, artefact_type, artefact_id, owner)


@router.patch("/{reference_id}", response_model=RecordReferencesOut)
def update_record_reference(
    project_id: UUID, artefact_type: str, artefact_id: UUID, reference_id: UUID, body: ExternalReferenceUpdate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordReferencesOut:
    """Changes a reference (only fields present in the body)."""
    project, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    require_tag_authority(resolver, artefact_type)
    row = refs.get_reference(db, artefact_type, artefact_id, reference_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference not found.")
    try:
        refs.update_reference(db, row, _owner_project(db, owner), body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    refs.audit_reference(db, row, "reference_updated", current_user.id)
    db.commit()
    return _out(db, project, resolver, artefact_type, artefact_id, owner)


@router.delete("/{reference_id}", response_model=RecordReferencesOut)
def remove_record_reference(
    project_id: UUID, artefact_type: str, artefact_id: UUID, reference_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordReferencesOut:
    """Removes a reference."""
    project, resolver, owner = _context(db, project_id, current_user, artefact_type, artefact_id)
    require_tag_authority(resolver, artefact_type)
    row = refs.get_reference(db, artefact_type, artefact_id, reference_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference not found.")
    refs.audit_reference(db, row, "reference_removed", current_user.id)
    refs.remove_reference(db, row)
    db.commit()
    return _out(db, project, resolver, artefact_type, artefact_id, owner)


@project_router.get("/external-references/{artefact_type}", response_model=PageReferencesOut)
def get_page_references(
    project_id: UUID, artefact_type: str, id: list[UUID] = Query(default=[]),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> PageReferencesOut:
    """The references of the listed records of one type, in a few statements, for a list's External references
    column. Records the caller cannot open from this project are left out, never reported as having none."""
    project = _project_or_404(db, project_id)
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    if not refs.references_enabled(db, artefact_type, organization_id=project.organization_id, project_id=project.id):
        return PageReferencesOut(references={})
    resolver = ArtefactResolver(db, project, current_user.id)
    return PageReferencesOut(references=page_references(db, project, resolver, artefact_type, id[:MAX_PAGE_RECORDS]))


@project_router.get("/records/by-external-reference", response_model=ReferencedRecordsOut)
def find_records_by_external_reference(
    project_id: UUID, key: str = Query(..., description="The key in the outside system, e.g. `PROJ-123` (exact, ignoring case)."),
    system: str | None = Query(None, description="The external system's name; any system when omitted."),
    artefact_type: str | None = Query(None, description="Only records of this registered type."),
    limit: int = Query(MAX_FOUND_RECORDS, ge=1, le=MAX_FOUND_RECORDS), project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReferencedRecordsOut:
    """Records of any type that carry this outside key and that the caller can open (others are omitted, not
    described), for an integration or an agent that holds a Jira or DOORS key and needs the record.

    `project_scope` also looks in the related projects the caller can open; each record carries its project."""
    project = _project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, current_user.id, include_related=project_scope.widened)
    scope_ids = {r.project.id for r in project_scope.projects(db, project, current_user.id)}
    records, truncated = find_records_by_reference(
        db, project=project, resolver=resolver, key=key, system=system, artefact_type=artefact_type, limit=limit,
        project_ids=scope_ids,
    )
    return ReferencedRecordsOut(records=[ReferencedRecordOut(**r.__dict__) for r in records], truncated=truncated)
