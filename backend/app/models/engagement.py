"""
Module: models.engagement

Lightweight social/engagement features layered on top of the existing
discussion-thread and notification systems: a single-emoji "reaction" on a
comment, and a per-entity subscription so a user can opt into notifications
for one specific requirement or change request rather than only broad
per-type preferences (see services/notifications.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class CommentReaction(UUIDPKMixin, TimestampMixin, Base):
    """A single user's reaction to a discussion comment.

    Attributes:
        comment_id: The `ReviewComment` being reacted to.
        user_id: The user who reacted.

    A user may only react once per comment (toggled on/off, not repeated) —
    enforced by the unique constraint rather than in application code, so a
    double-click race can't create two rows.
    """

    __tablename__ = "comment_reactions"
    __table_args__ = (UniqueConstraint("comment_id", "user_id"),)

    comment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("review_comments.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Subscription(UUIDPKMixin, TimestampMixin, Base):
    """A user's opt-in to notifications for one specific requirement or
    change request, independent of their broad per-type notification
    preferences (`NotificationPreference`).

    Attributes:
        user_id: The subscribing user.
        entity_type: `"requirement"` or `"change_request"`.
        entity_id: The id of the requirement/change request row.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "entity_type", "entity_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
