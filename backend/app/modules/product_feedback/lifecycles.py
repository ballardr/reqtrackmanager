"""
Module: modules.product_feedback.lifecycles

The Enhancement request state path as a `LifecycleDefinition`, so a project can turn off Under review and an
organisation can require it (`services.lifecycles`).

Responsibilities:
- Build the definition from `service.ALLOWED_TRANSITIONS` (one source) with the formal labels.
- Declare Under review optional.

Dependencies: `service`, `labels`, `services.lifecycles`.
"""

from __future__ import annotations

from app.modules.product_feedback import service as s
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum

LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.REQUEST_ARTEFACT_TYPE: LifecycleDefinition(
        label="Enhancement request", path=("new", "under_review", "accepted", "delivered"),
        transitions=table_from_enum(s.ALLOWED_TRANSITIONS), labels=REQUEST_STATUS_LABEL,
        optional=("under_review",),
    ),
}
