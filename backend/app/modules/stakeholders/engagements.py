"""
Module: modules.stakeholders.engagements

Business logic for Engagements, the contact log, and the research extras
(Phase 4; docs/plans/module-02-stakeholders-and-personas-plan.md, Phase 0
addenda 14, 15, 20, 29).

Responsibilities:
- Engagement create/update (a single row, no version history) and the retention
  read-out (`retention_due`).
- Participants: Stakeholders, personas covered and an audience group, all
  `ArtefactLink`s from the engagement. A group is expanded to its members by the
  caller and recorded as a snapshot, so an engagement keeps saying who it
  involved after membership changes (addendum 29).
- Outcome links: an engagement or finding "raised" Pain Points, Needs and Open
  Questions, or "answered" Open Questions.
- Research extras: session prompts, anonymous participants, findings.
- `last_engaged_by_stakeholder`, the derived "last engaged" S4 staleness reads.
- `erase_engagement`, the hard delete of an engagement, its participant data and
  its files (Phase 0 resolution 15).

Design decisions:
- Link types are created per organisation on first use (`service.get_or_create_link_type`),
  like the other Stakeholder relationships, and declared in `LINK_TYPE_SEEDS`.
- Everything here raises `ValueError` for a rule violation; callers translate it to HTTP.
- "Last engaged" counts only engagements dated today or earlier, and only this
  project's, so a shared org Stakeholder never leaks another project's contact history.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.file import FileAsset
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.user import User
from app.modules.stakeholders.groups import GROUP_ARTEFACT_TYPE
from app.modules.stakeholders.models import (
    Engagement,
    EngagementAnonymousParticipant,
    EngagementComment,
    EngagementCommentFile,
    EngagementFacilitator,
    EngagementFile,
    EngagementPrompt,
    ResearchFinding,
)
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    get_or_create_link_type,
    hidden_stakeholder_ids,
    link_type_id_if_exists,
)
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.files import delete_file
from app.services.relationships import create_link, delete_link, get_all_links, get_link_between

ENGAGEMENT_ARTEFACT_TYPE = "engagement"
FINDING_ARTEFACT_TYPE = "research_finding"
RESEARCH_SUBCOMPONENT = "research_extras"

PAIN_POINT_TYPE = "pain_point"
OPEN_QUESTION_TYPE = "open_question"

PARTICIPANT_FORWARD, PARTICIPANT_REVERSE = "Has participant", "Participated in"
COVERS_FORWARD, COVERS_REVERSE = "Covers persona", "Is covered in"
AUDIENCE_FORWARD, AUDIENCE_REVERSE = "Is aimed at", "Is the audience of"

ENGAGEMENT_CONTENT_FIELDS: tuple[str, ...] = (
    "title", "channel", "engagement_date", "purpose", "summary", "notes", "consent_recorded", "retain_until",
)


@dataclass(frozen=True)
class OutcomeKind:
    """One way an engagement or finding relates to a Pain Point, Need or Open Question.

    Attributes:
        key: Stable API identifier (`raised`, `answered`).
        forward: Org link type forward phrase (engagement/finding -> target).
        reverse: Its reverse phrase (target -> engagement/finding).
        target_types: Artefact types that may be the target.
    """

    key: str
    forward: str
    reverse: str
    target_types: tuple[str, ...]


OUTCOME_KINDS: tuple[OutcomeKind, ...] = (
    OutcomeKind("raised", "Raised", "Was raised by", (PAIN_POINT_TYPE, NEED_ARTEFACT_TYPE, OPEN_QUESTION_TYPE)),
    OutcomeKind("answered", "Answered", "Was answered by", (OPEN_QUESTION_TYPE,)),
)
OUTCOME_HOLDER_TYPES = (ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE)
_OUTCOME_BY_KEY = {k.key: k for k in OUTCOME_KINDS}


def get_outcome_kind(key: str) -> OutcomeKind | None:
    """The declared outcome kind with this key, or `None`."""
    return _OUTCOME_BY_KEY.get(key)


# --- Engagement ----------------------------------------------------------------


def create_engagement(db: Session, *, project_id: uuid.UUID, creator: User, **content: Any) -> Engagement:
    """Creates an engagement.

    Args:
        project_id: The owning project.
        creator: The acting user (who logged it).
        **content: Any `ENGAGEMENT_CONTENT_FIELDS`; `title`, `channel` and `engagement_date` are required.
    """
    content = {k: v for k, v in content.items() if k in ENGAGEMENT_CONTENT_FIELDS}
    engagement = Engagement(project_id=project_id, creator_id=creator.id, **content)
    db.add(engagement)
    db.flush()
    return engagement


def update_engagement(db: Session, engagement: Engagement, changes: dict[str, Any]) -> Engagement:
    """Applies `changes` in place. A key present is applied even when `None`, so the retain-until date can be
    cleared; absent keys are untouched. Facilitators are set with `set_facilitators`."""
    for key, value in changes.items():
        if key in ENGAGEMENT_CONTENT_FIELDS:
            setattr(engagement, key, value)
    db.flush()
    return engagement


def list_facilitators(db: Session, engagement_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[PrincipalRef]]:
    """Each engagement's facilitators in the order they were added (an engagement with none is absent)."""
    result: dict[uuid.UUID, list[PrincipalRef]] = {}
    if not engagement_ids:
        return result
    rows = db.scalars(
        select(EngagementFacilitator).where(EngagementFacilitator.engagement_id.in_(list(engagement_ids)))
        .order_by(EngagementFacilitator.sort_order, EngagementFacilitator.created_at, EngagementFacilitator.id)
    ).all()
    for row in rows:
        result.setdefault(row.engagement_id, []).append(PrincipalRef(type=PrincipalType(row.facilitator_type), id=row.facilitator_id))
    return result


def set_facilitators(db: Session, engagement: Engagement, facilitators: Sequence[PrincipalRef]) -> None:
    """Replaces the engagement's facilitators with `facilitators`, in that order (duplicates collapse).
    The caller has validated every principal."""
    wanted = list(dict.fromkeys((f.type.value, f.id) for f in facilitators))
    existing = {
        (row.facilitator_type, row.facilitator_id): row
        for row in db.scalars(select(EngagementFacilitator).where(EngagementFacilitator.engagement_id == engagement.id))
    }
    for key, row in existing.items():
        if key not in wanted:
            db.delete(row)
    for position, (kind, principal_id) in enumerate(wanted):
        if (kind, principal_id) in existing:
            existing[(kind, principal_id)].sort_order = position
        else:
            db.add(EngagementFacilitator(
                engagement_id=engagement.id, sort_order=position, facilitator_type=kind, facilitator_id=principal_id,
            ))
    db.flush()


def retention_due(engagement: Engagement, today: date | None = None) -> bool:
    """Whether the engagement has reached its retain-until date and is due for review or disposal."""
    return engagement.retain_until is not None and engagement.retain_until <= (today or datetime.now(UTC).date())


def list_project_engagements(db: Session, project_id: uuid.UUID) -> list[Engagement]:
    """The project's engagements, most recent first."""
    return list(db.scalars(
        select(Engagement).where(Engagement.project_id == project_id)
        .order_by(Engagement.engagement_date.desc(), Engagement.created_at.desc())
    ).all())


# --- Participants, personas covered, audience ----------------------------------


def _add_link(
    db: Session, engagement: Engagement, target_type: str, target_id: uuid.UUID, forward: str, reverse: str,
    actor: User, *, organization_id: uuid.UUID, duplicate_message: str, source_type: str = ENGAGEMENT_ARTEFACT_TYPE,
    source_id: uuid.UUID | None = None,
) -> ArtefactLink:
    """Creates `source -> target` under the org link type `forward`; the caller has authorised both ends.

    Raises:
        ValueError: If the link already exists.
    """
    link_type = get_or_create_link_type(db, organization_id, forward, reverse)
    source_id = source_id or engagement.id
    if get_link_between(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type_id=link_type.id,
    ) is not None:
        raise ValueError(duplicate_message)
    return create_link(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type_id=link_type.id, created_by=actor.id, project_id=engagement.project_id,
    )


def _outgoing(
    db: Session, source_type: str, source_id: uuid.UUID, organization_id: uuid.UUID, forward: str, target_type: str
) -> list[ArtefactLink]:
    """The links from the source made under link type `forward` to `target_type` (none if the type is unused)."""
    type_id = link_type_id_if_exists(db, organization_id, forward)
    if type_id is None:
        return []
    return [
        link for link in get_all_links(db, source_type, source_id)
        if link.source_id == source_id and link.source_type == source_type and link.target_type == target_type
        and link.link_type_id == type_id
    ]


def add_participant(
    db: Session, engagement: Engagement, stakeholder_id: uuid.UUID, actor: User, *, organization_id: uuid.UUID
) -> ArtefactLink:
    """Records that a Stakeholder took part (the caller has checked the project can see them).

    Raises:
        ValueError: If they are already a participant.
    """
    return _add_link(
        db, engagement, STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id, PARTICIPANT_FORWARD, PARTICIPANT_REVERSE, actor,
        organization_id=organization_id, duplicate_message="That Stakeholder is already a participant.",
    )


def list_participant_links(db: Session, engagement: Engagement, organization_id: uuid.UUID) -> list[ArtefactLink]:
    """The engagement's Stakeholder participant links."""
    return _outgoing(db, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, organization_id, PARTICIPANT_FORWARD, STAKEHOLDER_ARTEFACT_TYPE)


def add_covered_persona(
    db: Session, engagement: Engagement, persona_id: uuid.UUID, actor: User, *, organization_id: uuid.UUID
) -> ArtefactLink:
    """Records that the engagement covered a Persona (the caller has checked the project can see it).

    Raises:
        ValueError: If it is already recorded.
    """
    return _add_link(
        db, engagement, PERSONA_ARTEFACT_TYPE, persona_id, COVERS_FORWARD, COVERS_REVERSE, actor,
        organization_id=organization_id, duplicate_message="That Persona is already covered by this engagement.",
    )


def list_persona_links(db: Session, engagement: Engagement, organization_id: uuid.UUID) -> list[ArtefactLink]:
    """The engagement's covered-Persona links."""
    return _outgoing(db, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, organization_id, COVERS_FORWARD, PERSONA_ARTEFACT_TYPE)


def add_audience_group(
    db: Session, engagement: Engagement, group_id: uuid.UUID, actor: User, *, organization_id: uuid.UUID
) -> ArtefactLink:
    """Records the Stakeholder group the engagement was aimed at (members are added separately, as a snapshot).

    Raises:
        ValueError: If it is already recorded.
    """
    return _add_link(
        db, engagement, GROUP_ARTEFACT_TYPE, group_id, AUDIENCE_FORWARD, AUDIENCE_REVERSE, actor,
        organization_id=organization_id, duplicate_message="That group is already this engagement's audience.",
    )


def list_audience_links(db: Session, engagement: Engagement, organization_id: uuid.UUID) -> list[ArtefactLink]:
    """The engagement's audience-group links."""
    return _outgoing(db, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, organization_id, AUDIENCE_FORWARD, GROUP_ARTEFACT_TYPE)


def participant_counts(db: Session, project: Project, engagement_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Stakeholder participants per engagement, in one query (engagements with none are absent). A
    Stakeholder hidden from the project (Phase 3b) is not counted, so the count never discloses them."""
    type_id = link_type_id_if_exists(db, project.organization_id, PARTICIPANT_FORWARD)
    if type_id is None or not engagement_ids:
        return {}
    hidden = hidden_stakeholder_ids(db, project.id)
    counts: dict[uuid.UUID, int] = {}
    for source_id, target_id in db.execute(
        select(ArtefactLink.source_id, ArtefactLink.target_id).where(
            ArtefactLink.source_type == ENGAGEMENT_ARTEFACT_TYPE, ArtefactLink.source_id.in_(list(engagement_ids)),
            ArtefactLink.target_type == STAKEHOLDER_ARTEFACT_TYPE, ArtefactLink.link_type_id == type_id,
            ArtefactLink.source_project_id.is_(None),
        )
    ).all():
        if target_id not in hidden:
            counts[source_id] = counts.get(source_id, 0) + 1
    return counts


def engagement_ids_linked_to(
    db: Session, project: Project, target_type: str, target_id: uuid.UUID, forward: str
) -> set[uuid.UUID]:
    """The ids of this project's engagements with a `forward` link to the given record (list filters)."""
    type_id = link_type_id_if_exists(db, project.organization_id, forward)
    if type_id is None:
        return set()
    return set(db.scalars(
        select(ArtefactLink.source_id).join(Engagement, Engagement.id == ArtefactLink.source_id).where(
            ArtefactLink.source_type == ENGAGEMENT_ARTEFACT_TYPE, ArtefactLink.target_type == target_type,
            ArtefactLink.target_id == target_id, ArtefactLink.link_type_id == type_id,
            Engagement.project_id == project.id,
        )
    ))


def last_engaged_by_stakeholder(
    db: Session, project: Project, stakeholder_ids: Sequence[uuid.UUID] | None = None, *, today: date | None = None
) -> dict[uuid.UUID, date]:
    """Each Stakeholder's most recent engagement date in `project` (those never engaged are absent).

    Args:
        db: An active session.
        project: The viewing project; other projects' engagements are never counted.
        stakeholder_ids: Restrict to these Stakeholders (all participants when `None`).
        today: Engagements dated after this are not yet "engaged" (defaults to today, UTC).
    """
    type_id = link_type_id_if_exists(db, project.organization_id, PARTICIPANT_FORWARD)
    if type_id is None or (stakeholder_ids is not None and not stakeholder_ids):
        return {}
    query = (
        select(ArtefactLink.target_id, func.max(Engagement.engagement_date))
        .join(Engagement, Engagement.id == ArtefactLink.source_id)
        .where(
            ArtefactLink.source_type == ENGAGEMENT_ARTEFACT_TYPE, ArtefactLink.target_type == STAKEHOLDER_ARTEFACT_TYPE,
            ArtefactLink.link_type_id == type_id, ArtefactLink.source_project_id.is_(None),
            Engagement.project_id == project.id, Engagement.engagement_date <= (today or datetime.now(UTC).date()),
        )
        .group_by(ArtefactLink.target_id)
    )
    if stakeholder_ids is not None:
        query = query.where(ArtefactLink.target_id.in_(list(stakeholder_ids)))
    return {target_id: last for target_id, last in db.execute(query).all()}


def list_stakeholder_engagements(db: Session, project: Project, stakeholder_id: uuid.UUID) -> list[Engagement]:
    """This project's engagements the Stakeholder took part in, most recent first (their timeline)."""
    ids = engagement_ids_linked_to(db, project, STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id, PARTICIPANT_FORWARD)
    if not ids:
        return []
    return list(db.scalars(
        select(Engagement).where(Engagement.id.in_(ids))
        .order_by(Engagement.engagement_date.desc(), Engagement.created_at.desc())
    ).all())


# --- Outcomes: raised / answered -----------------------------------------------


def add_outcome(
    db: Session, engagement: Engagement, holder_type: str, holder_id: uuid.UUID, kind: OutcomeKind, target_type: str,
    target_id: uuid.UUID, actor: User, *, organization_id: uuid.UUID,
) -> ArtefactLink:
    """Records that an engagement or one of its findings raised/answered a record. The caller has
    resolved the holder and the target within the engagement's project.

    Raises:
        ValueError: If the holder or target type is not allowed for `kind`, or the link exists.
    """
    if holder_type not in OUTCOME_HOLDER_TYPES:
        raise ValueError("Only an engagement or a finding can raise or answer a record.")
    if target_type not in kind.target_types:
        raise ValueError(f"An engagement cannot have \"{kind.forward}\" a {target_type}.")
    return _add_link(
        db, engagement, target_type, target_id, kind.forward, kind.reverse, actor, organization_id=organization_id,
        duplicate_message="That outcome is already recorded.", source_type=holder_type, source_id=holder_id,
    )


def list_outcome_links(
    db: Session, holder_type: str, holder_id: uuid.UUID, organization_id: uuid.UUID
) -> list[tuple[ArtefactLink, OutcomeKind]]:
    """`(link, kind)` for every raised/answered link the holder has."""
    out = []
    for kind in OUTCOME_KINDS:
        for target_type in kind.target_types:
            out += [(link, kind) for link in _outgoing(db, holder_type, holder_id, organization_id, kind.forward, target_type)]
    return out


# --- Research extras -----------------------------------------------------------


def next_prompt_order(db: Session, engagement_id: uuid.UUID) -> int:
    """The `sort_order` a new prompt takes (after the existing ones)."""
    highest = db.scalar(select(func.max(EngagementPrompt.sort_order)).where(EngagementPrompt.engagement_id == engagement_id))
    return 0 if highest is None else highest + 1


def list_prompts(db: Session, engagement_id: uuid.UUID) -> list[EngagementPrompt]:
    """The engagement's session prompts in order."""
    return list(db.scalars(
        select(EngagementPrompt).where(EngagementPrompt.engagement_id == engagement_id)
        .order_by(EngagementPrompt.sort_order, EngagementPrompt.created_at)
    ).all())


def anonymous_participant_counts(db: Session, engagement_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Anonymous participants per engagement, in one query (engagements with none are absent)."""
    if not engagement_ids:
        return {}
    rows = db.execute(
        select(EngagementAnonymousParticipant.engagement_id, func.count())
        .where(EngagementAnonymousParticipant.engagement_id.in_(list(engagement_ids)))
        .group_by(EngagementAnonymousParticipant.engagement_id)
    ).all()
    return {engagement_id: count for engagement_id, count in rows}


def list_anonymous_participants(db: Session, engagement_id: uuid.UUID) -> list[EngagementAnonymousParticipant]:
    """The engagement's anonymous participants, in the order added."""
    return list(db.scalars(
        select(EngagementAnonymousParticipant).where(EngagementAnonymousParticipant.engagement_id == engagement_id)
        .order_by(EngagementAnonymousParticipant.created_at)
    ).all())


def list_findings(db: Session, engagement_id: uuid.UUID) -> list[ResearchFinding]:
    """The engagement's findings, oldest first."""
    return list(db.scalars(
        select(ResearchFinding).where(ResearchFinding.engagement_id == engagement_id).order_by(ResearchFinding.created_at)
    ).all())


# --- Erasure -------------------------------------------------------------------


def erase_engagement(db: Session, engagement: Engagement, actor: User) -> None:
    """Hard-deletes an engagement and everything that holds data about it (Phase 0 resolution 15):
    its notes, comments, prompts, anonymous participants, findings, every file in storage (direct and
    comment attachments) and every `ArtefactLink` touching it or its findings. Writes one audit event
    carrying only the id and the acting user, never the title or any content. The caller commits.

    Audit events logged earlier never held a title, filename or content (the routers log ids only and
    `ENGAGEMENT_ATTACHMENTS.log_filenames` is off), so none need scrubbing.
    """
    file_ids = set(db.scalars(select(EngagementFile.file_id).where(EngagementFile.engagement_id == engagement.id)))
    comment_ids = select(EngagementComment.id).where(EngagementComment.engagement_id == engagement.id)
    file_ids |= set(db.scalars(select(EngagementCommentFile.file_id).where(EngagementCommentFile.comment_id.in_(comment_ids))))
    for finding_id in db.scalars(select(ResearchFinding.id).where(ResearchFinding.engagement_id == engagement.id)).all():
        for link in get_all_links(db, FINDING_ARTEFACT_TYPE, finding_id, include_cross_project=True):
            delete_link(db, link)
    for link in get_all_links(db, ENGAGEMENT_ARTEFACT_TYPE, engagement.id, include_cross_project=True):
        delete_link(db, link)
    # The attachment rows cascade from the engagement; the bytes must be removed explicitly, so delete the assets.
    for asset in db.scalars(select(FileAsset).where(FileAsset.id.in_(file_ids))).all() if file_ids else []:
        delete_file(db, asset)
    db.flush()
    log_event(
        db, entity_type=ENGAGEMENT_ARTEFACT_TYPE, entity_id=engagement.id, action="erased", actor_id=actor.id,
        project_id=engagement.project_id,
    )
    db.delete(engagement)
    db.flush()


def resolve_engagement_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """The project owning a file attached to an engagement (or its comment); `None` for an unknown file."""
    from app.modules.stakeholders._engagement_shared import ENGAGEMENT_ATTACHMENTS
    from app.services.module_attachments import resolve_file_project_id

    return resolve_file_project_id(db, ENGAGEMENT_ATTACHMENTS, Engagement, file_id)
