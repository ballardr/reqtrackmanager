"""
Module: services.engagement

Shared helpers for comment reactions and per-entity subscriptions, used by
both the requirements and change-requests routers (comments/subscriptions
work identically for both entity types).
"""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ReviewComment
from app.models.engagement import CommentReaction, Subscription
from app.models.enums import PrincipalType, ReviewTargetType
from app.models.file import CommentFile, FileAsset
from app.models.project import FavoriteProject, Project
from app.models.requirement import Requirement
from app.models.user import User
from app.schemas.file import FileAssetOut
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.schemas.requirement import CommentOut
from app.services.audit import log_event
from app.services.principals import principal_labels, principal_recipients, validate_principal
from app.services.rbac import get_project_member_user_ids


def comments_to_out(db: Session, comments: list[ReviewComment], current_user_id: UUID) -> list[CommentOut]:
    """`CommentOut`s for several comments, each with the author's display name, this user's reaction state and
    attached files (none of which are columns on `ReviewComment`), loaded in a fixed number of statements so a
    thread of 200 comments costs the same as one of 2.

    Args:
        db: Active session (read only).
        comments: The comments, in the order to return.
        current_user_id: The viewer (for `reacted_by_me`).
    """
    if not comments:
        return []
    ids = [c.id for c in comments]
    authors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({c.author_id for c in comments})))}
    reaction_counts = dict(db.execute(
        select(CommentReaction.comment_id, func.count(CommentReaction.id))
        .where(CommentReaction.comment_id.in_(ids)).group_by(CommentReaction.comment_id)
    ).all())
    reacted = set(db.scalars(select(CommentReaction.comment_id).where(
        CommentReaction.comment_id.in_(ids), CommentReaction.user_id == current_user_id,
    )).all())
    attachments: dict[UUID, list[FileAsset]] = {}
    for comment_id, asset in db.execute(
        select(CommentFile.comment_id, FileAsset).join(FileAsset, CommentFile.file_id == FileAsset.id)
        .where(CommentFile.comment_id.in_(ids))
    ).all():
        attachments.setdefault(comment_id, []).append(asset)
    out = []
    for comment in comments:
        author = authors.get(comment.author_id)
        out.append(CommentOut(
            id=comment.id,
            author_id=comment.author_id,
            author_display_name=author.display_name if author is not None else "Unknown user",
            body=comment.body,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
            reaction_count=reaction_counts.get(comment.id, 0),
            reacted_by_me=comment.id in reacted,
            attachments=[FileAssetOut.model_validate(a) for a in attachments.get(comment.id, [])],
        ))
    return out


def comment_to_out(db: Session, comment: ReviewComment, current_user_id: UUID) -> CommentOut:
    """`comments_to_out` for one comment."""
    return comments_to_out(db, [comment], current_user_id)[0]


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


def get_comment_counts(db: Session, target_type: ReviewTargetType, target_ids: Collection[UUID]) -> dict[UUID, int]:
    """`get_comment_count` for many targets in one query, for list views.

    Returns:
        Comment count per target id; targets with no comments are absent.
    """
    if not target_ids:
        return {}
    return dict(db.execute(
        select(ReviewComment.target_id, func.count(ReviewComment.id)).where(
            ReviewComment.target_type == target_type, ReviewComment.target_id.in_(set(target_ids)),
        ).group_by(ReviewComment.target_id)
    ).all())


def _own_subscription(user_id: UUID, entity_type: str, entity_id: UUID):
    """The condition selecting a user's own (direct) subscription to an entity."""
    return (
        Subscription.subscriber_type == PrincipalType.USER.value,
        Subscription.subscriber_id == user_id,
        Subscription.entity_type == entity_type,
        Subscription.entity_id == entity_id,
    )


def is_subscribed(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> bool:
    """True when the user subscribed themselves (a group they watch through is listed separately,
    `list_group_watchers`)."""
    return db.scalar(select(Subscription.id).where(*_own_subscription(user_id, entity_type, entity_id))) is not None


def subscribed_ids(db: Session, user_id: UUID, entity_type: str, entity_ids: Collection[UUID]) -> set[UUID]:
    """`is_subscribed` for many entities of one type in one query, for list views."""
    if not entity_ids:
        return set()
    return set(db.scalars(select(Subscription.entity_id).where(
        Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == user_id,
        Subscription.entity_type == entity_type, Subscription.entity_id.in_(set(entity_ids)),
    )))


def subscribe(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> None:
    if not is_subscribed(db, user_id, entity_type, entity_id):
        db.add(Subscription(
            subscriber_type=PrincipalType.USER.value, subscriber_id=user_id, entity_type=entity_type, entity_id=entity_id,
        ))
        db.commit()


def unsubscribe(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> None:
    existing = db.scalar(select(Subscription).where(*_own_subscription(user_id, entity_type, entity_id)))
    if existing is not None:
        db.delete(existing)
        db.commit()


def list_group_watchers(db: Session, entity_type: str, entity_id: UUID) -> list[Subscription]:
    """The group subscriptions on an entity (organisation and project groups), oldest first."""
    return list(db.scalars(
        select(Subscription).where(
            Subscription.entity_type == entity_type, Subscription.entity_id == entity_id,
            Subscription.subscriber_type != PrincipalType.USER.value,
        ).order_by(Subscription.created_at)
    ).all())


def add_group_watcher(db: Session, group: PrincipalRef, entity_type: str, entity_id: UUID) -> Subscription:
    """Subscribes a group to an entity (idempotent). The caller has validated the group and the actor's right.

    Raises:
        ValueError: If `group` is a user (users subscribe themselves).
    """
    if group.type is PrincipalType.USER:
        raise ValueError("A user subscribes themselves; only a group can be added as a watcher.")
    existing = db.scalar(select(Subscription).where(
        Subscription.subscriber_type == group.type.value, Subscription.subscriber_id == group.id,
        Subscription.entity_type == entity_type, Subscription.entity_id == entity_id,
    ))
    if existing is not None:
        return existing
    subscription = Subscription(
        subscriber_type=group.type.value, subscriber_id=group.id, entity_type=entity_type, entity_id=entity_id,
    )
    db.add(subscription)
    db.flush()
    return subscription


def remove_group_watcher(db: Session, group: PrincipalRef, entity_type: str, entity_id: UUID) -> bool:
    """Removes a group's subscription; True when there was one."""
    existing = db.scalar(select(Subscription).where(
        Subscription.subscriber_type == group.type.value, Subscription.subscriber_id == group.id,
        Subscription.entity_type == entity_type, Subscription.entity_id == entity_id,
    ))
    if existing is None:
        return False
    db.delete(existing)
    return True


def watching_groups_out(db: Session, entity_type: str, entity_id: UUID) -> list[PrincipalOut]:
    """The groups watching an entity, resolved for display (with their current member counts)."""
    subscriptions = list_group_watchers(db, entity_type, entity_id)
    labels = principal_labels(db, [(s.subscriber_type, s.subscriber_id) for s in subscriptions])
    return [labels[(s.subscriber_type, s.subscriber_id)] for s in subscriptions]


def add_watching_group(
    db: Session, project: Project, entity_type: str, entity_id: UUID, group: PrincipalRef, actor: User
) -> list[PrincipalOut]:
    """Adds a group as a watcher of a requirement or change request in `project`, audit-logs and commits.

    Raises:
        HTTPException: 400 for a user, a group of another organisation, or a project group of another project.
    """
    if group.type is PrincipalType.USER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a group can be added as a watcher; users follow for themselves.")
    validate_principal(db, group, organization_id=project.organization_id, project_id=project.id, field="group")
    add_group_watcher(db, group, entity_type, entity_id)
    log_event(
        db, entity_type=entity_type, entity_id=entity_id, action="watcher_added", actor_id=actor.id,
        project_id=project.id, detail={"group": {"type": group.type.value, "id": str(group.id)}},
    )
    db.commit()
    return watching_groups_out(db, entity_type, entity_id)


def remove_watching_group(
    db: Session, project: Project, entity_type: str, entity_id: UUID, group: PrincipalRef, actor: User
) -> list[PrincipalOut]:
    """Removes a group from an entity's watchers (a no-op when it was not watching), audit-logs and commits."""
    if remove_group_watcher(db, group, entity_type, entity_id):
        log_event(
            db, entity_type=entity_type, entity_id=entity_id, action="watcher_removed", actor_id=actor.id,
            project_id=project.id, detail={"group": {"type": group.type.value, "id": str(group.id)}},
        )
    db.commit()
    return watching_groups_out(db, entity_type, entity_id)


def remove_subscriptions_and_favorites_for_projects(db: Session, user_id: UUID, project_ids: list[UUID]) -> None:
    """Deletes a user's `Subscription` rows for any requirement/change
    request under the given projects, and their `FavoriteProject` rows for
    those projects.

    Call this whenever a user loses access to a project or organisation
    (leaving, having a role revoked, being deactivated) — otherwise a stale
    subscription keeps triggering notifications containing real project
    content (a comment excerpt, a change-request title) for an entity the
    user can no longer view at all, since `get_subscriber_ids` has no access
    check of its own and `Notification` rows are visible to their owner
    regardless of the project's current membership.
    """
    if not project_ids:
        return
    requirement_ids = db.scalars(select(Requirement.id).where(Requirement.project_id.in_(project_ids))).all()
    cr_ids = db.scalars(select(ChangeRequest.id).where(ChangeRequest.project_id.in_(project_ids))).all()
    entity_ids = list(requirement_ids) + list(cr_ids)
    if entity_ids:
        db.execute(
            Subscription.__table__.delete().where(
                Subscription.subscriber_type == PrincipalType.USER.value, Subscription.subscriber_id == user_id,
                Subscription.entity_id.in_(entity_ids),
            )
        )
    db.execute(
        FavoriteProject.__table__.delete().where(
            FavoriteProject.user_id == user_id, FavoriteProject.project_id.in_(project_ids)
        )
    )


def get_subscriber_ids(db: Session, entity_type: str, entity_id: UUID, *, exclude_user_id: UUID) -> list[UUID]:
    """Returns the user ids to notify for an entity, excluding the given user
    (typically the comment's own author, who doesn't need a notification
    about their own comment).

    A user subscribed directly is included as before. A watching group contributes its members as
    they are now (so a membership change takes effect at once), limited to active users who can
    still view the entity's project: unlike a direct subscription, which is deleted when its user
    loses access (`remove_subscriptions_and_favorites_for_projects`), a group can include people
    with no access to this project at all.
    """
    rows = db.execute(
        select(Subscription.subscriber_type, Subscription.subscriber_id).where(
            Subscription.entity_type == entity_type, Subscription.entity_id == entity_id,
        )
    ).all()
    user_ids = {i for t, i in rows if t == PrincipalType.USER.value}
    groups = [PrincipalRef(type=PrincipalType(t), id=i) for t, i in rows if t != PrincipalType.USER.value]
    if groups:
        project_id = db.scalar(
            select(ChangeRequest.project_id).where(ChangeRequest.id == entity_id) if entity_type == "change_request"
            else select(Requirement.project_id).where(Requirement.id == entity_id)
        )
        members = principal_recipients(db, groups)
        if project_id is not None:
            members &= get_project_member_user_ids(db, project_id)
        else:
            members = set()
        user_ids |= members
    user_ids.discard(exclude_user_id)
    return sorted(user_ids)
