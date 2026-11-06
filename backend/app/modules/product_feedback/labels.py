"""
Module: modules.product_feedback.labels

Human-readable labels for Product Feedback's enum wire values, for reports and API
consumers. Mirrors the frontend's label maps in `frontend/src/modules/product_feedback/types.ts`
by hand. Lookups fall back to the raw value so a newly added member renders rather than crashing.
"""

from __future__ import annotations

REQUEST_STATUS_LABEL: dict[str, str] = {
    "new": "New",
    "under_review": "Under review",
    "accepted": "Accepted",
    "delivered": "Delivered",
    "declined": "Declined",
    "duplicate": "Duplicate",
}

# Badge tones, mirroring the `*_TONE` maps in the frontend types by hand (a test pins them).
REQUEST_STATUS_TONE: dict[str, str] = {
    "new": "info",
    "under_review": "info",
    "accepted": "accent",
    "delivered": "accent",
    "declined": "muted",
    "duplicate": "muted",
}

SUBMISSION_POLICY_LABEL: dict[str, str] = {
    "members": "Any project member",
    "triagers": "Triagers only",
}


def request_status_label(value: str) -> str:
    """Returns the display label for an `EnhancementRequestStatus` value (the raw value if unmapped)."""
    return REQUEST_STATUS_LABEL.get(value, value)
