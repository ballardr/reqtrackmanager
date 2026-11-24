"""
Module: modules.decisions.lifecycles

The Decision state path as a `LifecycleDefinition`, so a project can turn off Proposed and Under review and an
organisation can require them (`services.lifecycles`).

Responsibilities:
- Build the definition from the transition table `service.transition` enforces (one source) with the formal labels.
- Declare Proposed and Under review optional and Approved gated: turning the review steps off leaves Draft to
  Approved behind the approver's permission and comment.

Dependencies: `service`, `labels`, `services.lifecycles`.
"""

from __future__ import annotations

from app.modules.decisions import service as s
from app.modules.decisions.labels import DECISION_STATUS_LABEL
from app.modules.registry import LifecycleDefinition
from app.services.lifecycles import table_from_enum

LIFECYCLES: dict[str, LifecycleDefinition] = {
    s.DECISION_ARTEFACT_TYPE: LifecycleDefinition(
        label="Decision", path=("draft", "proposed", "under_review", "approved"),
        transitions=table_from_enum(s._ALLOWED_TRANSITIONS), labels=DECISION_STATUS_LABEL,
        optional=("proposed", "under_review"), gated=("approved",),
    ),
}
