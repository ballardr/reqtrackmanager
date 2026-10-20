"""
Module: services.link_nesting

Links between a project and its ancestors or descendants: which project pairs
may be linked, whether a link type allows it and in which direction, and which
related projects a user may see.

Responsibilities:
- Relate two projects (`project_relation`): same, one above the other, or
  unrelated (siblings, cousins, other trees).
- Decide whether a link type may join a project pair (`check_nesting`,
  `nesting_violation`), from the type's `nesting_scope` and `flow`.
- List the related projects a user can open (`related_projects`), the scope of
  both the link-candidate endpoint and the link graph.
- Find existing cross-level links that no longer satisfy a type's scope
  (`count_cross_links_violating`), for the admin "N links will be flagged" line.

Design decisions:
- Ancestry only. Siblings and unrelated projects stay unlinkable (that is the
  general cross-project problem).
- Related projects are walked outward from the request project and stop at the
  first project the user cannot open, so a hole in the chain never looks
  contiguous and nothing beyond it is disclosed (the `/ancestors` rule).
- "Can open" is a genuine project role, not settings-management capability:
  the related projects carry artefact content, not just structure.
- Enforced at link creation only. A link whose projects stop being related
  (reparent, detach) stays stored and is simply not shown (`is_link_live`) until
  the chain is restored; narrowing a type's scope flags existing links, never
  deletes them.

Dependencies: `services.project_hierarchy` (chains), `services.rbac` (roles),
`services.link_type_scope` (`LinkRuleError`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import LinkFlow, LinkNestingScope
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.services.link_type_scope import LinkRuleError
from app.services.project_hierarchy import get_project_chain_ids
from app.services.rbac import get_effective_project_roles, session_may_reach_project

MAX_RELATED_PROJECTS = 50
"""Cap on the related projects considered at once (ancestors + descendants), so a
huge tree cannot make one request unbounded."""

_MAX_EXAMINED_DESCENDANTS = 4 * MAX_RELATED_PROJECTS
"""Cap on descendants whose access is checked (each check resolves roles), including
ones the caller cannot open that are then skipped."""

_DESCENDANT_LEVEL_CAP = 20


class ProjectRelation(str, Enum):
    """How the second project relates to the first."""

    SAME = "same"
    ANCESTOR = "ancestor"  # the second is above the first
    DESCENDANT = "descendant"  # the second is below the first


def project_relation(db: Session, project_id: uuid.UUID, other_id: uuid.UUID) -> ProjectRelation | None:
    """How `other_id` relates to `project_id`, or `None` when they share no ancestry.

    Args:
        db: Active session (read only).
        project_id: The reference project.
        other_id: The project to relate to it.

    Returns:
        `SAME`, `ANCESTOR` (other is above), `DESCENDANT` (other is below) or `None`.
    """
    if project_id == other_id:
        return ProjectRelation.SAME
    if other_id in get_project_chain_ids(db, project_id):
        return ProjectRelation.ANCESTOR
    if project_id in get_project_chain_ids(db, other_id):
        return ProjectRelation.DESCENDANT
    return None


def nesting_violation(link_type: RequirementLinkTypeDefinition, *, source_is_above: bool) -> str | None:
    """Why `link_type` may not join two distinct, ancestry-related projects, or `None`.

    Args:
        link_type: The link type.
        source_is_above: Whether the link's source end is in the ancestor project
            (false: the target end is).

    Returns:
        A user-facing reason, or `None` when the pair is allowed.
    """
    name = link_type.forward_name
    scope = link_type.nesting_scope
    if scope is LinkNestingScope.SAME_PROJECT:
        return f'"{name}" links must stay within one project.'
    if scope is LinkNestingScope.UPSTREAM_IN_ANCESTOR:
        if link_type.flow is LinkFlow.NONE:
            return f'"{name}" has no direction, so it cannot say which end may sit in the parent project.'
        source_is_upstream = link_type.flow is LinkFlow.FORWARD_IS_DOWNSTREAM
        if source_is_upstream != source_is_above:
            return f'"{name}" links must have their upstream end in the same or a parent project, not below.'
    return None


def check_nesting(
    db: Session,
    link_type: RequirementLinkTypeDefinition,
    source_project_id: uuid.UUID,
    target_project_id: uuid.UUID,
) -> None:
    """Raises unless `link_type` may join an artefact of `source_project_id` to one of `target_project_id`.

    Same-project pairs always pass. Otherwise the projects must be in one ancestry
    line and the type's `nesting_scope` must permit the direction.

    Args:
        db: Active session (read only).
        link_type: The type being used.
        source_project_id / target_project_id: The projects of the two ends.

    Raises:
        LinkRuleError: If the projects are not related, or the type forbids the pair.
    """
    if source_project_id == target_project_id:
        return
    relation = project_relation(db, source_project_id, target_project_id)
    if relation is None:
        raise LinkRuleError("These records are not in the same nesting chain, so they cannot be linked.")
    reason = nesting_violation(link_type, source_is_above=relation is ProjectRelation.DESCENDANT)
    if reason is not None:
        raise LinkRuleError(reason)


def ancestor_side_project_id(db: Session, project_a: uuid.UUID, project_b: uuid.UUID) -> uuid.UUID | None:
    """The higher of two ancestry-related projects, `project_a` when they are equal, `None` when unrelated."""
    relation = project_relation(db, project_a, project_b)
    if relation is None:
        return None
    return project_b if relation is ProjectRelation.ANCESTOR else project_a


@dataclass(frozen=True)
class RelatedProject:
    """A project related to the request project that the user can open.

    Attributes:
        project: The project.
        relation: `SAME`, `ANCESTOR` or `DESCENDANT` relative to the request project.
        distance: Levels from the request project (0 for itself).
    """

    project: Project
    relation: ProjectRelation
    distance: int

    @property
    def label(self) -> str:
        """Nearest-first, relationship-only label (never the project's name)."""
        if self.relation is ProjectRelation.SAME:
            return "This project"
        if self.distance == 1:
            return "Parent project" if self.relation is ProjectRelation.ANCESTOR else "Child project"
        word = "up" if self.relation is ProjectRelation.ANCESTOR else "down"
        return f"{self.distance} levels {word}"


def can_open_project(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    """Whether the user holds a genuine role on the project (may read its content) and the
    credential behind the request may reach it (a token scoped to one project does not reach
    its parent or child)."""
    return session_may_reach_project(db, project_id) and bool(get_effective_project_roles(db, user_id, project_id))


def related_projects(
    db: Session, project: Project, user_id: uuid.UUID, *, include_archived: bool = True
) -> tuple[list[RelatedProject], bool]:
    """The project itself plus every ancestor and descendant the user can open.

    Ancestors are listed nearest first and stop at the first one the user cannot
    open; descendants are walked level by level and are neither listed nor
    descended through when the user cannot open them. At most
    `MAX_RELATED_PROJECTS` are returned.

    Args:
        db: Active session (read only).
        project: The request project (the user's access to it is already checked).
        user_id: The user.
        include_archived: Keep archived projects (their links still display); false
            for the list of projects a *new* link may target.

    Returns:
        `(projects, truncated)`: the request project first, then ancestors
        nearest first, then descendants level by level; `truncated` is true when the
        cap cut the list short.
    """
    found: list[RelatedProject] = [RelatedProject(project, ProjectRelation.SAME, 0)]
    chain = get_project_chain_ids(db, project.id)[1:]
    for distance, ancestor_id in enumerate(chain, start=1):
        if not can_open_project(db, user_id, ancestor_id):
            break
        ancestor = db.get(Project, ancestor_id)
        if ancestor is None or ancestor.organization_id != project.organization_id:
            break
        found.append(RelatedProject(ancestor, ProjectRelation.ANCESTOR, distance))

    truncated = False
    examined = 0
    visited = {project.id}
    frontier = [project.id]
    for distance in range(1, _DESCENDANT_LEVEL_CAP + 1):
        if not frontier:
            break
        children = db.scalars(
            select(Project).where(
                Project.parent_project_id.in_(frontier), Project.organization_id == project.organization_id
            ).order_by(Project.name, Project.id)
        ).all()
        frontier = []
        for child in children:
            if child.id in visited:
                continue
            examined += 1
            if examined > _MAX_EXAMINED_DESCENDANTS:
                truncated = True
                break
            if not can_open_project(db, user_id, child.id):
                continue
            if len(found) >= MAX_RELATED_PROJECTS:
                truncated = True
                break
            visited.add(child.id)
            frontier.append(child.id)
            found.append(RelatedProject(child, ProjectRelation.DESCENDANT, distance))
        if truncated:
            break
    if not include_archived:
        found = [r for r in found if r.relation is ProjectRelation.SAME or not r.project.is_archived]
    return found, truncated


def is_link_live(
    db: Session, link: ArtefactLink, chain_cache: dict[uuid.UUID, list[uuid.UUID]] | None = None
) -> bool:
    """Whether a stored link is still displayable: an ordinary link always is; a
    cross-level link only while its two projects are still in one ancestry line.

    Args:
        db: Active session (read only).
        link: The link.
        chain_cache: Optional `{project_id: chain}` shared across calls to avoid re-walking.
    """
    if link.source_project_id is None or link.target_project_id is None:
        return True
    cache = chain_cache if chain_cache is not None else {}
    for pid in (link.source_project_id, link.target_project_id):
        if pid not in cache:
            cache[pid] = get_project_chain_ids(db, pid)
    return link.target_project_id in cache[link.source_project_id] or link.source_project_id in cache[link.target_project_id]


def count_cross_links_violating(
    db: Session, link_type: RequirementLinkTypeDefinition, new_scope: LinkNestingScope, new_flow: LinkFlow | None = None
) -> int:
    """How many existing cross-level links of `link_type` would stop satisfying it
    if its scope became `new_scope` (and its flow `new_flow`), for the admin's
    "N links will be flagged" line. Nothing is changed or deleted.

    Args:
        db: Active session (read only).
        link_type: The type being edited.
        new_scope: The scope it would get.
        new_flow: The flow it would get, or `None` to keep the current one.

    Returns:
        The number of stored cross-level links of the type that would be flagged.
    """
    probe = RequirementLinkTypeDefinition(
        forward_name=link_type.forward_name, reverse_name=link_type.reverse_name,
        flow=new_flow or link_type.flow, nesting_scope=new_scope,
    )
    chain_cache: dict[uuid.UUID, list[uuid.UUID]] = {}
    count = 0
    for link in db.scalars(
        select(ArtefactLink).where(
            ArtefactLink.link_type_id == link_type.id, ArtefactLink.source_project_id.is_not(None)
        )
    ).all():
        if not is_link_live(db, link, chain_cache):
            continue
        source_is_above = link.source_project_id in chain_cache[link.target_project_id]
        if nesting_violation(probe, source_is_above=source_is_above) is not None:
            count += 1
    return count


def validate_nesting_scope(scope: LinkNestingScope, flow: LinkFlow) -> None:
    """Raises `ValueError` when `scope` and `flow` cannot go together: the
    directional scope needs a direction to name an upstream end."""
    if scope is LinkNestingScope.UPSTREAM_IN_ANCESTOR and flow is LinkFlow.NONE:
        raise ValueError(
            'The "upstream end may be in a parent project" option needs a flow direction: '
            "a link type with no direction has no upstream end."
        )
