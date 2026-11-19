"""
Module: services.notification_targets

Declares where each core notification type takes the person who opens it, as a
target kind (a short name such as `delivery_status`) rather than a URL. The
browser turns a kind into a page (`frontend/src/modules/notificationTargets.ts`),
so the bell, the notification list, the email and the digest share one resolver
and no module's route templates are copied onto the server.

Responsibilities:
- `CORE_TARGET_KINDS`: the kinds the core frontend resolver knows.
- `CORE_NOTIFICATION_TARGETS`: the ordered kinds of every core type that no
  module owns. A type lists several kinds when the data decides: the first kind
  whose data the notification carries wins, and the notification detail page is
  the fallback for a stored notification that carries none of it.
- `subject_available`: whether the person may still open the notification's subject.

Design decisions:
- The Compliance types are members of the core enum but belong to the Compliance
  module, so that module declares their kinds (`ModuleDefinition.notification_targets`)
  and the kinds only it can resolve (`notification_target_kinds`); core never names them.
  `registry.get_all_notification_targets` merges both.
- `detail` is implicit: every notification can open its detail page, so no type lists it
  unless that is its only page (an announcement).

External dependencies: `services.link_nesting` for project access, `services.rbac` for organisation membership.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.services.link_nesting import can_open_project
from app.services.rbac import get_effective_org_roles

#: The kinds the core frontend resolver can open.
CORE_TARGET_KINDS: frozenset[str] = frozenset(
    {
        "record",
        "delivery_status",
        "project",
        "project_members",
        "organization",
        "organization_files",
        "policy",
        "report_run",
        "preferences_security",
        "server_files",
        "detail",
    }
)

_STAGE_TYPES = (
    "stage_scoping", "stage_review", "stage_approved", "stage_completed", "stage_review_auto_approved",
    "stage_phase_upcoming", "stage_phase_overdue", "stage_phase_completed",
)
_RECORD_TYPES = (
    "change_request_submitted", "stakeholder_input_requested", "change_request_approved", "change_request_rejected",
    "requirements_updated", "comment_added", "requirement_review_due",
)

#: Ordered target kinds per core notification type (module-owned types are declared by their module).
CORE_NOTIFICATION_TARGETS: dict[str, tuple[str, ...]] = {
    **{key: ("delivery_status",) for key in _STAGE_TYPES},
    **{key: ("record",) for key in _RECORD_TYPES},
    "project_joined": ("project",),
    "permission_granted": ("organization", "project"),
    "permission_revoked": ("project",),
    "project_members_changed_by_org": ("project_members",),
    "password_changed": ("preferences_security",),
    "policy_published": ("policy",),
    "policy_acknowledgement_required": ("policy",),
    "report_run_finished": ("report_run",),
    "storage_limit_near": ("organization_files",),
    "system_storage_alert": ("server_files",),
    "system_announcement": ("detail",),
}


def subject_available(db: Session, user_id: uuid.UUID, notification: Notification) -> bool:
    """Whether the person can still open what the notification is about.

    A revoked project role, a removed organisation membership or a token whose scope
    excludes the project all leave a notification whose page would refuse the person,
    so the detail page says so instead of ending on an error.

    Args:
        db: Active session (read only).
        user_id: The recipient.
        notification: The notification.

    Returns:
        False when the notification names a project the person cannot open, or an
        organisation they no longer belong to; true otherwise.
    """
    if notification.project_id is not None and not can_open_project(db, user_id, notification.project_id):
        return False
    if notification.entity_type == "organization" and notification.entity_id:
        try:
            organization_id = uuid.UUID(notification.entity_id)
        except ValueError:
            return False
        return bool(get_effective_org_roles(db, user_id, organization_id))
    return True
