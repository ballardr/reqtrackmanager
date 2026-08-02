"""
Module: services.engagement

Shared helpers for comment reactions and per-entity subscriptions, used by
both the requirements and change-requests routers (comments/subscriptions
work identically for both entity types).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ReviewComment
from app.models.engagement import CommentReaction, Subscription
from app.models.enums import ReviewTargetType
from app.models.user import User
from app.schemas.requirement import CommentOut


def comment_to_out(db: Session, comment: ReviewComment, current_user_id: UUID) -> CommentOut:
    """Builds a CommentOut with the author's display name and this user's
    reaction state, since those aren't columns on `ReviewComment` itself."""
    author = db.get(User, comment.author_id)
    reaction_count = db.scalar(
        select(func.count(CommentReaction.id)).where(CommentReaction.comment_id == comment.id)
    ) or 0
    reacted_by_me = (
        db.scalar(
            select(CommentReaction.id).where(
                CommentReaction.comment_id == comment.id, CommentReaction.user_id == current_user_id
            )
        )
        is not None
    )
    return CommentOut(
        id=comment.id,
        author_id=comment.author_id,
        author_display_name=author.display_name if author is not None else "Unknown user",
        body=comment.body,
        created_at=comment.created_at,
        reaction_count=reaction_count,
        reacted_by_me=reacted_by_me,
    )


def add_reaction(db: Session, comment_id: UUID, user_id: UUID) -> None:
    """Adds the current user's reaction to a comment (idempotent)."""
    existing = db.scalar(
        select(CommentReaction).where(CommentReaction.comment_id == comment_id, CommentReaction.user_id == user_id)
    )
    if existing is None:
        db.add(CommentReaction(comment_id=comment_id, user_id=user_id))
        db.commit()


def remove_reaction(db: Session, comment_id: UUID, user_id: UUID) -> None:
    """Removes the current user's reaction from a comment (idempotent)."""
    existing = db.scalar(
        select(CommentReaction).where(CommentReaction.comment_id == comment_id, CommentReaction.user_id == user_id)
    )
    if existing is not None:
        db.delete(existing)
        db.commit()


def get_comment_count(db: Session, target_type: ReviewTargetType, target_id: UUID) -> int:
    """Returns how many discussion comments exist on a requirement/change request.

    Backs the list-view "has comments" badge (mock's discussion indicator).
    """
    return db.scalar(
        select(func.count(ReviewComment.id)).where(
            ReviewComment.target_type == target_type, ReviewComment.target_id == target_id
        )
    ) or 0


def is_subscribed(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> bool:
    return (
        db.scalar(
            select(Subscription.id).where(
                Subscription.user_id == user_id,
                Subscription.entity_type == entity_type,
                Subscription.entity_id == entity_id,
            )
        )
        is not None
    )


def subscribe(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> None:
    if not is_subscribed(db, user_id, entity_type, entity_id):
        db.add(Subscription(user_id=user_id, entity_type=entity_type, entity_id=entity_id))
        db.commit()


def unsubscribe(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> None:
    existing = db.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.entity_type == entity_type,
            Subscription.entity_id == entity_id,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.commit()


def get_subscriber_ids(db: Session, entity_type: str, entity_id: UUID, *, exclude_user_id: UUID) -> list[UUID]:
    """Returns subscriber user ids for an entity, excluding the given user
    (typically the comment's own author, who doesn't need a notification
    about their own comment)."""
    return list(
        db.scalars(
            select(Subscription.user_id).where(
                Subscription.entity_type == entity_type,
                Subscription.entity_id == entity_id,
                Subscription.user_id != exclude_user_id,
            )
        ).all()
    )
