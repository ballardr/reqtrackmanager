"""
Module: modules.traceability.router

Organisation-scoped API of governance profiles, mounted at `/api/v1/orgs/{organization_id}/modules/traceability`:
create, read, rename and delete a profile, set the projects it reaches, add and remove exemptions from an Enforced
profile, and see which projects a profile binds, offers or has been opted out of.

Design decisions:
- Every route needs the module to be on for the organisation (404 otherwise, as for any disabled module) and the
  `manage_org_governance` permission, with no server-administrator bypass: the policy belongs to the customer's process.
- A profile of another organisation is a 404, never a 403, so its existence is not disclosed.
- Responses assemble targets, exemptions and policy-row counts in bulk, so the list costs a fixed number of statements
  however many profiles exist.

Dependencies: `modules.traceability.profiles` (changes), `profile_resolution` (effects), `services.rbac` (gates).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.traceability import profile_resolution, profiles
from app.modules.traceability._shared import MANAGE_ORG_GOVERNANCE, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import GovernanceProfile
from app.modules.traceability.profiles import TargetSpec
from app.modules.traceability.schemas import (
    ExemptionSet,
    ProfileContributionOut,
    ProfileCreate,
    ProfileDetailOut,
    ProfileExemptionOut,
    ProfileOut,
    ProfileProjectOut,
    ProfileTargetIn,
    ProfileTargetOut,
    ProfileTargetsSet,
    ProfileUpdate,
)
from app.services.rbac import require_org_module_enabled, require_permission

router = APIRouter(prefix=f"/api/v1/orgs/{{organization_id}}/modules/{TRACEABILITY_MODULE_KEY}", tags=["traceability"])

_module_on = require_org_module_enabled(TRACEABILITY_MODULE_KEY)
_manage = require_permission(MANAGE_ORG_GOVERNANCE, server_admin_bypass=False)
_guards = [Depends(_module_on)]


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or 404."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _profile_or_404(db: Session, organization_id: UUID, profile_id: UUID) -> GovernanceProfile:
    """The organisation's profile, or 404 (also for a profile of another organisation)."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None or profile.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    return profile


def _specs(targets: Sequence[ProfileTargetIn]) -> list[TargetSpec]:
    return [TargetSpec(project_id=t.project_id, include_children=t.include_children) for t in targets]


def _profile_outs(db: Session, organization_id: UUID, wanted: Sequence[GovernanceProfile] | None = None) -> list[ProfileOut]:
    """The organisation's profiles (or `wanted`) with targets, exemptions and policy-row counts, in bulk."""
    rows = profile_resolution.rows_for_profiles(db, organization_id)
    chosen = rows.profiles if wanted is None else [p for p in rows.profiles if p.id in {w.id for w in wanted}]
    project_ids = {t.project_id for ts in rows.targets.values() for t in ts} | {e.project_id for es in rows.exemptions.values() for e in es}
    names = profile_resolution.project_names(db, project_ids)
    contributions = profiles.contribution_counts(db, organization_id, [p.id for p in chosen])
    return [
        ProfileOut(
            id=p.id, name=p.name, description=p.description, mode=ProfileMode(p.mode), target_kind=ProfileTargetKind(p.target_kind),
            targets=sorted(
                (
                    ProfileTargetOut(project_id=t.project_id, project_name=names.get(t.project_id, ""), include_children=t.include_children)
                    for t in rows.targets.get(p.id, ())
                ),
                key=lambda t: (t.project_name.casefold(), str(t.project_id)),
            ),
            exemptions=sorted(
                (
                    ProfileExemptionOut(
                        project_id=e.project_id, project_name=names.get(e.project_id, ""), include_children=e.include_children,
                        reason=e.reason,
                    )
                    for e in rows.exemptions.get(p.id, ())
                ),
                key=lambda e: (e.project_name.casefold(), str(e.project_id)),
            ),
            contributions=[ProfileContributionOut(key=k, name=n, count=c) for k, n, c in contributions.get(p.id, [])],
            created_at=p.created_at, updated_at=p.updated_at,
        )
        for p in chosen
    ]


def _detail(db: Session, profile: GovernanceProfile) -> ProfileDetailOut:
    """The profile with its effect on every project of the organisation it reaches."""
    base = _profile_outs(db, profile.organization_id, [profile])[0]
    projects = [
        ProfileProjectOut(
            project_id=project.id, project_name=project.name, outcome=outcome, applies=outcome.applies, choice=choice,
        )
        for project, outcome, choice in profile_resolution.profile_impact(db, profile)
        if outcome is not ProfileOutcome.NOT_TARGETED
    ]
    return ProfileDetailOut(**base.model_dump(), projects=projects)


@router.get("/profiles", response_model=list[ProfileOut], dependencies=_guards)
def list_profiles(organization_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db)) -> list[ProfileOut]:
    """The organisation's governance profiles with their targets, exemptions and policy-row counts."""
    _org_or_404(db, organization_id)
    return _profile_outs(db, organization_id)


@router.post("/profiles", response_model=ProfileDetailOut, status_code=status.HTTP_201_CREATED, dependencies=_guards)
def create_profile(
    organization_id: UUID, payload: ProfileCreate, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """Creates a profile."""
    org = _org_or_404(db, organization_id)
    profile = profiles.create_profile(
        db, organization=org, name=payload.name, description=payload.description, mode=payload.mode.value,
        target_kind=payload.target_kind.value, targets=_specs(payload.targets), actor_id=current_user.id,
    )
    db.commit()
    return _detail(db, profile)


@router.get("/profiles/{profile_id}", response_model=ProfileDetailOut, dependencies=_guards)
def get_profile(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """One profile with its effect on each project it reaches."""
    return _detail(db, _profile_or_404(db, organization_id, profile_id))


@router.patch("/profiles/{profile_id}", response_model=ProfileDetailOut, dependencies=_guards)
def update_profile(
    organization_id: UUID, profile_id: UUID, payload: ProfileUpdate,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """Renames a profile or changes its description or mode."""
    profile = _profile_or_404(db, organization_id, profile_id)
    profiles.update_profile(
        db, profile=profile, name=payload.name, description=payload.description,
        mode=None if payload.mode is None else payload.mode.value, actor_id=current_user.id,
    )
    db.commit()
    return _detail(db, profile)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_guards)
def delete_profile(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> None:
    """Deletes a profile with its targets, exemptions, choices and policy rows."""
    profile = _profile_or_404(db, organization_id, profile_id)
    profiles.delete_profile(db, profile=profile, actor_id=current_user.id)
    db.commit()


@router.put("/profiles/{profile_id}/targets", response_model=ProfileDetailOut, dependencies=_guards)
def set_profile_targets(
    organization_id: UUID, profile_id: UUID, payload: ProfileTargetsSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """Replaces the projects a profile reaches."""
    profile = _profile_or_404(db, organization_id, profile_id)
    profiles.set_targets(
        db, profile=profile, target_kind=payload.target_kind.value, targets=_specs(payload.targets),
        actor_id=current_user.id,
    )
    db.commit()
    return _detail(db, profile)


@router.post("/profiles/{profile_id}/exemptions", response_model=ProfileDetailOut, dependencies=_guards)
def add_profile_exemption(
    organization_id: UUID, profile_id: UUID, payload: ExemptionSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """Exempts a project from an Enforced profile."""
    profile = _profile_or_404(db, organization_id, profile_id)
    profiles.add_exemption(
        db, profile=profile, project_id=payload.project_id, include_children=payload.include_children,
        reason=payload.reason, actor_id=current_user.id,
    )
    db.commit()
    return _detail(db, profile)


@router.delete("/profiles/{profile_id}/exemptions/{project_id}", response_model=ProfileDetailOut, dependencies=_guards)
def remove_profile_exemption(
    organization_id: UUID, profile_id: UUID, project_id: UUID,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileDetailOut:
    """Removes a project's exemption from a profile."""
    profile = _profile_or_404(db, organization_id, profile_id)
    profiles.remove_exemption(db, profile=profile, project_id=project_id, actor_id=current_user.id)
    db.commit()
    return _detail(db, profile)
