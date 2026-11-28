"""
Module: modules.traceability.labels

The formal labels of the module's values that appear in files, reports, search results and notifications.

Responsibilities:
- Name each exception state as a person reads it.

Dependencies: `enums`.
"""

from __future__ import annotations

from app.modules.traceability.enums import ExceptionStatus

EXCEPTION_STATUS_LABEL: dict[str, str] = {
    ExceptionStatus.REQUESTED.value: "Requested",
    ExceptionStatus.APPROVED.value: "Approved",
    ExceptionStatus.REJECTED.value: "Rejected",
    ExceptionStatus.WITHDRAWN.value: "Withdrawn",
    ExceptionStatus.REVOKED.value: "Revoked",
}

EXCEPTION_STATUS_TONE: dict[str, str] = {
    ExceptionStatus.REQUESTED.value: "info",
    ExceptionStatus.APPROVED.value: "accent",
    ExceptionStatus.REJECTED.value: "danger",
    ExceptionStatus.WITHDRAWN.value: "muted",
    ExceptionStatus.REVOKED.value: "danger",
}
