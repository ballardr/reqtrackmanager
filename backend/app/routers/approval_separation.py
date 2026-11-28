"""
Module: routers.approval_separation

Approval separation configuration and the per-record status: whether the person who created a record may approve it
(`services.approval_separation`).

Responsibilities:
- Project: read the rule of every gated type of the project's enabled modules (any project member) and set the
  project's own choice for one type.
- Organisation: read the gated types with their requirement and exemptions, set the requirement of a type, add or
  remove an exempt project.
- Record: read a record's self-approval mark and whether the caller must find another approver.

Design decisions:
- Changing needs the lifecycle permissions (`manage_project_lifecycles`, `manage_org_lifecycles`) with no
  server-administrator bypass: the setting belongs to the customer's process, and it sits in the same Lifecycles group.
- A module a project or organisation cannot use is left out, so nobody is offered a switch that does nothing.
- The record status never reveals a record of another project: the record must belong to the path's project (or
  organisation).

Dependencies: `services.approval_separation`, the module registry (labels and availability).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import artefact_type_module
from app.schemas.lifecycle import (
    ApprovalStatusOut,
    ExemptionOut,
    ExemptionSet,
    OrgSeparationOut,
    OrgSeparationSet,
    ProjectSeparationOut,
    ProjectSeparationSet,
    ProjectSeparationsOut,
)
from app.services import approval_separation as separation
from app.services.lookups import project_or_404
from app.services.rbac import (
    MANAGE_ORG_LIFECYCLES,
    MANAGE_PROJECT_LIFECYCLES,
    get_effective_permissions,
    permission_satisfied,
    require_org_role,
    require_permission,
    require_project_view,
)

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/approval-separation", tags=["approval-separation"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/approval-separation", tags=["approval-separation"])

_manage_project = require_permission(MANAGE_PROJECT_LIFECYCLES, server_admin_bypass=False)
_manage_org = require_permission(MANAGE_ORG_LIFECYCLES, server_admin_bypass=False)
_org_member = require_org_role(*OrgRole)


def _module_name(artefact_type: str) -> str:
    """The display name of the module that owns the type (an empty string for a core type)."""
    module = artefact_type_module(artefact_type)
    return "" if module is None else module.name


def _project_response(db: Session, project: Project, user: User) -> ProjectSeparationsOut:
    """The project's rules and the caller's right to change them."""
    held = get_effective_permissions(db, user.id, project_id=project.id)
    return ProjectSeparationsOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_LIFECYCLES),
        has_parent=project.parent_project_id is not None,
        types=[
            ProjectSeparationOut(
                artefact_type=r.gate.artefact_type, label=r.gate.label, module_key=r.gate.module_key,
                module_name=_module_name(r.gate.artefact_type), own=r.own, chosen=r.chosen, source=r.source,
                required=r.enforced, exempt=r.required and r.exempt, separate=r.separate,
                self_approval_org_admins_only=r.gate.org_admins_only,
            )
            for r in separation.resolve_project_separations(db, project)
        ],
    )


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or 404."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _org_response(db: Session, org: Organization) -> list[OrgSeparationOut]:
    """The organisation's gated types with their requirement and exemptions."""
    rows = separation.organization_separations(db, org)
    project_ids = {pid for row in rows for pid, _ in row["exemptions"]}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    return [
        OrgSeparationOut(
            artefact_type=row["gate"].artefact_type, label=row["gate"].label, module_key=row["gate"].module_key,
            module_name=_module_name(row["gate"].artefact_type), required=row["required"],
            self_approval_org_admins_only=row["gate"].org_admins_only,
            exemptions=[
                ExemptionOut(
                    project_id=pid, project_name=projects[pid].name, project_code=projects[pid].code,
                    include_children=include_children,
                )
                for pid, include_children in row["exemptions"] if pid in projects
            ],
        )
        for row in rows
    ]


def _status_out(db: Session, data: dict) -> ApprovalStatusOut:
    """The status dictionary as the API shape, naming who approved."""
    approver = db.get(User, data["approved_by"]) if data["approved_by"] else None
    return ApprovalStatusOut(
        self_approved=data["self_approved"], approved_by_name=None if approver is None else approver.display_name,
        approved_at=data["approved_at"], needs_other_approver=data["needs_other_approver"],
    )


# --- project ----------------------------------------------------------------------------------


@project_router.get("", response_model=ProjectSeparationsOut)
def get_project_separations(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ProjectSeparationsOut:
    """The rule of every gated type of the project's enabled modules."""
    return _project_response(db, project_or_404(db, project_id), current_user)


@project_router.get("/status/{artefact_type}/{record_id}", response_model=ApprovalStatusOut)
def get_project_record_status(
    project_id: UUID, artefact_type: str, record_id: UUID,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ApprovalStatusOut:
    """A project record's self-approval mark and whether the caller must find another approver."""
    project = project_or_404(db, project_id)
    context = separation.record_context(db, artefact_type, record_id)
    if context is None or context[1] != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found.")
    return _status_out(db, separation.approval_status(
        db, user=current_user, artefact_type=artefact_type, record_id=record_id, creator_id=context[0],
        organization_id=project.organization_id, project_id=project_id,
    ))


@project_router.put("/{artefact_type}", response_model=ProjectSeparationsOut)
def set_project_separation(
    project_id: UUID, artefact_type: str, body: ProjectSeparationSet,
    current_user: User = Depends(_manage_project), db: Session = Depends(get_db),
) -> ProjectSeparationsOut:
    """Sets the project's own choice for one type (`null` follows the nearest ancestor project)."""
    project = project_or_404(db, project_id)
    separation.set_project_separation(
        db, project=project, artefact_type=artefact_type, separate=body.separate_approver, actor_id=current_user.id,
    )
    db.commit()
    return _project_response(db, project, current_user)


# --- organisation -----------------------------------------------------------------------------


@org_router.get("", response_model=list[OrgSeparationOut])
def get_org_separations(
    organization_id: UUID, current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgSeparationOut]:
    """The organisation's gated types with their requirement and exempt projects."""
    return _org_response(db, _org_or_404(db, organization_id))


@org_router.get("/status/{artefact_type}/{record_id}", response_model=ApprovalStatusOut)
def get_org_record_status(
    organization_id: UUID, artefact_type: str, record_id: UUID,
    current_user: User = Depends(_org_member), db: Session = Depends(get_db),
) -> ApprovalStatusOut:
    """An organisation-owned record's self-approval mark and whether the caller must find another approver."""
    context = separation.record_context(db, artefact_type, record_id)
    if context is None or context[1] is not None or context[2] != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found.")
    return _status_out(db, separation.approval_status(
        db, user=current_user, artefact_type=artefact_type, record_id=record_id, creator_id=context[0],
        organization_id=organization_id, project_id=None,
    ))


@org_router.put("/{artefact_type}", response_model=list[OrgSeparationOut])
def set_org_separation(
    organization_id: UUID, artefact_type: str, body: OrgSeparationSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgSeparationOut]:
    """Sets whether the organisation requires a separate approver for one type."""
    org = _org_or_404(db, organization_id)
    separation.set_org_required(
        db, organization=org, artefact_type=artefact_type, required=body.required, actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)


@org_router.post("/{artefact_type}/exemptions", response_model=list[OrgSeparationOut])
def add_org_exemption(
    organization_id: UUID, artefact_type: str, body: ExemptionSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgSeparationOut]:
    """Exempts a project (optionally with its nested children) from the organisation's requirement for a type."""
    org = _org_or_404(db, organization_id)
    project = db.get(Project, body.project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    separation.add_exemption(
        db, organization=org, artefact_type=artefact_type, project=project, include_children=body.include_children,
        actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)


@org_router.delete("/{artefact_type}/exemptions/{project_id}", response_model=list[OrgSeparationOut])
def remove_org_exemption(
    organization_id: UUID, artefact_type: str, project_id: UUID,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgSeparationOut]:
    """Removes a project's exemption."""
    org = _org_or_404(db, organization_id)
    separation.remove_exemption(
        db, organization=org, artefact_type=artefact_type, project_id=project_id, actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)
