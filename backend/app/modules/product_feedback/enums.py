"""
Module: modules.product_feedback.enums

Product Feedback's own vocabulary, kept in this package rather than core.
"""

from __future__ import annotations

import enum


class EnhancementRequestStatus(str, enum.Enum):
    """Lifecycle states of an `EnhancementRequest`.

    `NEW -> UNDER_REVIEW -> ACCEPTED -> DELIVERED` is the main line; `DECLINED` (a reason is
    mandatory) is the other terminal outcome. `DUPLICATE` is set only by merging a request
    into a canonical one, never by a direct transition. The legal moves are
    `service.ALLOWED_TRANSITIONS`.
    """

    NEW = "new"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    DECLINED = "declined"
    DUPLICATE = "duplicate"


class EnhancementRequestScope(str, enum.Enum):
    """Which tier owns a request: a project, or the organisation itself (its inbox)."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class SubmissionPolicy(str, enum.Enum):
    """Who may submit a request in a project: any member who can see the list, or only a triager."""

    MEMBERS = "members"
    TRIAGERS = "triagers"
