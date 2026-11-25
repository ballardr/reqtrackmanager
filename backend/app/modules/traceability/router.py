"""
Module: modules.traceability.router

Organisation-scoped API of governance profiles, mounted at `/api/v1/orgs/{organization_id}/modules/traceability`:
create, read, rename and delete a profile, set the projects it reaches, add and remove exemptions from an Enforced
profile, see which projects a profile binds, offers or has been opted out of, and set a profile's lifecycle, approval,
review and baseline policy.

Design decisions:
- A profile's lifecycle, approval, review and baseline policy routes also need their sub-component to be in effect for the organisation.
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
from app.models.project import Project
from app.models.user import User
from app.modules.seams import ApproverRole
from app.modules.traceability import (
    approval_policy,
    baseline_policy,
    lifecycle_policy,
    profile_resolution,
    profiles,
    review_policy,
)
from app.modules.traceability._shared import (
    APPROVAL_POLICIES,
    BASELINE_POLICIES,
    LIFECYCLE_POLICIES,
    MANAGE_ORG_GOVERNANCE,
    REVIEW_POLICIES,
    TRACEABILITY_MODULE_KEY,
)
from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import GovernanceProfile
from app.modules.traceability.profiles import TargetSpec
from app.modules.traceability.schemas import (
    ApprovalRolesSet,
    ApproverRoleOptionOut,
    ApproverRoleOut,
    BaselineCheckOptionOut,
    BaselineFieldOptionOut,
    BaselineFieldsOut,
    BaselineSettingsIn,
    BaselineSettingsOut,
    BaselineTypeOut,
    ExemptionSet,
    LifecycleRequiredSet,
    LifecycleSkipSet,
    LifecycleStateOut,
    LifecycleTypePolicyOut,
    ProfileApprovalOut,
    ProfileApprovalTypeOut,
    ProfileBaselineOut,
    ProfileContributionOut,
    ProfileCreate,
    ProfileDetailOut,
    ProfileExemptionOut,
    ProfileLifecycleOut,
    ProfileOut,
    ProfileProjectOut,
    ProfileReviewOut,
    ProfileReviewTypeOut,
    ProfileTargetIn,
    ProfileTargetOut,
    ProfileTargetsSet,
    ProfileUpdate,
    RequiredFieldIn,
    ReviewSettingsIn,
    ReviewSettingsOut,
)
from app.services import approval_policy as core_approval
from app.services.principals import principal_out
from app.services.rbac import require_org_module_enabled, require_org_subcomponent_enabled, require_permission

router = APIRouter(prefix=f"/api/v1/orgs/{{organization_id}}/modules/{TRACEABILITY_MODULE_KEY}", tags=["traceability"])

_module_on = require_org_module_enabled(TRACEABILITY_MODULE_KEY)
_manage = require_permission(MANAGE_ORG_GOVERNANCE, server_admin_bypass=False)
_guards = [Depends(_module_on)]
_lifecycle_guards = [Depends(_module_on), Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, LIFECYCLE_POLICIES))]
_approval_guards = [Depends(_module_on), Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, APPROVAL_POLICIES))]
_review_guards = [Depends(_module_on), Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, REVIEW_POLICIES))]
_baseline_guards = [Depends(_module_on), Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, BASELINE_POLICIES))]


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


def _lifecycle_out(db: Session, profile: GovernanceProfile) -> ProfileLifecycleOut:
    """The profile's lifecycle policy as the API shape."""
    org = _org_or_404(db, profile.organization_id)
    policy = lifecycle_policy.profile_policy(db, org, profile)
    return ProfileLifecycleOut(
        types=[
            LifecycleTypePolicyOut(
                artefact_type=t.artefact_type, label=t.definition.label, module_key=t.module_key,
                states=[LifecycleStateOut(key=k, label=t.definition.labels.get(k, k)) for k in t.definition.optional],
                required=t.required,
            )
            for t in policy.types
        ],
        skip_forbidden=policy.skip_forbidden,
    )


@router.get("/profiles/{profile_id}/lifecycle", response_model=ProfileLifecycleOut, dependencies=_lifecycle_guards)
def get_profile_lifecycle(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileLifecycleOut:
    """The states a profile requires of each record type and whether it forbids skipping steps."""
    return _lifecycle_out(db, _profile_or_404(db, organization_id, profile_id))


@router.put("/profiles/{profile_id}/lifecycle/skip", response_model=ProfileLifecycleOut, dependencies=_lifecycle_guards)
def set_profile_lifecycle_skip(
    organization_id: UUID, profile_id: UUID, payload: LifecycleSkipSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileLifecycleOut:
    """Sets whether a profile forbids skipping steps in the projects it applies to."""
    profile = _profile_or_404(db, organization_id, profile_id)
    lifecycle_policy.set_skip_forbidden(db, profile=profile, forbidden=payload.forbidden, actor_id=current_user.id)
    db.commit()
    return _lifecycle_out(db, profile)


@router.put("/profiles/{profile_id}/lifecycle/{artefact_type}", response_model=ProfileLifecycleOut, dependencies=_lifecycle_guards)
def set_profile_lifecycle_required(
    organization_id: UUID, profile_id: UUID, artefact_type: str, payload: LifecycleRequiredSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileLifecycleOut:
    """Sets the states a profile requires of one record type (an empty list removes the requirement)."""
    profile = _profile_or_404(db, organization_id, profile_id)
    lifecycle_policy.set_required(
        db, profile=profile, artefact_type=artefact_type, required=payload.required, actor_id=current_user.id,
    )
    db.commit()
    return _lifecycle_out(db, profile)


def approver_role_outs(roles: Sequence[ApproverRole], labels: dict[tuple[str, str], str]) -> list[ApproverRoleOut]:
    """The roles with their display names (the key for a role that is no longer offered)."""
    return [ApproverRoleOut(kind=r.kind, key=r.key, label=labels.get((r.kind, r.key), r.key)) for r in roles]


def role_option_outs(db: Session, organization_id: UUID) -> tuple[list[ApproverRoleOptionOut], dict[tuple[str, str], str]]:
    """The roles a policy of the organisation may name, and their labels by `(kind, key)`."""
    options = core_approval.role_options(db, organization_id)
    outs = [ApproverRoleOptionOut(kind=o.role.kind, key=o.role.key, label=o.label, scope=o.scope) for o in options]
    return outs, {(o.role.kind, o.role.key): o.label for o in options}


def _approval_out(db: Session, profile: GovernanceProfile) -> ProfileApprovalOut:
    """The profile's approval policy as the API shape."""
    options, labels = role_option_outs(db, profile.organization_id)
    return ProfileApprovalOut(
        types=[
            ProfileApprovalTypeOut(
                artefact_type=gate.artefact_type, label=gate.label, module_key=gate.module_key,
                roles=approver_role_outs(roles, labels),
            )
            for gate, roles in approval_policy.profile_policy(db, profile)
        ],
        role_options=options,
    )


@router.get("/profiles/{profile_id}/approval", response_model=ProfileApprovalOut, dependencies=_approval_guards)
def get_profile_approval(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileApprovalOut:
    """The roles a profile adds as approvers of each record type, with the roles a policy may name."""
    return _approval_out(db, _profile_or_404(db, organization_id, profile_id))


@router.put("/profiles/{profile_id}/approval/{artefact_type}", response_model=ProfileApprovalOut, dependencies=_approval_guards)
def set_profile_approval(
    organization_id: UUID, profile_id: UUID, artefact_type: str, payload: ApprovalRolesSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileApprovalOut:
    """Sets the roles a profile adds as approvers of one record type (an empty list removes them)."""
    profile = _profile_or_404(db, organization_id, profile_id)
    approval_policy.set_profile_roles(
        db, profile=profile, artefact_type=artefact_type,
        roles=[ApproverRole(kind=r.kind, key=r.key) for r in payload.roles], actor_id=current_user.id,
    )
    db.commit()
    return _approval_out(db, profile)


def review_settings_out(db: Session, settings: review_policy.ReviewSettings) -> ReviewSettingsOut:
    """Review settings with the default owner resolved for display."""
    owner = settings.default_owner
    return ReviewSettingsOut(
        interval_days=settings.interval_days, lead_days=settings.lead_days,
        default_owner=None if owner is None else principal_out(db, owner.type.value, owner.id),
    )


def _review_out(db: Session, profile: GovernanceProfile) -> ProfileReviewOut:
    """The profile's review policy as the API shape."""
    return ProfileReviewOut(
        types=[
            ProfileReviewTypeOut(
                artefact_type=t.artefact_type, label=t.label, module_key=t.module_key,
                settings=review_settings_out(db, settings),
            )
            for t, settings in review_policy.profile_policy(db, profile)
        ],
    )


@router.get("/profiles/{profile_id}/review", response_model=ProfileReviewOut, dependencies=_review_guards)
def get_profile_review(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileReviewOut:
    """The review interval, reminder lead and default owner a profile gives each record type with a review schedule."""
    return _review_out(db, _profile_or_404(db, organization_id, profile_id))


@router.put("/profiles/{profile_id}/review/{artefact_type}", response_model=ProfileReviewOut, dependencies=_review_guards)
def set_profile_review(
    organization_id: UUID, profile_id: UUID, artefact_type: str, payload: ReviewSettingsIn,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileReviewOut:
    """Sets the review settings a profile gives one record type (settings with nothing set remove them)."""
    profile = _profile_or_404(db, organization_id, profile_id)
    review_policy.set_profile_settings(
        db, profile=profile, artefact_type=artefact_type,
        settings=review_policy.ReviewSettings(payload.interval_days, payload.lead_days, payload.default_owner),
        actor_id=current_user.id,
    )
    db.commit()
    return _review_out(db, profile)


def baseline_settings_out(settings: baseline_policy.BaselineSettings) -> BaselineSettingsOut:
    """Baseline settings as the API shape."""
    return BaselineSettingsOut(
        applies_to_stage=settings.applies_to_stage, applies_to_manual=settings.applies_to_manual,
        notify_managers=settings.notify_managers, checks=list(settings.checks),
        required_fields=[RequiredFieldIn(artefact_type=f.artefact_type, field_key=f.field_key) for f in settings.required_fields],
    )


def baseline_check_options_out(options: Sequence[baseline_policy.CheckOption]) -> list[BaselineCheckOptionOut]:
    """The checks an organisation can enable as the API shape."""
    return [
        BaselineCheckOptionOut(key=o.key, name=o.name, module_key=o.module_key, artefact_types=list(o.artefact_types))
        for o in options
    ]


def baseline_types_out(types: Sequence[baseline_policy.BaselineType]) -> list[BaselineTypeOut]:
    """The record types a baseline can hold as the API shape."""
    return [BaselineTypeOut(artefact_type=t.artefact_type, label=t.label, module_key=t.module_key) for t in types]


def baseline_fields_out(options: dict[str, list[baseline_policy.FieldOption]]) -> dict[str, list[BaselineFieldOptionOut]]:
    """The requirable fields of each type as the API shape."""
    return {t: [BaselineFieldOptionOut(key=o.key, label=o.label) for o in fields] for t, fields in options.items()}


def _baseline_out(db: Session, profile: GovernanceProfile) -> ProfileBaselineOut:
    """The profile's baseline policy as the API shape."""
    return ProfileBaselineOut(
        settings=baseline_settings_out(baseline_policy.profile_policy(db, profile)),
        check_options=baseline_check_options_out(baseline_policy.check_options(db, profile.organization_id)),
        types=baseline_types_out(baseline_policy.baseline_types(db, profile.organization_id)),
    )


@router.get("/profiles/{profile_id}/baseline", response_model=ProfileBaselineOut, dependencies=_baseline_guards)
def get_profile_baseline(
    organization_id: UUID, profile_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileBaselineOut:
    """The checks a profile enables before baselines, the baseline kinds they run before and the fields it requires."""
    return _baseline_out(db, _profile_or_404(db, organization_id, profile_id))


@router.put("/profiles/{profile_id}/baseline", response_model=ProfileBaselineOut, dependencies=_baseline_guards)
def set_profile_baseline(
    organization_id: UUID, profile_id: UUID, payload: BaselineSettingsIn,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProfileBaselineOut:
    """Sets a profile's baseline policy (one that enables no check and requires no field removes it)."""
    profile = _profile_or_404(db, organization_id, profile_id)
    baseline_policy.set_profile_settings(
        db, profile=profile, actor_id=current_user.id,
        settings=baseline_policy.BaselineSettings(
            payload.applies_to_stage, payload.applies_to_manual, tuple(payload.checks),
            tuple(baseline_policy.RequiredField(f.artefact_type, f.field_key) for f in payload.required_fields),
            payload.notify_managers,
        ),
    )
    db.commit()
    return _baseline_out(db, profile)


@router.get("/profiles/{profile_id}/baseline/fields", response_model=BaselineFieldsOut, dependencies=_baseline_guards)
def get_profile_baseline_fields(
    organization_id: UUID, profile_id: UUID, project_id: UUID, current_user: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> BaselineFieldsOut:
    """The fields each baseline type offers in one of the organisation's projects, for choosing a profile's required fields
    (a profile's fields are not checked against any project, since custom fields differ between projects)."""
    _profile_or_404(db, organization_id, profile_id)
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return BaselineFieldsOut(types=baseline_fields_out(baseline_policy.field_options(db, project)))
