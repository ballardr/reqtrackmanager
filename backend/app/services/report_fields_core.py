"""
Module: services.report_fields_core

The `ReportFieldProvider`s for the three core artefact types (requirements, actions, change
requests): what a custom report layout may print or group by for each.

Responsibilities:
- Declare, per core type, the typed fields on top of the search's text fields (component, category,
  level, stage and owner of a requirement; type, assignee and due date of an action; kind and times of
  a change request).

Design decisions:
- Core types register through the same mechanism as module types, in core code because core owns
  them (a module's types are registered by the module, never listed here).
- A requirement is read through its current version (`valid_to IS NULL`), the joins coming from the
  search declaration so they are written once.
- A requirement's component and category are their names, looked up by correlated subquery, so a
  layout can group by the words a person sees.
- Review notes, comments and file contents are not fields; free text is limited to what the search
  already treats as a vetted, opt-in column.

Dependencies: the core models and `services.search_core` (the joins), `services.report_fields` (builders).
"""

from __future__ import annotations

from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest
from app.models.enums import ChangeRequestKind, RequirementLevel
from app.models.project import ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.modules.registry import ReportFieldProvider
from app.services.report_fields import (
    bool_field,
    date_field,
    enum_field,
    from_search,
    instant_field,
    name_lookup_field,
    principal_field,
)
from app.services.search_core import CORE_SEARCH_PROVIDERS

CORE_REPORT_FIELDS: dict[str, ReportFieldProvider] = {
    "requirement": from_search(
        CORE_SEARCH_PROVIDERS["requirement"],
        name_lookup_field(
            "component", "Component", ProjectComponent.name, ProjectComponent.id, Requirement.component_id,
            ProjectComponent.project_id,
        ),
        name_lookup_field(
            "category", "Category", ProjectCategory.name, ProjectCategory.id, Requirement.category_id,
            ProjectCategory.project_id,
        ),
        name_lookup_field(
            "target_stage", "Target stage", ProjectStage.name, ProjectStage.id, RequirementVersion.target_stage_id,
            ProjectStage.project_id,
        ),
        enum_field("level", "Level", RequirementVersion.level, RequirementLevel),
        principal_field("owner", "Owner", RequirementVersion.owner_type, RequirementVersion.owner_id),
        principal_field("reviewer", "Reviewer", RequirementVersion.reviewer_type, RequirementVersion.reviewer_id),
        date_field("review_date", "Review date", RequirementVersion.review_date),
        bool_field("is_completed", "Completed", Requirement.is_completed),
        instant_field("completed_at", "Completed at", Requirement.completed_at),
        math_fields=("description", "reasoning", "clarification"),
    ),
    "requirement_action": from_search(
        CORE_SEARCH_PROVIDERS["requirement_action"],
        name_lookup_field(
            "action_type", "Action type", ActionTypeDefinition.name, ActionTypeDefinition.id, RequirementAction.action_type_id,
            ActionTypeDefinition.project_id,
        ),
        principal_field("assignee", "Assignee", RequirementAction.assignee_type, RequirementAction.assignee_id),
        date_field("due_date", "Due date", RequirementAction.due_date),
        instant_field("completed_at", "Completed at", RequirementAction.completed_at),
    ),
    "change_request": from_search(
        CORE_SEARCH_PROVIDERS["change_request"],
        enum_field("kind", "Kind", ChangeRequest.kind, ChangeRequestKind),
        instant_field("submitted_at", "Submitted at", ChangeRequest.submitted_at),
        instant_field("decided_at", "Decided at", ChangeRequest.decided_at),
    ),
}

__all__ = ["CORE_REPORT_FIELDS"]
