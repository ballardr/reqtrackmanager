"""
Module: services.requirement_types

The requirement type vocabulary (`REQUIREMENT_TYPES`) and what a requirement does with it.

Responsibilities:
- The two-tier list (organisation base list, a project's overrides, hide and restore of organisation defaults, nested
  fallback to the nearest configured ancestor) as a `TypeVocabulary`.
- Seed the default list, ranked 1 to 3, for a new organisation (`seed_org_defaults`).
- Resolve the type id a payload names to the project type row a version stores (`resolve_requirement_type`).
- Read the type names of many versions at once (`type_names`) and the type name of each requirement in bulk for a
  record sub-type (`requirement_subtypes`).

Design decisions:
- The list order is for display; `rank` is the priority (lower is higher, equal ranks are peers, null is unranked) that
  ordering and traceability rules use. Which type must trace to which stays a traceability rule.
- A project with no configuration of its own shows its nearest configured ancestor's list, then the organisation's.
- An organisation type is never deleted while a project row references it (`TypeVocabulary.delete_org_type`).
- A version references a project type row only; `org_type_in_use` is therefore always false.

Dependencies: `models.requirement`, `models.requirement_type`, `services.type_vocabulary`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_type import ProjectRequirementType, RequirementTypeDefinition
from app.services.project_hierarchy import get_project_chain_ids
from app.services.type_vocabulary import TypeVocabulary

DEFAULT_REQUIREMENT_TYPES: tuple[str, ...] = ("Business Requirement", "Stakeholder Requirement", "Project Requirement")

#: The highest rank a type may have (a guard against a typo, not a design limit).
MAX_RANK = 1000


def check_rank(value: Any) -> int | None:
    """Validates a type's rank: a whole number from 1 to `MAX_RANK`, or nothing (unranked).

    Raises:
        ValueError: If the value is not a whole number in range.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RANK:
        raise ValueError(f"A rank must be a whole number from 1 to {MAX_RANK}.")
    return value


REQUIREMENT_TYPES = TypeVocabulary(
    kind="requirement_type",
    label="Requirement type",
    org_model=RequirementTypeDefinition,
    project_model=ProjectRequirementType,
    default_names=DEFAULT_REQUIREMENT_TYPES,
    org_type_in_use=lambda db, type_id: False,
    project_type_in_use=lambda db, type_id: db.scalar(
        select(RequirementVersion.id).where(RequirementVersion.project_type_id == type_id).limit(1)
    ) is not None,
    inherit_from_ancestors=True,
    extra_columns=("rank",),
    clean_extra=lambda column, value: check_rank(value),
)


def seed_org_defaults(db: Session, organization_id: uuid.UUID) -> None:
    """Gives a new organisation the default requirement types (`run_on_org_created_hooks`; the caller commits)."""
    for position, name in enumerate(DEFAULT_REQUIREMENT_TYPES):
        db.add(RequirementTypeDefinition(
            organization_id=organization_id, name=name, sort_order=position, is_active=True, rank=position + 1,
        ))


def resolve_requirement_type(db: Session, project: Project, type_id: uuid.UUID | None) -> uuid.UUID | None:
    """Resolves a payload's type id (an `EffectiveType.id` of the project's list) to the project type row a version
    stores, creating the passthrough row the first time an organisation type is chosen.

    Args:
        db: Active session (a passthrough row may be added; the caller commits).
        project: The requirement's project.
        type_id: The chosen entry, or `None` for an untyped requirement.

    Returns:
        The project type row id, or `None`.

    Raises:
        ValueError: If the id is not an enabled type of the project's list.
    """
    if type_id is None:
        return None
    return REQUIREMENT_TYPES.usable_row_id(db, project.id, project.organization_id, type_id)


def matching_type_row_ids(db: Session, project_id: uuid.UUID, names: Iterable[str]) -> list[uuid.UUID]:
    """The project type rows, of the project or an ancestor whose list it inherits, whose effective name is one of
    `names` (compared without regard to case), for a list filter by type name.

    Args:
        db: Active session.
        project_id: The project whose requirements are listed.
        names: Type names.

    Returns:
        The matching row ids (empty when none matches, so the filter then keeps nothing).
    """
    wanted = {n.strip().lower() for n in names if n.strip()}
    if not wanted:
        return []
    chain = get_project_chain_ids(db, project_id)
    rows = db.execute(
        select(ProjectRequirementType.id, ProjectRequirementType.name_override, RequirementTypeDefinition.name)
        .outerjoin(RequirementTypeDefinition, RequirementTypeDefinition.id == ProjectRequirementType.org_type_id)
        .where(ProjectRequirementType.project_id.in_(chain))
    ).all()
    return [row_id for row_id, override, org_name in rows if (override if override is not None else org_name or "").lower() in wanted]


def type_names(db: Session, project_type_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """The effective name of each project type row, in bulk.

    Args:
        db: Active session.
        project_type_ids: Project type row ids (`None` entries are skipped).

    Returns:
        `{row id: name}`; a row that no longer resolves to a name is absent.
    """
    wanted = {t for t in project_type_ids if t is not None}
    if not wanted:
        return {}
    names = REQUIREMENT_TYPES.display_names(db, [(None, row_id) for row_id in wanted])
    return {row_id: name for (_org, row_id), name in names.items() if row_id is not None and name is not None}


def type_ranks(db: Session, project_type_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, int]:
    """The effective rank of each project type row (the row's own, else its organisation type's), in bulk.

    Args:
        db: Active session.
        project_type_ids: Project type row ids (`None` entries are skipped).

    Returns:
        `{row id: rank}`; an unranked type is absent.
    """
    wanted = {t for t in project_type_ids if t is not None}
    if not wanted:
        return {}
    rows = db.execute(
        select(ProjectRequirementType.id, ProjectRequirementType.rank, RequirementTypeDefinition.rank)
        .outerjoin(RequirementTypeDefinition, RequirementTypeDefinition.id == ProjectRequirementType.org_type_id)
        .where(ProjectRequirementType.id.in_(wanted))
    ).all()
    return {row_id: own if own is not None else inherited for row_id, own, inherited in rows if own is not None or inherited is not None}


def requirement_subtypes(
    db: Session, project_id: uuid.UUID, record_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Each requirement's type name (`RecordSubtypeResolver`), for the requirements of `project_id` among `record_ids`.

    Args:
        db: Active session.
        project_id: The project the requirements belong to.
        record_ids: Requirement ids.

    Returns:
        `{requirement id: type name}`; an untyped requirement is absent.
    """
    rows = db.execute(
        select(Requirement.id, RequirementVersion.project_type_id)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.id.in_(record_ids), Requirement.project_id == project_id,
            RequirementVersion.valid_to.is_(None), RequirementVersion.project_type_id.is_not(None),
        )
    ).all()
    names = type_names(db, [type_id for _requirement_id, type_id in rows])
    return {requirement_id: names[type_id] for requirement_id, type_id in rows if type_id in names}


def copy_project_requirement_types(db: Session, source: Project, target: Project):
    """Copies `source`'s own requirement type configuration (overrides, project-local types, hidden defaults) to
    `target`, a project made from a template (not committed).

    Args:
        db: Active session.
        source: The template project.
        target: The new project.

    Returns:
        The `NameResolver` of the target's list, for storing each copied requirement's type by name
        (`NameResolver.row_id`).
    """
    from app.services.bundle_common import BundleImportWarnings
    from app.services.vocabulary_bundle import NameResolver, export_project_list

    exported = export_project_list(db, source, REQUIREMENT_TYPES)
    resolver = NameResolver(db, REQUIREMENT_TYPES, target.organization_id, target, BundleImportWarnings(), "requirement type")
    resolver.import_project_rows(exported["rows"])
    resolver.hide(exported["hidden"])
    return resolver
