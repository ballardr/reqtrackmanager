"""
Module: modules.stakeholders._research_shared

Handler bodies behind the research-extras routes (`research_project_router.py`):
session prompts, anonymous participants and findings of an Engagement
(Phase 4, Phase 0 addendum 2 item 19 and 20). The routes are gated by the
`research_extras` sub-component, so a project that has it off still has the full
engagement log.

RBAC and tenancy are the engagement's (`_engagement_shared`): every write needs
`require_engagement_manage`, and an item is only reachable through an engagement
of the request's project. Audit events carry ids only, since prompts, labels and
findings can quote participants.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import engagements as eng
from app.modules.stakeholders._engagement_shared import log
from app.modules.stakeholders._shared import get_visible_persona
from app.modules.stakeholders.engagements import FINDING_ARTEFACT_TYPE
from app.modules.stakeholders.models import (
    Engagement,
    EngagementAnonymousParticipant,
    EngagementPrompt,
    ResearchFinding,
)
from app.modules.stakeholders.schemas import (
    AnonymousParticipantCreate,
    AnonymousParticipantOut,
    AnonymousParticipantUpdate,
    FindingCreate,
    FindingOut,
    FindingUpdate,
    PromptCreate,
    PromptOut,
    PromptUpdate,
)
from app.modules.stakeholders.service import get_current_persona_version
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.relationships import delete_link, get_all_links


def _not_found(noun: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{noun} not found.")


# --- Session prompts ------------------------------------------------------------


def prompt_to_out(prompt: EngagementPrompt) -> PromptOut:
    return PromptOut(
        id=prompt.id, engagement_id=prompt.engagement_id, sort_order=prompt.sort_order, prompt=prompt.prompt,
        response_notes=prompt.response_notes,
    )


def list_prompts(db: Session, engagement: Engagement) -> list[PromptOut]:
    """The engagement's session prompts in order."""
    return [prompt_to_out(p) for p in eng.list_prompts(db, engagement.id)]


def _get_prompt(db: Session, engagement: Engagement, prompt_id: uuid.UUID) -> EngagementPrompt:
    prompt = db.get(EngagementPrompt, prompt_id)
    if prompt is None or prompt.engagement_id != engagement.id:
        raise _not_found("Prompt")
    return prompt


def add_prompt(db: Session, engagement: Engagement, payload: PromptCreate, actor: User, project: Project) -> PromptOut:
    """Appends a session prompt, audit-logs and commits."""
    prompt = EngagementPrompt(
        engagement_id=engagement.id, sort_order=eng.next_prompt_order(db, engagement.id), prompt=payload.prompt,
        response_notes=payload.response_notes,
    )
    db.add(prompt)
    db.flush()
    log(db, engagement.id, actor, project.id, "prompt_added", prompt_id=prompt.id)
    db.commit()
    return prompt_to_out(prompt)


def update_prompt(
    db: Session, engagement: Engagement, prompt_id: uuid.UUID, payload: PromptUpdate, actor: User, project: Project
) -> PromptOut:
    """Edits a prompt's text or response notes (only fields present change), audit-logs and commits."""
    prompt = _get_prompt(db, engagement, prompt_id)
    sent = payload.model_dump(exclude_unset=True)
    if "prompt" in sent and sent["prompt"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A prompt cannot be empty.")
    if "response_notes" in sent:
        prompt.response_notes = sent["response_notes"] or ""
    if "prompt" in sent:
        prompt.prompt = sent["prompt"]
    log(db, engagement.id, actor, project.id, "prompt_updated", prompt_id=prompt.id)
    db.commit()
    return prompt_to_out(prompt)


def move_prompt(
    db: Session, engagement: Engagement, prompt_id: uuid.UUID, direction: str, actor: User, project: Project
) -> list[PromptOut]:
    """Moves a prompt one place up or down (a no-op at the end), audit-logs and returns the new order."""
    _get_prompt(db, engagement, prompt_id)
    move_ordered(db, EngagementPrompt, [EngagementPrompt.engagement_id == engagement.id], prompt_id, direction)
    log(db, engagement.id, actor, project.id, "prompt_moved", prompt_id=prompt_id)
    db.commit()
    return list_prompts(db, engagement)


def delete_prompt(db: Session, engagement: Engagement, prompt_id: uuid.UUID, actor: User, project: Project) -> None:
    """Deletes a prompt and its response notes, audit-logs and commits."""
    prompt = _get_prompt(db, engagement, prompt_id)
    db.delete(prompt)
    log(db, engagement.id, actor, project.id, "prompt_deleted", prompt_id=prompt_id)
    db.commit()


# --- Anonymous participants -----------------------------------------------------


def participant_to_out(db: Session, participant: EngagementAnonymousParticipant) -> AnonymousParticipantOut:
    persona_name = None
    if participant.persona_id is not None:
        persona_name = get_current_persona_version(db, participant.persona_id).name
    return AnonymousParticipantOut(
        id=participant.id, engagement_id=participant.engagement_id, label=participant.label,
        persona_id=participant.persona_id, persona_name=persona_name,
    )


def list_anonymous(db: Session, engagement: Engagement) -> list[AnonymousParticipantOut]:
    """The engagement's anonymous participants."""
    return [participant_to_out(db, p) for p in eng.list_anonymous_participants(db, engagement.id)]


def _get_anonymous(db: Session, engagement: Engagement, participant_id: uuid.UUID) -> EngagementAnonymousParticipant:
    participant = db.get(EngagementAnonymousParticipant, participant_id)
    if participant is None or participant.engagement_id != engagement.id:
        raise _not_found("Participant")
    return participant


def add_anonymous(
    db: Session, engagement: Engagement, payload: AnonymousParticipantCreate, actor: User, project: Project
) -> AnonymousParticipantOut:
    """Adds an anonymous participant (a label and, optionally, a Persona the project can see), audit-logs and commits."""
    if payload.persona_id is not None:
        get_visible_persona(db, project, payload.persona_id)
    participant = EngagementAnonymousParticipant(
        engagement_id=engagement.id, label=payload.label.strip(), persona_id=payload.persona_id
    )
    db.add(participant)
    db.flush()
    log(db, engagement.id, actor, project.id, "anonymous_participant_added", participant_id=participant.id)
    db.commit()
    return participant_to_out(db, participant)


def update_anonymous(
    db: Session, engagement: Engagement, participant_id: uuid.UUID, payload: AnonymousParticipantUpdate, actor: User,
    project: Project,
) -> AnonymousParticipantOut:
    """Relabels or re-assigns an anonymous participant (only fields present change; `persona_id: null` clears
    the persona), audit-logs and commits."""
    participant = _get_anonymous(db, engagement, participant_id)
    sent = payload.model_dump(exclude_unset=True)
    if "label" in sent:
        if sent["label"] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A participant label cannot be empty.")
        participant.label = sent["label"].strip()
    if "persona_id" in sent:
        if sent["persona_id"] is not None:
            get_visible_persona(db, project, sent["persona_id"])
        participant.persona_id = sent["persona_id"]
    log(db, engagement.id, actor, project.id, "anonymous_participant_updated", participant_id=participant.id)
    db.commit()
    return participant_to_out(db, participant)


def delete_anonymous(
    db: Session, engagement: Engagement, participant_id: uuid.UUID, actor: User, project: Project
) -> None:
    """Removes an anonymous participant, audit-logs and commits."""
    db.delete(_get_anonymous(db, engagement, participant_id))
    log(db, engagement.id, actor, project.id, "anonymous_participant_deleted", participant_id=participant_id)
    db.commit()


# --- Findings -------------------------------------------------------------------


def finding_to_out(finding: ResearchFinding) -> FindingOut:
    return FindingOut(
        id=finding.id, project_id=finding.project_id, engagement_id=finding.engagement_id,
        creator_id=finding.creator_id, title=finding.title, description=finding.description,
        created_at=finding.created_at, updated_at=finding.updated_at,
    )


def list_findings(db: Session, engagement: Engagement) -> list[FindingOut]:
    """The engagement's findings, oldest first."""
    return [finding_to_out(f) for f in eng.list_findings(db, engagement.id)]


def get_finding(db: Session, engagement: Engagement, finding_id: uuid.UUID) -> ResearchFinding:
    """A finding of this engagement, else 404 (so another engagement's or project's ids look absent)."""
    finding = db.get(ResearchFinding, finding_id)
    if finding is None or finding.engagement_id != engagement.id:
        raise _not_found("Finding")
    return finding


def get_finding_in_project(db: Session, project_id: uuid.UUID, finding_id: uuid.UUID) -> ResearchFinding:
    """A finding of this project, else 404."""
    finding = db.get(ResearchFinding, finding_id)
    if finding is None or finding.project_id != project_id:
        raise _not_found("Finding")
    return finding


def add_finding(
    db: Session, engagement: Engagement, payload: FindingCreate, actor: User, project: Project
) -> FindingOut:
    """Records a finding on the engagement, audit-logs and commits."""
    finding = ResearchFinding(
        project_id=project.id, engagement_id=engagement.id, creator_id=actor.id, title=payload.title,
        description=payload.description,
    )
    db.add(finding)
    db.flush()
    log_event(
        db, entity_type=FINDING_ARTEFACT_TYPE, entity_id=finding.id, action="created", actor_id=actor.id,
        project_id=project.id, detail={"engagement_id": str(engagement.id)},
    )
    db.commit()
    return finding_to_out(finding)


def update_finding(
    db: Session, finding: ResearchFinding, payload: FindingUpdate, actor: User, project: Project
) -> FindingOut:
    """Edits a finding (only fields present change), audit-logs and commits."""
    sent = payload.model_dump(exclude_unset=True)
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A finding title cannot be null.")
    if "title" in sent:
        finding.title = sent["title"]
    if "description" in sent:
        finding.description = sent["description"] or ""
    log_event(
        db, entity_type=FINDING_ARTEFACT_TYPE, entity_id=finding.id, action="updated", actor_id=actor.id,
        project_id=project.id,
    )
    db.commit()
    return finding_to_out(finding)


def delete_finding(db: Session, finding: ResearchFinding, actor: User, project: Project) -> None:
    """Deletes a finding and every link it has, audit-logs and commits."""
    for link in get_all_links(db, FINDING_ARTEFACT_TYPE, finding.id, include_cross_project=True):
        delete_link(db, link)
    finding_id = finding.id
    db.delete(finding)
    log_event(
        db, entity_type=FINDING_ARTEFACT_TYPE, entity_id=finding_id, action="deleted", actor_id=actor.id,
        project_id=project.id,
    )
    db.commit()
