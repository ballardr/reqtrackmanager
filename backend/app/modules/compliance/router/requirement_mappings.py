"""
Module: modules.compliance.router.requirement_mappings

Cross-standard/cross-version requirement mapping links (Phase 11,
§19/§27): create/list/get/archive/unarchive, a requirement-scoped
convenience listing visible from either side of a mapping, and the
read-only added/removed/modified/replaced/re-mapped diff between two
versions of a standard.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.modules.compliance.models import (
    ComplianceMappingRelationshipTypeDefinition,
    ComplianceRequirement,
    ComplianceRequirementMapping,
    ComplianceStandard,
    ComplianceStandardVersion,
)
from app.modules.compliance.router._shared import _get_requirement_or_404, _get_version_or_404, _require_manage, _require_view
from app.modules.compliance.schemas import ComplianceRequirementMappingCreate, ComplianceRequirementMappingOut, StandardVersionDiffOut
from app.modules.compliance.service import build_diff_out, diff_standard_versions
from app.services.audit import log_event

router = APIRouter(tags=["compliance-org-requirement-mappings"])


def _get_org_requirement_or_404(db: Session, organization_id: UUID, requirement_id: UUID) -> ComplianceRequirement:
    """Resolves a bare `requirement_id` (no `standard_id`/`version_id` path
    segments — a mapping's two endpoints may belong to entirely different
    standards) to a `ComplianceRequirement`, walking up through its version
    and standard to confirm it belongs to `organization_id` — 404, not 403,
    on a mismatch, this module's usual cross-org-isolation convention."""
    requirement = db.get(ComplianceRequirement, requirement_id)
    if requirement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    version = db.get(ComplianceStandardVersion, requirement.standard_version_id)
    standard = db.get(ComplianceStandard, version.standard_id) if version is not None else None
    if standard is None or standard.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    return requirement


def _get_mapping_or_404(db: Session, organization_id: UUID, mapping_id: UUID) -> ComplianceRequirementMapping:
    mapping = db.get(ComplianceRequirementMapping, mapping_id)
    if mapping is None or mapping.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement mapping not found.")
    return mapping


@router.post("/requirement-mappings", response_model=ComplianceRequirementMappingOut, status_code=status.HTTP_201_CREATED)
def create_requirement_mapping(
    organization_id: UUID, payload: ComplianceRequirementMappingCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Creates a mapping between two compliance requirements (§19) — a
    Compliance Manager decision, mirroring standards/requirements
    management generally. Both requirements (which may belong to different
    standards, or to two versions of the *same* standard — see `models.py`'s
    own Phase 11 notes) and the relationship type must all belong to this
    organisation (404/400 otherwise). §19's "must not imply that satisfying
    one requirement automatically satisfies another unless the relationship
    explicitly supports that behaviour" is upheld structurally: nothing
    here (or anywhere else in this module) reads a mapping to alter a
    `ProjectComplianceRequirement`'s own assessment."""
    if payload.from_requirement_id == payload.to_requirement_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A requirement cannot be mapped to itself.")
    _get_org_requirement_or_404(db, organization_id, payload.from_requirement_id)
    _get_org_requirement_or_404(db, organization_id, payload.to_requirement_id)
    relationship_type = db.get(ComplianceMappingRelationshipTypeDefinition, payload.relationship_type_id)
    if relationship_type is None or relationship_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "relationship_type_id must be a relationship type in this organisation.")
    existing = db.scalar(
        select(ComplianceRequirementMapping.id).where(
            ComplianceRequirementMapping.from_requirement_id == payload.from_requirement_id,
            ComplianceRequirementMapping.to_requirement_id == payload.to_requirement_id,
            ComplianceRequirementMapping.relationship_type_id == payload.relationship_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This exact mapping already exists.")

    mapping = ComplianceRequirementMapping(
        organization_id=organization_id, from_requirement_id=payload.from_requirement_id,
        to_requirement_id=payload.to_requirement_id, relationship_type_id=payload.relationship_type_id,
        notes=payload.notes, created_by=current_user.id,
    )
    db.add(mapping)
    db.flush()
    log_event(db, entity_type="compliance_requirement_mapping", entity_id=mapping.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"from_requirement_id": str(mapping.from_requirement_id),
                      "to_requirement_id": str(mapping.to_requirement_id),
                      "relationship_type_id": str(mapping.relationship_type_id)})
    db.commit()
    db.refresh(mapping)
    return mapping


@router.get("/requirement-mappings", response_model=list[ComplianceRequirementMappingOut])
def list_requirement_mappings(
    organization_id: UUID, requirement_id: UUID | None = Query(None), include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists this organisation's requirement mappings, optionally filtered
    to those touching one specific requirement (either side of the
    mapping — §19's "must be visible from both requirements") via
    `?requirement_id=`."""
    query = select(ComplianceRequirementMapping).where(ComplianceRequirementMapping.organization_id == organization_id)
    if not include_archived:
        query = query.where(ComplianceRequirementMapping.is_archived.is_(False))
    if requirement_id is not None:
        query = query.where(
            (ComplianceRequirementMapping.from_requirement_id == requirement_id)
            | (ComplianceRequirementMapping.to_requirement_id == requirement_id)
        )
    return db.scalars(query.order_by(ComplianceRequirementMapping.created_at)).all()


@router.get("/requirement-mappings/{mapping_id}", response_model=ComplianceRequirementMappingOut)
def get_requirement_mapping(
    organization_id: UUID, mapping_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single requirement mapping."""
    return _get_mapping_or_404(db, organization_id, mapping_id)


@router.get(
    "/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/mappings",
    response_model=list[ComplianceRequirementMappingOut],
)
def list_mappings_for_requirement(
    organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID,
    include_archived: bool = Query(False),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """§19's "visible from both requirements"/"support navigation between
    linked requirements," viewed from one specific requirement's own page
    — a filtered, requirement-scoped view onto the same `/requirement-
    mappings` data (mirrors `project_router.py::list_requirement_evidence`'s
    identical "canonical CRUD lives at a flatter resource, this is a
    read-only filtered view" shape). The `compliance_list_requirement_
    mappings` MCP tool."""
    _, _, requirement = _get_requirement_or_404(db, organization_id, standard_id, version_id, requirement_id)
    query = select(ComplianceRequirementMapping).where(
        ComplianceRequirementMapping.organization_id == organization_id,
        (ComplianceRequirementMapping.from_requirement_id == requirement.id)
        | (ComplianceRequirementMapping.to_requirement_id == requirement.id),
    )
    if not include_archived:
        query = query.where(ComplianceRequirementMapping.is_archived.is_(False))
    return db.scalars(query.order_by(ComplianceRequirementMapping.created_at)).all()


@router.post("/requirement-mappings/{mapping_id}/archive", response_model=ComplianceRequirementMappingOut)
def archive_requirement_mapping(
    organization_id: UUID, mapping_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Soft-archives a requirement mapping (§19: "must be... auditable" —
    retained, not hard-deleted, mirroring every other entity in this
    module)."""
    mapping = _get_mapping_or_404(db, organization_id, mapping_id)
    if mapping.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This mapping is already archived.")
    mapping.is_archived = True
    mapping.archived_at = datetime.now(UTC)
    mapping.archived_by = current_user.id
    log_event(db, entity_type="compliance_requirement_mapping", entity_id=mapping.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/requirement-mappings/{mapping_id}/unarchive", response_model=ComplianceRequirementMappingOut)
def unarchive_requirement_mapping(
    organization_id: UUID, mapping_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Restores an archived requirement mapping."""
    mapping = _get_mapping_or_404(db, organization_id, mapping_id)
    if not mapping.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This mapping is not archived.")
    mapping.is_archived = False
    mapping.archived_at = None
    mapping.archived_by = None
    log_event(db, entity_type="compliance_requirement_mapping", entity_id=mapping.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.get(
    "/standards/{standard_id}/versions/{version_id}/diff/{other_version_id}",
    response_model=StandardVersionDiffOut,
)
def get_standard_version_diff(
    organization_id: UUID, standard_id: UUID, version_id: UUID, other_version_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """§27's "users should be able to see what changed between standard
    versions" — computes the added/removed/modified/replaced/re-mapped
    diff between the two named versions of this standard (both must belong
    to `standard_id`; a 400 if the same version is named twice). The two
    path segments may be given in either order — the response always
    orders `old_version_id`/`new_version_id` by `version_number`, so a
    caller doesn't need to already know which of two arbitrary versions is
    older. The `compliance_get_standard_version_diff` MCP tool."""
    _, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    _, other_version = _get_version_or_404(db, organization_id, standard_id, other_version_id)
    if version.id == other_version.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot diff a version against itself.")
    old_version, new_version = (
        (version, other_version) if version.version_number < other_version.version_number else (other_version, version)
    )
    diff = diff_standard_versions(db, standard_id=standard_id, old_version=old_version, new_version=new_version)
    return build_diff_out(diff)
