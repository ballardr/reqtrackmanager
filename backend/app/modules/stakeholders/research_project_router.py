"""
Module: modules.stakeholders.research_project_router

Project-scoped research-extras API, mounted beside the engagement
router: an engagement's session prompts, anonymous participants and findings,
and a finding's raised/answered links. Every route needs the `research_extras`
sub-component to be on for the project (404 otherwise), so turning it off hides
these while the engagement log keeps working. Reading needs project membership;
changes need the engagement manage gate (findings also accept a `(research_finding, manage)` grant).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _engagement_shared as es
from app.modules.stakeholders import _research_shared as rs
from app.modules.stakeholders.engagements import FINDING_ARTEFACT_TYPE, RESEARCH_SUBCOMPONENT
from app.modules.stakeholders.models import Engagement, ResearchFinding
from app.modules.stakeholders.schemas import (
    AnonymousParticipantCreate,
    AnonymousParticipantOut,
    AnonymousParticipantUpdate,
    FindingCreate,
    FindingOut,
    FindingUpdate,
    OutcomeCreate,
    OutcomeOut,
    PromptCreate,
    PromptMove,
    PromptOut,
    PromptUpdate,
)
from app.modules.stakeholders.service import STAKEHOLDERS_MODULE_KEY
from app.services.project_scope import ProjectScope
from app.services.rbac import require_project_subcomponent_enabled
from app.services.tags import TagFilter

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}", tags=["research-project"])

_require_view = require_project_subcomponent_enabled(STAKEHOLDERS_MODULE_KEY, RESEARCH_SUBCOMPONENT)


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _manage(db: Session, user: User, project_id: UUID, engagement_id: UUID) -> tuple[Project, Engagement]:
    """The project and engagement for a change, after the manage gate."""
    project = _project(db, project_id)
    engagement = es.get_engagement_in_project(db, project_id, engagement_id)
    es.require_engagement_manage(db, user, project)
    return project, engagement


def _finding_manage(db: Session, user: User, project_id: UUID, finding_id: UUID) -> tuple[Project, Engagement, ResearchFinding]:
    """The project, engagement and finding for a change to a finding, after the finding manage gate."""
    project = _project(db, project_id)
    finding = rs.get_finding_in_project(db, project_id, finding_id)
    es.require_finding_manage(db, user, project)
    return project, es.get_engagement_in_project(db, project_id, finding.engagement_id), finding


# --- Session prompts ----------------------------------------------------------


@router.get("/engagements/{engagement_id}/prompts", response_model=list[PromptOut])
def list_prompts(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return rs.list_prompts(db, es.get_engagement_in_project(db, project_id, engagement_id))


@router.post("/engagements/{engagement_id}/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
def add_prompt(
    project_id: UUID, engagement_id: UUID, payload: PromptCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    return rs.add_prompt(db, engagement, payload, current_user, project)


@router.patch("/engagements/{engagement_id}/prompts/{prompt_id}", response_model=PromptOut)
def update_prompt(
    project_id: UUID, engagement_id: UUID, prompt_id: UUID, payload: PromptUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    return rs.update_prompt(db, engagement, prompt_id, payload, current_user, project)


@router.post("/engagements/{engagement_id}/prompts/{prompt_id}/move", response_model=list[PromptOut])
def move_prompt(
    project_id: UUID, engagement_id: UUID, prompt_id: UUID, payload: PromptMove,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    return rs.move_prompt(db, engagement, prompt_id, payload.direction, current_user, project)


@router.delete("/engagements/{engagement_id}/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    project_id: UUID, engagement_id: UUID, prompt_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    rs.delete_prompt(db, engagement, prompt_id, current_user, project)


# --- Anonymous participants ---------------------------------------------------


@router.get("/engagements/{engagement_id}/anonymous-participants", response_model=list[AnonymousParticipantOut])
def list_anonymous_participants(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return rs.list_anonymous(db, es.get_engagement_in_project(db, project_id, engagement_id))


@router.post(
    "/engagements/{engagement_id}/anonymous-participants", response_model=AnonymousParticipantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_anonymous_participant(
    project_id: UUID, engagement_id: UUID, payload: AnonymousParticipantCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a participant who has no Stakeholder record: a label plus, optionally, the Persona they represent."""
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    return rs.add_anonymous(db, engagement, payload, current_user, project)


@router.patch(
    "/engagements/{engagement_id}/anonymous-participants/{participant_id}", response_model=AnonymousParticipantOut
)
def update_anonymous_participant(
    project_id: UUID, engagement_id: UUID, participant_id: UUID, payload: AnonymousParticipantUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    return rs.update_anonymous(db, engagement, participant_id, payload, current_user, project)


@router.delete(
    "/engagements/{engagement_id}/anonymous-participants/{participant_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_anonymous_participant(
    project_id: UUID, engagement_id: UUID, participant_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement = _manage(db, current_user, project_id, engagement_id)
    rs.delete_anonymous(db, engagement, participant_id, current_user, project)


# --- Findings -----------------------------------------------------------------


@router.get("/findings", response_model=list[FindingOut])
def list_project_findings(
    project_id: UUID, tag_filter: TagFilter = Depends(), current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
    project_scope: ProjectScope = Depends(),
):
    """Every finding in the project, newest first."""

    def rows_for(pid: UUID) -> list:
        """This endpoint's rows for one project of the scope."""
        _project(db, pid)
        rows = db.scalars(
            select(ResearchFinding).where(ResearchFinding.project_id == pid).order_by(ResearchFinding.created_at.desc())
        ).all()
        return [rs.finding_to_out(f) for f in tag_filter.keep(db, pid, FINDING_ARTEFACT_TYPE, rows)]

    return project_scope.collect(
        db, db.get(Project, project_id), current_user.id, FINDING_ARTEFACT_TYPE, rows_for,
        gate=(STAKEHOLDERS_MODULE_KEY, RESEARCH_SUBCOMPONENT),
    )


@router.get("/engagements/{engagement_id}/findings", response_model=list[FindingOut])
def list_findings(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return rs.list_findings(db, es.get_engagement_in_project(db, project_id, engagement_id))


@router.post("/engagements/{engagement_id}/findings", response_model=FindingOut, status_code=status.HTTP_201_CREATED)
def add_finding(
    project_id: UUID, engagement_id: UUID, payload: FindingCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = es.get_engagement_in_project(db, project_id, engagement_id)
    es.require_finding_manage(db, current_user, project)
    return rs.add_finding(db, engagement, payload, current_user, project)


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(
    project_id: UUID, finding_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return rs.finding_to_out(rs.get_finding_in_project(db, project_id, finding_id))


@router.put("/findings/{finding_id}", response_model=FindingOut)
def update_finding(
    project_id: UUID, finding_id: UUID, payload: FindingUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, _engagement, finding = _finding_manage(db, current_user, project_id, finding_id)
    return rs.update_finding(db, finding, payload, current_user, project)


@router.delete("/findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finding(
    project_id: UUID, finding_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    project, _engagement, finding = _finding_manage(db, current_user, project_id, finding_id)
    rs.delete_finding(db, finding, current_user, project)


@router.get("/findings/{finding_id}/outcomes", response_model=list[OutcomeOut])
def list_finding_outcomes(
    project_id: UUID, finding_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    """The Pain Points, Needs and Open Questions this finding raised or answered."""
    project = _project(db, project_id)
    finding = rs.get_finding_in_project(db, project_id, finding_id)
    return es.list_outcomes(db, FINDING_ARTEFACT_TYPE, finding.id, project)


@router.post("/findings/{finding_id}/outcomes", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def add_finding_outcome(
    project_id: UUID, finding_id: UUID, payload: OutcomeCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement, finding = _finding_manage(db, current_user, project_id, finding_id)
    return es.add_outcome(db, engagement, FINDING_ARTEFACT_TYPE, finding.id, payload, current_user, project)


@router.delete("/findings/{finding_id}/outcomes/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_finding_outcome(
    project_id: UUID, finding_id: UUID, link_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project, engagement, finding = _finding_manage(db, current_user, project_id, finding_id)
    es.remove_outcome(db, engagement, FINDING_ARTEFACT_TYPE, finding.id, link_id, current_user, project)
