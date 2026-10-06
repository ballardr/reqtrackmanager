"""
Module: services.project_link_types

Writes for the project level of the link-type vocabulary: a project's own link
types, its hide/show choices, and the organisation switch that forbids all of it.

Responsibilities:
- Create, rename and re-order a project's local link types, rejecting a name the
  organisation or an ancestor already provides (`create_project_link_type`,
  `update_project_link_type`).
- Hide or re-show a link type for a project (`set_visibility`).
- Read and set the organisation's customisation locks (`get_lock_summary`,
  `set_customisation_locks`).
- Refuse every project-level write while the organisation has locked
  customisation (`assert_not_locked`).

Design decisions:
- A name is unique within one scope (project, or organisation-wide) and, at
  creation, also against what the organisation and ancestors already provide:
  creating a clashing name is rejected up front, so shadowing only arises when an
  ancestor later adds a name a descendant already uses (and then the ancestor's
  admin learns nothing about the descendant).
- Hiding never deletes: a visibility row only removes the type from pickers.
- The lock is a list of keys (`PROJECT_CUSTOMISATION_LOCK_KEYS`), not a boolean per
  vocabulary, so the same switch can later cover other vocabularies. Locking leaves
  every project-level row dormant and unlocking restores it.

Dependencies: `services.link_type_scope` (scope resolution), `services.link_types`
(restriction validation), `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import LinkFlow
from app.models.organization import Organization
from app.models.project import Project
from app.models.requirement_link_type import ProjectLinkTypeVisibility, RequirementLinkTypeDefinition
from app.models.user import User
from app.services.audit import log_event
from app.services.link_type_scope import (
    PROJECT_CUSTOMISATION_LOCK_KEYS,
    is_customisation_locked,
    resolve_link_type_scope,
)
from app.services.link_types import normalise_artefact_types

LOCKED_MESSAGE = "Your organisation uses one shared set of link types, so projects cannot change them."


def assert_not_locked(db: Session, project: Project) -> None:
    """Raises 403 when the organisation forbids projects from customising link types."""
    if is_customisation_locked(db, project.organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, LOCKED_MESSAGE)


def validated_restrictions(
    source_types: Collection[str] | None, target_types: Collection[str] | None
) -> tuple[list[str] | None, list[str] | None]:
    """Normalises a link type's source/target restrictions, or raises 422 naming the unknown type."""
    try:
        return (
            normalise_artefact_types(source_types, field_name="allowed_source_types"),
            normalise_artefact_types(target_types, field_name="allowed_target_types"),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _check_name(db: Session, project: Project, forward_name: str, exclude_id: uuid.UUID | None) -> None:
    """Raises 400 unless `forward_name` is free in the project's own scope and not
    already provided by the organisation or an ancestor (compared case-insensitively)."""
    wanted = forward_name.casefold()
    for scoped in resolve_link_type_scope(db, project):
        if scoped.link_type.id == exclude_id or scoped.link_type.forward_name.casefold() != wanted:
            continue
        if scoped.owner_project_id == project.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project already has a link type with this forward name.")
        provider = "your organisation" if scoped.owner_project_id is None else "a parent project"
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'A link type named "{scoped.link_type.forward_name}" is already provided by {provider}; '
            "use that one or choose a different name.",
        )


def create_project_link_type(
    db: Session,
    project: Project,
    *,
    forward_name: str,
    reverse_name: str,
    flow: LinkFlow,
    allowed_source_types: Collection[str] | None,
    allowed_target_types: Collection[str] | None,
    actor: User,
) -> RequirementLinkTypeDefinition:
    """Creates a link type local to `project` (usable there and in every descendant).

    Args:
        db: Active session; the row is flushed, not committed.
        project: The owning project.
        forward_name / reverse_name: The two directional phrases.
        flow: Its direction in a traceability chain.
        allowed_source_types / allowed_target_types: Optional artefact-type restriction.
        actor: The acting user, for audit.

    Returns:
        The new type.

    Raises:
        HTTPException: 403 the organisation locks customisation; 400 the name is
            taken here or provided by the organisation/an ancestor; 422 a
            restriction names an unknown artefact type.
    """
    assert_not_locked(db, project)
    sources, targets = validated_restrictions(allowed_source_types, allowed_target_types)
    _check_name(db, project, forward_name, None)
    count = db.scalar(
        select(func.count()).select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.project_id == project.id)
    ) or 0
    link_type = RequirementLinkTypeDefinition(
        organization_id=project.organization_id, project_id=project.id, forward_name=forward_name,
        reverse_name=reverse_name, sort_order=count, flow=flow, allowed_source_types=sources,
        allowed_target_types=targets,
    )
    db.add(link_type)
    db.flush()
    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="created",
        actor_id=actor.id, organization_id=project.organization_id, project_id=project.id,
        detail={
            "forward_name": forward_name, "reverse_name": reverse_name, "flow": flow.value,
            "allowed_source_types": sources, "allowed_target_types": targets, "scope": "project",
        },
    )
    return link_type


def get_own_link_type(db: Session, project: Project, link_type_id: uuid.UUID) -> RequirementLinkTypeDefinition:
    """The link type if `project` owns it, else 404 (an organisation-wide or an
    ancestor's type is never editable from here)."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    return link_type


def update_project_link_type(
    db: Session,
    project: Project,
    link_type_id: uuid.UUID,
    *,
    forward_name: str,
    reverse_name: str,
    flow: LinkFlow | None,
    restrictions: dict[str, list[str] | None],
    actor: User,
) -> RequirementLinkTypeDefinition:
    """Renames a project-local link type and optionally changes its flow/restrictions.

    Args:
        db: Active session; flushed, not committed.
        project: The owning project.
        link_type_id: The type.
        forward_name / reverse_name: The new phrases.
        flow: The new direction, or `None` to keep it.
        restrictions: `allowed_source_types` and/or `allowed_target_types` to replace
            (a key left out keeps the current value; `None`/empty means any).
        actor: The acting user, for audit.

    Returns:
        The updated type.

    Raises:
        HTTPException: 403 locked; 404 not this project's own type; 400 name clash;
            422 unknown artefact type.
    """
    assert_not_locked(db, project)
    link_type = get_own_link_type(db, project, link_type_id)
    _check_name(db, project, forward_name, link_type.id)
    link_type.forward_name = forward_name
    link_type.reverse_name = reverse_name
    if flow is not None:
        link_type.flow = flow
    if restrictions:
        sources, targets = validated_restrictions(
            restrictions["allowed_source_types"] if "allowed_source_types" in restrictions else link_type.allowed_source_types,
            restrictions["allowed_target_types"] if "allowed_target_types" in restrictions else link_type.allowed_target_types,
        )
        link_type.allowed_source_types = sources
        link_type.allowed_target_types = targets
    db.flush()
    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="renamed",
        actor_id=actor.id, organization_id=project.organization_id, project_id=project.id,
        detail={
            "flow": link_type.flow.value, "allowed_source_types": link_type.allowed_source_types,
            "allowed_target_types": link_type.allowed_target_types, "scope": "project",
        },
    )
    return link_type


def set_visibility(
    db: Session, project: Project, link_type_id: uuid.UUID, hidden: bool | None, actor: User
) -> None:
    """Hides or re-shows a link type for `project`, or clears the project's own choice.

    Args:
        db: Active session; flushed, not committed.
        project: The project making the choice.
        link_type_id: A type the project can reach (organisation-wide, or the
            project's or an ancestor's own, and not shadowed).
        hidden: `True` hides it, `False` shows it (overriding an ancestor's hide),
            `None` removes the project's own choice.
        actor: The acting user, for audit.

    Raises:
        HTTPException: 403 locked; 404 the type is not reachable from this project.
    """
    assert_not_locked(db, project)
    reachable = {s.link_type.id for s in resolve_link_type_scope(db, project) if s.shadowed_by is None}
    if link_type_id not in reachable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    row = db.get(ProjectLinkTypeVisibility, (project.id, link_type_id))
    if hidden is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ProjectLinkTypeVisibility(project_id=project.id, link_type_id=link_type_id, hidden=hidden))
    else:
        row.hidden = hidden
    db.flush()
    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type_id,
        action="visibility_cleared" if hidden is None else ("hidden" if hidden else "shown"),
        actor_id=actor.id, organization_id=project.organization_id, project_id=project.id, detail={},
    )


@dataclass(frozen=True)
class LockSummary:
    """The organisation's customisation locks and what they currently switch off.

    Attributes:
        locks: Vocabularies projects may not customise.
        local_link_type_count: Project-local link types that exist (dormant while locked).
        local_link_type_project_count: Projects that own at least one.
    """

    locks: list[str]
    local_link_type_count: int
    local_link_type_project_count: int


def get_lock_summary(db: Session, organization_id: uuid.UUID) -> LockSummary:
    """The organisation's locks with the size of what locking affects, so the
    consequence is visible before the switch is flipped."""
    organization = db.get(Organization, organization_id)
    row = db.execute(
        select(func.count(), func.count(func.distinct(RequirementLinkTypeDefinition.project_id)))
        .where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.project_id.is_not(None),
        )
    ).one()
    return LockSummary(
        locks=list(organization.project_customisation_locks or []) if organization is not None else [],
        local_link_type_count=row[0], local_link_type_project_count=row[1],
    )


def set_customisation_locks(db: Session, organization_id: uuid.UUID, locks: Collection[str], actor: User) -> LockSummary:
    """Replaces the organisation's customisation locks.

    Args:
        db: Active session; flushed, not committed.
        organization_id: The organisation.
        locks: Keys from `PROJECT_CUSTOMISATION_LOCK_KEYS`.
        actor: The acting org admin, for audit.

    Returns:
        The new summary.

    Raises:
        HTTPException: 404 unknown organisation; 422 an unknown key.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    unknown = sorted(set(locks) - set(PROJECT_CUSTOMISATION_LOCK_KEYS))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown customisation lock(s): {', '.join(unknown)}."
        )
    new = [key for key in PROJECT_CUSTOMISATION_LOCK_KEYS if key in set(locks)]
    previous = list(organization.project_customisation_locks or [])
    organization.project_customisation_locks = new
    db.flush()
    if previous != new:
        log_event(
            db, entity_type="organization", entity_id=organization_id, action="project_customisation_locks_changed",
            actor_id=actor.id, organization_id=organization_id, detail={"from": previous, "to": new},
        )
    return get_lock_summary(db, organization_id)
