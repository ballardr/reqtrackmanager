"""
Module: services.membership_notifications

Tells a project's managers when someone *without* a manager/administrator
role on that project changed its membership through an org-level route
(docs/plans/platform-enhancements-2026-10-plan.md Phase 2).

Responsibilities:
- Decide whether an actor bypassed the project's own managers
  (`actor_bypasses_project_managers`), evaluated *before* the mutation so a
  self-revocation cannot hide the bypass.
- Notify every effective project manager/administrator except the actor
  (`notify_managers_of_member_change`), merging repeated changes by the same
  actor into one unread notification so a bulk add does not spam managers.

Design decisions:
- Recipients come from `rbac.get_project_users_by_role`, so inherited and
  group-derived managers count, matching change-request notification targeting.
- Coalescing keys on (recipient, type, project, actor) for unread rows created
  within `COALESCE_WINDOW`; the body keeps one line per change, capped, so no
  schema change is needed to carry a count.
- The audit event the caller already writes stays the system of record; this
  is a detective control, never a gate.

Dependencies: `services.notifications.notify`, `services.rbac`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectRole
from app.models.notification import Notification, NotificationType
from app.models.project import Project
from app.models.user import User
from app.services.notifications import notify
from app.services.rbac import get_effective_project_roles, get_project_users_by_role

COALESCE_WINDOW = timedelta(minutes=10)
MAX_BODY_LINES = 20
_OVERFLOW_LINE = "…and further changes."
_MANAGER_ROLES = frozenset({ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR})


def actor_bypasses_project_managers(db: Session, actor: User, project: Project) -> bool:
    """Whether `actor` holds no manager/administrator role on `project`.

    Args:
        db: Active session.
        actor: The user performing the membership change.
        project: The project being changed.

    Returns:
        True when the actor passed the endpoint gate through an org-level
        route (org admin or a `grant_roles` permission) rather than as one of
        the project's own managers, resolving inherited and group-derived
        roles. Call before mutating, since the change may alter the answer.
    """
    return not (get_effective_project_roles(db, actor.id, project.id) & _MANAGER_ROLES)


def _change_line(verb: str, target: str, role: ProjectRole | None, detail: str) -> str:
    """Formats one change as a body line, e.g. "Added Bo as member to project group QA"."""
    parts = [verb, target]
    if role is not None:
        parts.append(f"as {role.value.replace('_', ' ')}")
    if detail:
        parts.append(detail)
    return " ".join(parts)


def notify_managers_of_member_change(
    db: Session, *, project: Project, actor: User, verb: str, target: str,
    role: ProjectRole | None = None, detail: str = "",
) -> None:
    """Notifies the project's managers of a membership change made by a non-manager.

    Args:
        db: Active session; the caller commits.
        project: The project whose membership changed.
        actor: The user who made the change (never notified).
        verb: Past-tense action shown to managers, e.g. "Added", "Removed", "Invited".
        target: Display text for the user/group affected.
        role: The project role granted or revoked, if the change is a role grant/revoke.
        detail: Optional trailing phrase, e.g. "to project group QA" for a group membership change.

    Side effects:
        Creates one `Notification` per recipient, or appends a line to that
        recipient's unread notification for the same actor and project created
        within `COALESCE_WINDOW`. Recipients are every effective project
        manager/administrator minus the actor; none means nothing is sent.
    """
    recipient_ids = (
        get_project_users_by_role(db, project.id, ProjectRole.PROJECT_MANAGER)
        | get_project_users_by_role(db, project.id, ProjectRole.PROJECT_ADMINISTRATOR)
    ) - {actor.id}
    if not recipient_ids:
        return

    line = _change_line(verb, target, role, detail)
    title = f"{actor.display_name} changed the members of {project.name}"
    cutoff = datetime.now(UTC) - COALESCE_WINDOW
    db.flush()  # sessions here run with autoflush off; make earlier same-transaction rows visible to the lookup
    recipients = db.scalars(select(User).where(User.id.in_(recipient_ids)).order_by(User.id)).all()
    for recipient in recipients:
        existing = db.scalar(
            select(Notification)
            .where(
                Notification.user_id == recipient.id,
                Notification.type == NotificationType.PROJECT_MEMBERS_CHANGED_BY_ORG,
                Notification.project_id == project.id,
                Notification.entity_type == "user",
                Notification.entity_id == str(actor.id),
                Notification.read_at.is_(None),
                Notification.created_at >= cutoff,
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        if existing is None:
            notify(
                db, recipient, notification_type=NotificationType.PROJECT_MEMBERS_CHANGED_BY_ORG,
                title=title, body=line, project_id=project.id, entity_type="user", entity_id=str(actor.id),
                actor_id=actor.id,
            )
            continue
        lines = existing.body.split("\n") if existing.body else []
        if len(lines) < MAX_BODY_LINES:
            lines.append(line)
        elif lines[-1] != _OVERFLOW_LINE:
            lines.append(_OVERFLOW_LINE)
        existing.body = "\n".join(lines)
