"""
Module: services.link_type_usage

Deleting a link type that is in use: what depends on it, and the two ways out
(move its links to another type, or delete them too).

Responsibilities:
- `compute_usage`: how many links, projects, pending change requests and
  approved-requirement links depend on a type; which artefact-type rules name
  it; and, for every other type, whether it could take over (with the reason it
  cannot, never silently skipped).
- `delete_link_type`: the single delete path, in one transaction, writing one
  audit event per link touched plus one for the type itself.

Scope: the same two functions serve an organisation-wide type (`project=None`,
org admin) and a project's local type (`project=<owner>`, project admin).

Design decisions:
- Keep by copy: deleting a type that other projects use can leave it behind for them
  (`keep_in_projects`): a meaning-preserving copy is created as a local type in the
  top-most affected project of each branch (descendants inherit it) and the affected
  links are repointed to it, so nothing a child sees changes. A copy needs no authority
  over the child; moving or removing links does (every project whose links change must
  be manageable by the caller, else 409 with a count only, never project names).
  A copy whose name is taken in its project's scope becomes "<name> (copy)".
- Moving links merges duplicates: a moved link that would repeat an existing
  link of the target type between the same two records is dropped, and the
  count is reported, rather than failing the whole move.
- A pending change request that proposes the type is repointed by a move and
  *blocks* link removal; the foreign key's `SET NULL` would otherwise strip the
  type and leave a request that can no longer be applied.
- An artefact-type rule naming the type gets the replacement substituted by a
  move; removal drops it from the rule and is refused when that would empty the
  rule, never silently widening one to "any link type".
- Project and approved-link figures are best effort (projects are resolved
  per artefact, so large sets report `None` for the project count).

Dependencies: `services.link_types` (rules and validation), `services.link_type_scope`
(project scope), `services.requirements` (lock state), `services.audit`, `services.rbac`
(project management check).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ArtefactType, ChangeRequestStatus
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ArtefactTypeLinkRuleEntry,
    ProjectLinkTypeVisibility,
    RequirementLinkTypeDefinition,
)
from app.models.user import User
from app.modules.registry import get_artefact_summary, get_artefact_type_label
from app.services.audit import log_event
from app.services.link_type_scope import is_customisation_locked, resolve_link_type_scope
from app.services.link_types import get_artefact_rules
from app.services.rbac import can_manage_project_settings
from app.services.requirements import LOCKED_STATUSES, requires_change_request_for_links

# Above this many links the per-artefact project lookup is skipped.
MAX_PROJECT_SCAN = 1000

_PENDING_STATUSES = (ChangeRequestStatus.DRAFT, ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW)

DeleteMode = Literal["reassign", "remove_links"]


@dataclass(frozen=True)
class Candidate:
    """Another link type, and whether it can take over the links of the type being deleted.

    Attributes:
        link_type: The candidate.
        compatible: True when every affected link could move to it.
        reason: Why not, when `compatible` is false.
        flow_differs: True when its `flow` differs, so a move changes what the links mean.
    """

    link_type: RequirementLinkTypeDefinition
    compatible: bool
    reason: str | None
    flow_differs: bool


@dataclass(frozen=True)
class LinkTypeUsage:
    """What depends on a link type (see `compute_usage`).

    Attributes:
        link_count: Links of the type.
        project_count: Distinct projects holding them, or `None` when too many to resolve.
        pending_change_requests: Open change requests proposing the type.
        approved_requirement_links: Links touching an approved requirement in a project
            that requires a change request for such links.
        rule_artefact_types: Artefact types whose rule names the type.
        emptied_rule_artefact_types: The subset whose rule would become empty on removal.
        is_dedicated: The type has a fixed meaning with its own action.
        candidates: Every other link type that could take over in the same scope, assessed.
        is_last: The organisation's only organisation-wide link type (cannot be deleted).
        moved_link_count: Links the chosen mode would move or remove (all of them unless
            `keep_in_projects` keeps some for other projects).
        keep_available: Other projects hold links, so they could keep the type by copy.
        keep_project_count: How many other projects use the type and could keep it (`None` when too
            many links to resolve cheaply).
        unmanageable_project_count: Projects holding links the caller cannot manage, which
            blocks moving or removing them (count only, never names).
    """

    link_count: int
    project_count: int | None
    pending_change_requests: int
    approved_requirement_links: int
    rule_artefact_types: list[str]
    emptied_rule_artefact_types: list[str]
    is_dedicated: bool
    candidates: list[Candidate]
    is_last: bool
    moved_link_count: int
    keep_available: bool
    keep_project_count: int | None
    unmanageable_project_count: int


@dataclass
class DeleteOutcome:
    """What a delete did: links moved to the replacement, merged into existing
    ones, or removed; copies created for other projects (and the names of those
    that had to be renamed to avoid a clash)."""

    moved: int = 0
    merged: int = 0
    removed: int = 0
    copies_created: int = 0
    copies_renamed: list[str] = field(default_factory=list)
    rules_updated: list[str] = field(default_factory=list)


def _pairs_of(links: list[ArtefactLink]) -> list[tuple[str, str]]:
    """The distinct `(source_type, target_type)` pairs of `links`."""
    return list(dict.fromkeys((link.source_type, link.target_type) for link in links))


def _assess_candidate(
    candidate: RequirementLinkTypeDefinition,
    old: RequirementLinkTypeDefinition,
    pairs: list[tuple[str, str]],
    rules: dict[str, set[uuid.UUID]],
) -> Candidate:
    """Whether `candidate` could take over every link of `old` (see `Candidate`).

    Checks the candidate's own restriction against each affected pair, and each
    end's rule, treating a rule that names `old` as one the candidate will be
    substituted into."""
    flow_differs = candidate.flow != old.flow
    if candidate.dedicated_endpoint or old.dedicated_endpoint:
        return Candidate(candidate, False, "Links of this type have a fixed meaning and cannot be converted.", flow_differs)
    for source_type, target_type in pairs:
        if candidate.allowed_source_types is not None and source_type not in candidate.allowed_source_types:
            return Candidate(
                candidate, False,
                f"It cannot start from a {get_artefact_type_label(source_type).lower()}, which some links do.",
                flow_differs,
            )
        if candidate.allowed_target_types is not None and target_type not in candidate.allowed_target_types:
            return Candidate(
                candidate, False,
                f"It cannot point at a {get_artefact_type_label(target_type).lower()}, which some links do.",
                flow_differs,
            )
        for artefact_type in dict.fromkeys((source_type, target_type)):
            permitted = rules.get(artefact_type)
            # A rule naming the old type gets the candidate substituted in, so it still permits it.
            if permitted is not None and candidate.id not in permitted and old.id not in permitted:
                return Candidate(
                    candidate, False,
                    f"{get_artefact_type_label(artefact_type)} links are limited to other link types.",
                    flow_differs,
                )
    return Candidate(candidate, True, None, flow_differs)


def _artefact_project_ids(db: Session, ends: set[tuple[str, uuid.UUID]]) -> dict[tuple[str, uuid.UUID], uuid.UUID | None]:
    """Best-effort project of each `(type, id)`: core types in one query each, others via their provider."""
    result: dict[tuple[str, uuid.UUID], uuid.UUID | None] = {}
    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for artefact_type, artefact_id in ends:
        by_type[artefact_type].append(artefact_id)
    for artefact_type, ids in by_type.items():
        if artefact_type == ArtefactType.REQUIREMENT.value:
            rows = db.execute(select(Requirement.id, Requirement.project_id).where(Requirement.id.in_(ids))).all()
        elif artefact_type == ArtefactType.REQUIREMENT_ACTION.value:
            rows = db.execute(select(RequirementAction.id, RequirementAction.project_id).where(RequirementAction.id.in_(ids))).all()
        else:
            rows = []
            for artefact_id in ids:
                summary = get_artefact_summary(db, artefact_type, artefact_id)
                rows.append((artefact_id, summary.project_id if summary is not None else None))
        for artefact_id, project_id in rows:
            result[(artefact_type, artefact_id)] = project_id
    return result


def _approved_requirement_links(db: Session, links: list[ArtefactLink]) -> int:
    """Links with an approved requirement end in a project that requires a change request for them."""
    requirement_value = ArtefactType.REQUIREMENT.value
    requirement_ids = {
        i for link in links for t, i in ((link.source_type, link.source_id), (link.target_type, link.target_id))
        if t == requirement_value
    }
    if not requirement_ids:
        return 0
    rows = db.execute(
        select(Requirement.id, Requirement.project_id)
        .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
        .where(
            Requirement.id.in_(requirement_ids), RequirementVersion.valid_to.is_(None),
            RequirementVersion.status.in_(LOCKED_STATUSES),
        )
    ).all()
    locked_project = {requirement_id: project_id for requirement_id, project_id in rows}
    gated: dict[uuid.UUID, bool] = {}
    count = 0
    for link in links:
        for artefact_type, artefact_id in ((link.source_type, link.source_id), (link.target_type, link.target_id)):
            project_id = locked_project.get(artefact_id) if artefact_type == requirement_value else None
            if project_id is None:
                continue
            if project_id not in gated:
                project = db.get(Project, project_id)
                gated[project_id] = project is not None and requires_change_request_for_links(db, project)
            if gated[project_id]:
                count += 1
                break
    return count


def _pending_change_request_count(db: Session, link_type_id: uuid.UUID) -> int:
    """Open (draft, submitted, in review) change requests proposing the type."""
    return db.scalar(
        select(func.count(func.distinct(ChangeRequest.id)))
        .select_from(ChangeRequestVersion)
        .join(ChangeRequest, ChangeRequest.id == ChangeRequestVersion.change_request_id)
        .where(ChangeRequestVersion.proposed_link_type_id == link_type_id, ChangeRequest.status.in_(_PENDING_STATUSES))
    ) or 0


def _rule_ids_naming(db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID) -> list[ArtefactTypeLinkRule]:
    """The organisation's artefact-type rules that name the link type."""
    return list(
        db.scalars(
            select(ArtefactTypeLinkRule)
            .join(ArtefactTypeLinkRuleEntry, ArtefactTypeLinkRuleEntry.rule_id == ArtefactTypeLinkRule.id)
            .where(ArtefactTypeLinkRule.organization_id == organization_id, ArtefactTypeLinkRuleEntry.link_type_id == link_type_id)
            .order_by(ArtefactTypeLinkRule.artefact_type)
        ).all()
    )


def _get_link_type(
    db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID, project: Project | None
) -> RequirementLinkTypeDefinition:
    """The link type, or 404 unless it belongs to the organisation and to the
    scope being administered (organisation-wide when `project` is `None`, else
    that project's own)."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if (
        link_type is None
        or link_type.organization_id != organization_id
        or link_type.project_id != (project.id if project is not None else None)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    return link_type


def _scope_candidates(
    db: Session, organization_id: uuid.UUID, link_type_id: uuid.UUID, project: Project | None
) -> list[RequirementLinkTypeDefinition]:
    """The other link types that could take over the links of a type at this scope.

    Organisation-wide scope: the other organisation-wide types (a project-local type
    would be unusable in other projects). Project scope: the other types the project
    offers (organisation-wide plus its own and its ancestors', never hidden or
    shadowed), all of which are usable in the project and every descendant."""
    if project is None:
        return list(
            db.scalars(
                select(RequirementLinkTypeDefinition)
                .where(
                    RequirementLinkTypeDefinition.organization_id == organization_id,
                    RequirementLinkTypeDefinition.project_id.is_(None),
                    RequirementLinkTypeDefinition.id != link_type_id,
                )
                .order_by(RequirementLinkTypeDefinition.sort_order, RequirementLinkTypeDefinition.forward_name)
            ).all()
        )
    return [
        s.link_type for s in resolve_link_type_scope(db, project) if s.offered and s.link_type.id != link_type_id
    ]


def _project_parents(db: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID | None]:
    """`{project id: parent project id}` for every project of the organisation."""
    return {
        row.id: row.parent_project_id
        for row in db.execute(select(Project.id, Project.parent_project_id).where(Project.organization_id == organization_id)).all()
    }


def _subtree(parents: dict[uuid.UUID, uuid.UUID | None], root: uuid.UUID) -> set[uuid.UUID]:
    """`root` and every project beneath it."""
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for child, parent in parents.items():
        if parent is not None:
            children[parent].append(child)
    result, frontier = {root}, [root]
    while frontier:
        for child in children.get(frontier.pop(), []):
            if child not in result:
                result.add(child)
                frontier.append(child)
    return result


def _copy_sites(parents: dict[uuid.UUID, uuid.UUID | None], affected: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """`{affected project: the top-most affected project of its branch}`: where
    its copy lives. Projects below a copy site inherit that one copy, so a branch
    never has several same-named copies fighting under the ancestor-wins rule."""
    sites: dict[uuid.UUID, uuid.UUID] = {}
    for project_id in affected:
        top, current, seen = project_id, parents.get(project_id), {project_id}
        while current is not None and current not in seen:
            seen.add(current)
            if current in affected:
                top = current
            current = parents.get(current)
        sites[project_id] = top
    return sites


def _link_projects(db: Session, links: list[ArtefactLink]) -> dict[uuid.UUID, uuid.UUID | None]:
    """`{link id: project that holds it}` (the project of either end), best effort."""
    ends = {(link.source_type, link.source_id) for link in links} | {(link.target_type, link.target_id) for link in links}
    projects = _artefact_project_ids(db, ends)
    return {
        link.id: projects.get((link.source_type, link.source_id)) or projects.get((link.target_type, link.target_id))
        for link in links
    }


def _unmanaged_projects(
    db: Session, actor: User, project_ids: set[uuid.UUID]
) -> int:
    """How many of `project_ids` the actor cannot manage."""
    count = 0
    for project_id in project_ids:
        project = db.get(Project, project_id)
        if project is None or not can_manage_project_settings(db, actor, project):
            count += 1
    return count


def compute_usage(
    db: Session,
    organization_id: uuid.UUID,
    link_type_id: uuid.UUID,
    *,
    project: Project | None = None,
    actor: User | None = None,
    keep_in_projects: bool = False,
) -> LinkTypeUsage:
    """Everything the delete dialog needs to know about a link type.

    Args:
        db: Active session (read only).
        organization_id: The organisation the type must belong to.
        link_type_id: The type.
        project: The owning project for a project-local type, `None` for an
            organisation-wide one.
        actor: The caller, to count projects they cannot manage (project scope only).
        keep_in_projects: Assess as if other projects keep the type by copy, so
            candidates are judged against only the links the chosen mode would move.

    Returns:
        The usage report.

    Raises:
        HTTPException: 404 if the type is not in the organisation at this scope.
    """
    link_type = _get_link_type(db, organization_id, link_type_id, project)
    links = list(db.scalars(select(ArtefactLink).where(ArtefactLink.link_type_id == link_type_id)).all())
    owner_id = project.id if project is not None else None
    project_count: int | None = None
    keep_projects: set[uuid.UUID] | None = None
    moved_links, link_projects = links, {}
    if len(links) <= MAX_PROJECT_SCAN:
        link_projects = _link_projects(db, links)
        project_count = len({p for p in link_projects.values() if p is not None})
        keep_projects = {p for p in link_projects.values() if p is not None and p != owner_id}
    locked = is_customisation_locked(db, organization_id)
    keep_allowed = not link_type.dedicated_endpoint and not (project is None and locked)
    if keep_in_projects and keep_allowed and keep_projects is not None:
        moved_links = [link for link in links if link_projects[link.id] not in keep_projects]
    rules = get_artefact_rules(db, organization_id, owner_id)
    rule_types = sorted(t for t, ids in rules.items() if link_type_id in ids)
    pairs = _pairs_of(moved_links)
    others = _scope_candidates(db, organization_id, link_type_id, project)
    unmanageable = 0
    if project is not None and actor is not None and keep_projects is not None:
        needing = {link_projects[link.id] for link in moved_links if link_projects.get(link.id) is not None}
        unmanageable = _unmanaged_projects(db, actor, needing - {project.id})
    return LinkTypeUsage(
        link_count=len(links), project_count=project_count,
        pending_change_requests=_pending_change_request_count(db, link_type_id),
        approved_requirement_links=_approved_requirement_links(db, moved_links),
        rule_artefact_types=rule_types,
        emptied_rule_artefact_types=[t for t in rule_types if rules[t] == {link_type_id}],
        is_dedicated=link_type.dedicated_endpoint,
        candidates=[_assess_candidate(other, link_type, pairs, rules) for other in others],
        is_last=project is None and not others,
        moved_link_count=len(moved_links),
        keep_available=keep_allowed and (keep_projects is None or bool(keep_projects)),
        keep_project_count=None if keep_projects is None else len(keep_projects),
        unmanageable_project_count=unmanageable,
    )


def delete_link_type(
    db: Session,
    *,
    organization_id: uuid.UUID,
    link_type_id: uuid.UUID,
    mode: DeleteMode | None,
    reassign_to_id: uuid.UUID | None,
    actor: User,
    project: Project | None = None,
    keep_in_projects: bool = False,
) -> DeleteOutcome:
    """Deletes a link type, in one transaction, dealing with whatever uses it.

    An unused type is simply deleted. A type in use needs `mode`: `reassign`
    (with `reassign_to_id`) moves its links, merging duplicates, repointing
    pending change requests and substituting into artefact-type rules;
    `remove_links` deletes the links. Passing `reassign_to_id` without a mode
    means `reassign`. With `keep_in_projects`, links held by *other* projects
    (every project for an organisation-wide type; descendants for a local one)
    are not moved or removed: each branch gets a copy of the type as a local type
    in its top-most affected project and those links are repointed to it. Writes
    one audit event per link touched and one for the type. Does not commit.

    Args:
        db: Active session.
        organization_id: The organisation the type must belong to.
        link_type_id: The type to delete.
        mode: `"reassign"`, `"remove_links"` or `None`.
        reassign_to_id: The replacement type for `reassign`.
        actor: The acting user (audit, and the project-management check).
        project: The owning project for a project-local type, `None` for an
            organisation-wide one.
        keep_in_projects: Keep the type for the other projects that use it, by copy.

    Returns:
        Counts of what happened.

    Raises:
        HTTPException: 404 unknown type; 409 last organisation-wide type, in use
            with no mode, pending change requests block removal, a rule would be
            emptied, the replacement cannot take every link, or the caller cannot
            manage every project whose links would change (count only); 400 invalid
            replacement or keep not allowed.
    """
    link_type = _get_link_type(db, organization_id, link_type_id, project)
    owner_id = project.id if project is not None else None
    if project is None:
        org_wide = db.scalar(
            select(func.count()).select_from(RequirementLinkTypeDefinition).where(
                RequirementLinkTypeDefinition.organization_id == organization_id,
                RequirementLinkTypeDefinition.project_id.is_(None),
            )
        ) or 0
        if org_wide <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "An organisation must always have at least one requirement link type.")

    links = list(db.scalars(select(ArtefactLink).where(ArtefactLink.link_type_id == link_type_id)).all())
    link_projects = _link_projects(db, links) if links else {}

    parents = _project_parents(db, organization_id)
    copy_site: dict[uuid.UUID, uuid.UUID] = {}
    if keep_in_projects:
        if link_type.dedicated_endpoint:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with a fixed meaning cannot be kept by copy.")
        if project is None and is_customisation_locked(db, organization_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Your organisation uses one shared set of link types, so projects cannot keep a copy.",
            )
        copy_site = _copy_sites(parents, {p for p in link_projects.values() if p is not None and p != owner_id})
    kept_links = [link for link in links if link_projects.get(link.id) in copy_site]
    moved_links = [link for link in links if link_projects.get(link.id) not in copy_site]

    if mode is None and reassign_to_id is not None:
        mode = "reassign"
    if moved_links and mode is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This link type is used by {len(moved_links)} link(s). Pass reassign_to_id to convert them to another "
            "link type before deleting, or mode=remove_links to delete them.",
        )
    if project is not None and moved_links:
        needing = {link_projects[link.id] for link in moved_links if link_projects.get(link.id) is not None}
        unmanaged = _unmanaged_projects(db, actor, needing - {project.id})
        if unmanaged:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Links of this type are held by {unmanaged} other project(s) you cannot manage, so they cannot be "
                "moved or removed. Keep the link type for those projects instead.",
            )

    rules = _rule_ids_naming(db, organization_id, link_type_id)
    outcome = DeleteOutcome()
    replacement: RequirementLinkTypeDefinition | None = None
    pending = _pending_change_request_rows(db, link_type_id)
    kept_pending = [row for row in pending if row.project_id in copy_site]
    other_pending = [row for row in pending if row.project_id not in copy_site]

    copies = _create_copies(db, link_type, set(copy_site.values()), parents, actor, organization_id, outcome)
    for link in kept_links:
        copy = copies[copy_site[link_projects[link.id]]]  # type: ignore[index]  # kept links all have a project
        link.link_type_id = copy.id
        log_event(
            db, entity_type="artefact_link", entity_id=link.id, action="link_type_changed", actor_id=actor.id,
            organization_id=organization_id, project_id=link_projects[link.id],
            detail={
                "source_type": link.source_type, "source_id": str(link.source_id),
                "target_type": link.target_type, "target_id": str(link.target_id),
                "from_link_type_id": str(link_type.id), "to_link_type_id": str(copy.id), "reason": "kept_by_copy",
            },
        )
    for row in kept_pending:
        db.execute(
            update(ChangeRequestVersion).where(ChangeRequestVersion.id == row.version_id)
            .values(proposed_link_type_id=copies[copy_site[row.project_id]].id)
        )

    if mode == "reassign":
        if reassign_to_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id is required for mode=reassign.")
        if reassign_to_id == link_type_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id must be different from the item being deleted.")
        replacement = db.get(RequirementLinkTypeDefinition, reassign_to_id)
        if replacement is None or replacement.id not in {t.id for t in _scope_candidates(db, organization_id, link_type_id, project)}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id must be an existing link type in the same scope.")
        assessment = _assess_candidate(
            replacement, link_type, _pairs_of(moved_links), get_artefact_rules(db, organization_id, owner_id)
        )
        if not assessment.compatible:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f'"{replacement.forward_name}" cannot take these links: {assessment.reason}'
            )
        _move_links(db, moved_links, link_type, replacement, actor.id, organization_id, outcome)
        for row in other_pending:
            db.execute(
                update(ChangeRequestVersion).where(ChangeRequestVersion.id == row.version_id)
                .values(proposed_link_type_id=replacement.id)
            )
        for rule in rules:
            ids = {entry.link_type_id for entry in rule.allowed_link_types}
            ids.discard(link_type_id)
            ids.add(replacement.id)
            rule.allowed_link_types = [ArtefactTypeLinkRuleEntry(link_type_id=i) for i in sorted(ids, key=str)]
            outcome.rules_updated.append(rule.artefact_type)
    else:
        blocking = sum(1 for row in other_pending if row.is_open)
        if blocking:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{blocking} pending change request(s) propose this link type; resolve them before deleting it.",
            )
        emptied = [rule.artefact_type for rule in rules if {e.link_type_id for e in rule.allowed_link_types} == {link_type_id}]
        if emptied:
            names = ", ".join(get_artefact_type_label(t) for t in emptied)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The link rule for {names} allows only this link type; edit or remove that rule first.",
            )
        for link in moved_links:
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="deleted", actor_id=actor.id,
                organization_id=organization_id,
                detail={
                    "source_type": link.source_type, "source_id": str(link.source_id),
                    "target_type": link.target_type, "target_id": str(link.target_id),
                    "link_type_id": str(link_type_id), "reason": "link_type_deleted",
                },
            )
            db.delete(link)
            outcome.removed += 1
        for rule in rules:
            rule.allowed_link_types = [e for e in rule.allowed_link_types if e.link_type_id != link_type_id]
            outcome.rules_updated.append(rule.artefact_type)
    db.flush()

    log_event(
        db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="deleted", actor_id=actor.id,
        organization_id=organization_id, project_id=owner_id,
        detail={
            "name": link_type.forward_name, "mode": mode, "moved": outcome.moved, "merged": outcome.merged,
            "removed": outcome.removed, "copies_created": outcome.copies_created,
            "reassigned_to": str(replacement.id) if replacement is not None else None,
        },
    )
    db.execute(delete(ArtefactTypeLinkRuleEntry).where(ArtefactTypeLinkRuleEntry.link_type_id == link_type_id))
    db.delete(link_type)
    db.flush()
    return outcome


@dataclass(frozen=True)
class _PendingRow:
    """A change-request version proposing a link type: its id, project, and whether the request is still open."""

    version_id: uuid.UUID
    project_id: uuid.UUID
    is_open: bool


def _pending_change_request_rows(db: Session, link_type_id: uuid.UUID) -> list[_PendingRow]:
    """Every change-request version proposing the type (open or historic) with its project."""
    return [
        _PendingRow(row.id, row.project_id, row.status in _PENDING_STATUSES)
        for row in db.execute(
            select(ChangeRequestVersion.id, ChangeRequest.project_id, ChangeRequest.status)
            .join(ChangeRequest, ChangeRequest.id == ChangeRequestVersion.change_request_id)
            .where(ChangeRequestVersion.proposed_link_type_id == link_type_id)
        ).all()
    ]


def _free_copy_name(db: Session, project: Project, original: RequirementLinkTypeDefinition) -> str:
    """`original`'s forward name, or "<name> (copy)" / "(copy N)" when that name is
    already taken in the project's scope (organisation, ancestors or itself)."""
    taken = {
        s.link_type.forward_name.casefold()
        for s in resolve_link_type_scope(db, project)
        if s.link_type.id != original.id
    }
    name, counter = original.forward_name, 1
    while name.casefold() in taken:
        counter += 1
        suffix = " (copy)" if counter == 2 else f" (copy {counter - 1})"
        name = f"{original.forward_name[: 100 - len(suffix)]}{suffix}"
    return name


def _create_copies(
    db: Session,
    original: RequirementLinkTypeDefinition,
    sites: set[uuid.UUID],
    parents: dict[uuid.UUID, uuid.UUID | None],
    actor: User,
    organization_id: uuid.UUID,
    outcome: DeleteOutcome,
) -> dict[uuid.UUID, RequirementLinkTypeDefinition]:
    """Creates a local copy of `original` in each site project, carrying over
    visibility choices so the projects see exactly what they saw before.

    Returns:
        `{site project id: its copy}`.
    """
    copies: dict[uuid.UUID, RequirementLinkTypeDefinition] = {}
    visibility = {
        (row.project_id): row.hidden
        for row in db.scalars(
            select(ProjectLinkTypeVisibility).where(ProjectLinkTypeVisibility.link_type_id == original.id)
        ).all()
    }
    for site_id in sites:
        site = db.get(Project, site_id)
        if site is None:
            continue
        scope_before = {s.link_type.id: s for s in resolve_link_type_scope(db, site)}.get(original.id)
        name = _free_copy_name(db, site, original)
        own_count = db.scalar(
            select(func.count()).select_from(RequirementLinkTypeDefinition)
            .where(RequirementLinkTypeDefinition.project_id == site_id)
        ) or 0
        copy = RequirementLinkTypeDefinition(
            organization_id=organization_id, project_id=site_id, forward_name=name,
            reverse_name=original.reverse_name, sort_order=own_count, flow=original.flow,
            allowed_source_types=list(original.allowed_source_types) if original.allowed_source_types else None,
            allowed_target_types=list(original.allowed_target_types) if original.allowed_target_types else None,
        )
        db.add(copy)
        db.flush()
        subtree = _subtree(parents, site_id)
        for project_id, hidden in visibility.items():
            if project_id in subtree:
                db.add(ProjectLinkTypeVisibility(project_id=project_id, link_type_id=copy.id, hidden=hidden))
        hidden_above = (
            scope_before is not None and scope_before.hidden and scope_before.hidden_by_project_id not in subtree
            and site_id not in visibility
        )
        if hidden_above:
            db.add(ProjectLinkTypeVisibility(project_id=site_id, link_type_id=copy.id, hidden=True))
        log_event(
            db, entity_type="requirement_link_type_definition", entity_id=copy.id, action="created", actor_id=actor.id,
            organization_id=organization_id, project_id=site_id,
            detail={
                "forward_name": copy.forward_name, "copied_from": str(original.id), "reason": "link_type_deleted",
                "flow": copy.flow.value,
            },
        )
        outcome.copies_created += 1
        if name != original.forward_name:
            outcome.copies_renamed.append(name)
        copies[site_id] = copy
    db.flush()
    return copies


def _move_links(
    db: Session,
    links: list[ArtefactLink],
    old: RequirementLinkTypeDefinition,
    replacement: RequirementLinkTypeDefinition,
    actor_id: uuid.UUID,
    organization_id: uuid.UUID,
    outcome: DeleteOutcome,
) -> None:
    """Repoints `links` at `replacement`, dropping any that would duplicate an existing link of it."""
    existing = {
        (row.source_type, row.source_id, row.target_type, row.target_id)
        for row in db.execute(
            select(ArtefactLink.source_type, ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id)
            .where(ArtefactLink.link_type_id == replacement.id)
        ).all()
    }
    for link in links:
        key = (link.source_type, link.source_id, link.target_type, link.target_id)
        base = {
            "source_type": link.source_type, "source_id": str(link.source_id),
            "target_type": link.target_type, "target_id": str(link.target_id),
            "from_link_type_id": str(old.id), "to_link_type_id": str(replacement.id),
        }
        if key in existing:
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="deleted", actor_id=actor_id,
                organization_id=organization_id, detail={**base, "reason": "merged_into_existing"},
            )
            db.delete(link)
            outcome.merged += 1
        else:
            link.link_type_id = replacement.id
            existing.add(key)
            log_event(
                db, entity_type="artefact_link", entity_id=link.id, action="link_type_changed", actor_id=actor_id,
                organization_id=organization_id, detail=base,
            )
            outcome.moved += 1
