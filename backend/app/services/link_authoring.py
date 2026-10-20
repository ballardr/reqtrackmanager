"""
Module: services.link_authoring

Generic link creation and removal for any artefact of a project, the one
authorisation point for `routers.artefact_links`' write endpoints.

Responsibilities:
- Offer the link types usable from an artefact (`usable_options`).
- Create a link (`create_link_for_artefact`) after checking: both ends are
  visible records of the project (module enabled, `view` held), the caller holds
  `link` or `manage` on the page artefact's type (any state), or is a stakeholder,
  project administrator or manager linking a core record while no requirement involved
  is approved, the link type belongs to the project's
  organisation and is not dedicated, the link type's restriction and both ends'
  artefact-type rules allow it, and no approved requirement is being linked in a
  project that requires a change request for that.
- Remove a link (`delete_link_for_artefact`) under the same gates.
- Share the authorisation helpers (`require_page_artefact`, `related_project_or_404`,
  `linkable_types_for_project`) the finder reads in `services.link_browse` use, so the
  picker never offers what creation would refuse.
- Link across nesting: with `other_project_id` the other end may be in an ancestor
  or descendant project the caller can open (`related_project_or_404`). Each end is
  resolved, permission-checked and change-request-gated in its own project, the
  link type's nesting scope decides whether and in which direction the pair is
  allowed (`services.link_nesting`), and the audit event is written in both projects.

Design decisions:
- Reuses `ArtefactResolver` (the link graph's visibility rule) so authoring and
  display can never disagree about what a user may see.
- Both ends of a requirement are gated by the change-request rule, stricter than
  the legacy requirement endpoint (which only checked its own end), because a
  link on an approved requirement is the thing that rule protects.
- A symmetric link type counts a reversed pair as a duplicate.

Dependencies: `services.link_graph` (visibility), `services.link_types` (rules),
`services.link_nesting` (related projects), `services.relationships` (storage),
`services.requirements` (lock state), `services.audit`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import CORE_ARTEFACT_TYPES, ArtefactType
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
from app.services.link_graph import ArtefactResolver, is_locked_requirement
from app.services.link_nesting import is_link_live, related_projects
from app.services.link_type_scope import UNAVAILABLE_MESSAGE, assert_link_type_usable
from app.services.link_types import LinkRuleError, LinkTypeOption, list_usable_link_types
from app.services.relationships import create_link, delete_link, get_link_between
from app.services.requirements import get_current_version, is_locked, requires_change_request_for_links

_REQUIREMENT = ArtefactType.REQUIREMENT.value

#: The audit `authorised_by` value (and `require_link_authority` result) for linking by default role.
DEFAULT_ROLE_AUTHORITY = "role"

#: Stands in for a record that does not exist yet (the requirement a `new_requirement`
#: change request would create): the finder reads accept it as the page artefact so the
#: proposing form can search for link targets before the record exists. Never accepted by
#: a write; the caller must hold `link` or `manage` on the type, as for a real record.
DRAFT_ARTEFACT_ID = uuid.UUID(int=0)


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

    types = set(CORE_ARTEFACT_TYPES)
    for definition in get_module_registry().values():
        if definition.artefact_types and is_module_enabled_for_project(db, project.id, definition.key):
            types.update(definition.artefact_types)
    return types


def related_project_or_404(db: Session, project: Project, user_id: uuid.UUID, other_project_id: uuid.UUID) -> Project:
    """The ancestor/descendant project the caller can open, else 404.

    The same answer for "does not exist", "not in this nesting chain" and "you cannot
    open it", so a probe learns nothing about projects it has no access to.

    Raises:
        HTTPException: 404 when `other_project_id` is not `project` or an ancestor or
            descendant of it that the caller can open (see `related_projects`).
    """
    related, _ = related_projects(db, project, user_id)
    for entry in related:
        if entry.project.id == other_project_id:
            return entry.project
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record not found.")


def usable_options(
    db: Session, project: Project, artefact_type: str, other_type: str | None, other_project: Project | None = None
) -> list[LinkTypeOption]:
    """Link types usable from an artefact of `artefact_type` in `project`.

    Args:
        db: Active session (read only).
        project: The project; supplies the organisation and enabled modules.
        artefact_type: The page artefact's type.
        other_type: Narrow to options that can reach this type.
        other_project: The ancestor/descendant project of the other end (already
            authorised by the caller); `None` for the same project. Narrows the
            options to types whose nesting scope permits the pair, with the right
            orientation, and offers the artefact types enabled in that project.

    Returns:
        The usable options (dedicated types are never offered).
    """
    return list_usable_link_types(
        db, project, artefact_type, candidate_types=linkable_types_for_project(db, other_project or project),
        other_type=other_type, other_project=other_project,
    )


def gate_requirement(db: Session, project: Project, artefact_type: str, artefact_id: uuid.UUID, verb: str) -> None:
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


def require_page_artefact(
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


def require_finder_artefact(
    db: Session, resolver: ArtefactResolver, project: Project, artefact_type: str, artefact_id: uuid.UUID
) -> None:
    """Authorises the page artefact of a finder read (types, candidates, browse).

    Like `require_page_artefact`, but `DRAFT_ARTEFACT_ID` stands for a record not created
    yet and is accepted when the type is registered and the user may set links on it.

    Raises:
        HTTPException: 404 the type is unregistered or the artefact is not a visible record
            of the project; 403 a draft was named by a user who may not link that type.
    """
    if artefact_id == DRAFT_ARTEFACT_ID:
        if artefact_type not in get_all_registered_artefact_types():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
        require_link_authority(resolver, artefact_type)
        return
    require_page_artefact(db, resolver, project, artefact_type, artefact_id)


def require_link_authority(resolver: ArtefactResolver, artefact_type: str) -> str:
    """How the user may change `artefact_type` links in the project: `"manage"` or `"link"` (any
    state, approved included), or `"role"` (a stakeholder, project administrator or manager on a
    core type, only while no requirement involved is approved; see `require_unlocked_for_role`).

    Raises:
        HTTPException: 403 when none of them applies.
    """
    authority = resolver.link_authority(artefact_type)
    if authority is not None:
        return authority
    if resolver.has_default_link_role(artefact_type):
        return DEFAULT_ROLE_AUTHORITY
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"You do not have permission to change {get_artefact_type_label(artefact_type).lower()} links.",
    )


def require_unlocked_for_role(db: Session, authority: str, ends: list[tuple[str, uuid.UUID]]) -> None:
    """When the user links by default role alone, none of the `ends` may be an approved requirement.

    Holders of `link` or `manage` are not asked: the Link permission exists to link records in any
    state. Everyone else changes an approved requirement's links through a change request.

    Raises:
        HTTPException: 403 when `authority` is the default role and an end is approved.
    """
    if authority != DEFAULT_ROLE_AUTHORITY:
        return
    if any(is_locked_requirement(db, artefact_type, artefact_id) for artefact_type, artefact_id in ends):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "An approved requirement's links can be changed directly only with the Link permission; "
            "otherwise propose the change in a change request.",
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
    other_project_id: uuid.UUID | None = None,
) -> CreatedLink:
    """Links the page artefact to another record of the project, or of an ancestor or
    descendant project.

    Args:
        db: Active session; the link and audit event are added, not committed.
        project: The project the request is scoped to (membership already checked).
        user_id: The acting user.
        artefact_type / artefact_id: The page artefact.
        link_type_id: The link type to use.
        outgoing: True when the page artefact is the link's source.
        other_type / other_id: The record at the other end.
        other_project_id: The project of the other end when it is an ancestor or
            descendant of `project`; `None` (or `project`'s id) for the same project.

    Returns:
        The created link with the far end's summary.

    Raises:
        HTTPException: 404 an end is not a visible record of its project, or
            `other_project_id` is not a related project the caller can open; 403
            neither `link` nor `manage` held; 400 the link type is not usable (not available to the
            project, hidden, dedicated, a rule forbids the pair, or its nesting scope
            forbids this pair of projects) or it is a self-link or the other project is
            archived; 409 a duplicate, or a change request is required for an
            approved requirement.
    """
    resolver = ArtefactResolver(db, project, user_id)
    require_page_artefact(db, resolver, project, artefact_type, artefact_id)
    authority = require_link_authority(resolver, artefact_type)
    if other_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record not found.")
    other_project = project
    other_resolver = resolver
    if other_project_id is not None and other_project_id != project.id:
        other_project = related_project_or_404(db, project, user_id, other_project_id)
        other_resolver = ArtefactResolver(db, other_project, user_id)
    other_resolver.resolve({other_type: {other_id}})
    other = other_resolver.visible((other_type, other_id))
    if other is None or (other_project is not project and other.project_id != other_project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked record not found.")
    if other_project is not project and other_project.is_archived:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That project is archived, so it cannot take new links.")
    if (other_type, other_id) == (artefact_type, artefact_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A record cannot be linked to itself.")
    require_unlocked_for_role(db, authority, [(artefact_type, artefact_id), (other_type, other_id)])

    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, UNAVAILABLE_MESSAGE)
    try:
        assert_link_type_usable(db, project, link_type, enforce_offered=True)
    except LinkRuleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if link_type.dedicated_endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'"{link_type.forward_name}" links are made with their own action, not as a general link.',
        )
    source_type, source_id, target_type, target_id = (
        (artefact_type, artefact_id, other_type, other_id) if outgoing else (other_type, other_id, artefact_type, artefact_id)
    )
    gate_requirement(db, project, artefact_type, artefact_id, "added")
    gate_requirement(db, other_project, other_type, other_id, "added")
    if existing_duplicate(
        db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
        link_type=link_type,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "These records are already linked this way.")
    page_project_id, far_project_id = project.id, other_project.id
    try:
        link = create_link(
            db, source_type=source_type, source_id=source_id, target_type=target_type, target_id=target_id,
            link_type_id=link_type.id, created_by=user_id, project_id=project.id, enforce_offered=True,
            source_project_id=page_project_id if outgoing else far_project_id,
            target_project_id=far_project_id if outgoing else page_project_id,
        )
    except LinkRuleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit_link(db, link, action="created", actor_id=user_id, projects=(project, other_project), via_detail={
        "link_type_id": str(link_type.id), "authorised_by": authority,
    })
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
            it; 403 neither `link` nor `manage` held; 400 the link is structural (untyped) or its type is dedicated; 409 an
            approved requirement is involved and a change request is required.
    """
    resolver = ArtefactResolver(db, project, user_id)
    require_page_artefact(db, resolver, project, artefact_type, artefact_id)
    authority = require_link_authority(resolver, artefact_type)
    link = db.get(ArtefactLink, link_id)
    if link is None or (artefact_type, artefact_id) not in (
        (link.source_type, link.source_id), (link.target_type, link.target_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    if link.link_type_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This is a structural link (such as an action's membership of a requirement) and is managed from its own section.",
        )
    link_type = db.get(RequirementLinkTypeDefinition, link.link_type_id)
    if link_type is not None and link_type.dedicated_endpoint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'"{link_type.forward_name}" links belong to their own action and cannot be removed here.',
        )
    other_project = project
    if link.source_project_id is not None and link.target_project_id is not None:
        # A cross-level link: the page end must be in this project, the other end's project
        # must still be one the caller can open, and the other end must still be visible there.
        page_is_source = (artefact_type, artefact_id) == (link.source_type, link.source_id)
        page_project_id, far_project_id = (
            (link.source_project_id, link.target_project_id) if page_is_source
            else (link.target_project_id, link.source_project_id)
        )
        if page_project_id != project.id or not is_link_live(db, link):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
        try:
            other_project = related_project_or_404(db, project, user_id, far_project_id)
        except HTTPException as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.") from exc
        far_type, far_id = (link.target_type, link.target_id) if page_is_source else (link.source_type, link.source_id)
        far_resolver = ArtefactResolver(db, other_project, user_id)
        far_resolver.resolve({far_type: {far_id}})
        if far_resolver.visible((far_type, far_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found.")
    require_unlocked_for_role(
        db, authority, [(link.source_type, link.source_id), (link.target_type, link.target_id)]
    )
    source_project, target_project = (
        (project, project) if other_project is project
        else ((project, other_project) if (artefact_type, artefact_id) == (link.source_type, link.source_id) else (other_project, project))
    )
    gate_requirement(db, source_project, link.source_type, link.source_id, "removed")
    gate_requirement(db, target_project, link.target_type, link.target_id, "removed")
    audit_link(db, link, action="deleted", actor_id=user_id, projects=(project, other_project), via_detail={
        "link_type_id": str(link.link_type_id) if link.link_type_id else None, "authorised_by": authority,
    })
    delete_link(db, link)


def audit_link(
    db: Session, link: ArtefactLink, *, action: str, actor_id: uuid.UUID, projects: tuple[Project, Project],
    via_detail: dict,
) -> None:
    """Writes the link's audit event in each project it touches (once when both ends share one)."""
    detail = {
        "source_type": link.source_type, "source_id": str(link.source_id), "target_type": link.target_type,
        "target_id": str(link.target_id), "via": "generic", **via_detail,
    }
    seen: set[uuid.UUID] = set()
    for audited in projects:
        if audited.id in seen:
            continue
        seen.add(audited.id)
        extra = {} if len(set(p.id for p in projects)) == 1 else {
            "cross_project": True, "source_project_id": str(link.source_project_id),
            "target_project_id": str(link.target_project_id),
        }
        log_event(
            db, entity_type="artefact_link", entity_id=link.id, action=action, actor_id=actor_id,
            organization_id=audited.organization_id, project_id=audited.id, detail={**detail, **extra},
        )


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
