"""
Module: routers.tags

The tag API, for projects and for the organisation:
- `GET/POST .../tags`, `PATCH/DELETE .../tags/{id}`, `POST .../tags/{id}/merge`: the vocabulary.
- `PUT .../tag-settings`: free or restricted mode.
- `GET .../tags/usage` and `POST .../tags/reclassify`: usage tables and bulk change.
- `GET/PUT/POST/DELETE .../artefacts/{type}/{id}/tags`: the tags on one record of any type.

Authorisation: reading follows the record (or the project); applying a tag needs the authority
`services.tags.can_tag` gives; managing the vocabulary needs project settings authority (an
organisation administrator for the organisation's own vocabulary). A record the caller cannot
open is a 404, never a 403, as for the Links panel. The organisation's vocabulary is used only
by organisation-owned records (no project).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.tag import Tag
from app.models.user import User
from app.modules.registry import get_all_registered_artefact_types
from app.schemas.tags import (
    ReclassifyIn,
    ReclassifyOut,
    RecordTagAdd,
    RecordTagsOut,
    RecordTagsSet,
    TagChipOut,
    TagCreate,
    TagDeleteOut,
    TaggedRecordOut,
    TaggedRecordsOut,
    TagMerge,
    TagMergeOut,
    TagModeSet,
    TagOut,
    TagUpdate,
    TagUsageOut,
    TypeUsageOut,
    UsageRowOut,
    VocabularyOut,
)
from app.services import tags as tag_service
from app.services.link_authoring import DRAFT_ARTEFACT_ID
from app.services.link_graph import ArtefactResolver
from app.services.project_scope import ProjectScope
from app.services.rbac import can_manage_project_settings, require_org_role, require_project_manage, require_project_view
from app.services.tags import TagScope

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["tags"])
org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/tags", tags=["tags"])

_ANY_ORG_ROLE = (OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)
_org_admin = require_org_role(OrgRole.ORG_ADMIN)


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, else 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, else 404."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _chip(tag: Tag) -> TagChipOut:
    """A tag as the compact chip schema."""
    return TagChipOut(id=tag.id, name=tag.name, colour=tag.colour)


def _vocabulary_out(db: Session, vocab: tag_service.Vocabulary, *, own_project: Project | None) -> VocabularyOut:
    """The vocabulary with usage counts; a tag inherited from an ancestor is not editable here, and its
    count covers only this project's records."""
    counts = tag_service.usage_counts(
        db, [t.id for t in vocab.tags], project_id=own_project.id if vocab.inherited and own_project else None,
    )
    return VocabularyOut(
        mode=vocab.mode, mode_inherited=vocab.mode_inherited, inherited=vocab.inherited,
        has_parent=own_project is not None and own_project.parent_project_id is not None,
        own_mode=own_project.tag_mode if own_project is not None else vocab.mode,
        tags=[
            TagOut(id=t.id, name=t.name, colour=t.colour, usage_count=counts.get(t.id, 0), editable=not vocab.inherited)
            for t in vocab.tags
        ],
    )


def _usage_out(db: Session, scope: TagScope, artefact_type: str | None, vocab: tag_service.Vocabulary) -> TagUsageOut:
    """The usage tables plus the vocabulary tags nothing carries (none when the list is inherited)."""
    tables = tag_service.usage_by_type(db, scope, artefact_type)
    counts = tag_service.usage_counts(db, [t.id for t in vocab.tags])
    return TagUsageOut(
        tables=[
            TypeUsageOut(
                artefact_type=t.artefact_type, label=t.label,
                rows=[
                    UsageRowOut(tag_id=r.tag.id, name=r.tag.name, colour=r.tag.colour, count=r.count, last_used=r.last_used)
                    for r in t.rows
                ],
            )
            for t in tables
        ],
        unused=[_chip(t) for t in vocab.tags if counts.get(t.id, 0) == 0 and not vocab.inherited],
    )


# --- project vocabulary -----------------------------------------------------------------------


@router.get("/tags", response_model=VocabularyOut)
def get_project_tags(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> VocabularyOut:
    """The tags the project offers (its own, else its nearest ancestor's) with usage counts and mode."""
    project = _project_or_404(db, project_id)
    return _vocabulary_out(db, tag_service.vocabulary_for_project(db, project), own_project=project)


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_project_tag(
    project_id: UUID, body: TagCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> TagOut:
    """Adds a tag to the project's own vocabulary (the way a restricted list grows)."""
    tag = tag_service.create_tag(
        db, scope=TagScope(project.organization_id, project.id), actor_id=current_user.id, name=body.name,
        colour=body.colour,
    )
    db.commit()
    return TagOut(id=tag.id, name=tag.name, colour=tag.colour, usage_count=0, editable=True)


@router.put("/tag-settings", response_model=VocabularyOut)
def set_project_tag_mode(
    project_id: UUID, body: TagModeSet, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> VocabularyOut:
    """Sets the project's tag mode (`free`, `restricted`, or `null` to follow the nearest ancestor)."""
    tag_service.set_mode(db, project=project, organization=None, actor_id=current_user.id, mode=body.mode)
    db.commit()
    return _vocabulary_out(db, tag_service.vocabulary_for_project(db, project), own_project=project)


@router.get("/tags/usage", response_model=TagUsageOut)
def get_project_tag_usage(
    project_id: UUID, artefact_type: str | None = Query(None), current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> TagUsageOut:
    """Per record type, which tags are used how often and when last (the project's own records).

    A type the caller cannot view is left out, so the tables reveal nothing about its records."""
    project = _project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, current_user.id)
    out = _usage_out(
        db, TagScope(project.organization_id, project.id), artefact_type, tag_service.vocabulary_for_project(db, project),
    )
    out.tables = [t for t in out.tables if resolver.holds(t.artefact_type, "view")]
    return out


@router.get("/tags/records", response_model=TaggedRecordsOut)
def find_tagged_records(
    project_id: UUID, tag: list[str] = Query(..., description="Tag names (case-insensitive)."),
    tag_mode: Literal["any", "all"] = Query("any"), artefact_type: str | None = Query(None),
    limit: int = Query(tag_service.MAX_TAGGED_RECORDS, ge=1, le=tag_service.MAX_TAGGED_RECORDS),
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> TaggedRecordsOut:
    """Records of any type carrying these tags that the caller can open (others are omitted, not described).

    `project_scope` also looks in the related projects the caller can open; the resolver applies each
    one's own module, permission and visibility rules, and a record from another project carries its
    `project_id`, `project_name` and `project_code`."""
    project = _project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, current_user.id, include_related=project_scope.widened)
    scope_ids = {r.project.id for r in project_scope.projects(db, project, current_user.id)}
    records, truncated = tag_service.find_tagged_records(
        db, project=project, resolver=resolver, names=tag, match_all=tag_mode == "all", artefact_type=artefact_type,
        limit=limit, project_ids=scope_ids,
    )
    return TaggedRecordsOut(
        records=[TaggedRecordOut(**r.__dict__) for r in records], truncated=truncated,
    )


@router.post("/tags/reclassify", response_model=ReclassifyOut)
def reclassify_project_tags(
    project_id: UUID, body: ReclassifyIn, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ReclassifyOut:
    """Adds and removes tags on many records at once; `dry_run` (the default) only counts.

    Choosing by `from_tag_id` (every record with that tag) needs project settings authority.
    Choosing by `records` needs tag authority for each record's type and a record visible here.
    """
    project = _project_or_404(db, project_id)
    scope = TagScope(project.organization_id, project.id)
    if body.from_tag_id is not None:
        if not can_manage_project_settings(db, current_user, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")
        records = tag_service.records_with_tag(
            db, scope=scope, tag_id=body.from_tag_id, artefact_types=body.artefact_types,
        )
    elif body.records:
        resolver = ArtefactResolver(db, project, current_user.id)
        records = []
        for item in body.records:
            owner = tag_service.require_visible_record(resolver, project, item.artefact_type, item.artefact_id)
            if owner is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Organisation-owned records are reclassified from Organisation Admin.",
                )
            tag_service.require_tag_authority(resolver, item.artefact_type)
            records.append((item.artefact_type, item.artefact_id, owner))
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose records or a tag to reclassify from.")
    result = tag_service.reclassify(
        db, scope=scope, actor_id=current_user.id, records=records, add_ids=body.add, remove_ids=body.remove,
        dry_run=body.dry_run,
    )
    if not body.dry_run:
        db.commit()
    return ReclassifyOut(matched=result.matched, added=result.added, removed=result.removed, dry_run=body.dry_run)


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_project_tag(
    project_id: UUID, tag_id: UUID, body: TagUpdate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> TagOut:
    """Renames a tag and/or sets its colour. A tag inherited from a parent project is managed there (404 here)."""
    tag = tag_service.update_tag(
        db, scope=TagScope(project.organization_id, project.id), actor_id=current_user.id, tag_id=tag_id,
        name=body.name, colour=body.colour, clear_colour=body.clear_colour,
    )
    db.commit()
    return TagOut(
        id=tag.id, name=tag.name, colour=tag.colour, usage_count=tag_service.usage_count(db, tag.id), editable=True,
    )


@router.post("/tags/{tag_id}/merge", response_model=TagMergeOut)
def merge_project_tag(
    project_id: UUID, tag_id: UUID, body: TagMerge, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> TagMergeOut:
    """Moves every record from this tag to another and deletes this tag."""
    moved = tag_service.merge_tags(
        db, scope=TagScope(project.organization_id, project.id), actor_id=current_user.id, source_id=tag_id,
        target_id=body.into_tag_id,
    )
    db.commit()
    return TagMergeOut(records_moved=moved)


@router.delete("/tags/{tag_id}", response_model=TagDeleteOut)
def delete_project_tag(
    project_id: UUID, tag_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> TagDeleteOut:
    """Deletes a tag and removes it from every record that carries it."""
    affected = tag_service.delete_tag(
        db, scope=TagScope(project.organization_id, project.id), actor_id=current_user.id, tag_id=tag_id,
    )
    db.commit()
    return TagDeleteOut(records_untagged=affected)


# --- tags on one record -----------------------------------------------------------------------


def _record_context(
    db: Session, project_id: UUID, user: User, artefact_type: str, artefact_id: UUID,
) -> tuple[ArtefactResolver, TagScope]:
    """The resolver and the vocabulary scope of a record the caller can open (else 404)."""
    project = _project_or_404(db, project_id)
    resolver = ArtefactResolver(db, project, user.id)
    owner = tag_service.require_visible_record(resolver, project, artefact_type, artefact_id)
    return resolver, tag_service.scope_of_record(project, owner)


def _record_out(
    db: Session, resolver: ArtefactResolver, scope: TagScope, artefact_type: str, artefact_id: UUID,
) -> RecordTagsOut:
    """A record's tags with the picker data (`can_edit`, mode, the vocabulary to choose from)."""
    offered = tag_service.offered_tags(db, scope)
    return RecordTagsOut(
        tags=[_chip(t) for t in tag_service.get_record_tags(db, artefact_type, artefact_id)],
        can_edit=tag_service.can_tag(resolver, artefact_type),
        restricted=tag_service.mode_for_scope(db, scope) == tag_service.TAG_MODE_RESTRICTED,
        suggestions=[_chip(t) for t in sorted(offered.values(), key=lambda t: t.name.lower())],
    )


@router.get("/artefacts/{artefact_type}/{artefact_id}/tags", response_model=RecordTagsOut)
def get_record_tags(
    project_id: UUID, artefact_type: str, artefact_id: UUID, current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> RecordTagsOut:
    """The record's tags, whether the caller may change them, and the vocabulary to pick from.

    `DRAFT_ARTEFACT_ID` stands for a record being created: no tags, but the same `can_edit`,
    `restricted` and `suggestions` the create form's tag field needs (a write never accepts it)."""
    if artefact_id == DRAFT_ARTEFACT_ID:
        project = _project_or_404(db, project_id)
        if artefact_type not in get_all_registered_artefact_types():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
        resolver = ArtefactResolver(db, project, current_user.id)
        scope = tag_service.scope_of_record(project, project.id)
        return RecordTagsOut(
            tags=[], can_edit=tag_service.can_tag(resolver, artefact_type),
            restricted=tag_service.mode_for_scope(db, scope) == tag_service.TAG_MODE_RESTRICTED,
            suggestions=[_chip(t) for t in sorted(tag_service.offered_tags(db, scope).values(), key=lambda t: t.name.lower())],
        )
    resolver, scope = _record_context(db, project_id, current_user, artefact_type, artefact_id)
    return _record_out(db, resolver, scope, artefact_type, artefact_id)


@router.put("/artefacts/{artefact_type}/{artefact_id}/tags", response_model=RecordTagsOut)
def set_record_tags(
    project_id: UUID, artefact_type: str, artefact_id: UUID, body: RecordTagsSet,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordTagsOut:
    """Makes the record carry exactly these tag names (new names are created in free mode)."""
    resolver, scope = _record_context(db, project_id, current_user, artefact_type, artefact_id)
    tag_service.require_tag_authority(resolver, artefact_type)
    tag_service.set_record_tags(
        db, scope=scope, actor_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        names=body.tags,
    )
    db.commit()
    return _record_out(db, resolver, scope, artefact_type, artefact_id)


@router.post(
    "/artefacts/{artefact_type}/{artefact_id}/tags", response_model=RecordTagsOut, status_code=status.HTTP_201_CREATED,
)
def add_record_tag(
    project_id: UUID, artefact_type: str, artefact_id: UUID, body: RecordTagAdd,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordTagsOut:
    """Adds one tag by name, keeping the record's others."""
    resolver, scope = _record_context(db, project_id, current_user, artefact_type, artefact_id)
    tag_service.require_tag_authority(resolver, artefact_type)
    tag_service.add_record_tag(
        db, scope=scope, actor_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id, name=body.name,
    )
    db.commit()
    return _record_out(db, resolver, scope, artefact_type, artefact_id)


@router.delete("/artefacts/{artefact_type}/{artefact_id}/tags/{tag_id}", response_model=RecordTagsOut)
def remove_record_tag(
    project_id: UUID, artefact_type: str, artefact_id: UUID, tag_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> RecordTagsOut:
    """Removes one tag from the record."""
    resolver, scope = _record_context(db, project_id, current_user, artefact_type, artefact_id)
    tag_service.require_tag_authority(resolver, artefact_type)
    tag_service.remove_record_tag(
        db, scope=scope, actor_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id, tag_id=tag_id,
    )
    db.commit()
    return _record_out(db, resolver, scope, artefact_type, artefact_id)


# --- organisation vocabulary ------------------------------------------------------------------


@org_router.get("", response_model=VocabularyOut)
def get_org_tags(
    organization_id: UUID, current_user: User = Depends(require_org_role(*_ANY_ORG_ROLE)), db: Session = Depends(get_db),
) -> VocabularyOut:
    """The organisation's own tag vocabulary (used by organisation-owned records) and its mode."""
    _org_or_404(db, organization_id)
    return _vocabulary_out(db, tag_service.vocabulary_for_organization(db, organization_id), own_project=None)


@org_router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_org_tag(
    organization_id: UUID, body: TagCreate, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> TagOut:
    """Adds a tag to the organisation's vocabulary."""
    _org_or_404(db, organization_id)
    tag = tag_service.create_tag(
        db, scope=TagScope(organization_id, None), actor_id=current_user.id, name=body.name, colour=body.colour,
    )
    db.commit()
    return TagOut(id=tag.id, name=tag.name, colour=tag.colour, usage_count=0, editable=True)


@org_router.put("/settings", response_model=VocabularyOut)
def set_org_tag_mode(
    organization_id: UUID, body: TagModeSet, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> VocabularyOut:
    """Sets whether organisation-owned records may take an unlisted tag (`free`) or not (`restricted`)."""
    org = _org_or_404(db, organization_id)
    tag_service.set_mode(db, project=None, organization=org, actor_id=current_user.id, mode=body.mode)
    db.commit()
    return _vocabulary_out(db, tag_service.vocabulary_for_organization(db, organization_id), own_project=None)


@org_router.get("/usage", response_model=TagUsageOut)
def get_org_tag_usage(
    organization_id: UUID, artefact_type: str | None = Query(None), current_user: User = Depends(_org_admin),
    db: Session = Depends(get_db),
) -> TagUsageOut:
    """Per record type, which organisation tags are used how often and when last."""
    _org_or_404(db, organization_id)
    return _usage_out(
        db, TagScope(organization_id, None), artefact_type, tag_service.vocabulary_for_organization(db, organization_id),
    )


@org_router.post("/reclassify", response_model=ReclassifyOut)
def reclassify_org_tags(
    organization_id: UUID, body: ReclassifyIn, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> ReclassifyOut:
    """Adds and removes organisation tags on every organisation-owned record carrying `from_tag_id`."""
    _org_or_404(db, organization_id)
    if body.from_tag_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose the tag to reclassify from.")
    scope = TagScope(organization_id, None)
    records = tag_service.records_with_tag(db, scope=scope, tag_id=body.from_tag_id, artefact_types=body.artefact_types)
    result = tag_service.reclassify(
        db, scope=scope, actor_id=current_user.id, records=records, add_ids=body.add, remove_ids=body.remove,
        dry_run=body.dry_run,
    )
    if not body.dry_run:
        db.commit()
    return ReclassifyOut(matched=result.matched, added=result.added, removed=result.removed, dry_run=body.dry_run)


@org_router.patch("/{tag_id}", response_model=TagOut)
def update_org_tag(
    organization_id: UUID, tag_id: UUID, body: TagUpdate, current_user: User = Depends(_org_admin),
    db: Session = Depends(get_db),
) -> TagOut:
    """Renames an organisation tag and/or sets its colour."""
    _org_or_404(db, organization_id)
    tag = tag_service.update_tag(
        db, scope=TagScope(organization_id, None), actor_id=current_user.id, tag_id=tag_id, name=body.name,
        colour=body.colour, clear_colour=body.clear_colour,
    )
    db.commit()
    return TagOut(
        id=tag.id, name=tag.name, colour=tag.colour, usage_count=tag_service.usage_count(db, tag.id), editable=True,
    )


@org_router.post("/{tag_id}/merge", response_model=TagMergeOut)
def merge_org_tag(
    organization_id: UUID, tag_id: UUID, body: TagMerge, current_user: User = Depends(_org_admin),
    db: Session = Depends(get_db),
) -> TagMergeOut:
    """Moves every record from this organisation tag to another and deletes this one."""
    _org_or_404(db, organization_id)
    moved = tag_service.merge_tags(
        db, scope=TagScope(organization_id, None), actor_id=current_user.id, source_id=tag_id, target_id=body.into_tag_id,
    )
    db.commit()
    return TagMergeOut(records_moved=moved)


@org_router.delete("/{tag_id}", response_model=TagDeleteOut)
def delete_org_tag(
    organization_id: UUID, tag_id: UUID, current_user: User = Depends(_org_admin), db: Session = Depends(get_db),
) -> TagDeleteOut:
    """Deletes an organisation tag and removes it from every record."""
    _org_or_404(db, organization_id)
    affected = tag_service.delete_tag(db, scope=TagScope(organization_id, None), actor_id=current_user.id, tag_id=tag_id)
    db.commit()
    return TagDeleteOut(records_untagged=affected)
