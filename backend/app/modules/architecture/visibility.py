"""
Module: modules.architecture.visibility

The single path to an element its viewer does not own: which elements a person (or, for a core hook with no
person, a project) may read, however the element is owned.

An element is visible when any of these routes allows it:

- **Own project:** the viewer is working in the project that owns it.
- **Owner access:** it is project-owned and the person can open the owning project
  (`services.link_nesting.can_open_project`, which applies an access token's project scope) and the module is
  enabled there.
- **Organisation administrator:** it is organisation-owned and the person holds `architecture_org_admin`
  (or organisation admin).
- **Collection grant:** the element, or an ancestor of it, is a member of a collection granted to the viewer's
  project (or an ancestor project when the grant includes descendants) or to a group the person belongs to.

Every route is limited to the viewer's organisation. A recipient reads, places, connects, allocates and links; it
never edits (edits go through the owner's own routes, which find an element by its owner).

Design decisions:
- Two entry points share one implementation. `Viewer.of_user` is the full resolver the module's endpoints use.
  `Viewer.of_project` has no person, so only the own-project and project-grant routes apply: it serves the core
  hooks that see a project and not a person (the link graph, the global search, link validation), and it is always a
  subset of the person's view of the same project.
- A hidden element is indistinguishable from a missing one: callers answer 404 and put nothing about it in a
  count, a summary or a message.
- Ancestors and descendants are read with one recursive query each, so the number of statements does not grow
  with the number of elements asked about.

Dependencies: this module's models; `services.link_nesting`, `services.project_hierarchy`, `services.rbac`
and `modules.registry` (module state).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Integer, literal, select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.project import Project, ProjectGroup
from app.models.user import User
from app.modules.architecture._shared import ARCHITECTURE_ORG_ADMIN_ROLE
from app.modules.architecture.models import (
    ArchitectureCollection,
    ArchitectureCollectionGrant,
    ArchitectureCollectionMember,
    ArchitectureElement,
)
from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY
from app.modules.registry import is_module_enabled_for_project
from app.services.link_nesting import can_open_project
from app.services.project_hierarchy import get_project_chain_ids
from app.services.rbac import effective_org_group_ids_for_user, project_group_ids_for_user, user_satisfies_module_role

#: How many levels an element tree may be (`records.MAX_DEPTH`), plus one, so a corrupt cycle ends a walk.
_WALK_CAP = 13


@dataclass(frozen=True)
class Viewer:
    """Who is reading, and from where.

    Attributes:
        organization_id: The viewer's organisation; nothing outside it is ever visible.
        project_id: The project the viewer is working in, or `None` at the organisation level.
        user: The person, or `None` for a core hook that sees a project only.
    """

    organization_id: uuid.UUID
    project_id: uuid.UUID | None = None
    user: User | None = None

    @classmethod
    def of_user(cls, user: User, project: Project) -> Viewer:
        """A person working in `project`."""
        return cls(project.organization_id, project.id, user)

    @classmethod
    def of_project(cls, project_id: uuid.UUID, organization_id: uuid.UUID) -> Viewer:
        """A project with no person (the routes a person's identity cannot change)."""
        return cls(organization_id, project_id, None)

    @classmethod
    def of_organization(cls, user: User, organization_id: uuid.UUID) -> Viewer:
        """A person at the organisation level."""
        return cls(organization_id, None, user)


def _ancestors(db: Session, element_ids: Iterable[uuid.UUID]):
    """A recursive query of `(start, node)` pairs: each element with itself and every ancestor."""
    walk = select(
        ArchitectureElement.id.label("start"), ArchitectureElement.id.label("node"),
        ArchitectureElement.parent_id.label("parent"), literal(1, Integer).label("depth"),
    ).where(ArchitectureElement.id.in_(list(element_ids))).cte("architecture_ancestors", recursive=True)
    step = select(walk.c.start, ArchitectureElement.id, ArchitectureElement.parent_id, walk.c.depth + 1).join(
        ArchitectureElement, ArchitectureElement.id == walk.c.parent,
    ).where(walk.c.depth < _WALK_CAP)
    return walk.union_all(step)


def ancestor_parents(db: Session, element_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID | None]:
    """`{element id: its parent id}` for the given elements and every ancestor of them (one recursive query).

    A root maps to `None`. It reads the tree only and applies no visibility rule: a caller uses it for elements it
    has already checked, and an element's ancestors always share its owner.
    """
    wanted = list(element_ids)
    if not wanted:
        return {}
    walk = _ancestors(db, wanted)
    return {node: parent for node, parent in db.execute(select(walk.c.node, walk.c.parent).distinct())}


def is_shared_out(db: Session, element_id: uuid.UUID) -> bool:
    """Whether the element is shared with anyone: it, or an ancestor, is in a collection that has a grant."""
    walk = _ancestors(db, [element_id])
    return db.scalar(
        select(ArchitectureCollectionGrant.id)
        .join(ArchitectureCollectionMember, ArchitectureCollectionMember.collection_id == ArchitectureCollectionGrant.collection_id)
        .join(walk, walk.c.node == ArchitectureCollectionMember.element_id).limit(1)
    ) is not None


def descendant_ids(db: Session, roots: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The given elements and every element below them (one recursive query)."""
    wanted = list(roots)
    if not wanted:
        return set()
    walk = select(ArchitectureElement.id.label("node"), literal(1, Integer).label("depth")).where(
        ArchitectureElement.id.in_(wanted),
    ).cte("architecture_descendants", recursive=True)
    step = select(ArchitectureElement.id, walk.c.depth + 1).join(
        ArchitectureElement, ArchitectureElement.parent_id == walk.c.node,
    ).where(walk.c.depth < _WALK_CAP)
    return set(db.scalars(select(walk.union_all(step).c.node)))


def _grantee_matcher(db: Session, viewer: Viewer):
    """A function `(grant) -> bool`: whether a grant reaches the viewer (their project chain, their groups)."""
    chain = get_project_chain_ids(db, viewer.project_id) if viewer.project_id is not None else []
    direct = chain[:1]
    inherited = set(chain[1:])
    org_groups: frozenset[uuid.UUID] = (
        effective_org_group_ids_for_user(db, viewer.user.id) if viewer.user is not None else frozenset()
    )
    project_groups: dict[uuid.UUID, set[uuid.UUID]] = {}

    def project_group_ids(project_id: uuid.UUID) -> set[uuid.UUID]:
        if project_id not in project_groups:
            project_groups[project_id] = project_group_ids_for_user(db, viewer.user.id, project_id) if viewer.user else set()
        return project_groups[project_id]

    group_projects: dict[uuid.UUID, uuid.UUID] = {}

    def matches(grant: ArchitectureCollectionGrant) -> bool:
        if grant.project_id is not None:
            return grant.project_id in direct or (grant.include_descendants and grant.project_id in inherited)
        if viewer.user is None or grant.group_id is None:
            return False
        if grant.group_type == PrincipalType.ORG_GROUP.value:
            return grant.group_id in org_groups
        if grant.group_type == PrincipalType.PROJECT_GROUP.value:
            if grant.group_id not in group_projects:
                project_id = db.scalar(select(ProjectGroup.project_id).where(ProjectGroup.id == grant.group_id))
                if project_id is None:
                    return False
                group_projects[grant.group_id] = project_id
            return grant.group_id in project_group_ids(group_projects[grant.group_id])
        return False

    return matches


def _granted_collection_ids(db: Session, viewer: Viewer, collection_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The collections among `collection_ids` that are granted to the viewer (owned within the viewer's organisation)."""
    if not collection_ids:
        return set()
    in_organization = {
        collection_id for collection_id, org_id, project_org_id in db.execute(
            select(ArchitectureCollection.id, ArchitectureCollection.organization_id, Project.organization_id)
            .outerjoin(Project, Project.id == ArchitectureCollection.project_id)
            .where(ArchitectureCollection.id.in_(collection_ids))
        ).all() if (org_id or project_org_id) == viewer.organization_id
    }
    if not in_organization:
        return set()
    matches = _grantee_matcher(db, viewer)
    grants = db.scalars(select(ArchitectureCollectionGrant).where(
        ArchitectureCollectionGrant.collection_id.in_(in_organization),
    )).all()
    return {g.collection_id for g in grants if matches(g)}


def _by_collection_grant(db: Session, viewer: Viewer, element_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The elements among `element_ids` that a collection granted to the viewer contains, directly or through an
    ancestor."""
    if not element_ids:
        return set()
    walk = _ancestors(db, element_ids)
    pairs = db.execute(
        select(walk.c.start, ArchitectureCollectionMember.collection_id).join(
            ArchitectureCollectionMember, ArchitectureCollectionMember.element_id == walk.c.node,
        )
    ).all()
    granted = _granted_collection_ids(db, viewer, {collection for _start, collection in pairs})
    return {start for start, collection in pairs if collection in granted}


def visible_element_ids(db: Session, viewer: Viewer, element_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The ids among `element_ids` the viewer may read; an unknown id, or one hidden from the viewer, is absent.

    The own-project check runs first and is free; the other routes are tried only for what remains.
    """
    wanted = set(element_ids)
    if not wanted:
        return set()
    rows = db.execute(
        select(
            ArchitectureElement.id, ArchitectureElement.project_id, ArchitectureElement.organization_id,
            Project.organization_id,
        ).outerjoin(Project, Project.id == ArchitectureElement.project_id).where(ArchitectureElement.id.in_(wanted))
    ).all()
    found: set[uuid.UUID] = set()
    remaining: dict[uuid.UUID, tuple[uuid.UUID | None, uuid.UUID | None]] = {}
    for element_id, project_id, element_org, project_org in rows:
        if (element_org or project_org) != viewer.organization_id:
            continue
        if project_id is not None and project_id == viewer.project_id:
            found.add(element_id)
        else:
            remaining[element_id] = (project_id, element_org)
    if not remaining:
        return found

    if viewer.user is not None:
        open_projects: dict[uuid.UUID, bool] = {}
        for element_id, (project_id, _org) in remaining.items():
            if project_id is not None:
                if project_id not in open_projects:
                    open_projects[project_id] = can_open_project(db, viewer.user.id, project_id) and (
                        is_module_enabled_for_project(db, project_id, ARCHITECTURE_MODULE_KEY)
                    )
                if open_projects[project_id]:
                    found.add(element_id)
        if any(org is not None for _project, org in remaining.values()) and is_architecture_org_admin(
            db, viewer.user, viewer.organization_id,
        ):
            found |= {element_id for element_id, (_project, org) in remaining.items() if org is not None}

    pending = set(remaining) - found
    return found | _by_collection_grant(db, viewer, pending)


def is_architecture_org_admin(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    """Whether the person holds `architecture_org_admin` (organisation admin and server admin compose with it)."""
    return user_satisfies_module_role(
        db, user, ARCHITECTURE_MODULE_KEY, ARCHITECTURE_ORG_ADMIN_ROLE, organization_id=organization_id, project_id=None,
    )


def can_view_element(db: Session, viewer: Viewer, element_id: uuid.UUID) -> bool:
    """Whether the viewer may read one element."""
    return element_id in visible_element_ids(db, viewer, [element_id])


def granted_element_ids(db: Session, viewer: Viewer) -> set[uuid.UUID]:
    """Every element the viewer reaches through a collection grant (members and everything below them), in the
    viewer's organisation and not owned by the viewer's project: what has been shared with them.
    """
    chain = get_project_chain_ids(db, viewer.project_id) if viewer.project_id is not None else []
    candidates = {
        g.collection_id for g in db.scalars(select(ArchitectureCollectionGrant).where(
            ArchitectureCollectionGrant.project_id.in_(chain) | ArchitectureCollectionGrant.group_id.is_not(None)
        ))
    }
    granted = _granted_collection_ids(db, viewer, candidates)
    if not granted:
        return set()
    roots = set(db.scalars(select(ArchitectureCollectionMember.element_id).where(
        ArchitectureCollectionMember.collection_id.in_(granted),
    )))
    everything = descendant_ids(db, roots)
    if viewer.project_id is None or not everything:
        return everything
    own = set(db.scalars(select(ArchitectureElement.id).where(
        ArchitectureElement.id.in_(everything), ArchitectureElement.project_id == viewer.project_id,
    )))
    return everything - own
