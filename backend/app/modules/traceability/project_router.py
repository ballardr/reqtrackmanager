"""
Module: modules.traceability.project_router

Project-scoped API of governance profiles, mounted at `/api/v1/projects/{project_id}/modules/traceability`: which
profiles reach the project and what each does for it, the project's opt-out of a Default profile or opt-in to an
Opt-in profile, the project's approval policy (the roles that may also approve a record type, with where each comes from) and its
review policy (the interval, reminder lead and default owner of a record type, with where each comes from) and its
baseline policy (the checks that run before a baseline, with where each comes from) with a preview of what they say now.

Design decisions:
- Reading is open to every member of a project the module is on for, because a person asking why a policy applies needs
  the answer; changing a choice needs `manage_project_governance` with no server-administrator bypass.
- A project sees only the profiles that reach it; a profile that does not is not listed, so the organisation's other
  profiles are not disclosed.
- An Enforced profile is listed with its outcome (`enforced` or `exempt`) and no choice: only the organisation lifts it.
- The approval, review and baseline policy routes also need their part (`approval_policies`, `review_policies`,
  `baseline_policies`) to be in effect for the project (404 otherwise).
- The baseline preview names records by code and check, so it needs `manage_project_governance` like a change; it runs the
  checks as the caller, the person who would take the baseline.

Dependencies: `modules.traceability.profiles` (choices), `profile_resolution` (effects), `services.rbac` (gates).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.seams import ApproverRole
from app.modules.traceability import approval_policy, baseline_policy, profile_resolution, profiles, review_policy
from app.modules.traceability._shared import (
    APPROVAL_POLICIES,
    BASELINE_POLICIES,
    MANAGE_PROJECT_GOVERNANCE,
    REVIEW_POLICIES,
    TRACEABILITY_MODULE_KEY,
)
from app.modules.traceability.enums import ProfileMode, ProfileOutcome
from app.modules.traceability.models import GovernanceProfile
from app.modules.traceability.router import (
    baseline_check_options_out,
    baseline_fields_out,
    baseline_settings_out,
    baseline_types_out,
    review_settings_out,
)
from app.modules.traceability.schemas import (
    ApproverRoleOptionOut,
    ApproverRoleOut,
    BaselineFailureOut,
    BaselinePreviewOut,
    BaselineSettingsIn,
    ChoiceSet,
    EffectiveBaselineCheckOut,
    EffectiveBaselineFieldOut,
    EffectiveReviewOut,
    ProjectApprovalOut,
    ProjectApprovalRolesSet,
    ProjectApprovalTypeOut,
    ProjectBaselineOut,
    ProjectBaselineSet,
    ProjectProfileOut,
    ProjectProfilesOut,
    ProjectReviewOut,
    ProjectReviewSettingsSet,
    ProjectReviewTypeOut,
    RoleSourceOut,
)
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import approval_policy as core_approval
from app.services import baseline as core_baseline
from app.services.lookups import project_or_404
from app.services.principals import principal_out
from app.services.rbac import (
    get_effective_permissions,
    permission_satisfied,
    require_permission,
    require_project_module_enabled,
    require_project_subcomponent_enabled,
)

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{TRACEABILITY_MODULE_KEY}", tags=["traceability"])

_view = require_project_module_enabled(TRACEABILITY_MODULE_KEY)
_manage = require_permission(MANAGE_PROJECT_GOVERNANCE, server_admin_bypass=False)
_approval_view = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, APPROVAL_POLICIES)
_review_view = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, REVIEW_POLICIES)
_baseline_view = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, BASELINE_POLICIES)


def _response(db: Session, project: Project, user: User) -> ProjectProfilesOut:
    """The profiles that reach the project, Enforced first and then by name, with the caller's right to choose."""
    held = get_effective_permissions(db, user.id, project_id=project.id)
    states = [s for s in profile_resolution.project_profile_states(db, project) if s.outcome is not ProfileOutcome.NOT_TARGETED]
    tier = {ProfileMode.ENFORCED.value: 0, ProfileMode.DEFAULT.value: 1, ProfileMode.OPT_IN.value: 2}
    states.sort(key=lambda s: (tier[s.profile.mode], s.profile.name.casefold(), str(s.profile.id)))
    return ProjectProfilesOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_GOVERNANCE),
        profiles=[
            ProjectProfileOut(
                id=s.profile.id, name=s.profile.name, description=s.profile.description, mode=ProfileMode(s.profile.mode),
                outcome=s.outcome, applies=s.outcome.applies, choice=s.choice,
                can_choose=s.profile.mode != ProfileMode.ENFORCED.value,
            )
            for s in states
        ],
    )


@router.get("/profiles", response_model=ProjectProfilesOut)
def get_project_profiles(
    project_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ProjectProfilesOut:
    """The governance profiles that reach the project and what each does for it."""
    return _response(db, project_or_404(db, project_id), current_user)


@router.put("/profiles/{profile_id}/choice", response_model=ProjectProfilesOut, dependencies=[Depends(_view)])
def set_project_profile_choice(
    project_id: UUID, profile_id: UUID, payload: ChoiceSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProjectProfilesOut:
    """Opts the project out of a Default profile or in to an Opt-in profile, or clears its choice (`null`)."""
    project = project_or_404(db, project_id)
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None or profile.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found.")
    profiles.set_choice(db, profile=profile, project=project, opted_in=payload.opted_in, actor_id=current_user.id)
    db.commit()
    return _response(db, project, current_user)


def _approval_response(db: Session, project: Project, user: User) -> ProjectApprovalOut:
    """The project's approval policy for each record type, with the roles a policy may name."""
    held = get_effective_permissions(db, user.id, project_id=project.id)
    options = core_approval.role_options(db, project.organization_id)
    labels = {(o.role.kind, o.role.key): o.label for o in options}

    def outs(roles: list[ApproverRole]) -> list[ApproverRoleOut]:
        return [ApproverRoleOut(kind=r.kind, key=r.key, label=labels.get((r.kind, r.key), r.key)) for r in roles]

    return ProjectApprovalOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_GOVERNANCE),
        types=[
            ProjectApprovalTypeOut(
                artefact_type=p.gate.artefact_type, label=p.gate.label, module_key=p.gate.module_key,
                own=None if p.own is None else outs(p.own), inherited_from=p.inherited_from,
                effective=[RoleSourceOut(role=outs([e.role])[0], sources=list(e.sources)) for e in p.effective],
            )
            for p in approval_policy.project_policy(db, project)
        ],
        role_options=[
            ApproverRoleOptionOut(kind=o.role.kind, key=o.role.key, label=o.label, scope=o.scope) for o in options
        ],
    )


@router.get("/approval-policies", response_model=ProjectApprovalOut, dependencies=[Depends(_approval_view)])
def get_project_approval_policies(
    project_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ProjectApprovalOut:
    """The roles that may also approve each record type in the project, with where each comes from."""
    return _approval_response(db, project_or_404(db, project_id), current_user)


@router.put(
    "/approval-policies/{artefact_type}", response_model=ProjectApprovalOut, dependencies=[Depends(_approval_view)],
)
def set_project_approval_policy(
    project_id: UUID, artefact_type: str, payload: ProjectApprovalRolesSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProjectApprovalOut:
    """Sets the roles the project adds as approvers of one record type: a list (empty for none), or `null` to follow the
    nearest ancestor project."""
    project = project_or_404(db, project_id)
    approval_policy.set_project_roles(
        db, project=project, artefact_type=artefact_type,
        roles=None if payload.roles is None else [ApproverRole(kind=r.kind, key=r.key) for r in payload.roles],
        actor_id=current_user.id,
    )
    db.commit()
    return _approval_response(db, project, current_user)


def _review_response(db: Session, project: Project, user: User) -> ProjectReviewOut:
    """The project's review policy for each record type with a review schedule."""
    held = get_effective_permissions(db, user.id, project_id=project.id)

    def owner_out(owner: PrincipalRef | None) -> PrincipalOut | None:
        return None if owner is None else principal_out(db, owner.type.value, owner.id)

    return ProjectReviewOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_GOVERNANCE),
        types=[
            ProjectReviewTypeOut(
                artefact_type=p.review_type.artefact_type, label=p.review_type.label, module_key=p.review_type.module_key,
                own=None if p.own is None else review_settings_out(db, p.own), inherited_from=p.inherited_from,
                effective=EffectiveReviewOut(
                    interval_days=p.effective.interval_days, interval_source=p.effective.interval_source,
                    lead_days=p.effective.lead_days, lead_source=p.effective.lead_source,
                    default_owner=owner_out(p.effective.default_owner), owner_source=p.effective.owner_source,
                ),
            )
            for p in review_policy.project_policy(db, project)
        ],
    )


@router.get("/review-policies", response_model=ProjectReviewOut, dependencies=[Depends(_review_view)])
def get_project_review_policies(
    project_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ProjectReviewOut:
    """The review interval, reminder lead and default owner of each record type in the project, with where each comes from."""
    return _review_response(db, project_or_404(db, project_id), current_user)


@router.put("/review-policies/{artefact_type}", response_model=ProjectReviewOut, dependencies=[Depends(_review_view)])
def set_project_review_policy(
    project_id: UUID, artefact_type: str, payload: ProjectReviewSettingsSet,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProjectReviewOut:
    """Sets the review settings the project gives one record type: settings (none set for no policy here), or `null` to
    follow the nearest ancestor project."""
    project = project_or_404(db, project_id)
    given = payload.settings
    review_policy.set_project_settings(
        db, project=project, artefact_type=artefact_type,
        settings=None if given is None else review_policy.ReviewSettings(given.interval_days, given.lead_days, given.default_owner),
        actor_id=current_user.id,
    )
    db.commit()
    return _review_response(db, project, current_user)


def _baseline_response(db: Session, project: Project, user: User) -> ProjectBaselineOut:
    """The project's baseline policy: its own row, what applies with its sources, and what can be chosen."""
    held = get_effective_permissions(db, user.id, project_id=project.id)
    policy = baseline_policy.project_policy(db, project)
    fields = baseline_policy.field_options(db, project)
    labels = {(t, o.key): o.label for t, options in fields.items() for o in options}
    return ProjectBaselineOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_GOVERNANCE),
        own=None if policy.own is None else baseline_settings_out(policy.own), inherited_from=policy.inherited_from,
        checks=[
            EffectiveBaselineCheckOut(
                key=c.key, name=c.name, available=c.available, stage=c.stage, manual=c.manual, sources=list(c.sources),
            )
            for c in policy.checks
        ],
        required_fields=[
            EffectiveBaselineFieldOut(
                artefact_type=f.field.artefact_type, field_key=f.field.field_key,
                field_label=labels.get((f.field.artefact_type, f.field.field_key)), stage=f.stage, manual=f.manual,
                sources=list(f.sources),
            )
            for f in policy.required_fields
        ],
        notify_managers=policy.notify_managers,
        check_options=baseline_check_options_out(baseline_policy.check_options(db, project.organization_id)),
        types=baseline_types_out(baseline_policy.baseline_types(db, project.organization_id)),
        field_options=baseline_fields_out(fields),
    )


@router.get("/baseline-policy", response_model=ProjectBaselineOut, dependencies=[Depends(_baseline_view)])
def get_project_baseline_policy(
    project_id: UUID, current_user: User = Depends(_view), db: Session = Depends(get_db),
) -> ProjectBaselineOut:
    """The checks that run before the project's baselines and the fields it requires, with where each comes from."""
    return _baseline_response(db, project_or_404(db, project_id), current_user)


@router.put("/baseline-policy", response_model=ProjectBaselineOut, dependencies=[Depends(_baseline_view)])
def set_project_baseline_policy(
    project_id: UUID, payload: ProjectBaselineSet, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> ProjectBaselineOut:
    """Sets the project's own baseline policy: settings (no check for none), or `null` to follow the nearest ancestor."""
    project = project_or_404(db, project_id)
    given: BaselineSettingsIn | None = payload.settings
    baseline_policy.set_project_settings(
        db, project=project, actor_id=current_user.id,
        settings=None if given is None else baseline_policy.BaselineSettings(
            given.applies_to_stage, given.applies_to_manual, tuple(given.checks),
            tuple(baseline_policy.RequiredField(f.artefact_type, f.field_key) for f in given.required_fields),
            given.notify_managers,
        ),
    )
    db.commit()
    return _baseline_response(db, project, current_user)


@router.get("/baseline-checks", response_model=BaselinePreviewOut, dependencies=[Depends(_baseline_view)])
def preview_baseline_checks(
    project_id: UUID, kind: Literal["stage", "manual"], stage_id: UUID | None = None, component_id: UUID | None = None,
    current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> BaselinePreviewOut:
    """Runs the enabled checks against what a baseline taken now would hold and lists every failure, writing nothing.

    Args:
        project_id: The project.
        kind: `stage` (needs `stage_id`) or `manual`.
        stage_id: The stage whose baseline is previewed.
        component_id: A component's own baseline of the stage.

    Raises:
        HTTPException: 422 for a stage preview that names no stage of the project.
    """
    project = project_or_404(db, project_id)
    try:
        checks, failures = core_baseline.preview_checks(
            db, project, current_user, kind, stage_id=stage_id, component_id=component_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return BaselinePreviewOut(
        kind=kind, checks=[{"key": key, "name": provider.name} for key, provider in checks],
        failures=[
            BaselineFailureOut(
                check_key=f.check_key, check_name=f.check_name, artefact_type=f.artefact_type, artefact_id=f.artefact_id,
                code=f.code, message=f.message,
            )
            for f in failures
        ],
    )
