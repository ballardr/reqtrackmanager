"""
Module: services.link_authoring

Generic link creation and removal for any artefact of a project, the one
authorisation point for `routers.artefact_links`' write endpoints.

Responsibilities:
- Offer the link types usable from an artefact (`usable_options`).
- Create a link (`create_link_for_artefact`) after checking: both ends are
  visible records of the project (module enabled, `view` held), the caller holds
  `manage` on the page artefact's type, the link type belongs to the project's
  organisation and is not dedicated, the link type's restriction and both ends'
  artefact-type rules allow it, and no approved requirement is being linked in a
  project that requires a change request for that.
- Remove a link (`delete_link_for_artefact`) under the same gates.

Design decisions:
- Reuses `ArtefactResolver` (the link graph's visibility rule) so authoring and
  display can never disagree about what a user may see.
- Both ends of a requirement are gated by the change-request rule, stricter than
  the legacy requirement endpoint (which only checked its own end), because a
  link on an approved requirement is the thing that rule protects.
- A symmetric link type counts a reversed pair as a duplicate.

Dependencies: `services.link_graph` (visibility), `services.link_types` (rules),
`services.relationships` (storage), `services.requirements` (lock state),
`services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import (
    ArtefactSummary,
    get_all_registered_artefact_types,
    get_artefact_type_label,
    get_module_registry,
)
from app.services.audit import log_event
from app.services.link_graph import ArtefactResolver
from app.services.link_types import LinkRuleError, LinkTypeOption, list_usable_link_types
from app.services.relationships import create_link, delete_link, get_link_between
from app.services.requirements import get_current_version, is_locked, requires_change_request_for_links

_REQUIREMENT = ArtefactType.REQUIREMENT.value


@dataclass(frozen=True)
class CreatedLink:
    """A created link and how it reads from the page artefact's side."""

    link: ArtefactLink
    link_type: RequirementLinkTypeDefinition
    outgoing: bool
    other_type: str
    other: ArtefactSummary


def linkable_types_for_project(db: Session, project: Project) -> set[str]:
    """Registered artefact types whose owning module is enabled for `project` (core types always)."""
    from app.modules.registry import is_module_enabled_for_project

    types = {ArtefactType.REQUIREMENT.value, ArtefactType.REQUIREMENT_ACTION.value}
    for definition in get_module_registry().values():
        if definition.artefact_types and is_module_enabled_for_project(db, project.id, definition.key):
            types.update(definition.artefact_types)
    return types


def usable_options(
    db: Session, project: Project, artefact_type: str, other_type: str | None
) -> list[LinkTypeOption]:
    """Link types usable from an artefact of `artefact_type` in `project`.

    Args:
        db: Active session (read only).
        project: The project; supplies the organisation and enabled modules.
        artefact_type: The page artefact's type.
        other_type: Narrow to options that can reach this type.

    Returns:
        The usable options (dedicated types are never offered).
    """
    return list_usable_link_types(
        db, project.organization_id, artefact_type,
        candidate_types=linkable_types_for_project(db, project), other_type=other_type,
    )


def _gate_requirement(db: Session, project: Project, artefact_type: str, artefact_id: uuid.UUID, verb: str) -> None:
    """409 when `artefact_id` is an approved requirement and the project needs a change request for its links."""
    if artefact_type != _REQUIREMENT:
        return
    requirement = db.get(Requirement, artefact_id)
    if requirement is None:
        return
    if is_locked(get_current_version(db, requirement.id)) and requires_change_request_for_links(db, project):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An approved requirement is involved and this project requires links to be {verb} via a change request.",
        )


def _require_page_artefact(
    db: Session, resolver: ArtefactResolver, project: Project, artefact_type: str, artefact_id: uuid.UUID
) -> ArtefactSummary:
    """The page artefact's summary, or 404 unless it is a visible record of the project."""
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    resolver.resolve({artefact_type: {artefact_id}})
    summary = resolver.visible((artefact_type, artefact_id))
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    return summary


def require_visible_artefact(
    db: Session, project: Project, user_id: uuid.UUID, artefact_type: str, artefact_id: uuid.UUID
) -> ArtefactSummary:
    """The artefact's summary, or 404 unless it is a visible record of `project` for the user."""
    return _require_page_artefact(db, ArtefactResolver(db, project, user_id), project, artefact_type, artefact_id)


def _require_manage(resolver: ArtefactResolver, artefact_type: str) -> None:
    """403 unless the user holds `manage` on `artefact_type` in the project."""
    if not resolver.holds(artefact_type, "manage"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You do not have permission to change {get_artefact_type_label(artefact_type).lower()} links.",
        )


def create_link_for_artefact(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID,
    artefact_type: str,
    artefact_id: uuid.UUID,
    link_type_id: uuid.UUID,
    outgoing: bool,
    other_type: str,
    other_id: uuid.UUID,
) -> CreatedLink:
    """Links the page artefact to another record of the project.

    Args:
        db: Active session; the link and audit event are added, not committed.
        project: The project the request is scoped to (membership already checked).
        user_id: The acting user.
        artefact_type / artefact_id: The page artefact.
        link_type_id: The link type to use.
        outgoing: True when the page artefact is the link's source.
        other_type / other_id: The record at the other end.

    Returns:
        The created link with the far end's summary.

    Raises:
        HTTPException: 404 an end is not a visible record of the project; 403
            `manage` not held; 400 the link type is not usable (other organisation,
            dedicated, a rule forbids the pair) or it is a self-link; 409 a
            duplicate, or a change request is required for an approved requirement.
    """
    resolver = ArtefactResolver(db, project, user_id)
    _require_page_artefact(db, resolver, project, artefact_type, artefact_id)
    _require_manage(resolver, artefact_type)
    if other_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record not found.")
    resolver.resolve({other_type: {other_id}})
    other = resolver.visible((other_type, other_id))
    if other is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record not found.")
    if (other_type, other_id) == (artefact_type, artefact_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A record cannot be linked to itself.")

    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link_type_id must be a link type defined in this project's organisation.")
    if link_type.dedicated_endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'"{link_type.forward_name}" links are made with their own action, not as a general link.',
        )
    source_type, source_id, target_type, target_id = (
        (artefact_type, artefact_id, other_type, other_id) if outgoing else (other_type, other_id, artefact_type, artefact_id)
    )
    _gate_requirement(db, project, artefact_type, artefact_id, "added")
    _gate_requirement(db, project, other_type, other_id, "added")
    if existing_duplicate(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type=link_type,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "These records are already linked this way.")
    try:
        link = create_link(
            db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
            link_type_id=link_type.id, created_by=user_id,
        )
    except LinkRuleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(
        db, entity_type="artefact_link", entity_id=link.id, action="created", actor_id=user_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={
            "source_type": source_type, "source_id": str(source_id), "target_type": target_type,
            "target_id": str(target_id), "link_type_id": str(link_type.id), "via": "generic",
        },
    )
    return CreatedLink(link=link, link_type=link_type, outgoing=outgoing, other_type=other_type, other=other)


def delete_link_for_artefact(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID,
    artefact_type: str,
    artefact_id: uuid.UUID,
    link_id: uuid.UUID,
) -> None:
    """Removes a link touching the page artefact.

    Args:
        db: Active session; the deletion and audit event are added, not committed.
        project: The project the request is scoped to (membership already checked).
        user_id: The acting user.
        artefact_type / artefact_id: The page artefact; the link must touch it.
        link_id: The link to remove.

    Raises:
        HTTPException: 404 the artefact is not visible or the link does not touch
            it; 403 `manage` not held; 400 the link's type is dedicated; 409 an
            approved requirement is involved and a change request is required.
    """
    resolver = ArtefactResolver(db, project, user_id)
    _require_page_artefact(db, resolver, project, artefact_type, artefact_id)
    _require_manage(resolver, artefact_type)
    link = db.get(ArtefactLink, link_id)
    if link is None or (artefact_type, artefact_id) not in (
        (link.source_type, link.source_id), (link.target_type, link.target_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id) if link.link_type_id else None
    if link_type is not None and link_type.dedicated_endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'"{link_type.forward_name}" links belong to their own action and cannot be removed here.',
        )
    _gate_requirement(db, project, link.source_type, link.source_id, "removed")
    _gate_requirement(db, project, link.target_type, link.target_id, "removed")
    log_event(
        db, entity_type="artefact_link", entity_id=link.id, action="deleted", actor_id=user_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={
            "source_type": link.source_type, "source_id": str(link.source_id), "target_type": link.target_type,
            "target_id": str(link.target_id), "link_type_id": str(link.link_type_id) if link.link_type_id else None,
            "via": "generic",
        },
    )
    delete_link(db, link)


def existing_duplicate(
    db: Session, *, source_type: str, source_id: uuid.UUID, target_type: str, target_id: uuid.UUID,
    link_type: RequirementLinkTypeDefinition,
) -> bool:
    """Whether this link (or, for a symmetric type, its mirror) already exists."""
    if get_link_between(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type_id=link_type.id,
    ) is not None:
        return True
    return link_type.forward_name == link_type.reverse_name and get_link_between(
        db, source_type=target_type, source_id=target_id, target_type=source_type, target_id=source_id,
        link_type_id=link_type.id,
    ) is not None
