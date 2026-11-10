"""
Module: services.bundle_approval_state

What a project import does with the approval state a bundle carries.

Responsibilities:
- Count the core records that arrive already approved, decided or voted, for the import's audit event.
- When the organisation does not allow imported approval state (`Organization.allow_imported_approval_state`),
  return every record to a fresh draft before it is written: the core requirements and change requests here, and
  each module's records through the same `template_reset` hook a template copy uses, run inside
  `template_reset.keeping_history()` so archived records and authorship are kept.

Design decisions:
- The default is to allow it, so a restore or a move reproduces the project exactly; an organisation whose
  approvers must not be bypassable switches it off. Neither setting lets a bundle name an approver outside the
  organisation (`bundle_common.UserResolver`).
- The bundle is edited before import, so every import path (the endpoint, an organisation bundle, a merge) uses one rule.

External dependencies: `app.modules.registry` (module bundle hooks), `services.template_reset`.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import ChangeRequestStatus, RequirementStatus
from app.modules.registry import get_all_module_project_bundle_hooks
from app.services.template_reset import keeping_history

_DRAFT = RequirementStatus.DRAFT.value
_CR_DRAFT = ChangeRequestStatus.DRAFT.value


def count_approval_state(data: dict[str, Any]) -> int:
    """How many core requirements and change requests in the bundle arrive beyond draft (approved, reviewed,
    decided, voted or completed)."""
    requirements = sum(
        1 for r in data.get("requirements", [])
        if r.get("is_completed") or any(v.get("status") != _DRAFT for v in r.get("versions", []))
    )
    change_requests = sum(1 for cr in data.get("change_requests", []) if cr.get("status") != _CR_DRAFT or cr.get("votes"))
    return requirements + change_requests


def strip_approval_state(data: dict[str, Any]) -> None:
    """Returns the bundle's records to fresh drafts, in place: requirements, change requests, baselines and reviews
    here, and every module's records through its `template_reset` hook."""
    for requirement in data.get("requirements", []):
        requirement.update(is_completed=False, completed_at=None, completed_by_email=None)
        for version in requirement.get("versions", []):
            version["status"] = _DRAFT
    for cr in data.get("change_requests", []):
        cr.update(status=_CR_DRAFT, submitted_at=None, decided_at=None, decided_by_email=None, decision_note=None, votes=[])
        for task in cr.get("tasks", []):
            task.update(is_done=False, completed_at=None)
    data["baselines"] = []
    data["requirement_reviews"] = []
    with keeping_history():
        for _key, hooks in get_all_module_project_bundle_hooks():
            if hooks.template_reset is not None:
                hooks.template_reset(data)
