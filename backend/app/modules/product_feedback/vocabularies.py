"""
Module: modules.product_feedback.vocabularies

The two short, organisation-defined lists a request is classified by, each a `TypeVocabulary` (organisation base
list; a project overrides, adds and hides entries):

- `EXTERNAL_SYSTEMS` — the outside tool a reference points into (Jira, ServiceNow, ...).
- `REQUEST_CHANNELS` — how a requester asked (Support ticket, Call, Email, ...).

Design decisions:
- Nested projects (**Decided by: User**): a child project with no configuration of its own shows its nearest
  ancestor's effective list, else the organisation's (`TypeVocabulary(inherit_from_ancestors=True)`). Its first change
  copies the inherited configuration into it, so it is then its own. A record in a child may reference the
  ancestor's row for an entry the ancestor added or renamed.
- A project record references a *project* row (`resolve_system` / `resolve_channel` create the passthrough row the
  first time an organisation entry is chosen); an organisation-inbox reference points at the organisation's entry
  directly, and is converted to a project row when the request is triaged (`references.convert_to_project`).
- Entries are seeded when an organisation is created (`seed_defaults`), never for a project.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.product_feedback.models import (
    EnhancementRequestExternalRef,
    EnhancementRequestRequesterChannel,
    ExternalSystemDefinition,
    ProjectExternalSystem,
    ProjectRequestChannel,
    RequestChannelDefinition,
)
from app.services.type_vocabulary import TypeVocabulary

DEFAULT_EXTERNAL_SYSTEMS: tuple[str, ...] = ("Jira", "ServiceNow", "Zendesk", "Azure DevOps", "GitHub", "Other")
DEFAULT_REQUEST_CHANNELS: tuple[str, ...] = (
    "Engagement", "Support ticket", "Call", "Chat", "Conversation", "Email", "Survey", "Internal", "Other",
)
#: The entry a legacy single delivery link was filed under, and the one the Other fallback uses.
OTHER_NAME = "Other"

EXTERNAL_SYSTEMS = TypeVocabulary(
    kind="external_system",
    label="External system",
    org_model=ExternalSystemDefinition,
    project_model=ProjectExternalSystem,
    default_names=DEFAULT_EXTERNAL_SYSTEMS,
    org_type_in_use=lambda db, type_id: db.scalar(
        select(EnhancementRequestExternalRef.id).where(EnhancementRequestExternalRef.org_system_id == type_id).limit(1)
    ) is not None,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(EnhancementRequestExternalRef.id).where(EnhancementRequestExternalRef.project_system_id == type_id).limit(1)
    ) is not None,
    inherit_from_ancestors=True,
)

REQUEST_CHANNELS = TypeVocabulary(
    kind="request_channel",
    label="Request channel",
    org_model=RequestChannelDefinition,
    project_model=ProjectRequestChannel,
    default_names=DEFAULT_REQUEST_CHANNELS,
    # A requester's channel references a project row, never an organisation entry directly.
    org_type_in_use=lambda db, type_id: False,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(EnhancementRequestRequesterChannel.id).where(EnhancementRequestRequesterChannel.channel_id == type_id).limit(1)
    ) is not None,
    inherit_from_ancestors=True,
)


def seed_org_defaults(db: Session, organization_id: uuid.UUID) -> None:
    """`ModuleDefinition.on_org_created`: gives a new organisation the default systems and channels."""
    EXTERNAL_SYSTEMS.seed_defaults(db, organization_id)
    REQUEST_CHANNELS.seed_defaults(db, organization_id)


def resolve_system(
    db: Session, organization_id: uuid.UUID, project: Project | None, system_id: uuid.UUID,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Resolves a payload's system id to the `(org_system_id, project_system_id)` pair a reference stores.

    Args:
        db: Active session (a passthrough project row may be added; the caller commits).
        organization_id: The request's organisation.
        project: The request's project, or `None` for an inbox request.
        system_id: An `EffectiveType.id` of the request's tier (the project's list, or the organisation's).

    Raises:
        ValueError: If the id is not an enabled system of that tier.
    """
    if project is None:
        org_type = db.get(ExternalSystemDefinition, system_id)
        if org_type is None or org_type.organization_id != organization_id or not org_type.is_active:
            raise ValueError("This is not a valid external system for this organisation.")
        return org_type.id, None
    return None, EXTERNAL_SYSTEMS.usable_row_id(db, project.id, organization_id, system_id)


def resolve_channel(db: Session, project: Project, channel_id: uuid.UUID) -> uuid.UUID:
    """Resolves a payload's channel id (an `EffectiveType.id` of the project's list) to the project row a
    requester's channel stores.

    Raises:
        ValueError: If the id is not an enabled channel of the project.
    """
    return REQUEST_CHANNELS.usable_row_id(db, project.id, project.organization_id, channel_id)
