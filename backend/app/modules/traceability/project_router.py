"""
Module: modules.traceability.project_router

Project-scoped API of governance profiles, mounted at `/api/v1/projects/{project_id}/modules/traceability`: which
profiles reach the project and what each does for it, and the project's opt-out of a Default profile or opt-in to an
Opt-in profile.

Design decisions:
- Reading is open to every member of a project the module is on for, because a person asking why a policy applies needs
  the answer; changing a choice needs `manage_project_governance` with no server-administrator bypass.
- A project sees only the profiles that reach it; a profile that does not is not listed, so the organisation's other
  profiles are not disclosed.
- An Enforced profile is listed with its outcome (`enforced` or `exempt`) and no choice: only the organisation lifts it.

Dependencies: `modules.traceability.profiles` (choices), `profile_resolution` (effects), `services.rbac` (gates).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.traceability import profile_resolution, profiles
from app.modules.traceability._shared import MANAGE_PROJECT_GOVERNANCE, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import ProfileMode, ProfileOutcome
from app.modules.traceability.models import GovernanceProfile
from app.modules.traceability.schemas import ChoiceSet, ProjectProfileOut, ProjectProfilesOut
from app.services.lookups import project_or_404
from app.services.rbac import (
    get_effective_permissions,
    permission_satisfied,
    require_permission,
    require_project_module_enabled,
)

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{TRACEABILITY_MODULE_KEY}", tags=["traceability"])

_view = require_project_module_enabled(TRACEABILITY_MODULE_KEY)
_manage = require_permission(MANAGE_PROJECT_GOVERNANCE, server_admin_bypass=False)


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
