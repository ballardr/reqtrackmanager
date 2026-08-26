"""
Module: services.project_hierarchy

Structural helpers for the parent/child project tree
(`Project.parent_project_id`, unlimited depth): cycle prevention, ancestor/
descendant walks, tree building for `GET /projects/tree`, and the
action-type fallback resolution (`resolve_effective_action_types`).

Deliberately separate from `services.rbac`, which owns the two RBAC-cascade
mechanisms (`role_inheritance_mode` forward resolution and the
`ProjectMemberSource` reverse/member-source resolution) — those need the
project-tree structure this module provides, but this module has no RBAC
knowledge of its own. See `docs/decisions.md`'s "Hierarchical projects"
entry for the full design, including why forward inheritance and the
member-source mechanism are kept fully decoupled from each other.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
from app.models.project import Project

# Defensive circuit-breaker for the iterative walks below — several
# thousand nodes is far beyond any realistic project tree, so this should
# never actually trip; it exists purely to bound worst-case query cost
# against a pathological tree rather than to limit modelled depth, which is
# unlimited by design.
_PROJECT_TREE_ITERATION_CAP = 5000


def get_descendant_project_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Returns every project (transitively) nested under `project_id`,
    walking `Project.parent_project_id` downward. Used by
    `would_create_project_cycle`."""
    visited: set[UUID] = set()
    frontier = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_TREE_ITERATION_CAP:
        iterations += 1
        children = set(
            db.scalars(select(Project.id).where(Project.parent_project_id.in_(frontier))).all()
        )
        new = children - visited
        if not new:
            break
        visited.update(new)
        frontier = new
    return visited


def would_create_project_cycle(db: Session, project_id: UUID, new_parent_id: UUID) -> bool:
    """True if setting `project_id`'s parent to `new_parent_id` would create
    a cycle — either they're the same project (self-parenting), or
    `new_parent_id` is already reachable as a descendant of `project_id`
    (i.e. `project_id` already, transitively, contains `new_parent_id`, so
    adding the reverse edge would close a loop). Mirrors
    `services.rbac.would_create_org_group_cycle` exactly. Only relevant when
    reparenting an *existing* project — a brand-new project has no children
    yet, so it cannot create a cycle by definition.
    """
    if project_id == new_parent_id:
        return True
    return new_parent_id in get_descendant_project_ids(db, project_id)


def get_ancestor_chain(db: Session, project_id: UUID) -> list[Project]:
    """Returns `project_id`'s ancestors, root-first, walking
    `Project.parent_project_id` upward. No accessibility filtering — the
    caller (`GET /{id}/ancestors`) truncates at the first ancestor the
    requesting user can't view, rather than skipping over it and continuing
    further up, so a partially-visible chain never looks contiguous when
    it isn't.
    """
    chain: list[Project] = []
    visited: set[UUID] = {project_id}
    current_id = project_id
    iterations = 0
    while iterations < _PROJECT_TREE_ITERATION_CAP:
        iterations += 1
        current = db.get(Project, current_id)
        if current is None or current.parent_project_id is None or current.parent_project_id in visited:
            break
        parent = db.get(Project, current.parent_project_id)
        if parent is None:
            break
        chain.append(parent)
        visited.add(parent.id)
        current_id = parent.id
    chain.reverse()
    return chain


def resolve_effective_action_types(db: Session, project_id: UUID) -> list[ActionTypeDefinition]:
    """Returns the action types a project should offer when creating a
    requirement action: its own, if it has any, else the nearest ancestor's
    (walking `Project.parent_project_id` upward), else an empty list at an
    unconfigured root.

    Always on, independent of `role_inheritance_mode`/`ProjectMemberSource`
    — a purely structural fallback, not gated by either RBAC mechanism (see
    `docs/decisions.md`). Does not check the caller's access to the parent:
    this only ever runs in the context of an endpoint that has already
    checked the caller's access to `project_id` itself
    (`require_project_view`/`require_project_manage`), and it never returns
    the parent's identity, just its action-type rows for use within the
    child — a deliberate, accepted, and documented trade-off (a broader
    audience than the parent's own could see the parent's action-type
    *names* through a more-visible child; low-sensitivity metadata, not
    content).
    """
    visited: set[UUID] = set()
    current_id: UUID | None = project_id
    iterations = 0
    while current_id is not None and current_id not in visited and iterations < _PROJECT_TREE_ITERATION_CAP:
        iterations += 1
        visited.add(current_id)
        own = db.scalars(
            select(ActionTypeDefinition)
            .where(ActionTypeDefinition.project_id == current_id)
            .order_by(ActionTypeDefinition.sort_order)
        ).all()
        if own:
            return list(own)
        current_id = db.scalar(select(Project.parent_project_id).where(Project.id == current_id))
    return []


def build_project_tree(db: Session, organization_id: UUID, accessible_ids: set[UUID]) -> list[dict]:
    """Builds the nested tree structure for `GET /projects/tree`, restricted
    to `accessible_ids` (the caller's accessible-project-id set for this
    organisation, computed the same way `list_projects` does). A node whose
    real parent isn't in `accessible_ids` is rendered as a root here, never
    omitted or annotated as having a hidden parent.

    Fetches the org's entire accessible project set in one query and builds
    the tree in Python — realistic org project counts make a recursive CTE
    unnecessary here (unlike the RBAC walks in `services.rbac`, which run
    on every request and do warrant one).

    Returns a list of dicts shaped like `ProjectTreeNodeOut` (not the
    Pydantic model itself, to keep this module free of a schemas
    dependency) — the router wraps the result with
    `ProjectTreeNodeOut.model_validate`.
    """
    projects = db.scalars(
        select(Project).where(Project.organization_id == organization_id, Project.id.in_(accessible_ids))
    ).all()
    by_id = {p.id: p for p in projects}

    def node(p: Project) -> dict:
        return {
            "id": p.id,
            "name": p.name,
            "organization_id": p.organization_id,
            "is_archived": p.is_archived,
            "children": [],
        }

    nodes = {p.id: node(p) for p in projects}
    roots: list[dict] = []
    for p in projects:
        if p.parent_project_id is not None and p.parent_project_id in by_id:
            nodes[p.parent_project_id]["children"].append(nodes[p.id])
        else:
            roots.append(nodes[p.id])
    return roots
