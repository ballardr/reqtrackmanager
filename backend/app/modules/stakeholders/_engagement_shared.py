"""
Module: modules.stakeholders._engagement_shared

Handler bodies behind the project-scoped Engagement router
(`engagement_project_router.py`), mirroring `_need_shared.py`: the manage gate,
the API shapes, create/update/erase, the participant / persona / audience / outcome
links, and the comment and file kit.

RBAC: viewing needs the module to be enabled for the project (the engagement log
is always on); create, edit, erase, link and upload need the project
`engagement_owner` role or a Fine-Grained Access Control `(engagement, manage)`
grant. Commenting needs view only, like the other records. An Engagement has no
organisation scope, so there is no org-level role.

Tenancy and personal data: an engagement only links to Stakeholders, Personas and
groups its own project can see (own, or the organisation's and not hidden), and
to Pain Points / Needs / Open Questions of the same project; anything else 404s.
Titles and notes can name people, so audit events carry ids only, never a title
or filename, and `erase_engagement` removes everything.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders import engagements as eng
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders import relationships as rel
from app.modules.stakeholders._group_shared import GroupContext, list_members
from app.modules.stakeholders._shared import (
    apply_value_error_as_conflict,
    get_visible_persona,
    get_visible_stakeholder,
    holder_name,
)
from app.modules.stakeholders.engagements import ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE
from app.modules.stakeholders.enums import StakeholderScope
from app.modules.stakeholders.models import (
    Engagement,
    EngagementComment,
    EngagementCommentFile,
    EngagementFile,
    Persona,
    Stakeholder,
)
from app.modules.stakeholders.schemas import (
    EngagementAudienceAdded,
    EngagementAudienceOut,
    EngagementCommentOut,
    EngagementCreate,
    EngagementOut,
    EngagementParticipantOut,
    EngagementPersonaOut,
    EngagementUpdate,
    OutcomeCreate,
    OutcomeOut,
    RelationshipTargetOut,
    StakeholderEngagementOut,
)
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDERS_MODULE_KEY,
    hidden_stakeholder_ids,
)
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services import module_attachments as att
from app.services.audit import log_event
from app.services.permissions import encode_permission
from app.services.principals import principal_labels, validate_principal
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role
from app.services.relationships import delete_link

ENGAGEMENT_MANAGE_PERMISSION = encode_permission(ENGAGEMENT_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)
FINDING_MANAGE_PERMISSION = encode_permission(FINDING_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

# Filenames can be personal data (an email export named for a person), so audit events carry file ids.
ENGAGEMENT_ATTACHMENTS = att.AttachmentKit(
    artefact_type=ENGAGEMENT_ARTEFACT_TYPE, label="Engagement", comment_model=EngagementComment,
    comment_file_model=EngagementCommentFile, file_model=EngagementFile, fk="engagement_id",
    comment_out=EngagementCommentOut, log_filenames=False,
)

_TEXT_FIELDS = ("purpose", "summary", "notes")


def get_engagement_in_project(db: Session, project_id: uuid.UUID, engagement_id: uuid.UUID) -> Engagement:
    """Loads an engagement, 404ing unless it belongs to `project_id` (so another project's ids look absent)."""
    engagement = db.get(Engagement, engagement_id)
    if engagement is None or engagement.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Engagement not found.")
    return engagement


def require_engagement_manage(db: Session, current_user: User, project: Project) -> None:
    """Gate for create/edit/erase/link/attachment actions: the project `engagement_owner` role (composing
    with server admin, org admin and project manager) or an FGAC `(engagement, manage)` grant.

    Raises:
        HTTPException: 403 if neither holds.
    """
    if user_satisfies_module_role(
        db, current_user, STAKEHOLDERS_MODULE_KEY, "engagement_owner",
        organization_id=project.organization_id, project_id=project.id,
    ):
        return
    held = get_effective_permissions(
        db, current_user.id, organization_id=project.organization_id, project_id=project.id
    )
    if permission_satisfied(held, ENGAGEMENT_MANAGE_PERMISSION):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Engagement Owner (or admin/manager) may do this.")


def require_finding_manage(db: Session, current_user: User, project: Project) -> None:
    """Gate for changing a research finding or its raised/answered links: whoever may manage Engagements, or a
    Fine-Grained Access Control `(research_finding, manage)` grant (registering the artefact type creates that
    atom, so it must do something). The finding grant does not confer anything on the engagement itself.

    Raises:
        HTTPException: 403 if neither holds.
    """
    try:
        require_engagement_manage(db, current_user, project)
        return
    except HTTPException:
        pass
    held = get_effective_permissions(
        db, current_user.id, organization_id=project.organization_id, project_id=project.id
    )
    if not permission_satisfied(held, FINDING_MANAGE_PERMISSION):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Engagement Owner (or admin/manager) may do this.")


def log(db: Session, engagement_id: uuid.UUID, actor: User, project_id: uuid.UUID, action: str, **detail: Any) -> None:
    """Audit-logs an engagement event. `detail` must hold ids only (see the module docstring)."""
    log_event(
        db, entity_type=ENGAGEMENT_ARTEFACT_TYPE, entity_id=engagement_id, action=action, actor_id=actor.id,
        project_id=project_id, detail={k: str(v) for k, v in detail.items()} or None,
    )


# --- API shapes ---------------------------------------------------------------


def _facilitators_out(db: Session, engagement_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[PrincipalOut]]:
    """Each engagement's facilitators with display data, resolved in one batch."""
    refs = eng.list_facilitators(db, engagement_ids)
    labels = principal_labels(db, [ref for entries in refs.values() for ref in entries])
    return {eid: [labels[(ref.type.value, ref.id)] for ref in entries] for eid, entries in refs.items()}


def engagement_to_out(
    db: Session, engagement: Engagement, project: Project, *, facilitators: dict[uuid.UUID, list[PrincipalOut]] | None = None,
    participants: int | None = None, anonymous: int | None = None,
) -> EngagementOut:
    """The API shape (`facilitators`, `participants` and `anonymous` are batch results for list endpoints)."""
    if facilitators is None:
        facilitators = _facilitators_out(db, [engagement.id])
    if participants is None:
        participants = eng.participant_counts(db, project, [engagement.id]).get(engagement.id, 0)
    if anonymous is None:
        anonymous = eng.anonymous_participant_counts(db, [engagement.id]).get(engagement.id, 0)
    return EngagementOut(
        id=engagement.id, project_id=engagement.project_id, creator_id=engagement.creator_id,
        unique_code=engagement.unique_code, title=engagement.title,
        channel=engagement.channel, engagement_date=engagement.engagement_date, purpose=engagement.purpose,
        summary=engagement.summary, notes=engagement.notes, consent_recorded=engagement.consent_recorded,
        retain_until=engagement.retain_until, retention_due=eng.retention_due(engagement),
        participant_count=participants,
        anonymous_participant_count=anonymous,
        created_at=engagement.created_at, updated_at=engagement.updated_at,
        facilitators=facilitators.get(engagement.id, []),
    )


def engagements_to_out(db: Session, engagements: Sequence[Engagement], project: Project) -> list[EngagementOut]:
    """`engagement_to_out` for many engagements, resolving facilitators and participant counts in batches."""
    ids = [e.id for e in engagements]
    facilitators = _facilitators_out(db, ids)
    counts = eng.participant_counts(db, project, ids)
    anonymous = eng.anonymous_participant_counts(db, ids)
    return [
        engagement_to_out(
            db, e, project, facilitators=facilitators, participants=counts.get(e.id, 0), anonymous=anonymous.get(e.id, 0)
        )
        for e in engagements
    ]


def stakeholder_timeline(db: Session, project: Project, stakeholder: Stakeholder) -> list[StakeholderEngagementOut]:
    """The project's engagements a visible Stakeholder took part in, most recent first."""
    return [
        StakeholderEngagementOut(id=e.id, title=e.title, channel=e.channel, engagement_date=e.engagement_date)
        for e in eng.list_stakeholder_engagements(db, project, stakeholder.id)
    ]


# --- List ---------------------------------------------------------------------


def list_engagements(
    db: Session, project: Project, *, channel: str | None = None, stakeholder_id: uuid.UUID | None = None,
    persona_id: uuid.UUID | None = None, date_from=None, date_to=None, retention_due: bool | None = None,
) -> list[EngagementOut]:
    """The project's engagements, most recent first, narrowed by any of the filters (all must hold)."""
    rows = eng.list_project_engagements(db, project.id)
    if channel is not None:
        rows = [e for e in rows if e.channel.value == channel]
    if date_from is not None:
        rows = [e for e in rows if e.engagement_date >= date_from]
    if date_to is not None:
        rows = [e for e in rows if e.engagement_date <= date_to]
    if retention_due is not None:
        rows = [e for e in rows if eng.retention_due(e) == retention_due]
    if stakeholder_id is not None:
        get_visible_stakeholder(db, project, stakeholder_id)
        ids = eng.engagement_ids_linked_to(db, project, STAKEHOLDER_ARTEFACT_TYPE, stakeholder_id, eng.PARTICIPANT_FORWARD)
        rows = [e for e in rows if e.id in ids]
    if persona_id is not None:
        get_visible_persona(db, project, persona_id)
        ids = eng.engagement_ids_linked_to(db, project, PERSONA_ARTEFACT_TYPE, persona_id, eng.COVERS_FORWARD)
        rows = [e for e in rows if e.id in ids]
    return engagements_to_out(db, rows, project)


# --- Create / update / erase --------------------------------------------------


def _validate_facilitators(db: Session, project: Project, facilitators: Sequence[PrincipalRef]) -> None:
    """Rejects (400) a facilitator who may not be named on the project's engagements: a user outside the
    organisation, or a group of another organisation or project."""
    for ref in facilitators:
        validate_principal(db, ref, organization_id=project.organization_id, project_id=project.id, field="facilitators")


def create_engagement_from_payload(
    db: Session, payload: EngagementCreate, creator: User, project: Project
) -> EngagementOut:
    """Validates every reference in a create payload (404 before anything is written), creates the engagement
    with its participants, covered personas and audience groups (groups expanded to their members), audit-logs,
    commits and returns the API shape."""
    _validate_facilitators(db, project, payload.facilitators)
    stakeholders = [get_visible_stakeholder(db, project, sid) for sid in dict.fromkeys(payload.stakeholder_ids)]
    personas = [get_visible_persona(db, project, pid) for pid in dict.fromkeys(payload.persona_ids)]
    universe = grp.load_groups(db, project.organization_id, project.id)
    if any(gid not in universe for gid in payload.group_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder group not found.")
    content = payload.model_dump(exclude={"facilitators", "stakeholder_ids", "persona_ids", "group_ids"})
    engagement = eng.create_engagement(db, project=project, creator=creator, **content)
    eng.set_facilitators(db, engagement, payload.facilitators)
    for stakeholder in stakeholders:
        apply_value_error_as_conflict(
            eng.add_participant, db, engagement, stakeholder.id, creator, organization_id=project.organization_id
        )
    for persona in personas:
        apply_value_error_as_conflict(
            eng.add_covered_persona, db, engagement, persona.id, creator, organization_id=project.organization_id
        )
    for group_id in dict.fromkeys(payload.group_ids):
        _audience_with_members(db, engagement, group_id, creator, project)
    log(db, engagement.id, creator, project.id, "created")
    db.commit()
    db.refresh(engagement)
    return engagement_to_out(db, engagement, project)


def update_engagement_from_payload(
    db: Session, engagement: Engagement, payload: EngagementUpdate, actor: User, project: Project
) -> EngagementOut:
    """Applies a partial update (only fields present in the request body change), audit-logs, commits and
    returns the API shape."""
    sent = payload.model_dump(exclude_unset=True)
    for required in ("title", "channel", "engagement_date"):
        if required in sent and sent[required] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"An engagement's {required} cannot be null.")
    for text_field in _TEXT_FIELDS:
        if text_field in sent and sent[text_field] is None:
            sent[text_field] = ""
    if "consent_recorded" in sent and sent["consent_recorded"] is None:
        sent["consent_recorded"] = False
    if "facilitators" in sent:
        facilitators = payload.facilitators or []
        _validate_facilitators(db, project, facilitators)
        eng.set_facilitators(db, engagement, facilitators)
    eng.update_engagement(db, engagement, sent)  # ignores keys that are not engagement columns, like `facilitators`
    log(db, engagement.id, actor, project.id, "updated", fields=",".join(sorted(sent)))
    db.commit()
    db.refresh(engagement)
    return engagement_to_out(db, engagement, project)


def erase(db: Session, engagement: Engagement, actor: User) -> None:
    """Permanently deletes the engagement and all of its data (see `engagements.erase_engagement`), then commits."""
    eng.erase_engagement(db, engagement, actor)
    db.commit()


# --- Participants -------------------------------------------------------------


def _visible(project: Project, hidden: set[uuid.UUID], stakeholder: Stakeholder) -> bool:
    """Whether the project may see the stakeholder (its own, or the organisation's and not hidden)."""
    if stakeholder.scope == StakeholderScope.PROJECT:
        return stakeholder.project_id == project.id
    return stakeholder.organization_id == project.organization_id and stakeholder.id not in hidden


def participant_to_out(db: Session, link, stakeholder: Stakeholder) -> EngagementParticipantOut:
    return EngagementParticipantOut(
        link_id=link.id, stakeholder_id=stakeholder.id, name=holder_name(db, STAKEHOLDER_ARTEFACT_TYPE, stakeholder),
        scope=stakeholder.scope.value,
    )


def list_participants(db: Session, engagement: Engagement, project: Project) -> list[EngagementParticipantOut]:
    """The Stakeholders who took part, minus any hidden from the project, by name."""
    hidden = hidden_stakeholder_ids(db, project.id)
    out = []
    for link in eng.list_participant_links(db, engagement, project.organization_id):
        stakeholder = db.get(Stakeholder, link.target_id)
        if stakeholder is not None and _visible(project, hidden, stakeholder):
            out.append(participant_to_out(db, link, stakeholder))
    return sorted(out, key=lambda p: p.name.lower())


def add_participant(
    db: Session, engagement: Engagement, stakeholder_id: uuid.UUID, actor: User, project: Project
) -> EngagementParticipantOut:
    """Adds a visible Stakeholder as a participant (409 on a duplicate), audit-logs and commits."""
    stakeholder = get_visible_stakeholder(db, project, stakeholder_id)
    link = apply_value_error_as_conflict(
        eng.add_participant, db, engagement, stakeholder.id, actor, organization_id=project.organization_id
    )
    log(db, engagement.id, actor, project.id, "participant_added", stakeholder_id=stakeholder.id)
    db.commit()
    return participant_to_out(db, link, stakeholder)


def remove_participant(
    db: Session, engagement: Engagement, stakeholder_id: uuid.UUID, actor: User, project: Project
) -> None:
    """Removes a participant link (404 if there is none), audit-logs and commits."""
    for link in eng.list_participant_links(db, engagement, project.organization_id):
        if link.target_id == stakeholder_id:
            delete_link(db, link)
            log(db, engagement.id, actor, project.id, "participant_removed", stakeholder_id=stakeholder_id)
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "That Stakeholder did not take part.")


# --- Personas covered ---------------------------------------------------------


def persona_to_out(db: Session, link, persona: Persona) -> EngagementPersonaOut:
    return EngagementPersonaOut(
        link_id=link.id, persona_id=persona.id, name=holder_name(db, PERSONA_ARTEFACT_TYPE, persona),
        scope=persona.scope.value,
    )


def list_personas(db: Session, engagement: Engagement, project: Project) -> list[EngagementPersonaOut]:
    """The Personas the engagement covered, minus any hidden from the project, by name."""
    out = []
    for link in eng.list_persona_links(db, engagement, project.organization_id):
        persona = db.get(Persona, link.target_id)
        if persona is None:
            continue
        try:
            get_visible_persona(db, project, persona.id)
        except HTTPException:
            continue
        out.append(persona_to_out(db, link, persona))
    return sorted(out, key=lambda p: p.name.lower())


def add_persona(
    db: Session, engagement: Engagement, persona_id: uuid.UUID, actor: User, project: Project
) -> EngagementPersonaOut:
    """Records a visible Persona as covered (409 on a duplicate), audit-logs and commits."""
    persona = get_visible_persona(db, project, persona_id)
    link = apply_value_error_as_conflict(
        eng.add_covered_persona, db, engagement, persona.id, actor, organization_id=project.organization_id
    )
    log(db, engagement.id, actor, project.id, "persona_added", persona_id=persona.id)
    db.commit()
    return persona_to_out(db, link, persona)


def remove_persona(db: Session, engagement: Engagement, persona_id: uuid.UUID, actor: User, project: Project) -> None:
    """Removes a covered-Persona link (404 if there is none), audit-logs and commits."""
    for link in eng.list_persona_links(db, engagement, project.organization_id):
        if link.target_id == persona_id:
            delete_link(db, link)
            log(db, engagement.id, actor, project.id, "persona_removed", persona_id=persona_id)
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "That Persona was not covered.")


# --- Audience groups ----------------------------------------------------------


def _audience_out(link, group) -> EngagementAudienceOut:
    return EngagementAudienceOut(link_id=link.id, group_id=group.id, name=group.name, scope=group.scope.value)


def list_audiences(db: Session, engagement: Engagement, project: Project) -> list[EngagementAudienceOut]:
    """The groups the engagement was aimed at (those the project can see), by name."""
    universe = grp.load_groups(db, project.organization_id, project.id)
    out = [
        _audience_out(link, universe[link.target_id])
        for link in eng.list_audience_links(db, engagement, project.organization_id) if link.target_id in universe
    ]
    return sorted(out, key=lambda a: a.name.lower())


def _audience_with_members(
    db: Session, engagement: Engagement, group_id: uuid.UUID, actor: User, project: Project
) -> EngagementAudienceAdded:
    """Records `group_id` as an audience and adds its current members (the group and every group beneath
    it, minus archived and hidden Stakeholders) as participants: a snapshot, so later membership changes
    do not alter who the engagement involved (Phase 0 addendum 3, item 29). Existing participants are kept."""
    group = grp.load_groups(db, project.organization_id, project.id).get(group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stakeholder group not found.")
    members = list_members(db, GroupContext(project.organization_id, project), group_id, direct_only=False)
    link = apply_value_error_as_conflict(
        eng.add_audience_group, db, engagement, group_id, actor, organization_id=project.organization_id
    )
    existing = {p.target_id for p in eng.list_participant_links(db, engagement, project.organization_id)}
    added = []
    for member in members:
        if member.stakeholder_id in existing:
            continue
        stakeholder = db.get(Stakeholder, member.stakeholder_id)
        added.append(participant_to_out(
            db, eng.add_participant(db, engagement, stakeholder.id, actor, organization_id=project.organization_id),
            stakeholder,
        ))
    return EngagementAudienceAdded(
        audience=_audience_out(link, group), participants_added=added,
        already_participating=len(members) - len(added),
    )


def add_audience(
    db: Session, engagement: Engagement, group_id: uuid.UUID, actor: User, project: Project
) -> EngagementAudienceAdded:
    """Adds an audience group and its members as participants (409 if the group is already an audience),
    audit-logs and commits."""
    result = _audience_with_members(db, engagement, group_id, actor, project)
    log(db, engagement.id, actor, project.id, "audience_added", group_id=group_id, participants_added=len(result.participants_added))
    db.commit()
    return result


def remove_audience(db: Session, engagement: Engagement, group_id: uuid.UUID, actor: User, project: Project) -> None:
    """Removes the audience link only: the participants it added stay (the record is a snapshot)."""
    for link in eng.list_audience_links(db, engagement, project.organization_id):
        if link.target_id == group_id:
            delete_link(db, link)
            log(db, engagement.id, actor, project.id, "audience_removed", group_id=group_id)
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "That group is not this engagement's audience.")


# --- Outcomes: raised / answered ----------------------------------------------


def list_outcomes(
    db: Session, holder_type: str, holder_id: uuid.UUID, project: Project
) -> list[OutcomeOut]:
    """What an engagement or finding raised or answered, within this project (targets elsewhere or whose
    module is disabled are left out)."""
    out = []
    for link, kind in eng.list_outcome_links(db, holder_type, holder_id, project.organization_id):
        summary = rel.resolve_target(db, project, link.target_type, link.target_id)
        if summary is not None:
            out.append(OutcomeOut(
                link_id=link.id, kind=kind.key, target_type=link.target_type, target_id=summary.id, label=summary.label,
            ))
    return sorted(out, key=lambda o: (o.kind, o.label.lower()))


def list_outcome_targets(db: Session, user: User, project: Project, target_type: str) -> list[RelationshipTargetOut]:
    """The project's records of `target_type` an engagement or finding can raise or answer: the picker's choices.

    Raises:
        HTTPException: 404 for a type no outcome kind targets, one whose module is not installed, or one the
            caller may not view (the `(type, view)` FGAC atom), so a title is never shown that the owning
            module's own screens would hide.
    """
    allowed = {t for kind in eng.OUTCOME_KINDS for t in kind.target_types}
    held = get_effective_permissions(db, user.id, organization_id=project.organization_id, project_id=project.id)
    viewable = permission_satisfied(held, encode_permission(target_type, PermissionLevel.VIEW.value))
    if target_type not in allowed or not rel.target_type_available(target_type) or not viewable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such outcome target type.")
    return [RelationshipTargetOut(id=s.id, label=s.label, status=s.status) for s in rel.list_targets(db, project, target_type)]


def add_outcome(
    db: Session, engagement: Engagement, holder_type: str, holder_id: uuid.UUID, payload: OutcomeCreate,
    actor: User, project: Project,
) -> OutcomeOut:
    """Records that the holder raised/answered a record of this project (422 for a target type the kind does not
    allow, 409 if its module is not installed or on a duplicate), audit-logs and commits."""
    kind = eng.get_outcome_kind(payload.kind)
    if kind is None or payload.target_type not in kind.target_types:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"\"{payload.kind}\" cannot point at a {payload.target_type}."
        )
    if not rel.target_type_available(payload.target_type):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{payload.target_type} is not available until its module is installed.")
    summary = rel.resolve_target(db, project, payload.target_type, payload.target_id)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target not found.")
    link = apply_value_error_as_conflict(
        eng.add_outcome, db, engagement, holder_type, holder_id, kind, payload.target_type, summary.id, actor,
        organization_id=project.organization_id,
    )
    log(db, engagement.id, actor, project.id, "outcome_added", kind=kind.key, target_type=payload.target_type, target_id=summary.id,
        holder_type=holder_type, holder_id=holder_id)
    db.commit()
    return OutcomeOut(link_id=link.id, kind=kind.key, target_type=payload.target_type, target_id=summary.id, label=summary.label)


def remove_outcome(
    db: Session, engagement: Engagement, holder_type: str, holder_id: uuid.UUID, link_id: uuid.UUID, actor: User,
    project: Project,
) -> None:
    """Removes one outcome link of the holder (404 if the id is not one of its links), audit-logs and commits."""
    for link, kind in eng.list_outcome_links(db, holder_type, holder_id, project.organization_id):
        if link.id == link_id:
            delete_link(db, link)
            log(db, engagement.id, actor, project.id, "outcome_removed", kind=kind.key, holder_type=holder_type,
                holder_id=holder_id)
            db.commit()
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Outcome not found.")


# --- Comments and files -------------------------------------------------------


def add_comment(db: Session, engagement: Engagement, user: User, body: str, **scope_ids) -> EngagementCommentOut:
    """Adds and audit-logs a comment."""
    return att.add_comment(db, ENGAGEMENT_ATTACHMENTS, engagement, user, body, **scope_ids)


def list_comments(db: Session, engagement: Engagement) -> list[EngagementCommentOut]:
    """Comments on an engagement, oldest first."""
    return att.list_comments(db, ENGAGEMENT_ATTACHMENTS, engagement)


def edit_comment(
    db: Session, engagement: Engagement, comment_id: uuid.UUID, user: User, body: str, **scope_ids
) -> EngagementCommentOut:
    """Author-only edit; audit-logged."""
    return att.edit_comment(db, ENGAGEMENT_ATTACHMENTS, engagement, comment_id, user, body, **scope_ids)


async def attach_to_comment(
    db: Session, engagement: Engagement, comment_id: uuid.UUID, user: User, file: UploadFile, *,
    organization_id: uuid.UUID, **scope_ids,
) -> FileAsset:
    """Author-only comment attachment."""
    return await att.attach_to_comment(
        db, ENGAGEMENT_ATTACHMENTS, engagement, comment_id, user, file, organization_id=organization_id, **scope_ids
    )


def remove_comment_attachment(
    db: Session, engagement: Engagement, comment_id: uuid.UUID, file_id: uuid.UUID, user: User, **scope_ids
) -> None:
    """Author-only removal of a comment attachment; audit-logged."""
    att.remove_comment_attachment(db, ENGAGEMENT_ATTACHMENTS, engagement, comment_id, file_id, user, **scope_ids)


async def attach_file(
    db: Session, engagement: Engagement, user: User, file: UploadFile, *, organization_id: uuid.UUID, **scope_ids
) -> FileAsset:
    """Uploads and links a file to an engagement (caller has checked manage)."""
    return await att.attach_file(
        db, ENGAGEMENT_ATTACHMENTS, engagement, user, file, organization_id=organization_id, **scope_ids
    )


def list_files(db: Session, engagement: Engagement) -> list[FileAsset]:
    """Files directly attached to an engagement."""
    return att.list_files(db, ENGAGEMENT_ATTACHMENTS, engagement)


def unlink_file(db: Session, engagement: Engagement, file_id: uuid.UUID, user: User, **scope_ids) -> None:
    """Unlinks and deletes a directly attached file (caller has checked manage)."""
    att.unlink_file(db, ENGAGEMENT_ATTACHMENTS, engagement, file_id, user, **scope_ids)
