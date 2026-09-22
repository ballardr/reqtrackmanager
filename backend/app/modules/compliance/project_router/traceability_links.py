"""
Module: modules.compliance.project_router.traceability_links

Cross-links between this module's own compliance requirements and
the project's core (non-compliance) requirements: create/list/delete,
gated by the same core-requirement-edit role
(`_require_core_requirement_edit_role`) core requirement links
already use, not `_require_officer`.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.modules.compliance.models import ComplianceRequirement, ComplianceRequirementTraceabilityLink, ComplianceStandard, ComplianceStandardVersion
from app.modules.compliance.project_router._shared import _require_view
from app.modules.compliance.schemas import ComplianceRequirementTraceabilityLinkCreate, ComplianceRequirementTraceabilityLinkOut
from app.services.audit import log_event
from app.services.rbac import get_effective_project_roles

router = APIRouter(tags=["compliance-project-traceability-links"])


_CAN_EDIT_CORE_REQUIREMENT_LINKS = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)


def _require_core_requirement_edit_role(db: Session, user: User, project_id: UUID) -> None:
    """Raises 403 unless `user` holds a requirement-editing role on the
    project — the same permission that already gates every other edit to
    a core requirement's own `RequirementLink`s (`routers.requirements.
    _require_edit_role`), not a new compliance-specific one, per this
    phase's own scope note."""
    if not get_effective_project_roles(db, user.id, project_id) & set(_CAN_EDIT_CORE_REQUIREMENT_LINKS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders, administrators, or managers may do this.")


def _get_core_requirement_in_project(db: Session, project_id: UUID, requirement_id: UUID) -> Requirement:
    """Mirrors `routers.requirements._get_requirement_in_project` — 404s
    unless `requirement_id` belongs to `project_id`, guarding against the
    same cross-project IDOR that helper's own docstring describes."""
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    return requirement


def _get_org_compliance_requirement_or_404(db: Session, organization_id: UUID, compliance_requirement_id: UUID) -> ComplianceRequirement:
    """Mirrors `router.py::_get_org_requirement_or_404` — resolves a bare
    `compliance_requirement_id`, walking up through its version and
    standard, to confirm it belongs to `organization_id` (404, not 403, on
    a mismatch)."""
    requirement = db.get(ComplianceRequirement, compliance_requirement_id)
    if requirement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    version = db.get(ComplianceStandardVersion, requirement.standard_version_id)
    standard = db.get(ComplianceStandard, version.standard_id) if version is not None else None
    if standard is None or standard.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    return requirement


def _traceability_link_to_out(db: Session, link: ComplianceRequirementTraceabilityLink) -> ComplianceRequirementTraceabilityLinkOut:
    """Resolves a `ComplianceRequirementTraceabilityLink` into the API
    shape, denormalising the compliance requirement's own identifying
    fields plus its owning standard/version (mirrors core's own
    `_link_to_out` "resolve everything server-side" convention) so the
    frontend's Links card can render a full row with no second round
    trip."""
    # `compliance_requirement_id`/`standard_version_id`/`standard_id` are all
    # non-nullable FKs with `ON DELETE CASCADE` back to this link row, so all
    # three lookups below are guaranteed to resolve for any link row that
    # still exists — no None-guards needed, unlike core's own `_link_to_out`
    # (whose `other_requirement_id` can legitimately point past a row this
    # exact request is racing to delete from the other end).
    compliance_requirement = db.get(ComplianceRequirement, link.compliance_requirement_id)
    version = db.get(ComplianceStandardVersion, compliance_requirement.standard_version_id)
    standard = db.get(ComplianceStandard, version.standard_id)
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id)
    return ComplianceRequirementTraceabilityLinkOut(
        id=link.id, requirement_id=link.requirement_id, compliance_requirement_id=link.compliance_requirement_id,
        link_type_id=link.link_type_id, display_name=link_type.forward_name if link_type is not None else "",
        compliance_requirement_reference=compliance_requirement.reference,
        compliance_requirement_name=compliance_requirement.name,
        standard_id=standard.id, standard_reference=standard.reference, standard_name=standard.name,
        standard_version_id=version.id, standard_version_label=version.version_label,
        created_by=link.created_by, created_at=link.created_at,
    )


@router.post(
    "/requirements/{requirement_id}/traceability-links",
    response_model=ComplianceRequirementTraceabilityLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_traceability_link(
    project_id: UUID, requirement_id: UUID, payload: ComplianceRequirementTraceabilityLinkCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a traceability link from a core requirement to a compliance
    standard requirement (Phase 34). Gated by `_require_core_requirement_
    edit_role` — the same permission that already gates every other edit
    to this requirement's own links — not a compliance-specific role."""
    _require_core_requirement_edit_role(db, current_user, project_id)
    project = db.get(Project, project_id)
    requirement = _get_core_requirement_in_project(db, project_id, requirement_id)
    _get_org_compliance_requirement_or_404(db, project.organization_id, payload.compliance_requirement_id)
    link_type = db.get(RequirementLinkTypeDefinition, payload.link_type_id)
    if link_type is None or link_type.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link_type_id must be a link type defined in this project's organisation.")
    existing = db.scalar(
        select(ComplianceRequirementTraceabilityLink.id).where(
            ComplianceRequirementTraceabilityLink.requirement_id == requirement_id,
            ComplianceRequirementTraceabilityLink.compliance_requirement_id == payload.compliance_requirement_id,
            ComplianceRequirementTraceabilityLink.link_type_id == payload.link_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This exact link already exists.")
    link = ComplianceRequirementTraceabilityLink(
        requirement_id=requirement.id, compliance_requirement_id=payload.compliance_requirement_id,
        link_type_id=payload.link_type_id, created_by=current_user.id,
    )
    db.add(link)
    db.flush()
    log_event(db, entity_type="compliance_requirement_traceability_link", entity_id=link.id, action="created",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(requirement_id), "compliance_requirement_id": str(payload.compliance_requirement_id),
                      "link_type_id": str(payload.link_type_id)})
    db.commit()
    db.refresh(link)
    return _traceability_link_to_out(db, link)


@router.get(
    "/requirements/{requirement_id}/traceability-links",
    response_model=list[ComplianceRequirementTraceabilityLinkOut],
)
def list_requirement_traceability_links(
    project_id: UUID, requirement_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists a core requirement's own compliance-requirement traceability
    links. Read access mirrors every other read endpoint on this router —
    any project member with the module enabled, not edit-gated."""
    _get_core_requirement_in_project(db, project_id, requirement_id)
    links = db.scalars(
        select(ComplianceRequirementTraceabilityLink).where(
            ComplianceRequirementTraceabilityLink.requirement_id == requirement_id
        )
    ).all()
    return [_traceability_link_to_out(db, link) for link in links]


@router.delete("/requirements/{requirement_id}/traceability-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement_traceability_link(
    project_id: UUID, requirement_id: UUID, link_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes a traceability link. 404s unless `link_id` belongs to
    `requirement_id` (mirrors core's own `delete_link`'s cross-scope
    check)."""
    _require_core_requirement_edit_role(db, current_user, project_id)
    _get_core_requirement_in_project(db, project_id, requirement_id)
    link = db.get(ComplianceRequirementTraceabilityLink, link_id)
    if link is None or link.requirement_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    log_event(db, entity_type="compliance_requirement_traceability_link", entity_id=link.id, action="deleted",
              actor_id=current_user.id, project_id=project_id,
              detail={"requirement_id": str(link.requirement_id), "compliance_requirement_id": str(link.compliance_requirement_id)})
    db.delete(link)
    db.commit()
