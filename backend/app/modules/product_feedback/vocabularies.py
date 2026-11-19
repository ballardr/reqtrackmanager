"""
Module: modules.product_feedback.vocabularies

The short, organisation-defined list a request's requesters are classified by, a `TypeVocabulary` (organisation base
list; a project overrides, adds and hides entries):

- `REQUEST_CHANNELS` — how a requester asked (Support ticket, Call, Email, ...).

The outside systems a request's external references point into (Jira, ServiceNow, ...) are shared by every record
type and live in `services.external_references`.

Design decisions:
- Nested projects (**Decided by: User**): a child project with no configuration of its own shows its nearest
  ancestor's effective list, else the organisation's (`TypeVocabulary(inherit_from_ancestors=True)`). Its first change
  copies the inherited configuration into it, so it is then its own. A record in a child may reference the
  ancestor's row for an entry the ancestor added or renamed.
- A project record references a *project* row (`resolve_channel` creates the passthrough row the first time an
  organisation entry is chosen).
- Entries are seeded when an organisation is created (`seed_org_defaults`), never for a project.
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
