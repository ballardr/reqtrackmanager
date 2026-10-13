"""
Module: modules.stakeholders.engagement_project_router

Project-scoped Engagement API (Phase 4), mounted at
`/api/v1/projects/{project_id}/modules/stakeholders` beside the other project
routers: the engagement log (CRUD and hard delete), its participants, covered
personas, audience groups, the Pain Points / Needs / Open Questions it raised or
answered, comments and files, and a Stakeholder's engagement timeline.

The log is always on: it needs the module enabled for the project, not a
sub-component (the research extras live in `research_project_router.py`).
RBAC: any project member can read; `_engagement_shared.require_engagement_manage`
gates every change. An engagement's files resolve through
`engagements.resolve_engagement_file_project_id`.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import _engagement_shared as es
from app.modules.stakeholders._shared import get_visible_stakeholder
from app.modules.stakeholders.engagements import ENGAGEMENT_ARTEFACT_TYPE
from app.modules.stakeholders.enums import EngagementChannel
from app.modules.stakeholders.models import Engagement
from app.modules.stakeholders.schemas import (
    EngagementAudienceAdded,
    EngagementAudienceCreate,
    EngagementAudienceOut,
    EngagementCommentCreate,
    EngagementCommentOut,
    EngagementCommentUpdate,
    EngagementCreate,
    EngagementOut,
    EngagementParticipantCreate,
    EngagementParticipantOut,
    EngagementPersonaCreate,
    EngagementPersonaOut,
    EngagementUpdate,
    OutcomeCreate,
    OutcomeOut,
    StakeholderEngagementOut,
)
from app.modules.stakeholders.service import STAKEHOLDERS_MODULE_KEY
from app.schemas.file import FileAssetOut
from app.services.rbac import require_project_module_enabled

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}", tags=["engagements-project"])

_require_view = require_project_module_enabled(STAKEHOLDERS_MODULE_KEY)


def _project(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, engagement_id: UUID) -> Engagement:
    return es.get_engagement_in_project(db, project_id, engagement_id)


# --- Engagement CRUD ----------------------------------------------------------


@router.post("/engagements", response_model=EngagementOut, status_code=status.HTTP_201_CREATED)
def create_engagement(
    project_id: UUID, payload: EngagementCreate, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Logs an engagement, optionally with its participants, covered personas and audience groups.
    Requires the Engagement Owner role (or FGAC grant)."""
    project = _project(db, project_id)
    es.require_engagement_manage(db, current_user, project)
    return es.create_engagement_from_payload(db, payload, current_user, project)


@router.get("/engagements", response_model=list[EngagementOut])
def list_engagements(
    project_id: UUID, channel: EngagementChannel | None = None, stakeholder_id: UUID | None = None,
    persona_id: UUID | None = None, date_from: date | None = None, date_to: date | None = None,
    retention_due: bool | None = None, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The project's engagements, most recent first. Filters combine: channel, a participant Stakeholder, a
    covered Persona, a date range, and whether the retain-until date has been reached."""
    project = _project(db, project_id)
    return es.list_engagements(
        db, project, channel=channel.value if channel else None, stakeholder_id=stakeholder_id, persona_id=persona_id,
        date_from=date_from, date_to=date_to, retention_due=retention_due,
    )


@router.get("/engagements/{engagement_id}", response_model=EngagementOut)
def get_engagement(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    project = _project(db, project_id)
    return es.engagement_to_out(db, _get(db, project_id, engagement_id), project)


@router.put("/engagements/{engagement_id}", response_model=EngagementOut)
def update_engagement(
    project_id: UUID, engagement_id: UUID, payload: EngagementUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return es.update_engagement_from_payload(db, engagement, payload, current_user, project)


@router.delete("/engagements/{engagement_id}", status_code=status.HTTP_204_NO_CONTENT)
def erase_engagement(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    """Permanently deletes the engagement, its notes, participants data, findings, comments and files.
    Irreversible; the UI asks for a two-tier confirmation first."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.erase(db, engagement, current_user)


@router.get("/stakeholders/{stakeholder_id}/engagements", response_model=list[StakeholderEngagementOut])
def list_stakeholder_engagements(
    project_id: UUID, stakeholder_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    """The project's engagements a visible Stakeholder took part in, most recent first (their timeline)."""
    project = _project(db, project_id)
    return es.stakeholder_timeline(db, project, get_visible_stakeholder(db, project, stakeholder_id))


# --- Participants -------------------------------------------------------------


@router.get("/engagements/{engagement_id}/participants", response_model=list[EngagementParticipantOut])
def list_participants(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    project = _project(db, project_id)
    return es.list_participants(db, _get(db, project_id, engagement_id), project)


@router.post(
    "/engagements/{engagement_id}/participants", response_model=EngagementParticipantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    project_id: UUID, engagement_id: UUID, payload: EngagementParticipantCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a Stakeholder this project can see as a participant (409 on a duplicate)."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return es.add_participant(db, engagement, payload.stakeholder_id, current_user, project)


@router.delete("/engagements/{engagement_id}/participants/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_participant(
    project_id: UUID, engagement_id: UUID, stakeholder_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.remove_participant(db, engagement, stakeholder_id, current_user, project)


# --- Personas covered ---------------------------------------------------------


@router.get("/engagements/{engagement_id}/personas", response_model=list[EngagementPersonaOut])
def list_personas(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    project = _project(db, project_id)
    return es.list_personas(db, _get(db, project_id, engagement_id), project)


@router.post(
    "/engagements/{engagement_id}/personas", response_model=EngagementPersonaOut, status_code=status.HTTP_201_CREATED
)
def add_persona(
    project_id: UUID, engagement_id: UUID, payload: EngagementPersonaCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records a Persona this project can see as covered (409 on a duplicate)."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return es.add_persona(db, engagement, payload.persona_id, current_user, project)


@router.delete("/engagements/{engagement_id}/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_persona(
    project_id: UUID, engagement_id: UUID, persona_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.remove_persona(db, engagement, persona_id, current_user, project)


# --- Audience groups ----------------------------------------------------------


@router.get("/engagements/{engagement_id}/audiences", response_model=list[EngagementAudienceOut])
def list_audiences(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    project = _project(db, project_id)
    return es.list_audiences(db, _get(db, project_id, engagement_id), project)


@router.post(
    "/engagements/{engagement_id}/audiences", response_model=EngagementAudienceAdded,
    status_code=status.HTTP_201_CREATED,
)
def add_audience(
    project_id: UUID, engagement_id: UUID, payload: EngagementAudienceCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Aims the engagement at a Stakeholder group and adds the group's current members as participants, as a
    snapshot (existing participants are kept; 409 if the group is already an audience)."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return es.add_audience(db, engagement, payload.group_id, current_user, project)


@router.delete("/engagements/{engagement_id}/audiences/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_audience(
    project_id: UUID, engagement_id: UUID, group_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes the audience link only; the participants it added stay."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.remove_audience(db, engagement, group_id, current_user, project)


# --- Raised / answered --------------------------------------------------------


@router.get("/engagements/{engagement_id}/outcomes", response_model=list[OutcomeOut])
def list_outcomes(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    """The Pain Points, Needs and Open Questions this engagement raised or answered."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    return es.list_outcomes(db, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, project)


@router.post("/engagements/{engagement_id}/outcomes", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def add_outcome(
    project_id: UUID, engagement_id: UUID, payload: OutcomeCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records that the engagement raised (Pain Point, Need or Open Question) or answered (Open Question) a record
    of this project."""
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return es.add_outcome(db, engagement, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, payload, current_user, project)


@router.delete("/engagements/{engagement_id}/outcomes/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_outcome(
    project_id: UUID, engagement_id: UUID, link_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.remove_outcome(db, engagement, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, link_id, current_user, project)


# --- Comments -----------------------------------------------------------------


@router.post(
    "/engagements/{engagement_id}/comments", response_model=EngagementCommentOut, status_code=status.HTTP_201_CREATED
)
def add_engagement_comment(
    project_id: UUID, engagement_id: UUID, payload: EngagementCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return es.add_comment(db, _get(db, project_id, engagement_id), current_user, payload.body, project_id=project_id)


@router.get("/engagements/{engagement_id}/comments", response_model=list[EngagementCommentOut])
def list_engagement_comments(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return es.list_comments(db, _get(db, project_id, engagement_id))


@router.patch("/engagements/{engagement_id}/comments/{comment_id}", response_model=EngagementCommentOut)
def edit_engagement_comment(
    project_id: UUID, engagement_id: UUID, comment_id: UUID, payload: EngagementCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    return es.edit_comment(
        db, _get(db, project_id, engagement_id), comment_id, current_user, payload.body, project_id=project_id
    )


@router.post(
    "/engagements/{engagement_id}/comments/{comment_id}/files", response_model=FileAssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_engagement_comment_attachment(
    project_id: UUID, engagement_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    return await es.attach_to_comment(
        db, _get(db, project_id, engagement_id), comment_id, current_user, file,
        organization_id=project.organization_id, project_id=project_id,
    )


@router.delete(
    "/engagements/{engagement_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_engagement_comment_attachment(
    project_id: UUID, engagement_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    _project(db, project_id)
    es.remove_comment_attachment(
        db, _get(db, project_id, engagement_id), comment_id, file_id, current_user, project_id=project_id
    )


# --- Direct files -------------------------------------------------------------


@router.post("/engagements/{engagement_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_engagement_file(
    project_id: UUID, engagement_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    return await es.attach_file(
        db, engagement, current_user, file, organization_id=project.organization_id, project_id=project_id
    )


@router.get("/engagements/{engagement_id}/files", response_model=list[FileAssetOut])
def list_engagement_files(
    project_id: UUID, engagement_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)
):
    _project(db, project_id)
    return es.list_files(db, _get(db, project_id, engagement_id))


@router.delete("/engagements/{engagement_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_engagement_file(
    project_id: UUID, engagement_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    project = _project(db, project_id)
    engagement = _get(db, project_id, engagement_id)
    es.require_engagement_manage(db, current_user, project)
    es.unlink_file(db, engagement, file_id, current_user, project_id=project_id)
