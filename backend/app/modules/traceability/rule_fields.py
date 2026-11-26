"""
Module: modules.traceability.rule_fields

The record properties a traceability rule's "applies when" condition can test, registered as
`ModuleDefinition.rule_condition_fields` (`modules.seams.RuleConditionField`).

Responsibilities:
- Read each property for many records of one project in a bounded number of statements: the record's sub-type, the rank of
  a requirement's type, the component and category it is placed in, its tags and its status.
- Offer the values the rule editor can choose from (`options`) where the property has a closed set.

Design decisions:
- A property is a value read through the services that own it (`modules.registry.resolve_record_subtypes`,
  `services.requirement_types`, `services.placements`, `services.tags`, the summary provider's status), never through a
  query on another module's tables, so a new record type needs nothing here.
- Component, category and tag are tested by name, not id: a component belongs to one project, so an id could not serve a
  rule an organisation profile owns, and a name carries across the projects a profile reaches and through a bundle.
- A record placed in several components holds each as a value, and a condition holds when any of them satisfies it.
- A module adds a property of its own by registering another `RuleConditionField`; this file holds only the properties
  every record type has.

Dependencies: `modules.registry`, `services.placements`, `services.tags`, `services.requirement_types`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectCategory, ProjectComponent
from app.modules import registry
from app.modules.seams import RuleConditionField
from app.services import placements, record_summaries, requirement_types, tags
from app.services.project_hierarchy import resolve_effective_action_types

SUBTYPE = "subtype"
REQUIREMENT_TYPE_RANK = "requirement_type_rank"
COMPONENT = "component"
CATEGORY = "category"
TAG = "tag"
STATUS = "status"


def _subtypes(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    return {record_id: [name] for record_id, name in registry.resolve_record_subtypes(db, project_id, artefact_type, ids).items()}


def subtype_options(db: Session, organization_id: uuid.UUID, artefact_type: str, project_id: uuid.UUID | None = None) -> list[str]:
    """The sub-type names a rule may name for a record type.

    Args:
        db: Active session (read only).
        organization_id: The organisation.
        artefact_type: The record type.
        project_id: The project whose own vocabulary applies, or `None` for the organisation's (a profile's rule).

    Returns:
        The names: a requirement's types and an action's types as the project (or organisation) offers them, otherwise the
        names the type's module registers (`registry.get_subtypes`); empty when the type has no sub-types.
    """
    if artefact_type == "requirement":
        if project_id is None:
            return [t.name for t in requirement_types.REQUIREMENT_TYPES.active_org_types(db, organization_id)]
        return [t.name for t in requirement_types.REQUIREMENT_TYPES.resolve_effective(db, project_id, organization_id) if t.is_enabled]
    if artefact_type == "requirement_action":
        if project_id is None:
            return []
        return [a.name for a in resolve_effective_action_types(db, project_id)]
    return registry.get_subtypes(db, organization_id, artefact_type)


def _subtype_options(db: Session, project_id: uuid.UUID, artefact_type: str) -> Sequence[str]:
    project = db.get(Project, project_id)
    return [] if project is None else subtype_options(db, project.organization_id, artefact_type, project_id)


def _ranks(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    return {record_id: [rank] for record_id, rank in requirement_types.requirement_ranks(db, project_id, ids).items()}


def _places(
    db: Session, artefact_type: str, ids: Sequence[uuid.UUID], *, categories: bool,
) -> Mapping[uuid.UUID, Sequence[str | int]]:
    """The component (or category) names of each record's places, in one read of the places and one of the names."""
    pairs = placements.pairs_for_records(db, artefact_type, ids)
    wanted = {(p.category_id if categories else p.component_id) for ps in pairs.values() for p in ps} - {None}
    if not wanted:
        return {}
    model = ProjectCategory if categories else ProjectComponent
    names = {row_id: name for row_id, name in db.execute(select(model.id, model.name).where(model.id.in_(wanted)))}
    found: dict[uuid.UUID, list[str | int]] = defaultdict(list)
    for record_id, record_pairs in pairs.items():
        for pair in record_pairs:
            name = names.get(pair.category_id if categories else pair.component_id)
            if name is not None and name not in found[record_id]:
                found[record_id].append(name)
    return found


def _components(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    return _places(db, artefact_type, ids, categories=False)


def _categories(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    return _places(db, artefact_type, ids, categories=True)


def _component_options(db: Session, project_id: uuid.UUID, artefact_type: str) -> Sequence[str]:
    return list(db.scalars(select(ProjectComponent.name).where(ProjectComponent.project_id == project_id).order_by(ProjectComponent.name)))


def _category_options(db: Session, project_id: uuid.UUID, artefact_type: str) -> Sequence[str]:
    return list(db.scalars(select(ProjectCategory.name).where(ProjectCategory.project_id == project_id).order_by(ProjectCategory.name)))


def _tags(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    return {record_id: list(names) for record_id, names in tags.tag_names_for_records(db, artefact_type, ids).items() if names}


def _statuses(db: Session, project_id: uuid.UUID, artefact_type: str, ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, Sequence[str | int]]:
    found = record_summaries.read_summaries(db, project_id, artefact_type, ids)
    return {record_id: [summary.status] for record_id, summary in found.items() if summary.status}


FIELDS: tuple[RuleConditionField, ...] = (
    RuleConditionField(key=SUBTYPE, label="Sub-type", value_kind="text", values=_subtypes, options=_subtype_options),
    RuleConditionField(
        key=REQUIREMENT_TYPE_RANK, label="Requirement type rank", value_kind="number", values=_ranks,
        artefact_types=("requirement",),
    ),
    RuleConditionField(key=COMPONENT, label="Component", value_kind="text", values=_components, options=_component_options),
    RuleConditionField(key=CATEGORY, label="Category", value_kind="text", values=_categories, options=_category_options),
    RuleConditionField(key=TAG, label="Tag", value_kind="text", values=_tags),
    RuleConditionField(key=STATUS, label="Status", value_kind="text", values=_statuses),
)
