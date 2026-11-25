"""
Module: modules.product_feedback.vocabularies

The organisation-defined list requesters are classified by: `REQUEST_CHANNELS`,
a `TypeVocabulary` (organisation base list; a project overrides, adds, hides).
A child project with no configuration shows its nearest ancestor's effective
list, else the organisation's; its first change copies it in. A project record
references a project row (`resolve_channel`). Entries are seeded at organisation
creation, never per project; external systems live in `services.external_references`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.product_feedback.models import (
    EnhancementRequestRequesterChannel,
    ProjectRequestChannel,
    RequestChannelDefinition,
)
from app.services.type_vocabulary import TypeVocabulary

DEFAULT_REQUEST_CHANNELS: tuple[str, ...] = (
    "Engagement", "Support ticket", "Call", "Chat", "Conversation", "Email", "Survey", "Internal", "Other",
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
    """`ModuleDefinition.on_org_created`: gives a new organisation the default request channels."""
    REQUEST_CHANNELS.seed_defaults(db, organization_id)


def resolve_channel(db: Session, project: Project, channel_id: uuid.UUID) -> uuid.UUID:
    """Resolves a payload's channel id (an `EffectiveType.id` of the project's list) to the project row a
    requester's channel stores.

    Raises:
        ValueError: If the id is not an enabled channel of the project.
    """
    return REQUEST_CHANNELS.usable_row_id(db, project.id, project.organization_id, channel_id)
